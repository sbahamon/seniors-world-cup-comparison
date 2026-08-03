# /// script
# requires-python = ">=3.11"
# dependencies = ["requests"]
# ///
"""Discover which non-English Wikipedias carry a squad-list page per edition.

Why this exists. The interlanguage links on the *English squads* pages are
almost empty -- only ~30 (edition, language) pairs across the whole v1 corpus,
and most of those are Vietnamese. That is not evidence that other wikis lack
squad lists; it is evidence that their squad articles are not sitelinked to
ours. Spanish, for instance, keeps them under `Anexo:Equipos participantes en
la Copa Mundial de Futbol Sub-20 de 2013`, an article the English squads page
has never been linked to.

So we discover the title instead of constructing it. For each edition we take
the *main tournament* article -- which is sitelinked in ~15 languages -- follow
it to the target wiki, and read its outgoing links, looking for one that names
a squad list in that language. This respects the CLAUDE.md rule against
string-formatting a year into a title template: nothing is constructed, the
local wiki tells us what the page is called, and a rename cannot hide a page
from us.

Writes data/lang_targets.csv. Network-only; parses nothing.

    uv run scripts/probe_langs.py
"""
from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fetch_page import USER_AGENT, api_get_host  # noqa: E402
from ingest import youth_targets  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

# Words that name a squad list in each language. Matched case-insensitively
# against the link target. Deliberately generous: a false positive costs one
# fetch and then fails the integrity checks loudly, whereas a false negative
# silently forfeits a whole edition's recovery.
SQUAD_WORDS = {
    "es": ["equipos participantes", "plantillas", "convocatorias", "jugadores participantes"],
    "pt": ["equipas participantes", "equipes participantes", "elencos", "convocados",
           "jogadores", "selecoes participantes", "seleções participantes"],
    "fr": ["effectifs", "equipes participantes", "équipes participantes", "joueurs"],
    "de": ["kader", "mannschaftskader", "aufgebote"],
    "it": ["convocazioni", "rose ", "rose del", "squadre partecipanti"],
    "nl": ["selecties", "spelers"],
    "ca": ["equips participants", "plantilles"],
    "pl": ["kadry", "sklady", "składy"],
    "cs": ["soupisky", "soupisek"],
    "sv": ["trupper", "truppar"],
    "fi": ["joukkueet", "kokoonpanot", "pelaajat"],
    "da": ["trupper"],
    "no": ["tropper"],
    "tr": ["kadrolar", "kadroları", "kadrolari"],
    "ru": ["составы", "заявки"],
    "uk": ["склади", "заявки"],
    "uz": ["tarkiblari", "tarkib"],
    "ko": ["선수 명단", "선수명단", "참가 선수"],
    "ja": ["選手", "出場チーム", "参加チーム"],
    "zh": ["參賽名單", "参赛名单", "球員名單", "球员名单", "阵容", "陣容", "參賽球員", "参赛球员"],
    "ar": ["تشكيلات", "قائمة اللاعبين", "المنتخبات المشاركة", "تشكيلة"],
    "fa": ["فهرست بازیکنان", "بازیکنان", "ترکیب"],
    "he": ["סגלים"],
    "id": ["skuat", "skuad", "pemain"],
    "ms": ["skuad", "pemain"],
    "vi": ["đội hình", "danh sách cầu thủ", "cầu thủ"],
    "th": ["ผู้เล่น"],
    "el": ["αποστολές"],
    "hu": ["keretek"],
    "ro": ["loturi"],
    "hr": ["sastavi"],
    "sr": ["саставе", "sastavi"],
    "sk": ["supisky", "súpisky"],
}

