# CLAUDE.md

Standing context and instructions. Read on every run.

## What this project is

Measures how much national-team senior World Cup squads overlap with their own U-20 and U-17 World Cup squads, men's and women's, to test whether youth-tournament success actually feeds senior success or just looks like it does.

The headline metric is squad overlap, not title-to-title correlation. Title-to-title is too lumpy and too contaminated by age misrepresentation to mean much. Overlap answers the mechanistic question: what share of a senior squad came up through the youth pipeline.

## Where the project is now

**Phase 0 — done.** Scaffold runs, `uv run` works, the MediaWiki API is reachable.

**Phase 1 — passed and confirmed closed (2026-08-02).** The parser handles every template dialect encountered, QIDs resolve, and the join produced high overlap for Spain women and low for Nigeria men, which is what it was built to test. Signed off; the approval gate on Phase 2 is satisfied.

**Phase 2 ingestion — done (2026-08-03).** All 38 pages of the v1 scope ingested by `scripts/ingest.py`: 32 youth editions plus the 6 senior pages, 17,481 players, 184 senior squads. 0 editions failed, `parse_failures.csv` empty, 0 error-severity integrity flags. `window_coverage.csv` came out 573 `ingested` / 899 `not_qualified`, with no `failed` and no `not_held`, so **no squad in the v1 scope is provisional on window grounds**. The senior pages are needed as well as the youth ones because `window_coverage.csv` is keyed per senior squad.

`scripts/ingest.py` fetches each edition once and extracts every federation from it, windowing through `editions_in_window()`. It is not `phase1.py` extended — `phase1.py` still applies the retired any-prior-edition rule, which is correct for the window-exempt validation and wrong for measurement, and it stays as the parser/join regression check. The two scripts no longer share output paths: `ingest.py` owns `data/squads.csv` and the other unprefixed data files, `phase1.py` writes only `phase1_`-prefixed ones, so the regression check is now free to run. See Schema.

**Phase 2 overlap — computed as a diagnostic (2026-08-03).** `scripts/overlap.py` writes `data/overlap.csv`, 184 rows, full documented column set, coverage columns carried from `window_coverage_rates.csv` and cross-checked against a recomputation. 152 squads have a defined share; the other 32 have an empty in-window youth pool and carry a null share with `n_youth_alumni` still written as 0. `finish` is empty on 181 rows because `results.csv` is a stub — see below.

**These shares are coverage statistics, not findings.** Nothing in `overlap.csv` may be reported as a result yet, and no ranked table of federations by overlap share may be produced. `scripts/diagnose_coverage.py` writes `reports/coverage_diagnostic.md`, which is what the shares were computed for.

**What the diagnostic found.** Three things, all of which constrain what can be reported later:

1. *Dispersion inverts the level story.* Men's per-federation windowed redlink rate is far lower (mean 18.8–22.4%) but far more dispersed (CV 0.85–0.99) than women's (mean 44.3–45.1%, CV 0.41–0.43). Women's coverage is uniformly bad; men's is bimodal, ranging 0% to 71% inside a single edition. On dispersion — which is what wrecks ranking — the men's side is the worse of the two. Do not restate "women's coverage is 2.3× worse" as if it settled which side supports a cross-federation comparison. It settles the level only.
2. *The redlink correlation is real but moderate and concentrated in the tail.* Within-edition rank correlation between redlink rate and measured share runs −0.06 to −0.60; the pooled edition-fixed-effects figure is −0.30. It is a cliff, not a gradient: below a 30% redlink rate the correlation is near zero (men −0.05, women −0.16), above it the relationship bites (men −0.27, women −0.43). The naive pooled correlation across all six editions is +0.01 — a Simpson reversal, because women have both higher redlink rates and higher shares. Never quote the unpooled figure.
3. *The dominant driver of measured overlap is neither coverage nor conversion.* `n_editions_ingested` — how many of its 8 in-window youth editions the federation actually appeared in — correlates +0.58 to +0.87 with share, several times the coverage effect. A federation that reached 1 youth edition has a 21-player pool and mechanically almost no chance of a high share. **`share_youth_alumni` is therefore substantially a measure of youth-tournament qualification frequency, not of youth-to-senior conversion.** This is a definitional problem with the metric, independent of the redlink gap, and it is not fixed by RSSSF or any other source. Address it before treating overlap as an answer to the project's question.

