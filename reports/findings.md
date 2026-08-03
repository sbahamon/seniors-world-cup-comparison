# Do youth World Cups feed the senior team?

What 17,481 squad entries can and cannot say about the youth-to-senior pipeline.

*August 2026. Every figure here comes from the CSVs in this repository. Nothing is
scaled, imputed, or corrected for coverage.*

---

## 1. The question, and why this measures it with squads

Nigeria has won the men's U-17 World Cup five times. It has never gone past the
senior round of 16. That pairing is the folk version of the question this project
asks: does winning at youth level mean anything for the senior team, or are the two
tournaments effectively separate competitions that happen to share a flag?

Comparing trophies cannot answer it. There have been too few youth World Cups, the
results are lumpy, and on the men's side the age-group results are contaminated by
age misrepresentation — a problem no data source fixes, because the officially
registered dates of birth are themselves the compromised ones. Correlating a handful
of youth titles against a handful of senior finishes would produce a number, and the
number would mean nothing.

So this project asks the mechanistic question underneath it instead: **how much of a
senior World Cup squad actually came up through that federation's own youth World Cup
teams?** Of the 23 players a country takes to a senior World Cup, how many were in
one of its U-20 or U-17 World Cup squads?

That is squad overlap, and it has three properties the trophy comparison lacks. It is
observed for every squad rather than for the handful that won something. It is a
count of people rather than a placement, so it is not hostage to a single knockout
result. And it points at a specific causal story — a pipeline that moves individual
players from age-group football into the senior team — rather than at a vague
association between two rankings.

A player counts as a youth alumnus if the same person appears in a U-20 or U-17 World
Cup squad for the same federation and gender, in a tournament held **four to twelve
years** before the senior one. Identity is matched on Wikidata QID, never on display
name and never on article title: names split on accents, transliteration and
nicknames, and article titles get renamed out from under a saved dataset, silently
lowering the overlap number on the next run with no error raised.

The window is fixed rather than "any earlier tournament" because otherwise each
federation's number would depend on how many youth editions happened to have been
collected for it, which is not a property of the football. Four to twelve years covers
a player who was 17 at a U-17 through to about 29 at the senior tournament, and 20 at
a U-20 through to about 32. It is a deliberate truncation: a 33-year-old who played a
U-17 at 17 falls outside it. The truncation is identical for every federation, so
cross-federation comparison is unaffected and only the absolute level is slightly
understated.

---

## 2. Scope

| | |
|---|---|
| Senior editions | 6 — men's 2010, 2014, 2018, 2022; women's 2019, 2023 |
| Youth editions ingested | 32 — the union of the U-20 and U-17 tournaments inside those six windows |
| Squad entries | 17,481 (one row per player per tournament) |
| Senior squads | 184 |
| Entries with no joinable identity | 4,490 |

Six senior tournaments looks arbitrarily small. It is not: they are every senior
edition where all eight in-window youth tournaments were actually held. The women's
youth tournaments are young — the U-19/U-20 began in 2002 and the U-17 in 2008 — so
women's senior squads before roughly 2015 have windows reaching back into years when
the tournaments did not exist. Women's 2007, 2011 and 2015 get 1, 3 and 6 of the usual
8. The men's side has the same defect at its left edge with a shorter ramp: 1998 has
zero eligible editions, 2002 has two. At the other end, the 2021 men's and 2020
women's youth tournaments were cancelled for COVID, which puts men's 2026 and women's
2027 at six of eight.

Mixing those denominators would manufacture a finding. A squad measured against eight
tournaments will show higher overlap than one measured against three, for reasons that
have nothing to do with football, and plotted over time it reads as federations
steadily getting better at development when it is really the youth tournaments coming
into existence and the pipeline filling. Restricting the scope removes the artifact
rather than annotating it.

The restriction costs less than the short list suggests, because ingestion is bounded
by youth editions rather than by squads: the same U-17 2013 squad list serves every
federation that played in it.

---

## 3. What the data says about football

### 3.1 The scarce thing is getting to the youth World Cup at all

This is the finding that survives everything below, because it does not depend on any
player being identifiable. Whether a federation played in a youth World Cup is
recorded on that tournament's own squad page. It does not matter whether its players
have Wikipedia articles.

Every senior squad has eight youth World Cups in its window. Here is how many of them
the federation actually turned up to:

| Editions reached | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
|---|---|---|---|---|---|---|---|---|---|
| Men's squads (128) | 17 | 25 | 18 | 11 | 18 | 13 | 15 | 5 | 6 |
| Women's squads (56) | 15 | 10 | 7 | 2 | 3 | 5 | 1 | 8 | 5 |

**Thirty-two of the 184 senior squads — nearly one in six — come from a federation
that reached none of its eight eligible youth World Cups.** For those squads there is
no youth pipeline to convert, because there is no youth pipeline. Their overlap share
is undefined, not zero; the distinction matters, and reporting 0.0% for them would be
the most misleading number this project could emit.

The modal men's squad reached exactly one. Only 11 of the 184 come from a federation
present at all eight: Brazil and the United States on the men's side in both 2010 and
2014, Australia in 2010, Mexico in 2022, Germany and New Zealand in both women's
editions, and Nigeria's women in 2019.

Two of those names are worth pausing on. New Zealand and Nigeria are ever-present in
women's youth World Cups while being nowhere near the senior top tier. That is what a
shallower qualifying field looks like from the inside: the women's youth tournaments
have had fewer serious contenders per confederation, so a mid-tier federation can be
permanently in the draw. Running the other way, 15 of 56 women's senior squads —
better than one in four — came from a federation that had not reached a single youth
World Cup in the previous twelve years. Whatever produced those senior teams, a youth
World Cup pipeline was not it.

This is youth-programme *reach*, not youth-programme *quality*. It says a federation
gets its age-group teams to the tournament. It says nothing about what happens to
those players next. That second step is the one everything below struggles to measure.

### 3.2 Where conversion can be measured: 14 federations

Overlap can be reported honestly only where two conditions hold at once: most of a
federation's youth players are identifiable (a windowed redlink rate under 30% — see
§4), and the federation appeared in enough youth editions that the pool is not a
handful of players (at least five of eight). **Forty senior squads across 14
federations clear both.**

The full surviving set, ordered by edition and then alphabetically. It is deliberately
*not* ordered by share:

| Edition | Federation | Redlink rate | Editions reached | Youth pool | Alumni | Share |
|---|---|---|---|---|---|---|
| Men's 2010 | Argentina | 7.8% | 6 of 8 | 116 | 6 of 23 | 26.1% |
| Men's 2010 | Australia | 23.4% | 8 of 8 | 154 | 11 of 23 | 47.8% |
| Men's 2010 | Brazil | 5.2% | 8 of 8 | 153 | 8 of 23 | 34.8% |
| Men's 2010 | Germany | 13.7% | 5 of 8 | 95 | 2 of 23 | 8.7% |
| Men's 2010 | Japan | 4.1% | 5 of 8 | 98 | 8 of 23 | 34.8% |
| Men's 2010 | Spain | 6.1% | 6 of 8 | 115 | 10 of 23 | 43.5% |
| Men's 2010 | United States | 16.3% | 8 of 8 | 153 | 12 of 23 | 52.2% |
| Men's 2014 | Argentina | 12.1% | 6 of 8 | 124 | 9 of 23 | 39.1% |
| Men's 2014 | Australia | 18.6% | 5 of 8 | 102 | 8 of 23 | 34.8% |
| Men's 2014 | Brazil | 4.2% | 8 of 8 | 165 | 8 of 23 | 34.8% |
| Men's 2014 | Colombia | 21.4% | 5 of 8 | 103 | 10 of 23 | 43.5% |
| Men's 2014 | Germany | 5.8% | 5 of 8 | 104 | 4 of 23 | 17.4% |
| Men's 2014 | Japan | 7.7% | 5 of 8 | 104 | 10 of 23 | 43.5% |
| Men's 2014 | Mexico | 19.6% | 5 of 8 | 102 | 4 of 23 | 17.4% |
| Men's 2014 | Nigeria | 27.2% | 6 of 8 | 125 | 5 of 23 | 21.7% |
| Men's 2014 | South Korea | 14.5% | 7 of 8 | 145 | 15 of 23 | 65.2% |
| Men's 2014 | Spain | 6.9% | 7 of 8 | 145 | 11 of 23 | 47.8% |
| Men's 2014 | United States | 13.9% | 8 of 8 | 165 | 5 of 23 | 21.7% |
| Men's 2018 | Argentina | 19.8% | 6 of 8 | 126 | 8 of 23 | 34.8% |
| Men's 2018 | Brazil | 7.5% | 7 of 8 | 147 | 11 of 23 | 47.8% |
| Men's 2018 | England | 1.0% | 5 of 8 | 104 | 9 of 23 | 39.1% |
| Men's 2018 | Japan | 9.5% | 5 of 8 | 105 | 6 of 23 | 26.1% |
| Men's 2018 | Mexico | 16.7% | 6 of 8 | 126 | 5 of 23 | 21.7% |
| Men's 2018 | Nigeria | 25.8% | 7 of 8 | 147 | 10 of 23 | 43.5% |
| Men's 2018 | South Korea | 9.5% | 6 of 8 | 126 | 9 of 23 | 39.1% |
| Men's 2018 | Spain | 7.1% | 6 of 8 | 126 | 9 of 23 | 39.1% |
| Men's 2018 | Uruguay | 15.6% | 7 of 8 | 147 | 12 of 23 | 52.2% |
| Men's 2022 | Argentina | 15.9% | 6 of 8 | 126 | 9 of 26 | 34.6% |
| Men's 2022 | Brazil | 7.1% | 6 of 8 | 126 | 6 of 26 | 23.1% |
| Men's 2022 | England | 3.2% | 6 of 8 | 125 | 9 of 26 | 34.6% |
| Men's 2022 | France | 4.0% | 6 of 8 | 126 | 6 of 26 | 23.1% |
| Men's 2022 | Germany | 10.5% | 5 of 8 | 105 | 1 of 26 | 3.9% |
| Men's 2022 | Mexico | 17.3% | 8 of 8 | 168 | 6 of 26 | 23.1% |
| Men's 2022 | United States | 7.9% | 6 of 8 | 126 | 11 of 26 | 42.3% |
| Men's 2022 | Uruguay | 11.9% | 6 of 8 | 126 | 11 of 26 | 42.3% |
| Women's 2019 | France | 26.7% | 5 of 8 | 105 | 12 of 23 | 52.2% |
| Women's 2019 | Germany | 20.8% | 8 of 8 | 168 | 17 of 23 | 73.9% |
| Women's 2019 | United States | 19.2% | 6 of 8 | 125 | 10 of 23 | 43.5% |
| Women's 2023 | Spain | 14.3% | 5 of 8 | 105 | 10 of 23 | 43.5% |
| Women's 2023 | United States | 22.5% | 7 of 8 | 147 | 12 of 23 | 52.2% |