# Federation -> non-English Wikipedias plausibly covering its youth players,
# home language first. Only federations that actually appear in the v1 youth
# corpus are listed. Anglophone federations are deliberately absent: English
# Wikipedia already *is* their best-covered wiki, so there is nothing to gain.
FEDERATION_LANGS = {
    "North Korea": ["ko"], "South Korea": ["ko"], "Japan": ["ja"], "China PR": ["zh"],
    "Costa Rica": ["es"], "Mexico": ["es"], "Paraguay": ["es"], "Honduras": ["es"],
    "Colombia": ["es"], "Panama": ["es"], "Venezuela": ["es"], "Uruguay": ["es"],
    "Argentina": ["es"], "Ecuador": ["es"], "Chile": ["es"], "Spain": ["es"],
    "Peru": ["es"], "Guatemala": ["es"], "El Salvador": ["es"], "Cuba": ["es"],
    "Bolivia": ["es"], "Dominican Republic": ["es"],
    "Brazil": ["pt"], "Portugal": ["pt"], "Angola": ["pt"], "Cape Verde": ["pt"],
    "Mali": ["fr"], "Cameroon": ["fr"], "Burkina Faso": ["fr"], "Ivory Coast": ["fr"],
    "Guinea": ["fr"], "Senegal": ["fr"], "France": ["fr"], "DR Congo": ["fr"],
    "Congo": ["fr"], "Benin": ["fr"], "Togo": ["fr"], "Niger": ["fr"],
    "Gabon": ["fr"], "Haiti": ["fr"], "Canada": ["fr"],
    "Belgium": ["nl", "fr"], "Switzerland": ["de", "fr"], "Netherlands": ["nl"],
    "United Arab Emirates": ["ar"], "Syria": ["ar"], "Iraq": ["ar"], "Egypt": ["ar"],
    "Tunisia": ["ar", "fr"], "Morocco": ["ar", "fr"], "Algeria": ["ar", "fr"],
    "Saudi Arabia": ["ar"], "Qatar": ["ar"], "Oman": ["ar"], "Bahrain": ["ar"],
    "Kuwait": ["ar"], "Yemen": ["ar"], "Libya": ["ar"], "Jordan": ["ar"],
    "Iran": ["fa"], "Uzbekistan": ["uz", "ru"], "Tajikistan": ["ru"],
    "Kazakhstan": ["ru"], "Russia": ["ru"], "Ukraine": ["uk", "ru"],
    "Germany": ["de"], "Austria": ["de"], "Italy": ["it"], "Finland": ["fi"],
    "Sweden": ["sv"], "Norway": ["no"], "Denmark": ["da"], "Poland": ["pl"],
    "Turkey": ["tr"], "Czech Republic": ["cs"], "Slovakia": ["sk"],
    "Croatia": ["hr"], "Serbia": ["sr"], "Hungary": ["hu"], "Romania": ["ro"],
    "Greece": ["el"], "Thailand": ["th"], "Vietnam": ["vi"], "Indonesia": ["id"],
    "Malaysia": ["ms"], "Israel": ["he"],
}

TOP_N_LANGS = 4  # languages probed per edition, ranked by recoverable redlinks


def opportunity() -> dict[str, dict[str, int]]:
    """edition -> language -> redlinks in federations that language could cover."""
    out: dict[str, dict[str, int]] = {}
    with (DATA / "squads.csv").open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r["level"] == "senior" or r["player_qid"]:
                continue
            per = out.setdefault(r["tournament_id"], {})
            for lang in FEDERATION_LANGS.get(r["team"], []):
                per[lang] = per.get(lang, 0) + 1
    return out


def main_langlinks(main_title: str) -> dict[str, str]:
    resp = api_get_host("en.wikipedia.org", {
        "action": "query", "titles": main_title, "prop": "langlinks",
        "lllimit": "500", "redirects": "1", "format": "json", "formatversion": "2",
    })
    pages = resp.json().get("query", {}).get("pages", [])
    return {l["lang"]: l["title"] for p in pages for l in p.get("langlinks", [])}


