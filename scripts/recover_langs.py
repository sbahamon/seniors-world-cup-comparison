# /// script
# requires-python = ">=3.11"
# dependencies = ["requests", "lxml"]
# ///
"""Recover QIDs for redlinked youth players from non-English Wikipedias.

The idea. A QID is language-independent, but we only ever resolved them from
English article links. Other wikis keep their own squad pages for the same
editions, and a player who is a redlink on en.wiki is often blue on their home
wiki -- which hands us the QID directly. The squad page itself asserts
membership, and the local article link gives the identity key, so this is the
opposite of the RSSSF path: a roster *with* an identity key. The join that makes
this project trustworthy is unchanged, only sourced from more pages.

Three design choices carry the safety of this script.

1. **Parse rendered HTML, not wikitext.** Ten wikis means ten template
   dialects: `Jugador de fútbol` (es), `СФВм` (ru), `Mftk-g-futbolcu` (tr),
   `サッカーナショナルチーム選手一覧 選手` (ja), raw wikitables (de, fr), and
   Korean pages that are nothing but per-team transclusions. Rendered HTML
   collapses all of that, because every dialect is a fork of one visual squad
   table -- and MediaWiki expands the Korean transclusions for us.

2. **Identify federations by QID overlap, never by reading the local header.**
   CLAUDE.md already rules out hand-maintained country-code maps, and a map of
   country names across ten languages would be far worse. Instead a local
   section is matched to the en.wiki squad it shares the most QIDs with. This is
   language-independent and self-validating: if we were scraping club links
   instead of player links, nothing would match and the section would be
   dropped, loudly, rather than silently attributed to the wrong federation.

3. **Attach by verified shirt-number concordance, not by name.** Korean and
   Arabic names share no characters with their English forms, so name
   similarity is unavailable exactly where it is most needed. Shirt numbers are
   unique inside a squad, and -- crucially -- the players we *already* matched
   by QID let us check that the two wikis agree on the numbering before we
   trust it for anyone else. Fewer than MIN_ANCHORS agreeing players, or any
   disagreement among them, and number-based attachment is refused for that
   squad.

Writes data/squads_recovered.csv (staging; the diff against data/squads.csv must
be purely additive), data/lang_recovery.csv, data/lang_format_variants.csv and
data/lang_integrity_flags.csv. It never writes data/squads.csv -- ingest.py owns
that path.

    uv run scripts/recover_langs.py
"""
from __future__ import annotations

import csv
import difflib
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from lxml import html as lxml_html

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fetch_page import api_get_host, api_post_host  # noqa: E402
from ingest import EXPECTED_TEAMS, SQUAD_BAND, SQUAD_MODE_TOLERANCE, canon_team  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

# --- attachment thresholds -------------------------------------------------
# A section must share this many QIDs with an en.wiki squad before we will call
# it that federation, and must beat the runner-up by this factor. Both are
# deliberately strict: a mis-identified section would attribute one country's
# players to another, which is the worst error available here.
MIN_TEAM_ANCHORS = 3
TEAM_MARGIN = 2.0

# Shirt-number attachment needs this many players already matched by QID, all
# of them agreeing on the number, before the numbering is trusted for the rest.
MIN_ANCHORS = 3
ANCHOR_CONCORDANCE = 1.0

# Name-similarity attachment, used when numbers are unavailable on one side.
NAME_SIM = 0.84
NAME_MARGIN = 0.08

SKIP_LINK_PREFIX = re.compile(
    r"^(File|Image|Media|Category|Template|Help|Portal|Wikipedia|Special|"
    r"Archivo|Categoría|Plantilla|Anexo|Файл|Категория|Шаблон|ملف|تصنيف|قالب|"
    r"Datei|Kategorie|Vorlage|Fichier|Catégorie|Modèle|ファイル|Category|"
    r"분류|틀|Tập tin|Thể loại|Bản mẫu|Fayl|Turkum|Andoza|Dosya|Kategori|Şablon)"
    r"\s*:", re.IGNORECASE)


def fold(name: str) -> str:
    d = unicodedata.normalize("NFKD", name)
    s = "".join(c for c in d if not unicodedata.combining(c))
    return " ".join("".join(c for c in s.lower() if c.isalnum() or c == " ").split())


