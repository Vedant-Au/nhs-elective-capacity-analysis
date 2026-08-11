# Phase 5 Validation Report: Scenario and Strategy Model

**Model:** NHS Cheshire and Merseyside ICB (QYG) elective capacity scenario and strategy model
**Horizon:** 18 months to September 2027
**Date of this validation:** 11 August 2026
**Artefacts validated:** `excel/NHS_CM_Scenario_Strategy_Model.xlsx`, `scripts/scenario_wayfinding.py`, `scripts/scenario_early_warning.py`, `scripts/build_scenario_workbook.py`

---

## 1. What was built and why

Phase 3 produced a single optimal allocation of £15m across three capacity levers. That result depends on seven parameters, four of which are analyst estimates rather than sourced figures. Phase 5 asks the question the optimiser cannot answer: given that uncertainty, which commitment should the ICB make, and what would have to be observed for it to be wrong.

Method follows Cairns and Wright (2018) *Scenario Thinking*: Ch.2 basic method, Ch.5 sum-of-ranks decision analysis, Ch.8 robust strategy and early-warning flags, framed within Sminia's (2026) scenario-doing/wayfinding distinction, with an institutional feasibility screen from Sminia (2022) Ch.7.

Two deliberate departures from the book are recorded because they change what the output means:

1. **The impact axis of the Stage 5 matrix is computed, not judged.** It is the swing in breaches cleared when each driving force moves across its plausible range. The uncertainty axis is an evidence grade assigned from this project's own provenance record.
2. **Cluster outcome ranges are measured where measurable.** The backlog range is the Phase 2 Monte Carlo forecast's own p5 and p95 at horizon end (0.911 / 1.147 of the p50), not a round number chosen for symmetry.

---

## 2. Baseline reproduction

Before anything was built on top of it, the Phase 3 LP was re-run from the warehouse and checked against the delivered Solver workbook.

| Quantity | Phase 3 build log | Re-run 11 Aug 2026 | Status |
|---|---|---|---|
| Blended unit tariff | £472.49 | £472.49 | Match |
| c1 in-house / c2 outsourcing | £472.49 / £472.49 | £472.49 / £472.49 | Match |
| c3 diagnostic | £247.32 | £247.32 | Match |
| Baseline over-52wk breaches (18mo) | 296,284 | 296,284 | Match |
| Total reduction at £15m | 60,649 (20.5%) | 60,649 (20.5%) | Match |
| Higher-deprivation share of reduction | 80.5% | 80.5% | Match |

All Phase 3 sanity assertions passed unchanged.

---

## 3. Defects found and fixed during this phase

### 3.1 Equity figures were solver artefacts, not results

**Found:** The first build produced identical objective values with wildly different equity outcomes. The same 15,873 breaches cleared were reported at both 100% and 29.7% higher-deprivation share, depending only on which optimal vertex HiGHS reached. The Phase 3 build log had already established that this LP is degenerate whenever two levers are priced identically; what was new was that an equity *objective* had been built on top of that non-unique quantity and was being ranked.

**Fix:** Hierarchical (lexicographic) optimisation. The first solve maximises breaches cleared; a second solve then holds that total at its optimum and, among all allocations achieving it, maximises the reduction accruing to higher-deprivation providers. The reported equity figure is now unique, reproducible, and has a clear meaning: the best equity outcome obtainable at zero cost to the primary objective.

**Verified:** re-running the engine now returns identical equity figures across repeated runs.

### 3.2 Excel and Python disagreed on the strategy ranking

**Found:** The workbook's live `RANK()` formulas produced a different sum-of-ranks from the engine for five of eight strategies. A clean recalculation (0 errors, 402 formulas) had not caught this. The formulas evaluated correctly and returned wrong numbers.

**Root cause, first pass:** genuine ties were being broken by floating-point noise. Several strategies reach the same outcome by different routes, and the LP returns those to within solver tolerance rather than bit-identically: 63,493.495 against 63,493.432, a difference of 0.06 of a breach in 63,493.

**Root cause, second pass:** the first fix rounded the ranking basis in the engine but left the workbook recomputing value-for-money from the *rounded* breaches while Python computed it from the *unrounded* ones. Excel divided 42,454 by the budget where Python divided 42,454.334. Rounding in two places proved worse than not rounding at all.

**Fix:** a single canonical rounded basis (`canonicalise()`), with every derived quantity rebuilt from the rounded inputs exactly as the workbook's own formulas do.

**Verified:** all 40 rows now agree on all four rank columns, all eight strategy totals, and all worst-case regret figures.

### 3.3 Delivery-risk figures were also solver artefacts, and this one changed the recommendation

