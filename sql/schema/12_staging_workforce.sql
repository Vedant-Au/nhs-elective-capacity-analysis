-- Staging layer for NHS Workforce Statistics (HCHS staff), one March
-- snapshot per fiscal year, Cheshire and Merseyside trusts only. See
-- scripts/load_workforce.py header for the full scope rationale (annual
-- snapshot, headline staff-group columns only) and the three-era column
-- layout drift this loader has to reconcile (no ICS columns pre-2022, no
-- header text at all on the org columns in the two oldest files).
--
-- provider_org_code is the same ODS code used throughout this warehouse
-- (RTT/DM01/A&E/KH03), joinable directly against those fact tables and
-- against sql/reference/cheshire_merseyside_providers.csv. Note RBN's
-- provider_org_name changes from "St Helens and Knowsley Teaching
-- Hospitals NHS Trust" (2020-21) to "Mersey and West Lancashire Teaching
-- Hospitals NHS Trust" (2022 onwards) — a real trust merger/rename, not a
-- data error, and the reason provider_org_name is stored per-row here
-- rather than assumed to be a stable attribute joinable from the
-- reference CSV alone.

create table if not exists stg_workforce_raw (
    fiscal_year                            text not null,     -- '2019-20' etc — always the March snapshot of that FY
    period_end_date                         date not null,     -- 31 March of the relevant calendar year
    provider_org_code                       text not null,     -- ODS code, e.g. 'REM'
    provider_org_name                       text,

    total_fte                                numeric,           -- all HCHS staff, full-time equivalent
    prof_qual_clinical_fte                    numeric,           -- doctors + nurses + midwives + ambulance + scientific/therapeutic/technical
    hchs_doctors_fte                          numeric,           -- all doctor grades combined
    consultant_fte                            numeric,           -- consultant grade only — the scarce, elective-throughput-critical grade
    nurses_health_visitors_fte                 numeric,
    scientific_therapeutic_technical_fte        numeric,           -- includes radiographers/radiologists' support staff — relevant to DM01 diagnostic capacity

    source_file                                text,
    loaded_at                                    timestamp default now()
);

create index if not exists idx_stg_workforce_provider on stg_workforce_raw (provider_org_code);
create index if not exists idx_stg_workforce_fy on stg_workforce_raw (fiscal_year);