def name_sim(a: str, b: str) -> float:
    """Similarity over folded names, rewarding shared surname tokens.

    Squad pages disagree constantly on how much of a name to print -- "Eva
    Navarro" against "Eva Navarro Ramírez" -- so a plain ratio under-scores
    correct pairs. Token overlap covers that; the sequence ratio covers
    transliteration drift.
    """
    fa, fb = fold(a), fold(b)
    if not fa or not fb:
        return 0.0
    ratio = difflib.SequenceMatcher(None, fa, fb).ratio()
    ta, tb = set(fa.split()), set(fb.split())
    jacc = len(ta & tb) / len(ta | tb) if ta | tb else 0.0
    return max(ratio, 0.5 * ratio + 0.5 * jacc)


# --------------------------------------------------------------------------
# rendered-HTML squad extraction
# --------------------------------------------------------------------------

@dataclass
class LocalPlayer:
    shirt_no: str
    article: str          # local-wiki article title
    display: str          # link text as rendered
    birth_year: str
    ordinal: int          # position within the section's listing
    qid: str = ""


@dataclass
class LocalRow:
    shirt_no: str
    cells: dict[int, list[tuple[str, str]]]  # cell index -> (title, text) links
    birth_year: str


@dataclass
class LocalSection:
    heading: str
    rows: list[LocalRow] = field(default_factory=list)
    players: list[LocalPlayer] = field(default_factory=list)
    cell_idx: int = -1


YEAR_RE = re.compile(r"(?<!\d)(19[7-9]\d|200\d|201\d)(?!\d)")
INT_RE = re.compile(r"^\s*(\d{1,2})\s*$")


def cell_links(cell) -> list[tuple[str, str]]:
    """(title, text) for real article links in a cell, flags and files dropped."""
    out = []
    for a in cell.iter("a"):
        title = a.get("title") or ""
        href = a.get("href") or ""
        cls = a.get("class") or ""
        if not title or "new" in cls.split() or "redlink=1" in href:
            continue  # a redlink here is no better than a redlink on en.wiki
        if not href.startswith("/wiki/") or SKIP_LINK_PREFIX.match(title):
            continue
        if a.find("img") is not None and not (a.text_content() or "").strip():
            continue  # flag icon
        out.append((title, (a.text_content() or "").strip()))
    return out


MAX_CELL_IDX = 8      # columns past this are statistics, never the player
MIN_COLUMN_ROWS = 5   # a column seen in fewer rows than this is not a column


def choose_player_column(section: LocalSection, qids: dict[str, str],
                         en_by_team: dict[str, list[dict]]
                         ) -> tuple[int, str | None, int, int]:
    """Which column holds the player, and which federation is this?

    Answered together, from evidence, because they are the same question. The
    first attempt at this took "the first link in the row" as the player, which
    on Spanish pages is the *position* -- `[[Guardameta|POR]]` -- and on others
    would be the club. Guessing a column order across ten wikis is not
    something to be clever about.

    So: score every candidate column against every federation's en.wiki squad
    by shared QIDs, and take the best pair. Positions and clubs score zero
    against a list of footballers, so the player column wins by construction,
    and a page we are reading wrongly produces no winner rather than a wrong
    one.
    """
    counts: Counter = Counter()
    for row in section.rows:
        for idx in row.cells:
            counts[idx] += 1
    best = (0, -1, None, 0)  # score, cell index, team, runner-up
    for idx, n in counts.items():
        if idx > MAX_CELL_IDX or n < MIN_COLUMN_ROWS:
            continue
        col_qids = {qids[t] for row in section.rows
                    for t, _ in row.cells.get(idx, []) if t in qids}
        if not col_qids:
            continue
        scores = sorted(
            ((len(col_qids & {r["player_qid"] for r in rows if r["player_qid"]}), team)
             for team, rows in en_by_team.items()), reverse=True)
        top = scores[0]
        second = scores[1][0] if len(scores) > 1 else 0
        if top[0] > best[0]:
            best = (top[0], idx, top[1], second)
    score, idx, team, second = best
    if score < MIN_TEAM_ANCHORS or (second and score < second * TEAM_MARGIN):
        return idx, None, score, second
    return idx, team, score, second


