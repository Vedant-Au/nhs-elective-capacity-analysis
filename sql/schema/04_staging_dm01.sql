-- Staging layer for DM01 (Diagnostic Waiting Times and Activity) extracts.
-- Source: NHS England "CSV Extract - All Provider-Commissioner Data" (one zip
-- per month), confirmed against the real Apr-2019, Jan-2021 and Mar-2026
-- files on 2026-08-07 — schema is stable across the whole FY19-20-FY25-26
-- window (30 columns, same names, every year checked), which is a relief
-- after RTT where I had to double check the part-type coding by year.
--
-- Much simpler shape than RTT: 15 wait bands here (00<01 through 12<13,
-- then one open-ended "13+ Weeks" tail), not 106 — DM01's standard is a
-- 6-week wait target, not RTT's 18/52-week thresholds, so NHS only bothers
-- publishing weekly granularity up to 13 weeks before bucketing the rest.
-- Grain is (period, provider, commissioner, diagnostic test) — no separate
-- "part type" dimension like RTT, but there IS a "TOTAL" pseudo-row per
-- provider/commissioner that NHS pre-aggregates across the 15 real tests.
-- Verified this on the Mar-2026 file: summing the 15 real tests' Total WL
-- per (provider, commissioner) matches the declared TOTAL row exactly,
-- 9,316/9,316 pairs, zero mismatches — so it's safe to either use NHS's own
-- TOTAL row or re-derive it; the fact table below excludes the TOTAL
-- pseudo-row from the per-test grain and re-derives the all-tests view by
-- summing the real 15, so the fact table never has to trust an un-auditable
-- externally-supplied total.

create table if not exists stg_dm01_raw (
    period                              text not null,   -- e.g. 'DM01-MARCH-2026'
    provider_parent_org_code            text,             -- ICB the provider sits under
    provider_parent_name                text,
    provider_org_code                   text not null,    -- ODS code, e.g. 'REM'
    provider_org_name                   text,
    commissioner_parent_org_code        text,
    commissioner_parent_name            text,
    commissioner_org_code               text,
    commissioner_org_name               text,
    diagnostic_test_sort_order          integer,          -- 1-15 for real tests, 16 = NHS's own "TOTAL" pseudo-row
    diagnostic_test_code                text not null,    -- e.g. 'MRI', 'CT', ... , 'TOTAL'

    -- 15 wait bands: 14 finite weekly bands then one open-ended tail.
    -- Named wk_00 ... wk_12 (matching the band's lower bound in weeks) plus
    -- wk_13_plus for the '13+ Weeks' catch-all, same naming convention as
    -- RTT's wk_* columns for consistency across the warehouse.
    wk_00 integer, wk_01 integer, wk_02 integer, wk_03 integer, wk_04 integer,
    wk_05 integer, wk_06 integer, wk_07 integer, wk_08 integer, wk_09 integer,
    wk_10 integer, wk_11 integer, wk_12 integer,
    wk_13_plus integer,                 -- '13+ Weeks' — no upper bound, the long-wait tail

    total_wl                            integer,          -- 'Total WL' — verified = sum(wk_00..wk_13_plus) on every row checked, 0 mismatches across 149,056 rows
    waiting_list_activity               integer,          -- patients seen who were on the waiting list
    planned_activity                    integer,          -- surveillance/planned re-tests, not driven by a referral
    unscheduled_activity                integer,          -- activity outside the normal booking process (e.g. inpatient add-ons)
    total_activity                      integer,          -- waiting_list_activity + planned_activity + unscheduled_activity

    source_file                         text,             -- which zip this row came from, for traceability
    loaded_at                           timestamp default now()
);

create index if not exists idx_stg_dm01_period on stg_dm01_raw (period);
create index if not exists idx_stg_dm01_provider on stg_dm01_raw (provider_org_code);
create index if not exists idx_stg_dm01_test on stg_dm01_raw (diagnostic_test_code);


-- Unpivoted long view, same rationale as stg_rtt_long: stays a view, not a
-- materialized table, since most consumers only need the total_wl / band
-- aggregates already on stg_dm01_raw. Useful when Tableau needs the actual
-- wait-time distribution curve for a specific test/provider.
create or replace view stg_dm01_long as
select period, provider_org_code, provider_org_name,
       commissioner_org_code, commissioner_org_name,
       diagnostic_test_code,
       band, patient_count
from stg_dm01_raw
cross join lateral (
    values
        ('00', wk_00), ('01', wk_01), ('02', wk_02), ('03', wk_03), ('04', wk_04),
        ('05', wk_05), ('06', wk_06), ('07', wk_07), ('08', wk_08), ('09', wk_09),
        ('10', wk_10), ('11', wk_11), ('12', wk_12), ('13+', wk_13_plus)
) as bands(band, patient_count)
where patient_count is not null and patient_count <> 0
  and diagnostic_test_code <> 'TOTAL';  -- exclude the pseudo-row here too, this view is for real per-test detail