Every squad here has all eight in-window editions held, so the denominators are equal.

**Read down the columns, not across them.** These are squads of 23 to 26 players, so
the sampling uncertainty on any single share is large: a 95% Wilson interval on 9 of
23 runs from 22.2% to 59.2%. Almost every pair of federations in this table has
overlapping intervals. The chart on the project page draws those intervals precisely
so the ranking cannot be read off it.

What *is* readable is a federation compared against itself, which no amount of
selection bias touches:

- **Germany's men sit at the bottom of the set in all three measurable squads** —
  8.7% in 2010, 17.4% in 2014, 3.9% in 2022. Germany is one of the best-covered
  federations in the corpus (2022 redlink rate 10.5%), so this is not a pipeline going
  unseen. A senior Germany squad is largely built from players who were not at a youth
  World Cup, either because they were not selected then or because Germany's age-group
  teams did not qualify in the years those players were eligible. Any individual
  interval here is wide; what is suggestive is that three independent squads point the
  same way.
- **The same federation's 2019 women's squad is at 73.9%, the highest figure in the
  set.** One country, two programmes, opposite answers. Whatever "German player
  development" means, it does not mean one thing.
- **South Korea's 2014 men's squad was 65.2% youth-World-Cup alumni** — 15 of 23.
  Uruguay in 2018 and the United States in 2010 were both above half. These are senior
  teams that are, quite literally, their youth teams grown up.

### 3.3 The worked case: Nigeria

Nigeria is the federation the project was built around, and it behaves the way §3.1
predicts. Its youth teams are almost always at the tournament. What changes from cycle
to cycle is how many of those players are still there when the senior squad is picked.

| Senior squad | Editions reached | Redlink rate | Alumni | Share | Measurable? |
|---|---|---|---|---|---|
| Men's 2010 | 4 of 8 | 36.4% | 6 of 23 | 26.1% | No — fails both filters |
| Men's 2014 | 6 of 8 | 27.2% | 5 of 23 | 21.7% | Yes |
| Men's 2018 | 7 of 8 | 25.8% | 10 of 23 | 43.5% | Yes |
| Women's 2019 | 8 of 8 | 54.2% | 14 of 23 | 60.9% | No — coverage |
| Women's 2023 | 7 of 8 | 60.5% | 10 of 23 | 43.5% | No — coverage |