def extract_sections(doc) -> list[LocalSection]:
    """Walk the rendered page in document order, tables grouped under headings.

    Each row keeps every article link it carries, indexed by which cell it came
    from. Deciding which of those cells is the player is deferred to
    choose_player_column, which does it from evidence rather than from a guess
    about column order.
    """
    sections: list[LocalSection] = []
    current = LocalSection(heading="(lead)")
    sections.append(current)

    for el in doc.iter():
        tag = el.tag if isinstance(el.tag, str) else ""
        if tag in ("h1", "h2", "h3", "h4", "h5"):
            text = " ".join((el.text_content() or "").split())
            text = re.sub(r"\[\s*edit\s*\]$", "", text, flags=re.I).strip()
            current = LocalSection(heading=text or "(unnamed)")
            sections.append(current)
            continue
        if tag != "tr":
            continue
        cells = [c for c in el if isinstance(c.tag, str) and c.tag in ("td", "th")]
        if len(cells) < 2:
            continue  # position band row ("Goalkeepers"), or a header row
        shirt = ""
        m = INT_RE.match(" ".join((cells[0].text_content() or "").split()))
        if m:
            shirt = m.group(1)
        per_cell = {i: links for i, c in enumerate(cells) if (links := cell_links(c))}
        if not per_cell:
            continue
        row_text = " ".join((el.text_content() or "").split())
        years = YEAR_RE.findall(row_text)
        current.rows.append(LocalRow(shirt_no=shirt, cells=per_cell,
                                     birth_year=years[-1] if years else ""))
    return [s for s in sections if s.rows]


CACHE = ROOT / ".cache" / "lang"


def _cache_path(host: str, title: str, kind: str) -> Path:
    import hashlib
    key = hashlib.sha1(f"{host}|{title}".encode()).hexdigest()[:16]
    return CACHE / f"{key}.{kind}"


def fetch_html(host: str, title: str):
    """Rendered HTML for a local squad page, cached on disk.

    Fetching this corpus is ~40 page renders plus ~700 pageprops batches at one
    request per second. The cache is here so a change to the *matching* logic
    can be re-run in seconds instead of re-spending twenty minutes of someone
    else's rate limit for bytes we already have. Delete .cache/ to force a
    refetch.
    """
    CACHE.mkdir(parents=True, exist_ok=True)
    path = _cache_path(host, title, "html")
    if path.exists():
        return lxml_html.fromstring(path.read_text(encoding="utf-8"))
    resp = api_get_host(host, {
        "action": "parse", "page": title, "prop": "text",
        "format": "json", "formatversion": "2", "redirects": "1",
    }, timeout=60)
    data = resp.json()
    if "error" in data:
        raise RuntimeError(f"{host} {title!r}: {data['error']}")
    path.write_text(data["parse"]["text"], encoding="utf-8")
    return lxml_html.fromstring(data["parse"]["text"])


def resolve_local_qids(host: str, titles: list[str]) -> dict[str, str]:
    """Local article title -> QID, via that wiki's own pageprops.

    Same one-request trick ingest.py uses on en.wiki: prop=pageprops carries
    wikibase_item, so no wikidata.org egress is needed and redirects resolve in
    the same call. A local article with no Wikidata item yields nothing -- there
    is no title fallback here, because a local title is not a key our corpus
    shares.
    """
    out: dict[str, str] = {}
    uniq = sorted({t for t in titles if t})
    CACHE.mkdir(parents=True, exist_ok=True)
    path = _cache_path(host, "|".join(uniq), "qids")
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    for i in range(0, len(uniq), 50):
        batch = uniq[i:i + 50]
        data = api_post_host(host, {
            "action": "query", "titles": "|".join(batch), "prop": "pageprops",
            "ppprop": "wikibase_item", "redirects": "1",
            "format": "json", "formatversion": "2",
        }, timeout=60).json().get("query", {})
        chain: dict[str, str] = {}
        for key in ("normalized", "redirects"):
            for e in data.get(key, []):
                chain[e["from"]] = e["to"]
        pages = {p["title"]: p for p in data.get("pages", [])}
        for t in batch:
            cur, seen = t, set()
            while cur in chain and cur not in seen:
                seen.add(cur)
                cur = chain[cur]
            page = pages.get(cur, {})
            if page.get("missing"):
                continue
            qid = page.get("pageprops", {}).get("wikibase_item", "")
            if qid:
                out[t] = qid
    path.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    return out


# --------------------------------------------------------------------------
# matching
# --------------------------------------------------------------------------

@dataclass
class Flag:
    tournament_id: str
    lang: str
    page_title: str
    team: str
    check: str
    severity: str
    expected: str
    observed: str
    detail: str


