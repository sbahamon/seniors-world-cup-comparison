# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Is measured overlap tracking football, or English Wikipedia article coverage?

Two questions, both about whether a cross-federation comparison is salvageable.

(a) DISPERSION, not level. The aggregate redlink rate is the wrong statistic.
    A uniform 42% miss rate attenuates every federation by roughly the same
    factor and largely preserves ordering; a bimodal 0%-to-86% spread destroys
    it. So what matters per senior edition is the spread of the per-federation
    windowed redlink rate, not its mean.

(b) CORRELATION between a federation's redlink rate and its measured overlap
    share, within each senior edition and pooled. A strong negative correlation
    means measured overlap is substantially tracking article coverage rather
    than football.

Nothing here corrects, scales or imputes for coverage. Reporting the gap is the
point; modelling it away would assume redlinked players convert at the same rate
as covered ones, which is the open question.

CONTROLS. Two confounds are reported alongside the raw correlation rather than
left implicit:

  n_editions_ingested  a federation that appeared in 2 of its 8 in-window youth
                       editions has both a small pool and fewer chances to have
                       produced an alumnus. If that drives both variables the
                       raw correlation overstates the coverage effect, so a
                       partial rank correlation holding it fixed is reported.
  edition              pooling across senior editions mixes six different share
                       and coverage levels, which can manufacture a correlation
                       out of between-edition differences alone. The pooled
                       figure is therefore also reported on within-edition
                       centred ranks (edition fixed effects).

Squads with an empty in-window youth pool are excluded throughout: their
coverage rate and their share are both undefined, not zero.

    uv run scripts/diagnose_coverage.py
