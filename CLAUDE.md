# CLAUDE.md

Standing context and instructions. Read on every run.

## What this project is

Measures how much national-team senior World Cup squads overlap with their own U-20 and U-17 World Cup squads, men's and women's, to test whether youth-tournament success actually feeds senior success or just looks like it does.

The headline metric is squad overlap, not title-to-title correlation. Title-to-title is too lumpy and too contaminated by age misrepresentation to mean much. Overlap answers the mechanistic question: what share of a senior squad came up through the youth pipeline.

## Operating environment

- Runs in Claude Code on the web (ephemeral cloud VM). Anything not committed to git is lost when the session ends. Commit intermediate data as you produce it; do not hold it only in memory.
- Network egress is allowlisted. The only external domain this project needs is `en.wikipedia.org` (MediaWiki API). If a request is blocked by the proxy, stop and tell me to allowlist the domain. Do not loop on retries.
- Python runs with `uv`. Use PEP 723 inline script metadata (a `# /// script` dependency block) so scripts run with `uv run scripts/<name>.py` and no separate venv step.

## Data source and the one design decision that matters

Source is English Wikipedia squad-list pages via the MediaWiki action API (`action=parse`, `prop=wikitext`), for example the page `2023 FIFA Women's World Cup squads`. Parse the squad templates (`{{nat fs player}}`, `{{fs player}}`) and the section headers that name each team. Squad-page formatting varies by edition, so inspect the actual wikitext before assuming a structure.

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
`team, gender, year, squad_size, n_youth_alumni, share_youth_alumni, n_from_u20, n_from_u17, finish`

## Build order. Do not skip.

Phase 0: scaffold, confirm `uv run` works, confirm the MediaWiki API is reachable. This is where the allowlist prompt will fire.

Phase 1: validate on two known cases before touching anything else.
- High-overlap case, Spain women. Senior 2023 WWC squad against Spain's U-20 women (2018, 2022) and U-17 women (2018) squads. Expected: high overlap. If it comes back low, the parser or matcher is broken.
- Low-overlap control, Nigeria men. U-17 champions in 2013 and 2015 against their later senior World Cup squads. Expected: low overlap. If it comes back high, the matcher is inventing joins.

Print both, stop, and let me eyeball before going further.

Phase 2: only after I confirm Phase 1 looks right, fan out to the full set of federations and tournaments.

## Reporting honesty

Do not present a single correlation coefficient as the answer. The sample is small and lumpy. Report the overlap distribution and be explicit about confounds:
- Men's youth results are contaminated by age misrepresentation, so men's overlap and men's youth "success" both mean less than they appear to.
- This metric counts squad membership, not minutes. A benchwarmer on a youth champion counts the same as a starter. A minutes-weighted version is a later refinement, not v1.
- Redlink gaps understate overlap. Report how many players could not be joined.

## Don'ts

- Don't fabricate squad members. If a page won't parse, record it in `data/parse_failures.csv` and move on.
- Don't fan out before Phase 1 is confirmed.
- Don't hold results only in memory. Commit CSVs as you go.

## Overlap definition (replaces the earlier version)

A senior-squad player counts as a youth alumnus if their `player_qid` appears in any U-20 or U-17 World Cup squad for the same federation and gender, in an edition inside the age window defined below.

Fixed age window. This is not optional and not per-team. For a senior tournament in year `Y`, the eligible youth editions are every U-20 and U-17 World Cup held in years `Y-15` through `Y-4` inclusive. Both bounds are inclusive. Apply the identical window to every federation and both genders.

The earlier "any prior edition" rule is retired. It made each team's overlap number depend on how many youth editions happened to have been scraped for that team, which is not a property of the football. Under that rule Spain women was measured against three editions and Nigeria men against two, so their overlap shares were not comparable to each other. Any comparison across teams requires that every team be evaluated against the same window.

Consequences you must honor:

- Before computing overlap for any senior squad, you must have ingested every U-20 and U-17 edition in that squad's window for that federation and gender. A missing edition is a correctness bug, not a coverage gap.
- If an edition in the window cannot be ingested (page missing, parse failure, team did not qualify), record it in `data/window_coverage.csv` as `team, gender, senior_year, youth_level, youth_year, status (ingested|not_qualified|failed)`. A team is only comparable if every in-window edition is `ingested` or `not_qualified`. Any `failed` makes that squad's number provisional and it must be labeled as such in output.
- Note that a federation not qualifying for a youth edition is real signal, not missing data. Do not impute anything for it.

## Coverage bias. Read before reporting any men's number.

The dominant error source in this project is not identity matching. It is that players with no English Wikipedia article have no QID and are structurally unjoinable. In Phase 1 this was 20 of 42 in Nigeria's youth pool.

This gap is not random. English Wikipedia coverage of youth footballers correlates with national wealth, league profile, and European club presence — which is close to the exact variable the project is trying to measure. Low measured overlap for an under-covered federation and genuinely poor youth-to-senior conversion produce the same number. The pipeline cannot currently distinguish them.

Therefore:

- Never report a cross-federation men's comparison as a finding until the redlink gap is closed for the under-covered federations in it. RSSSF is the realistic supplementary source for youth squad lists. Until then, men's cross-federation numbers are provisional and must be labeled provisional wherever they appear.
- Compute and carry a coverage rate alongside every overlap number. Add to `overlap.csv`: `n_youth_pool, n_youth_pool_linked, youth_coverage_rate`. An overlap share without its coverage rate next to it is not interpretable and must not be presented alone.
- A 0.0% overlap on a squad with a low coverage rate is a coverage floor showing through, not a result. Say so explicitly rather than reporting the zero.
- The women's side has better article coverage and is not distorted by age misrepresentation the way the men's side is. When the two disagree, weight the women's result and say why.
- Do not "correct" for coverage by scaling overlap up by the inverse coverage rate. That assumes redlinked players convert at the same rate as covered ones, which is precisely the thing in question. Report the gap; do not model it away.

## Output labeling

Every table, summary, or writeup produced by this project must carry, per row: the coverage rate, and a provisional flag where the window is incomplete or coverage is low. Do not produce a clean-looking ranked table of federations by overlap share. That format implies a precision the data does not have and invites exactly the misreading these rules exist to prevent.