def fill_players(section: LocalSection, qids: dict[str, str]) -> None:
    """Materialise the section's squad from its chosen player column.

    A name cell can hold more than one link: the player, plus a captaincy
    marker like `[[Captain (association football)|(c)]]`. When the player
    themself is a redlink, the marker is the only link left and taking "the
    first link" quietly recovers the *article about captaincy* as a footballer.
    Two of those got through before this rule existed.

    The rule that removes them needs no vocabulary and no language: one person
    appears once in a squad, so any link target repeated within the section is
    not a player.
    """
    repeated = {t for t, n in Counter(
        t for row in section.rows for t, _ in row.cells.get(section.cell_idx, [])
    ).items() if n > 1}
    section.players = []
    for row in section.rows:
        links = [(t, x) for t, x in row.cells.get(section.cell_idx, [])
                 if t not in repeated]
        if not links:
            continue  # redlinked on this wiki too; nothing to recover
        title, text = links[0]
        section.players.append(LocalPlayer(
            shirt_no=row.shirt_no, article=title, display=text or title,
            birth_year=row.birth_year, ordinal=len(section.players),
            qid=qids.get(title, ""),
        ))


def attach(section: LocalSection, en_rows: list[dict], acc: Counter,
           used_qids: set[str]) -> tuple[list[dict], list[str]]:
    """Attach new QIDs to unresolved en.wiki rows. Returns (recoveries, notes).

    `used_qids` is every QID already standing against this squad -- the ones
    en.wiki had plus anything a previous language page contributed. One person
    cannot occupy two rows of one squad, so a QID that is already spoken for is
    refused rather than duplicated. Two such collisions did occur before this
    guard existed, both from a local page listing the same article twice.
    """
    notes: list[str] = []
    en_qids = {r["player_qid"] for r in en_rows if r["player_qid"]}
    by_qid = {r["player_qid"]: r for r in en_rows if r["player_qid"]}

    # 1. concordance: do the two wikis agree on shirt numbers for the players
    #    they already share? Nothing number-based is trusted until they do.
    anchors = [(p, by_qid[p.qid]) for p in section.players
               if p.qid and p.qid in by_qid]
    numbered = [(lp, er) for lp, er in anchors if lp.shirt_no and er["shirt_no"]]
    agree = sum(1 for lp, er in numbered if lp.shirt_no.lstrip("0") == er["shirt_no"].lstrip("0"))
    conc = (agree / len(numbered)) if numbered else 0.0
    numbers_ok = len(numbered) >= MIN_ANCHORS and conc >= ANCHOR_CONCORDANCE
    if numbered and not numbers_ok:
        notes.append(f"shirt-number concordance {agree}/{len(numbered)} - numbers not trusted")
        acc["shirt_numbers_disagree"] += 1

    open_rows = [r for r in en_rows if not r["player_qid"]]
    taken: set[int] = set()
    recoveries: list[dict] = []

    for lp in section.players:
        if not lp.qid or lp.qid in used_qids:
            continue  # unknown on the local wiki too, or already on this squad
        cands = [r for i, r in enumerate(open_rows) if i not in taken]
        if not cands:
            continue

        target, method, score = None, "", 0.0
        if numbers_ok and lp.shirt_no:
            hit = [r for r in cands
                   if r["shirt_no"] and r["shirt_no"].lstrip("0") == lp.shirt_no.lstrip("0")]
            if len(hit) == 1:
                target, method, score = hit[0], "shirt_number", 1.0

        if target is None:
            scored = sorted(((name_sim(lp.display, r["display_name"]), r) for r in cands),
                            key=lambda t: -t[0])
            if scored and scored[0][0] >= NAME_SIM:
                runner = scored[1][0] if len(scored) > 1 else 0.0
                if scored[0][0] - runner >= NAME_MARGIN:
                    target, method, score = scored[0][1], "name", scored[0][0]

        if target is None:
            # Last resort, and only when neither wiki numbered its squad: the
            # listing order itself. Kept because CLAUDE.md's rule is never to
            # drop anything silently -- this is logged either way.
            if not numbers_ok and not any(r["shirt_no"] for r in en_rows) \
                    and lp.ordinal < len(cands):
                target, method, score = cands[lp.ordinal], "ordinal", 0.0
        if target is None:
            acc["unattached_local_player"] += 1
            continue

        # birth-year veto: both sides know it and they disagree by more than a
        # year. Squad pages differ on whether they print the DOB or the age, so
        # one year of slack is the honest tolerance.
        if lp.birth_year and target["birth_year"]:
            if abs(int(lp.birth_year) - int(target["birth_year"])) > 1:
                acc["birth_year_veto"] += 1
                notes.append(f"birth-year veto {lp.display} {lp.birth_year} "
                             f"vs {target['display_name']} {target['birth_year']}")
                continue

        taken.add(open_rows.index(target))
        used_qids.add(lp.qid)
        recoveries.append({"row": target, "qid": lp.qid, "method": method,
                           "score": f"{score:.2f}", "local_article": lp.article,
                           "local_display": lp.display})
        acc[f"attached_by_{method}"] += 1
    return recoveries, notes