"""

from __future__ import annotations

import csv
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
REPORTS = ROOT / "reports"

EDITIONS = [("w", 2019), ("w", 2023), ("m", 2010), ("m", 2014), ("m", 2018), ("m", 2022)]
PERM_N = 20000
SEED = 20260803


# --------------------------------------------------------------------------
# statistics, hand-rolled to keep this dependency-free
# --------------------------------------------------------------------------

def mean(xs: list[float]) -> float:
    return sum(xs) / len(xs)


def quantile(xs: list[float], q: float) -> float:
    """Linear-interpolation quantile on a sorted copy (numpy's default)."""
    s = sorted(xs)
    if len(s) == 1:
        return s[0]
    pos = q * (len(s) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def stdev(xs: list[float]) -> float:
    if len(xs) < 2:
        return 0.0
    m = mean(xs)
    return (sum((x - m) ** 2 for x in xs) / (len(xs) - 1)) ** 0.5


def pearson(xs: list[float], ys: list[float]) -> float:
    mx, my = mean(xs), mean(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = sum((x - mx) ** 2 for x in xs) ** 0.5
    dy = sum((y - my) ** 2 for y in ys) ** 0.5
    return num / (dx * dy) if dx and dy else 0.0


def ranks(xs: list[float]) -> list[float]:
    """Average ranks, ties shared."""
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    out = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        avg = (i + j) / 2 + 1
        for k in range(i, j + 1):
            out[order[k]] = avg
        i = j + 1
    return out


def spearman(xs: list[float], ys: list[float]) -> float:
    return pearson(ranks(xs), ranks(ys))


def perm_p(xs: list[float], ys: list[float], stat, n: int = PERM_N) -> float:
    """Two-sided permutation p-value. Small n here, so exact-ish beats a t-approx."""
    obs = abs(stat(xs, ys))
    rng = random.Random(SEED)
    shuffled = list(ys)
    hits = 0
    for _ in range(n):
        rng.shuffle(shuffled)
        if abs(stat(xs, shuffled)) >= obs - 1e-12:
            hits += 1
    return (hits + 1) / (n + 1)


def residualise(y: list[float], x: list[float]) -> list[float]:
    """Residuals of y on x by OLS -- used on ranks, giving a partial rank corr."""
    mx, my = mean(x), mean(y)
    denom = sum((v - mx) ** 2 for v in x)
    b = sum((v - mx) * (w - my) for v, w in zip(x, y)) / denom if denom else 0.0
    return [w - (my + b * (v - mx)) for v, w in zip(x, y)]


# --------------------------------------------------------------------------
# data
# --------------------------------------------------------------------------

class Squad:
    __slots__ = ("team", "gender", "year", "share", "redlink", "pool",
                 "n_ing", "size", "alumni")

    def __init__(self, r: dict):
        self.team = r["team"]
        self.gender = r["gender"]
        self.year = int(r["year"])
        self.size = int(r["squad_size"])
        self.alumni = int(r["n_youth_alumni"])
        self.share = float(r["share_youth_alumni"]) if r["share_youth_alumni"] else None
        self.pool = int(r["n_youth_pool"])
        cov = r["youth_coverage_rate"]
        self.redlink = 1.0 - float(cov) if cov else None
        self.n_ing = 0

    @property
    def label(self) -> str:
        return f"{self.team} {self.gender}{self.year}"


def load() -> list[Squad]:
    with (DATA / "overlap.csv").open(newline="", encoding="utf-8") as fh:
        squads = [Squad(r) for r in csv.DictReader(fh)]
    with (DATA / "window_coverage_rates.csv").open(newline="", encoding="utf-8") as fh:
        ing = {(r["team"], r["gender"], int(r["senior_year"])): int(r["n_editions_ingested"])
               for r in csv.DictReader(fh)}
    for s in squads:
        s.n_ing = ing[(s.team, s.gender, s.year)]
    return squads


# --------------------------------------------------------------------------
# (a) dispersion
# --------------------------------------------------------------------------

def dispersion(squads: list[Squad], out: list[str]) -> None:
    out.append("## (a) Per-federation windowed redlink rate, by senior edition\n")
    out.append("Redlink rate = share of a federation's in-window youth pool that carries")
    out.append("no joinable article. Squads with an empty pool are excluded (undefined,")
    out.append("not 0%). Dispersion is what decides whether ranking survives; the mean")
    out.append("only decides the level.\n")
    out.append("| edition | n | mean | median | IQR | p10 | p90 | min | max | CV |")
    out.append("|---|---|---|---|---|---|---|---|---|---|")
    for gender, year in EDITIONS:
        rs = [s.redlink for s in squads
              if s.gender == gender and s.year == year and s.redlink is not None]
        m = mean(rs)
        iqr = quantile(rs, 0.75) - quantile(rs, 0.25)
        out.append(
            f"| {gender}{year} | {len(rs)} | {m:.1%} | {quantile(rs, 0.5):.1%} | "
            f"{iqr:.1%} | {quantile(rs, 0.1):.1%} | {quantile(rs, 0.9):.1%} | "
            f"{min(rs):.1%} | {max(rs):.1%} | {stdev(rs)/m:.2f} |"
        )

    out.append("\n### Extremes, and how thin the pools behind them are\n")
    for gender, year in EDITIONS:
        sub = sorted([s for s in squads
                      if s.gender == gender and s.year == year and s.redlink is not None],
                     key=lambda s: s.redlink)
        best = ", ".join(f"{s.team} {s.redlink:.0%} (pool {s.pool})" for s in sub[:3])
        worst = ", ".join(f"{s.team} {s.redlink:.0%} (pool {s.pool})" for s in sub[-3:][::-1])
        out.append(f"- **{gender}{year}** best: {best} — worst: {worst}")

    out.append("\n### Men vs women, on dispersion rather than level\n")
    for g, name in (("m", "men"), ("w", "women")):
        rs = [s.redlink for s in squads if s.gender == g and s.redlink is not None]
        iqrs, cvs = [], []
        for gender, year in EDITIONS:
            if gender != g:
                continue
            e = [s.redlink for s in squads
                 if s.gender == g and s.year == year and s.redlink is not None]
            iqrs.append(quantile(e, 0.75) - quantile(e, 0.25))
            cvs.append(stdev(e) / mean(e))
        out.append(f"- {name}: pooled mean {mean(rs):.1%}, per-edition IQR "
                   f"{min(iqrs):.1%}–{max(iqrs):.1%}, per-edition CV "
                   f"{min(cvs):.2f}–{max(cvs):.2f}")


# --------------------------------------------------------------------------
# (b) correlation
# --------------------------------------------------------------------------

def scatter_shape(sub: list[Squad], out: list[str]) -> None:
    """Quartile bins of redlink rate -- says whether the pattern is broad or
    a couple of extreme federations doing all the work."""
    ordered = sorted(sub, key=lambda s: s.redlink)
    n = len(ordered)
    out.append("")
    out.append("| redlink quartile | n | mean redlink | mean share | mean pool |")
    out.append("|---|---|---|---|---|")
    for q in range(4):
        chunk = ordered[q * n // 4:(q + 1) * n // 4]
        if not chunk:
            continue
        out.append(
            f"| Q{q+1} | {len(chunk)} | {mean([s.redlink for s in chunk]):.1%} | "
            f"{mean([s.share for s in chunk]):.1%} | "
            f"{mean([float(s.pool) for s in chunk]):.0f} |"
        )


def correlate(label: str, sub: list[Squad], out: list[str], detail: bool) -> dict:
    x = [s.redlink for s in sub]
    y = [s.share for s in sub]
    r = pearson(x, y)
    rho = spearman(x, y)
    res = {"label": label, "n": len(sub), "r": r, "rho": rho,
           "p": perm_p(x, y, spearman)}

    # partial rank correlation holding the number of in-window editions the
    # federation actually appeared in fixed
    rx, ry, rz = ranks(x), ranks(y), ranks([float(s.n_ing) for s in sub])
    res["partial"] = pearson(residualise(rx, rz), residualise(ry, rz))

    # jackknife: how much of rho rests on any single federation
    jk = []
    for i in range(len(sub)):
        cut = sub[:i] + sub[i + 1:]
        jk.append(spearman([s.redlink for s in cut], [s.share for s in cut]))
    res["jk_lo"], res["jk_hi"] = min(jk), max(jk)
    res["jk_worst"] = sub[jk.index(max(jk))].label

    # trimmed: drop the most extreme 10% at each end of the redlink axis
    ordered = sorted(sub, key=lambda s: s.redlink)
    k = max(1, len(ordered) // 10)
    mid = ordered[k:-k]
    res["trimmed"] = spearman([s.redlink for s in mid], [s.share for s in mid])
    res["trimmed_n"] = len(mid)

    if detail:
        out.append(f"\n### {label} (n={len(sub)})\n")
        out.append(f"- Pearson r = {r:+.3f}, Spearman rho = {rho:+.3f} "
                   f"(permutation p = {res['p']:.4f})")
        out.append(f"- partial rho holding n_editions_ingested fixed = {res['partial']:+.3f}")
        out.append(f"- jackknife rho range over drop-one-federation = "
                   f"{res['jk_lo']:+.3f} to {res['jk_hi']:+.3f}")
        out.append(f"- rho on the middle {res['trimmed_n']} federations "
                   f"(10% trimmed each end) = {res['trimmed']:+.3f}")
        scatter_shape(sub, out)
    return res


def threshold(usable: list[Squad], out: list[str]) -> None:
    """Is the scatter a gradient or a cliff?

    Every edition's quartile table shows Q1-Q3 roughly flat and Q4 falling off,
    which is a different animal from a linear attenuation. A gradient degrades
    every federation's rank a little; a cliff leaves most of the ordering intact
    and makes the worst-covered tail uninterpretable. The remedy differs, so the
    distinction is worth measuring rather than eyeballing.
    """
    out.append("\n### Shape of the scatter: gradient or cliff?\n")
    out.append("Split at a 30% redlink rate, within gender so the two levels do not mix.\n")
    out.append("| slice | n below 30% | mean share below | n at/above 30% | "
               "mean share above | rho below | rho above |")
    out.append("|---|---|---|---|---|---|---|")
    for g, name in (("m", "men"), ("w", "women")):
        sub = [s for s in usable if s.gender == g]
        lo = [s for s in sub if s.redlink < 0.30]
        hi = [s for s in sub if s.redlink >= 0.30]
        rlo = spearman([s.redlink for s in lo], [s.share for s in lo]) if len(lo) > 2 else 0.0
        rhi = spearman([s.redlink for s in hi], [s.share for s in hi]) if len(hi) > 2 else 0.0
        out.append(
            f"| {name} | {len(lo)} | {mean([s.share for s in lo]):.1%} | {len(hi)} | "
            f"{mean([s.share for s in hi]):.1%} | {rlo:+.3f} | {rhi:+.3f} |"
        )

    out.append("\nHow far the pool-size confound goes, per edition: rank correlation")
    out.append("between a federation's redlink rate and the number of in-window youth")
    out.append("editions it actually appeared in.\n")
    parts = []
    for gender, year in EDITIONS:
        sub = [s for s in usable if s.gender == gender and s.year == year]
        parts.append(f"{gender}{year} {spearman([s.redlink for s in sub], [float(s.n_ing) for s in sub]):+.2f}")
    out.append("- redlink rate vs n_editions_ingested: " + ", ".join(parts))

    # The competing explanation for measured overlap, and it is a big one: a
    # federation that appeared in 1 of its 8 in-window youth editions has a
    # 21-player pool and mechanically few chances to have produced an alumnus.
    # That is partly a football fact (it failed to qualify) and partly a ceiling.
    parts = []
    for gender, year in EDITIONS:
        sub = [s for s in usable if s.gender == gender and s.year == year]
        parts.append(f"{gender}{year} {spearman([float(s.n_ing) for s in sub], [s.share for s in sub]):+.2f}")
    out.append("- n_editions_ingested vs share: " + ", ".join(parts))


def correlation(squads: list[Squad], out: list[str]) -> None:
    out.append("\n## (b) Redlink rate vs measured overlap share\n")
    out.append("Negative rho = worse-covered federations measure lower overlap. Squads")
    out.append("with an undefined share or an undefined coverage rate are excluded.\n")

    rows = []
    for gender, year in EDITIONS:
        sub = [s for s in squads if s.gender == gender and s.year == year
               and s.share is not None and s.redlink is not None]
        rows.append(correlate(f"{gender}{year}", sub, out, detail=True))

    # pooled, three ways
    usable = [s for s in squads if s.share is not None and s.redlink is not None]
    out.append("\n### Pooled\n")
    for name, sub in (("all six editions", usable),
                      ("men only", [s for s in usable if s.gender == "m"]),
                      ("women only", [s for s in usable if s.gender == "w"])):
        rows.append(correlate(f"pooled: {name}", sub, out, detail=True))

    # edition fixed effects: centre both variables on their edition's mean rank
    cx, cy = [], []
    for gender, year in EDITIONS:
        sub = [s for s in usable if s.gender == gender and s.year == year]
        rx, ry = ranks([s.redlink for s in sub]), ranks([s.share for s in sub])
        mx, my = mean(rx), mean(ry)
        cx.extend(v - mx for v in rx)
        cy.extend(v - my for v in ry)
    fe = pearson(cx, cy)
    out.append(f"\n### Pooled with edition fixed effects\n")
    out.append(f"- within-edition centred rank correlation = {fe:+.3f} (n={len(cx)})")
    out.append("- This is the pooled number to trust: it cannot be manufactured by the")
    out.append("  six editions sitting at different coverage and share levels.")

    threshold(usable, out)

    out.append("\n### Summary\n")
    out.append("| slice | n | Pearson r | Spearman rho | perm p | partial rho | "
               "jackknife rho range | trimmed rho |")
    out.append("|---|---|---|---|---|---|---|---|")
    for d in rows:
        out.append(
            f"| {d['label']} | {d['n']} | {d['r']:+.3f} | {d['rho']:+.3f} | "
            f"{d['p']:.4f} | {d['partial']:+.3f} | "
            f"{d['jk_lo']:+.3f} to {d['jk_hi']:+.3f} | {d['trimmed']:+.3f} |"
        )
    out.append(f"| edition fixed effects | {len(cx)} | — | {fe:+.3f} | — | — | — | — |")


def main() -> int:
    squads = load()
    out: list[str] = []
    out.append("# Coverage diagnostic: does measured overlap track article coverage?\n")
    out.append("Generated by `uv run scripts/diagnose_coverage.py` from `data/overlap.csv`.")
    out.append("Everything here is **provisional**. Overlap is measured over a Y-4..Y-12")
    out.append("window and undercounts unusually long senior careers, uniformly across")
    out.append("teams. No figure is corrected or scaled for coverage.\n")

    n_undef = sum(1 for s in squads if s.share is None)
    out.append(f"184 senior squads; {184 - n_undef} usable, {n_undef} excluded for an")
    out.append("empty in-window youth pool (undefined coverage rate and undefined share).")

    dispersion(squads, out)
    correlation(squads, out)

    text = "\n".join(out) + "\n"
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / "coverage_diagnostic.md").write_text(text, encoding="utf-8")
    print(text)
    print(f"wrote {REPORTS / 'coverage_diagnostic.md'}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