Between 2014 and 2018 Nigeria's measured overlap doubled, from 21.7% to 43.5%, while
its youth qualification barely moved (6 of 8, then 7 of 8) and its coverage barely
moved either (27.2%, then 25.8%). Whatever changed, it changed in the conversion step,
not in the pipeline's width and not in how much of it we can see. The two intervals
overlap at the edges and two squads four years apart are not a trend — but this is the
exact shape the project was built to look for, and in the one federation where it was
most expected, it is visible.

Nigeria's women are the counterexample that shows the limit. Eight of eight and seven
of eight youth editions — the most complete pipeline in the corpus — with shares of
60.9% and 43.5% that **cannot be reported**, because more than half the players in
that youth pool have no article to match against. The best-connected pipeline here is
one of the least measurable. That is not a coincidence, and §4 is why.

---

## 4. Why it stops here: the coverage gap

Every match in this project runs through a player's Wikidata identity. A youth player
with no English Wikipedia article has no identity to match, so they can never be
counted as a senior alumnus no matter how many youth tournaments they actually played
in. Across the corpus that is **4,490 of 17,481 squad entries**.

Three things produce it and the effect on the pool is identical for all three: the
name is plain text in the wikitext and never linked; the name is linked but the target
article does not exist (the largest category — 3,069 occurrences); or the article
exists but carries no Wikidata item (rare — 9 entries in 17,481, and those fall back
to a title-keyed join rather than dropping out).

The gap is not noise, because it is not random. English Wikipedia's coverage of youth
footballers tracks national wealth, league profile and European club presence — which
is uncomfortably close to the variable this project is trying to measure. **A
federation with genuinely poor youth-to-senior conversion and a federation whose youth
players simply have no articles produce the same low number, and nothing in the
pipeline distinguishes them.**

### 4.1 The two sides fail differently, and neither dominates

| Senior edition | Squads | Youth pool | Unjoinable | Rate |
|---|---|---|---|---|
| Men's 2010 | 32 | 1,811 | 358 | 19.8% |
| Men's 2014 | 32 | 2,235 | 410 | 18.3% |
| Men's 2018 | 32 | 2,141 | 377 | 17.6% |
| Men's 2022 | 32 | 2,099 | 332 | 15.8% |
| Women's 2019 | 24 | 1,721 | 736 | 42.8% |
| Women's 2023 | 32 | 1,827 | 759 | 41.5% |

**On level, the women's data is about 2.3× worse:** a pooled mean per-federation rate
of 44.8% against 20.4% for the men. The mechanism is structural, not an accident of
one tournament — women's U-17 is the worst-covered family in the corpus at 53–63%, and
it supplies four of the eight editions in *every* women's window, so no choice of
women's senior edition escapes it.

That level difference is the intuitive result and it is also, on its own, misleading.
**On dispersion, the men's data is the worse of the two.**

| | Pooled mean | Per-edition IQR | Per-edition CV |
|---|---|---|---|
| Men | 20.4% | 16.3%–31.3% | 0.85–0.99 |
| Women | 44.8% | 25.9%–29.8% | 0.41–0.43 |

Women's coverage is a uniformly bad blanket. Men's coverage is bimodal, running from
0% to 71% *inside a single senior edition*. Dispersion is what wrecks a
cross-federation comparison, because it means two federations sitting in the same
table are being measured through wildly different lenses. England's 2014 men's youth
pool is 0% unjoinable; Honduras's, in the same tournament, is 58%. Ranking those two
against each other on measured overlap is not a football comparison.

So the two sides trade off rather than one being usable and the other not: the men's
data is better covered on average, the women's data has cleaner ages. When they
disagree, the honest move is to say which axis is driving the disagreement.

### 4.2 The relationship is a cliff, not a gradient

Splitting at a 30% redlink rate, within gender so the two levels do not mix:

| | n below 30% | mean share below | rho below | n at/above 30% | mean share above | rho above |
|---|---|---|---|---|---|---|
| Men | 84 | 24.7% | −0.048 | 27 | 15.4% | −0.269 |
| Women | 10 | 43.9% | −0.155 | 31 | 42.4% | −0.433 |

