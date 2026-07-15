# youth-to-senior squad overlap

Does senior national-team success actually track U-20 / U-17 success in football? This measures it directly, for men's and women's teams, by computing how much each senior World Cup squad overlaps with that federation's own youth World Cup squads.

## The question

Youth-tournament results are a weak predictor of senior strength, and weaker on the men's side than most people expect. Nigeria has won the U-17 World Cup five times and never passed the senior round of 16. The cleaner way to ask the question is not "do youth champions become senior champions" but "how much of a senior squad actually came up through the youth pipeline." That is squad overlap, and it is what this repo computes.

## Approach

Pull senior, U-20, and U-17 World Cup squad lists from Wikipedia. For each senior squad, compute the share of players who previously appeared in a U-20 or U-17 World Cup squad for the same federation. Relate that share to how far the senior team went.

The join key is each player's Wikipedia article title, not their name. That sidesteps most of the transliteration and disambiguation problems that break name matching. The full design and the reasoning behind that choice are in CLAUDE.md.

## Data

Everything derived lives in `data/` as CSV so it can be reviewed and diffed without running anything:
- `squads.csv`, raw extracted squad memberships
- `results.csv`, senior tournament finishes
- `overlap.csv`, the computed per-squad overlap
- `redlinks.csv`, `parse_failures.csv`, coverage gaps

## Running

Scripts use `uv` with inline dependencies. Run any script with:

```
uv run scripts/<name>.py
```

No venv setup needed. Network access is limited to `en.wikipedia.org`. In Claude Code on the web you will be prompted to allow it on the first request.

## Known limitations

- Counts squad membership, not minutes. A youth-team benchwarmer counts as overlap.
- Men's youth data is contaminated by age misrepresentation, so treat men's youth success and overlap with more suspicion than women's.
- Small, lumpy sample. Read the distribution, not a single correlation number.
