# Valuation

`fantaclaude rank` prices the entire listone before the auction. It re-syncs
the league's settings from the live league API first unless `--offline` is
passed; everything after that one read is local computation over
[the data spine](data-spine.md).

## Projection

Every listone player is projected from his own history under this league's own
bonus/malus rather than a published fantamedia: each past appearance is
re-scored through the league's own scoring table.

Two quantities come out, each as a distribution rather than a point. The
expected fantamedia is shrunk toward the role's mean by a weight driven by how
many appearances it rests on, with recent seasons weighted heavier and goals
and assists pulled toward non-penalty xG and xA where the advanced-stats source
covers the season. Expected presenze is the giornate remaining times a rate,
itself a posterior mean shrunk toward the role's own rate, so two appearances
out of two do not read as a full season played.

Rotation is a depth-chart effect, not a club-wide multiplier: the matches a
rotating club's second choice loses go to the men behind him. An eligible
player takes a defensive-modifier uplift from the `d_factor.yml` table when the
league has it active. Every knob here lives in the projection's own
configuration, in `core/src/fantaclaude/analysis/projection.py`.

The quotazione is carried through this stage and read nowhere in it: a price is
not a value, and seeding a valuation with the market's number would compute
nothing.

## Pricing is a roster problem

The pricer does not rank players and read prices off the ranking: it solves for
the best *completion* of a roster, and a max price falls out as an indifference
point.

For a player offered at some price, `buy_value` is the value of buying him: his
own value at the rank the completion leaves him at, plus the best completion of
everything else with the credits that remain. `walk_value` is the best
completion when he is not bought — and in both branches he leaves the pool,
since if he is not bought here someone else buys him. The max price is the
largest amount at which `buy_value` still reaches `walk_value`, solved at the
p25, p50 and p75 of his value, which is the band the board prints.

`rank_weight` is the rank the completion actually leaves him at, not his
class's first: it depends on how many better players of his class the
completion also buys, so it is the optimiser's decision. Composition is a
decision variable too — the optimiser chooses how many of each class to buy
within the ranks the league's modules demand. A completion that cannot meet a
hard minimum is worth negative infinity, which drives the price of the last
player who can fill a mandatory slot up to whatever credits remain.

Tiers are cut by the largest gaps in value within a class; how many, and how
deep the top of the class runs, are `tiers_per_class` and `tier_pool` in
`pricing.yml`.

## Inflation and the reserve

`inflation` is the credits still on the market over the quotazioni of the
credible pool, the top candidates of each class by value rather than every name
on the listone. It is clamped at both ends, by `inflation_floor` and
`inflation_ceiling` in `pricing.yml`, and a player's `expected_price` is his
quotazione times it.

The `reserve` holds credits back so the last roster slots can still be filled:
one credit for every slot the completion leaves unfilled below the roster
minimum. It is solved rather than subtracted once: reserving shrinks the
budget, a smaller budget buys fewer players, and fewer players leave more slots
to reserve for.

## Scenarios

`preferences.yml` holds the choices that change a number: a target composition,
a risk appetite, a cap on the budget share any one role class may take. Its
`scenarios:` block names further scenarios, each overriding those same keys. A
run prices every one of them by default — one board per scenario, one committed
band per player per scenario — so the auction board can be read under any of
them later. Naming the base scenario as an override is refused rather than
quietly merged. Scenarios and knowledge-base notes are where a human argues
with the model.

## A model has an identity

`model_hash` is a digest over the projection configuration, the pricing
configuration from `pricing.yml`, the contents of `preferences.yml`, the
D-Factor table and a model version. Change any of them and the hash moves.

That is the point. Two runs whose `model_hash` differs are not comparable as
"before and after a fix" — they are two different models, and the gap between
their numbers cannot be attributed to any single change. A tuned knob is a new
model, not a tweak. Which scenarios a run priced is deliberately *not* in the
hash — everything that actually moves a price is.