Read "Coverage bias" before scoping any further work. The full corpus reverses the assumption this project carried about which gender is better covered.

Phase 1 is a parser and join test, **not a measurement**, and is deliberately exempt from the age window. Its cases are Spain women's 2023 senior squad against U-20 women 2018/2022 and U-17 women 2018, and Nigeria men's 2014 and 2018 senior squads against U-17 men 2013/2015. Several of those pairings fall outside the window. This is intentional. Do not amend Phase 1 into window compliance; that would cost a cheap regression check and buy nothing.

Phase 1 outputs are therefore **not results** and must never be reported as overlap figures. Specifically, Spain women 2023 at 26.1%, Nigeria men 2018 at 8.7%, and Nigeria men 2014 at 0.0% are all withdrawn. The Nigeria 2014 figure is void in a stronger sense: its only youth input was U-17 2013, which falls after the Y-4 boundary for a 2014 senior squad, so it was computed against zero eligible editions. Zero eligible editions is an empty comparison, not a low overlap.

## Operating environment

- Runs in Claude Code on the web (ephemeral cloud VM). Anything not committed to git is lost when the session ends. Commit intermediate data as you produce it; do not hold it only in memory.
- Network egress is allowlisted. The only external domain this project needs is `en.wikipedia.org` (MediaWiki API). If a request is blocked by the proxy, stop and tell me to allowlist the domain. Do not loop on retries.
- **Throttle the API.** A full ingest is ~450 requests and firing them back to back earns a sustained HTTP 429 partway through — the first Phase 2 run lost nine editions to it, recorded as `failed` for a reason having nothing to do with the data. All API access goes through `fetch_page.api_get()`: one request per second, plus a bounded four-attempt backoff honouring `Retry-After`. That backoff is not the retry loop ruled out above; that rule is about the proxy blocking a domain, where retrying cannot help. A 429 with `Retry-After` is the API stating its rate. After four attempts it raises and the edition is recorded as failed like any other retrieval failure. A full run takes roughly an hour at this rate — that is the correct cost, not a problem to optimise away.
- Python runs with `uv`. Use PEP 723 inline script metadata (a `# /// script` dependency block) so scripts run with `uv run scripts/<name>.py` and no separate venv step.

## Data source

Source is English Wikipedia squad-list pages via the MediaWiki action API (`action=parse`, `prop=wikitext`), for example the page `2023 FIFA Women's World Cup squads`. Parse the squad templates and the section headers that name each team.

Squad-page formatting varies by edition — inspect the actual wikitext before assuming a structure. Dialects encountered include `{{nat fs player}}`, `{{nat fs g player}}`, `{{nat fs player no caps}}`, `{{National football squad player}}`, `{{National football squad player (no caps)}}` and `{{National football squad player (goals)}}`; player names appear as wikilinks, as `'''bolded'''` wikilinks, and as `{{sortname|First|Last}}` with an optional `dab=`; team headers appear both as plain names and as `{{fbu|17|CODE}}` with country codes that are not consistent between editions.

**Some squads are not templates at all.** A few pages write a squad as a raw wikitable, one row per player, with position taken from `!colspan=...|Goalkeepers` band rows. On the 2008 U-20 Women's page 5 of 16 squads are in that dialect — England, France, United States, Canada, New Zealand — and a template-only parser returns 11 teams while raising no warning whatsoever. Four of the five are well-covered federations, so the loss lands precisely where the data is otherwise good. Table rows must carry a shirt number or a date of birth to count as a player; the row with neither is the trailing head-coach row.

**Do not resolve `{{fbu|N|CODE}}` headers from a hand-maintained code map.** Ask the API: `action=expandtemplates` returns the rendered country name, so NGR/NGA and IRN/IRI collapse to one federation for free and there is no map to keep current. The hand-typed map in `squad_parser.COUNTRY_CODES` was missing codes on 15 of the 38 v1 pages, and every miss drops an entire 18–24 player squad.

