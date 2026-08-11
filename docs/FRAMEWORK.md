# Healthcare Capacity Optimisation Toolkit

A reusable pipeline for answering one class of question: **given a constrained
budget, a set of delivery levers whose costs and capacities are partly unknown,
and an equity duty, what should we commit to, and what would tell us we were
wrong?**

It was extracted from a completed engagement (NHS Cheshire and Merseyside
elective recovery) rather than designed in the abstract, so every stage exists
because that engagement needed it.

---

## What is generalised, and what is not

| Layer | Generalised? | Where it lives |
|---|---|---|
| Scope, providers, horizon | Yes | config YAML |
| Cost model components and prices | Yes | config YAML |
| Levers, capacity bases, growth rates | Yes | config YAML |
| Equity dimension and direction | Yes | config YAML |
| Driving forces and their ranges | Yes | config YAML |
| Candidate strategies | Yes | config YAML |
| Objectives, directions, tie precision | Yes | config YAML |
| Optimisation, scenario and ranking method | Yes, engagement-agnostic | `scripts/toolkit/engine.py` |
| **Warehouse table and column names** | **No** | `scripts/toolkit/extract.py` |

The last row is the honest boundary. `extract.py` assumes the fact-table shape
this project's SQL layer builds: activity by provider and month, a forecast
table with Monte Carlo percentiles, workforce, beds, and diagnostics. Porting to
a differently-shaped warehouse means editing those queries. The toolkit does not
pretend to be schema-agnostic, because claiming that without having done it once
would be an assertion rather than a capability.

---

## Running it

```bash
python3 scripts/toolkit/run.py --config config/cheshire_merseyside.yaml
python3 scripts/toolkit/run.py --config config/cheshire_acute_only.yaml
```

Outputs per engagement: a results JSON plus CSVs for the driving-forces matrix,
the strategy-by-scenario grid, the ranks, and the regret matrix.

Starting a new engagement means copying a config, editing it, and running. If
the config is internally inconsistent the loader refuses to start rather than
defaulting quietly. A silently-defaulted parameter in a capacity model is worse
than a crash, because it produces a plausible number nobody questions.

---

## The seven stages

**1. Extract.** Pull activity, capacity, cost mix and the forecast interval for
the providers in scope. The demand range is taken from the forecast's own p5 and
p95 rather than invented.

**2. Impact/uncertainty matrix.** For each driving force, measure the swing in
the objective as it moves across its plausible range. Grade its evidence on a
four-point rubric. Criticality is the product.

This is the main methodological departure from the source literature, where the
matrix is populated by participants placing sticky notes. Here the impact axis
is computed and the uncertainty axis is graded against documented provenance.
Both are stated as departures wherever the output is presented.

**3. Tipping points.** Locate, by bisection on the *lever mix* rather than on
the objective value, the parameter values at which the optimal answer changes
shape. A sensitivity range says how far the answer moves; a tipping point says
where it becomes a different answer, which is the more useful thing for a
decision-maker to hold.

**4. Anchor-stability check.** Re-run stage 2 from a different corner of the
parameter space. A one-at-a-time sweep is only valid at the point it is
evaluated, and a lever that looks inert at the base case can be the only live
lever past a tipping point.

**5. Scenario framing.** Take the two most critical drivers as Factors A and B,
frame their extremes into four scenarios, and carry the central case as a
reference. No probabilities are assigned. These test plausibility, not
likelihood.

**6. Strategy evaluation.** Solve every strategy against every scenario. Each
strategy is a constraint set over the same optimisation, so all are evaluated on
identical terms.

**7. Decision analysis.** Rank every strategy-scenario combination on each
objective, sum the ranks, then re-run with each objective doubled and tripled to
test whether the ordering survives a different priority. Compute minimax regret.
Report whether the recommendation is weight-stable, and if it is not, say so.

---

## Four rules the toolkit enforces

Each exists because breaking it produced a wrong answer that looked right.

**Never rank a quantity the optimisation does not pin.** A linear programme with
equally-priced levers has many optimal solutions. Any metric read off the
allocation is then decided by which vertex the solver reached. The engine solves
hierarchically: maximise volume, then equity within that, then minimise
reliance on the weakest-evidenced levers within that. Every ranked quantity is
therefore uniquely determined.

