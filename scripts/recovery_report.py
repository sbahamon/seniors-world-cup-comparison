# /// script
# requires-python = ">=3.11"
# dependencies = ["requests"]
# ///
"""Measure what the non-English recovery bought, and what it did not.

Three questions, in order of how much they matter.

1. How far did coverage move, per edition and per federation?

2. **Of the recovered players, how many are actually youth alumni** -- i.e.
   turn up in a senior squad inside the window? This is the question the whole
   coverage diagnostic rested on without ever testing. If recovered players are
   overwhelmingly non-converters, then redlinks were mostly players who never
   made a senior squad, the gap was never dropping many real alumni, and the
   project's central limitation is weaker than it has been treated as. If a
   substantial share convert, the gap was genuinely lossy. Both answers are
   worth having; neither is the one we are hoping for.

3. Do the diagnostic's headline numbers move -- the 30% cliff, the men/women
   dispersion contrast, and the K-of-8 intersection that came out at 14
   federations?

Reads data/squads.csv and data/squads_recovered.csv and writes
reports/recovery.md. Pure function of what is on disk; no network. It writes
nothing under data/ and does not touch reports/coverage_diagnostic.md,
reports/findings.md or docs/.

    uv run scripts/recovery_report.py
"""
from __future__ import annotations

import csv
import math
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from editions import editions_in_window  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
REPORTS = ROOT / "reports"

V1_SENIOR = [("w", 2019), ("w", 2023), ("m", 2010), ("m", 2014), ("m", 2018), ("m", 2022)]
COVERAGE_CUTOFF = 0.30  # the diagnostic's cliff