**Found during the Phase 7 reproduction check**, not during Phase 5's own assurance. Diffing the generalised toolkit against this engine cell by cell showed exactly one disagreement out of 40: scenario A2B1, strategy S6, returning identical breaches cleared (116,655) and identical equity (116,655) but a delivery-risk exposure of 0.855 against 0.823.

**Root cause:** the lexicographic fix at §3.1 pinned volume and then equity, but left the *lever mix* free. Delivery-risk exposure is computed from the lever mix, so it remained non-unique for exactly the same reason equity had been, and like equity it was being ranked as an objective.

**Fix:** a third lexicographic stage. Among all allocations achieving both the optimal reduction and the optimal equity outcome, minimise reliance on the evidence-weak levers. This costs nothing in either prior objective by construction, and makes the reported figure mean something specific: the best achievable risk profile at no cost to volume or equity.

**Consequence: material, not cosmetic.** Before the fix, S2 appeared to lead under all eight weight-sensitivity tests, and the Phase 6 board paper said so. After it:

- S1, S2 and S5 are revealed to be **the same commitment**, identical on all four objectives in all five scenarios. The apparent separation between them had been noise in an unpinned quantity.
- The recommendation is **no longer weight-stable**. S7 takes first place whenever delivery risk is weighted at twice or three times the other objectives.
- The board paper was rewritten to present a judgement about risk appetite rather than a robust result, and to state the correction explicitly in its assurance annex.

The general lesson, now enforced in the toolkit and documented in `FRAMEWORK.md`: **never rank a quantity the optimisation does not pin.** Both times this rule was broken on this project, the resulting figure looked entirely reasonable and was wrong.

### 3.4 A one-at-a-time tornado evaluated at a single anchor

**Found (pre-emptively):** at the base assumption the diagnostic lever dominates and the treatment levers are never used, so their capacity assumptions register zero impact. Past the diagnostic tipping point they are the only levers in play. A matrix built at one anchor and presented as *the* matrix would have understated them to zero.

**Fix:** `stability_check()` re-runs the full sweep from the far corner of the most critical driver and reports whether any force's status is anchor-dependent.

**Result:** none flipped. The three inert drivers are inert at both anchors, for the structural reason set out in section 4.

---

## 4. Verification of the headline findings

### 4.1 No capacity ceiling binds anywhere in the scenario range

Computed directly from the lever caps:

| Lever | 18-month capacity ceiling | Budget required to exhaust it |
|---|---|---|
| Independent sector | 67,587 pathways | £31.9m |
| Diagnostic | 281,649 pathways | £69.7m |
| In-house | 226,575 pathways | £107.1m |

The scenario range runs £7.5m–£30m. Within it, the budget constraint binds and no capacity constraint does. This is why independent-sector scalability, NHS in-house productivity and the size of the backlog all register zero impact: they are real uncertainties about quantities that cannot affect the outcome at these funding levels.

**Cross-check:** confirmed independently by solving at both ends of each driver's range and observing bit-identical allocations.

### 4.2 The diagnostic tipping point at 3.34

The diagnostic weighted cost is £141.33 per test. Indifference against the £472.49 treatment cost therefore occurs at 472.49 / 141.33 = **3.343 tests per pathway**.

**Cross-check by two independent routes:** (a) closed-form division as above; (b) bisection on the optimal spend mix in `tipping_points()`, which returns 3.343203. The two agree to four significant figures.

Below the threshold the model spends 100% on diagnostics; at 3.40 it switches to 77% in-house / 23% outsourcing and the outcome floors at 31,747 breaches cleared.

### 4.3 Triangulation of the unsourced parameter

Observed DM01 diagnostic activity per completed RTT pathway across the 12 core trusts, 84 months of data:

- trailing 12 months: **0.84**
- full window: **0.76**
- range: 0.60 – 0.91 (never above 1.0 in any single month)

Against a model assumption of 1.75 and a tipping point of 3.34.

**This does not settle the parameter, and is not presented as doing so.** Three caveats are recorded on the face of the workbook:

- DM01 covers 15 test types and no pathology at all, so it **understates** total diagnostic input per pathway.
- Not every DM01 test sits on an RTT pathway (direct-access and GP-requested activity is included), so it **overstates** tests attributable to RTT completions.
- The model parameter is **marginal** (tests to unlock one additional pathway); the proxy is an **average** across all activity. These are different quantities.

The two measurement biases run in opposite directions and neither is quantified, so no net correction is applied or implied. What the proxy establishes is narrower and still useful: the observed ratio has never in 84 months approached the level at which the recommended strategy would change. **The direction of the recommendation is better evidenced than the magnitude of the benefit it produces.**

### 4.4 Weight stability of the recommendation

