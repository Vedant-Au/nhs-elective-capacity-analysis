-- Staging layer for KH03 (Bed Availability and Occupancy), overnight G&A/
-- Maternity/Mental Illness/Learning Disability beds. Quarterly collection,
-- not monthly like RTT/DM01/A&E — 4 snapshots a year, quarter-end dates
-- (30 Jun, 30 Sep, 31 Dec, 31 Mar).
--
-- Two genuinely different source shapes had to be reconciled here, not just
-- two file formats of the same shape like RTT's zip-vs-csv or A&E's
-- direct-csv:
--   1. NHS publishes three consolidated "flat file" CSVs (KH03-Available-
--      Overnight-only.csv, KH03-Occupied-Overnight-only.csv, plus a by-
--      specialty one not used here — see note below) covering the full
--      history back to 2001 in long format: one row per (provider, sector,
--      quarter). Checked the actual min/max dates in these files rather
--      than trusting the filename's "onwards" framing — they stop at
--      2024-06-30 (Q1 2024-25), not the present day, even though the page
--      itself is current. That's a real gap against this project's FY19-20-
--      FY25-26 window, not a mistake on my end — the consolidated CSVs are
--      just stale relative to the individual quarterly releases.
--   2. To cover Q2 2024-25 through Q4 2025-26 (the gap), pulled the
--      individual quarterly "Beds-Open-Overnight-Web_File-QX-20XX-XX.xlsx"
--      releases directly — these are wide-format (Available and Occupied
--      per sector as side-by-side column blocks on one row per provider,
--      not one row per provider-sector) and have an 11-row metadata/title
--      preamble before the real header at row 15, data from row 18 (row 16
--      is an England national total row, row 17 is a blank spacer — both
--      confirmed by inspection, not assumed). Reconciled by reshaping the
--      wide quarterly files into the same long (provider, sector, quarter,
--      available, occupied) shape as the consolidated CSVs during load,
--      rather than trying to force the CSVs into a wide shape — the long
--      shape is the more stable target since it doesn't hardcode a fixed
--      set of sector columns.
--
-- Scope decision, flagged explicitly rather than silently: this table only
-- covers overnight beds by sector (General & Acute / Maternity / Mental
-- Illness / Learning Disability), not day-only beds, and not the specialty-
-- level breakdown NHS also publishes (KH03-Occupied-by-Spec-Overnight-only,
-- 932k rows nationally). Day-only beds matter for day-case elective
-- throughput and the specialty split would sharpen the pressure index
-- further, but both roughly double the ETL surface for a secondary signal
-- when General & Acute overnight occupancy is the headline bed-pressure
-- metric NHS itself leads with. Noted as a Phase 2+ enhancement rather than
-- pretending the warehouse is more complete than it is.
--
-- Sector label casing is inconsistent in the source data ('Mental Illness'
-- vs 'Mental illness' turned up in the consolidated CSV) — normalised to a
-- fixed vocabulary during load rather than trusted as-is, same discipline
-- as A&E's TOTAL-row casing.

create table if not exists stg_kh03_raw (
    provider_org_code    text not null,     -- ODS code, e.g. 'REM'
    provider_org_name    text,               -- only populated from the Excel source; consolidated CSVs don't carry a name column
    quarter_end_date     date not null,      -- 30 Jun / 30 Sep / 31 Dec / 31 Mar
    fiscal_year          text not null,      -- '2019-20' etc, computed during load (Apr-Mar NHS fiscal year)
    sector                text not null,     -- normalised: 'General & Acute' | 'Maternity' | 'Mental Illness' | 'Learning Disability'
    available_beds        numeric,           -- average daily available beds for the quarter — fractional, NHS's own methodology, not a data error
    occupied_beds          numeric,          -- average daily occupied beds for the quarter

    source_file            text,
    loaded_at               timestamp default now()
);

create index if not exists idx_stg_kh03_provider on stg_kh03_raw (provider_org_code);
create index if not exists idx_stg_kh03_quarter on stg_kh03_raw (quarter_end_date);
