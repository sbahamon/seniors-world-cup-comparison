# /// script
# requires-python = ">=3.11"
# dependencies = ["requests"]
# ///
"""Parse Wikipedia squad-list wikitext into (team, player) rows.

Squad pages are NOT uniform across editions. Confirmed dialects in the wild:

  template names
    {{nat fs g player|...}}                        2013 U-17, 2015 U-17, 2018 WC, 2023 WWC
    {{nat fs player no caps|...}}                  2018 U-20 W, 2018 U-17 W, 2022 U-20 W
    {{National football squad player|...}}         2014 WC
    {{National football squad player (no caps)|..} 2018 U-17 W (some teams)

  name= values
    name=[[Article]]                               plain link
    name=[[Article|Display]]                       piped link
    name='''[[Article]]'''                         bolded (2013 U-17)
    name={{sortname|First|Last}}                   -> [[First Last]]
    name={{sortname|First|Last|dab=footballer}}    -> [[First Last (footballer)]]
    name=Plain Text                                redlink, no article to join on

  team section headers
    ===Spain===                                    plain name
    ==={{fbu|17|NGR}}===                           FIFA code (2013 U-17)
    ==={{fbu|17|NGA}}===                           IOC code for the SAME country (2015 U-17)
    ==={{fbu|17|HON|1949}}===                      trailing flag-variant year

That last pair matters: Nigeria is NGR on one page and NGA on another. A code map
missing either alias silently drops a whole squad and pushes overlap toward zero.

Run directly to inspect one page:
    uv run scripts/squad_parser.py "2023 FIFA Women's World Cup squads"
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass

from fetch_page import API, USER_AGENT, fetch_wikitext

import requests

# Template names (normalized: lowercased, whitespace collapsed) that hold one
# player. Matched as a prefix so "(no caps)" / "no caps" suffixes are covered.
PLAYER_TEMPLATE_PREFIXES = (
    "nat fs player",
    "nat fs g player",
    "fs player",
    "national football squad player",
)

# FIFA/IOC country codes seen in ==={{fbu|...}}=== headers. Several countries
# have more than one code in use across editions; all aliases map to one name.
COUNTRY_CODES = {
    "ARG": "Argentina", "AUS": "Australia", "AUT": "Austria", "BEL": "Belgium",
    "BRA": "Brazil", "CAN": "Canada", "CHI": "Chile", "CHN": "China",
    "CIV": "Ivory Coast", "CMR": "Cameroon", "COL": "Colombia",
    "CRC": "Costa Rica", "CRO": "Croatia", "DEN": "Denmark", "ECU": "Ecuador",
    "ENG": "England", "ESP": "Spain", "FIN": "Finland", "FRA": "France",
    "GER": "Germany", "GHA": "Ghana", "GUI": "Guinea", "HON": "Honduras",
    "IRN": "Iran", "IRI": "Iran", "IRQ": "Iraq", "ITA": "Italy",
    "JPN": "Japan", "KOR": "South Korea", "MAR": "Morocco", "MEX": "Mexico",
    "MLI": "Mali", "NED": "Netherlands", "NGA": "Nigeria", "NGR": "Nigeria",
    "NZL": "New Zealand", "PAN": "Panama", "PAR": "Paraguay", "PRK": "North Korea",
    "RSA": "South Africa", "RUS": "Russia", "SVK": "Slovakia", "SWE": "Sweden",
    "SYR": "Syria", "TUN": "Tunisia", "UAE": "United Arab Emirates",
    "URU": "Uruguay", "USA": "United States", "UZB": "Uzbekistan",
    "VEN": "Venezuela",
}


@dataclass
class Player:
    team: str
    shirt_no: str
    position: str
    player_article: str  # "" when the name is not linked (a redlink)
    display_name: str
    birth_year: str = ""  # diagnostic only, never a join key


# --------------------------------------------------------------------------
# wikitext primitives
# --------------------------------------------------------------------------

REF_RE = re.compile(r"<ref[^>]*?/>|<ref[^>]*?>.*?</ref>", re.DOTALL | re.IGNORECASE)


def strip_refs(text: str) -> str:
    return REF_RE.sub("", text)


def split_params(body: str) -> list[str]:
    """Split template body on top-level '|', ignoring pipes nested in {{ }} or [[ ]]."""
    parts: list[str] = []
    cur: list[str] = []
    curly = square = 0
    i = 0
    while i < len(body):
        two = body[i : i + 2]
        if two == "{{":
            curly += 1
            cur.append(two)
            i += 2
        elif two == "}}":
            curly -= 1
            cur.append(two)
            i += 2
        elif two == "[[":
            square += 1
            cur.append(two)
            i += 2
        elif two == "]]":
            square -= 1
            cur.append(two)
            i += 2
        elif body[i] == "|" and curly == 0 and square == 0:
            parts.append("".join(cur))
            cur = []
            i += 1
        else:
            cur.append(body[i])
            i += 1
    parts.append("".join(cur))
    return parts


def iter_templates(text: str):
    """Yield (name, body) for every brace-balanced {{...}} in `text`."""
    i = 0
    while True:
        start = text.find("{{", i)
        if start == -1:
            return
        depth = 0
        j = start
        while j < len(text) - 1:
            if text[j : j + 2] == "{{":
                depth += 1
                j += 2
            elif text[j : j + 2] == "}}":
                depth -= 1
                j += 2
                if depth == 0:
                    break
            else:
                j += 1
        else:
            return  # unbalanced; give up on the rest of the page
        body = text[start + 2 : j - 2]
        params = split_params(body)
        name = re.sub(r"\s+", " ", params[0]).strip().lower()
        yield name, params[1:]
        i = start + 2  # allow nested templates to be seen too


def parse_named(params: list[str]) -> tuple[dict[str, str], list[str]]:
    """Split template params into named {k: v} and positional [v, ...]."""
    named: dict[str, str] = {}
    positional: list[str] = []
    for p in params:
        if "=" in p:
            k, _, v = p.partition("=")
            named[k.strip().lower()] = v.strip()
        else:
            positional.append(p.strip())
    return named, positional


def normalize_title(title: str) -> str:
    """Canonicalize a wiki link target the way MediaWiki does."""
    t = title.replace("_", " ").strip()
    t = t.lstrip(":").strip()
    t = t.split("#", 1)[0].strip()  # drop section anchors
    t = re.sub(r"\s+", " ", t)
    if not t:
        return ""
    return t[0].upper() + t[1:]


# --------------------------------------------------------------------------
# name= extraction
# --------------------------------------------------------------------------

WIKILINK_RE = re.compile(r"\[\[([^\[\]|]+)(?:\|([^\[\]]*))?\]\]")
SORTNAME_RE = re.compile(r"\{\{\s*sortname\s*\|", re.IGNORECASE)


def parse_sortname(value: str) -> tuple[str, str] | None:
    """Resolve the first {{sortname|First|Last|...}} to (article, display)."""
    m = SORTNAME_RE.search(value)
    if not m:
        return None
    for name, params in iter_templates(value[m.start() :]):
        if name != "sortname":
            continue
        named, positional = parse_named(params)
        if len(positional) < 2:
            return None
        first, last = positional[0], positional[1]
        display = f"{first} {last}".strip()
        if named.get("nolink"):
            return "", display
        if len(positional) >= 3 and positional[2]:
            # third positional overrides the link target
            return normalize_title(positional[2]), display
        dab = named.get("dab")
        article = f"{first} {last} ({dab})" if dab else f"{first} {last}"
        return normalize_title(article), display
    return None


def parse_player_name(value: str) -> tuple[str, str]:
    """Return (player_article, display_name) for a template's name= value.

    player_article is "" when the player has no linked article (a redlink).
    The FIRST link/sortname wins, so trailing captain markers such as
    "([[Captain (association football)|c]])" are ignored rather than mistaken
    for the player.
    """
    value = strip_refs(value).strip()
    value = value.replace("'''", "").replace("''", "").strip()

    link = WIKILINK_RE.search(value)
    sort = SORTNAME_RE.search(value)

    # whichever construct appears first is the player themselves
    if link and (not sort or link.start() < sort.start()):
        article = normalize_title(link.group(1))
        display = (link.group(2) or link.group(1)).strip()
        return article, display
    if sort:
        parsed = parse_sortname(value)
        if parsed:
            return parsed

    # unlinked plain text -> redlink
    plain = re.sub(r"\{\{[^{}]*\}\}", "", value)
    plain = re.sub(r"\([^)]*\)", "", plain)
    plain = re.sub(r"\s+", " ", plain).strip(" -–—,")
    return "", plain


# --------------------------------------------------------------------------
# section / team extraction
# --------------------------------------------------------------------------

HEADER_RE = re.compile(r"^(={2,4})\s*(.+?)\s*\1\s*$", re.MULTILINE)


def header_to_team(raw: str) -> str | None:
    """Turn a section header into a country name, or None if it isn't a team."""
    raw = strip_refs(raw).strip()
    if "{{" not in raw:
        name = re.sub(r"\[\[([^\[\]|]+)(?:\|([^\[\]]*))?\]\]", r"\1", raw).strip()
        return name or None

    for name, params in iter_templates(raw):
        if not re.match(r"^(fb|fbu|fbw|fbaw|nft|fb-rt|flagicon|flagu?)\b", name):
            continue
        _, positional = parse_named(params)
        for tok in positional:
            tok = tok.strip()
            # skip age level ("17", "20") and flag-variant years ("1949")
            if not tok or tok.isdigit():
                continue
            code = tok.upper()
            if code in COUNTRY_CODES:
                return COUNTRY_CODES[code]
            # some headers spell the country out, e.g. {{fbu|17|Iraq}}
            if len(tok) > 3:
                return tok
            return None  # unknown 2-3 letter code: caller records a failure
    return None


