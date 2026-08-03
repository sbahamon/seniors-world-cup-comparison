# /// script
# requires-python = ">=3.11"
# dependencies = ["requests"]
# ///
"""Phase 1: validate the parser and the join on two known cases.

  Spain women  -- expected HIGH overlap (2023 senior vs U-20 2018/2022, U-17 2018)
  Nigeria men  -- expected LOW  overlap (2014/2018 senior vs U-17 2013/2015)

THIS IS NOT A MEASUREMENT. Phase 1 is a parser and join test, deliberately
exempt from the Y-4..Y-12 age window -- several of the pairings above fall
outside it. Its outputs are validation artifacts, not results.

Consequently this writes data/phase1_validation.csv, NOT data/overlap.csv.
That path is reserved by the schema for window-compliant Phase 2 output, and a
file named overlap.csv carrying a share column would be reporting withdrawn
figures. Squad-size and alumni COUNTS are kept -- they are the regression
signal on a re-run -- but the shares themselves are withdrawn and are not
computed here.

EVERY OUTPUT OF THIS SCRIPT IS PREFIXED `phase1_`. It writes
data/phase1_squads.csv, data/phase1_results.csv, data/phase1_redlinks.csv,
data/phase1_parse_failures.csv and data/phase1_validation.csv, and it writes
nothing else.

That prefix is load-bearing. This script used to write the unprefixed
data/squads.csv, data/redlinks.csv, data/parse_failures.csv and
data/results.csv -- all four of which ingest.py owns and fills with the v1
corpus. Running the regression check therefore replaced a 17,481-player
squads.csv with 174 rows and a 4,490-row redlinks.csv with 26, and the only way
back was an hour-long re-ingest. A regression check that punishes you for
running it does not get run, which costs exactly the safety net it exists to
provide. ingest.py is the sole writer of the unprefixed paths; this script must
never reclaim one.

data/results.csv is included in that rule even though nothing else writes it
today. The schema calls it hand-curated, and the three rows below are this
script's own fixture for its two validation cases -- not a curated result set.
Regenerating a hand-curated file from a hardcoded constant is the same bug
wearing a different hat.

    uv run scripts/phase1.py
"""
from __future__ import annotations

import csv
import unicodedata
import urllib.parse
from collections import defaultdict
from pathlib import Path

from fetch_page import fetch_wikitext
from squad_parser import parse_page, resolve_pages

DATA = Path(__file__).resolve().parent.parent / "data"

# (tournament_id, level, gender, year, page title, teams to keep)
SOURCES = [
    # --- Spain women: the high-overlap case ---
    ("wwc2023", "senior", "w", 2023, "2023 FIFA Women's World Cup squads", ["Spain"]),
    ("u20w2018", "u20", "w", 2018, "2018 FIFA U-20 Women's World Cup squads", ["Spain"]),
    ("u20w2022", "u20", "w", 2022, "2022 FIFA U-20 Women's World Cup squads", ["Spain"]),
    ("u17w2018", "u17", "w", 2018, "2018 FIFA U-17 Women's World Cup squads", ["Spain"]),
    # --- Nigeria men: the low-overlap control ---
    ("wc2014", "senior", "m", 2014, "2014 FIFA World Cup squads", ["Nigeria"]),
    ("wc2018", "senior", "m", 2018, "2018 FIFA World Cup squads", ["Nigeria"]),
    ("u17m2013", "u17", "m", 2013, "2013 FIFA U-17 World Cup squads", ["Nigeria"]),
    ("u17m2015", "u17", "m", 2015, "2015 FIFA U-17 World Cup squads", ["Nigeria"]),
]

# Hand-curated senior finishes (CLAUDE.md says hand-curation is fine here).
RESULTS = [
    ("Spain", "w", 2023, "Champions"),
    ("Nigeria", "m", 2014, "Round of 16"),
    ("Nigeria", "m", 2018, "Group stage"),
]


def source_url(page: str) -> str:
    return "https://en.wikipedia.org/wiki/" + urllib.parse.quote(page.replace(" ", "_"))


def fold(name: str) -> str:
    """Accent/case/punctuation-insensitive key, for redlink fallback matching only."""
    decomposed = unicodedata.normalize("NFKD", name)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return "".join(c for c in stripped.lower() if c.isalnum() or c == " ").strip()