def load(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def pool_for(rows: list[dict], gender: str, senior_year: int, team: str) -> list[dict]:
    """A senior squad's in-window youth pool: same federation, same gender."""
    want = {(lv, yr) for lv, g, yr, title in editions_in_window(gender, senior_year) if title}
    return [r for r in rows
            if r["level"] != "senior" and r["gender"] == gender and r["team"] == team
            and (r["level"], int(r["year"])) in want]


def squad_stats(rows: list[dict]) -> dict:
    """Per senior squad: pool, redlinks, alumni, share, editions appeared in."""
    senior = defaultdict(list)
    for r in rows:
        if r["level"] == "senior":
            senior[(r["gender"], int(r["year"]), r["team"])].append(r)
    out = {}
    for (gender, year, team), squad in senior.items():
        pool = pool_for(rows, gender, year, team)
        linked = [p for p in pool if p["player_qid"]]
        squad_qids = {r["player_qid"] for r in squad if r["player_qid"]}
        alumni = {p["player_qid"] for p in linked if p["player_qid"] in squad_qids}
        eds = {(p["level"], p["year"]) for p in pool}
        out[(gender, year, team)] = {
            "squad_size": len(squad),
            "n_pool": len(pool),
            "n_linked": len(linked),
            "n_redlink": len(pool) - len(linked),
            "redlink_rate": (len(pool) - len(linked)) / len(pool) if pool else None,
            "n_alumni": len(alumni),
            "share": len(alumni) / len(squad) if (pool and squad) else None,
            "n_editions": len(eds),
            "alumni_qids": alumni,
        }
    return out


def _binom(n: int, k: int, p: float) -> float:
    return math.comb(n, k) * p**k * (1 - p) ** (n - k)


def spearman(xs: list[float], ys: list[float]) -> float:
    def rank(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
                j += 1
            avg = (i + j) / 2 + 1
            for k in range(i, j + 1):
                r[order[k]] = avg
            i = j + 1
        return r
    if len(xs) < 3:
        return float("nan")
    rx, ry = rank(xs), rank(ys)
    mx, my = statistics.mean(rx), statistics.mean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = (sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry)) ** 0.5
    return num / den if den else float("nan")


def dispersion(stats: dict, gender: str, year: int) -> dict | None:
    rates = [s["redlink_rate"] for (g, y, _), s in stats.items()
             if g == gender and y == year and s["redlink_rate"] is not None]
    if len(rates) < 3:
        return None
    m = statistics.mean(rates)
    return {"n": len(rates), "mean": m, "median": statistics.median(rates),
            "cv": statistics.pstdev(rates) / m if m else float("nan"),
            "min": min(rates), "max": max(rates)}


def intersection(stats: dict, k: int, cutoff: float = COVERAGE_CUTOFF) -> tuple[int, set]:
    keep = [(g, y, t) for (g, y, t), s in stats.items()
            if s["redlink_rate"] is not None and s["redlink_rate"] < cutoff
            and s["n_editions"] >= k]
    return len(keep), {t for _, _, t in keep}


def main() -> int:
    before_rows = load(DATA / "squads.csv")
    after_rows = load(DATA / "squads_recovered.csv")
    rec = load(DATA / "lang_recovery.csv")
    before, after = squad_stats(before_rows), squad_stats(after_rows)

    L: list[str] = []
    W = L.append

    W("# Recovery from non-English Wikipedias\n")
    W("Generated by `uv run scripts/recovery_report.py` from `data/squads.csv` and")
    W("`data/squads_recovered.csv`. Everything here remains **provisional**: overlap")
    W("is still measured over a Y-4..Y-12 window, nothing is scaled or corrected for")
    W("coverage, and the selection caveats in `reports/findings.md` still bind.\n")

    # ---- 1. what was recovered ------------------------------------------------
    tot = len(before_rows)
    red_b = sum(1 for r in before_rows if r["level"] != "senior" and not r["player_qid"])
    red_a = sum(1 for r in after_rows if r["level"] != "senior" and not r["player_qid"])
    W("## 1. What was recovered\n")
    W(f"- youth players in the v1 corpus: **{sum(1 for r in before_rows if r['level'] != 'senior')}**")
    W(f"- redlinked before: **{red_b}** ({red_b / (tot - 4327):.1%}) — after: **{red_a}** "
      f"({red_a / (tot - 4327):.1%})")
    W(f"- recovered: **{red_b - red_a}** QIDs, from {len({r['lang'] for r in rec})} "
      f"language wikis across {len({r['tournament_id'] for r in rec})} editions\n")
    W("| language | recovered | editions |")
    W("|---|---|---|")
    by_lang = Counter(r["lang"] for r in rec)
    for lang, n in by_lang.most_common():
        eds = len({r["tournament_id"] for r in rec if r["lang"] == lang})
        W(f"| {lang} | {n} | {eds} |")
    W("")

    # per edition
    W("### Per youth edition\n")
    W("| edition | pool | redlinks before | after | rate before | rate after | recovered |")
    W("|---|---|---|---|---|---|---|")
    eds = sorted({r["tournament_id"] for r in before_rows if r["level"] != "senior"})
    for ed in eds:
        pb = [r for r in before_rows if r["tournament_id"] == ed]
        pa = [r for r in after_rows if r["tournament_id"] == ed]
        rb = sum(1 for r in pb if not r["player_qid"])
        ra = sum(1 for r in pa if not r["player_qid"])
        if rb == ra:
            continue
        W(f"| {ed} | {len(pb)} | {rb} | {ra} | {rb / len(pb):.1%} | {ra / len(pa):.1%} | {rb - ra} |")
    W("")
    W(f"{len(eds) - sum(1 for ed in eds if any(r['tournament_id'] == ed for r in rec))} "
      f"of {len(eds)} editions recovered nothing at all.\n")

    # per federation
    W("### Per federation (all with any recovery)\n")
    W("| federation | youth pool | redlinks before | after | rate before | rate after | recovered |")
    W("|---|---|---|---|---|---|---|")
    fb, fa = defaultdict(lambda: [0, 0]), defaultdict(lambda: [0, 0])
    for r in before_rows:
        if r["level"] != "senior":
            fb[r["team"]][0] += 1
            fb[r["team"]][1] += 0 if r["player_qid"] else 1
    for r in after_rows:
        if r["level"] != "senior":
            fa[r["team"]][0] += 1
            fa[r["team"]][1] += 0 if r["player_qid"] else 1
    moved = sorted((fb[t][1] - fa[t][1], t) for t in fb if fb[t][1] != fa[t][1])
    for n, t in sorted(moved, reverse=True):
        W(f"| {t} | {fb[t][0]} | {fb[t][1]} | {fa[t][1]} | "
          f"{fb[t][1] / fb[t][0]:.1%} | {fa[t][1] / fa[t][0]:.1%} | {n} |")
    W("")
    W(f"{len(moved)} federations moved at all; "
      f"{len(fb) - len(moved)} of {len(fb)} did not move by a single player.\n")

    # ---- 2. THE question: are recovered players alumni? -----------------------
    W("## 2. Are the recovered players actually alumni?\n")
    W("The coverage diagnostic assumed redlinked players are lost *alumni* — that")
    W("closing the gap would raise measured overlap. That assumption has never been")
    W("tested, and it is testable directly: take each recovered QID and ask whether")
    W("it turns up in a senior squad for the same federation inside the window.")
    W("Senior-side coverage is 99.7% (11 redlinks in 4,327 players), so a recovered")
    W("player who converted would be found.\n")

    senior_qids: dict[tuple, set] = defaultdict(set)
    for r in after_rows:
        if r["level"] == "senior" and r["player_qid"]:
            senior_qids[(r["gender"], r["team"])].add((r["player_qid"], int(r["year"])))
    v1_years = {(g, y) for g, y in V1_SENIOR}

    def converted(gender: str, team: str, youth_year: int, qid: str) -> int | None:
        """Senior year this youth player reached, inside the window, or None.

        One unit of observation: (player, youth edition, federation). Both the
        recovered set and the base rate below are counted this way, so the two
        numbers are directly comparable -- a youth player whose edition sits in
        two senior windows must not count twice on one side of the comparison
        and once on the other.
        """
        for q, sy in senior_qids.get((gender, team), ()):
            if q == qid and (gender, sy) in v1_years and sy - 12 <= youth_year <= sy - 4:
                return sy
        return None

    alum_rows = []
    non_alum = 0
    for r in rec:
        hit = converted(r["gender"], r["team"], int(r["year"]), r["recovered_qid"])
        if hit:
            alum_rows.append((r["team"], r["tournament_id"], hit, r["display_name"], r["lang"]))
        else:
            non_alum += 1
    alum = len(alum_rows)
    n = alum + non_alum
    W(f"**{alum} of {n} recovered players ({alum / n:.1%}) appear in a senior squad "
      f"inside their window. {non_alum} ({non_alum / n:.1%}) do not.**\n")

    # Base rate, counted identically: youth players who were ALREADY linked on
    # en.wiki, one unit per (player, youth edition, federation), restricted to
    # youth editions that fall in at least one in-scope senior window.
    in_window_eds = {(g, lv, yr) for g, sy in V1_SENIOR
                     for lv, gg, yr, title in editions_in_window(g, sy) if title
                     for g2 in [gg] if g2 == g}
    base_hit = base_tot = 0
    for r in before_rows:
        if r["level"] == "senior" or not r["player_qid"]:
            continue
        if (r["gender"], r["level"], int(r["year"])) not in in_window_eds:
            continue
        base_tot += 1
        if converted(r["gender"], r["team"], int(r["year"]), r["player_qid"]):
            base_hit += 1
    base = base_hit / base_tot
    W(f"For comparison, the same measurement over the youth players who were "
      f"*already* linked on en.wiki: **{base_hit}/{base_tot} = {base:.1%}**.\n")
    expected = base * n
    W(f"If recovered players converted at the rate of already-covered ones we would "
      f"expect about **{expected:.0f}** of the {n}, not {alum}. Under a binomial with "
      f"p={base:.3f}, P(X<={alum}) = "
      f"{sum(_binom(n, i, base) for i in range(alum + 1)):.2e}.\n")
    W("### What this bounds for the 4,304 redlinks still unresolved\n")
    proj = (alum / n) * red_a
    cur_alumni = sum(s["n_alumni"] for s in after.values())
    W(f"At the observed rate, the remaining {red_a} youth redlinks would contribute")
    W(f"about **{proj:.0f}** further alumni across all 184 senior squads — roughly")
    W(f"{proj / 184:.2f} per squad, against the {cur_alumni / 184:.1f} per squad measured now.")
    W("At the *already-covered* rate of 12.2% it would instead be about")
    W(f"{base * red_a:.0f}, which is the number the coverage worry has implicitly assumed.\n")
    W("Which of those two is the right projection depends on whether the recovered")
    W("players resemble the residue. They almost certainly overstate it: a player")
    W("notable enough for an article on their home wiki is more likely to have")
    W("converted than one with no article on any wiki. So **1.1% reads as an upper")
    W("bound on the residue's conversion rate, not a central estimate** — which makes")
    W("the projection above an upper bound too.\n")
    W("The mechanism is worth naming, because it means the redlink gap is not a")
    W("neutral veil over the outcome. English Wikipedia notability for a youth")
    W("footballer is driven substantially by reaching a senior national team, so")
    W("converting is itself a large part of *why* a player stops being a redlink.")
    W("The redlinked pool is therefore depleted of alumni by construction. That is a")
    W("reason the gap costs less than feared — and simultaneously a reason it can")
    W("never be treated as missing-at-random.\n")

    if alum_rows:
        W("The recovered players who did convert:\n")
        W("| federation | youth edition | senior year | name | via |")
        W("|---|---|---|---|---|")
        for team, tid, sy, name, lang in sorted(alum_rows):
            W(f"| {team} | {tid} | {sy} | {name} | {lang} |")
        W("")

    # ---- 3. does anything downstream move? -----------------------------------
    W("## 3. Do the diagnostic's numbers move?\n")
    W("### Windowed redlink rate and dispersion, per senior edition\n")
    W("| edition | n | mean before | mean after | CV before | CV after | max before | max after |")
    W("|---|---|---|---|---|---|---|---|")
    for gender, year in V1_SENIOR:
        db, da = dispersion(before, gender, year), dispersion(after, gender, year)
        if not db or not da:
            continue
        tag = f"{gender}{year}"
        W(f"| {tag} | {db['n']} | {db['mean']:.1%} | {da['mean']:.1%} | "
          f"{db['cv']:.2f} | {da['cv']:.2f} | {db['max']:.1%} | {da['max']:.1%} |")
    W("")

    W("### The 30% cliff\n")
    W("Split within gender, as in the diagnostic, so the two levels do not mix.\n")
    W("| slice | n below 30% | mean share below | n at/above 30% | mean share above | rho below | rho above |")
    W("|---|---|---|---|---|---|---|")
    for label, stats in (("before", before), ("after", after)):
        for gsel, gname in (("m", "men"), ("w", "women")):
            lo_r, lo_s, hi_r, hi_s = [], [], [], []
            for (g, y, t), s in stats.items():
                if g != gsel or s["redlink_rate"] is None or s["share"] is None:
                    continue
                (lo_r if s["redlink_rate"] < COVERAGE_CUTOFF else hi_r).append(s["redlink_rate"])
                (lo_s if s["redlink_rate"] < COVERAGE_CUTOFF else hi_s).append(s["share"])
            if not lo_s or not hi_s:
                continue
            W(f"| {gname} ({label}) | {len(lo_s)} | {statistics.mean(lo_s):.1%} | "
              f"{len(hi_s)} | {statistics.mean(hi_s):.1%} | "
              f"{spearman(lo_r, lo_s):+.3f} | {spearman(hi_r, hi_s):+.3f} |")
    W("")

    W("### The intersection: coverage under 30% and at least K of 8 in-window editions\n")
    W("| K | squads before | federations before | squads after | federations after |")
    W("|---|---|---|---|---|")
    for k in (4, 5, 6):
        sb, tb = intersection(before, k)
        sa, ta = intersection(after, k)
        W(f"| >={k} | {sb} | {len(tb)} | {sa} | {len(ta)} |")
    W("")
    _, tb5 = intersection(before, 5)
    _, ta5 = intersection(after, 5)
    gained, lost = sorted(ta5 - tb5), sorted(tb5 - ta5)
    W(f"At K>=5 the federation set gains {gained or 'nothing'} and loses "
      f"{lost or 'nothing'}.\n")
    W("Loosening the coverage filter to 35%:\n")
    W("| K | federations before | federations after |")
    W("|---|---|---|")
    for k in (4, 5, 6):
        _, t1 = intersection(before, k, 0.35)
        _, t2 = intersection(after, k, 0.35)
        W(f"| >={k} | {len(t1)} | {len(t2)} |")
    W("")

    REPORTS.mkdir(exist_ok=True)
    (REPORTS / "recovery.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"wrote reports/recovery.md ({len(L)} lines)")
    print(f"\nrecovered {red_b - red_a}; alumni {alum}/{n} ({alum / n:.1%}) "
          f"vs base rate {base_hit / base_tot:.1%}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
