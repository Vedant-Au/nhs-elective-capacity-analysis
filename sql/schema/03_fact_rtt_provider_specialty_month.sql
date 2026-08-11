-- Core RTT fact table at the provider-specialty-month grain the charter
-- specifies. Built by aggregating stg_rtt_raw across commissioners (the fact
-- table doesn't care which ICB/GP practice referred the patient, only which
-- provider treated them and in what specialty) and pivoting the five RTT
-- part types into named measures.
--
-- Part-type mapping (confirmed against RTT Part Description in the actual
-- source file, not assumed from memory):
--   Part_1A  -> completed pathways, admitted
--   Part_1B  -> completed pathways, non-admitted
--   Part_2   -> incomplete pathways (the waiting list itself)
--   Part_2A  -> incomplete pathways with a decision to admit already made
--   Part_3   -> new RTT clock starts in the month

drop table if exists fact_rtt_provider_specialty_month;

create table fact_rtt_provider_specialty_month as
with base as (
    select
        provider_org_code,
        treatment_function_code,
        period,
        rtt_part_type,
        total_all,
        -- 18-week and 52-week thresholds computed off the raw band columns
        -- rather than trusting a pre-summed column, because there isn't one
        -- in the source for these specific cut-points — NHS publishes the
        -- full distribution and expects you to sum the bands you care about.
        (wk_18+wk_19+wk_20+wk_21+wk_22+wk_23+wk_24+wk_25+wk_26+wk_27+wk_28+wk_29
         +wk_30+wk_31+wk_32+wk_33+wk_34+wk_35+wk_36+wk_37+wk_38+wk_39+wk_40+wk_41
         +wk_42+wk_43+wk_44+wk_45+wk_46+wk_47+wk_48+wk_49+wk_50+wk_51+wk_52+wk_53
         +wk_54+wk_55+wk_56+wk_57+wk_58+wk_59+wk_60+wk_61+wk_62+wk_63+wk_64+wk_65
         +wk_66+wk_67+wk_68+wk_69+wk_70+wk_71+wk_72+wk_73+wk_74+wk_75+wk_76+wk_77
         +wk_78+wk_79+wk_80+wk_81+wk_82+wk_83+wk_84+wk_85+wk_86+wk_87+wk_88+wk_89
         +wk_90+wk_91+wk_92+wk_93+wk_94+wk_95+wk_96+wk_97+wk_98+wk_99+wk_100+wk_101
         +wk_102+wk_103+wk_104_plus) as over_18wk,
        (wk_52+wk_53+wk_54+wk_55+wk_56+wk_57+wk_58+wk_59+wk_60+wk_61+wk_62+wk_63
         +wk_64+wk_65+wk_66+wk_67+wk_68+wk_69+wk_70+wk_71+wk_72+wk_73+wk_74+wk_75
         +wk_76+wk_77+wk_78+wk_79+wk_80+wk_81+wk_82+wk_83+wk_84+wk_85+wk_86+wk_87
         +wk_88+wk_89+wk_90+wk_91+wk_92+wk_93+wk_94+wk_95+wk_96+wk_97+wk_98+wk_99
         +wk_100+wk_101+wk_102+wk_103+wk_104_plus) as over_52wk
    from stg_rtt_raw
)
, agg as (
    select
        provider_org_code,
        treatment_function_code,
        period,

        sum(total_all) filter (where rtt_part_type = 'Part_2')                       as waiting_list_size,
        sum(over_18wk) filter (where rtt_part_type = 'Part_2')                       as waiting_list_over_18wk,
        sum(over_52wk) filter (where rtt_part_type = 'Part_2')                       as waiting_list_over_52wk,

        sum(total_all) filter (where rtt_part_type = 'Part_1A')                      as completed_admitted,
        sum(total_all) filter (where rtt_part_type = 'Part_1B')                      as completed_nonadmitted,
        coalesce(sum(total_all) filter (where rtt_part_type = 'Part_1A'), 0)
          + coalesce(sum(total_all) filter (where rtt_part_type = 'Part_1B'), 0)     as completed_pathways_total,

        sum(total_all) filter (where rtt_part_type = 'Part_3')                       as new_pathways_started

    from base
    group by provider_org_code, treatment_function_code, period
)
-- long_wait_share computed inline rather than as an ALTER TABLE ... GENERATED
-- column: Postgres supports stored generated columns added after the fact,
-- DuckDB (what this was actually validated against — see docs/STATUS.md)
-- doesn't yet. Computing it in the same SELECT is portable across both and
-- is honestly clearer to read than chasing it down in a separate ALTER
-- further down the file.
select
    *,
    case when waiting_list_size > 0
         then round(waiting_list_over_18wk::numeric / waiting_list_size, 4)
         else null end as long_wait_share_18wk
from agg;

alter table fact_rtt_provider_specialty_month
    add primary key (provider_org_code, treatment_function_code, period);

-- NOTE (2026-08-07): no median wait time column here on purpose. NHS
-- publishes a true patient-level median separately (not derivable from these
-- banded aggregates without assuming a distribution within each band), and a
-- band-midpoint approximation would look precise without being accurate —
-- exactly the kind of false confidence the charter's risk log flags. If a
-- median proxy turns out to be genuinely needed for the pressure index in
-- Phase 2, it goes in as a clearly-labelled estimate, not silently as
-- "median_wait_weeks".