def parse_birth_year(value: str) -> str:
    """Pull the birth year out of {{birth date and age2|<as-of Y|M|D>|<born Y|M|D>}}.

    Diagnostic only -- it tells us whether a senior player was even age-eligible
    for the youth editions in scope. Never used as a join key.
    """
    for name, params in iter_templates(value):
        if "birth date and age" not in name:
            continue
        _, positional = parse_named(params)
        digits = [p for p in positional if p.strip().isdigit()]
        if len(digits) >= 4:
            return digits[3].strip()  # [as-of Y, M, D, born Y, ...]
    return ""


def is_player_template(name: str) -> bool:
    return any(name.startswith(p) for p in PLAYER_TEMPLATE_PREFIXES)


def parse_page(wikitext: str) -> tuple[list[Player], list[str]]:
    """Parse a squads page. Returns (players, warnings)."""
    players: list[Player] = []
    warnings: list[str] = []

    headers = list(HEADER_RE.finditer(wikitext))
    if not headers:
        return [], ["no section headers found"]

    for idx, h in enumerate(headers):
        start = h.end()
        end = headers[idx + 1].start() if idx + 1 < len(headers) else len(wikitext)
        section = wikitext[start:end]

        rows = [
            (name, params)
            for name, params in iter_templates(section)
            if is_player_template(name)
        ]
        if not rows:
            continue  # not a squad section (references, stats, group headers)

        team = header_to_team(h.group(2))
        if not team:
            warnings.append(
                f"{len(rows)} players under unrecognised header {h.group(2)!r}"
            )
            continue

        for _, params in rows:
            named, _ = parse_named(params)
            article, display = parse_player_name(named.get("name", ""))
            players.append(
                Player(
                    team=team,
                    shirt_no=named.get("no", "").strip(),
                    position=named.get("pos", "").strip(),
                    player_article=article,
                    display_name=display,
                    birth_year=parse_birth_year(named.get("age", "")),
                )
            )
    return players, warnings


