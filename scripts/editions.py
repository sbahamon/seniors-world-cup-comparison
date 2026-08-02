# /// script
# requires-python = ">=3.11"
# dependencies = ["requests"]
# ///
"""Explicit lookup table of youth World Cup editions and their squad-page titles.

CLAUDE.md forbids constructing these titles by formatting a year into a template,
because the tournaments were renamed and a renamed page goes missing silently.
Verified against the live API on 2026-08-02; every title below returned an
existing page.

Renames that actually bite:
  men's U-20   FIFA World Youth Championship        -> FIFA U-20 World Cup   (2007)
  men's U-17   FIFA U-17 World Championship         -> FIFA U-17 World Cup   (2007)
  women's U-20 FIFA U-19 Women's World Championship -> FIFA U-20 Women's
               World Championship (2006 only)       -> FIFA U-20 Women's
               World Cup (2008)
  women's U-17 no rename; the tournament began in 2008

`not_held` is a distinct status from `failed`: the 2021 men's and 2020 women's
editions were cancelled (COVID) and the women's tournaments did not exist before
2002/2008. An edition that was never played is not a coverage gap and must not
make a squad provisional.

    uv run scripts/editions.py          # verify every title still resolves
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

import requests

from fetch_page import API, USER_AGENT

DATA = Path(__file__).resolve().parent.parent / "data"

# (level, gender, year, page title or None when no edition was held)
EDITIONS: list[tuple[str, str, int, str | None]] = [
    # --- men's U-20 -------------------------------------------------------
    ("u20", "m", 1997, "1997 FIFA World Youth Championship squads"),
    ("u20", "m", 1999, "1999 FIFA World Youth Championship squads"),
    ("u20", "m", 2001, "2001 FIFA World Youth Championship squads"),
    ("u20", "m", 2003, "2003 FIFA World Youth Championship squads"),
    ("u20", "m", 2005, "2005 FIFA World Youth Championship squads"),
    ("u20", "m", 2007, "2007 FIFA U-20 World Cup squads"),
    ("u20", "m", 2009, "2009 FIFA U-20 World Cup squads"),
    ("u20", "m", 2011, "2011 FIFA U-20 World Cup squads"),
    ("u20", "m", 2013, "2013 FIFA U-20 World Cup squads"),
    ("u20", "m", 2015, "2015 FIFA U-20 World Cup squads"),
    ("u20", "m", 2017, "2017 FIFA U-20 World Cup squads"),
    ("u20", "m", 2019, "2019 FIFA U-20 World Cup squads"),
    ("u20", "m", 2021, None),  # cancelled, COVID
    ("u20", "m", 2023, "2023 FIFA U-20 World Cup squads"),
    ("u20", "m", 2025, "2025 FIFA U-20 World Cup squads"),
    # --- men's U-17 -------------------------------------------------------
    ("u17", "m", 1997, "1997 FIFA U-17 World Championship squads"),
    ("u17", "m", 1999, "1999 FIFA U-17 World Championship squads"),
    ("u17", "m", 2001, "2001 FIFA U-17 World Championship squads"),
    ("u17", "m", 2003, "2003 FIFA U-17 World Championship squads"),
    ("u17", "m", 2005, "2005 FIFA U-17 World Championship squads"),
    ("u17", "m", 2007, "2007 FIFA U-17 World Cup squads"),
    ("u17", "m", 2009, "2009 FIFA U-17 World Cup squads"),
    ("u17", "m", 2011, "2011 FIFA U-17 World Cup squads"),
    ("u17", "m", 2013, "2013 FIFA U-17 World Cup squads"),
    ("u17", "m", 2015, "2015 FIFA U-17 World Cup squads"),
    ("u17", "m", 2017, "2017 FIFA U-17 World Cup squads"),
    ("u17", "m", 2019, "2019 FIFA U-17 World Cup squads"),
    ("u17", "m", 2021, None),  # cancelled, COVID
    ("u17", "m", 2023, "2023 FIFA U-17 World Cup squads"),
    ("u17", "m", 2025, "2025 FIFA U-17 World Cup squads"),
    # --- women's U-20 (U-19 until 2004) -----------------------------------
    ("u20", "w", 2002, "2002 FIFA U-19 Women's World Championship squads"),
    ("u20", "w", 2004, "2004 FIFA U-19 Women's World Championship squads"),
    ("u20", "w", 2006, "2006 FIFA U-20 Women's World Championship squads"),
    ("u20", "w", 2008, "2008 FIFA U-20 Women's World Cup squads"),
    ("u20", "w", 2010, "2010 FIFA U-20 Women's World Cup squads"),
    ("u20", "w", 2012, "2012 FIFA U-20 Women's World Cup squads"),
    ("u20", "w", 2014, "2014 FIFA U-20 Women's World Cup squads"),
    ("u20", "w", 2016, "2016 FIFA U-20 Women's World Cup squads"),
    ("u20", "w", 2018, "2018 FIFA U-20 Women's World Cup squads"),
    ("u20", "w", 2020, None),  # cancelled, COVID
    ("u20", "w", 2022, "2022 FIFA U-20 Women's World Cup squads"),
    ("u20", "w", 2024, "2024 FIFA U-20 Women's World Cup squads"),
    # --- women's U-17 (tournament began 2008) -----------------------------
    ("u17", "w", 2008, "2008 FIFA U-17 Women's World Cup squads"),
    ("u17", "w", 2010, "2010 FIFA U-17 Women's World Cup squads"),
    ("u17", "w", 2012, "2012 FIFA U-17 Women's World Cup squads"),
    ("u17", "w", 2014, "2014 FIFA U-17 Women's World Cup squads"),
    ("u17", "w", 2016, "2016 FIFA U-17 Women's World Cup squads"),
    ("u17", "w", 2018, "2018 FIFA U-17 Women's World Cup squads"),
    ("u17", "w", 2020, None),  # cancelled, COVID
    ("u17", "w", 2022, "2022 FIFA U-17 Women's World Cup squads"),
    ("u17", "w", 2024, "2024 FIFA U-17 Women's World Cup squads"),
]


def window(senior_year: int) -> range:
    """Eligible youth edition years for a senior tournament: Y-12..Y-4 inclusive."""
    return range(senior_year - 12, senior_year - 3)


def editions_in_window(gender: str, senior_year: int) -> list[tuple[str, str, int, str | None]]:
    yrs = window(senior_year)
    return [e for e in EDITIONS if e[1] == gender and e[2] in yrs]


# Senior World Cup editions, for reporting window denominators.
SENIOR = {
    "m": [1998, 2002, 2006, 2010, 2014, 2018, 2022, 2026],
    "w": [1991, 1995, 1999, 2003, 2007, 2011, 2015, 2019, 2023, 2027],
}


def window_counts(gender: str, senior_year: int) -> tuple[int, int]:
    """(n_editions_in_window, n_editions_held_in_window) for a senior squad.

    Held excludes `not_held` editions -- cancelled, or before the tournament
    existed. Both numbers must be carried wherever an overlap share appears; a
    squad measured against 6 held editions is not comparable to one measured
    against 8.
    """
    in_window = editions_in_window(gender, senior_year)
    return len(in_window), sum(1 for e in in_window if e[3])


def print_windows() -> None:
    for gender in ("w", "m"):
        print(f"\n{'women' if gender == 'w' else 'men'}'s senior World Cups")
        print(f"  {'year':<6}{'in window':>10}{'held':>6}{'not_held':>10}   note")
        for y in SENIOR[gender]:
            total, held = window_counts(gender, y)
            note = ""
            if held == 0:
                note = "no eligible editions -- overlap undefined"
            elif total != held:
                note = "denominator differs, not comparable to an 8-edition squad"
            print(f"  {y:<6}{total:>10}{held:>6}{total - held:>10}   {note}")


def verify() -> int:
    """Confirm every non-null page title still resolves. Returns exit code."""
    titles = [e[3] for e in EDITIONS if e[3]]
    session = requests.Session()
    bad: list[str] = []
    for i in range(0, len(titles), 50):
        batch = titles[i : i + 50]
        resp = session.get(
            API,
            params={
                "action": "query", "titles": "|".join(batch), "redirects": "1",
                "format": "json", "formatversion": "2",
            },
            headers={"User-Agent": USER_AGENT},
            timeout=40,
        )
        resp.raise_for_status()
        data = resp.json()["query"]
        chain = {}
        for key in ("normalized", "redirects"):
            for e in data.get(key, []):
                chain[e["from"]] = e["to"]
        gone = {p["title"] for p in data.get("pages", []) if p.get("missing")}
        for t in batch:
            cur, seen = t, set()
            while cur in chain and cur not in seen:
                seen.add(cur)
                cur = chain[cur]
            if cur in gone:
                bad.append(t)

    DATA.mkdir(exist_ok=True)
    with (DATA / "editions.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["level", "gender", "year", "page_title", "status"])
        for level, gender, year, title in EDITIONS:
            if title is None:
                w.writerow([level, gender, year, "", "not_held"])
            else:
                w.writerow([level, gender, year, title,
                            "failed" if title in bad else "exists"])
    print(f"wrote data/editions.csv ({len(EDITIONS)} editions)")

    held = [e for e in EDITIONS if e[3]]
    print(f"verified {len(held) - len(bad)}/{len(held)} page titles resolve")
    for t in bad:
        print(f"  MISSING: {t}")
    return 1 if bad else 0


if __name__ == "__main__":
    if "--windows" in sys.argv:
        print_windows()
        sys.exit(0)
    sys.exit(verify())