# --------------------------------------------------------------------------
# integrity, same shape as ingestion -- the dialects are new, so these are
# load-bearing again
# --------------------------------------------------------------------------

def check_page(tid: str, lang: str, title: str, level: str, gender: str, year: int,
               matched: dict[str, LocalSection], unmatched: list[LocalSection]) -> list[Flag]:
    flags: list[Flag] = []
    expected = EXPECTED_TEAMS.get((level, gender, year))
    if expected is not None and len(matched) != expected:
        flags.append(Flag(tid, lang, title, "", "team_count", "error", str(expected),
                          str(len(matched)),
                          f"matched: {', '.join(sorted(matched))}"))
    for s in unmatched:
        flags.append(Flag(tid, lang, title, "", "unmatched_section", "warn", "matched",
                          "unmatched",
                          f"heading {s.heading!r}, {len(s.rows)} rows"))
    # Size checks measure the section's full row count, not the linked subset.
    # The linked subset is *supposed* to be short -- that shortfall is the
    # coverage gap we are here to close -- so checking it against a 18-23 band
    # would flag every well-parsed page on this wiki and hide the real defect,
    # which is a page whose squads are the wrong length in the first place.
    lo, hi = SQUAD_BAND[level]
    for team, s in sorted(matched.items()):
        if not (lo <= len(s.rows) <= hi):
            flags.append(Flag(tid, lang, title, team, "squad_size_band", "error",
                              f"{lo}-{hi}", str(len(s.rows)),
                              "local squad size outside the plausible band"))
    sizes = Counter(len(s.rows) for s in matched.values())
    if sizes:
        mode, mode_n = sizes.most_common(1)[0]
        if mode_n > 1:
            for team, s in sorted(matched.items()):
                d = abs(len(s.rows) - mode)
                if d:
                    flags.append(Flag(
                        tid, lang, title, team, "squad_size_vs_edition",
                        "error" if d > SQUAD_MODE_TOLERANCE else "warn",
                        str(mode), str(len(s.rows)),
                        f"{d} off this page's modal squad size "
                        f"({mode_n} of {len(matched)} squads are {mode})"))
    return flags


# --------------------------------------------------------------------------

RECOVERY_FIELDS = ["tournament_id", "level", "gender", "year", "team", "lang",
                   "page_title", "shirt_no", "display_name", "recovered_qid",
                   "method", "score", "local_article", "local_display"]
FLAG_FIELDS = ["tournament_id", "lang", "page_title", "team", "check", "severity",
               "expected", "observed", "detail"]
VARIANT_FIELDS = ["tournament_id", "lang", "page_title", "variant", "count"]
SQUAD_FIELDS = ["tournament_id", "level", "gender", "year", "team", "shirt_no",
                "position", "player_article", "player_qid", "display_name",
                "source_url", "birth_year"]


def write_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"  wrote {path.relative_to(ROOT)} ({len(rows)} rows)")