Assume more variance exists than you have seen. All 32 youth editions in the v1 scope needed at least one parser accommodation; see `data/format_variants.csv`.

## The join key

Join players on their **Wikidata QID**, not on display name and not on the article title. Wikipedia has already disambiguated people (accents, transliteration, "born 1990" suffixes, nicknames), so the linked article is the right identity anchor — but the *title* of that article is not stable. Pages get moved: rename `Eva Navarro (footballer)` to `Eva Navarro (footballer, born 2001)` and a title-keyed join silently drops the match on the next run, with no error and a quietly lower overlap number. QIDs never change.

Get the QID from the already-allowlisted en.wikipedia.org API, not from wikidata.org: `action=query&prop=pageprops&ppprop=wikibase_item&redirects=1`. One request returns the redirect-resolved title and the QID together, so this costs nothing over plain redirect resolution. Fall back to the canonical article title for the rare page carrying no Wikidata item (in Phase 1 this was 0 of 148).

Resolve redirects regardless. `María Isabel Rodríguez` and `Misa Rodríguez` are one player, as are `Catalina Coll`/`Cata Coll` and `Paula Sancho`/`Pauleta (footballer, born 1998)`. Display-name matching splits all three.

A bluelink pointing at a page that does not exist is a redlink for our purposes. Treat it as one.

Players with no linked article (redlinks) cannot be joined this way. Put them in `data/redlinks.csv` with their raw name and squad, and fall back to normalized fuzzy name matching for those only, flagged as lower confidence. Never silently merge or drop them.

## Schema

Persist everything as CSV under `data/` so it stays diffable and reviewable from a phone.

`data/squads.csv`, one row per (tournament, team, player):
`tournament_id, level (senior|u20|u17), gender (m|w), year, team, shirt_no, position, player_article, player_qid, display_name, source_url, birth_year`

`player_qid` is the join key; `player_article` is the redirect-resolved title it came from, kept for review and as the fallback key. `birth_year` is parsed from the squad template and is a diagnostic only — it says whether a senior player was even age-eligible for the youth editions in scope, so a low overlap share can be read correctly. Never join on it.

`data/results.csv`, one row per (senior tournament, team):
`team, gender, year, finish` (round reached). Hand-curated is fine; this is a small set.

`data/overlap.csv`, derived, one row per (senior tournament, team):
`team, gender, year, squad_size, n_youth_alumni, share_youth_alumni, n_from_u20, n_from_u17, finish, n_youth_pool, n_youth_pool_linked, youth_coverage_rate, n_editions_in_window, n_editions_held_in_window`

`overlap.csv` is produced by `scripts/overlap.py` only. Nothing window-exempt may be written to that path — see `phase1_validation.csv` below. `share_youth_alumni` is empty, never `0.0`, when `n_editions_held_in_window` is 0 (cannot occur in the v1 scope, guard retained) or when `n_youth_pool` is 0 (32 of 184 squads). `n_youth_alumni` is still written as 0 for those — the count is real, the share is undefined, and reading the two together is what separates "measured, nobody came through" from "no denominator". `n_from_u20 + n_from_u17` can exceed `n_youth_alumni`: a player at both a U-17 and a U-20 in the window is one alumnus and appears in both level columns.

`data/window_coverage.csv`, one row per (senior squad, in-window youth edition):
`team, gender, senior_year, youth_level, youth_year, status`

`data/editions.csv`, the edition-to-page-title lookup: `level, gender, year, page_title, status`.

**Two different `status` columns exist, with different value sets. Do not conflate them.** `editions.csv.status` is `exists | not_held | failed` and describes the *page*: whether a squad-list article is retrievable for that edition at all, independent of any federation. `window_coverage.csv.status` is `ingested | not_qualified | not_held | failed` and describes one *federation's relationship* to one edition. Only the latter feeds the denominator rule.

**`scripts/ingest.py` is the sole writer of `data/squads.csv`**, and of `redlinks.csv`, `parse_failures.csv`, `integrity_flags.csv`, `format_variants.csv`, `window_coverage.csv` and `window_coverage_rates.csv`. No other script may write any of those paths.

