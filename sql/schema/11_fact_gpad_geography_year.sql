-- GPAD fact table, grain (ons_code, fiscal_year) — one row per National/
-- Region/STP-or-ICB geography per fiscal year (March snapshot only, see
-- 10_staging_gpad.sql header for the annual-vs-monthly scope decision).
--
-- Joins Table 3a and Table 4's staged rows back together on (ons_code,
-- fiscal_year) rather than keeping them as two separate fact tables, since
-- every downstream use of this data wants both the status breakdown and
-- the patient-list-size-normalised demand rate together. Table 3a and
-- Table 4's own appointments_total figures are cross-checked at the join
-- (both tables independently publish a total appointment count for the
-- same geography-month) rather than assumed to agree — see the sanity
-- check in scripts/load_gpad.py / STATUS.md for the result of that check.
--
-- appointments_per_1000_patients is the headline demand-pressure metric
-- this table exists to produce: patient list size is the closest thing
-- GPAD has to a population denominator, so appointments per registered
-- patient (scaled per 1,000) is a fairer way to compare Cheshire and
-- Merseyside's primary-care demand against other ICBs or against its own
-- trend than a raw appointment count would be, given list sizes differ
-- substantially by geography and grow over time.

drop table if exists fact_gpad_geography_year;

create table fact_gpad_geography_year as
select
    coalesce(t3.ons_code, t4.ons_code)             as ons_code,
    coalesce(t3.fiscal_year, t4.fiscal_year)         as fiscal_year,
    coalesce(t3.period_end_date, t4.period_end_date) as period_end_date,
    coalesce(t3.geog_type_raw, t4.geog_type_raw)     as geog_type_raw,
    coalesce(t3.geog_name, t4.geog_name)             as geog_name,

    t3.open_active_practices,
    t3.included_practices,

    t3.appointments_total          as appointments_total_t3a,
    t4.appointments_total          as appointments_total_t4,
    -- the two source tables should agree on total appointments for the same
    -- geography-month; where they don't (or one side is missing), prefer
    -- Table 3a since it's the more detailed source and flag the mismatch
    -- via appointments_total_mismatch rather than silently picking one
    coalesce(t3.appointments_total, t4.appointments_total) as appointments_total,
    case when t3.appointments_total is not null
              and t4.appointments_total is not null
              and t3.appointments_total <> t4.appointments_total
         then true else false end  as appointments_total_mismatch,

    t3.appointments_attended,
    t3.appointments_dna,
    t3.appointments_unknown,
    case when t3.appointments_total > 0
         then round(t3.appointments_attended / t3.appointments_total, 4)
         else null end             as pct_attended,
    case when t3.appointments_total > 0
         then round(t3.appointments_dna / t3.appointments_total, 4)
         else null end             as pct_dna,

    t4.patient_list_size,
    case when t4.patient_list_size > 0
         then round(1000.0 * coalesce(t3.appointments_total, t4.appointments_total) / t4.patient_list_size, 2)
         else null end             as appointments_per_1000_patients

from (select * from stg_gpad_raw where source_table = 'Table 3a') t3
full outer join (select * from stg_gpad_raw where source_table = 'Table 4') t4
    on t3.ons_code = t4.ons_code and t3.fiscal_year = t4.fiscal_year;

alter table fact_gpad_geography_year
    add primary key (ons_code, fiscal_year);