def main() -> None:
    DATA.mkdir(exist_ok=True)

    rows: list[dict] = []
    failures: list[dict] = []

    for tid, level, gender, year, page, teams in SOURCES:
        try:
            wikitext = fetch_wikitext(page)
            players, warnings = parse_page(wikitext)
        except Exception as exc:  # noqa: BLE001 - record and move on, per CLAUDE.md
            failures.append({"tournament_id": tid, "page": page, "reason": repr(exc)})
            print(f"PARSE FAILURE {page}: {exc!r}")
            continue

        for w in warnings:
            failures.append({"tournament_id": tid, "page": page, "reason": w})

        for team in teams:
            squad = [p for p in players if p.team == team]
            if not squad:
                failures.append(
                    {"tournament_id": tid, "page": page, "reason": f"team {team!r} not found"}
                )
                print(f"PARSE FAILURE {page}: team {team!r} not found")
                continue
            for p in squad:
                rows.append(
                    {
                        "tournament_id": tid,
                        "level": level,
                        "gender": gender,
                        "year": year,
                        "team": team,
                        "shirt_no": p.shirt_no,
                        "position": p.position,
                        "player_article": p.player_article,
                        "display_name": p.display_name,
                        "source_url": source_url(page),
                        "birth_year": p.birth_year,
                    }
                )

    # Resolve every link target to canonical title + Wikidata QID in one pass.
    linked = [r["player_article"] for r in rows if r["player_article"]]
    resolved = resolve_pages(linked)
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
            # QID when there is one, canonical title as the fallback
            r["join_key"] = info.qid or f"title:{info.canonical}"
            notes = []
            if info.canonical != raw:
                notes.append(f"redirect from {raw}")
            if not info.qid:
                notes.append("no wikidata item, joined on title")
            r["join_note"] = "; ".join(notes)

    write_csv(
        DATA / "phase1_squads.csv",
        ["tournament_id", "level", "gender", "year", "team", "shirt_no",
         "position", "player_article", "player_qid", "display_name", "source_url",
         "birth_year"],
        rows,
    )
    write_csv(DATA / "phase1_results.csv", ["team", "gender", "year", "finish"],
              [dict(zip(["team", "gender", "year", "finish"], r)) for r in RESULTS])
    write_csv(DATA / "phase1_parse_failures.csv",
              ["tournament_id", "page", "reason"], failures)

    overlap_rows, redlink_rows, report = compute(rows)

    write_csv(
        DATA / "phase1_validation.csv",
        ["team", "gender", "year", "squad_size", "n_youth_alumni", "n_from_u20",
         "n_from_u17", "youth_editions_used", "finish", "note"],
        overlap_rows,
    )
    write_csv(
        DATA / "phase1_redlinks.csv",
        ["tournament_id", "level", "gender", "year", "team", "display_name",
         "reason", "fuzzy_match", "fuzzy_match_source", "confidence"],
        redlink_rows,
    )
    print(report)


