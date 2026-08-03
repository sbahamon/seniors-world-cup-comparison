#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Build the static project page's chart data from the committed CSVs.

Reads `data/window_coverage_rates.csv` and `data/overlap.csv` and rewrites the
generated block inside `docs/index.html` in place. The page therefore ships its
own data and fetches nothing at runtime.

This script computes nothing new about football. It reshapes columns that
`ingest.py` and `overlap.py` already wrote, and adds one display-level quantity:
a Wilson 95% interval on `n_youth_alumni / squad_size` for the surviving set, so
the overlap chart can show sampling uncertainty rather than a bare point. That
interval covers sampling only -- it does not cover the redlink gap, and the page
says so beside the chart.

It is not a writer of anything under `data/`.

    uv run scripts/build_site.py
"""

from __future__ import annotations

import csv
import json
import math
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RATES = ROOT / "data" / "window_coverage_rates.csv"
OVERLAP = ROOT / "data" / "overlap.csv"
PAGE = ROOT / "docs" / "index.html"

BEGIN = "/* BEGIN GENERATED DATA -- built by scripts/build_site.py */"
END = "/* END GENERATED DATA */"

# The intersection thresholds published in reports/intersection.md. Kept here so
# the page draws the same surviving set the report describes.
MAX_REDLINK = 0.30
MIN_EDITIONS = 5

EDITION_LABEL = {
    ("m", "2010"): "Men's 2010",
    ("m", "2014"): "Men's 2014",
    ("m", "2018"): "Men's 2018",
    ("m", "2022"): "Men's 2022",
    ("w", "2019"): "Women's 2019",
    ("w", "2023"): "Women's 2023",
}
EDITION_ORDER = ["m2010", "m2014", "m2018", "m2022", "w2019", "w2023"]


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for k successes in n trials."""
    if n == 0:
        raise ValueError("empty denominator")
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z / denom * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return max(0.0, centre - half), min(1.0, centre + half)