def main() -> int:
    targets = json.loads((DATA / "lang_targets_selected.json").read_text())
    squads = list(csv.DictReader((DATA / "squads.csv").open(encoding="utf-8")))
    en: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for r in squads:
        en[r["tournament_id"]][r["team"]].append(r)

    recoveries: list[dict] = []
    flags: list[Flag] = []
    variants: list[dict] = []
    assigned: dict[tuple, str] = {}          # one recovery per en.wiki row
    used_qids: dict[tuple, set[str]] = {}    # one QID per person per squad

    for t in targets:
        tid, lang, title = t["tournament_id"], t["lang"], t["title"]
        host = f"{lang}.wikipedia.org"
        acc: Counter = Counter()
        print(f"\n{tid} [{lang}]  {title}")
        try:
            doc = fetch_html(host, title)
            sections = extract_sections(doc)
        except Exception as exc:  # noqa: BLE001
            print(f"  FETCH/PARSE FAILURE: {exc!r}")
            flags.append(Flag(tid, lang, title, "", "fetch_failed", "error", "ok",
                              "failed", repr(exc)))
            continue

        # Every candidate column is resolved, not just a guessed one -- the
        # column choice below is made on QIDs, so it needs them all first.
        cand_titles = [t for s in sections for row in s.rows
                       for idx, links in row.cells.items() if idx <= MAX_CELL_IDX
                       for t, _ in links]
        qids = resolve_local_qids(host, cand_titles)
        acc["local_links_examined"] = len(set(cand_titles))
        acc["local_links_with_qid"] = len(qids)

        en_by_team = en.get(tid, {})
        level, gender, year = next(
            (r["level"], r["gender"], int(r["year"])) for r in squads
            if r["tournament_id"] == tid)
        matched: dict[str, LocalSection] = {}
        unmatched: list[LocalSection] = []
        for s in sections:
            idx, team, best, second = choose_player_column(s, qids, en_by_team)
            s.cell_idx = idx
            if team is None or team in matched:
                if team is not None and team in matched:
                    acc["duplicate_team_section"] += 1
                unmatched.append(s)
                continue
            fill_players(s, qids)
            acc[f"player_column_index:{idx}"] += 1
            matched[team] = s
        acc["local_linked_players"] = sum(len(s.players) for s in matched.values())
        acc["local_players_with_qid"] = sum(
            1 for s in matched.values() for p in s.players if p.qid)

        n_before = 0
        page_rec = 0
        for team, s in sorted(matched.items()):
            rows = en_by_team[team]
            used = used_qids.setdefault(
                (tid, team), {r["player_qid"] for r in rows if r["player_qid"]})
            recs, notes = attach(s, rows, acc, used)
            for note in notes:
                flags.append(Flag(tid, lang, title, team, "attach_note", "warn",
                                  "", "", note))
            for rec in recs:
                row = rec["row"]
                key = (tid, team, row["shirt_no"], row["display_name"])
                if key in assigned:
                    acc["duplicate_assignment_skipped"] += 1
                    continue
                assigned[key] = rec["qid"]
                recoveries.append({
                    "tournament_id": tid, "level": level, "gender": gender,
                    "year": year, "team": team, "lang": lang, "page_title": title,
                    "shirt_no": row["shirt_no"], "display_name": row["display_name"],
                    "recovered_qid": rec["qid"], "method": rec["method"],
                    "score": rec["score"], "local_article": rec["local_article"],
                    "local_display": rec["local_display"],
                })
                page_rec += 1
            n_before += sum(1 for r in rows if not r["player_qid"])

        flags.extend(check_page(tid, lang, title, level, gender, year, matched, unmatched))
        print(f"  sections {len(sections)}  matched {len(matched)}"
              f"{'/' + str(EXPECTED_TEAMS.get((level, gender, year))) if EXPECTED_TEAMS.get((level, gender, year)) else ''}"
              f"  local linked {acc['local_linked_players']}"
              f"  with QID {acc['local_players_with_qid']}"
              f"  -> recovered {page_rec} of {n_before} open rows")
        for k, v in sorted(acc.items()):
            variants.append({"tournament_id": tid, "lang": lang, "page_title": title,
                             "variant": k, "count": v})
        for f in flags[-6:]:
            if f.tournament_id == tid and f.lang == lang and f.severity == "error":
                print(f"  [ERROR] {f.check}: expected {f.expected}, got {f.observed}")

    # ---- staging corpus: current squads.csv plus recovered QIDs --------------
    rec_by_key: dict[tuple, dict] = {}
    for r in recoveries:
        rec_by_key[(r["tournament_id"], r["team"], r["shirt_no"], r["display_name"])] = r
    staged: list[dict] = []
    for r in squads:
        out = dict(r)
        key = (r["tournament_id"], r["team"], r["shirt_no"], r["display_name"])
        hit = rec_by_key.get(key)
        if hit and not r["player_qid"]:
            out["player_qid"] = hit["recovered_qid"]
            out["player_article"] = f"{hit['lang']}:{hit['local_article']}"
        staged.append(out)

    print()
    write_csv(DATA / "squads_recovered.csv", SQUAD_FIELDS, staged)
    write_csv(DATA / "lang_recovery.csv", RECOVERY_FIELDS, recoveries)
    write_csv(DATA / "lang_integrity_flags.csv", FLAG_FIELDS, [vars(f) for f in flags])
    write_csv(DATA / "lang_format_variants.csv", VARIANT_FIELDS, variants)

    errs = sum(1 for f in flags if f.severity == "error")
    print(f"\nrecovered {len(recoveries)} QIDs; {errs} error-severity flags, "
          f"{len(flags) - errs} warnings")
    return 0


if __name__ == "__main__":
    sys.exit(main())