Below roughly 30%, coverage and measured overlap are close to unrelated. Above it, the
relationship bites. That is what makes the threshold defensible rather than arbitrary:
there is a region where coverage does not visibly distort the answer and a region
where it does.

The pattern is broad rather than the work of two or three outliers. Jackknifing
federation by federation moves the pooled men's correlation only between −0.287 and
−0.243; trimming 10% from each end leaves it at −0.265. The women's pooled figure
behaves the same way (jackknife −0.361 to −0.254, trimmed −0.185). Individual editions
vary a lot — men's 2022 is the strongest at rho = −0.599 with a permutation p of
0.0006, men's 2010 the weakest at −0.057 — which is itself a reason not to lean on any
single edition.

### 4.3 The number not to quote

Pool all six senior editions together and the correlation between redlink rate and
overlap share is **+0.012** (Pearson +0.036, permutation p = 0.88). Read naively, that
says the coverage gap does not distort the measurement at all.

It is a Simpson's-paradox artifact. Women's squads have both higher redlink rates
*and* higher overlap shares than men's squads, so pooling across genders introduces a
between-group association that cancels the real within-edition effect and flips its
sign. Within each edition the correlation is negative in all six.

**With edition fixed effects the within-edition rank correlation is −0.296 (n = 152).
That is the number.** It cannot be manufactured by the six editions sitting at
different coverage and share levels, which is exactly what the pooled figure is
measuring instead. The pooled +0.012 should never be quoted.

---

## 5. The deeper problem: the metric is substantially measuring qualification

Suppose the coverage gap vanished tomorrow. The headline metric would still not mean
what it appears to mean.

Within each senior edition, the number of in-window youth editions a federation
actually appeared in correlates with its measured overlap share at:

| w2019 | w2023 | m2010 | m2014 | m2018 | m2022 |
|---|---|---|---|---|---|
| +0.86 | +0.85 | +0.73 | +0.65 | +0.87 | +0.58 |

That is several times the size of the coverage effect measured in §4.2. **The dominant
driver of `share_youth_alumni` is how often a federation reached youth World Cups, not
how well it converted the players it sent there.** The mechanism is arithmetic: a
federation that reached one edition has a pool of about 21 players for a senior squad
to have come from, and mechanically almost no chance of a high share; one that reached
all eight has around 170.

This is a definitional problem with the metric, not a data problem, and no
supplementary source touches it.

The obvious repair — divide alumni by the size of the joinable youth pool instead of by
the senior squad — **inverts the bias rather than removing it.** Senior squads cap at
23 (26 in 2022), so a 147-player pool has a mechanical ceiling near 16% while a
21-player pool can reach 100%. Swapping one mechanical artifact for its mirror image is
not progress.

The honest decomposition is two separate quantities: qualification frequency as its own
measure (§3.1, which is clean), and conversion-given-appearance as a second, with
uncertainty carried. That was scoped and deliberately not implemented, because it was
gated on the surviving set being large enough to compare conversion rates across
federations — and §6 is why it is not.

---

## 6. The intersection, and the design limit

Applying both filters at once settles the shape of the whole project:

| Stage | Senior squads | Distinct federations |
|---|---|---|
| In scope | 184 | 63 |
| Overlap defined (federation reached ≥1 youth edition) | 152 | 52 |
| Coverage filter: windowed redlink rate under 30% | 94 | 33 |
| Precision filter: also reached ≥5 of 8 youth editions | **40** | **14** |

The count is stable in the teens across every threshold combination tried: 17
federations at the most permissive setting (≥4 editions), 12 at the strictest (≥6).
Loosening coverage from 30% to 35% adds at most one federation.

That is case-study territory, not a statistical finding, and three consequences follow.

**The surviving set is selected on approximately the variable being measured.** Article
coverage tracks national wealth and European club presence. Qualification frequency
tracks youth-programme investment. Both filters select the same federations, so the
intersection is close to a list of well-resourced football nations — Argentina,
Australia, Brazil, Colombia, England, France, Germany, Japan, Mexico, Nigeria, South
Korea, Spain, the United States, Uruguay. Any finding computed on that set is a finding
about *that set*. It cannot speak to whether youth pipelines feed senior success in
general.

**The women's side cannot support cross-federation work at all.** Five squads and four
federations survive across both editions: France, Germany and the United States in
2019; Spain and the United States in 2023. The men's side supplies 35 of the 40.

