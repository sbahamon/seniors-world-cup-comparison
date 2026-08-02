# /// script
# requires-python = ">=3.11"
# dependencies = ["requests"]
# ///
"""Phase 2 ingestion: fetch every in-scope edition once, extract every federation.

This is NOT phase1.py extended. phase1.py's compute() applies the retired
"any prior edition" rule, which is correct for the window-exempt validation case
and wrong for measurement; it stays untouched as the parser/join regression
check. This script windows through editions.editions_in_window() instead, and it
does not compute overlap at all -- data/overlap.csv is deliberately left
unwritten.

Scope (CLAUDE.md "Scope for v1"): senior women's 2019/2023 and men's
2010/2014/2018/2022, whose Y-12..Y-4 windows all contain a full 8 held editions.
The union of those six windows is 32 youth editions; those plus the 6 senior
pages are the 38 pages fetched here. Ingestion is bounded by editions, not
squads: one fetch per page, all federations extracted from it.

    uv run scripts/ingest.py --preflight        # assertions only, no fetching
    uv run scripts/ingest.py --only u20m2003,u20m2011 --out /tmp/smoke
    uv run scripts/ingest.py --resume --commit  # full run, commit per edition

WHAT THE INTEGRITY CHECKS ARE FOR
---------------------------------
The failure that matters is not a page that throws -- that lands in
parse_failures.csv and is visible. It is a page that parses without error and
returns 14 of 18 players, or 20 of 24 teams. Nothing errored, so nothing is
recorded, and the youth pool just quietly shrinks. That deflates measured
overlap hardest for the federations already worst hit by the redlink gap, which
is the exact bias CLAUDE.md says is the dominant error source. Two real
instances found while building this:

  2003 World Youth Championship   5 of 24 squads dropped -- the hand-typed
                                  COUNTRY_CODES map has no BFA/CZE/EGY/IRL/KSA
  2008 U-20 Women's World Cup     5 of 16 squads dropped SILENTLY, no warning --
                                  England, France, US, Canada and New Zealand are
                                  written as raw wikitables, not player templates

Both are fixed in squad_parser (expand=/tables=), but the fix is not the point:
the checks below are what would have caught them, and are what will catch the
next dialect. Every deviation is written to data/integrity_flags.csv.

An `error`-severity flag on an edition also changes how window_coverage reads
that edition: a federation missing from an edition we know we mis-parsed is
`failed`, not `not_qualified`. Conflating those two would let a parser bug
masquerade as "this country didn't qualify" and quietly stop the provisional
flag from firing.
"""
from __future__ import annotations

import argparse
import csv
import subprocess
import sys
import unicodedata
import urllib.parse
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import requests

from editions import editions_in_window, window_counts
from fetch_page import API, USER_AGENT, fetch_wikitext
from squad_parser import parse_page, resolve_pages

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

# --------------------------------------------------------------------------
# scope
# --------------------------------------------------------------------------

# The six senior editions of CLAUDE.md "Scope for v1" -- the only ones whose
# windows hold a full 8 held editions, hence the only ones whose shares are
# comparable without a denominator caveat.
V1_SENIOR: list[tuple[str, int, str]] = [
    ("w", 2019, "2019 FIFA Women's World Cup squads"),
    ("w", 2023, "2023 FIFA Women's World Cup squads"),
    ("m", 2010, "2010 FIFA World Cup squads"),
    ("m", 2014, "2014 FIFA World Cup squads"),
    ("m", 2018, "2018 FIFA World Cup squads"),
    ("m", 2022, "2022 FIFA World Cup squads"),
]

# Expected finals-tournament team count per edition. Hand-entered, and checked
# against what the parser actually extracts -- a mismatch in either direction is
# the loud flag, so a wrong entry here surfaces rather than corrupts.
#   men's U-20  24 throughout (World Youth Championship kept 24 on rename)
#   men's U-17  16 through 2005, 24 from 2007
#   women's U-20 / U-17  16 throughout the in-scope years
EXPECTED_TEAMS: dict[tuple[str, str, int], int] = {}
for _y in (1999, 2001, 2003, 2005, 2007, 2009, 2011, 2013, 2015, 2017):
    EXPECTED_TEAMS[("u20", "m", _y)] = 24
    EXPECTED_TEAMS[("u17", "m", _y)] = 16 if _y <= 2005 else 24
