-- A&E fact table, grain (provider, month) — no test/specialty dimension to
-- cut by here, unlike RTT/DM01, so there's only one fact table for this
-- source rather than a per-detail-grain table plus a rollup.
--
-- Excludes NHS's own TOTAL pseudo-row before aggregating. Have to check for
-- it in either the period column or the provider_org_code column (see
-- 06_staging_ae.sql header note on why), case-insensitively and trimmed,
-- since the label position and casing both vary by month and I'm not
-- willing to bet a future month doesn't introduce yet another casing
-- variant NHS hasn't used yet.
--
-- total_attendances and total_over4hr both sum the type1/type2/other trio
-- AND the booked-appointment trio with coalesce-to-zero, so a pre-Aug-2020
-- month (where the booked_* columns are genuinely NULL, not zero) still
-- gets a correct total from the three columns that did exist rather than
-- the sum silently going NULL. This is the one place in this fact table
-- where NULL-vs-zero actually matters for a downstream sum, so it's called
-- out explicitly rather than left to whatever the SQL engine's default
-- NULL-propagation behaviour happens to be.
--
-- pct_seen_within_4hr is NHS's actual headline A&E performance metric (the
-- "4-hour standard"), computed here rather than trusted from any published
-- source, same reasoning as everywhere else in this warehouse — provenance
-- over convenience.

drop table if exists fact_ae_provider_month;

create table fact_ae_provider_month as
with base as (
    select
        provider_org_code,
        period,

        attendances_type1, attendances_type2, attendances_other,
        attendances_booked_type1, attendances_booked_type2, attendances_booked_other,

        over4hr_type1, over4hr_type2, over4hr_other,
        over4hr_booked_type1, over4hr_booked_type2, over4hr_booked_other,

        waited_4to12hr_dta,
        waited_12hr_plus_dta,

        emergency_admissions_type1, emergency_admissions_type2,
        emergency_admissions_other, other_emergency_admissions

    from stg_ae_raw
    where lower(trim(period)) <> 'total'
      and lower(trim(provider_org_code)) <> 'total'
)
select
    provider_org_code,
    period,

    -- attendances: type1/2/other plus booked (coalesced to 0 so pre-Aug-2020
    -- months, where booked_* is genuinely NULL, still sum correctly)
    (attendances_type1 + attendances_type2 + attendances_other
        + coalesce(attendances_booked_type1, 0)
        + coalesce(attendances_booked_type2, 0)
        + coalesce(attendances_booked_other, 0))            as total_attendances,

    (over4hr_type1 + over4hr_type2 + over4hr_other
        + coalesce(over4hr_booked_type1, 0)
        + coalesce(over4hr_booked_type2, 0)
        + coalesce(over4hr_booked_other, 0))                as total_over4hr,

    waited_4to12hr_dta,
    waited_12hr_plus_dta,                                    -- corridor-care proxy: DTA-to-admission waits of 12+ hrs

    (emergency_admissions_type1 + emergency_admissions_type2
        + emergency_admissions_other + other_emergency_admissions) as total_emergency_admissions,

    case when (attendances_type1 + attendances_type2 + attendances_other
                + coalesce(attendances_booked_type1, 0)
                + coalesce(attendances_booked_type2, 0)
                + coalesce(attendances_booked_other, 0)) > 0
         then round(
                1.0 - (over4hr_type1 + over4hr_type2 + over4hr_other
                        + coalesce(over4hr_booked_type1, 0)
                        + coalesce(over4hr_booked_type2, 0)
                        + coalesce(over4hr_booked_other, 0))::numeric
                      / (attendances_type1 + attendances_type2 + attendances_other
                        + coalesce(attendances_booked_type1, 0)
                        + coalesce(attendances_booked_type2, 0)
                        + coalesce(attendances_booked_other, 0)),
                4)
         else null end                                       as pct_seen_within_4hr

from base;

alter table fact_ae_provider_month
    add primary key (provider_org_code, period);
