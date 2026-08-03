# /// script
# requires-python = ">=3.11"
# dependencies = ["requests"]
# ///
"""Phase 2 overlap: write data/overlap.csv for the six v1 senior editions.

Reads only what is already on disk -- no network, no re-ingest. Inputs are
data/squads.csv (written by ingest.py), data/window_coverage_rates.csv (the
coverage half, also ingest.py) and data/results.csv (finishes, a stub).

WHAT THIS IS AND IS NOT
-----------------------
The shares written here are a diagnostic, not a finding. The question this run
exists to answer is whether measured overlap tracks English Wikipedia article
coverage rather than football; see scripts/diagnose_coverage.py. Nothing in this
file is corrected, scaled or imputed for coverage -- doing so would assume
redlinked players convert to senior squads at the same rate as covered ones,
which is exactly the open question.

JOIN KEY
--------
player_qid, per CLAUDE.md "The join key". Article titles move; QIDs do not. The
9 players in 17,481 whose article carries no Wikidata item fall back to a
title-keyed join, prefixed so a title can never collide with a QID. The 4,490
players with no linked article at all are unjoinable in either direction -- they
are in data/redlinks.csv and are counted in n_youth_pool but not in
n_youth_pool_linked. A redlinked youth player can never be counted as an
alumnus no matter how many youth tournaments they actually played.

NULL SHARES
-----------
share_youth_alumni is left empty, never 0.0, in two cases:

  n_editions_held_in_window == 0   0/0 is undefined. Cannot occur in the v1
                                   scope (all six windows hold a full 8) but the
                                   guard stays, because the withdrawn Nigeria
                                   2014 figure is what an unguarded 0/0 looks
                                   like in a table.
  n_youth_pool == 0                the federation appeared in none of its 8
                                   eligible youth editions, so there is no pool
                                   to have come up through. CLAUDE.md "Coverage
                                   bias" rules this share undefined along with
                                   the coverage rate. 32 of the 184 squads.

n_youth_alumni is still written as 0 for those squads -- the count is a real 0,
it is the *share* that is undefined. Reading the two columns together is what
distinguishes "measured, and nobody came through" from "no denominator".

n_from_u20 + n_from_u17 can exceed n_youth_alumni: a player who appeared at both
a U-17 and a U-20 in the window is counted once as an alumnus and once in each
level column.

    uv run scripts/overlap.py
    uv run scripts/overlap.py --out /tmp/check   # write elsewhere, e.g. to diff

Nothing here touches the network. `requests` is declared only because
editions.py imports it at module scope for its own title-verification mode.
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from editions import editions_in_window, window_counts  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

# CLAUDE.md "Scope for v1" -- the six senior editions with a full 8 held
# in-window editions. Kept in sync with ingest.V1_SENIOR by the check below.
V1_SENIOR: list[tuple[str, int]] = [
    ("w", 2019), ("w", 2023),
    ("m", 2010), ("m", 2014), ("m", 2018), ("m", 2022),
]

OVERLAP_FIELDS = [
    "team", "gender", "year", "squad_size", "n_youth_alumni", "share_youth_alumni",
    "n_from_u20", "n_from_u17", "finish",
    "n_youth_pool", "n_youth_pool_linked", "youth_coverage_rate",
    "n_editions_in_window", "n_editions_held_in_window",
]


def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        sys.exit(f"missing input: {path}")
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def join_key(row: dict) -> str | None:
    """QID, else a title-keyed fallback, else None (unjoinable redlink)."""
    if row.get("player_qid"):
        return row["player_qid"]
    if row.get("player_article"):
        return "title:" + row["player_article"]
    return None


def build(squads: list[dict], rates: list[dict], finishes: list[dict]) -> list[dict]:
    senior = defaultdict(list)   # (gender, year, team) -> rows
    youth = defaultdict(list)    # (gender, level, year, team) -> rows
    for r in squads:
        if r["level"] == "senior":
            senior[(r["gender"], int(r["year"]), r["team"])].append(r)
        else:
            youth[(r["gender"], r["level"], int(r["year"]), r["team"])].append(r)

    rate_index = {(r["team"], r["gender"], int(r["senior_year"])): r for r in rates}
    finish_index = {(r["team"], r["gender"], int(r["year"])): r["finish"] for r in finishes}

    rows: list[dict] = []
    for gender, senior_year in V1_SENIOR:
        window = editions_in_window(gender, senior_year)
        total, held = window_counts(gender, senior_year)
        teams = sorted({t for (g, y, t) in senior if g == gender and y == senior_year})
        if not teams:
            sys.exit(f"no senior squads in squads.csv for {gender}{senior_year}")

        for team in teams:
            squad = senior[(gender, senior_year, team)]

            # the youth pool this squad is measured against: every held in-window
            # U-20/U-17 edition this federation appeared in. not_held editions
            # (title None) contribute nothing and are already out of `held`.
            pool: list[dict] = []
            keys_by_level: dict[str, set[str]] = {"u20": set(), "u17": set()}
            for level, g, yr, title in window:
                if not title:
                    continue
                for p in youth[(g, level, yr, team)]:
                    pool.append(p)
                    k = join_key(p)
                    if k:
                        keys_by_level[level].add(k)

            all_youth_keys = keys_by_level["u20"] | keys_by_level["u17"]
            senior_keys = [join_key(p) for p in squad]
            alumni = [k for k in senior_keys if k and k in all_youth_keys]
            n_u20 = sum(1 for k in alumni if k in keys_by_level["u20"])
            n_u17 = sum(1 for k in alumni if k in keys_by_level["u17"])

            linked = sum(1 for p in pool if join_key(p))
            share = ""
            if held and pool and squad:
                share = f"{len(alumni) / len(squad):.4f}"

            # coverage columns are carried from window_coverage_rates.csv, which
            # is the file of record for them; recomputing here is a cross-check,
            # not a second source of truth.
            rate = rate_index.get((team, gender, senior_year))
            if rate is None:
                sys.exit(f"no window_coverage_rates row for {team} {gender}{senior_year}")
            if int(rate["n_youth_pool"]) != len(pool) or int(rate["n_youth_pool_linked"]) != linked:
                sys.exit(
                    f"pool mismatch for {team} {gender}{senior_year}: "
                    f"rates says {rate['n_youth_pool']}/{rate['n_youth_pool_linked']}, "
                    f"recomputed {len(pool)}/{linked}"
                )

            rows.append({
                "team": team, "gender": gender, "year": senior_year,
                "squad_size": len(squad),
                "n_youth_alumni": len(alumni),
                "share_youth_alumni": share,
                "n_from_u20": n_u20, "n_from_u17": n_u17,
                "finish": finish_index.get((team, gender, senior_year), ""),
                "n_youth_pool": rate["n_youth_pool"],
                "n_youth_pool_linked": rate["n_youth_pool_linked"],
                "youth_coverage_rate": rate["youth_coverage_rate"],
                "n_editions_in_window": total,
                "n_editions_held_in_window": held,
            })
    return rows


def report(rows: list[dict]) -> None:
    print(f"\n{len(rows)} senior squads written to overlap.csv")
    undefined = [r for r in rows if not r["share_youth_alumni"]]
    print(f"  {len(undefined)} with an undefined share (empty in-window youth pool)")
    nofinish = sum(1 for r in rows if not r["finish"])
    print(f"  {nofinish} with no finish -- results.csv is a stub, not curated")

    print(f"\n  {'edition':<10}{'squads':>7}{'defined':>9}{'mean share':>12}"
          f"{'mean cov':>10}")
    for gender, year in V1_SENIOR:
        sub = [r for r in rows if r["gender"] == gender and int(r["year"]) == year]
        defined = [r for r in sub if r["share_youth_alumni"]]
        ms = sum(float(r["share_youth_alumni"]) for r in defined) / len(defined)
        cov = [float(r["youth_coverage_rate"]) for r in sub if r["youth_coverage_rate"]]
        print(f"  {gender}{year:<9}{len(sub):>7}{len(defined):>9}{ms:>11.1%}"
              f"{sum(cov)/len(cov):>10.1%}")
    print("\n  Shares are a coverage diagnostic, not a finding. Provisional -- the"
          "\n  redlink gap is unresolved on both sides. Y-4..Y-12 window truncates"
          "\n  unusually long senior careers, uniformly across teams.")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=DATA)
    args = ap.parse_args()

    squads = read_csv(DATA / "squads.csv")
    rates = read_csv(DATA / "window_coverage_rates.csv")
    finishes = read_csv(DATA / "results.csv")

    rows = build(squads, rates, finishes)
    if len(rows) != len(rates):
        sys.exit(f"row count {len(rows)} != window_coverage_rates {len(rates)}")

    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / "overlap.csv"
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=OVERLAP_FIELDS)
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {path}")
    report(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