for _y in (2008, 2010, 2012, 2014, 2016, 2018):
    EXPECTED_TEAMS[("u20", "w", _y)] = 16
    EXPECTED_TEAMS[("u17", "w", _y)] = 16
EXPECTED_TEAMS[("senior", "m", 2010)] = 32
EXPECTED_TEAMS[("senior", "m", 2014)] = 32
EXPECTED_TEAMS[("senior", "m", 2018)] = 32
EXPECTED_TEAMS[("senior", "m", 2022)] = 32
EXPECTED_TEAMS[("senior", "w", 2019)] = 24
EXPECTED_TEAMS[("senior", "w", 2023)] = 32

# Absolute plausibility band on one squad. Youth finals squads have run 18
# (1999 U-17) to 21 (modern); senior ran 23 through 2018 and 26 from 2022.
# Deliberately loose -- the tight check is SQUAD_MODE_TOLERANCE below, which
# compares a squad to the rest of its own edition and so needs no prior.
SQUAD_BAND = {"u17": (18, 23), "u20": (18, 23), "senior": (18, 26)}
SQUAD_MODE_TOLERANCE = 2  # players off the edition's modal squad size

# Federation names that differ between page dialects for the same federation.
# Kept short on purpose: expand_headers() already collapses the FIFA/IOC code
# aliases (NGR/NGA, IRN/IRI), so this only covers prose spellings. The
# `name_variant_review` check below hunts for entries this map is missing.
# Historical federations (Yugoslavia, Serbia and Montenegro) are NOT merged into
# their successors -- that would be a claim about football, not a spelling fix.
FEDERATION_ALIASES = {
    "China": "China PR",
    "Korea Republic": "South Korea",
    "Korea DPR": "North Korea",
    "Ireland": "Republic of Ireland",
    "Côte d'Ivoire": "Ivory Coast",
    "Cote d'Ivoire": "Ivory Coast",
    "USA": "United States",
    "United States of America": "United States",
    "Congo DR": "DR Congo",
    "Democratic Republic of the Congo": "DR Congo",
    "DR Congo": "DR Congo",
    "IR Iran": "Iran",
    "Czechia": "Czech Republic",
    "Türkiye": "Turkey",
    "Cabo Verde": "Cape Verde",
    "Macedonia": "North Macedonia",
    "Republic of Macedonia": "North Macedonia",
    "Netherlands Antilles": "Netherlands Antilles",
    "Trinidad & Tobago": "Trinidad and Tobago",
}


def canon_team(name: str) -> str:
    return FEDERATION_ALIASES.get(name.strip(), name.strip())


def tid(level: str, gender: str, year: int) -> str:
    return f"{level}{gender}{year}"


def source_url(page: str) -> str:
    return "https://en.wikipedia.org/wiki/" + urllib.parse.quote(page.replace(" ", "_"))


def fold(name: str) -> str:
    decomposed = unicodedata.normalize("NFKD", name)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return "".join(c for c in stripped.lower() if c.isalnum() or c == " ").strip()


@dataclass
class Edition:
    level: str
    gender: str
    year: int
    page_title: str

    @property
    def tid(self) -> str:
        return tid(self.level, self.gender, self.year)

    @property
    def key(self) -> tuple[str, str, int]:
        return (self.level, self.gender, self.year)

    def __str__(self) -> str:
        who = "women" if self.gender == "w" else "men"
        return f"{self.tid} ({self.level.upper()} {who} {self.year})"


def youth_targets() -> list[Edition]:
    """The union of the six in-scope senior windows, deduplicated.

    `not_held` editions (title None) are excluded -- there is no page to fetch --
    but they still appear in window_coverage.csv with status not_held, which is
    what keeps them out of the denominator instead of marking a squad provisional.
    """
    seen: dict[tuple[str, str, int], Edition] = {}
    for gender, year, _ in V1_SENIOR:
        for level, g, yr, title in editions_in_window(gender, year):
            if title and (level, g, yr) not in seen:
                seen[(level, g, yr)] = Edition(level, g, yr, title)
    return sorted(seen.values(), key=lambda e: (e.gender, e.level, e.year))


def senior_targets() -> list[Edition]:
    return [Edition("senior", g, y, t) for g, y, t in V1_SENIOR]


# --------------------------------------------------------------------------
# preflight: everything that can be asserted before a single squad is fetched
# --------------------------------------------------------------------------

