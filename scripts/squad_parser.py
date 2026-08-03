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

  squad body format
    {{nat fs start}} ... player templates ... {{nat fs end}}    the common case
    a raw wikitable ({| ... |}) with one row per player          2008 U-20 W and friends

TWO OPT-IN EXTENSIONS, added for Phase 2 ingestion (`expand=` and `tables=`).
Both default OFF so `parse_page(wikitext)` behaves exactly as it did in Phase 1
and the phase1.py regression check is untouched.

  expand=True   resolve ==={{fbu|...}}=== headers through the MediaWiki
                expandtemplates API instead of the COUNTRY_CODES literal below.
                COUNTRY_CODES is 50 entries hand-typed against the two pages
                Phase 1 happened to touch; across the 32 Phase 2 editions it
                misses constantly (BFA, CZE, EGY, IRL, KSA, POR, GUA, THA, JAM,
                QAT ...), and every miss drops a whole 18-24 player squad.
                Expanding the template asks Wikipedia what the code means, so
                there is no map to keep current and NGR/NGA and IRN/IRI collapse
                to one federation for free.

  tables=True   parse squads written as a raw wikitable. Some older pages mix
                both dialects in one article -- 2008 FIFA U-20 Women's World Cup
                squads has 11 template squads and 5 table squads (England,
                France, United States, Canada, New Zealand). Without this the
                page parses "successfully" at 11 of 16 teams, raising no
                warning, and four well-covered federations vanish from the youth
                pool. That is the silent-shrink failure mode in its purest form.

Run directly to inspect one page:
    uv run scripts/squad_parser.py "2023 FIFA Women's World Cup squads"
    uv run scripts/squad_parser.py --full "2008 FIFA U-20 Women's World Cup squads"