This was learned twice. Equity was caught first: the same 15,873 breaches
cleared reported at both 100% and 29.7% higher-need share across runs. Delivery
risk was caught later, and only because the generalised toolkit was diffed
against the engagement engine. One cell in forty returned identical volume and
identical equity but a different lever mix. Fixing it changed the
recommendation from "robust under every weighting" to "a judgement call about
risk appetite", which is a materially different thing to tell a board.

**Round in exactly one place.** Derived quantities are rebuilt from rounded
inputs, so a workbook recomputing them in Excel cannot disagree with the engine
about which strategies tie. Rounding in two places is worse than not rounding at
all.

**State the direction of any inverted index.** Deprivation ranks run backwards:
rank 1 is most deprived. The config must say so explicitly and the toolkit will
not guess. Getting this wrong silently inverts the equity constraint, and it has
already caused one documented misreading on this engagement.

**Separate what is computed from what is judged.** Flexibility, insurability and
institutional feasibility are analyst judgements and are labelled as such
wherever they appear. They are screened alongside the scored objectives, never
blended into the same weighted total.

---

## Transferability evidence

The toolkit was validated two ways.

**Reproduction.** Run against the primary configuration it reproduces the
original engagement engine exactly. Forty cells across six metrics agree to within
1.5×10⁻⁸, all eight strategy scores match, the same degenerate pairs are
detected, the same tipping point is found, and all eight weight-sensitivity
orderings are identical.

**Discrimination.** Run against a second configuration (the seven general acute
providers only, specialist centres excluded, with a £9m envelope and a 10pp
equity tolerance) it produces a different analysis with no code changes:

| | Primary (12 trusts) | Acute only (7 trusts) |
|---|---|---|
| Diagnostic tipping point | 3.3429 | 3.3677 |
| S3 no in-house expansion | 339 | 320 |
| S4 diagnostic-led | 361 | 364 |
| S6 diversified hedge | 374 | 367 |
| S7 treatment only | 295 | 292 |
| S7 worst-case regret | 106,324 | 63,685 |

The structural conclusions hold across both: funding and diagnostic conversion
are the critical factors, S1/S2/S5 collapse to one commitment, and the
recommendation is not weight-stable against S7. That is a reasonable result. The
two configurations are the same health economy under different scopes, so
identical structure and shifted magnitudes is what should be expected. The
toolkit is discriminating on the things that genuinely differ and agreeing on
the things that genuinely do not.

A caveat on how strong this evidence is. Both configurations run against the
same warehouse, the same lever set and the same cost schedule. This demonstrates
that scope, envelope and tolerance are genuinely parameterised; it does not
demonstrate portability to a different provider landscape or a different
warehouse schema, which would require the extraction queries to be reworked
(see the boundary table above). Claiming more than that from two runs on one
dataset would be overreach.

Reproduction alone would only show the code still runs. Discrimination is what
shows the generalisation is real, within the boundary just stated.

---

## Method sources

- Cairns, G. and Wright, G. (2018) *Scenario Thinking*, 2nd ed., Palgrave
  Macmillan. Ch.2 intuitive-logics basic method; Ch.5 Goodwin and Wright
  sum-of-ranks decision analysis; Ch.8 robust strategy, the
  flexible/diversified/insurable screen, and early-warning flags.
- Sminia, H. (2026) "From Scenario Thinking to Scenario Doing: Strategic
  Management as Wayfinding", *Futures & Foresight Science* 8:e70038. The
  framing of monitoring as continuing participation rather than a one-off
  exercise.
- Sminia, H. (2022) *The Strategic Manager*, 3rd ed., Routledge, Ch.7. The
  institutional feasibility screen.

---

## Files

```
config/
  cheshire_merseyside.yaml      primary engagement configuration
  cheshire_acute_only.yaml      second configuration, transferability test
scripts/toolkit/
  config.py                     load and validate; refuses ambiguous configs
  extract.py                    warehouse -> model inputs
  engine.py                     optimisation, scenarios, decision analysis
  run.py                        CLI runner
```
