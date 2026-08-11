# NHS Elective Capacity: Analysis, Optimisation and Scenario Strategy

An end-to-end analytics and strategy engagement for **NHS Cheshire and Merseyside ICB (QYG)**, taken from raw open data through to a board-ready recommendation and a reusable toolkit.

> **This is a self-directed project, not a commissioned piece of work.** There is no client and no stakeholder brief. It uses real NHS England open data and is built to the standard of a real ICB analytics engagement, including its assurance discipline. The recommendation is illustrative and has not been reviewed by anyone at the ICB.

---

## What the question was

An ICB has a constrained elective recovery budget, three ways to spend it, and a backlog it cannot clear. Where should the money go, and what would tell us the answer was wrong?

That question needed a warehouse before it needed an answer, so the project runs in seven phases.

| Phase | What was built |
|---|---|
| 1 | Data acquisition and warehousing, seven NHS sources, 84 months |
| 2 | Analytics layer: pressure index, forecasting, clustering, inequality of access |
| 3 | Capacity optimiser (linear programme, delivered as an Excel Solver model) |
| 4 | Tableau story, five story points |
| 5 | Scenario and strategy model |
| 6 | Executive board paper |
| 7 | Generalised, config-driven toolkit |

---

## Headline findings

**It is a money problem, not a capacity problem.** No delivery lever's capacity ceiling binds until the funding envelope reaches £31.9m (independent sector), £69.7m (diagnostic) or £107.1m (in-house). The range under consideration is £7.5m to £30m. Three long-running deliverability debates therefore change the outcome by nothing at all.

**The entire allocation turns on one unsourced number.** Diagnostic and treatment capacity become indifferent at 3.34 diagnostic tests per unlocked pathway. The planning assumption is 1.75, and no NHS dataset publishes the figure. Triangulating it against observed DM01 activity gives 0.84, which is comfortably clear of the threshold but is an average where the model needs a marginal ratio, so it bounds the argument rather than settling it.

**Equity is free here.** The equity tolerance never binds. At every funding level examined, the whole reduction can be directed to higher-deprivation trusts at zero cost to total breaches cleared, because the budget clears far less than those trusts alone are carrying.

**The recommendation is a judgement, not a calculation.** Three of the eight candidate strategies turn out to be the same commitment. The genuine alternative clears roughly half as many breaches but carries no exposure to the weakest assumption in the model. Which one wins depends entirely on risk appetite, and the analysis says so rather than manufacturing a robust-looking answer.

**One expected finding did not survive testing.** More-deprived catchments have *more* consultants per 1,000 FTE, not fewer (Spearman rho −0.59, p = 0.044), and the deprivation-to-pressure relationship is not statistically significant once specialist centres are excluded.

---

## Assurance

Three defects were found and corrected during validation, and all three are documented rather than quietly fixed. They are in the repository because the trail is part of the work.

1. **Equity figures were solver artefacts.** The same 15,873 breaches cleared were reported at both 100% and 29.7% higher-need share depending only on which optimal vertex the solver reached.
2. **Delivery-risk figures were too, and this one changed the recommendation.** Caught only by diffing the generalised toolkit against the engagement engine, one cell in forty. Before the fix the recommendation appeared robust under every weighting; after it, it is a judgement call.
3. **Excel and Python disagreed on the strategy ranking** while the formula checker reported zero errors across 402 formulas. The formulas evaluated correctly and returned wrong numbers.

The rule now enforced throughout: **never rank a quantity the optimisation does not pin.**

A statistical claim was also retracted. "Diagnostic waits rose from 6.2% to 9.9%" was endpoint selection on a series whose full window trends significantly *downward*. See `docs/PHASE5_VALIDATION.md`.

---

## Repository layout

```
config/          Engagement configurations for the toolkit (YAML)
data_raw/        Raw NHS downloads — NOT COMMITTED, see Reproducing below
docs/            Board paper, framework, validation report, build log, figures
excel/           Capacity optimiser and scenario model workbooks
scenarios/       Scenario engine outputs and toolkit run results
scripts/         Loaders, analytics, optimiser, scenario engine, document builders
scripts/toolkit/ The generalised, config-driven pipeline
sql/             Warehouse DDL in build order, plus reference CSVs
tableau/         Packaged story workbook and its data extracts
```

**Start here:** `docs/NHS_CM_Elective_Capacity_Board_Paper.docx` for the argument, `docs/FRAMEWORK.md` for the reusable method, `docs/PHASE5_VALIDATION.md` for how it was checked.

`docs/STATUS.md` is the dated build log kept throughout. It is a working record rather than a polished document, and it is committed deliberately: it shows the reasoning, the wrong turns and the corrections as they happened.

---

## Reproducing

The warehouse and raw data are excluded from version control. The warehouse is ~154MB, above GitHub's hard file limit, and both are fully rebuildable.

```bash
pip install duckdb pandas numpy scipy openpyxl matplotlib pyyaml

bash scripts/download_rtt.sh          # raw downloads, ~135MB
python3 scripts/build_warehouse.py    # builds nhs_warehouse.db

python3 scripts/build_solver_inputs.py
python3 scripts/solve_capacity_optimizer.py
python3 scripts/scenario_wayfinding.py
python3 scripts/scenario_early_warning.py
python3 scripts/build_scenario_workbook.py
python3 scripts/build_report_figures.py
node    scripts/build_board_paper.js
```

The generalised toolkit runs from a single config:

```bash
python3 scripts/toolkit/run.py --config config/cheshire_merseyside.yaml
python3 scripts/toolkit/run.py --config config/cheshire_acute_only.yaml
```

**Note on DuckDB:** on a synced folder (iCloud, Dropbox, OneDrive), writing to the warehouse in place fails on DuckDB's WAL checkpoint. Build in a temporary directory and copy the finished file across.

---

## Data sources

All open data, used under the terms below.

| Source | Publisher | Coverage |
|---|---|---|
| RTT waiting times | NHS England | Apr 2019 – Mar 2026 |
| DM01 diagnostics | NHS England | Apr 2019 – Mar 2026 |
| A&E attendances | NHS England | Apr 2019 – Mar 2026 |
| KH03 bed occupancy | NHS England | Quarterly |
| GPAD appointments | NHS England | Annual snapshot |
| Workforce statistics | NHS England | Annual snapshot |
| Index of Multiple Deprivation 2019 | MHCLG | 2019 |
| National Cost Collection 2024/25 | NHS England | Unit costs |

---

## Method sources

- Cairns, G. and Wright, G. (2018) *Scenario Thinking*, 2nd ed., Palgrave Macmillan
- Sminia, H. (2026) "From Scenario Thinking to Scenario Doing: Strategic Management as Wayfinding", *Futures & Foresight Science* 8:e70038
- Sminia, H. (2022) *The Strategic Manager*, 3rd ed., Routledge

---

## Licence

Code and documentation in this repository are MIT licensed, see `LICENSE`.

The underlying NHS England and MHCLG datasets are published under the **Open Government Licence v3.0** and remain subject to its terms. They are not redistributed here.