def compute(rows: list[dict]) -> tuple[list[dict], list[dict], str]:
    finishes = {(t, g, y): f for t, g, y, f in RESULTS}

    youth: dict[tuple[str, str], list[dict]] = defaultdict(list)
    seniors: dict[tuple[str, str, int], list[dict]] = defaultdict(list)
    for r in rows:
        if r["level"] == "senior":
            seniors[(r["team"], r["gender"], r["year"])].append(r)
        else:
            youth[(r["team"], r["gender"])].append(r)

    overlap_rows: list[dict] = []
    redlink_rows: list[dict] = []
    out: list[str] = []

    # every unjoinable senior/youth name goes to redlinks.csv, never dropped
    for r in rows:
        if r["player_article"]:
            continue
        pool = [
            y for y in youth[(r["team"], r["gender"])]
            if r["level"] == "senior" and y["year"] < r["year"]
        ]
        hit = next((y for y in pool if fold(y["display_name"]) == fold(r["display_name"])), None)
        redlink_rows.append(
            {
                "tournament_id": r["tournament_id"],
                "level": r["level"],
                "gender": r["gender"],
                "year": r["year"],
                "team": r["team"],
                "display_name": r["display_name"],
                "reason": r["join_note"],
                "fuzzy_match": hit["display_name"] if hit else "",
                "fuzzy_match_source": hit["tournament_id"] if hit else "",
                "confidence": "low" if hit else "",
            }
        )

    for (team, gender, year), squad in sorted(seniors.items(), key=lambda kv: kv[0]):
        prior = [y for y in youth[(team, gender)] if y["year"] < year]
        editions = sorted({(y["level"], y["year"]) for y in prior})

        by_key: dict[str, list[dict]] = defaultdict(list)
        for y in prior:
            if y["join_key"]:
                by_key[y["join_key"]].append(y)

        matched, unjoinable = [], []
        for p in squad:
            if not p["join_key"]:
                unjoinable.append(p)
                continue
            hits = by_key.get(p["join_key"])
            if hits:
                matched.append((p, hits))

        # Low-confidence sweep in the other direction: a senior player who DOES
        # have an article can still be missed when their youth-squad entry was
        # never linked. Nigeria's youth pool is ~half redlinks, so this is the
        # dominant source of undercount there. Reported separately, never folded
        # into n_youth_alumni.
        unlinked_youth = {
            fold(y["display_name"]): y for y in prior if not y["player_article"]
        }
        matched_keys = {p["join_key"] for p, _ in matched}
        fuzzy_extra = [
            (p, unlinked_youth[fold(p["display_name"])])
            for p in squad
            if p["join_key"]
            and p["join_key"] not in matched_keys
            and fold(p["display_name"]) in unlinked_youth
        ]

        n_u20 = sum(1 for _, h in matched if any(x["level"] == "u20" for x in h))
        n_u17 = sum(1 for _, h in matched if any(x["level"] == "u17" for x in h))
        size = len(squad)

        overlap_rows.append(
            {
                "team": team, "gender": gender, "year": year, "squad_size": size,
                "n_youth_alumni": len(matched),
                "n_from_u20": n_u20, "n_from_u17": n_u17,
                "youth_editions_used": " ".join(
                    f"{lv}{yr}" for lv, yr in editions) or "none",
                "finish": finishes.get((team, gender, year), ""),
                "note": "validation only, window-exempt; share withheld",
            }
        )

        label = f"{team} {'women' if gender == 'w' else 'men'} {year}"
        out.append(f"\n{'=' * 68}\n{label}  --  {finishes.get((team, gender, year), '?')}\n{'=' * 68}")
        out.append(f"  senior squad size      {size}")
        out.append(
            "  youth editions used    "
            + (", ".join(f"{lv.upper()} {yr}" for lv, yr in editions) or "none")
        )
        out.append(f"  youth alumni           {len(matched)}")
        out.append(
            f"  ratio                  {len(matched)}/{size}"
            "   (validation signal, NOT an overlap result)"
        )
        out.append(f"  ...from U-20           {n_u20}")
        out.append(f"  ...from U-17           {n_u17}")
        out.append(f"  unjoinable (redlink)   {len(unjoinable)} of {size} senior players")
        if unjoinable:
            out.append("      " + ", ".join(p["display_name"] for p in unjoinable))
        n_youth_red = sum(1 for y in prior if not y["player_article"])
        out.append(f"  redlinks in youth pool {n_youth_red} of {len(prior)} youth players")
        out.append(
            f"  extra name-only hits    {len(fuzzy_extra)} (low confidence, NOT counted above)"
        )
        for p, y in fuzzy_extra:
            out.append(
                f"      {p['display_name']} ~ unlinked {y['display_name']} "
                f"({y['level'].upper()} {y['year']})"
            )

        # A senior player who was already too old for every youth edition in
        # scope could never match, no matter how good the pipeline is. Reporting
        # the share over the whole squad understates overlap unless we say so.
        cutoffs = [yr - (20 if lv == "u20" else 17) for lv, yr in editions]
        eligible = [
            p for p in squad
            if p["birth_year"] and cutoffs and int(p["birth_year"]) >= min(cutoffs)
        ]
        no_dob = sum(1 for p in squad if not p["birth_year"])
        if eligible:
            hit = sum(1 for p, _ in matched if p in eligible)
            out.append(
                f"  age-eligible for those editions: {len(eligible)} of {size}"
                + (f" ({no_dob} missing DOB)" if no_dob else "")
            )
            out.append(
                f"  share among age-eligible {hit}/{len(eligible)} = "
                f"{hit / len(eligible):.1%}"
            )

        if matched:
            out.append("  matched players:")
            for p, hits in sorted(matched, key=lambda m: int(m[0]["shirt_no"] or 0)):
                via = ", ".join(f"{x['level'].upper()} {x['year']}" for x in sorted(
                    hits, key=lambda x: x["year"]))
                out.append(f"      {p['shirt_no']:>2}  {p['display_name']:<24} via {via}")

    return overlap_rows, redlink_rows, "\n".join(out)


def write_csv(path: Path, fields: list[str], data: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(data)
    print(f"wrote {path.relative_to(DATA.parent)}  ({len(data)} rows)")


if __name__ == "__main__":
    main()