**`scripts/overlap.py` is the sole writer of `data/overlap.csv`**, and writes nothing else. It reads `squads.csv`, `window_coverage_rates.csv` and `results.csv` and touches no network. **`scripts/diagnose_coverage.py` is the sole writer of `reports/coverage_diagnostic.md`** and writes nothing under `data/`. Both are pure functions of what is already on disk, so either can be re-run at any time without an ingest.

Everything `scripts/phase1.py` produces is prefixed `phase1_` and is owned by it alone:
`data/phase1_squads.csv`, `data/phase1_results.csv`, `data/phase1_redlinks.csv`, `data/phase1_parse_failures.csv`, `data/phase1_validation.csv`.

That split exists because `phase1.py` originally wrote the unprefixed `squads.csv`, `redlinks.csv`, `parse_failures.csv` and `results.csv`. Running the regression check replaced a 17,481-player `squads.csv` with 174 rows and a 4,490-row `redlinks.csv` with 26, recoverable only by an hour-long re-ingest. A regression check that punishes you for running it stops being run, which costs the safety net it exists to provide. Do not let either script reclaim the other's paths.

`data/phase1_validation.csv` holds the Phase 1 parser/join test output. It is not a results file and carries no share column — Phase 1 is window-exempt, so its shares are withdrawn (see "Where the project is now"). Squad-size and alumni counts are kept because they are the regression signal if the parser changes. The committed `phase1_*` files are the expected output: a clean run reproduces them byte-for-byte (174 squad rows, 26 redlinks, ratios 0/23, 2/23, 6/23), so `git diff` after `uv run scripts/phase1.py` is the regression check.

`data/results.csv` is **not yet curated**. It currently holds only the three fixture rows Phase 1 left behind when it still wrote this path, duplicated now in `phase1_results.csv`. Measuring overlap for the v1 scope needs finishes for all 184 senior squads; treat the present contents as a stub, not as data.

`data/redlinks.csv` and `data/parse_failures.csv` capture everything that could not be joined or could not be parsed. Nothing is ever dropped silently.

`data/window_coverage_rates.csv`, derived, one row per (senior squad):
`team, gender, senior_year, senior_squad_size, n_youth_pool, n_youth_pool_linked, n_youth_pool_redlinks, youth_coverage_rate, n_editions_in_window, n_editions_held_in_window, n_editions_ingested, n_editions_not_qualified, n_editions_failed, provisional`

This is the coverage half of `overlap.csv`, computed without computing overlap — it exists so the redlink gap can be read before any share is calculated. It deliberately carries **no alumni count and no share column**, so it cannot quietly become `overlap.csv` under another name. `youth_coverage_rate` is empty, never `0.0`, when `n_youth_pool` is 0; an empty pool is an undefined rate, the same trap as a zero denominator. Note that a rate over a small pool is noisy — a federation appearing in 1 of its 8 in-window editions has a 21-player pool, so read `n_editions_ingested` alongside the rate.

A per-edition redlink rate is not a substitute for this. The pool a senior squad is actually measured against spans its whole window, and single-edition rates swing widely around it.

`data/integrity_flags.csv`, one row per detected deviation:
`tournament_id, level, gender, year, page_title, team, check, severity, expected, observed, detail`

`severity` is `error | warn`. This file exists for the failure mode that does not throw: a page that parses cleanly and returns 20 of 24 teams, or 14 of 18 players. Nothing errors, so nothing reaches `parse_failures.csv`, and the youth pool silently shrinks — which deflates overlap hardest for the federations already worst hit by the redlink gap. Checks are team count against the known finals field size, squad size against an absolute band, squad size against the edition's own modal squad, unresolved section headers, duplicate teams, squads with no shirt numbers, squads with zero linked players, and near-duplicate federation spellings across the corpus.

**An `error`-severity flag changes how `window_coverage.csv` reads that edition.** A federation missing from an edition we know we mis-parsed is `failed`, not `not_qualified`. Without that rule a parser bug masquerades as "this country didn't qualify" and the provisional flag never fires.

`data/format_variants.csv`, one row per (edition, accommodation):
`tournament_id, level, gender, year, page_title, variant, count, description`