# --------------------------------------------------------------------------
# redirect resolution
# --------------------------------------------------------------------------

@dataclass
class PageInfo:
    canonical: str  # title after normalization + redirects
    qid: str = ""  # Wikidata item, "" if the page has none
    missing: bool = False  # linked but no such article == effectively a redlink


def resolve_pages(titles: list[str]) -> dict[str, PageInfo]:
    """Resolve raw link targets to canonical title + Wikidata QID.

    One request gets both, from the already-allowlisted en.wikipedia.org API --
    prop=pageprops carries the wikibase_item, so no wikidata.org egress is
    needed.

    The QID is the join key we actually want. Article titles get moved: rename
    "Eva Navarro (footballer)" to "...(footballer, born 2001)" and a title-keyed
    join silently drops the match on the next run, with no error and a quietly
    lower overlap. QIDs never change. Redirect resolution is kept anyway as the
    fallback for the handful of pages that carry no Wikidata item.
    """
    out: dict[str, PageInfo] = {}
    uniq = sorted({t for t in titles if t})
    session = requests.Session()

    for i in range(0, len(uniq), 50):  # API caps titles at 50 per request
        batch = uniq[i : i + 50]
        resp = session.get(
            API,
            params={
                "action": "query",
                "titles": "|".join(batch),
                "prop": "pageprops",
                "ppprop": "wikibase_item",
                "redirects": "1",
                "format": "json",
                "formatversion": "2",
            },
            headers={"User-Agent": USER_AGENT},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json().get("query", {})

        chain: dict[str, str] = {}
        for norm in data.get("normalized", []):
            chain[norm["from"]] = norm["to"]
        for redir in data.get("redirects", []):
            chain[redir["from"]] = redir["to"]

        pages = {p["title"]: p for p in data.get("pages", [])}

        for title in batch:
            seen: set[str] = set()
            cur = title
            while cur in chain and cur not in seen:
                seen.add(cur)
                cur = chain[cur]
            page = pages.get(cur, {})
            out[title] = PageInfo(
                canonical=cur,
                qid=page.get("pageprops", {}).get("wikibase_item", ""),
                missing=bool(page.get("missing")),
            )

    return out


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: uv run scripts/squad_parser.py '<page title>'")
    page = sys.argv[1]
    parsed, warns = parse_page(fetch_wikitext(page))
    teams: dict[str, int] = {}
    for pl in parsed:
        teams[pl.team] = teams.get(pl.team, 0) + 1
    print(f"{page}: {len(parsed)} players across {len(teams)} teams")
    for team, n in sorted(teams.items()):
        print(f"  {n:3d}  {team}")
    redlinks = [p for p in parsed if not p.player_article]
    print(f"unlinked (redlink) names: {len(redlinks)}")
    for w in warns:
        print(f"WARNING: {w}")