def preflight(targets: list[Edition]) -> list[str]:
    """Assertions that run before any bulk fetching. Returns fatal problems."""
    fatal: list[str] = []
    youth = [e for e in targets if e.level != "senior"]
    senior = [e for e in targets if e.level == "senior"]

    print("preflight")

    # 1. every in-scope senior window really is a full 8 held editions. If this
    #    trips, the v1 comparable-core claim is wrong and nothing downstream is
    #    comparable, so it is fatal rather than a flag.
    for gender, year, _ in V1_SENIOR:
        total, held = window_counts(gender, year)
        ok = total == 8 and held == 8
        print(f"  window {gender}{year}: {total} in window, {held} held "
              f"{'ok' if ok else 'FATAL'}")
        if not ok:
            fatal.append(
                f"{gender}{year} window is {total} editions / {held} held, expected 8/8"
            )

    # 2. the union is the 32 editions the scope note commits to
    if len(youth) == 32:
        print(f"  youth edition union: {len(youth)} ok")
    else:
        print(f"  youth edition union: {len(youth)} FATAL (expected 32)")
        fatal.append(f"youth union is {len(youth)} editions, expected 32")

    # 3. an expected team count for every edition -- without one, check A below
    #    silently does nothing and a truncated page passes
    missing = [str(e) for e in targets if e.key not in EXPECTED_TEAMS]
    if missing:
        print(f"  expected-team-count coverage: FATAL, {len(missing)} missing")
        fatal.extend(f"no EXPECTED_TEAMS entry for {m}" for m in missing)
    else:
        print(f"  expected-team-count coverage: {len(targets)}/{len(targets)} ok")

    # 4. every page title still resolves. Titles come from the editions.py
    #    lookup precisely because the tournaments were renamed; a 404 here is a
    #    hard failure to record, never a silent skip.
    missing_pages = check_titles([e.page_title for e in targets])
    if missing_pages:
        print(f"  page titles resolve: {len(targets) - len(missing_pages)}/{len(targets)}")
        for t in missing_pages:
            print(f"      MISSING: {t}")
    else:
        print(f"  page titles resolve: {len(targets)}/{len(targets)} ok")

    print(f"  targets: {len(senior)} senior + {len(youth)} youth = {len(targets)} pages")
    return fatal


def check_titles(titles: list[str]) -> set[str]:
    """Return the subset of `titles` that does not resolve to an existing page."""
    session = requests.Session()
    gone: set[str] = set()
    for i in range(0, len(titles), 50):
        batch = titles[i : i + 50]
        resp = session.get(
            API,
            params={"action": "query", "titles": "|".join(batch), "redirects": "1",
                    "format": "json", "formatversion": "2"},
            headers={"User-Agent": USER_AGENT},
            timeout=40,
        )
        resp.raise_for_status()
        data = resp.json()["query"]
        chain: dict[str, str] = {}
        for key in ("normalized", "redirects"):
            for e in data.get(key, []):
                chain[e["from"]] = e["to"]
        absent = {p["title"] for p in data.get("pages", []) if p.get("missing")}
        for t in batch:
            cur, seen = t, set()
            while cur in chain and cur not in seen:
                seen.add(cur)
                cur = chain[cur]
            if cur in absent:
                gone.add(t)
    return gone


# --------------------------------------------------------------------------
# per-edition integrity checks
# --------------------------------------------------------------------------

@dataclass
class Flag:
    edition: Edition
    team: str
    check: str
    severity: str  # error | warn
    expected: str
    observed: str
    detail: str

    def row(self) -> dict:
        return {
            "tournament_id": self.edition.tid, "level": self.edition.level,
            "gender": self.edition.gender, "year": self.edition.year,
            "page_title": self.edition.page_title, "team": self.team,
            "check": self.check, "severity": self.severity,
            "expected": self.expected, "observed": self.observed,
            "detail": self.detail,
        }


@dataclass
class EditionResult:
    edition: Edition
    rows: list[dict] = field(default_factory=list)
    flags: list[Flag] = field(default_factory=list)
    failures: list[dict] = field(default_factory=list)
    teams: set[str] = field(default_factory=set)
    fetched: bool = False

    @property
    def errors(self) -> list[Flag]:
        return [f for f in self.flags if f.severity == "error"]

    @property
    def reliable(self) -> bool:
        """True when a federation's absence from this edition can be trusted.

        Anything less and absence is ambiguous -- it might be a squad we failed
        to extract -- so window_coverage must call it `failed`, not
        `not_qualified`.
        """
        return self.fetched and not self.errors


