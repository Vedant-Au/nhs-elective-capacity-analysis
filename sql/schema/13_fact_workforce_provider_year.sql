-- Workforce fact table, grain (provider_org_code, fiscal_year). Nothing to
-- pivot or reconcile here unlike KH03/GPAD — stg_workforce_raw is already
-- one row per provider per year, so this table mainly adds the derived
-- ratios that make workforce numbers comparable across trusts of very
-- different sizes: consultants and scientific/therapeutic/technical FTE
-- per 1,000 total FTE, which is what actually lets you ask "is this trust
-- relatively thin on the specialist staff elective/diagnostic capacity
-- depends on" rather than just "is this trust big or small".

drop table if exists fact_workforce_provider_year;

create table fact_workforce_provider_year as
select
    provider_org_code,
    provider_org_name,
    fiscal_year,
    period_end_date,

    total_fte,
    prof_qual_clinical_fte,
    hchs_doctors_fte,
    consultant_fte,
    nurses_health_visitors_fte,
    scientific_therapeutic_technical_fte,

    case when total_fte > 0 then round(1000.0 * consultant_fte / total_fte, 2) else null end
        as consultants_per_1000_fte,
    case when total_fte > 0 then round(1000.0 * scientific_therapeutic_technical_fte / total_fte, 2) else null end
        as scitech_per_1000_fte,
    case when total_fte > 0 then round(prof_qual_clinical_fte / total_fte, 4) else null end
        as pct_clinical_fte

from stg_workforce_raw;

alter table fact_workforce_provider_year
    add primary key (provider_org_code, fiscal_year);
