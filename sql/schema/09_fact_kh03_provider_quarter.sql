-- KH03 fact table, grain (provider, quarter). Pivots stg_kh03_raw's long
-- sector rows into General & Acute-specific columns plus an all-sectors
-- total, rather than keeping four parallel sector columns for every metric.
-- G&A is what actually matters for the elective-care pressure index this
-- warehouse is being built for (Maternity/Mental Illness/Learning
-- Disability beds don't compete with the same elective waiting list), so
-- it gets first-class columns; the other three sectors are folded into
-- the _total columns for context (e.g. spotting a trust that's converted
-- G&A capacity to another sector) without a column explosion.

drop table if exists fact_kh03_provider_quarter;

create table fact_kh03_provider_quarter as
with pivoted as (
    select
        provider_org_code,
        quarter_end_date,
        fiscal_year,

        sum(case when sector = 'General & Acute' then available_beds else 0 end) as available_ga,
        sum(case when sector = 'General & Acute' then occupied_beds else 0 end)  as occupied_ga,

        sum(available_beds) as available_total,
        sum(occupied_beds)  as occupied_total

    from stg_kh03_raw
    group by provider_org_code, quarter_end_date, fiscal_year
)
select
    *,
    case when available_ga > 0 then round(occupied_ga / available_ga, 4) else null end as pct_occupied_ga,
    case when available_total > 0 then round(occupied_total / available_total, 4) else null end as pct_occupied_total
from pivoted;

alter table fact_kh03_provider_quarter
    add primary key (provider_org_code, quarter_end_date);