def check_edition(ed: Edition, players: list, warnings: list[str]) -> list[Flag]:
    flags: list[Flag] = []
    by_team: dict[str, list] = defaultdict(list)
    for p in players:
        by_team[canon_team(p.team)].append(p)

    # A. team count against the known finals field size
    expected = EXPECTED_TEAMS.get(ed.key)
    if expected is not None and len(by_team) != expected:
        got = sorted(by_team)
        flags.append(Flag(
            ed, "", "team_count", "error", str(expected), str(len(by_team)),
            f"teams extracted: {', '.join(got)}",
        ))

    # B. a section that holds players but whose header did not resolve to a
    #    federation. parse_page already refuses to guess; this makes it loud.
    for w in warnings:
        flags.append(Flag(ed, "", "unresolved_section", "error", "resolved", "unresolved", w))

    # C. absolute squad-size band
    lo, hi = SQUAD_BAND[ed.level]
    for team, squad in sorted(by_team.items()):
        if not (lo <= len(squad) <= hi):
            flags.append(Flag(
                ed, team, "squad_size_band", "error", f"{lo}-{hi}", str(len(squad)),
                "squad size outside the plausible band for this level",
            ))

    # D. squad size against the rest of the same edition. This is the check that
    #    catches "14 of 18 players": every other squad on the page agrees, so the
    #    modal size is the ground truth and no hand-entered prior is needed.
    sizes = Counter(len(s) for s in by_team.values())
    if sizes:
        mode, mode_n = sizes.most_common(1)[0]
        if mode_n > 1:
            for team, squad in sorted(by_team.items()):
                delta = abs(len(squad) - mode)
                if delta:
                    flags.append(Flag(
                        ed, team, "squad_size_vs_edition",
                        "error" if delta > SQUAD_MODE_TOLERANCE else "warn",
                        str(mode), str(len(squad)),
                        f"{delta} off this edition's modal squad size "
                        f"({mode_n} of {len(by_team)} squads are {mode})",
                    ))

    # E. the same federation under two headers -- a merged section would double
    #    a squad and inflate its youth pool
    header_teams = Counter(canon_team(p.team) for p in players)
    for team, squad in by_team.items():
        if header_teams[team] != len(squad):  # defensive; should be identical
            flags.append(Flag(ed, team, "team_row_mismatch", "error",
                              str(len(squad)), str(header_teams[team]), ""))

    # F. squads where the parse produced no shirt numbers at all -- usually a
    #    sign the table-column mapping went wrong even though names came through
    for team, squad in sorted(by_team.items()):
        if squad and not any(p.shirt_no for p in squad):
            flags.append(Flag(ed, team, "no_shirt_numbers", "warn", "some", "none",
                              "column mapping may be off; names still extracted"))

    # G. a squad where nothing is linked. Not a parse bug -- it is the coverage
    #    floor CLAUDE.md warns about -- but it must be visible, because such a
    #    squad contributes zero joinable players to the youth pool.
    for team, squad in sorted(by_team.items()):
        linked = sum(1 for p in squad if p.player_article)
        if squad and linked == 0:
            flags.append(Flag(ed, team, "zero_linked_players", "warn", ">0", "0",
                              "entire squad is redlinks; contributes nothing joinable"))
    return flags


def check_name_variants(all_teams: dict[str, set[str]]) -> list[Flag]:
    """Hunt for two spellings of one federation that FEDERATION_ALIASES misses.

    A split name is invisible in every per-edition check -- both halves parse
    fine -- and it halves that federation's youth pool at join time. Flags pairs
    where one folded name contains the other ("China" / "China PR").
    """
    flags: list[Flag] = []
    names = sorted(all_teams)
    for i, a in enumerate(names):
        for b in names[i + 1 :]:
            fa, fb = fold(a), fold(b)
            if fa == fb or fa.startswith(fb + " ") or fb.startswith(fa + " "):
                flags.append(Flag(
                    Edition("", "", 0, ""), f"{a} / {b}", "name_variant_review", "warn",
                    "one federation name", f"{a!r} and {b!r}",
                    f"{a} in {sorted(all_teams[a])}; {b} in {sorted(all_teams[b])}",
                ))
    return flags


# --------------------------------------------------------------------------
# ingestion
# --------------------------------------------------------------------------

