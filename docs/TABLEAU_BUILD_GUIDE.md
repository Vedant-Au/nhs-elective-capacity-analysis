# NHS Cheshire & Merseyside — Tableau Story Build Guide

Data is ready in `tableau/` (11 CSVs). This guide is the click-by-click for building the actual `.twbx` in Tableau Desktop — I can't hand-author Tableau's binary/XML formats reliably, so this phase splits the way the Excel Solver phase did: I prepared the data and the design, you build the workbook. Written for Tableau Desktop 2023.x+ (menu paths below match that generation of the UI — if your version's menus differ slightly, the underlying concept is the same).

Five story points, each its own dashboard, sequenced into one Tableau Story:

1. The Backlog — RTT waiting list trend, pre/post-COVID
2. Where's the pressure worst? — pressure index by provider
3. What's driving it? — deprivation cross-cut, consultant staffing, clusters
4. Where's this heading? — 18-month forecast with uncertainty bands
5. What can be done? — capacity-optimizer results

Budget roughly 2-3 hours for a first pass (longer if this is your first Tableau build) — 11 sheets, 5 dashboards, 1 story, plus the dual-axis/band techniques in story points 1 and 4 which take some trial and error even for experienced builders.

---

## 0. Files in `tableau/`

| File | Grain | Rows | Purpose |
|---|---|---|---|
| `dim_provider.csv` | 1 row/provider | 12 | Hub table: name, type, LA, deprivation rank, `higher_deprivation` flag |
| `rtt_trend_provider_month.csv` | provider-month | 1,005 | Waiting list size, over-18wk/52wk shares, completions |
| `pressure_index_provider_month.csv` | provider-month | 1,005 | Composite pressure index (0-100) + 6 underlying signals, averaged across specialties |
| `pressure_index_provider_specialty_month.csv` | provider-specialty-month | 10,951 | Same, at full specialty grain — only needed for drill-downs |
| `pressure_clusters.csv` | provider-specialty | 172 | Which of 4 behavioural clusters each provider-specialty series falls into |
| `inequality_deprivation.csv` | 1 row/provider | 12 | IMD rank/score, mean pressure, consultants per 1,000 FTE — the inputs behind the correlation stats |
| `inequality_correlations.csv` | 1 row/stat | 8 | Spearman rho, p-value, bootstrap CI for each deprivation-vs-outcome pair, with and without specialist centres |
| `forecast_provider_month.csv` | provider-month | 1,224 | Historical + 18-month forecast, with MC p5/p50/p95 bands |
| `forecast_model_selection.csv` | provider-method | 48 | Which forecasting method won per provider (backtest MAPE) |
| `solver_results_provider.csv` | 1 row/provider | 12 | Capacity optimizer's £15m allocation: lever mix, baseline/residual breaches, cost |
| `solver_budget_sensitivity.csv` | 1 row/budget level | 9 | How the optimal allocation changes from £2m to £130m |

**Two gotchas baked into the data already — don't re-derive these differently in Tableau:**

- **IMD rank direction is inverted from intuition.** Rank **1 = most deprived** local authority in England (out of 317). So low `la_imd_rank` / `imd_avg_rank` = high deprivation. `dim_provider.higher_deprivation` is already a pre-computed boolean (median-split) — use that for coloring instead of trying to eyeball the raw rank.
- **Two deprivation-rank columns exist and are NOT interchangeable in general** (though in this specific 12-provider set they agree): `dim_provider.la_imd_rank` (from `dim_imd2019_local_authority.imd_rank_of_avg_rank`) is the one used everywhere else in this project. `inequality_deprivation.imd_avg_rank` is a separately-sourced field that the correlation stats in `inequality_correlations.csv` were actually computed against — keep that pairing intact (i.e., when you build the deprivation scatter in story point 3, pull `imd_avg_rank` from `inequality_deprivation.csv`, not `la_imd_rank` from `dim_provider.csv`, so your chart matches the printed rho/p-value).

---

## 1. Connect the data

1. Open Tableau Desktop → on the start screen, under **Connect → To a File**, click **Text File** → browse to the `tableau/` folder → select `dim_provider.csv` → **Open**. This lands you on the Data Source canvas with `dim_provider` as the only table so far.
2. In the left-hand **Files** pane (still on the Data Source tab), you'll see the rest of the CSVs in the same folder listed automatically since they share a directory. One at a time, drag each of the following 9 onto the canvas, dropping it near (not on top of) `dim_provider`:
   `rtt_trend_provider_month.csv`, `pressure_index_provider_month.csv`, `pressure_index_provider_specialty_month.csv`, `pressure_clusters.csv`, `inequality_deprivation.csv`, `forecast_provider_month.csv`, `forecast_model_selection.csv`, `solver_results_provider.csv`.
3. Each time you drop a new table, Tableau draws a relationship line (a thin noodle with a chain-link icon) back to `dim_provider` and opens a small editor beneath the canvas. Click that editor and confirm the join clause reads **`provider_org_code` = `provider_org_code`** on both sides — Tableau usually guesses this correctly from the matching column name, but check every single one, since a wrong auto-guess (e.g. matching on `provider_org_name` instead) will silently produce wrong aggregates later with no error shown.
4. Leave `inequality_correlations.csv` and `solver_budget_sensitivity.csv` **unconnected to this canvas** — don't drag them on. They have no `provider_org_code` column to relate on, and forcing a relationship (or worse, a join) against a table with no shared key produces either an error or a Cartesian-product row explosion. Instead:
   - Click the **+** next to the data-source tabs at the bottom-left of the screen (or **Data → New Data Source**) to add each as its own independent data source, connected the same way (Connect → Text File → select the CSV). You'll end up with 3 data source tabs total in this workbook: `NHS Capacity Model` (the 9-table relationship canvas), `Inequality Correlations`, and `Budget Sensitivity`.
5. Rename the main data source: double-click the `dim_provider+` tab name at the bottom → type `NHS Capacity Model`. Rename the other two similarly (`Inequality Correlations`, `Budget Sensitivity`) so the Data pane in each sheet is legible.
6. In the Files pane on the `NHS Capacity Model` canvas, single-click each table icon and rename it in the top-left label field to something readable — `dim_provider` → `Providers`, `rtt_trend_provider_month` → `RTT Trend`, `pressure_index_provider_month` → `Pressure Index (Provider)`, `pressure_index_provider_specialty_month` → `Pressure Index (Specialty)`, `pressure_clusters` → `Clusters`, `inequality_deprivation` → `Deprivation`, `forecast_provider_month` → `Forecast`, `forecast_model_selection` → `Forecast Model Selection`, `solver_results_provider` → `Solver Results`. These names are what you'll see in the Data pane on every sheet, so getting them readable now saves confusion for all 11 sheets you're about to build.
7. Click **Sheet 1** at the bottom to leave the Data Source tab and start building.

**Verify the relationships are actually working before building anything:** on Sheet 1, with the `NHS Capacity Model` source active, drag `provider_org_name` (from Providers) to Rows and `SUM(waiting_list_size)` (from RTT Trend) to Text. You should see 12 rows, each with a non-null, non-zero total. If you see nulls, or fewer than 12 rows, go back to the Data Source tab and re-check the relationship clause on RTT Trend — this is the single most common thing that goes wrong at this stage.

---

## 2. Formatting conventions (set these once, keep them everywhere)

- **Provider color palette:** on the first sheet where you drop `provider_org_name` onto **Color** (this'll be Sheet 1a), click the **Color** legend on the right → **Edit Colors...** → with the palette dropdown set to a categorical one (Tableau 20 is good for 12 distinct items) → click each provider name in the list and assign it a color, OR just click **Assign Palette** to auto-assign, then manually swap 1-2 if any look too similar. Click **OK**. From this point on, every subsequent sheet that uses `provider_org_name` on Color will inherit this exact mapping automatically (Tableau keys the mapping to the field name + data source, not per-sheet) — this is what makes a story look coherent rather than assembled from random default palettes. Don't re-edit the color mapping on a later sheet unless you want to change it everywhere.
- **Deprivation color:** wherever `higher_deprivation` (True/False) is used, right-click the Color legend → Edit Colors → set True to a solid dark blue (e.g. `#08519C`) and False to a neutral grey (`#BDBDBD`). Keep this consistent across every sheet in story point 3.
- **Cluster color:** wherever `cluster` (values 1-4) is used, first convert it to a discrete/categorical field if Tableau treats it as continuous (right-click the `cluster` pill wherever it's used → **Convert to Discrete**), then Edit Colors with a 4-color categorical palette. This only appears on sheet 3c, so no cross-sheet consistency to worry about.
- **Dashboard size:** on every dashboard (not sheet), in the left Dashboard pane under **Size**, choose **Fixed Size** and enter **1366 × 768**. Do this before placing objects — resizing after you've laid things out will scramble the layout.
- **Number formatting — set on the pill, not just the axis:** right-click a measure pill (in the Data pane, on a shelf, or on the axis) → **Default Properties → Number Format...**:
  - `pressure_index_0_100` → Number (Custom), 1 decimal place.
  - `over18_share`, `over52_share`, `pct_reduction` → Percentage, 1 decimal place.
  - `cost_18mo`, `total_cost` → Currency (Custom), format string `£#,##0,,"m"` for millions (the two trailing commas divide by a million; this is a standard Tableau custom-format trick) or `£#,##0` if you'd rather show full pounds.
- **Font/title consistency:** Format → Workbook Theme (Tableau 2023.3+) if available, or manually keep chart titles in Sentence case and consistent font size (Format → Font) across sheets — small thing, but noticeable if skipped.

---

## 3. Story Point 1 — "The Backlog"

**Data source:** `NHS Capacity Model` → tables `RTT Trend` + `Providers`

### Sheet 1a — "Waiting List Trend"

1. New Worksheet, rename the tab `1a Waiting List Trend`.
2. Drag `period_month` from **RTT Trend** to the **Columns** shelf. Click the pill's dropdown arrow → confirm it's set to the green continuous **Month** (not Year, not discrete/blue) — you want a continuous monthly time axis.
3. Drag `waiting_list_size` to **Rows**. It lands as `SUM(waiting_list_size)` by default — leave it as Sum (this is a stock, not a flow, but summing across the 12 providers for the "all providers" default view is what you want; per-provider color breaks it out anyway).
4. Drag `provider_org_name` (from **Providers**) onto **Color**.
5. On the **Marks** card dropdown (top-left of the Marks card, currently "Automatic"), set it to **Line**.
6. Set up the provider color palette now if you haven't already (see Section 2 above) — this is the sheet where you do it first.
7. Add the COVID reference line: click the **Analytics** tab (next to Data, top-left) → drag **Reference Line** onto the view → drop it under **Table** scope → in the dialog, set Value to **Constant** → type the date `3/1/2020` (or use the date picker) → Label: Custom → type `COVID-19 onset` → Line: dashed, grey. Click OK.
8. Format the Y-axis: right-click the vertical axis → Edit Axis → Title: `Waiting list size`. Right-click the X-axis → Edit Axis → Title: `Month`.
9. Sheet title: double-click the default title at top → change to `Waiting List Trend, Apr-2019 to Mar-2026`.

### Sheet 1b — "Breach Share Trend"

1. New Worksheet, rename `1b Breach Share Trend`.
2. Drag `period_month` to Columns (continuous Month, same as above).
3. Drag `over18_share` to Rows.
4. Drag `over52_share` to Rows again, to the **right** of the first pill — you'll now have two rows/panes stacked vertically.
5. Right-click the `SUM(over52_share)` pill (the second one) → **Dual Axis**. This merges the two into one pane with two Y-axes.
6. Right-click the right-hand axis → **Synchronize Axis** — leave this **OFF**, since `over18_share` and `over52_share` are on meaningfully different scales (18-week breaches are a much bigger share than 52-week) and forcing them to share a scale will flatten the 52-week line into near-invisibility.
7. On the Marks card, you'll now see two mini Marks cards (one per measure) — set both to **Line**.
8. Try `provider_org_name` on Color first; if 12 lines × 2 measures × dual-axis is too cluttered to read, remove it and leave both lines as unbroken ICB-wide averages instead — build both versions in 2 minutes and keep whichever is legible. There's no wrong answer here, just readability.
9. Format both axes: left axis title `Over-18wk share`, right axis title `Over-52wk share`, both as Percentage.

### KPI cards

Build 3 small single-value tiles for the dashboard header.

1. New Worksheet, rename `1c KPI Latest Waiting List`.
2. Create a calculated field to isolate the most recent month: **Analysis menu → Create Calculated Field...** → name it `Is Latest Period`, formula:
   ```
   [period_month] = {FIXED : MAX([period_month])}
   ```
   Click OK. This is a Fixed Level-of-Detail calculation — it computes the single latest date across the *entire* data source regardless of any other filters on the sheet, then compares each row's own month to it.
3. Drag `Is Latest Period` to the **Filters** shelf → in the dialog check only **True** → OK.
4. Drag `waiting_list_size` to **Text** on the Marks card. It'll show as `SUM(waiting_list_size)` for just the latest month now (since every other month is filtered out).
5. Set Marks card type to **Text**, then format the number large: click **Text** on the Marks card → **Edit Label...** → increase font size to ~36pt, bold.
6. Repeat this pattern (duplicate the sheet via right-click tab → Duplicate) for `over18_share` and `over52_share`, swapping the measure on Text each time. Rename the duplicated tabs `1d KPI Over18 Share` and `1e KPI Over52 Share`.

### Dashboard 1 layout

1. New Dashboard, rename `1 The Backlog`. Set Fixed Size 1366×768 (Section 2).
2. Drag the 3 KPI sheets into a horizontal row across the top (~150px tall).
3. Drag `1a Waiting List Trend` below, large (~400px tall).
4. Drag `1b Breach Share Trend` below that, or side-by-side with 1a if space allows.
5. **Add the highlight action:** Dashboard menu → **Actions...** → **Add Action → Highlight**. Source Sheets: `1a Waiting List Trend`. Target Sheets: same sheet (self-highlight) or leave default "All Sheets Using This Data Source". Run action on: **Hover**. Clearing the selection: **Show all values**. Click OK. Now hovering one provider's line dims the other 11 — this is the single most effective touch for a 12-series line chart.

---

## 4. Story Point 2 — "Where's the pressure worst?"

**Data source:** `NHS Capacity Model` → tables `Pressure Index (Provider)` + `Providers`

### Sheet 2a — "Pressure Index by Provider"

1. New Worksheet, rename `2a Pressure Index Ranking`.
2. Drag `provider_org_name` to **Rows**.
3. Drag `pressure_index_0_100` to **Columns**. It lands as `SUM` — right-click the pill → **Measure → Average** (you want the mean across all months for this provider, not a sum of monthly index values, which is meaningless).
4. Sort descending: click the little sort icon that appears on the axis toolbar when you hover over it (or right-click the `provider_org_name` header → **Sort** → By: Field → `AVG(pressure_index_0_100)` → Descending).
5. Drag `higher_deprivation` (from **Providers**) onto **Color**. Set colors per Section 2.
6. Marks card → **Bar**.
7. Axis title: `Mean pressure index (0-100)`.

### Sheet 2b — "Pressure Index Trend by Provider"

1. New Worksheet, rename `2b Pressure Index Trend`.
2. Drag `period_month` to Columns (continuous Month).
3. Drag `pressure_index_0_100` to Rows → set to **Average**.
4. Drag `provider_org_name` to Color.
5. Marks card → **Line**.
6. If overlaying 12 lines looks noisy, try the trellis alternative: drag `provider_org_name` onto **Rows** to the *left* of `period_month`'s pane — this creates one small chart per provider stacked vertically (a "small multiples" trellis). Build both, pick whichever tells the story more clearly; the trellis is usually better for a "where's this worst and since when" read but takes more vertical space.

### Dashboard 2 layout

1. New Dashboard, rename `2 Pressure Worst`. Fixed 1366×768.
2. Place `2a Pressure Index Ranking` on the left third, `2b Pressure Index Trend` on the right two-thirds.
3. Add a Highlight action same as Dashboard 1, sourced from either sheet, so clicking a bar in 2a highlights that provider's line in 2b.

---

## 5. Story Point 3 — "What's driving it?"

**Data source:** `Inequality Correlations` (standalone) provides the printed stats; `NHS Capacity Model` → table `Deprivation` provides the scatter data (this table is itself provider-grain, so it can be used with or without a relationship back to Providers — using it standalone is simplest here since it already has `provider_org_name`, `is_specialist_centre`, etc. baked in).

### Sheet 3a — "Deprivation vs Pressure"

1. New Worksheet, rename `3a Deprivation vs Pressure`.
2. Drag `imd_avg_rank` (from **Deprivation**) to Columns.
3. Drag `mean_pressure_index` to Rows.
4. Both pills default to continuous measures already at provider grain (1 row per provider), so no aggregation change needed — but double check: right-click each pill, confirm it says `AGG(imd_avg_rank)` not `SUM`; if it shows SUM change it to **Attribute** or simply drag `provider_org_name` onto Detail first so Tableau treats each provider as its own mark rather than aggregating them together.
5. Drag `provider_org_name` onto **Detail** (so each provider is its own point) and onto **Label** (so names show on the chart).
6. Drag `is_specialist_centre` onto **Color**.
7. Drag `total_fte` onto **Size**.
8. Marks card → **Circle**.
9. Add a trend line: Analytics tab → drag **Trend Line** onto the view → drop under **Linear**.
10. Add the annotation: right-click an empty area of the plot → **Annotate → Area** → type:
    ```
    Spearman rho = 0.49, p = 0.11 (n=12)
    Not statistically significant — the visual trend
    should not be read as a confirmed relationship.
    ```
11. Reverse the X-axis reading, or at minimum label it clearly: right-click the X-axis → Edit Axis → Title: `IMD rank (1 = most deprived nationally)`. (Optionally tick **Reversed** under the axis range so "more deprived" reads left-to-right as "worse", i.e. rank 1 on the right — try it both ways and keep whichever reads more intuitively; either is defensible as long as the axis title makes the direction explicit.)

### Sheet 3b — "Consultant Staffing vs Deprivation"

1. Duplicate Sheet 3a (right-click tab → Duplicate), rename `3b Staffing vs Deprivation`.
2. Swap the Rows pill from `mean_pressure_index` to `consultants_per_1000_fte`.
3. Update the annotation text:
    ```
    Spearman rho = -0.59, p = 0.044 (n=12)
    Statistically significant — more-deprived catchments
    actually have MORE consultants per 1,000 FTE, not
    fewer. The clearest relationship in this inequality
    analysis, though it runs opposite to the assumption
    that deprivation correlates with under-staffing.
    ```
    (Note: `imd_avg_rank` runs 1=most deprived upward, so a *negative* correlation with `consultants_per_1000_fte` means staffing falls as rank rises — i.e. falls as deprivation *decreases*. Read the sign against the rank direction, not against "deprivation" directly, or it's easy to get this backwards.)
4. Give this sheet visual prominence when you lay out the dashboard (larger panel, not squeezed) — it's the one result that clears significance.

### Sheet 3c — "Pressure Profile Clusters"

1. New Worksheet, rename `3c Pressure Clusters`, data source `NHS Capacity Model` → table `Clusters`.
2. Drag `rtt_over18_share` to Columns → set to **Average**.
3. Drag `dm01_breach` to Rows → set to **Average**.
4. Drag `cluster` onto **Color** (convert to discrete first — right-click the pill → **Convert to Discrete** — then it'll appear blue/categorical instead of green/continuous).
5. Drag `provider_org_code` and `treatment_function_code` onto **Detail** (so each provider-specialty pair is its own point, not aggregated together).
6. Marks card → **Circle**.
7. Build the tooltip: click **Tooltip** on the Marks card → edit the text to include `<cluster_mean_pressure>` and `<cluster_size>` alongside the default fields, so hovering any point explains "Cluster 2 — mean pressure 54.3, 135 series" in plain language.

### Dashboard 3 layout

1. New Dashboard, rename `3 What's Driving It`. Fixed 1366×768.
2. Top row: `3a Deprivation vs Pressure` and `3b Staffing vs Deprivation` side by side, roughly equal width but give 3b slightly more visual weight (border, or a "Significant" badge text box) since it's the finding that holds up.
3. Bottom: `3c Pressure Clusters` full width.

---

## 6. Story Point 4 — "Where's this heading?"

**Data source:** `NHS Capacity Model` → tables `Forecast`, `Forecast Model Selection`, `Providers`

This is the fiddliest sheet in the whole workbook — the historical/forecast split and the uncertainty band both need small calculated fields and a dual-axis trick. Two calculated fields first, then the sheet build.

### Calculated fields (Analysis → Create Calculated Field)

**`Historical Value`:**
```
IF NOT [is_forecast] THEN [waiting_list_size] END
```

**`Forecast Value (Median)`:**
```
IF [is_forecast] THEN [mc_p50] END
```

These split one continuous line into two fields — historical rows populate the first and return null on the second, forecast rows do the opposite — so you can format them with different line styles without a messy filter-based workaround.

### Sheet 4 — "18-Month Forecast with Uncertainty"

1. New Worksheet, rename `4 Forecast`.
2. Drag `period_month` to Columns (continuous Month).
3. Drag `Historical Value` to Rows.
4. Drag `Forecast Value (Median)` to Rows, to the right of the first pill.
5. Right-click the `Forecast Value (Median)` pill → **Dual Axis**.
6. Right-click either axis → **Synchronize Axis** — this time turn it **ON** (both fields are the same waiting-list-size unit, so they must share a scale, unlike the 1b sheet).
7. On the Marks card, you'll see two mini-cards. Set both to **Line**. On the `Historical Value` layer, leave the line solid. On the `Forecast Value (Median)` layer, click the line thickness/style dropdown in the Format pane (or Format menu → Lines → Pane tab) and set the dash pattern to dashed.
8. Add the uncertainty band. Two options — try the simple one first, upgrade to the filled band only if you have time to spare:
   - **Option A (reliable, recommended default):** drag `mc_p5` to Rows (third pill) and `mc_p95` to Rows (fourth pill). Dual-axis and synchronize each against the same axis as above. Set both to **Line**, thin (1px), light grey, dashed. This draws the 90% interval as two faint bounding lines around the solid/dashed median — not as polished as a filled band, but bulletproof and quick.
   - **Option B (filled band, more polish, more fiddly):** instead of two thin lines, use two **Area** marks layered to fake a band: put `mc_p95` on its own dual-axis layer as an **Area** mark, colored light blue at ~30% opacity. Put `mc_p5` on another dual-axis layer as an **Area** mark colored **white** (matching the dashboard background) at 100% opacity, layered on top. The white area masks out everything below the p5 line, leaving only the p5-to-p95 gap visible as a colored band. Layer order depends on the order you added the pills to Rows — if the mask doesn't cover correctly, drag the pills into the opposite order on the Rows shelf and check again. This is the standard Tableau community technique for confidence bands; it's inherently a bit trial-and-error, budget 15-20 minutes if you go this route.
9. Add a filter for provider: drag `provider_org_name` to the **Filters** shelf → select all, or set a default → also drag it to a **Filter card** on the dashboard (see below) as a single-select dropdown, since 12 overlapping forecast lines with bands is unreadable. Alternatively, right-click the field in the Data pane → **Show Filter**, then on the filter card that appears, change its dropdown (top-right corner of the card) to **Single Value (dropdown)**.
10. Tooltip: drag `method` and `backtest_mape` from **Forecast Model Selection** onto **Tooltip** on the Marks card (this works because both tables relate through Providers) — filter that table to `is_winner = True` first via a Data Source filter (Data menu → Edit Data Source Filters → Add → `is_winner` = True) so only the winning method shows, not all candidate methods.

### Dashboard 4 layout

1. New Dashboard, rename `4 Forecast`. Fixed 1366×768.
2. Filter control (the provider single-select) top-left, small.
3. Sheet 4 filling most of the canvas.
4. A text box, bottom or corner: `18-month forecast via Monte Carlo simulation. Shaded/bounded region = 90% interval (p5-p95), not a guarantee. Method and backtest accuracy shown per provider on hover.`

---

## 7. Story Point 5 — "What can be done?"

**Data source:** `NHS Capacity Model` → table `Solver Results` (+ `Providers`) for sheets 5a/5b; `Budget Sensitivity` (standalone) for sheet 5c.

### Sheet 5a — "Baseline vs Residual Breaches"

1. New Worksheet, rename `5a Cleared vs Remaining`.
2. Optional but recommended for clean legend labels — create 2 calculated fields:
   ```
   Cleared (Breaches Avoided)
   [reduction_18mo]
   ```
   ```
   Remaining (Residual Breaches)
   [residual_over52_18mo]
   ```
3. Drag `provider_org_name` to Rows.
4. Sort descending by `baseline_over52_18mo`: right-click the `provider_org_name` header → Sort → By Field → `SUM(baseline_over52_18mo)` → Descending.
5. Drag `Cleared (Breaches Avoided)` to Columns.
6. Drag `Remaining (Residual Breaches)` to Columns, to the right of the first.
7. On the toolbar, click **Show Me** (top-right) and pick **stacked bar** — Tableau will convert the two Columns measures into a Measure Names/Measure Values stacked bar automatically. If it doesn't offer the right chart, do it manually: this creates a `Measure Names` pill on Color and `Measure Values` on Columns — that's the setup you want either way.
8. Recolor `Measure Names` legend: Cleared → a positive green, Remaining → a muted red/grey.
9. Axis title: `Over-52wk breaches, 18-month horizon`.

### Sheet 5b — "Lever Mix by Provider"

1. New Worksheet, rename `5b Lever Mix`.
2. Drag `provider_org_name` to Rows (same sort order as 5a for visual consistency — right-click → Sort → By Field → `SUM(baseline_over52_18mo)` from the Solver Results table → Descending, or manually match the order).
3. Drag `x1_inhouse_monthly`, `x2_outsource_monthly`, `x3_diagnostic_monthly` all onto **Columns** one after another.
4. Show Me → stacked bar (same Measure Names/Measure Values pattern as 5a).
5. Recolor: give x3 (diagnostic) a distinct strong color since it'll dominate the £15m scenario — this is the visual point of the sheet.
6. Add a text box on the dashboard (not the sheet) noting: "At £15m, spend is concentrated on the diagnostic lever — the cheapest per-breach-avoided option once in-house and outsourcing were corrected to an equal £472.49 unit cost (see Excel Assumptions tab)."

### Sheet 5c — "Budget Sensitivity"

1. New Worksheet, rename `5c Budget Sensitivity`, data source `Budget Sensitivity`.
2. Drag `budget` to Columns. Right-click → confirm it's continuous (green).
3. Drag `pct_reduction` to Rows.
4. Marks card → **Line**.
5. Optional second axis: drag `total_cost` to Rows, dual-axis, synchronize off (different units/scales).
6. Add reference line at the current model default: Analytics tab → **Reference Line** → Constant → Value `15000000` → Label `Current model default (£15m)` → dashed.
7. Format `budget` axis as currency millions (Section 2's custom format), `pct_reduction` as percentage.
8. Text box on the dashboard: "Allocation shifts materially past ~£90m as the diagnostic lever saturates and in-house/outsourcing activate — a step-change in the curve, not smooth scaling."

### Dashboard 5 layout

1. New Dashboard, rename `5 What Can Be Done`. Fixed 1366×768.
2. Top-left: `5a Cleared vs Remaining`. Top-right: `5b Lever Mix`.
3. Bottom, full width: `5c Budget Sensitivity`.
4. Corner text box (small, muted styling — this is a caveat, not a headline): "Diagnostic tests-per-pathway ratio (1.75) is an analyst estimate, not sourced from a cost dataset — every other cost input is from NHS National Cost Collection 2024/25 and the 2025/26 NHS Payment Scheme."

---

## 8. Assemble the Story

1. Click the **New Story** icon at the bottom of the workbook (next to the New Dashboard icon), or **Story → New Story**.
2. In the left Story pane, under **Size**, pick a size that matches your dashboards — either select 1366×768 directly from the preset list, or **Custom** if it's not offered.
3. Drag `1 The Backlog` from the sheet list onto the story canvas — this becomes story point 1.
4. Click **Add a caption** above the canvas and type: `A backlog that never fully recovered`.
5. Click the **+** that appears to the right of the current story point to add a new one. Drag `2 Pressure Worst` onto it, caption: `Pressure isn't evenly spread`.
6. Repeat for the remaining 3: `3 What's Driving It` → `What's really driving it — and what isn't`; `4 Forecast` → `Where the next 18 months are heading`; `5 What Can Be Done` → `What £15m of capacity investment can and can't fix`.
7. **Re-verify interactive actions inside the story.** Filter/highlight actions built at the dashboard level sometimes need re-confirming once embedded in a story point — click into each story point, interact with the filter/highlight (hover a line, pick a provider from the dropdown), and confirm it behaves as it did in the standalone dashboard. If a story point's captured state shows a filter applied that you don't want as the *default* view, set the dashboard to the state you want, then click **Update** in the story toolbar (it appears above the active story point) to re-capture that state.
8. Click through all 5 points start to finish once, end to end, before exporting — this catches stale filter states left over from editing (e.g. a provider filter left on "REM" from testing sheet 4, when you meant the default to be "All").

---

## 9. Export

**File → Export Packaged Workbook...** (not File → Save, which produces a `.twb` that only contains *references* to the CSVs, not the data itself). Choose a save location, keep the filename e.g. `NHS_Cheshire_Merseyside_Capacity_Story.twbx`. The packaged workbook bundles the CSVs inside the file, so it stays portable even if the `tableau/` folder moves or is deleted later.

---

## 10. Final QA checklist

- [ ] Same provider = same color on every sheet that shows `provider_org_name` (spot-check 3 sheets from different story points)
- [ ] IMD rank axis in story point 3 correctly reads low-rank-is-worse (axis title states "1 = most deprived nationally" explicitly)
- [ ] Story point 3's deprivation-vs-pressure trend line doesn't visually overstate a non-significant result (rho=0.49, p=0.11) — annotation says so explicitly
- [ ] Story point 4's forecast line clearly distinguishes historical (solid) from forecast (dashed), and the p5-p95 band/lines are visibly distinct from the median, not mistaken for a second forecast line
- [ ] Story point 5's £15m budget reference line is visible on the sensitivity curve (5c) so a viewer can connect the specific allocation (5a/5b) to where it sits on the broader curve
- [ ] Every dashboard fits the fixed 1366×768 canvas with no cut-off elements
- [ ] All filter/highlight actions still work when clicked through inside the assembled Story, not just on the standalone dashboards
- [ ] Exported as **Packaged Workbook (.twbx)**, not `.twb`

---

## Troubleshooting

- **A relationship shows nulls or fewer than 12 providers.** Go back to the Data Source tab, click the relationship line between the two tables, and re-check the join clause — it's almost always matched on the wrong field (e.g. `provider_org_name` instead of `provider_org_code`) or matched against a table where the code has different casing/whitespace (shouldn't happen here since all extracts came from the same warehouse query, but check first).
- **The color legend keeps resetting between sheets.** This happens if the field's data type or role (dimension vs measure) differs between two uses — e.g. if `cluster` is Continuous on one sheet and you convert it to Discrete on another, Tableau treats them as different fields for coloring purposes. Keep field types consistent everywhere you use them.
- **Dual-axis marks won't format independently (both lines change together).** You're clicking the shared Marks card instead of the per-measure mini-card. After creating a dual axis, the Marks card splits into one section per measure — click directly on the measure's name inside the Marks card (not the axis) to get its own Color/Size/Format controls.
- **The Option B filled band (Section 6) shows the wrong shape or no mask.** Layer order matters and isn't always obvious from the Rows shelf order alone — try dragging the two pills into the opposite order, and separately check each layer's mark type didn't silently revert to Automatic (which may render as Bar instead of Area) after the dual-axis conversion.
- **A sheet built from a standalone data source (Inequality Correlations, Budget Sensitivity) can't see `provider_org_name` for coloring/filtering.** That's expected — those two are intentionally not related to the rest (see Section 1, step 4). If you want provider-level color or filtering on a sheet using one of these, you're on the wrong data source for what you're trying to do; the provider-keyed data lives in `NHS Capacity Model` instead.
- **Numbers don't match the reference figures at the bottom of this guide.** Re-check aggregation types first (Average vs Sum is the single most common mismatch) before assuming the data extract is wrong — every figure below was checked directly against the warehouse and the Solver's saved solution before this guide was written.

---

## Appendix: all calculated fields, for copy-paste

```
Is Latest Period
[period_month] = {FIXED : MAX([period_month])}
```

```
Historical Value
IF NOT [is_forecast] THEN [waiting_list_size] END
```

```
Forecast Value (Median)
IF [is_forecast] THEN [mc_p50] END
```

```
Cleared (Breaches Avoided)
[reduction_18mo]
```

```
Remaining (Residual Breaches)
[residual_over52_18mo]
```

---

## Reference: what the numbers should look like (sanity-check against these while building)

- Story point 1: REM (Liverpool University Hospitals) waiting list ~37k (Apr-2019) → ~174k (2022 peak) → ~133k (latest) — steepest trajectory of the 12.
- Story point 3: rho = 0.49 (p=0.11) for deprivation→pressure; rho = -0.59 (p=0.044) for deprivation→consultant staffing — the second is the one that's actually statistically significant.
- Story point 5: at £15m, the model spends entirely on the diagnostic lever (x3) — £0 on in-house/outsourcing (x1/x2) — clearing ~20.5% of the 18-month projected over-52-week breach volume. The split only starts using x1/x2 above roughly £90m in the sensitivity sweep.