Every format variant the parser had to accommodate, logged rather than silently absorbed. Baseline dialects (plain `===Spain===` headers, `{{nat fs player}}` / `{{nat fs g player}}`) are excluded by design — the residual is the number that matters. It is a proxy for how much variance is still hiding in editions that happened to parse cleanly: in the v1 corpus **32 of 32 youth editions needed at least one accommodation**, so an edition parsing without complaint is not evidence of uniformity.

## Overlap definition

A senior-squad player counts as a youth alumnus if their `player_qid` appears in any U-20 or U-17 World Cup squad for the same federation and gender, in an edition inside the age window below.

### Age window

For a senior tournament in year `Y`, the eligible youth editions are every U-20 and U-17 World Cup held in years `Y-12` through `Y-4` inclusive. Both bounds inclusive. This is not optional and not per-team — apply the identical window to every federation and both genders.

The window is fixed rather than "any prior edition" because that older rule made each team's overlap number depend on how many youth editions happened to have been scraped for that team, which is not a property of the football. Any comparison across teams requires that every team be evaluated against the same window.

Y-12 is the lower bound because the binding constraint is player age, not edition count. A U-17 player is ~17 and a U-20 is ~20, so a wider bound implies a senior squad member aged ~32 who played a U-17 at 17. That happens, but it is rare, and paying ~12 editions per squad to catch it made every single squad a fan-out. Y-12 covers players up to roughly 29 (U-17 route) and 32 (U-20 route) at the senior tournament, and costs about 8 editions.

This is a deliberate truncation, not a claim that no such players exist. State it wherever results are reported: overlap is measured over a Y-4..Y-12 window and will slightly undercount unusually long senior careers. The truncation is uniform across teams, so cross-team comparisons remain valid; only the absolute level is affected.

### Window coverage

- Before computing overlap for any senior squad, you must have ingested every U-20 and U-17 edition in that squad's window for that federation and gender. A missing edition is a correctness bug, not a coverage gap.
- Record every in-window edition in `data/window_coverage.csv`.
- A federation not qualifying for a youth edition is real signal, not missing data. Do not impute anything for it.

### Edition status and the denominator rule

`window_coverage.csv` status is one of: `ingested | not_qualified | not_held | failed`.

`not_held` means the edition was never played and there is no squad to miss. Causes: the 2021 men's and 2020 women's tournaments cancelled for COVID; women's U-17 not existing before 2008; women's U-19/U-20 not existing before 2002; any in-window year before a tournament's inception.

`not_held` is categorically different from the other three. `ingested` and `not_qualified` both mean the edition happened and the federation's relationship to it is known. `failed` means it happened and could not be retrieved. Recording a never-played edition as `failed` would mark squads provisional for a data problem that does not exist, and the provisional flag is load-bearing — if it fires on non-problems it stops meaning anything at fan-out.

**Denominator rule.** `not_held` editions are removed from the window denominator entirely. A squad is comparable if every in-window edition is `ingested`, `not_qualified`, or `not_held`. Only `failed` makes a squad provisional.

**Both counts must be carried.** `n_editions_in_window` and `n_editions_held_in_window` both appear in `overlap.csv`. A squad measured against 6 held editions must not be silently compared to one measured against 8. This is the same failure as the original unequal-edition-set problem arriving through a different door, and the guard is reporting both numbers wherever an overlap share appears.

## Scope for v1

v1 is scoped to senior editions with a full 8 held in-window editions: **women's 2019 and 2023, men's 2010, 2014, 2018, 2022.** Everything else is out of scope for v1 — do not ingest or report it.

Rationale: these are the only editions whose shares are comparable without a denominator caveat. Ingestion is bounded by youth editions, not squads, so the core costs 32 youth editions (the verified union across the six windows) and yields ~184 senior squads. Nigeria men 2010/2014/2018 and Spain women 2023 are all inside it.

Excluded: women's 1991–2003 (zero eligible editions), women's 2007/2011/2015 (partial, 1/3/6 held), men's 1998 (zero) and 2002 (two), men's 2026 and women's 2027 (6 of 8, COVID cancellations).

## Zero and partial denominators

A squad with zero held in-window editions has an **undefined** overlap, not zero. Emit null for the share, never 0.0% — 0/0 rendering as 0.0% in a table would be the most misleading number this project could emit, and it is the same failure as the withdrawn Nigeria 2014 figure.

