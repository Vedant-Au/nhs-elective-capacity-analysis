# Build log

Running log, not a polished doc — dated entries, most recent first.

## 2026-08-08 (Tableau story phase)

Solver phase fully closed out (all cost inputs sourced/verified, see prior
entry). Moved to Phase 4: Tableau story. Same constraint hit as the VBA
macro: no Tableau Desktop, and `tableauhyperapi` isn't installable in this
sandbox (`pip install tableauhyperapi --break-system-packages` — no
matching distribution). Can't reliably hand-author `.twb`/`.twbx` binary/XML
without a way to validate against real Tableau. Asked Vedant how to
proceed; he chose: I prepare data + a detailed build guide, he builds the
actual workbook in Tableau Desktop.

Designed a 5-story-point narrative that mirrors this project's own
analytical arc rather than inventing a new one: (1) The Backlog — RTT trend
pre/post-COVID, (2) Where's the pressure worst — pressure index by
provider, (3) What's driving it — deprivation cross-cut + consultant
staffing + pressure clusters, (4) Where's this heading — 18-month forecast
with MC bands, (5) What can be done — capacity optimizer results. Point 5
directly visualizes the Solver output, answering the open question from
the last entry.

Exported 11 CSVs to `tableau/` from the warehouse + the Solver's saved
JSON solutions (`/tmp/solver_model_solution.json`,
`/tmp/budget_sensitivity.json`): a `dim_provider` hub table (12 providers,
with a pre-computed `higher_deprivation` median-split flag) plus RTT trend,
pressure index (both provider-month and provider-specialty-month grain),
pressure clusters, inequality/deprivation stats + correlations, forecast
with MC p5/p50/p95 bands, forecast model selection, and the Solver's
provider-level allocation + budget sensitivity sweep. Script:
`scripts/export_tableau_extracts.py`. Sanity-checked every extract (no
nulls, correct row counts, spot-checked values against known figures — e.g.
REM's waiting list trajectory 37k→174k→133k) before treating them as final.

Two real gotchas documented directly in the build guide so they don't get
silently mis-built in Tableau: IMD rank is inverted (rank 1 = MOST
deprived, not least — easy to get backwards on an axis), and there are two
non-interchangeable deprivation-rank columns in play
(`dim_provider.la_imd_rank` vs `inequality_deprivation.imd_avg_rank`) — the
correlation stats in `inequality_correlations.csv` were computed against
the latter, so the story point 3 scatter needs to pull from that same
column or the printed rho/p-value won't match what's on screen.

Wrote `docs/TABLEAU_BUILD_GUIDE.md` — full step-by-step: data source
relationships (not joins — grain mismatches across the 11 extracts need
Tableau's relationship model), formatting conventions (consistent provider
color palette across every sheet, deprivation/cluster color conventions,
fixed 1366×768 dashboard size), sheet-by-sheet build instructions per story
point with exact shelves/fields/mark types, a caveat callout for the one
unsourced number left in the whole model (1.75 diagnostic
tests-per-pathway), story assembly steps, a final QA checklist, and
reference figures to sanity-check against while building (e.g. rho=-0.59,
p=0.044 for deprivation→consultant staffing is the one statistically
significant inequality finding — worth giving real prominence, not burying
it next to the non-significant pressure correlation).

**Next action:** Vedant builds the `.twbx` in Tableau Desktop following the
guide. Nothing further needed from me here unless he hits a snag or wants
the extracts re-cut. After that: AI decision-support layer (Phase 5),
executive report (Phase 6), generalised framework (Phase 7) — then, per
Vedant's standing instruction, push to GitHub only once the entire project
is done.

## 2026-08-07

Repo scaffold created. Region decided: NHS Cheshire and Merseyside (see charter for
rationale — strong deprivation contrast between Liverpool/Knowsley and the more
affluent Cheshire boroughs, which matters for the inequality-of-access question,
plus a stable set of acute providers to warehouse against). Data window: FY2019-20
through FY2026-27 (year to date), agreed with Vedant over full 2006-26 history —
enough to show pre-COVID baseline, COVID disruption and current recovery without
ingesting a decade of data nobody will reference in the final analysis.

Sandbox has no outbound internet access beyond page fetches (confirmed by a failed
curl to nhs.uk and google.com — both timed out, error 56). So bulk file downloads
have to happen on Vedant's machine, into the connected project folder. Wrote
`scripts/download_rtt.sh` to handle this for RTT — it scrapes each fiscal-year RTT
index page for the "Full CSV data file" link (NHS England randomises a hash suffix
on every publish, so the URLs can't be hardcoded) and pulls anything not already on
disk. Have NOT been able to test-run it myself (no network in this environment) —
first thing to check once Vedant runs it locally is that the files actually landed
and aren't HTML error pages saved with a .zip extension (happens if a page
structure changes and the regex grabs nothing, or if NHS England fronts the
download with a redirect curl doesn't follow).

Deliberately did NOT write the SQL warehouse DDL yet. I know roughly what's in the
RTT full CSV from having looked at NHS RTT publications before (provider code,
commissioner code, part type — Incomplete/Admitted/NonAdmitted/New Periods,
treatment function, banded weeks-waited columns), but I'm not going to guess exact
column names and get the schema subtly wrong. Once real files are on disk I'll
profile the actual header row and build the DDL against it.

Still need download scripts for: DM01 (diagnostics), A&E, KH03 (beds), GPAD, NHS
workforce stats, IMD 2019. RTT was the one I could verify page structure for in
this session — same scrape-don't-hardcode approach should work for the others but
each publication page has its own layout, so writing all six blind risks the same
"looks done, silently downloads nothing" failure mode. Doing them one at a time,
checked against the real page.

### Update, same day
Didn't end up needing the shell script — Vedant has Claude in Chrome connected,
so drove the actual browser to each fiscal-year RTT index page and downloaded
the "Full CSV data file" for every month directly (files land in the real
~/Downloads, then get copied into data_raw/rtt/ from there — the sandbox can
read the connected Downloads folder but can't `mv`/delete from it, only `cp`,
so originals stay in Downloads too). `scripts/download_rtt.sh` is still useful
as a repeatable version of the same logic and is untested — leaving it in the
repo but the actual FY19-20 through FY25-26 pull for this session was done via
browser.

Result: 84/84 months (7 fiscal years × 12), 312MB, all verified as real zip
archives via `file` (not HTML error pages saved with a .zip extension, which
was the failure mode I was worried about). Two outlier files worth flagging
now so they don't look like a scraping bug later: Feb22 and Mar22 are ~110MB
each versus ~3-4MB for every other month — that's NHS England's own file, not
a download error, and probably means those two months' extracts weren't
cleanly deduplicated/compressed the same way on their end. Will need to check
this doesn't break the CSV parser when Phase 1 gets to profiling — possibly a
repeated-header or malformed-row issue in the source file itself.

### Next action
Unzip a handful of these (start with a recent one and the two 110MB outliers)
and profile the actual header row before writing any DDL — don't want to
guess the schema. Then write the same page-scrape approach for DM01, A&E,
KH03, GPAD, workforce, and IMD. RTT is the only dataset pulled so far.

## 2026-08-07 (later same session)

Profiled Mar-2026 and Mar-2022 extracts. Confirmed 121-column schema:
Period / Provider Parent / Provider / Commissioner Parent / Commissioner /
RTT Part Type / RTT Part Description / Treatment Function / 106 weekly wait
bands (Gt 00 To 01 Weeks ... Gt 104 Weeks) / Total / unknown-clock-start /
Total All. Part-type codes are Part_1A/1B/2/2A/3, not English labels — cross-
checked against RTT Part Description in the same row to confirm Part_2 =
Incomplete Pathways (the waiting list), Part_1A/1B = completed admitted/non-
admitted, Part_3 = new clock starts.

The Feb22/Mar22 "110MB" filenames from last entry turned out to be a red
herring, not a real problem — checked actual file sizes on disk and they're
~4.4MB like every other month. NHS labels those two files with the
*uncompressed* CSV size instead of the zip size (inconsistent with every
other month in the naming convention), which is just an NHS-side quirk, not
a scraping bug. Correcting the record since I flagged it as a risk last
entry and don't want that assumption to persist unchallenged into Phase 2.

Pulled the actual Cheshire & Merseyside provider list straight out of the
Mar-2026 data (grep on Provider Parent Name = the ICB), not from a web
search — good thing, because the web search result from Phase 0 had listed
"North Cheshire and Mersey NHS Foundation Trust" as a member trust and that
org doesn't exist anywhere in the real RTT data. 13 core NHS trusts report
under this ICB (listed in sql/reference/cheshire_merseyside_providers.csv),
plus ~12 independent-sector providers (SpaMedica, Spire, Newmedica etc.)
doing NHS-funded elective work under the same ICB, flagged separately since
the Phase 4 capacity model treats "outsourced capacity" as a lever, not
baseline.

Wrote and validated (against DuckDB, loaded with the real Mar-2026 CSV, not
just eyeballed) sql/schema/01_staging.sql, 02_dimensions.sql,
03_fact_rtt_provider_specialty_month.sql. Fact table builds clean: 4,264
rows for Mar-2026 alone, sanity check (over-18wk count can never exceed
total waiting list) passes with zero violations, and the per-trust totals
land in a believable range — Liverpool University Hospitals (REM) at
121,300 incomplete pathways, Mersey and West Lancashire (RBN, a merged
multi-site trust) higher at 155,332, Mersey Care (RW4, mental health, not
core to elective RTT) at just 106. One deliberate gap: no median-wait-time
column — that can't be derived accurately from banded aggregate data
without assuming a distribution within each band, and a fake-precise
"median" column was exactly the false-confidence risk the charter flagged.
If Phase 2's pressure index needs a proxy, it goes in clearly labelled as
an estimate.

One portability note: the DDL originally used a Postgres `ALTER TABLE ...
ADD COLUMN ... GENERATED ALWAYS AS ... STORED` for the long-wait-share
ratio. DuckDB doesn't support adding generated columns after table
creation, so that's now computed inline in the CTAS instead — works on
both engines and is arguably clearer anyway.

### Next action
DM01 (diagnostics) is the natural next pull — same page-scrape-then-browser-
download pattern as RTT, different page structure to check first. Then A&E,
KH03, GPAD, workforce, IMD, in that order (roughly matches how much each one
unblocks — diagnostics and A&E feed the pressure index directly, IMD only
matters once there's something to cross-cut by deprivation).

## 2026-08-07 (later still, same session)

DM01 pulled and warehoused, same session. Scraped all 7 fiscal-year DM01
index pages (2019-20 through 2025-26) via web_fetch — URL list saved to
scripts/dm01_urls.txt for traceability, same reasoning as keeping RTT's
scraped links auditable rather than trusting memory. One naming quirk worth
flagging so it doesn't look like a bug later: Jul-19 and Aug-19 use a
different filename convention entirely (date-prefixed, no hash suffix) —
NHS hadn't standardised the DM01 filename pattern yet in mid-2019. Not a
scraping error.

Downloaded all 84 files via Claude in Chrome (same browser-download-into-
~/Downloads-then-cp pattern as RTT). 84/84 landed, verified as real zip
archives via `file`, no HTML error pages, 105MB total — much smaller than
RTT's 312MB, which makes sense given DM01's schema is far thinner (30
columns vs RTT's 121, 15 wait bands vs 106).

Profiled Mar-2026, Apr-2019 and Jan-2021 extracts before writing any DDL.
Good news this time: schema is completely stable across the whole 7-year
window — same 30 column names, same structure, no part-way format change to
work around like RTT didn't have either but I wasn't sure about DM01 until I
actually checked. Grain is (period, provider, commissioner, diagnostic
test) — no "part type" dimension like RTT, but NHS does publish a "TOTAL"
pseudo-row (Diagnostic Tests Sort Order = 16) that pre-aggregates the other
15 real tests. Verified this row is trustworthy rather than assuming it:
summed the 15 real tests' Total WL per (provider, commissioner) pair on the
Mar-2026 file and compared to the declared TOTAL row — 9,316/9,316 pairs
matched exactly, zero mismatches. Also checked Total WL itself is genuinely
just sum(the 15 weekly bands) — checked all 149,056 rows in the Mar-2026
file, zero mismatches. Both checks needed doing before I could trust the
fact table design (specifically, before deciding it's safe to re-derive the
all-tests rollup from the 15 real tests rather than trusting NHS's own
TOTAL row blindly).

DM01's wait-time bands only go to 13 weeks (00<01 through 12<13, then one
open-ended "13+ Weeks" tail) — makes sense once you remember DM01's
operational standard is a 6-week wait, not RTT's 18/52-week thresholds. Kept
this distinction explicit in the fact table's column names
(waiting_list_over_6wk, not over_18wk) specifically so nobody downstream
copy-pastes an RTT column name onto a DM01 table and silently mixes up the
two standards.

Wrote and validated (DuckDB again, loaded with real Mar-2026 + Apr-2019 +
Jan-2021 data together to catch any year-to-year schema drift) sql/schema/
04_staging_dm01.sql, 05_fact_dm01_provider_test_month.sql, plus a
dim_diagnostic_test table added to 02_dimensions.sql (the 15 test codes are
a closed set, confirmed identical across all three years checked, so
hardcoded rather than derived). Two fact tables: fact_dm01_provider_test_
month at the natural (provider, test, month) grain, and fact_dm01_provider_
month which sums the per-test table to an all-tests-combined view — this is
the one that actually lines up with fact_rtt_provider_specialty_month's
grain for Phase 2's pressure index, since RTT is per-specialty and DM01 is
per-test and neither decomposes into the other. Loaded 478,704 raw rows
across the 3 sample months, built 18,885 provider-test-month rows and 1,259
provider-month rows, zero sanity-check violations (over-6wk count never
exceeds total) on either table. Spot check: Liverpool University Hospitals
(REM) Mar-2026, all tests combined — 18,287 on the diagnostic waiting list,
2,012 (11%) waiting over 6 weeks. Believable range, not obviously broken.

Also closed out a TODO from the RTT dimension table while I was in there:
dim_provider.icb_code had a placeholder note saying RTT only carries the
ICB's full name, not a short code. DM01's Provider Parent Org Code column
does carry the short code — confirmed QYG = NHS Cheshire and Merseyside ICB
directly from the data, not from a web search this time either.

### Next action
A&E next (KH03/GPAD/workforce/IMD after) — same scrape-verify-download-
profile-validate loop. Diagnostics and A&E are the two datasets the Phase 2
pressure index depends on most directly, so getting both warehoused before
starting the Python analytics layer is the right order.

## 2026-08-07 (yet later, same session)

A&E pulled and warehoused. Before touching downloads this time, caught a
mistake worth recording rather than quietly fixing: I reconstructed the
84-URL list from what I'd scraped earlier in the session (before a context
compaction) instead of treating it as authoritative, and a few of the hash
suffixes repeated across fiscal years in a way that looked exactly like the
pattern-guessing this project explicitly rules out (NHS's hash suffixes
aren't predictable and have to be scraped fresh — that's the whole reason
scripts/dm01_urls.txt exists as an auditable artifact rather than trusting
memory). Re-fetched all 7 fiscal-year A&E index pages fresh and diffed every
single one of the 84 URLs against the reconstructed list before downloading
anything. Every URL matched byte-for-byte — so nothing was actually wrong,
but I wasn't in a position to know that until I checked, and downloading 83
files against an unverified list would have been the wrong call regardless
of how it turned out. Saved the confirmed list to scripts/ae_urls.txt.

Downloaded all 84 files via Claude in Chrome — direct CSVs this time, not
zips (confirmed earlier in the session that NHS's server triggers a real
download for these too, not an in-tab render). Batched by fiscal year (12
files per batch), verified file count and byte range after every batch
before moving to the next rather than firing all 84 and checking once at
the end. 84/84 landed, all pass as real CSV/text via `file`, sizes tightly
clustered 26.7-34.6KB with no outliers (unlike RTT's Feb/Mar22 quirk) —
2.7MB total, much smaller than DM01's 105MB, which tracks with A&E being a
much thinner file (16-22 columns vs DM01's 30, one row per provider per
month vs DM01's per-test grain).

Profiled Apr-2019, Jul-2020, Aug-2020, Mar-2022, Mar-2024, Dec-2024 and
Mar-2026 before writing DDL. Unlike DM01, this source is NOT schema-stable
across the full window — but the break is exactly where NHS's own page text
said it would be ("Format ... have changed due to the inclusion of booked
attendances"), so this was a confirm-the-documented-change exercise rather
than a blind discovery. 16 columns Apr-2019 through Jul-2020 (16 months), 22
columns Aug-2020 onward (68 months) — the attendance and over-4hr counts
each split from a single Type1/Type2/Other trio into two parallel trios,
walk-in vs booked. Checked several months well after the boundary (Mar-2022,
Mar-2024, Dec-2024, Mar-2026) to confirm it's one clean break, not a moving
target that changes again later.

NHS's own "TOTAL" pseudo-row is messier here than DM01's: absent entirely
from all 12 FY2019-20 files (not introduced until FY2020-21), and where
present, the label lands in either the Period or the Org Code column
depending on the month, with four different casings across files (TOTAL,
Total, 'Total ' with a trailing space, and one straight typo TOTAl). First
pass at checking for it used naive comma-splitting and produced a false
mismatch against Mar-2026's total (missed that some Org names or fields
needed proper CSV quote-handling) — switched to Python's csv module and the
mismatch disappeared, sum of the 199 real provider rows matched the TOTAL
row exactly. Same conclusion as DM01: safe to re-derive rather than trust
the row itself, and re-deriving means the fact table doesn't depend on the
row being present or consistently labelled, which it isn't.

Wrote and validated (DuckDB, loaded Apr-2019 + Aug-2020 + Mar-2026 together
specifically to cross the schema boundary in one test) sql/schema/
06_staging_ae.sql and 07_fact_ae_provider_month.sql. Single fact table this
time, grain (provider, month) — no test/specialty/commissioner dimension to
cut by, so no separate detail-vs-rollup pair like DM01 needed. Loaded 653
rows across the 3 sample months, zero sanity-check violations (over-4hr
count never exceeds total attendances). Confirmed the booked_* columns are
genuinely NULL (not zero) for all 236 Apr-2019 rows and populated for both
later months, and that total_attendances still sums correctly across the
NULL boundary via coalesce. Spot check: Liverpool University Hospitals
(REM) Mar-2026 — 27,225 attendances, 70.04% seen within 4 hours, 1,124
patients waiting 12+ hours from decision-to-admit; Apr-2019 — 8,222
attendances, 70.88% within 4 hours. Both in a believable range for a large
acute trust, not obviously broken.

One naming note for later phases: this collection's "Parent Org" column is
the NHS England region (e.g. "NHS ENGLAND NORTH WEST"), not the ICB — a
different meaning from RTT/DM01's Provider Parent. Kept as-is for
traceability but the ICB filter for Cheshire & Merseyside still has to come
from dim_provider, not from this column.

### Next action
KH03 (bed availability and occupancy) next, then GPAD, workforce, IMD —
same loop. A&E and DM01 both feed the Phase 2 pressure index, so that
dependency is now clear; KH03 adds the discharge/flow side.

## 2026-08-07 (yet later still, same session)

KH03 (bed availability and occupancy) pulled and warehoused — quarterly,
not monthly, so a smaller file count but a genuinely different acquisition
shape from RTT/DM01/A&E that was worth checking properly rather than
assuming the same "one file per period" pattern would hold.

NHS actually publishes two different things for this collection: individual
quarterly Excel releases going back to 2000-01 (matching the RTT/DM01/A&E
pattern), and three consolidated "flat file" CSVs that claim to cover the
full history in one download each. Went with the consolidated CSVs first
since downloading 3 files beats downloading 28 — but checked the actual
min/max dates in them rather than trusting the page's "onwards" framing,
and they stop at 2024-06-30 (Q1 2024-25), seven quarters short of this
project's FY2025-26 window end. Not a bug on my end, just a stale flat
file sitting next to a current set of individual releases — pulled the 7
missing quarterly Excel files (Q2 2024-25 through Q4 2025-26) to close the
gap.

The two sources don't share a shape, which RTT/DM01/A&E never made me deal
with: the consolidated CSVs are long format (one row per provider-sector-
quarter), the quarterly Excel files are wide format (Available and Occupied
for all four sectors as parallel column blocks on one row per provider),
with an 11-row metadata preamble before the real header at row 15 and data
from row 18 (row 16 is an England national total row, row 17 a blank
spacer — confirmed by inspection, not assumed). Wrote scripts/load_kh03.py
to reshape both into the same long form before loading, since forcing the
CSVs into a wide shape would mean hardcoding a sector list into the load
path rather than the fact table.

Caught one real bug while writing the loader, not after: the consolidated
CSVs comma-format bed counts once they hit 4 digits ('2,079' instead of
'2079') but not smaller ones, so a naive float() blew up on the first
large trust it hit. Affected 27 rows in the Available file and 13 in
Occupied, out of ~56k each — small in proportion but enough to silently
drop real data if I hadn't run the loader against the full window (only
caught it because I insisted on validating the whole FY19-20-FY25-26 range
rather than just the 2-quarter sample I'd started with).

Scope decision, flagged rather than silently narrowed: this only covers
overnight beds by sector (General & Acute / Maternity / Mental Illness /
Learning Disability), not day-only beds and not the specialty-level
breakdown NHS also publishes (a 932k-row national file). General & Acute
overnight occupancy is the headline bed-pressure metric and the one that
actually competes with the elective waiting list for capacity; day-only
beds and the specialty split would sharpen things further but roughly
double the ETL surface for a secondary signal. Noted as a Phase 2+
enhancement, not pretended away.

Validated the full loader (not just a sample) against DuckDB: 21,364
staged rows across all 28 expected quarters (Jun-2019 through Mar-2026,
zero gaps), 5,341 fact rows, zero sanity violations (occupied never
exceeds available beyond a 2% rounding tolerance). Spot-checked REM
(Liverpool University Hospitals) across the full series rather than one
quarter, and the numbers tell a real, externally-checkable story rather
than just "not obviously broken": available G&A beds roughly double
between Jun-2019 (826) and Dec-2019 (1,602) — which lines up with the
real October 2019 merger that formed the trust (Royal Liverpool + Aintree),
not a data glitch. Occupancy craters to 61.5% in Jun-2020 and stays
depressed through 2020-21, which matches the KH03 page's own warning about
lower occupancy during COVID due to infection-control cohorting, then
climbs back to the low-to-mid 90s by 2022-23 as pressure resumed — the
shape a domain-literate reader would expect, not a coincidence I'm
claiming without being able to explain it.

### Next action
GPAD (GP appointments data) next, then workforce, then IMD last. Four
core NHS activity/capacity sources now warehoused (RTT, DM01, A&E, KH03);
GPAD adds the primary-care demand side, which the elective pressure index
doesn't strictly need but the "why is the system under pressure" narrative
in the final report will.

## 2026-08-07 (yet again, same session)

GPAD (Appointments in General Practice). Scoped this one down deliberately
before touching a single URL, not after. GPAD's standard per-month
downloadable files are wildly out of proportion to everything else in this
warehouse — the daily-counts zip alone runs 41-55MB/month, plus another
~20MB/month for the practice-level crosstab, against A&E's ~32KB/month for
the same span. Checked the much smaller "Summary" xlsx (~350-480KB/month)
first via a probe download of March 2026 and confirmed it already carries
Table 3a (appointments by status, National/Region/ICB/Sub-ICB tier) and
Table 4 (appointments + patient list size, same tiers) — enough to build an
appointments-per-registered-patient demand metric without touching the
daily/practice-level files at all.

Given GPAD's role here is to support the "why is the system under
pressure" narrative rather than feed the elective pressure index directly,
took one further scope cut: loaded one March snapshot per fiscal year (7
files) instead of all 84 monthly releases. Flagging this explicitly rather
than quietly under-delivering — monthly primary-care granularity is a
genuine Phase 2+ candidate if the analysis later needs it, not a corner
being cut without saying so.

URLs are hash-pathed per month same as everything else NHS publishes
(`files.digital.nhs.uk/4B/246A37/...`) and NOT guessable, so scraped each
of the 7 target month pages individually rather than reconstructing from
pattern — logged to scripts/gpad_urls.txt before downloading anything, same
discipline as ae_urls.txt/dm01_urls.txt. Direct curl to files.digital.nhs.uk
timed out from the sandbox (consistent with the network note from the start
of this log), so downloaded via Claude in Chrome navigate-per-URL, same
pattern that worked for A&E and KH03's direct-file downloads.

Real discontinuity found and handled, not glossed over: NHS Cheshire and
Merseyside ICB (code QYG) was only formed 1 Jul 2022, from the "Cheshire
and Merseyside STP" that existed before it. Checked the actual Table 3a/4
rows for the pre-ICB years rather than assuming the geography just wasn't
there — it is, under a different type label and (in the March 2020 file
specifically) a different area code too:
  - March 2020: Type='STP', NHS Area Code='E54000008' (not yet assigned the
    QYG letter-code), ONS Code='E54000008'. A near-identical duplicate row
    also exists under Type='Regional Local Office', Q75, E39000026 — same
    figures, different NHS org-hierarchy lens on the same geography.
  - March 2021 / March 2022: Type='STP', NHS Area Code='QYG', ONS
    Code='E54000008' — the QYG code is already in use here, a year before
    the STP legally became an ICB.
  - March 2023 onwards: Type='ICB', NHS Area Code='QYG', ONS
    Code='E54000008'.
The ONS code is the one identifier that's genuinely stable across all 7
years — nhs_area_code and the type label both drift. Built the staging
table and loader around ons_code as the join key for exactly this reason,
and filtered to National/Region/STP-or-ICB tier by ons_code prefix (ENG /
E40xxxxxx / E54xxxxxx) rather than by the type-label text, since checking
the 2020 file confirmed 'Regional Local Office' rows (E39xxxxxx) sit at the
same level as 'STP' rows and would double-count Cheshire and Merseyside's
appointments if the filter went on label text instead of code prefix.
Deliberately did not load CCG or Sub-ICB-Location rows (both E38xxxxxx) —
pre-2022 CCGs don't map cleanly onto today's Sub ICB Locations and that
granularity isn't needed at the GPAD layer when provider-level detail
already exists via DM01/A&E/KH03. Another explicit Phase 2+ deferral, not
a silent one.

Wrote scripts/load_gpad.py to parse both tables out of each year's xlsx
(row/column layout confirmed identical across all 7 files by inspection —
header at row 13, data from row 14 for Table 3a / row 12 for Table 4,
terminated by the first blank Type cell before the footnotes/copyright
block) and sql/schema/10_staging_gpad.sql / 11_fact_gpad_geography_year.sql.
The fact table full-outer-joins Table 3a and Table 4 on (ons_code,
fiscal_year) and flags (rather than silently resolves) any case where the
two tables disagree on total appointments for the same geography-month.

Validated against DuckDB: 700 staged rows (350 per table, 100 rows/year x
7 years — 1 National + 7 Region + 42 STP-or-ICB entities, x2 tables), 350
fact rows, zero (ons_code, fiscal_year) duplicates, zero nulls on required
fields, and zero appointments_total mismatches between Table 3a and Table
4 across all 350 joined rows — a genuine agreement, not a coincidence,
since the two tables are independently populated within each release.
National appointment totals track the "Key Facts" figures each publication
page states in its own text (e.g. 31.4m stated vs 31,343,735 loaded for
March 2025) even though the two aren't calculated identically. Cheshire
and Merseyside's own trend is plausible throughout: 1.02m appointments
(FY19-20) jumping to 1.30m by FY20-21 — a real effect, not an error, since
remote/telephone consultations made appointments easier to book quickly
even as face-to-face access was constrained during the pandemic — then
1.33m/1.36m/1.27m/1.34m/1.45m through FY21-22-FY25-26, patient list size
growing steadily (2.61m to 2.81m), attendance rate stable at 88-90%, DNA
rate stable at 4.7-5.8%.

### Next action
Workforce statistics next, then IMD last, per the established ordering.

## 2026-08-07 (once more, same session)

NHS Workforce Statistics. Same annual-snapshot scope as GPAD (one March
file per fiscal year) and for the same reason — staffing is a contextual
signal for the capacity-pressure narrative, not an input the elective
pressure index needs at monthly resolution. Unlike GPAD, though, this
source is genuinely trust-level (real ODS org codes, e.g. REM, RBL — not
ICB-level), so it was possible to filter straight down to the 13 Cheshire
and Merseyside trust codes already sitting in
sql/reference/cheshire_merseyside_providers.csv rather than staging every
NHS trust in England.

The March 2026 file ("NHS HCHS Workforce Statistics, Trusts and core
organisations - data tables") turned out to be a different resource
entirely from every prior year's ("NHS Workforce Statistics, March 20XX
England and Organisation") — different filename convention, different
sheet name ('2' vs '3. NHSE, Org & SG - FTE'), different file size (7MB vs
~2MB). The March 2025 page's own text had flagged this coming ("We intend
for this format to replace the current suite of data files..."), so this
wasn't a surprise once I re-read the page copy, but it meant the loader
couldn't assume one workbook shape for all 7 years.

Went in expecting two column layouts (pre/post the 2022 ICS reorg) and
found four. Discovered the extra two by writing the loader defensively and
letting it fail loudly rather than silently mis-map columns:
  - March 2020 / March 2021: no ICS columns, no header text at all on the
    org name/code columns, blank spacer columns between staff-group
    subtotals.
  - March 2022: still no ICS columns and still no header text on org name/
    code, but the spacer columns are gone — a hybrid of the layout either
    side of it. Found this one because the first version of the loader
    (which branched on a hardcoded "pre/post 2022" boundary) raised
    "could not locate header row" on this exact file, which is a much
    better failure mode than silently reading the wrong column.
  - March 2023 - March 2025: ICS code/name columns added, full header
    text, no spacers.
  - March 2026: same as 2023-25 plus two extra leading columns (Data
    month, Data type).
Rewrote scripts/load_workforce.py around a single anchor-and-search column
resolver instead of hardcoding four index maps — it locates 'Nurses &
health visitors' (confirmed identical, unambiguous, present in all four
variants, including the two "unlabelled" years where only the org name/
code columns lack header text) and searches backward from there for every
other needed field, including Organisation code/name as fixed -1/-2
offsets from wherever 'Total' resolves. This survived all four variants on
first retry with zero hardcoded per-era branching left in the final
version — a more defensible design than the pre/post-2022 branch it
replaced, since a future NHS column reshuffle is more likely to break a
hardcoded index than a text-anchored search.

Scope, flagged same as elsewhere: staged Total FTE, Professionally
Qualified Clinical Staff, HCHS Doctors (all grades), Consultants, Nurses &
Health Visitors, and Scientific/Therapeutic & Technical staff (the group
that covers radiographers — the staff side of DM01 diagnostic capacity).
Left the finer sub-grade breakdown (registrars, foundation years, support-
staff split, infrastructure split) unloaded — available in the same files
for a later phase, not discarded.

Validated against DuckDB: 91 staged rows (13 trusts x 7 years, no gaps),
91 fact rows, zero nulls on required fields, zero duplicate (provider,
fiscal_year) keys, and total_fte never falls below the sum of its own
consultant/nurses/scitech components across all 91 rows. REM's FTE trend
is smooth throughout (11,481 to 14,143 across the 7 years, +23%,
consultants 639 to 795, +24%) with no discontinuities. RBN is the one
trust with a real jump rather than a smooth trend — 6,293 FTE in FY22-23
to 9,668 in FY23-24, +54% — and that's not a data fault: Southport and
Ormskirk NHS Trust merged into St Helens and Knowsley Teaching Hospitals
on 1 April 2023 to form Mersey and West Lancashire Teaching Hospitals,
which is exactly the FY boundary where the jump and the provider_org_name
change both land. Checked the org name in the data changes on the same
row the FTE jumps, rather than treating them as two separate facts.

### Next action
IMD 2019 (deprivation) last, per the established ordering — this closes
out the core data-acquisition phase (RTT, DM01, A&E, KH03, GPAD, Workforce,
then IMD). After IMD: Python analytics layer, Excel Solver/VBA model,
Tableau story, AI decision-support layer, executive report, then the
generalised Healthcare Process & Performance Optimisation Framework
extracted from this build — all still pending, per the original charter.

## 2026-08-07 (final entry, same session)

IMD 2019 (deprivation) — last of the seven core sources. Different shape
from everything else warehoused so far: a single point-in-time publication
(26 Sep 2019), not a monthly/quarterly time series, so it landed as a
static reference table (dim_imd2019_local_authority) rather than a
staging+fact pair with a fiscal_year grain.

Source is gov.uk's File 11 (upper-tier local authority summaries) rather
than File 1, the LSOA-level file the publication's own guidance calls
"usually sufficient for most users" — LSOA (32,844 areas nationally) is
far finer than anything else in this warehouse joins against, since
nothing else here carries an LSOA key. Upper-tier local authority is the
right grain: interpretable standalone, small (151 nationally, 9 of them
Cheshire and Merseyside), and it's the exact geography the original
charter's rationale for choosing this ICB was pointing at.

These URLs are permanent gov.uk asset links (assets.publishing.service.gov.uk),
not per-period hash paths like every NHS Digital source this session — a
genuinely different acquisition shape (one-time static download, no
per-month scraping loop needed), and confirmed as such by reading the
publication page once rather than assuming.

Scope: loaded the IMD sheet (overall Index of Multiple Deprivation) and
the Health sheet (Health Deprivation and Disability domain) out of the
11 sheets in File 11. The other domains (Income, Employment, Education,
Crime, Barriers to Housing and Services, Living Environment, IDACI,
IDAOPI) are sitting in the same downloaded file, unloaded — a legitimate
Phase 2+ enhancement for a fuller socioeconomic narrative, not needed for
this project's deprivation-as-a-lens-on-healthcare-pressure use case.
Deliberately did NOT build a provider-to-local-authority mapping here —
trust catchments cross LA boundaries, so which LA's score to attach to
which provider is an analytical modelling choice for the analytics layer
to make deliberately, not something to bake into the warehouse silently.

Validated against DuckDB: 9/9 target local authorities loaded, zero nulls,
zero duplicate keys. The data itself corroborates the charter's own
rationale for this ICB rather than just failing to contradict it: Knowsley
and Liverpool sit at national ranks 3 and 4 (out of 151, rank 1 = most
deprived) on both overall IMD and the Health domain specifically, while
Cheshire East and Cheshire West and Chester sit at ranks 131 and 112 (the
least-deprived end) — a genuinely stark within-ICB contrast, not a
marginal one talked up to justify a decision already made.

### Data acquisition phase complete
Seven sources now warehoused end to end: RTT (waiting times), DM01
(diagnostics), A&E (emergency attendances), KH03 (bed occupancy), GPAD
(primary care demand), NHS Workforce Statistics, IMD 2019 (deprivation).
Every source has staging DDL, fact/dimension DDL, and — where the source
needed procedural reconciliation beyond plain SQL (KH03's two source
shapes, GPAD's geography discontinuity, Workforce's four column layouts)
— a dedicated, documented Python loader, all validated against DuckDB with
row counts, null checks, duplicate-key checks, and at least one real-
world-corroborated sanity check per source (Liverpool's 2019 trust merger
in KH03 and now in Workforce's RBN entry, COVID-era occupancy dips, the
Cheshire/Merseyside STP-to-ICB code continuity in GPAD, IMD's own
deprivation gradient). Nothing pushed to GitHub yet, per Vedant's explicit
instruction to hold that until the entire project is done.

### Next action
Python analytics layer next: forecasting, clustering, the elective
pressure index itself, Monte Carlo simulation, sensitivity analysis,
intervention ranking, inequality-of-access analysis (this is where
dim_imd2019_local_authority actually gets used). This is a substantially
larger and more architecturally significant body of work than any single
source acquisition so far — it needs its own design pass (how the pressure
index is actually defined and weighted, what the provider-to-LA mapping
for the inequality cut will be, what the forecasting approach is) before
writing code, not a start-typing-immediately approach.

## 2026-08-08

Checked in with Vedant on the two design questions that actually needed a
decision rather than analyst judgment: what the elective pressure index
should primarily capture, and whether workforce/IMD feed the formula or
stay contextual. Confirmed: RTT-centric core with DM01/A&E/beds as bounded
modifiers, and workforce/IMD as contextual overlays (cross-referenced
against the index as findings, not blended into it). Both match what the
charter's own framing implied, so this mostly locks in the plan rather
than changing it.

Before any analytics could run, realised there was no actual persisted
warehouse — every source's validation up to this point (including RTT/
DM01/A&E, built in an earlier session) used in-memory DuckDB connections
scoped to whatever was being checked at the time. Nothing had been loaded
to disk across all 7 sources at once. Built scripts/build_warehouse.py to
fix that.

RTT and DM01 arrive as national zips (one per month, 84 each); A&E as
national CSVs (84). Rather than warehouse all of England for a project
scoped to one ICB, filtered every insert down to the 25 provider codes in
sql/reference/cheshire_merseyside_providers.csv at SQL read time (DuckDB's
read_csv_auto with a WHERE pushdown), not by loading everything and
filtering after.

Two more schema-drift discoveries, on top of everything already logged
this project:
  - RTT's band structure genuinely changed mid-window: April 2019's
    extract has 69 columns with a single "Gt 52 Weeks" catch-all for
    anything past a year, while March 2026's has 121 columns with
    fine-grained per-week bands out to "Gt 104 Weeks". The existing
    01_staging.sql header comment ("121 columns, confirmed against Mar-
    2026 and Mar-2022") turned out not to hold for the full 84-month
    window — it was accurate for the two months actually checked, just not
    representative. Handled with a per-file dynamic column resolver
    (parse each file's real header, map every band it has, zero-fill any
    band it doesn't) rather than a hardcoded 121-column assumption — zero-
    fill rather than NULL-fill specifically, because the fact table's
    over_18wk/over_52wk sums are plain `+` arithmetic and a single NULL in
    that chain would silently null the whole row.
  - A&E's header text turned out to have THREE variants across the
    window, not the two (16-col/22-col, booked-appointments-added-Aug-
    2020) already documented from the earlier validation pass. FY2019-20's
    files prefix every attendance/over-4hr column with "Number of " and
    use inconsistent capitalisation and "Other A&E Department" vs "Other
    Department" wording. The literal-string column mapping that worked
    fine on the two months spot-checked earlier broke immediately on the
    full 84-file run. Rewrote as a case-insensitive regex resolver against
    normalised header text instead of a growing pile of hardcoded exact
    strings — the actual lesson here, stated plainly: two-month spot
    checks catch real bugs but don't guarantee full-window coverage, and
    the fix that generalises (pattern matching) is worth the extra design
    time over a fix that only patches the specific case just found.

Also hit a real environment constraint worth recording for future
sessions: backgrounded/nohup'd long-running processes in this sandbox do
NOT reliably survive across tool-call boundaries — a first attempt to run
the whole build as one nohup'd background job got partway through (47 of
84 RTT files) before silently dying between polls, with no error in the
log (stdout buffering meant the buffer was lost when the process was
killed, not flushed). Rebuilt the loader to be resumable and time-boxed
instead: each invocation checks which source_file values are already in
the target staging table, processes only what's missing, and stops itself
within a ~35s budget rather than trying to survive across an unreliable
background window. Called repeatedly (2 calls for RTT, 1 each for DM01/
A&E) until each source reported 0 files remaining. Slower wall-clock than
a single long-running job would have been if it had worked, but
deterministic and resumable, which matters more here.

One more environment quirk: writing directly to nhs_warehouse.db on the
synced project mount failed with "Operation not permitted" during
DuckDB's WAL checkpoint (the mount doesn't support the file remove-then-
recreate pattern DuckDB's checkpointing needs). Built the database in
/tmp instead and copied the finished file across as the last step. A
stale .wal file left over from the first (failed) attempt at the project-
mount path then blocked even opening the freshly-copied .db (DuckDB tried
to replay it and hit "table already exists") — `rm` on that stale file
was ALSO blocked by the mount's permissions, but `mv` (renaming it out of
the way) worked where deletion didn't. Filed away as a real, reproducible
quirk of this specific mount, not a one-off fluke.

Validated the finished warehouse: 25 providers loaded across RTT (773,991
staging rows / 15,519 fact rows) and DM01 (807,088 / 25,080), 12-13
providers in A&E (1,006 rows — not every C&M provider runs an A&E
department, e.g. Liverpool Heart & Chest and Clatterbridge Cancer Centre
correctly have zero A&E rows), all at 84/84 months for the core NHS
trusts. Zero negative waiting lists, zero A&E over-4hr-exceeds-total rows,
zero out-of-range breach shares. REM's RTT waiting list is the strongest
corroboration yet in this project: 37,060 (Apr-2019, pre-COVID) -> 84,720
(Apr-2020, COVID onset) -> peaking at 174,088 (Sep-2022) -> declining to
133,170 (Sep-2025) — this is the well-documented national NHS elective
backlog trajectory (pandemic surge, 2022 peak, gradual post-2022 recovery
plan effect) showing up correctly in one trust's own numbers, not
something asserted from memory. A handful of independent-sector providers
(R6X7C, Y9S1N, Z5J5V, V4U1Y) only appear in a subset of the 84 periods —
checked and this matches their real opening dates as newer Community
Diagnostic Centres (a 2021+ NHS initiative), not a load gap.

nhs_warehouse.db now sits in the project root, ~150MB, all 7 sources
joinable on provider_org_code (RTT/DM01/A&E/KH03/Workforce) or geography
code (GPAD/IMD).

### Next action
Provider-to-local-authority mapping reference (small, needed before the
inequality-of-access analysis can join fact tables to
dim_imd2019_local_authority), then the elective pressure index itself.

## 2026-08-08 (later same session)

Built sql/reference/provider_local_authority.csv and dim_provider_local_
authority — a deliberate single-site simplification mapping each of the 13
core trusts to one host LA, needed to join RTT/DM01/A&E/KH03 (keyed on
provider_org_code) through to dim_imd2019_local_authority (keyed on
la_code). Flagged per-row via catchment_caveat wherever the single-LA
assignment materially understates the real catchment — every regional
specialist centre (RBQ Liverpool Heart & Chest, RBS Alder Hey, REN
Clatterbridge Cancer, REP Liverpool Women's, RET Walton neuro) and the
mental health trust (RW4 Mersey Care) draws from well beyond its assigned
LA, and RBN/RWW's multi-site mergers are noted too. Not claiming this is a
true patient-flow catchment model — it's a single anchor point per trust,
documented as such.

Hit two real bugs loading this, worth recording since both were subtle:
  - `read_csv_auto` failed to parse the file at all (sniffed the whole
    header as one column), and adding an explicit `delim=','` made it
    worse. Root cause turned out to be in the CSV itself, not DuckDB: row
    13 (RW4/Mersey Care) had `primary_site_name` = "HQ (V7, Liverpool)" —
    a genuine comma inside an unquoted field, which is invalid CSV. That
    shifted every column on that one row (la_code read as " Liverpool)",
    which then failed a later FK check against dim_imd2019_local_authority
    with exactly that garbage value — the FK constraint doing its job and
    catching a real data problem, not a false alarm). Fixed by quoting the
    field properly. Worth noting DuckDB's sniffer error message pointed
    entirely the wrong direction (delimiter detection) for what was
    actually a malformed-row problem — the fix came from reading the raw
    file byte-for-byte, not from trusting the error text.
  - Same synced-mount WAL-checkpoint permission error as the main
    warehouse build (Operation not permitted removing .wal during
    checkpoint) recurred on this small follow-up table, because the CREATE
    TABLE/INSERT ran directly against the project-mount .db file instead
    of routing through /tmp first. Same fix applied: build in /tmp, copy
    over. Also found a second stale .wal sitting on the project mount from
    the main build's own copy-back step (small, 683 bytes, left behind
    after the file copy) — same `mv`-not-`rm` workaround. This mount's
    WAL-file restriction is now a fully established pattern for this
    project: never write to nhs_warehouse.db in place on the synced mount,
    always /tmp-then-copy.

Loaded and validated: 13/13 rows, join test against dim_imd2019_local_
authority sorted by deprivation rank confirms the mapping lines up with
the ICB's known deprivation gradient — Knowsley (RBN) and Liverpool (REM,
RBQ, RBS, REP, RET, RW4) cluster at national ranks 3-4 (most deprived),
Wirral (RBL, REN) at rank 56, Warrington (RWW) at 109, Cheshire West and
Chester (RJR) at 112, Cheshire East (RBT, RJN) at 131 (least deprived) —
consistent with every other corroboration of this ICB's within-region
contrast logged earlier in this project.

### Next action
Elective pressure index (task #17) — RTT-centric core (waiting-list growth
vs. baseline, 18-week/52-week breach shares) with bounded modifiers from
DM01 (6-week diagnostic breach share), A&E (% seen within 4hr, inverted),
and KH03 bed occupancy (forward-filled quarterly-to-monthly, since KH03 is
the only quarterly-cadence source of the four). Workforce and IMD stay
contextual overlays per Vedant's confirmed decision, joined in via
dim_provider_local_authority for the inequality-of-access cut once the
index itself exists.

## 2026-08-08 (continuation session, new chat)

Picked this project back up in a new session — the prior one hit its usage
limit mid-way through an AskUserQuestion call about the pressure index
design (interrupted before the question text was ever seen in this
session). Rather than guess what it was about to ask, put fresh design
questions to Vedant directly, since the two things STATUS.md's prior "Next
action" entry hadn't already locked in were the index's grain and how the
four RTT/DM01/A&E/KH03 signals should combine. Confirmed:
  - Grain: provider-specialty-month (the native RTT/DM01 grain), not the
    coarser provider-month. Real consequence, stated plainly rather than
    glossed over: DM01/A&E/KH03 only exist at provider-month, so those
    three columns are identical across every specialty within a given
    provider-month — only the three RTT-derived columns vary by specialty.
  - Weighting: statistically derived, not fixed analyst weights — and
    explicitly NOT stress-tested in this same pass. Vedant's own framing:
    derive the weights now, test them later via Monte Carlo (that's
    already the next phase on the charter's list, so this isn't adding new
    scope, just sequencing it correctly).

Built scripts/build_pressure_index.py and sql/schema/16_fact_elective_
pressure_index.sql. Scoped to the 12 trusts where dim_provider.
in_core_analysis is true — i.e. real RTT elective volume — same exclusion
of independent-sector providers and RW4 (Mersey Care, mental health) as
every other scoping decision already logged in this project.

Six signals, all oriented so higher = more pressure: rtt_growth (waiting
list vs. own Apr-Jun 2019 baseline), rtt_over18_share, rtt_over52_share,
dm01_breach (6-week diagnostic breach share), ae_pressure (1 - % seen
within 4hr), kh03_occupancy (G&A bed occupancy, mapped from KH03's
calendar quarter onto its 3 constituent months). Standardized all six
across the full panel and ran PCA — PC1's loadings are the "statistically
derived" weights Vedant asked for.

Two real findings from the fit, reported honestly rather than smoothed
over or hidden:
  - PC1 only explains ~32% of the variance across the six standardized
    signals. That means this composite is one useful lens on pressure, not
    a strongly unified single factor — worth carrying forward into the
    Monte Carlo/sensitivity phase as a real caveat, not just a formality
    to test.
  - dm01_breach loaded NEGATIVE on PC1 (weight -0.096, corr with PC1
    -0.132) — every other signal loads positive (0.27 to 0.52) and moves
    together, but DM01's 6-week diagnostic breach share weakly moves
    AGAINST that shared factor in this ICB across this window. Plausible
    real read: targeted diagnostic capacity investment (Community
    Diagnostic Centres, which this project's own GPAD/DM01 entries already
    noted opened across 2021+) may have held 6-week diagnostic performance
    up even as RTT/A&E/bed pressure rose elsewhere. Kept the sign as PCA
    actually found it rather than flipping it to match the other five —
    forcing that would defeat the point of asking for statistically
    derived weights in the first place.

REN (Clatterbridge Cancer Centre) has no A&E department, so its
ae_pressure is imputed as the other 11 core providers' mean for that month
— flagged per-row via ae_pressure_imputed (1,084 rows) rather than left
silently blended in.

Validated against DuckDB (built in /tmp per this project's established
WAL-checkpoint mount workaround, copied back to nhs_warehouse.db as the
final step — no stale-.wal issue this time, copy succeeded cleanly):
11,956 provider-specialty-month rows, zero rows where over52_share
exceeds over18_share beyond a rounding tolerance, pressure_index_0_100
populated for 11,913/11,956 rows (the 43-row gap is real: 23 rows with a
zero-sized waiting list making the share ratios undefined, 20 more missing
a DM01 match for that exact provider-month, both pre-existing small gaps
already documented earlier in this warehouse's validation, not something
this step introduced).

Spot check on REM, using pressure_index_0_100 averaged by year rather than
the raw waiting-list numbers this project has already corroborated
repeatedly: 22 (2019) -> 17 (2020) -> 54 (2021) -> 76 (2022) -> 73 (2023)
-> 66 (2024) -> 68 (2025). The 2020 dip despite the waiting list nearly
doubling that year is a real, explainable pattern rather than a bug: A&E
attendances and G&A bed occupancy both genuinely fell during COVID
lockdown and infection-control cohorting (already documented in this
project's own KH03 validation — "occupancy craters to 61.5% in Jun-2020"),
and those two signals carry the two largest PCA weights, so the composite
can legitimately fall even while the RTT backlog alone was building. The
index then rises sharply through 2021-2022 as A&E/bed pressure returned to
normal on top of the accumulated RTT backlog, matching the known national
post-lockdown pressure peak, and eases only partially afterward — level,
not a clean recovery, which also matches the real slow pace of NHS
elective recovery rather than an artificially tidy curve.

### Next action
Python analytics layer: forecasting, clustering, Monte Carlo simulation
(this is where the pressure index's PCA weights actually get
stress-tested, per Vedant's sequencing), sensitivity analysis, intervention
ranking, and the inequality-of-access analysis joining through
dim_provider_local_authority to dim_imd2019_local_authority. Needs its own
design pass on forecasting method before writing code, same discipline as
the pressure index got.

## 2026-08-08 (continuation session, later same day)

Checked in with Vedant on Monte Carlo scope: rather than a single, separate
"Monte Carlo simulation" deliverable, apply it wherever viable across the
analytics layer as each piece gets built. First application: the
weight-sensitivity stress-test already promised for the pressure index.

Built scripts/pressure_index_sensitivity.py — bootstrap-resamples the
11,913 complete-case rows 2,000 times, refits StandardScaler+PCA(1) on each
resample, and checks two things: (1) how much each feature's loading
actually wobbles, and (2) whether the resulting provider-level pressure
RANKING (the thing that actually matters for the report — which trusts are
under the most pressure) holds up even if the exact loadings move.

Results, both genuinely reassuring rather than just "test passed":
  - dm01_breach's negative loading (flagged as a real finding, not
    forced, in the last entry) is stable across 98.8% of the 2,000
    resamples — this is not sampling noise from one unlucky fit, it's a
    real, repeatable pattern in this ICB's data. Worth stating in the
    final report as an actual finding (diagnostic breach share moving
    against the other five pressure signals), not hedging it as
    uncertain.
  - Provider-level ranking is extremely stable under weight
    resampling: mean Spearman rank correlation 0.9985 against the
    baseline ranking across all 2,000 resamples (worst single resample
    still 0.986). So even though PC1 only explains ~32% of the six
    signals' variance (the honesty caveat from the last entry), which
    trust is under more or less pressure than which other trust is a
    robust conclusion — the low explained-variance caveat matters for
    how much weight to put on the exact composite SCORE, much less for
    ranking providers against each other, and that distinction is worth
    keeping straight in the final report rather than treating "32%
    explained variance" as a blanket reason to distrust the index.

Wrote ref_pressure_index_weight_sensitivity (per-feature loading
distribution, 90% CI, sign-stability flag) and
ref_pressure_index_rank_stability (the rank-correlation distribution) to
the warehouse, same /tmp-build-then-copy pattern as everything else.

### Next action
Forecasting. Vedant's steer: try multiple methods (seasonal-naive
baseline, linear trend, Holt-Winters, SARIMA/auto-ARIMA) and let a
time-based backtest decide which fits each series best, rather than
picking one method up front. Target: RTT waiting_list_size aggregated to
provider-month for the 12 core trusts (the trusted primitive), with
Monte Carlo (bootstrapped residual) prediction intervals rather than
closed-form confidence intervals, again per the "MC wherever viable"
steer. Specialty-level forecasting and a forecasted pressure index (by
re-running the index formula on forecasted inputs) are a natural
follow-on once the provider-level model is validated, not being ruled
out, just sequenced after.

## 2026-08-08 (continuation session, later still)

Forecasting. Built scripts/forecast_waiting_list.py: four candidate
methods (seasonal_naive, linear_trend, holt_winters, auto_arima via
pmdarima) backtested per provider on the last 12 of 84 months, winner
refit on the full series for an 18-month forward forecast, Monte Carlo
(2,000-iteration bootstrapped in-sample residuals) prediction intervals
rather than each model's own closed-form CI. Scoped to provider-month
(sum across specialties), not provider-specialty-month — 84 months is
already thin for a 12-month-seasonal model, splitting into ~25 specialty
series per provider would leave most too short to fit anything beyond a
naive baseline. Flagged as a scope decision, not a silent simplification;
specialty-level forecasting is a legitimate follow-on.

Real discovery while assembling the input series: the actual max period in
the warehouse is 2026-03 (March 2026), not September 2025 as an earlier,
mid-build validation spot-check in this log had cited — that citation was
accurate for the point the warehouse was at when it was written, and the
full FY2025-26 months (through March 2026) were evidently loaded by a
later step in the same original build. 84 months = 7 fiscal years x 12
(Apr-2019 through Mar-2026) checks out exactly against "7 fiscal years"
stated everywhere else in this log — not a new gap, just this entry
catching up the record.

Results, reported as they came out rather than tuned to look tidier:
  - Backtest MAPEs vary widely by provider, roughly 2-60% across the
    four methods. Several trusts (RBQ, REN, RJN in particular) have no
    method scoring better than ~10-17% even at their best — the 2020-2022
    COVID disruption sits inside the training window and genuinely
    confuses trend/seasonality for some series more than others. Treat
    those trusts' forecasts as directional, not precise, and said so
    plainly in the table's own header comment (sql/schema/18_fact_rtt_
    waitinglist_forecast.sql) so this doesn't need rediscovering later.
  - seasonal_naive (literally repeat last year's monthly pattern) won
    for 4 of 12 providers, including REM (12.06% MAPE, beating
    holt_winters' 15.15% and auto_arima's 16.40%; linear_trend was far
    worse at 45.13%, badly overshooting REM's actual trajectory). That a
    flat repeat-last-year forecast beats trend-fitting models on REM's
    holdout year is itself informative, not just a modelling footnote:
    it means REM's RTT waiting list has been oscillating around a
    plateau in its most recent year rather than following a clear
    monotonic trend, consistent with the "declining but staying
    elevated" pattern the pressure index already showed for REM
    (73/66/68/64 across 2023-2026, not a clean recovery curve).
  - holt_winters won for RBN, RBS, REP, RWW; auto_arima for REN, RET,
    RJR; linear_trend only for RJN (and even there at a mediocre 17.4%
    MAPE — every method struggled on RJN specifically, worth flagging
    rather than treating the "winner" label as a mark of a good fit).

Wrote fact_rtt_waitinglist_forecast_provider_month (1,224 rows: 12
providers x (84 historical + 18 forecast) months) and
ref_forecast_model_selection (48 rows: every method's backtest MAPE per
provider, not just the winner's, so the choice is auditable). Validated:
zero negative point forecasts, REM's forward path spot-checked and
consistent with its recent plateau rather than an implausible trend
extrapolation.

### Next action
Clustering (peer-group providers/specialties by pressure profile) and the
inequality-of-access cut via dim_provider_local_authority /
dim_imd2019_local_authority are the two pieces left before intervention
ranking. Intervention ranking itself likely belongs closer to the Excel
Solver capacity-optimizer phase (it needs a defined set of levers and a
cost/impact model, which is really that phase's job) rather than the
Python analytics layer — worth confirming that boundary with Vedant before
building it in the wrong place.

## 2026-08-08 (continuation session, later still #2)

Confirmed both open questions with Vedant: cluster provider-specialty
series (not just the 12 providers) on their pressure-index profile, and
move intervention ranking to the Excel Solver phase rather than building a
first pass here — it genuinely needs a cost/impact model and constraints
that don't exist yet, and building it now risked producing a ranking that
would just get thrown away once real levers/constraints are defined.

Built scripts/cluster_pressure_profiles.py: 172 provider-specialty series
(not every provider reports every treatment function, hence 172 rather
than 12 x 25), each collapsed to the mean of the same six pressure-index
input signals across however many months it has data for, then KMeans-
clustered on the standardized means. k=4 won on silhouette score across
k=2..8 (0.403, next best k=3 at 0.370) — statistically derived the same
way the pressure index's own weights were, not asserted.

Honest result, not smoothed into a tidier story: the split is heavily
imbalanced — 135 of 172 series land in one large cluster with no strongly
distinguishing feature (essentially "the ordinary middle"), 31 in a
genuinely distinct LOW-pressure cluster (all four broadcast/derived
signals well below average), and two tiny outlier clusters of 5 and 1.
The Monte Carlo stability check (1,000 bootstrap resamples, Adjusted Rand
Index vs. the baseline clustering) came back only moderately stable: mean
ARI 0.46, ranging 0.13 to 0.97 across resamples. Read together, the honest
takeaway is: most provider-specialty series don't segment into clean,
robust bands on these six signals — pressure looks fairly continuous
across the bulk of them. The parts of this result actually worth relying
on are the two extremes (the low-pressure cluster and the single-series
outlier), not the exact boundary carving up the large middle cluster.
Recorded this directly in sql/schema/19_ref_pressure_profile_clusters.sql
so nobody downstream treats "4 clusters" as a firm segmentation later.

REM spot check: 19 of its 21 specialties land in the ordinary middle
cluster, 2 (X01, C_170) in the genuinely low-pressure cluster, and its
C_330 specialty is the single-row outlier cluster on its own (over18/
over52/A&E all several SD above every other series) — worth a manual look
before the final report, since an n=1 cluster is either a real, striking
finding or a data artifact and this hasn't been checked either way yet.

### Next action
Inequality-of-access analysis: join the pressure index and forecast
outputs through dim_provider_local_authority to dim_imd2019_local
authority, and check whether pressure/waiting-time outcomes actually track
this ICB's already-established deprivation gradient (Knowsley/Liverpool at
national rank 3-4, most deprived; Cheshire East at rank 131, least) or run
against it. This is the last piece before wrapping up the Python analytics
layer and reporting back to Vedant on the phase as a whole.

## 2026-08-08 (continuation session, later still #3)

Inequality-of-access, the last piece of this phase. Built scripts/
inequality_of_access.py: joins the pressure index (mean per core provider)
and latest-year workforce staffing intensity through dim_provider_local_
authority to dim_imd2019_local_authority, correlates against deprivation
rank (Spearman, Monte Carlo bootstrap CI — same "wherever viable" MC
treatment as everything else this phase).

Caught and fixed a real bug in the first run, before trusting the output
rather than after: used dim_imd2019_local_authority's imd_avg_rank column
directly, which produced nonsense-looking rank values in the tens of
thousands. That column is the raw population-weighted average of LSOA-level
national ranks (out of 32,844 LSOAs) — NOT the LA's own comparable rank.
The right column, imd_rank_of_avg_rank (1-151, 1=most deprived), was
sitting right next to it the whole time and is exactly what this log's own
earlier entries have been citing all along (Knowsley=3, Liverpool=4,
Cheshire East=131). Caught it by cross-checking the first run's output
against those already-established numbers rather than trusting a
plausible-looking dataframe — the join ran without error, so nothing would
have flagged this automatically. Fixed by aliasing the correct columns in
the query and left an explicit column note in sql/schema/20_ref_
inequality_of_access.sql so this doesn't get rediscovered later.

Result, genuinely two-sided rather than picking the more interesting half:
across all 12 core providers, deprivation rank and mean pressure index
correlate POSITIVELY (rho=+0.49) — meaning LESS-deprived areas show
somewhat HIGHER pressure in this data, the opposite of the naive
"deprivation drives worse access" assumption — but not significantly
(p=0.108) and with a bootstrap CI that's wide even though it does stay on
the positive side [+0.03, +0.84]. The obvious next question - is this
real - gets answered by excluding the 5 regional specialist centres
(RBQ/RBS/REN/REP/RET), whose single-LA assignment is already documented as
understating their real ICB-wide catchment: the correlation drops to
rho=+0.31 (p=0.53), CI now spanning strongly negative to strongly positive.
Same pattern on consultants_per_1000_fte vs deprivation (rho=-0.59, p=0.044
for all 12; rho=-0.52, p=0.229, CI crossing zero once specialist centres
are excluded). Honest read: the apparent relationship in the raw 12-point
data is largely an artifact of Liverpool (this ICB's most-deprived LA)
happening to host most of the specialist tertiary centres — not a real
deprivation-pressure effect — and n=12 (or n=7 once corrected) is too
small to conclude much either way regardless. Recorded as the genuine
state of the evidence, not left as a vague "needs more data" placeholder.

Wrote ref_inequality_provider_deprivation (12 rows, full provider x
deprivation x workforce table) and ref_inequality_correlations (16 rows:
4 outcome/independent-variable pairs x 2 provider subsets).

### Python analytics layer: phase complete
Five pieces built and validated this continuation: the elective pressure
index itself (PCA-weighted, provider-specialty-month), its Monte Carlo
weight-sensitivity test (rankings robust, exact score less so), the RTT
waiting-list forecast (method-per-provider backtest + MC prediction
intervals), pressure-profile clustering (k=4, honestly reported as only
moderately stable), and the inequality-of-access cross-reference (a
genuine null-ish result once specialist centres are correctly excluded,
not a confirmed inequality story). Intervention ranking was deliberately
NOT built here — confirmed with Vedant it belongs in the Excel Solver
capacity-optimizer phase, which needs its own cost/impact model and
constraints first.

### Next action
Per the original charter's ordering: Excel Solver/VBA capacity-optimizer
model next, then the Tableau story, then the AI decision-support layer,
then the executive report, then the generalised Healthcare Process &
Performance Optimisation Framework extracted from this build. Excel Solver
phase needs its own design pass with Vedant (what levers, what
constraints, what objective function) before writing anything, same
discipline as every phase so far.

## 2026-08-07 (continuation session, new chat, design pass)

Excel Solver design pass. Put the three open questions (objective, levers,
constraints) to Vedant plus a scope/horizon question; he delegated the
first three and the scope call to analyst judgment, with one explicit
steer on constraints: "real life applicability (suppose this is a real NHS
project)". Decisions below, made against that steer rather than against
what's easiest to model.

Objective: minimize total RTT over-52-week breach count, summed across the
12 core trusts x specialties x the 18-month forecast horizon
(fact_rtt_waitinglist_forecast_provider_month's 2026-04 through 2027-09
window) — total waiting list size carried as a secondary reported metric,
not the optimization target itself. Deliberately NOT optimizing directly
on pressure_index_0_100: it's the right lens for the inequality-of-access
and clustering work already done, but its own validation already flagged
it as explaining only ~32% of the six signals' variance (ref_pressure_
index_pca_weights) — not a strongly unified number to hang a real
capacity-allocation decision on. 52+ week breaches is what NHS England's
own Elective Recovery Plan actually targets nationally, so it's both more
defensible to a non-technical reader and a closer match to how a real ICB
would frame this decision than an internally-derived composite.

Levers, three of the four candidates, one deliberately excluded rather
than silently dropped: extra in-house elective capacity (additional
sessions per provider-specialty, bounded by Workforce FTE and KH03 bed
headroom), independent-sector outsourcing (the ~12 non-core providers
already flagged separately in dim_provider), and diagnostic capacity
investment (DM01, mirroring the real Community Diagnostic Centre expansion
this project's own GPAD/DM01 entries already noted). Workforce
reallocation across trusts is OUT for this pass: real NHS consultant/
nursing moves involve recruitment and training lead times that don't fit
inside an 18-month operational-capacity horizon, so treating headcount as
a same-period decision variable would be the opposite of "real life
applicability" — a legitimate longer-horizon follow-on, not pretended
away.

Constraints, all four, but the equity one reshaped to match how ICBs
actually operate rather than an idealized version: (1) a fixed total
budget envelope split across the three levers, which will need a per-unit
cost assumption for each — sourcing real NHS reference costs / Elective
Recovery Fund rates where they exist and flagging clearly wherever an
assumption has to stand in for one, same disclosure standard as every
other estimate in this project; (2) workforce/bed capacity ceilings from
the Workforce and KH03 tables already warehoused, so no lever can push a
provider-specialty past what current staffing or beds could plausibly
support; (3) an independent-sector outsourcing cap bounded per provider
rather than unlimited external capacity; (4) a BOUNDED equity tolerance,
not a hard no-worsening floor — real system-level plans do redistribute
capacity toward higher-pressure trusts with some cost to lower-pressure
ones, capped rather than zero-tolerance, which is a more honest model of
the actual efficiency/equity tradeoff ICBs navigate than an artificial
floor that forbids it outright. Ties back to the inequality-of-access
phase's own deprivation-gradient findings rather than treating equity as a
fresh consideration.

Scope: all 12 core trusts, full specialty mix, the same 18-month forecast
horizon the forecasting phase already built — continues that phase's own
scope rather than narrowing it, and an ICB-level plan is exactly the level
a real NHS elective recovery plan would be evaluated at.

### Blocked
Sandbox shell is down as of this session (VM-level disk-full error on
useradd, confirmed identical across three retries, not something fixable
by retrying differently) — can't run Python/DuckDB/Excel-build work until
it recovers. Design decisions above don't depend on it and are locked in;
actual Solver build (data extraction, cost assumptions, VBA/Solver
constraints, validation) is next once the sandbox is back.

### Next action
Build the capacity-optimizer: pull the 18-month forecast + workforce/KH03
capacity ceilings + independent-sector provider list into the model
inputs, source or transparently estimate per-unit costs for the three
levers, build the Excel workbook with Solver-ready decision variables and
constraints per the design above, validate the optimized allocation
against the constraints (nothing exceeds capacity ceilings or the budget
envelope, equity tolerance respected) before treating any output as a real
recommendation.

## 2026-08-08 (continuation session, new chat, still blocked)

Picked this back up — sandbox shell still down, confirmed with two fresh
attempts (identical `useradd: /etc/passwd... No space left on device`
error both times). This is a VM-level constraint, not something retrying
differently fixes, so did non-shell prep work instead of waiting idle:
saved a condensed project summary to Claude's persistent memory (overview,
current-phase status, working conventions, file reference — four short
files instead of re-reading this whole log every new session) and started
sourcing the real per-unit costs the Solver's budget constraint needs, per
this project's standing rule not to guess figures that can be sourced.

Web research only (no file downloads, no code) — findings, flagged
honestly by how solid each one is rather than presented as more certain
than it is:
  - Elective Recovery Fund payment mechanism (HFMA, describing the
    2022/23 scheme's rules): NHS in-house activity delivered above the
    104%-of-2019/20 baseline is reimbursed at 75% of national tariff
    price; independent-sector activity is reimbursed at 100% of tariff
    once both a system-wide and an IS-specific activity threshold are
    met. If this asymmetry still holds under the 2025/26 NHS Payment
    Scheme, it's a real, non-obvious point for the Solver's cost model —
    it would mean outsourcing costs the commissioner MORE per case than
    marginal in-house activity, not less, which cuts against the naive
    assumption that outsourcing is the "cheap lever." Needs re-
    verification against the actual 2025/26 Payment Scheme Annex D
    (england.nhs.uk) before being coded into the model — this source is
    3 years old and describes the scheme as it stood then, not confirmed
    current.
  - Community Diagnostic Centre capital investment: no single fixed
    per-centre figure exists publicly — real examples range roughly
    £5.2m (Walton) to £18.4m (Coventry & Rugby) depending on scale, so
    any per-unit diagnostic-capacity-investment cost for the Solver will
    have to be an explicitly-flagged assumption (e.g. cost per additional
    weekly diagnostic slot, derived from one of these real examples), not
    a single sourced NHS figure.
  - HRG-level / average elective spell costs (National Cost Collection
    2023/24): the actual figures live in NHS England's Power BI
    dashboards and downloadable spreadsheets, not in any web page text a
    search/fetch can extract — this needs the sandbox back (download +
    parse) rather than more web research.

None of this has been written into any SQL/schema file or script yet —
it's source material for the cost assumptions, still needs the ERF
asymmetry re-checked against the current-year Payment Scheme and the
actual National Cost Collection spreadsheet pulled once the shell
recovers, per this project's standing discipline of not coding an
unverified figure into the model.

### Next action
Same as above, unchanged: still blocked on the sandbox for the actual
Solver build. Once the shell recovers — re-verify the ERF 75%/100%
reimbursement split against 2025/26 Payment Scheme Annex D, pull the
National Cost Collection spreadsheet for elective HRG average costs, then
proceed with the capacity-optimizer build as already designed.

## 2026-08-08 (continuation session, sandbox recovered)

Sandbox came back mid-session (confirmed with a direct retry, then cross-
checked with an independently-isolated remote agent hitting the identical
disk-full error beforehand — that ruled out it being a session-specific
fault, so worth recording: it was host-level, not fixable from inside a
session, and cleared on its own). Picked the Solver build straight back up.

Real gap found before writing any Excel, not after: the RTT forecast
(fact_rtt_waitinglist_forecast_provider_month) is provider-month
waiting_list_size only, per its own documented scope decision — but the
Solver's objective (minimize over-52-week breaches) needs a breach-COUNT
forecast, which doesn't exist. Bridged it with a proxy, not a guess:
provider-level trailing-6-month over_52_share (Oct-2025 to Mar-2026,
actual data) x forecasted waiting_list_size = baseline over-52wk breach
forecast. Flagged in the workbook's own Read Me tab as a proxy, not
presented as if the forecast itself covered breach bands.

Grain decision, made and documented rather than deferred: decision
variables are at PROVIDER level (12 x 3 levers = 36), not provider-
specialty as the original design pass's wording implied. Reason is data,
not just Excel's Solver limit (though that's real too — a ~700-variable
specialty-level model would exceed the free Solver's practical ~200-
variable ceiling): Workforce and KH03, two of the three lever-cap sources,
only exist at provider grain in this warehouse. No specialty-level FTE or
bed data exists to constrain against, so a genuinely disaggregated model
isn't supportable by what's actually warehoused.

Levers unified into one comparable unit (RTT-equivalent completed
pathways/month) rather than three different units (sessions, outsourced
cases, diagnostic slots) — makes the LP directly interpretable and avoids
compounding three separate, harder-to-defend conversion factors into one
model. Costs: c1 (in-house) = 75% x £1,500 assumed blended tariff = £1,125
(the 75% is the one genuinely SOURCED figure this session, from the ERF
mechanism found earlier — not yet re-verified against 2025/26's actual
Payment Scheme, flagged as such); c2 (outsourcing) = 100% x £1,500 =
£1,500 (also ERF-sourced multiplier, unsourced base tariff); c3
(diagnostic-unlocked pathway) = £400, the weakest-sourced figure, loosely
anchored on real CDC capital cost range (£5.2m-£18.4m/centre found last
session) but the RTT-equivalent conversion itself is an analyst
assumption. Tried once more this session to pull NHS England's actual
National Cost Collection HRG data (a real, direct download link exists:
NCC_National-Schedule_2024_25.zip) — web_fetch returned it as opaque
binary, unusable, and the sandbox itself still has no outbound internet
for a direct curl (confirmed again). Genuinely couldn't get past this
without a working general-purpose internet path from the sandbox; every
uncertain cost figure is flagged in the workbook's Assumptions tab rather
than presented as sourced when it isn't.

Solved the LP twice: once with scipy.optimize.linprog (HiGHS) as an
independent reference answer, once by reading back the same formulas
LibreOffice-recalculated inside the actual Excel file — objective, cost,
and equity-check cells matched the Python reference to within rounding
(37,499.99 vs 37,500.00 reduction; £14,999,997.60 vs £15,000,000.00 cost).
Caught two real bugs before trusting the recalculated file, not after:
(1) three Assumptions-tab note strings that started with the character
"=" got silently parsed as formulas by openpyxl/LibreOffice and returned
#N/A — reworded them; (2) the "higher-deprivation" flag and median-IMD-
rank formulas on Provider Inputs referenced column D (LA host NAME, text)
instead of column E (LA IMD rank, the number they actually needed) — a
column-index slip from restructuring the sheet layout mid-build, caught
by recalc.py's zero-tolerance error report, not by eyeballing the sheet.

Honest finding, not smoothed over: at the default £15m budget, 100% of
spend goes to the cheapest lever (diagnostics, £400/unit) — in-house and
outsourcing never activate at all. Confirmed this is a real structural
property of the model (three levers with identical modeled effect per
unit of reduction but different price will always fill cheapest-first),
not a bug, by sweeping 9 budget levels (£2m-£130m): in-house capacity
only starts activating once diagnostic headroom is exhausted, around
£90-130m ICB-wide; outsourcing never becomes the cheapest option at any
budget level tested, because the sourced ERF mechanism makes it the most
expensive of the three levers, not because it was excluded. Worth stating
plainly in the eventual executive report as a real result of the ERF's
own pricing structure, not an artifact of this model.

No VBA macro included — flagged as a deliberate limitation, not a silent
gap. openpyxl can't author a new VBA project from scratch (only preserve
one already in a template via keep_vba=True), and there's no existing
macro-enabled template in this project to start from; hand-crafting a
vbaProject.bin with no way to test it actually drives Excel's Solver
correctly risked shipping a broken file. Shipped a plain .xlsx instead,
pre-filled with the Python-validated reference-optimal solution as a
starting point, with exact cell-by-cell Solver dialog instructions
(objective cell, variable range, all 6 constraints) on the Solver Model
tab itself so Vedant can open Data > Solver and re-optimize under
different assumptions in under a minute.

Delivered: excel/NHS_Cheshire_Merseyside_Capacity_Optimizer.xlsx (5 tabs —
Read Me, Assumptions, Provider Inputs, Solver Model, Budget Sensitivity),
plus scripts/build_solver_inputs.py, scripts/solve_capacity_optimizer.py,
scripts/budget_sensitivity.py, scripts/build_solver_workbook.py for full
reproducibility. Recalculated clean (0 errors across 187 formulas) via
this project's standard recalc.py check.

### Next action
Per the original charter's ordering: Tableau story next, then the AI
decision-support layer, then the executive report, then the generalised
Healthcare Process & Performance Optimisation Framework. Before that,
worth a design check-in with Vedant on two open items from this session:
(1) whether to spend more effort getting a genuinely sourced NHS tariff
figure (would need a working outbound-internet path this sandbox doesn't
have, or Vedant downloading the NCC file locally for Claude to read from
the synced folder) before the executive report cites any £ figures from
this model as more than illustrative; (2) whether the Tableau phase
should visualize this Solver output as one of its views, which would
mean sequencing it right after this phase rather than treating the two
as fully independent.

## 2026-08-08 (continuation session, same day — real cost data)

Open item #1 above got resolved same day, not deferred: Vedant offered
screenshots of the actual NHS England National Cost Collection (NCC)
2024/25 Power BI dashboard (still couldn't be pulled directly — web_fetch
returns the underlying file as unusable opaque binary, same limitation
logged earlier this session). Rather than ask for a blind full-page
capture, asked for the specific view needed first (Summary: HRG tab,
Total row, by point-of-delivery) — got exactly that, five screenshots
covering the full currency-column set.

Real, sourced 2024/25 national average unit costs obtained: Elective
Inpatient £6,624 (1,255,967 completions), Daycase £1,078 (7,680,341),
Outpatient Procedures £233 (19,224,707), Diagnostic Imaging £140
(8,573,583 tests) — all England-wide, 206 providers, Total row. These
replace the flat £1,500/£400 analyst planning assumptions from the
original build with a genuinely weighted figure:
  - Blended admitted-completion cost = NCC's Elective Inpatient and
    Daycase costs weighted by NCC's own NATIONAL activity mix between the
    two (daycase is ~86% of national admitted activity). RTT itself
    doesn't split "admitted" completions into daycase vs. inpatient, so
    this is the one place a national ratio stands in for something this
    ICB's own data can't provide — flagged in the workbook, not hidden
    inside a single number.
  - That blended admitted cost is then combined with the REAL C&M-
    specific admitted/non-admitted completion mix (pulled fresh from
    fact_rtt_provider_specialty_month, trailing 6 months: 14.7% admitted,
    85.3% non-admitted — this ICB's own genuine mix, not assumed) and the
    real Outpatient Procedures cost as the non-admitted proxy.
  - Result: unit_tariff = £472.49 (down sharply from the £1,500 flat
    guess — because C&M's actual completions are heavily non-admitted,
    which the flat guess didn't account for). c1 (in-house, 75% ERF) =
    £354.37, c2 (outsourcing, 100% ERF) = £472.49, c3 (diagnostic) = 1.75
    x the real £140 Diagnostic Imaging cost = £245 (the 1.75 tests-per-
    pathway multiplier is the one fully unsourced figure left in the
    model — flagged as such, base cost is now real).

Re-solved the LP and re-ran the budget sweep with these real costs — the
result changed meaningfully, not just cosmetically, which is itself worth
recording: at the same £15m default budget, reduction rose from 12.7% to
20.7% (lower real costs buy more capacity for the same money). More
importantly, the earlier "outsourcing never activates" finding — reported
honestly last entry as a real structural result — turned out to be an
artifact of the placeholder costs, not a durable finding: with real
costs, in-house AND outsourcing both activate together once diagnostic
headroom exhausts (~£90m ICB-wide), and total reduction then plateaus
around 98% regardless of further budget — every lever's CAPACITY ceiling
becomes binding, not the budget. Worth flagging as a lesson for this
project generally: a "genuine structural finding" from a model still
built on flagged planning assumptions needs re-checking once real data
replaces the assumption, not treated as settled just because it passed
its own internal sanity checks.

Rebuilt the full pipeline (build_solver_inputs.py -> solve_capacity_
optimizer.py -> budget_sensitivity.py -> build_solver_workbook.py),
re-validated: clean recalc (0 errors, 190 formulas), Excel-computed
objective/cost/equity cells matched the independent Python LP solve to
within rounding again. Updated Assumptions tab now shows the full real
derivation chain (NCC source cells -> blended admitted cost -> unit
tariff -> c1/c2/c3) as live formulas, not a single hardcoded number, so
the sourcing is auditable cell-by-cell rather than asserted in a note.

### Next action
Unchanged from the prior entry otherwise: Tableau story next (worth
deciding whether it visualizes this Solver output), then AI decision-
support layer, executive report, generalised framework. The ERF 75%/100%
reimbursement split is still the one policy-mechanism figure not
re-verified against the current 2025/26 Payment Scheme — worth a final
check before the executive report treats it as current, not just
historically accurate.

## 2026-08-08 (continuation session, same day — diagnostic cost refinement)

Vedant asked what else the NCC dashboard could usefully provide, then
offered "Directly Accessed Pathology Services" (a real, granular page —
493.6m tests, £1.19bn, broken down by 9 pathology sub-services). Checked
against dim_diagnostic_test before using it, rather than blending it in
because it was offered: DM01 (the diagnostic dataset this project's
capacity-investment lever actually represents) has NO pathology category
at all — its 15 test types split into imaging, endoscopy, and
physiological measurement only. Told Vedant plainly the pathology data,
while real, doesn't apply here rather than forcing a fit.

Used the real DM01 test-mix instead (12 core trusts, whole warehouse
window, from fact_dm01_provider_test_month x dim_diagnostic_test):
imaging 79.2%, audiology 3.8%, other physiological measurement
(echocardiography, sleep studies, neurophysiology, urodynamics) 9.2%,
endoscopy 7.7%. Matched each category to the closest real NCC currency —
Diagnostic Imaging (£140) for imaging, Directly Accessed Audiology (£107)
for audiology specifically, Directly Accessed Diagnostic Services (£90)
as the best available proxy for the other physiological measurement
tests, and Outpatient Procedures (£233) for endoscopy since NCC has no
dedicated "diagnostic test" currency for endoscopy — most NHS endoscopies
are costed as day-case/outpatient procedures, so reusing that existing
model input was the more honest match than stretching Diagnostic Imaging
to cover something it isn't.

Weighted result: £141.33/test, barely different from the prior
imaging-only £140 proxy — because imaging dominates DM01 volume at ~79%.
Worth stating plainly: this was a genuine check, not a wasted step —
confirms the earlier single-category proxy was already reasonable rather
than silently assuming so. c3 (diagnostic-unlocked pathway cost) moves
from £245 to £247.32; at the default £15m budget, total reduction moves
from 20.66% to 20.47% — a real but small effect, consistent with how
little the underlying unit cost moved.

Re-ran the full pipeline and re-validated: clean recalc (0 errors, 191
formulas), Excel and Python LP solve agree on objective/cost/equity cells
again. Assumptions tab now carries the full DM01-to-NCC-currency mapping
as auditable cells (4 real DM01 shares x 4 matched NCC costs -> weighted
diagnostic cost -> c3), not a single asserted number.

### Next action
Same as before: Tableau story next per the charter, ERF split still
needs re-verification against 2025/26's actual Payment Scheme before the
executive report cites it as current.

## 2026-08-08 (continuation session, same day — Solver automation)

Vedant asked to add Solver's setup into the file directly and resave.
Same limitation as the VBA-macro decision earlier this project: openpyxl
can't author a new VBA project into the xlsx, and this sandbox has no
real Excel to validate a hand-crafted macro against (only LibreOffice,
whose Solver tool is a different implementation with its own storage
format) — embedding something untestable risked shipping a file that
looks done but silently fails when Vedant actually opens Data > Solver.

Gave the safer version instead: excel/solver_macro.bas, plain-text VBA
using Excel's standard, decades-stable Solver API (SolverReset/SolverOk/
SolverAdd/SolverSolve — not a reverse-engineered binary format), with the
exact cell references already documented on the Solver Model tab (L19
objective, I6:K17 decision variables, all 6 constraints) and step-by-step
paste-in instructions. Vedant adds it himself via Alt+F11 — 30 seconds,
and he can read exactly what it does before running it, rather than
trusting an opaque embedded blob.

### Next action
Unchanged: Tableau story next per the charter.

## 2026-08-08 (continuation session, same day — ERF split corrected)

Closed the one flagged-but-unverified item explicitly this time, rather
than letting it ride into the next phase: the 75%/100% Elective Recovery
Fund marginal-rate split (c1 vs c2's cost differential, sourced from a
2022 HFMA article describing the 2022/23 scheme) checked against the
actual current 2025/26 NHS Payment Scheme.

Result: WRONG, not just unverified. NHS England's own 2025/26 NHSPS
documentation ("NHS provider payment mechanisms" long-read, the main
2025/26 NHSPS page, corroborated by HFMA reporting) confirms the
marginal-rate mechanism was REMOVED for 2025/26 — both NHS and
independent-sector providers are now paid 100% of NHSPS unit price for
elective activity, with no floors, ceilings, or marginal rates, a
"significant change from previous arrangements" per NHS England's own
framing. c1 (in-house) and c2 (outsourcing) are corrected to be equal
(£472.49 each) rather than 75%/100% of the blended tariff.

Real consequence, not cosmetic: the earlier "in-house is structurally
cheaper than outsourcing" finding — which drove every allocation decision
up to this point whenever diagnostic headroom ran out — was itself an
artifact of using the wrong, outdated payment rule. With the correction,
the two levers are genuinely tied on cost, and the LP is indifferent
between them (Solver fills whichever has capacity headroom, not whichever
policy makes cheaper). Re-ran the budget sweep to confirm: at £90m
in-house and outsourcing now split roughly evenly (41,488 vs 39,294
units) rather than the earlier heavily in-house-skewed split (137,451 vs
16,844) that the wrong cost differential had been producing.

Caught a real bug while rebuilding, before shipping it: updated the
Assumptions tab's note text describing c1 as corrected, but initially
forgot to update the actual Excel FORMULA underneath it — the cell still
computed unit_tariff x 75% even though the note said 100%. A note
matching a formula's intent isn't the same as the formula matching it;
caught by re-checking the recalculated file's actual values against the
Python reference (c1 read back as £354, not £472) rather than trusting
that editing the docstring meant the behavior changed. Fixed and
re-validated — recalc clean (0 errors, 191 formulas), Excel and Python LP
solve agree again.

This changes what's now the only real caveat on the Solver's cost model:
the diagnostic lever's tests-per-pathway conversion (1.75x) and the
admitted/daycase-inpatient national-mix bridging assumption. Everything
else in the cost structure is now sourced and verified against current
policy, not carried forward from an unverified flag.

Note for whoever opens the workbook next: Vedant's own manual Solver run
from earlier this session was on the PRE-correction cost model (75%/100%
split) and got overwritten when the workbook was rebuilt — he'll need to
re-run Solver (native Data > Solver, or the solver_macro.bas VBA route,
both still using the same cell layout and setup instructions, unchanged)
to get an allocation consistent with the corrected costs. The pre-filled
reference solution in the file already reflects the correction.

### Next action
Every flagged Solver-phase item is now either sourced or explicitly and
correctly labeled as an estimate — no more open verification items before
moving on. Tableau story next per the charter.

## 2026-08-08 (continuation session, same day — stale-file save caught)

Vedant re-ran Solver and saved, said "done" for a check. Read the file
back and the allocation looked plausible (valid, zero cap violations,
budget exactly spent, equity constraint satisfied) but c1_inhouse read
back as £354.37 — the OLD, uncorrected 75%-of-tariff value, not the
£472.49 fix from the entry above. His Excel session had almost certainly
still had the pre-correction workbook open in memory from earlier in the
session; saving wrote that stale in-memory state back over the corrected
file on disk. The objective value (60,649) still matched either cost
version's expected answer, which could easily have looked like
confirmation if not checked cell-by-cell — coincidental, not meaningful:
at this £15m budget the optimal solve never touches the in-house/
outsourcing levers at all, so c1/c2's exact price doesn't affect this
particular result either way. A matching total number is not the same as
a correct file — checked the actual Assumptions-tab cell value, not just
the objective, and that's what caught it.

Rebuilt clean end-to-end from the (already-fixed) pipeline scripts rather
than trust any intermediate /tmp state, re-validated (0 errors, 191
formulas), confirmed c1=c2=£472.49 in the file actually on disk this
time, re-copied to excel/.

Practical note for Vedant to avoid repeating this: close the workbook in
Excel fully before Claude regenerates and re-delivers it, then reopen the
fresh copy before running Solver again — an open Excel session doesn't
notice the file changed underneath it and will happily save its own
stale in-memory version back over a correction.

### Next action
Unchanged: Tableau story next per the charter.

## 2026-08-11 (Phase 4 verified, Phase 5 built — scenario wayfinding)

### Phase 4 sign-off
Vedant delivered `tableau/NHS_Cheshire_Merseyside_Capacity_Story.twbx` (Tableau
2026.2.1). Verified by parsing the workbook XML rather than by eye: all five
story points present and mapped to the right dashboards, extracts embedded
(3 .hyper files, so it is portable off his Desktop path), all nine CSVs
modelled as Tableau relationships rather than joins so there is no
row-duplication fan-out, and the inequality annotation now reads in the
CORRECTED direction ("more-deprived catchments actually have MORE consultants
per 1,000 FTE", rho=-0.59, p=0.044). Confirmed over52 is a strict subset of
over18 in all 1,005 rows and that sheets 1b/5a use two pills on a shared axis
rather than an arithmetic sum, so there is no double-count.

Five fixes handed back rather than applied — no Tableau here to validate an
XML edit against, same reasoning as the VBA macro: (1) delete the leftover
`Sheet 1`; (2) `3b` uses SUM on a per-1,000 ratio, renders identically today
because provider is on Detail but breaks silently if the LOD changes, should
be AVG; (3) `3a`/`3b` x-axis is imd_avg_rank with no reversal and no
directional label — the exact trap that produced the backwards write-up once
already; (4) dashboard `Forecast` breaks the 1-5 naming; (5) `2b` carries an
unlabelled quantitative filter on the pressure index measure.

### Phase 5 — scenario and strategy model
Vedant's steer: deterministic/offline only, Python scripts plus a validation
report, Excel workbook plus CSVs, and — after sharing Cairns & Wright's
*Scenario Thinking* (2nd ed.), Sminia's *The Strategic Manager* (3rd ed., chs
1-8) and Sminia's 2026 *Futures & Foresight Science* wayfinding paper — "read
the book, draw insight from them and make your call". Also: this must read as
a real ICB deliverable, not a portfolio exercise.

Built to Cairns & Wright Ch.2 (basic method stages 1-8), Ch.5 (Goodwin &
Wright sum-of-ranks with weight sensitivity), Ch.8 (minimax regret,
flexible/diversified/insurable screen, early-warning flags), framed on
Sminia's scenario-doing/wayfinding distinction, with an institutional
feasibility screen from Sminia Ch.7 (institutional theory — OCR'd, the PDF is
a scanned image with no text layer).

Two departures from the book, both because this project has quantitative
material a workshop does not: the Stage 5 impact axis is COMPUTED (swing in
breaches cleared per driver, a one-at-a-time tornado) rather than placed by
sticky note, with the uncertainty axis graded against the project's own
source-provenance record; and cluster ranges are measured where measurable —
the backlog range is the Phase 2 MC forecast's own p5/p95 at horizon end
(0.911/1.147 of p50).

Deliverables: `excel/NHS_CM_Scenario_Strategy_Model.xlsx` (12 tabs, 402
formulas, live objective weights so the ordering recalculates), `scenarios/`
CSVs + full JSON, 5 new Tableau extracts, `docs/PHASE5_VALIDATION.md`, and
three scripts (`scenario_wayfinding.py`, `scenario_early_warning.py`,
`build_scenario_workbook.py`).

### Findings that changed the picture
1. **It is not a capacity problem, it is a money problem.** No capacity
   ceiling binds until £31.9m (independent sector), £69.7m (diagnostic) or
   £107.1m (in-house). The scenario range is £7.5m-£30m. Consequence:
   independent-sector scalability, NHS in-house productivity and the size of
   the backlog itself have LITERALLY ZERO effect on breaches cleared at any
   funding level in scope. Three long-running debates are not live decisions.
2. **One number decides the whole allocation.** The diagnostic and treatment
   levers are indifferent at 3.343 tests per unlocked pathway (verified two
   ways: closed form 472.49/141.33, and bisection on the spend mix). Below it
   the model spends 100% on diagnostics; at 3.40 it flips to 77% in-house /
   23% outsourcing. The working assumption is 1.75 — the one figure in the
   whole model with no published source.
3. **That figure can now be triangulated from our own warehouse.** Observed
   DM01 activity per completed RTT pathway across the 12 core trusts is 0.84
   (trailing 12m), 0.76 (full 84-month window), never above 0.91 in any single
   month. Does NOT settle the parameter — DM01 excludes pathology (understates)
   but includes non-RTT direct-access tests (overstates), and the model
   parameter is marginal while the proxy is an average. Reported as bounding
   the argument, not closing it: the direction of the recommendation is better
   evidenced than the magnitude of the benefit.
4. **Equity is free here.** The 15pp equity tolerance never binds. At every
   funding level examined the entire reduction can be directed to
   higher-deprivation providers at zero cost to total breaches cleared,
   because the budget clears far less than those trusts alone are carrying.
   S1 (unconstrained) and S5 (equity-first) are detected as an identical
   commitment and reported as such.
5. **Recommendation: S2, NHS delivery only** — first under equal weights and
   under all eight weight-sensitivity tests, zero worst-case regret. One live
   counter-indication, reported prominently rather than buried: DM01 6-week
   breach share has risen 6.2% -> 9.9% in twelve months, which undercuts the
   10% diagnostic headroom the strategy assumes.

### Two real defects caught in validation
- **Equity figures were solver artefacts.** The first build reported the same
  15,873 breaches cleared at both 100% and 29.7% higher-deprivation share
  depending only on which optimal vertex HiGHS reached. The Phase 3 log had
  already established this LP is degenerate when two levers are priced
  identically; what was new was that an equity OBJECTIVE had been built on top
  of that non-unique quantity and was being ranked. Fixed with a lexicographic
  second solve: hold total reduction at its optimum, then maximise the
  higher-deprivation share among all allocations achieving it.
- **Excel and Python disagreed on the ranking, and a clean recalc did not
  catch it** (0 errors, 402 formulas — the formulas evaluated correctly and
  returned wrong numbers). Root cause in two layers: first, genuine ties broken
  by floating-point noise (63,493.495 vs 63,493.432 — 0.06 of a breach in
  63,493); then, after rounding the engine's ranking basis, the workbook was
  still recomputing value-for-money from ROUNDED breaches while Python used
  UNROUNDED ones. Rounding in two places was worse than not rounding at all.
  Fixed with a single canonical basis (`canonicalise()`) that rebuilds every
  derived quantity from the rounded inputs exactly as the workbook's formulas
  do. Now 0 mismatches across 40 rows x 4 rank columns, 8 strategy totals and
  8 regret figures.

### Next action
Phase 6 (executive report) and Phase 7 (generalised framework) remain. The
scenario CSVs are cut and ready for a sixth Tableau story point if wanted.
Standing instruction unchanged: nothing pushed to GitHub until the whole
project is done.

## 2026-08-12 (Phases 6 and 7 — board paper, toolkit, and a recommendation that changed)

### Phase 6 — executive board paper
`docs/NHS_CM_Elective_Capacity_Board_Paper.docx`, 10 pages, recommendation-first
per Vedant's steer, written as a real ICB committee paper (version block,
distribution, explicit decision sought, annexes) rather than a portfolio piece.
Six figures, all generated from stored outputs by `scripts/build_report_figures.py`
so none can drift from the analysis: backlog with MC forecast band, capacity
ceilings vs funding range, the tipping-point curve, strategy comparison,
observed diagnostic conversion, diagnostic waiting-time context. Each render
was viewed and three placement defects fixed before shipping.

### Tableau remediation
`docs/TABLEAU_REMEDIATION.md` — step-by-step for the four fixes, written against
the actual workbook XML. NOTE: the fifth item I flagged in the previous session
is WITHDRAWN. The filter on `2b` is `included-values="non-null"` — Tableau's
standard automatic null-exclusion filter, not a leftover threshold. Recorded as
withdrawn rather than quietly dropped.

### Phase 7 — config-driven toolkit
`config/*.yaml` + `scripts/toolkit/{config,extract,engine,run}.py`, documented in
`docs/FRAMEWORK.md`. Everything engagement-specific is in the YAML; the engine
is engagement-agnostic. `config.py` refuses to start on an ambiguous config
rather than defaulting silently (it will not, for instance, guess whether a low
deprivation rank means more or less deprived).

Honest boundary, stated in FRAMEWORK.md rather than glossed: `extract.py` still
assumes THIS warehouse's table and column names. Scope, envelope, tolerances,
levers, costs, drivers, strategies and objectives are parameterised; the schema
is not.

### A statistical claim I had to retract
The "diagnostic waits deteriorating, 6.2% -> 9.9% in twelve months" line from the
previous session was ENDPOINT SELECTION on a noisy series, not a finding. Tested
properly: full window trends significantly DOWNWARD (-0.138pp/month, p=0.009,
Kendall tau -0.24 p=0.001); last 24 months no significant trend either way
(p=0.209); last 12 months no significant trend (p=0.131) on sd=2.0. What
survives is a level shift between consecutive 12-month means, 8.1% -> 10.2%.
Corrected in flag F3, the workbook, the board paper and fig6 (which now shows
all 84 months, so the COVID spike to 62% and the recovery to a ~10% plateau are
visible — and that 10% is still ~3x the pre-pandemic 3%).

### The big one: a third degenerate quantity, found only by building the toolkit
Diffing the generalised toolkit against the Phase 5 engine cell by cell found
ONE disagreement in 40: A2B1/S6, identical volume (116,655) and identical equity,
but delivery-risk exposure 0.855 vs 0.823. Root cause: the §3.1 lexicographic fix
pinned volume then equity but left the LEVER MIX free — and delivery risk is
computed from the lever mix. So a ranked objective was, once again, reading
solver internals.

Fixed with a THIRD lexicographic stage (maximise volume -> maximise equity within
that -> minimise reliance on evidence-weak levers within that). Applied to both
the Phase 5 engine and the toolkit so they cannot diverge.

Consequence was material, not cosmetic:
- S1, S2 and S5 are now revealed to be THE SAME COMMITMENT (identical on all 4
  objectives in all 5 scenarios, 274 each). S2's previous apparent lead was
  noise in an unpinned quantity.
- The recommendation is NO LONGER weight-stable. S7 takes first whenever
  delivery risk is weighted x2 or x3.
- The board paper was rewritten to present a judgement about risk appetite
  rather than a robust result, and states the correction in its assurance annex.
- The recommendation is still S2, but now for a different and better reason:
  the model is genuinely indifferent between S1/S2/S5, so the tie is broken on
  institutional legitimacy (Sminia Ch.7) — ground the model does not capture.

Rule now enforced in the toolkit and written into FRAMEWORK.md: NEVER RANK A
QUANTITY THE OPTIMISATION DOES NOT PIN. Broken twice on this project; both times
the resulting figure looked entirely reasonable and was wrong.

### Toolkit validation
- Reproduction: toolkit reproduces the Phase 5 engine exactly — 40 cells x 6
  metrics agree to 1.5e-08, all 8 strategy scores match, same degenerate pairs,
  same tipping point (3.3429), all 8 weight orderings identical.
- Discrimination: second config (7 acute trusts only, £9m, 10pp) runs with zero
  code changes and shifts the tipping point to 3.3677, S3 339->320, S4 361->364,
  S6 374->367, S7 295->292, S7 regret 106,324->63,685. Structural conclusions
  hold across both, which is the right answer for two scopes of the same health
  economy. Caveat stated in FRAMEWORK.md: same warehouse, same levers, same cost
  schedule — this does not evidence portability to a different schema.

### Next action
All seven charter phases complete. Outstanding: the four Tableau fixes on
Vedant's side, an optional sixth story point (extracts already cut in
`tableau/`), and the GitHub push — still gated on Vedant's standing instruction
that nothing is pushed until the whole project is done.