def read(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def build() -> dict:
    rates = read(RATES)
    overlap = read(OVERLAP)

    by_key = {(r["team"], r["gender"], r["senior_year"]): r for r in rates}

    # ---- (1) qualification frequency: all 184 squads -----------------------
    counts = Counter((r["gender"], int(r["n_editions_ingested"])) for r in rates)
    qualification = {
        "bins": list(range(9)),
        "m": [counts[("m", k)] for k in range(9)],
        "w": [counts[("w", k)] for k in range(9)],
        "n_squads": len(rates),
        "n_men": sum(1 for r in rates if r["gender"] == "m"),
        "n_women": sum(1 for r in rates if r["gender"] == "w"),
    }
    full_house = sorted(
        f"{r['team']} ({EDITION_LABEL[(r['gender'], r['senior_year'])]})"
        for r in rates
        if int(r["n_editions_ingested"]) == 8
    )
    qualification["full_house"] = full_house
    qualification["n_zero"] = sum(
        1 for r in rates if int(r["n_editions_ingested"]) == 0
    )

    # ---- (2) the surviving set: overlap with uncertainty -------------------
    measurable = []
    for o in overlap:
        if not o["share_youth_alumni"] or not o["youth_coverage_rate"]:
            continue
        r = by_key[(o["team"], o["gender"], o["year"])]
        redlink = 1.0 - float(o["youth_coverage_rate"])
        eds = int(r["n_editions_ingested"])
        if redlink >= MAX_REDLINK or eds < MIN_EDITIONS:
            continue
        alumni, squad = int(o["n_youth_alumni"]), int(o["squad_size"])
        lo, hi = wilson(alumni, squad)
        measurable.append(
            {
                "team": o["team"],
                "gender": o["gender"],
                "year": o["year"],
                "edition": f"{o['gender']}{o['year']}",
                "edition_label": EDITION_LABEL[(o["gender"], o["year"])],
                "share": round(float(o["share_youth_alumni"]), 4),
                "lo": round(lo, 4),
                "hi": round(hi, 4),
                "alumni": alumni,
                "squad": squad,
                "redlink": round(redlink, 4),
                "editions": eds,
                "pool": int(o["n_youth_pool"]),
                "u20": int(o["n_from_u20"]),
                "u17": int(o["n_from_u17"]),
            }
        )
    # Alphabetical by federation, then by edition. Deliberately not by share:
    # a share-ordered chart reads as a ranking the data cannot support.
    measurable.sort(key=lambda d: (d["team"], EDITION_ORDER.index(d["edition"])))
    federations = sorted({d["team"] for d in measurable})

    # ---- (3) dispersion: per-federation windowed redlink rates -------------
    dispersion: dict[str, list] = {"m": [], "w": []}
    for o in overlap:
        if not o["youth_coverage_rate"]:
            continue
        dispersion[o["gender"]].append(
            {
                "team": o["team"],
                "label": f"{o['team']} · {EDITION_LABEL[(o['gender'], o['year'])]}",
                "redlink": round(1.0 - float(o["youth_coverage_rate"]), 4),
                "pool": int(o["n_youth_pool"]),
            }
        )
    for g in dispersion:
        dispersion[g].sort(key=lambda d: d["redlink"])

    # ---- (4) the funnel ----------------------------------------------------
    defined = [
        o for o in overlap if o["share_youth_alumni"] and o["youth_coverage_rate"]
    ]
    passes_cov = [
        o for o in defined if 1.0 - float(o["youth_coverage_rate"]) < MAX_REDLINK
    ]
    funnel = [
        {
            "label": "Senior squads in scope",
            "squads": len(overlap),
            "feds": len({o["team"] for o in overlap}),
            "note": "Six senior World Cups, 2010–2023.",
        },
        {
            "label": "Overlap is defined",
            "squads": len(defined),
            "feds": len({o["team"] for o in defined}),
            "note": f"{len(overlap) - len(defined)} squads appeared in none of their eight "
            "eligible youth editions. Their share is undefined, not zero.",
        },
        {
            "label": "Coverage filter: under 30% redlink",
            "squads": len(passes_cov),
            "feds": len({o["team"] for o in passes_cov}),
            "note": "Above roughly 30% unjoinable players, measured overlap starts "
            "tracking article coverage instead of football.",
        },
        {
            "label": "Precision filter: 5+ of 8 youth editions",
            "squads": len(measurable),
            "feds": len(federations),
            "note": "A federation that reached one youth edition has a 21-player "
            "pool and mechanically almost no chance of a high share.",
        },
    ]

    return {
        "qualification": qualification,
        "measurable": measurable,
        "federations": federations,
        "dispersion": dispersion,
        "funnel": funnel,
        "thresholds": {"redlink": MAX_REDLINK, "editions": MIN_EDITIONS},
    }


def main() -> None:
    data = build()
    payload = json.dumps(data, ensure_ascii=False, indent=None, separators=(",", ":"))

    html = PAGE.read_text(encoding="utf-8")
    start = html.index(BEGIN) + len(BEGIN)
    stop = html.index(END)
    html = html[:start] + "\nconst DATA = " + payload + ";\n" + html[stop:]
    PAGE.write_text(html, encoding="utf-8")

    q = data["qualification"]
    print(f"qualification: {q['n_squads']} squads ({q['n_men']}m / {q['n_women']}w), "
          f"{q['n_zero']} at zero editions, {len(q['full_house'])} at 8 of 8")
    print(f"measurable:    {len(data['measurable'])} squads, "
          f"{len(data['federations'])} federations")
    print(f"dispersion:    {len(data['dispersion']['m'])} men's / "
          f"{len(data['dispersion']['w'])} women's squads with a defined rate")
    for step in data["funnel"]:
        print(f"funnel:        {step['squads']:>3} squads / {step['feds']:>2} feds  "
              f"{step['label']}")
    print(f"wrote {PAGE.relative_to(ROOT)} ({len(payload):,} bytes of data)")


if __name__ == "__main__":
    main()