"""
from __future__ import annotations

import re
import sys
from collections import Counter
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


def header_to_team(raw: str, expanded: dict[str, str] | None = None) -> str | None:
    """Turn a section header into a country name, or None if it isn't a team.

    `expanded` is the optional expand_headers() lookup; when it has an answer for
    this header it wins over the COUNTRY_CODES literal, which is incomplete by
    construction.
    """
    if expanded and raw in expanded:
        return expanded[raw]
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


# --------------------------------------------------------------------------
# header expansion (opt-in; see module docstring)
# --------------------------------------------------------------------------

FILE_LINK_RE = re.compile(r"(?i)^\s*(file|image|media)\s*:")
_TEAM_SUFFIX_RE = re.compile(
    r"\s+national\s+(under[- ]?\d+\s+)?(women'?s\s+)?football\s+team\s*$", re.IGNORECASE
)


def expand_headers(raw_headers: list[str]) -> dict[str, str]:
    """Ask MediaWiki what each templated section header renders to.

    {{fbu|20|BFA}} expands to a flag icon plus
    [[Burkina Faso national under-20 football team|Burkina Faso]]; we keep the
    last non-File link's display text. Batched with an @@n@@ sentinel between
    entries so one request covers a whole page's headers.

    Returns {raw header: federation name} for the headers it could resolve.
    Headers it cannot resolve are simply absent, so the caller still records an
    unresolved-header failure rather than inventing a team.
    """
    uniq = sorted({h for h in raw_headers if "{{" in h})
    if not uniq:
        return {}

    out: dict[str, str] = {}
    session = requests.Session()
    for i in range(0, len(uniq), 60):
        batch = uniq[i : i + 60]
        text = "\n".join(f"@@{n}@@\n{h}" for n, h in enumerate(batch))
        resp = session.get(
            API,
            params={
                "action": "expandtemplates",
                "prop": "wikitext",
                "text": text,
                "format": "json",
                "formatversion": "2",
            },
            headers={"User-Agent": USER_AGENT},
            timeout=40,
        )
        resp.raise_for_status()
        expanded = resp.json()["expandtemplates"]["wikitext"]

        parts = re.split(r"@@(\d+)@@", expanded)
        for j in range(1, len(parts) - 1, 2):
            body = parts[j + 1]
            links = [
                m for m in WIKILINK_RE.finditer(body)
                if not FILE_LINK_RE.match(m.group(1))
            ]
            if not links:
                continue
            last = links[-1]
            name = (last.group(2) or last.group(1)).strip()
            name = _TEAM_SUFFIX_RE.sub("", name).strip()
            if name:
                out[batch[int(parts[j])]] = name
    return out


# --------------------------------------------------------------------------
# wikitable squads (opt-in; see module docstring)
# --------------------------------------------------------------------------

POSITION_GROUPS = {
    "goalkeeper": "GK", "goalkeepers": "GK", "goalies": "GK",
    "defender": "DF", "defenders": "DF", "defence": "DF", "defense": "DF",
    "midfielder": "MF", "midfielders": "MF", "midfield": "MF",
    "forward": "FW", "forwards": "FW", "attacker": "FW", "attackers": "FW",
    "striker": "FW", "strikers": "FW",
}

# a cell's leading "align=left|" / "bgcolor=#EFEFEF|" style attributes
CELL_ATTR_RE = re.compile(r"""^[A-Za-z0-9_\-\s="'%#;:.,()]*=[A-Za-z0-9_\-\s="'%#;:.,()]*$""")


def extract_table(section: str) -> str | None:
    """Return the first brace-balanced {| ... |} block in `section`."""
    start = section.find("{|")
    if start == -1:
        return None
    depth, i = 0, start
    while i < len(section) - 1:
        two = section[i : i + 2]
        if two == "{|":
            depth += 1
            i += 2
        elif two == "|}":
            depth -= 1
            i += 2
            if depth == 0:
                return section[start:i]
        else:
            i += 1
    return None


def split_cells(line: str) -> list[str]:
    """Split one wikitable line into cells on top-level '||' (or '!!')."""
    cells: list[str] = []
    cur: list[str] = []
    curly = square = 0
    i = 0
    while i < len(line):
        two = line[i : i + 2]
        if two in ("{{", "[["):
            (curly, square) = (curly + 1, square) if two == "{{" else (curly, square + 1)
            cur.append(two)
            i += 2
        elif two in ("}}", "]]"):
            (curly, square) = (curly - 1, square) if two == "}}" else (curly, square - 1)
            cur.append(two)
            i += 2
        elif two in ("||", "!!") and curly == 0 and square == 0:
            cells.append("".join(cur))
            cur = []
            i += 2
        else:
            cur.append(line[i])
            i += 1
    cells.append("".join(cur))
    return cells


def strip_cell_attrs(cell: str) -> str:
    """Drop a cell's style attributes: 'align=left|[[X]]' -> '[[X]]'."""
    parts = split_params(cell)  # top-level '|' split, link/template aware
    if len(parts) >= 2 and CELL_ATTR_RE.match(parts[0].strip()):
        return "|".join(parts[1:]).strip()
    return cell.strip()


def parse_table_squad(
    section: str, team: str, acc: Counter | None = None
) -> list[Player]:
    """Parse a squad written as a raw wikitable rather than player templates."""
    note = acc if acc is not None else Counter()
    table = extract_table(section)
    if table is None:
        return []

    # group rows on the |- separators
    rows: list[list[str]] = []
    cur: list[str] = []
    for line in table.splitlines():
        stripped = line.strip()
        if stripped.startswith("|-"):
            rows.append(cur)
            cur = []
        elif stripped.startswith(("|", "!")) and not stripped.startswith(("{|", "|}")):
            cur.append(stripped)
    rows.append(cur)

    def cells_of(row: list[str]) -> list[str]:
        out: list[str] = []
        for line in row:
            out.extend(split_cells(line[1:]))  # drop the leading '|' or '!'
        return [strip_cell_attrs(c) for c in out]

    # Column layout from the header row, when there is one. Falls back to
    # "number first, name second" plus a scan for the birth-date template.
    col_no = col_name = col_pos = col_dob = None
    for row in rows:
        if not row or not all(l.startswith("!") for l in row):
            continue
        labels = [re.sub(r"[^a-z ]", " ", c.lower()).strip() for c in cells_of(row)]
        if not any(l.startswith("name") or l.startswith("player") for l in labels):
            continue
        for idx, lab in enumerate(labels):
            if col_no is None and lab in ("", "no", "no ", "number", "shirt"):
                col_no = idx
            elif col_name is None and (lab.startswith("name") or lab.startswith("player")):
                col_name = idx
            elif col_pos is None and lab.startswith("pos"):
                col_pos = idx
            elif col_dob is None and ("birth" in lab or lab.startswith("dob")):
                col_dob = idx
        break
    if col_name is None:
        col_no, col_name = 0, 1
        note["table_column_fallback"] += 1

    players: list[Player] = []
    position = ""
    for row in rows:
        if not row:
            continue
        if all(l.startswith("!") for l in row):
            # a "Goalkeepers" / "Defenders" band, or the header row itself
            label = re.sub(r"[^a-z]", "", cells_of(row)[-1].lower())
            position = POSITION_GROUPS.get(label, position)
            continue
        cells = cells_of(row)
        if len(cells) <= col_name:
            continue
        name_cell = cells[col_name]
        article, display = parse_player_name(name_cell)
        if not display and not article:
            continue
        dob = ""
        if col_dob is not None and col_dob < len(cells):
            dob = parse_birth_year(cells[col_dob])
        if not dob:
            for c in cells:
                dob = parse_birth_year(c)
                if dob:
                    break
        shirt = ""
        if col_no is not None and col_no < len(cells):
            shirt = re.sub(r"\D", "", strip_refs(cells[col_no]))
        # A squad-table row carries a shirt number, a date of birth, or both.
        # The row with neither is the trailing "head coach" row these tables end
        # with -- 2008 U-20 W France has one, and taking it produced a 22nd
        # "player" named Stephane Pilard. Fabricating a squad member is worse
        # than dropping a real one, so the row is required to look like a player.
        if not shirt and not dob:
            note["table_nonplayer_row_dropped"] += 1
            continue
        pos = position
        if col_pos is not None and col_pos < len(cells):
            pos = POSITION_GROUPS.get(
                re.sub(r"[^a-z]", "", cells[col_pos].lower()), cells[col_pos].strip()
            ) or position
        players.append(
            Player(team=team, shirt_no=shirt, position=pos,
                   player_article=article, display_name=display, birth_year=dob)
        )
    return players


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


BIRTH_TEMPLATE_RE = re.compile(r"(?i)\{\{\s*birth date and age")


def note_header(raw: str, expanded: dict[str, str] | None, note: Counter) -> None:
    """Record how a team header had to be resolved.

    `header_code_needs_expansion` is the interesting one: the header is a
    template whose country code the COUNTRY_CODES literal does not know, so
    before expand_headers() existed this section was dropped outright.
    """
    if "{{" not in raw:
        note["header_plain_text"] += 1
        return
    note["header_template"] += 1
    if header_to_team(raw, None) is None:
        note["header_code_needs_expansion"] += 1
        if not (expanded and raw in expanded):
            note["header_unresolvable"] += 1


def looks_like_squad_table(section: str) -> bool:
    """Gate for the table fallback: squad tables carry a DOB per player.

    Statistics tables ("players by club", "average age by country") never do, so
    this keeps the fallback from inventing a squad out of a stats section whose
    plain-text header happens to parse as a team name.
    """
    return len(BIRTH_TEMPLATE_RE.findall(section)) >= 5


def parse_page(
    wikitext: str,
    *,
    expand: bool = False,
    tables: bool = False,
    acc: Counter | None = None,
) -> tuple[list[Player], list[str]]:
    """Parse a squads page. Returns (players, warnings).

    Both keyword flags default off so Phase 1 output is unchanged; see the module
    docstring for what they buy Phase 2.

    `acc` is an optional Counter the parser fills with the format variants it had
    to accommodate on this page -- which player-template dialect, whether a
    header needed API expansion, whether a squad came from a wikitable, and so
    on. It is an out-parameter rather than a third return value so existing
    two-value callers keep working. The point is not the individual counts; it is
    that a page which needed three accommodations is evidence that pages which
    needed none may simply have variants nobody has looked for yet.
    """
    note = acc if acc is not None else Counter()
    players: list[Player] = []
    warnings: list[str] = []

    headers = list(HEADER_RE.finditer(wikitext))
    if not headers:
        return [], ["no section headers found"]

    expanded = expand_headers([h.group(2) for h in headers]) if expand else None

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
            if not (tables and looks_like_squad_table(section)):
                continue  # not a squad section (references, stats, group headers)
            team = header_to_team(h.group(2), expanded)
            if not team:
                warnings.append(f"table squad under unrecognised header {h.group(2)!r}")
                continue
            note_header(h.group(2), expanded, note)
            table_players = parse_table_squad(section, team, note)
            if not table_players:
                warnings.append(f"table squad for {team!r} yielded no players")
                continue
            note["wikitable_squad"] += 1
            players.extend(table_players)
            continue

        team = header_to_team(h.group(2), expanded)
        if not team:
            warnings.append(
                f"{len(rows)} players under unrecognised header {h.group(2)!r}"
            )
            continue
        note_header(h.group(2), expanded, note)

        for tmpl_name, params in rows:
            note[f"player_template:{tmpl_name}"] += 1
            named, _ = parse_named(params)
            raw_name = named.get("name", "")
            if SORTNAME_RE.search(raw_name):
                note["name_via_sortname"] += 1
            if "'''" in raw_name:
                note["name_wrapped_in_bold"] += 1
            article, display = parse_player_name(raw_name)
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
    argv = [a for a in sys.argv[1:] if a != "--full"]
    full = "--full" in sys.argv  # expand headers + parse table squads
    if len(argv) != 1:
        sys.exit("usage: uv run scripts/squad_parser.py [--full] '<page title>'")
    page = argv[0]
    parsed, warns = parse_page(fetch_wikitext(page), expand=full, tables=full)
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
