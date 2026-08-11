# Tableau Remediation: `NHS_Cheshire_Merseyside_Capacity_Story.twbx`

**Workbook version:** Tableau 2026.2.1
**Reviewed:** 11 August 2026, by parsing the workbook XML rather than by eye
**Fixes required:** 4 (a fifth item was raised on first review and is withdrawn, see §6)
**Estimated time:** 15 minutes

Work through these in order. Each fix has a verification step; do not skip them, because two of these changes are invisible on screen when applied correctly and equally invisible when applied wrongly.

Before starting: **File → Save As** a copy, so there is something to fall back to.

---

## 1. Delete the leftover `Sheet 1`

**What is wrong:** the workbook contains a worksheet named `Sheet 1` holding `provider_org_name` on Rows and `SUM(waiting_list_size)` on Text. It is exploratory scratch work, not part of the story, and it is not referenced by any dashboard.

**Why it matters:** a stray default-named sheet is the single clearest signal that a workbook was shipped without a final pass. Anyone opening the file sees it in the tab strip before they see anything else.

**Steps**

1. At the bottom of the Tableau window, find the tab named `Sheet 1`.
2. Right-click the tab → **Delete**.
3. Confirm when prompted.

**Verify:** the tab strip runs `1a` through `5c`, then the five dashboards, then the story. No sheet named `Sheet 1` remains.

---

## 2. `3b Staffing vs Deprivation`: change SUM to AVG on the ratio measure

**What is wrong:** the Rows shelf carries `SUM(consultants_per_1000_fte)`. That field is a **ratio**, consultants per 1,000 FTE, and ratios cannot be meaningfully summed.

**Why it matters, and why the chart looks fine today:** `provider_org_name` sits on Detail, so each mark aggregates exactly one row, and SUM of one value equals AVG of one value. The chart is currently correct *by accident*. The moment anyone removes provider from Detail, filters to a group, or reuses the field elsewhere, SUM silently returns a meaningless number, added-up ratios, with no error and no visual cue. This is a latent defect, not a cosmetic one.

**Steps**

1. Open worksheet `3b Staffing vs Deprivation`.
2. On the **Rows** shelf, click the `SUM(consultants_per_1000_fte)` pill.
3. From the dropdown choose **Measure** → **Average**.
4. The pill now reads `AVG(consultants_per_1000_fte)`.

**Do not change** `SUM(total_fte)` on the Size shelf. Total FTE is a genuine count and is correctly summed.

**Verify:** the scatter plot is visually **unchanged**, with the same twelve marks in the same positions. If any mark moves, something else is aggregating more than one row per provider and needs investigating before you go further.

---

## 3. `3a` and `3b`: make the IMD axis direction explicit

**What is wrong:** both sheets put `AVG(imd_avg_rank)` on Columns with a default ascending axis and no directional labelling. IMD rank is **inverted**: rank 1 is the *most* deprived area, high ranks are the *least* deprived. So the chart currently reads left-to-right as most-deprived → least-deprived, which is the opposite of how almost every reader will assume a "deprivation" axis runs.

**Why it matters:** this exact inversion already caused a documented error in this project. The staffing correlation was written up backwards in the build guide, and was only caught when the Tableau trend line visually contradicted the text. The chart is the last line of defence against that mistake being made again by the next reader. Fix it in both sheets.

Pick **one** of the two approaches below and apply it consistently to `3a` and `3b`. Option A is recommended: reversing the axis makes the visual read in the intuitive direction, so no one has to hold the inversion in their head.

### Option A: reverse the axis (recommended)

1. Open `3a Deprivation vs Pressure`.
2. Right-click the horizontal axis → **Edit Axis…**
3. Under **Scale**, tick **Reversed**.
4. Still in the Edit Axis dialog, set **Axis Titles → Title** to:
   `IMD average rank (right = more deprived)`
5. Click **OK**.
6. Repeat steps 2–5 on `3b Staffing vs Deprivation`.

### Option B: keep the axis, label it hard

1. Right-click the horizontal axis → **Edit Axis…**
2. Set **Axis Titles → Title** to:
   `IMD average rank (1 = MOST deprived; left = more deprived)`
3. Click **OK**. Repeat on the other sheet.

**Verify:** read the caption on `3b`, "more-deprived catchments actually have MORE consultants per 1,000 FTE", and check it against the chart. Under Option A the trend line should now slope **downward** to the right; under Option B it slopes **upward** to the right. Either way, confirm the direction you see matches the sentence. If it does not, stop: the annotation and the visual have diverged again.

---

## 4. Rename the `Forecast` dashboard

**What is wrong:** four dashboards follow the pattern `1 The Backlog`, `2 Pressure Worst`, `3 What's Driving It`, `5 What Can Be Done`. The fourth is named simply `Forecast`, breaking the sequence and leaving an apparent gap at position 4.

**Steps**

1. Right-click the `Forecast` dashboard tab → **Rename**.
2. Enter: `4 Where It's Heading`
3. Press Enter.

**Verify. This step is essential.** Renaming a dashboard does **not** automatically relink the story point that captured it. Open the story `NHS Cheshire Merseyside Capacity Story`, click through to story point 4 ("Where the next 18 months are heading") and confirm the forecast dashboard still renders. If the story point is now blank or shows an error, re-drag `4 Where It's Heading` onto that story point from the left-hand pane.

---

## 5. Add the sixth story point (optional)

The Phase 5 scenario extracts are cut and waiting in `tableau/`:

| File | Contents |
|---|---|
| `scenario_strategy_grid.csv` | 40 strategy × scenario outcomes |
| `scenario_regret_matrix.csv` | Worst-case regret per strategy |
| `scenario_driving_forces.csv` | Impact/uncertainty matrix inputs |
| `diagnostic_conversion_observed.csv` | 84 months of observed tests per pathway |
| `scenario_early_warning_flags.csv` | The monitoring flags |

Suggested story point: **"What we should commit to, and what would change our mind"**, with a bar chart of breaches cleared by strategy with scenario on colour, a line chart of `diagnostic_conversion_observed` with reference lines at 1.75 (assumption) and 3.34 (tipping point), and the flags table alongside.

The reference lines are the point of the whole exhibit: they show at a glance that observed conversion has never come close to the level at which the recommendation would reverse.

---

## 6. Withdrawn: the filter on `2b Pressure Index Trend`

On first review I flagged an unlabelled quantitative filter on `AVG(pressure_index_0_100)` in `2b` as a possible leftover from exploratory work.

**That was wrong, and no action is needed.** On closer inspection of the XML the filter is `included-values="non-null"`, Tableau's standard automatic null-exclusion filter, added whenever a measure containing nulls is placed on a shelf. It is not a threshold, it hides no data that should be visible, and removing it would have no effect.

Recorded here rather than quietly dropped, so that the review trail matches what was actually found.

---

## Summary checklist

- [ ] `Sheet 1` deleted
- [ ] `3b` Rows pill reads `AVG(consultants_per_1000_fte)`; chart visually unchanged
- [ ] `3a` IMD axis reversed or explicitly labelled
- [ ] `3b` IMD axis reversed or explicitly labelled, matching `3a`
- [ ] `3b` caption direction re-checked against the visual
- [ ] `Forecast` renamed to `4 Where It's Heading`
- [ ] Story point 4 still renders after the rename
- [ ] Workbook saved as `.twbx` (packaged, so the extracts travel with it)

Save with **File → Save As → Tableau Packaged Workbook (.twbx)**. Saving as `.twb` would leave the workbook pointing at CSVs on your Desktop and it would break for anyone else.