**Superseded by §3.3. The original claim here was wrong, and is retained in corrected form rather than deleted.**

After the delivery-risk fix, the position is: S1, S2 and S5 tie at 274 and are the same commitment. S7 scores 295 under equal weights but takes first place under both delivery-risk weightings (×2 and ×3). Two strategies therefore place first across the eight tests, and **the recommendation is not weight-stable.**

This is reported as the finding. The choice between S2 and S7 depends on how much weight the Board places on exposure to unsourced delivery assumptions, and the analysis cannot settle it. S7 clears roughly half as many breaches but carries zero exposure.

---

## 5. Checks performed

| Check | Result |
|---|---|
| Phase 3 baseline reproduced from warehouse | Pass: exact match on 6 headline quantities |
| LP solves successfully in all 40 strategy × scenario cells | Pass |
| Budget constraint respected in every cell | Pass (≤ envelope + £1 tolerance) |
| Reduction never exceeds baseline, per provider and in total | Pass |
| Equity share within [0, 1] in every cell | Pass |
| Equity figures reproducible across repeated runs | Pass, after lexicographic fix |
| Delivery-risk figures reproducible across repeated runs | Pass, after third lexicographic stage |
| Generalised toolkit reproduces this engine, 40 cells × 6 metrics | Pass: max difference 1.5×10⁻⁸ |
| Toolkit produces a coherent, different analysis on a second configuration | Pass: see `FRAMEWORK.md` |
| Excel per-row ranks vs engine, 4 objectives × 40 rows | Pass: 0 mismatches |
| Excel sum-of-ranks vs engine, 8 strategies | Pass: exact |
| Excel worst-case regret vs engine, 8 strategies | Pass: exact |
| Excel derived columns (equity share, breaches per £1m) vs engine | Pass: 40 rows |
| Excel criticality vs engine, 6 drivers | Pass: exact |
| Independent re-solve of the recommended cell | Pass: 60,649 vs 60,649 |
| Workbook formula recalculation | Pass: 402 formulas, 0 errors |
| Tipping point by two independent methods | Pass: agree to 4 s.f. |
| Tornado stability at a second anchor | Pass: no driver flips |
| Degenerate strategy pairs detected and reported | S1 ≡ S5 flagged in output |

---

## 6. Known limitations

1. **Provider-level allocations are not unique.** The LP remains degenerate. Totals, constraint satisfaction, and the lexicographically-resolved equity and delivery-risk figures are reliable; a specific provider-by-provider split is not, and should not be read as a distribution plan.

2. **S1, S2 and S5 are the same commitment.** Neither the outsourcing lock nor the equity constraint binds at any funding level examined, so all three produce identical results everywhere. This is reported as a finding rather than concealed: the 15pp equity tolerance in the Phase 3 model is decorative, and the choice among the three has to be made on institutional grounds the model does not capture.

3. **Three inputs are judgement, not computation,** and are marked in amber on the face of the workbook: the flexible and insurable scores, the institutional feasibility ratings, and the plausible ranges for driving forces where no measured distribution exists.

4. **The delivery-risk objective is a construction of this analysis,** defined as the share of delivered capacity resting on levers whose capacity assumptions are grade-4 estimates. It is not a standard NHS measure. The weight-sensitivity test covers the risk that the recommendation depends on it; S2 leads even when this objective is tripled and when it is one of four equally weighted.

5. **Scenarios carry no probabilities.** In the intuitive-logics tradition they test plausibility. No expected-value calculation across scenarios is offered, and none should be inferred.

6. **Flag F1 has no internal data source.** The funding envelope is the single highest-impact uncertainty in the model and cannot be monitored from the warehouse. It must be tracked through the finance route.

7. **One counter-indication is live.** Flag F3: the share of the DM01 diagnostic waiting list waiting over six weeks has risen from 6.2% to 9.9% in twelve months. The recommended strategy assumes 10% headroom for additional diagnostic activity. This trend runs against the recommendation and is the most important thing to watch.

---

## 7. Reproduction

```bash
python3 scripts/build_solver_inputs.py        # warehouse -> /tmp/solver_model_inputs.json
python3 scripts/scenario_wayfinding.py        # engine    -> /tmp/scenario_wayfinding.json
python3 scripts/scenario_early_warning.py     # flags + triangulation
python3 scripts/build_scenario_workbook.py    # workbook
python3 <xlsx-skill>/scripts/recalc.py /tmp/NHS_CM_Scenario_Strategy_Model.xlsx
```

Note the standing environment constraint: build against a copy of `nhs_warehouse.db` in `/tmp` and copy finished artefacts across. Writing to the warehouse in place on the synced mount fails on DuckDB's WAL checkpoint.