A squad with a partial denominator may be computed, but its share must never appear without `n_editions_held_in_window` beside it.

## Tournament naming trap. Handle deliberately.

Tournaments were renamed mid-history, and a renamed page goes missing without raising an error. Under the current rules a missed in-window edition is a correctness bug, not a coverage gap, so this must be handled explicitly.

- men's U-20: **FIFA World Youth Championship** through 2005, **FIFA U-20 World Cup** from 2007.
- men's U-17: **FIFA U-17 World Championship** through 2005, **FIFA U-17 World Cup** from 2007.
- women's U-20: **FIFA U-19 Women's World Championship** (2002, 2004), then **FIFA U-20 Women's World Championship** (2006 only), then **FIFA U-20 Women's World Cup** from 2008.
- women's U-17: no rename; the tournament began in 2008.

Resolve edition page titles from the explicit lookup table in `scripts/editions.py` (mirrored to `data/editions.csv`). Do not construct titles by string-formatting a year into a template. If a resolved page 404s, that is a hard failure to record in `window_coverage.csv` as `failed`, never a silent skip.

Check for equivalent renames before relying on any newly constructed title.

## Coverage bias. Read before reporting any number, either gender.

The dominant error source in this project is not identity matching. It is that players with no English Wikipedia article have no QID and are structurally unjoinable. In Phase 1 this was 20 of 42 in Nigeria's youth pool.

**A "redlink" here means any squad player we cannot join on a QID**, whichever of these three produced it, because the effect on the pool is identical:

1. the name is plain text in the wikitext, never linked at all;
2. the name is linked but the target article does not exist — a literal red link on the rendered page;
3. the name is linked to a real article that carries no Wikidata item (rare: 9 players in 17,481 across the whole v1 corpus, and these fall back to a title-keyed join rather than dropping out).

Cases 1 and 2 are the ones that matter, and case 2 is the larger of the two in this corpus — 3,069 occurrences, logged as `bluelink_to_missing_page` in `format_variants.csv`. A redlinked player is not missing from the *squad*; they are missing from the *joinable pool*, so they can never be counted as a youth alumnus no matter how many youth tournaments they actually played. Everything unjoinable goes to `data/redlinks.csv`; nothing is dropped silently.

This gap is not random. English Wikipedia coverage of youth footballers correlates with national wealth, league profile, and European club presence — which is close to the exact variable the project is trying to measure. Low measured overlap for an under-covered federation and genuinely poor youth-to-senior conversion produce the same number. The pipeline cannot currently distinguish them.

Therefore:

- Never report a cross-federation men's comparison as a finding until the redlink gap is closed for the under-covered federations in it. RSSSF is the realistic supplementary source for youth squad lists. Until then, men's cross-federation numbers are provisional and must be labeled provisional wherever they appear.
- Compute and carry a coverage rate alongside every overlap number, via `n_youth_pool`, `n_youth_pool_linked` and `youth_coverage_rate`. An overlap share without its coverage rate next to it is not interpretable and must not be presented alone.
- A 0.0% overlap on a squad with a low coverage rate is a coverage floor showing through, not a result. Say so explicitly rather than reporting the zero.
- **The women's side does NOT have better article coverage. Measured, it is substantially worse.** This reverses what this file asserted before Phase 2 ingestion, and it was asserted on no evidence. Over the full v1 corpus the windowed redlink rate is 42.8% for women's 2019 and 41.5% for women's 2023, against 15.8–19.8% for all four men's editions — roughly 2.3× worse. The mechanism is structural rather than an artifact of one senior edition: women's U-17 is the worst-covered family in the corpus at 53–63% and supplies four of the eight editions in *every* women's window, so no choice of women's senior edition escapes it. The old "weight the women's result" rule does not survive on coverage grounds and must not be applied.
- The age-misrepresentation advantage of the women's side is **not** affected by the above and still stands — that is a separate axis, and nothing in Phase 2 tested it. So the two sides now trade off rather than one dominating: men's data is better covered, women's data has cleaner ages. When they disagree, say which axis is driving the disagreement instead of privileging either gender by default.
- Do not "correct" for coverage by scaling overlap up by the inverse coverage rate. That assumes redlinked players convert at the same rate as covered ones, which is precisely the thing in question. Report the gap; do not model it away.