def looks_like_squad_title(title: str, lang: str, year: int) -> bool:
    """Squad-list title for *this* edition, in this language.

    The year test is load-bearing and not a shortcut around the CLAUDE.md rule
    on constructing titles. Every one of these pages sits in a navbox listing
    the whole tournament series, so an unfiltered link scrape hands back the
    1977 and 1979 squad pages for a 2013 query -- which is how you would end up
    silently attributing one edition's players to another. We still discover the
    title from the wiki; we only refuse to accept one whose year disagrees.
    """
    words = SQUAD_WORDS.get(lang, [])
    if not words or not any(w.lower() in title.lower() for w in words):
        return False
    found = {m.group(0) for m in re.finditer(r"(?<!\d)(?:19|20)\d{2}(?!\d)", title)}
    return str(year) in found


def find_squad_page(lang: str, local_main: str, year: int) -> list[str]:
    """Discover the local squad-list page: navbox links first, then search."""
    if lang not in SQUAD_WORDS:
        return []
    host = f"{lang}.wikipedia.org"
    resp = api_get_host(host, {
        "action": "query", "titles": local_main, "prop": "links",
        "plnamespace": "0|100|104",  # main + Anexo/Annex pseudo-namespaces
        "pllimit": "max", "redirects": "1", "format": "json", "formatversion": "2",
    })
    pages = resp.json().get("query", {}).get("pages", [])
    links = [l["title"] for p in pages for l in p.get("links", [])]
    hits = [t for t in links if looks_like_squad_title(t, lang, year)]
    if hits:
        return sorted(set(hits))

    # Fallback: the local wiki may have a squad page that the tournament
    # article does not link (no navbox, or the navbox predates the page). Ask
    # the wiki's own search rather than guessing a title.
    for word in SQUAD_WORDS[lang][:2]:
        resp = api_get_host(host, {
            "action": "query", "list": "search",
            "srsearch": f"{local_main} {word}", "srlimit": "20",
            "srnamespace": "0|100|104", "format": "json", "formatversion": "2",
        })
        found = [s["title"] for s in resp.json().get("query", {}).get("search", [])]
        hits = [t for t in found if looks_like_squad_title(t, lang, year)]
        if hits:
            return sorted(set(hits))
    return []


FIELDS = ["tournament_id", "level", "gender", "year", "lang", "local_main",
          "candidate_title", "recoverable_redlinks", "status"]


def main() -> int:
    opp = opportunity()
    rows: list[dict] = []
    for ed in youth_targets():
        per = opp.get(ed.tid, {})
        ranked = sorted(per.items(), key=lambda kv: -kv[1])[:TOP_N_LANGS]
        ll = main_langlinks(ed.page_title[: -len(" squads")])
        print(f"\n{ed.tid}  probing {', '.join(f'{l}({n})' for l, n in ranked)}", flush=True)
        for lang, n in ranked:
            local_main = ll.get(lang)
            if not local_main:
                print(f"    {lang}: no {lang}.wikipedia article for the tournament")
                rows.append({"tournament_id": ed.tid, "level": ed.level,
                             "gender": ed.gender, "year": ed.year, "lang": lang,
                             "local_main": "", "candidate_title": "",
                             "recoverable_redlinks": n, "status": "no_local_tournament_article"})
                continue
            hits = find_squad_page(lang, local_main, ed.year)
            if not hits:
                print(f"    {lang}: {local_main} -> no squad-list link")
                rows.append({"tournament_id": ed.tid, "level": ed.level,
                             "gender": ed.gender, "year": ed.year, "lang": lang,
                             "local_main": local_main, "candidate_title": "",
                             "recoverable_redlinks": n, "status": "no_squad_page"})
                continue
            for h in hits:
                print(f"    {lang}: {h}")
                rows.append({"tournament_id": ed.tid, "level": ed.level,
                             "gender": ed.gender, "year": ed.year, "lang": lang,
                             "local_main": local_main, "candidate_title": h,
                             "recoverable_redlinks": n, "status": "candidate"})

    DATA.mkdir(exist_ok=True)
    with (DATA / "lang_targets.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    found = [r for r in rows if r["status"] == "candidate"]
    print(f"\nwrote data/lang_targets.csv: {len(rows)} probes, "
          f"{len(found)} candidate pages across "
          f"{len({(r['tournament_id'], r['lang']) for r in found})} (edition, language) pairs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