def ingest_edition(ed: Edition) -> EditionResult:
    res = EditionResult(edition=ed)
    print(f"\n{ed}  <- {ed.page_title}")

    try:
        wikitext = fetch_wikitext(ed.page_title)
        players, warnings = parse_page(wikitext, expand=True, tables=True)
    except Exception as exc:  # noqa: BLE001 - record and move on, per CLAUDE.md
        res.failures.append({"tournament_id": ed.tid, "page": ed.page_title,
                             "reason": repr(exc)})
        print(f"  FETCH/PARSE FAILURE: {exc!r}")
        return res

    res.fetched = True
    for w in warnings:
        res.failures.append({"tournament_id": ed.tid, "page": ed.page_title, "reason": w})
    res.flags = check_edition(ed, players, warnings)

    rows: list[dict] = []
    for p in players:
        rows.append({
            "tournament_id": ed.tid, "level": ed.level, "gender": ed.gender,
            "year": ed.year, "team": canon_team(p.team), "shirt_no": p.shirt_no,
            "position": p.position, "player_article": p.player_article,
            "display_name": p.display_name, "source_url": source_url(ed.page_title),
            "birth_year": p.birth_year,
        })

    resolve_qids(rows)
    res.rows = rows
    res.teams = {r["team"] for r in rows}

    if rows:
        linked = sum(1 for r in rows if r["join_key"])
        red = len(rows) - linked
        expected = EXPECTED_TEAMS.get(ed.key)
        print(f"  teams {len(res.teams)}/{expected}   players {len(rows)}   "
              f"joinable {linked}   redlinks {red} ({red / len(rows):.1%})")
    else:
        print("  no players extracted")
    for f in res.flags:
        print(f"  [{f.severity.upper():5s}] {f.check}"
              + (f" {f.team}" if f.team else "")
              + f": expected {f.expected}, got {f.observed}")
    return res


def resolve_qids(rows: list[dict]) -> None:
    """Attach player_qid / join_key in place. QID is the join key; see CLAUDE.md."""
    resolved = resolve_pages([r["player_article"] for r in rows if r["player_article"]])
    for r in rows:
        raw = r["player_article"]
        info = resolved.get(raw) if raw else None
        if not raw:
            r["player_qid"], r["join_key"], r["join_note"] = "", "", "no linked article"
        elif info is None or info.missing:
            # a bluelink pointing at a non-existent page is still a redlink
            r["player_article"] = ""
            r["player_qid"], r["join_key"] = "", ""
            r["join_note"] = "linked article does not exist"
        else:
            r["player_article"] = info.canonical
            r["player_qid"] = info.qid
            r["join_key"] = info.qid or f"title:{info.canonical}"
            notes = []
            if info.canonical != raw:
                notes.append(f"redirect from {raw}")
            if not info.qid:
                notes.append("no wikidata item, joined on title")
            r["join_note"] = "; ".join(notes)


# --------------------------------------------------------------------------
# window coverage
# --------------------------------------------------------------------------

def build_window_coverage(
    results: dict[str, EditionResult], squad_rows: list[dict]
) -> list[dict]:
    """One row per (senior squad, in-window youth edition).

    Status, and why each value is what it is:
      not_held      the edition was never played (COVID cancellation, or before
                    the tournament existed). Removed from the denominator
                    entirely -- there is no squad to miss.
      ingested      the edition was parsed cleanly and this federation is in it.
      not_qualified the edition was parsed cleanly and this federation is not.
                    Real signal, not missing data. Only ever emitted for an
                    edition with no error-severity integrity flag.
      failed        the edition could not be retrieved, OR it was retrieved but
                    an error-severity flag means we cannot tell a genuine
                    non-qualification from a squad we dropped. This is the only
                    status that makes a senior squad provisional, so it must not
                    absorb cases that belong in not_qualified -- and must not be
                    withheld from cases that do belong here.
    """
    teams_by_edition = {t: r.teams for t, r in results.items()}
    rows: list[dict] = []

    for gender, senior_year, _ in V1_SENIOR:
        senior_tid = tid("senior", gender, senior_year)
        federations = sorted({r["team"] for r in squad_rows
                              if r["tournament_id"] == senior_tid})
        if not federations:
            print(f"  window_coverage: no senior squads for {senior_tid}, skipping")
            continue

        for level, g, yr, title in editions_in_window(gender, senior_year):
            youth_tid = tid(level, g, yr)
            if title is None:
                status_for = lambda team: "not_held"  # noqa: E731
            elif youth_tid not in results:
                status_for = lambda team: "failed"  # noqa: E731
            else:
                res = results[youth_tid]
                if not res.reliable:
                    present = teams_by_edition.get(youth_tid, set())
                    # a federation we DID extract is still ingested; only the
                    # absences are untrustworthy on a flagged edition
                    status_for = (
                        lambda team, p=present: "ingested" if team in p else "failed"
                    )
                else:
                    present = teams_by_edition[youth_tid]
                    status_for = (
                        lambda team, p=present: "ingested" if team in p else "not_qualified"
                    )

            for team in federations:
                rows.append({
                    "team": team, "gender": gender, "senior_year": senior_year,
                    "youth_level": level, "youth_year": yr, "status": status_for(team),
                })
    return rows


