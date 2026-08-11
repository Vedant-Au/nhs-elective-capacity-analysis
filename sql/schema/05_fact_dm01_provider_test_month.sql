-- Core DM01 fact tables at two grains: provider x diagnostic-test x month
-- (for the "which modality is the bottleneck" cut) and provider x month
-- (all tests combined, for the pressure index that has to sit alongside the
-- RTT fact table at the same provider-month grain). Built by aggregating
-- stg_dm01_raw across commissioners, same reasoning as the RTT fact table —
-- the warehouse cares which provider did the test, not who referred the
-- patient.
--
-- DM01's operational standard is a 6-week wait, not RTT's 18/52-week
-- thresholds, so "long wait" here means >6 weeks, not >18. Keeping this
-- fact table's column names test-specific (over_6wk, not over_18wk) so
-- nobody downstream mixes up the two standards by copy-pasting a column
-- name across fact tables.

drop table if exists fact_dm01_provider_test_month;

create table fact_dm01_provider_test_month as
with base as (
    select
        provider_org_code,
        diagnostic_test_code,
        period,
        total_wl,
        (wk_06+wk_07+wk_08+wk_09+wk_10+wk_11+wk_12+wk_13_plus) as over_6wk,
        wk_13_plus as over_13wk,   -- the open-ended tail, DM01's equivalent of a "very long wait" flag
        waiting_list_activity,
        planned_activity,
        unscheduled_activity,
        total_activity
    from stg_dm01_raw
    where diagnostic_test_code <> 'TOTAL'   -- exclude NHS's own pre-aggregated row, re-derived below instead
)
, agg as (
    select
        provider_org_code,
        diagnostic_test_code,
        period,

        sum(total_wl)               as waiting_list_size,
        sum(over_6wk)                as waiting_list_over_6wk,
        sum(over_13wk)               as waiting_list_over_13wk,

        sum(waiting_list_activity)   as waiting_list_activity,
        sum(planned_activity)        as planned_activity,
        sum(unscheduled_activity)    as unscheduled_activity,
        sum(total_activity)          as total_activity

    from base
    group by provider_org_code, diagnostic_test_code, period
)
select
    *,
    case when waiting_list_size > 0
         then round(waiting_list_over_6wk::numeric / waiting_list_size, 4)
         else null end as long_wait_share_6wk
from agg;

alter table fact_dm01_provider_test_month
    add primary key (provider_org_code, diagnostic_test_code, period);


-- All-tests-combined rollup at the provider-month grain — this is the one
-- that actually joins to fact_rtt_provider_specialty_month's grain for the
-- Phase 2 pressure index (RTT is per specialty, DM01 is per test, neither
-- decomposes into the other, so "all tests combined" is the right level to
-- bring diagnostics into a provider-wide capacity view). Summed from the
-- per-test fact table above rather than re-reading stg_dm01_raw's TOTAL
-- pseudo-row — verified on Mar-2026 that the two approaches agree exactly
-- (see 04_staging_dm01.sql comment), and summing our own already-validated
-- fact table means this rollup can't silently drift from it.
drop table if exists fact_dm01_provider_month;

create table fact_dm01_provider_month as
select
    provider_org_code,
    period,
    sum(waiting_list_size)        as waiting_list_size,
    sum(waiting_list_over_6wk)    as waiting_list_over_6wk,
    sum(waiting_list_over_13wk)   as waiting_list_over_13wk,
    sum(waiting_list_activity)    as waiting_list_activity,
    sum(planned_activity)         as planned_activity,
    sum(unscheduled_activity)     as unscheduled_activity,
    sum(total_activity)           as total_activity,
    case when sum(waiting_list_size) > 0
         then round(sum(waiting_list_over_6wk)::numeric / sum(waiting_list_size), 4)
         else null end as long_wait_share_6wk
from fact_dm01_provider_test_month
group by provider_org_code, period;

alter table fact_dm01_provider_month
    add primary key (provider_org_code, period);
