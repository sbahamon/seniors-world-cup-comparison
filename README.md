# youth-to-senior squad overlap

Does senior national-team success actually track U-20 / U-17 success in football? This measures it directly, for men's and women's teams, by computing how much each senior World Cup squad overlaps with that federation's own youth World Cup squads.

## The question

Youth-tournament results are a weak predictor of senior strength, and weaker on the men's side than most people expect. Nigeria has won the U-17 World Cup five times and never passed the senior round of 16. The cleaner way to ask the question is not "do youth champions become senior champions" but "how much of a senior squad actually came up through the youth pipeline." That is squad overlap, and it is what this repo computes.

## Results

- **[reports/findings.md](reports/findings.md)** — the writeup: what the data says about football, and exactly where it stops.
- **[The project page](https://sbahamon.github.io/seniors-world-cup-comparison/)** — four charts, built from the CSVs in this repo (`docs/`, rebuilt by `uv run scripts/build_site.py`).
- [reports/coverage_diagnostic.md](reports/coverage_diagnostic.md) and [reports/intersection.md](reports/intersection.md) — the correlation and filter tables the writeup draws on.

Short version: youth World Cup *participation* is far more unequally distributed than the sport's development rhetoric suggests — nearly one senior squad in six comes from a federation that reached none of its eight eligible youth World Cups. Youth-to-senior *conversion* can be measured honestly for only 14 federations, and those 14 are close to a list of well-resourced football nations, because both filters that make the measurement trustworthy select on approximately the variable being measured. The general question is not answered here, and more scraping would not answer it.

## Approach

Pull senior, U-20, and U-17 World Cup squad lists from Wikipedia. For each senior squad, compute the share of players who previously appeared in a U-20 or U-17 World Cup squad for the same federation, within a fixed age window of 4 to 12 years before the senior tournament. Relate that share to how far the senior team went.

The join key is each player's **Wikidata QID**, not their name and not their Wikipedia article title. Names split on accents, transliteration and nicknames; article titles get renamed out from under a saved dataset. QIDs never change. The full design and the reasoning are in CLAUDE.md.

## Scope, and why it is narrow

v1 covers six senior tournaments: **women's 2019 and 2023, men's 2010, 2014, 2018 and 2022.**

That looks arbitrarily small. It isn't — it is every senior edition whose overlap share is comparable to the others without a caveat. Each senior squad is measured against the youth editions held 4 to 12 years earlier, which is normally 8 tournaments. Two things knock that denominator down:

**Pre-inception windows.** The women's youth tournaments are young. The U-19/U-20 began in 2002 and the U-17 in 2008, so senior squads before roughly 2015 have windows reaching back into years when the tournaments did not exist. A 2003 women's squad had *zero* youth World Cups it could possibly have drawn from. Women's 2007, 2011 and 2015 get 1, 3 and 6 of the usual 8. The men's side has the same defect at its left edge, shorter: 1998 has zero and 2002 has two.

**The COVID cancellations.** The 2021 men's and 2020 women's youth tournaments were never played. That puts both men's 2026 and women's 2027 at 6 held editions out of 8 — so on each side, the next World Cup cannot be cleanly compared to its own predecessor.

Mixing those denominators together would manufacture a finding. Squads measured against 8 tournaments will show higher overlap than squads measured against 3, for a reason that has nothing to do with football. Plotted over time it reads as a steady rise in youth-to-senior conversion — federations apparently getting better at developing players — when it is really just the youth tournaments coming into existence and the pipeline filling up. Restricting v1 to the six full-denominator editions removes that artifact rather than annotating it.

Narrowing costs little, because ingestion is bounded by youth editions rather than by squads. The same U-17 2013 squad list serves every federation that played in it. The six in-scope senior editions need 32 youth editions between them and yield about 184 senior squads — so the scope restriction throws away far less data than the short edition list suggests.

## Data

Everything derived lives in `data/` as CSV so it can be reviewed and diffed without running anything:

- `squads.csv` — raw extracted squad memberships, one row per player per tournament, keyed by `player_qid`
- `results.csv` — senior tournament finishes
- `overlap.csv` — the computed per-squad overlap, carrying its coverage rate and both edition counts alongside every share. Written by `scripts/overlap.py`, which reads only what is already on disk.
- `window_coverage_rates.csv` — per senior squad, the redlink rate over its whole in-window youth pool. The coverage half of `overlap.csv`, computed without computing overlap, so the joinability gap can be read before any share exists. Carries no alumni count and no share column.
- `integrity_flags.csv` — deviations found by the ingestion's own checks: team counts and squad sizes that do not match expectation. It catches the pages that parse cleanly while returning partial data, which raise no error and would otherwise shrink the youth pool invisibly.
- `format_variants.csv` — every wikitext format variant the parser had to accommodate, logged rather than absorbed. All 32 youth editions needed at least one, so a page parsing without complaint is not evidence that the corpus is uniform.
- `phase1_*.csv` — output of the parser/join validation run (`phase1_squads.csv`, `phase1_validation.csv`, `phase1_redlinks.csv`, `phase1_parse_failures.csv`, `phase1_results.csv`). Deliberately *not* results files: that test is exempt from the age window, so it reports squad sizes and alumni counts but no overlap shares. The prefix keeps the regression check from overwriting the main ingestion's output — `scripts/ingest.py` is the sole writer of the unprefixed files, and a clean `phase1.py` run reproduces its own files byte-for-byte, so `git diff` is the check.
- `editions.csv` — the edition-to-page-title lookup. Tournaments were renamed mid-history (the men's U-20 was the *FIFA World Youth Championship* until 2005, the men's U-17 the *U-17 World Championship*, and the women's U-20 changed name twice), so page titles are resolved from an explicit table rather than built by formatting a year into a string. A renamed page would otherwise go missing with no error.
- `window_coverage.csv` — one row per (senior squad, in-window youth edition), recording what happened to each
- `redlinks.csv`, `parse_failures.csv` — everything that could not be joined or parsed. Nothing is dropped silently.

Two files carry a `status` column and they mean different things. In `editions.csv`, status is `exists`, `not_held` or `failed`, and describes whether a squad-list page can be retrieved for that edition at all — a property of the page, independent of any country. In `window_coverage.csv` it describes one federation's relationship to one edition, and is the one that feeds the denominator:

| status | meaning |
| --- | --- |
| `ingested` | edition happened, squad retrieved |
| `not_qualified` | edition happened, federation did not play in it — real signal, not missing data |
| `not_held` | edition was never played (cancelled, or before the tournament existed) |
| `failed` | edition happened but could not be retrieved |

The distinction matters for the denominator. `not_held` editions are removed from it entirely, since there is no squad to miss. Only `failed` makes a squad's number provisional — which keeps the provisional flag meaningful instead of firing on non-problems.

## Running

Scripts use `uv` with inline dependencies. Run any script with:

```
uv run scripts/<name>.py
```

The scripts:

- `fetch_page.py` — fetch raw wikitext for one page from the MediaWiki API
- `squad_parser.py` — parse a squads page into (team, player) rows; resolves redirects and Wikidata QIDs. Run it directly against a page title to inspect what it extracts.
- `editions.py` — the edition-to-page-title lookup. Run with no arguments to re-verify every title still resolves; `--windows` prints the in-window edition counts per senior tournament.
- `phase1.py` — the parser/join validation run

No venv setup needed. Network access is limited to `en.wikipedia.org`. In Claude Code on the web you will be prompted to allow it on the first request.

## Known limitations

**Coverage bias is the dominant error source, and it is not fixed.** A player with no English Wikipedia article has no QID and is structurally unjoinable. During validation this was 20 of 42 players in Nigeria's youth pool — nearly half the pool simply cannot be matched. The gap is not random: English Wikipedia coverage of youth footballers tracks national wealth, league profile and European club presence, which is uncomfortably close to the variable this project is trying to measure. An under-covered federation and a federation with genuinely poor youth-to-senior conversion produce the same low number, and the pipeline cannot currently tell them apart. Men's cross-federation results are therefore **provisional** until the gap is closed for the under-covered federations in them (RSSSF is the realistic supplementary source). Note that the scope restriction above does *not* help here — it equalizes denominators, nothing more.

The gap is reported, never modelled away. Scaling overlap up by the inverse of the coverage rate would assume redlinked players convert at the same rate as covered ones, which is precisely the question at issue.

Other limitations:

- **Age misrepresentation** contaminates men's youth football, so men's youth "success" and men's overlap both mean less than they appear to. No data source fixes this: the officially registered dates of birth are themselves the contaminated ones.
- **Membership, not minutes.** A youth-team benchwarmer counts exactly as much as a starter. A minutes-weighted version is a later refinement.
- **The window truncates.** Measuring over 4 to 12 years slightly undercounts unusually long senior careers — a 33-year-old who played a U-17 at 17 falls outside it. The truncation is uniform across teams, so comparisons stay valid; only the absolute level is affected.
- **No trend lines.** Overlap shares are not comparable across time on either side, for the denominator reasons above. Cross-federation comparison within a single senior edition is the safer comparison and is unaffected.
- **Small, lumpy sample.** Read the distribution, not a single correlation number.