**More data does not fix it.** RSSSF is the realistic supplementary source for youth
squad lists, and it would rescue 18 more squads at this threshold — but only **five
more federations**: Canada, China PR, Costa Rica, New Zealand and Paraguay. Most
badly-covered federations also fail the precision filter, and no source can fix a
federation not having qualified. Of the 58 badly-covered squads a supplementary source
would target, only 18 pass precision; the other 40 are unmeasurable regardless of
coverage. Fourteen federations becoming nineteen does not turn a case study into a
statistical finding.

For the same reason, the 184 senior finishes were never curated. Relating overlap to
senior success needs a usable n, and there is not one. `data/results.csv` remains a
stub, deliberately.

---

## 7. What this answers, and what it does not

**Answered, and it is a real football result:** reaching youth World Cups is far more
unequally distributed than the sport's own rhetoric about development suggests. Nearly
one senior squad in six comes from a federation that reached none of its eight eligible
youth World Cups; the modal men's squad's federation reached one. Before any question
about conversion can be asked, most of world football does not have a youth World Cup
pipeline to convert. On the women's side the pattern has a second edge: a shallower
qualifying field lets mid-tier federations like New Zealand and Nigeria be permanently
present at youth level without that translating into senior standing.

**Answered for 14 federations, with the selection stated:** youth-alumni share ranges
from 3.9% to 73.9% across the 40 measurable squads, and the within-federation
comparisons are the informative ones. Germany's men are consistently at the bottom
while its women are at the top; South Korea's 2014 squad was two-thirds youth alumni;
Nigeria's men doubled their share between 2014 and 2018 with no change in qualification
or coverage. These are legitimate observations about specific programmes, with
intervals wide enough that no ranking should be read into the gaps between them.

**Not answered:** whether youth World Cup pipelines feed senior success across world
football. Not partially, not provisionally — not answered.

That is worth being precise about, because it is not a null result and it is not a
result of running out of effort. A null result would be having measured the
relationship and found it absent. What happened here is that the measurement is only
available on a subsample that was selected on the thing being measured. The federations
where the question is most interesting — the ones with strong youth results and weak
senior ones, which is the puzzle that motivates the question in the first place — are
disproportionately the ones open sources cover worst. And every filter that makes the
measurement trustworthy also selects for wealth and for youth-programme investment.
Those two facts are not independent, and that is what makes it a design limit rather
than a coverage gap.

The informative content is knowing where the answer would have to come from. It is not
Wikipedia, and it is probably not any open aggregation of article-linked squad lists,
because the same wealth gradient governs all of them. It would take federation-level or
FIFA-level squad records with identity resolution that does not depend on whether a
player later became notable enough to have an article written about them. That is a
different data-acquisition problem from the one this project solved, and it is the one
that matters.

---

## Standing caveats on every number above

- Overlap is measured over a Y−4 to Y−12 window and slightly undercounts unusually long
  senior careers. The truncation is uniform across federations.
- Cross-federation men's comparisons remain **provisional** while the coverage gap is
  open for the under-covered federations in them.
- The metric counts squad membership, not minutes. A youth-tournament benchwarmer counts
  exactly as much as a starter.
- Men's youth results and men's overlap are both contaminated by age misrepresentation.
  No data source fixes this.
- Overlap shares are **not comparable across time** on either side, because windows
  differ in how much pre-inception territory they cover. No trend is fitted or described
  here. Cross-federation comparison within a single senior edition is the safer one.
- Nothing is corrected for coverage. Scaling overlap up by the inverse of the coverage
  rate would assume unjoinable players convert at the same rate as joinable ones, which
  is precisely the question at issue.
- Nothing is dropped silently: every unjoinable player is in `data/redlinks.csv`, every
  parse failure in `data/parse_failures.csv`, every format accommodation in
  `data/format_variants.csv`, and every extraction anomaly in `data/integrity_flags.csv`.

## Sources in this repository

- `data/squads.csv` — 17,481 squad entries, keyed by Wikidata QID
- `data/overlap.csv` — per-squad overlap with its coverage rate and both edition counts
- `data/window_coverage_rates.csv` — the coverage half, computed without computing overlap
- `reports/coverage_diagnostic.md` — the full correlation tables behind §4
- `reports/intersection.md` — the filter counts behind §6
- `docs/index.html` — the project page, with the four charts
