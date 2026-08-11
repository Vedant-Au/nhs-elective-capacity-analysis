-- Staging layer for the Monthly A&E Attendances and Emergency Admissions
-- collection. Source: NHS England direct CSV download (no zip, unlike RTT/
-- DM01), one file per month. Profiled Apr-2019, Jul/Aug-2020 (either side of
-- a documented format change), Mar-2022, Mar-2024, Dec-2024 and Mar-2026 on
-- 2026-08-07 before writing this DDL.
--
-- Unlike RTT and DM01, this is NOT schema-stable across the whole FY19-20-
-- FY25-26 window. There's exactly one break, and NHS told us about it on the
-- page itself ("Format ... have changed due to the inclusion of booked
-- attendances") rather than me having to discover it blind:
--   - Apr-2019 through Jul-2020 (16 months): 16 columns, no booked-
--     appointments breakout.
--   - Aug-2020 onward (68 months): 22 columns — the three "A&E attendances"
--     and three "Attendances over 4hrs" columns each split into a
--     Type1/Type2/Other trio PLUS a parallel Booked Appointments
--     Type1/Type2/Other trio.
-- Checked both sides of the boundary plus three more recent months and the
-- 22-column shape is stable from Aug-2020 straight through to Mar-2026 — one
-- break, not a moving target. Staging table uses the 22-column superset; the
-- six booked_* columns are genuinely NULL (not zero) for the 16 pre-Aug-2020
-- months, because "how many were booked appointments" simply wasn't
-- collected yet, not because it was zero.
--
-- Grain is (period, provider org_code) — no commissioner dimension here at
-- all, unlike RTT/DM01, because A&E attendance is inherently a provider-side
-- count (whoever showed up at whose department), not something with a
-- referring commissioner attached.
--
-- Note "Parent Org" in this collection is the NHS England REGION the
-- provider sits under (e.g. "NHS ENGLAND NORTH WEST"), not the ICB — a
-- genuinely different meaning from RTT/DM01's "Provider Parent". Region is
-- too coarse to be useful (all of Cheshire & Merseyside plus Greater
-- Manchester plus Lancashire are all "NORTH WEST"), so it's kept here for
-- completeness/traceability but the ICB filter for this fact table still
-- comes from dim_provider (seeded from the real RTT extract), the same as
-- every other source in this warehouse.
--
-- NHS also publishes a pre-aggregated "TOTAL" pseudo-row, same idea as
-- DM01's TOTAL row — but two things are messier here than DM01: (1) it's
-- absent entirely from all 12 FY2019-20 files (NHS hadn't started including
-- it yet — genuinely missing, not a scraping fault, confirmed by checking
-- every FY19-20 file), and (2) even where present, the "TOTAL" marker
-- sometimes lands in the Period column and sometimes in the Org Code column
-- depending on the month, and the label itself isn't consistently cased
-- ('TOTAL', 'Total', 'Total ' with a trailing space, and one straight typo
-- 'TOTAl' turned up). Verified on Mar-2026 via a proper CSV parser (not
-- naive comma-splitting, which mis-split on the first attempt and produced
-- a false mismatch) that where the row exists, summing the 199 real
-- provider rows matches it exactly — same trust-but-verify conclusion as
-- DM01, so the fact table re-derives the total from real provider rows
-- rather than reading NHS's own TOTAL row, and doesn't depend on it being
-- present or consistently labelled.

create table if not exists stg_ae_raw (
    period                              text not null,   -- e.g. 'MSitAE-MARCH-2026'
    provider_org_code                   text not null,    -- ODS code, e.g. 'REM'
    parent_org_region                   text,             -- NHS England region (NOT the ICB — see header note)
    provider_org_name                   text,

    attendances_type1                   integer,          -- major A&E (type 1)
    attendances_type2                   integer,          -- single specialty (type 2, e.g. some eye/dental units)
    attendances_other                   integer,          -- type 3/4 — UTCs, minor injury units, walk-in centres
    attendances_booked_type1            integer,          -- NULL pre-Aug-2020, see header note
    attendances_booked_type2            integer,
    attendances_booked_other            integer,

    over4hr_type1                       integer,
    over4hr_type2                       integer,
    over4hr_other                       integer,
    over4hr_booked_type1                integer,          -- NULL pre-Aug-2020
    over4hr_booked_type2                integer,
    over4hr_booked_other                integer,

    waited_4to12hr_dta                  integer,          -- decision-to-admit to actual admission, 4-12hrs
    waited_12hr_plus_dta                integer,          -- decision-to-admit to actual admission, 12+ hrs — the corridor-care metric

    emergency_admissions_type1          integer,
    emergency_admissions_type2          integer,
    emergency_admissions_other          integer,
    other_emergency_admissions          integer,          -- emergency admissions NOT via A&E (e.g. direct GP admission)

    source_file                         text,
    loaded_at                           timestamp default now()
);

create index if not exists idx_stg_ae_period on stg_ae_raw (period);
create index if not exists idx_stg_ae_provider on stg_ae_raw (provider_org_code);

-- No long/unpivoted view for A&E — unlike RTT's wait bands or DM01's per-
-- test breakdown, there's no natural "band" dimension here worth unpivoting.
-- The 22 columns are already the right shape to query directly.