**Scoping does not fix this.** Scoping equalizes denominators only. The redlink gap remains the dominant error source on both sides and is unresolved. Cross-federation results stay provisional and labeled provisional regardless of how clean the window arithmetic looks — and note that `provisional` in `window_coverage_rates.csv` means something narrower (an in-window edition we failed to retrieve). A squad can be non-provisional there and still be uninterpretable through coverage. Do not read that column as an all-clear.

Measured windowed redlink rates for the v1 corpus, for reference when scoping the overlap work:

| senior edition | squads | youth pool | redlinks | rate |
|---|---|---|---|---|
| men's 2010 | 32 | 1811 | 358 | 19.8% |
| men's 2014 | 32 | 2235 | 410 | 18.3% |
| men's 2018 | 32 | 2141 | 377 | 17.6% |
| men's 2022 | 32 | 2099 | 332 | 15.8% |
| women's 2019 | 24 | 1721 | 736 | 42.8% |
| women's 2023 | 32 | 1827 | 759 | 41.5% |

32 of the 184 senior squads have an empty in-window youth pool — the federation appeared in none of its 8 eligible youth editions. Their coverage rate is undefined, not 0%, and so is any overlap share computed for them.

## Era comparability. Both genders.

`not_held` is not a neutral status. Senior squads whose windows reach back before the youth tournaments existed are structurally capped below what a modern squad can reach — a 2003 women's senior team could not have youth alumni from tournaments not yet invented. Women's U-17 began 2008 and women's U-19/U-20 began 2002, so women's senior tournaments through roughly 2014 have windows that are partly or wholly pre-inception. The men's side has the identical defect at the left edge, with a shorter ramp: men's 1998 has zero eligible editions and men's 2002 has two.

This is a real feature of the era, not measurement error, but it means **overlap shares are not comparable across time on either side.** Any trend line over senior tournaments will show a rise that is substantially an artifact of youth tournaments coming into existence and the pipeline filling, not of federations getting better at development.

Do not report an overlap time series without stating this. Do not fit or describe a trend across editions whose windows differ in how much pre-inception territory they cover. Cross-federation comparison *within* a single senior edition is unaffected and remains the safer comparison to make.

## Output labeling

Every table, summary, or writeup produced by this project must carry, per row: the coverage rate, and a provisional flag where the window is incomplete or coverage is low. Do not produce a clean-looking ranked table of federations by overlap share. That format implies a precision the data does not have and invites exactly the misreading these rules exist to prevent.

## Reporting honesty

Do not present a single correlation coefficient as the answer. The sample is small and lumpy. Report the overlap distribution and be explicit about confounds:

- Men's youth results are contaminated by age misrepresentation, so men's overlap and men's youth "success" both mean less than they appear to. No data source fixes this — the officially registered dates of birth are themselves the contaminated ones.
- This metric counts squad membership, not minutes. A benchwarmer on a youth champion counts the same as a starter. A minutes-weighted version is a later refinement, not v1.
- Redlink gaps understate overlap. Report how many players could not be joined.

## Don'ts

- Don't fabricate squad members. If a page won't parse, record it in `data/parse_failures.csv` and move on.
- Don't ingest or report anything outside the v1 scope. (the better standing rule — the fan-out gate was one-time, this is permanent)
- Don't begin ingestion until Phase 1 is explicitly confirmed closed. Confirmed 2026-08-02 — this gate is satisfied and spent. It is kept only as a record that it was met; it is not a live constraint.
- Don't hold results only in memory. Commit CSVs as you go.
- Don't emit 0.0% for a squad with a zero denominator. Emit null. Same for a coverage rate over an empty youth pool.
- Don't present an overlap share without its coverage rate and edition counts.
- Don't treat a clean parse as evidence the page was fully extracted. Check the extracted team count and squad sizes against expectation and record deviations in `data/integrity_flags.csv`. Silent partial extraction is the failure mode that costs the most here, and it never raises an error.
- Don't silently absorb a format variant. Log it in `data/format_variants.csv` and keep going.