# --------------------------------------------------------------------------
# persistence
# --------------------------------------------------------------------------

SQUAD_FIELDS = ["tournament_id", "level", "gender", "year", "team", "shirt_no",
                "position", "player_article", "player_qid", "display_name",
                "source_url", "birth_year"]
REDLINK_FIELDS = ["tournament_id", "level", "gender", "year", "team", "display_name",
                  "reason", "fuzzy_match", "fuzzy_match_source", "confidence"]
FAILURE_FIELDS = ["tournament_id", "page", "reason"]
FLAG_FIELDS = ["tournament_id", "level", "gender", "year", "page_title", "team",
               "check", "severity", "expected", "observed", "detail"]
COVERAGE_FIELDS = ["team", "gender", "senior_year", "youth_level", "youth_year", "status"]


def write_csv(path: Path, fields: list[str], data: list[dict], quiet: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(data)
    if not quiet:
        print(f"  wrote {path.name} ({len(data)} rows)")


def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def redlink_rows(rows: list[dict]) -> list[dict]:
    """Every player who cannot be joined on a QID. Nothing is dropped silently.

    Joinability is read off player_qid/player_article rather than the in-memory
    join_key, so this gives the same answer for rows reloaded from squads.csv on
    a --resume run as for rows just parsed.

    fuzzy_match is left empty here: the fallback name match is against a senior
    squad, and overlap is not computed this session. The columns stay so the
    file keeps its schema shape.
    """
    return [{
        "tournament_id": r["tournament_id"], "level": r["level"], "gender": r["gender"],
        "year": r["year"], "team": r["team"], "display_name": r["display_name"],
        "reason": r.get("join_note") or "no linked article",
        "fuzzy_match": "", "fuzzy_match_source": "", "confidence": "",
    } for r in rows if not (r.get("player_qid") or r.get("player_article"))]


def git_commit(out: Path, message: str) -> None:
    try:
        subprocess.run(["git", "add", str(out)], cwd=ROOT, check=True,
                       capture_output=True)
        done = subprocess.run(["git", "commit", "-m", message], cwd=ROOT,
                              capture_output=True, text=True)
        if done.returncode == 0:
            print(f"  committed: {message}")
        elif "nothing to commit" not in done.stdout:
            print(f"  commit failed: {done.stdout.strip() or done.stderr.strip()}")
    except subprocess.CalledProcessError as exc:
        print(f"  git error: {exc}")


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=DATA,
                    help="output directory (default: data/)")
    ap.add_argument("--only", default="",
                    help="comma-separated tournament_ids to ingest, e.g. u20m2003,u20m2011")
    ap.add_argument("--preflight", action="store_true",
                    help="run the assertions and stop, fetching no squads")
    ap.add_argument("--resume", action="store_true",
                    help="skip editions already present in the output squads.csv")
    ap.add_argument("--commit", action="store_true",
                    help="git commit after each edition")
    args = ap.parse_args()

    targets = senior_targets() + youth_targets()
    fatal = preflight(targets)
    if fatal:
        print("\nPREFLIGHT FAILED -- not fetching:")
        for f in fatal:
            print(f"  {f}")
        return 1
    if args.preflight:
        return 0

    selected = targets
    if args.only:
        wanted = {t.strip() for t in args.only.split(",") if t.strip()}
        selected = [e for e in targets if e.tid in wanted]
        unknown = wanted - {e.tid for e in selected}
        if unknown:
            print(f"\nunknown tournament_ids (not in v1 scope): {sorted(unknown)}")
            return 1

    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    partial = args.only or args.out != DATA

    # Carry forward anything already on disk for editions we are not refetching.
    keep_squads = read_csv(out / "squads.csv")
    keep_flags = read_csv(out / "integrity_flags.csv")
    keep_failures = read_csv(out / "parse_failures.csv")
    done = {r["tournament_id"] for r in keep_squads}
    if args.resume:
        skipped = [e for e in selected if e.tid in done]
        selected = [e for e in selected if e.tid not in done]
        if skipped:
            print(f"\nresume: skipping {len(skipped)} already-ingested editions")
    refetching = {e.tid for e in selected}
    keep_squads = [r for r in keep_squads if r["tournament_id"] not in refetching]
    keep_flags = [r for r in keep_flags if r["tournament_id"] not in refetching]
    keep_failures = [r for r in keep_failures if r["tournament_id"] not in refetching]

    print(f"\ningesting {len(selected)} editions -> {out}")

    results: dict[str, EditionResult] = {}
    squad_rows: list[dict] = list(keep_squads)
    flag_rows: list[dict] = list(keep_flags)
    failure_rows: list[dict] = list(keep_failures)

    for ed in selected:
        res = ingest_edition(ed)
        results[ed.tid] = res
        squad_rows.extend(res.rows)
        flag_rows.extend(f.row() for f in res.flags)
        failure_rows.extend(res.failures)

        # Persist after every edition. The VM is ephemeral; nothing is held only
        # in memory (CLAUDE.md, Operating environment).
        write_csv(out / "squads.csv", SQUAD_FIELDS, squad_rows, quiet=True)
        write_csv(out / "redlinks.csv", REDLINK_FIELDS, redlink_rows(squad_rows),
                  quiet=True)
        write_csv(out / "integrity_flags.csv", FLAG_FIELDS, flag_rows, quiet=True)
        write_csv(out / "parse_failures.csv", FAILURE_FIELDS, failure_rows, quiet=True)
        if args.commit:
            git_commit(out, f"Ingest {ed.tid}: {len(res.rows)} players, "
                            f"{len(res.teams)} teams")

    # redlinks over the whole surviving corpus, not just this run's editions
    write_csv(out / "redlinks.csv", REDLINK_FIELDS, redlink_rows(squad_rows))
    write_csv(out / "squads.csv", SQUAD_FIELDS, squad_rows)
    write_csv(out / "integrity_flags.csv", FLAG_FIELDS, flag_rows)
    write_csv(out / "parse_failures.csv", FAILURE_FIELDS, failure_rows)

    # cross-edition federation-name check, only meaningful over a full corpus
    if not partial:
        appearances: dict[str, set[str]] = defaultdict(set)
        for r in squad_rows:
            appearances[r["team"]].add(r["tournament_id"])
        variant_flags = check_name_variants(appearances)
        if variant_flags:
            flag_rows.extend(f.row() for f in variant_flags)
            write_csv(out / "integrity_flags.csv", FLAG_FIELDS, flag_rows)
            print(f"  {len(variant_flags)} federation-name variants to review")

        coverage = build_window_coverage(results, squad_rows)
        write_csv(out / "window_coverage.csv", COVERAGE_FIELDS, coverage)
        if args.commit:
            git_commit(out, "Window coverage and integrity flags for the v1 scope")
    else:
        print("\npartial run: window_coverage.csv and the federation-name check "
              "need the full corpus and were skipped")

    report(selected, results, squad_rows, flag_rows)
    return 0


def report(selected, results, squad_rows, flag_rows) -> None:
    print(f"\n{'=' * 72}\nsummary\n{'=' * 72}")
    ok = [t for t, r in results.items() if r.fetched]
    bad = [t for t, r in results.items() if not r.fetched]
    print(f"  editions attempted   {len(selected)}")
    print(f"  editions ingested    {len(ok)}")
    print(f"  editions failed      {len(bad)}" + (f"  {bad}" if bad else ""))
    errors = [f for f in flag_rows if f["severity"] == "error"]
    warns = [f for f in flag_rows if f["severity"] == "warn"]
    print(f"  integrity flags      {len(errors)} error, {len(warns)} warn")
    for check, n in Counter(f["check"] for f in flag_rows).most_common():
        print(f"      {check:26s} {n}")

    linked = sum(1 for r in squad_rows if r.get("player_qid") or r.get("player_article"))
    total = len(squad_rows)
    if total:
        print(f"  players             {total}, linked {linked}, "
              f"redlinks {total - linked} ({(total - linked) / total:.1%})")


if __name__ == "__main__":
    sys.exit(main())
