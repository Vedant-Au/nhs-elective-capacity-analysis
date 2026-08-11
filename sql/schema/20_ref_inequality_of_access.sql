-- Inequality-of-access cross-reference: pressure index and workforce
-- staffing intensity against this ICB's IMD 2019 deprivation gradient.
-- Built by scripts/inequality_of_access.py. Workforce and IMD are
-- CONTEXTUAL overlays per the charter's confirmed design (cross-referenced
-- as findings, never blended into the pressure index formula itself).
--
-- COLUMN NOTE, learned the hard way while building this (caught before
-- trusting the first result, not after — see script header): use
-- imd_rank_of_avg_rank / health_rank_of_avg_rank from
-- dim_imd2019_local_authority (LA's own rank out of 151, 1 = most
-- deprived), NOT imd_avg_rank / health_avg_rank (the raw population-
-- weighted average of LSOA-level ranks out of 32,844 LSOAs — a much larger,
-- not-directly-comparable number). This table's own imd_avg_rank /
-- health_avg_rank columns already carry the CORRECT (1-151) values, aliased
-- during the join specifically to avoid this trap recurring downstream.
--
-- HONEST FINDING, both parts needed to not overstate it: across all 12 core
-- providers, deprivation rank and mean_pressure_index correlate positively
-- (rho=+0.49, i.e. LESS-deprived areas show somewhat HIGHER pressure in
-- this data — the opposite of the naive "deprivation = worse access"
-- assumption) but NOT significantly (p=0.108) and with a wide bootstrap CI.
-- Once the 5 regional specialist centres (RBQ/RBS/REN/REP/RET — whose
-- single-LA assignment is known to understate their real, ICB-wide
-- catchment, per dim_provider_local_authority's own caveat) are excluded,
-- the correlation drops to rho=+0.31 (p=0.53) with a CI spanning strongly
-- negative to strongly positive. Same pattern on consultants_per_1000_fte
-- vs deprivation. Read this as: the apparent relationship in the raw data
-- is largely an artifact of Liverpool (this ICB's most-deprived LA)
-- happening to host most of the specialist tertiary centres, not a real
-- deprivation-pressure or deprivation-staffing effect — and even setting
-- that aside, n=12 (or n=7) is too small to draw a confident conclusion
-- either way. This is the honest state of the evidence, not an
-- inconclusive placeholder to firm up later.

create table if not exists ref_inequality_provider_deprivation (
    provider_org_code       text primary key,
    la_code                   text,
    la_name                    text,
    catchment_caveat            text,
    is_specialist_centre         boolean,
    imd_avg_rank                  integer,  -- LA's own IMD rank out of 151 (1 = most deprived) -- see column note above
    imd_avg_score                  double,
    health_avg_rank                 integer,  -- LA's own Health domain rank out of 151
    health_avg_score                  double,
    mean_pressure_index                 double,   -- mean across all months in fact_elective_pressure_index...
    mean_rtt_over18_share                 double,
    mean_rtt_growth                         double,
    consultants_per_1000_fte                  double,   -- most recent fiscal year available
    total_fte                                   double,
    fiscal_year                                   text
);

create table if not exists ref_inequality_correlations (
    subset                text,     -- 'all_12_core_providers' or 'excl_5_specialist_centres_n7'
    independent_var         text,     -- 'imd_avg_rank' or 'health_avg_rank'
    outcome                   text,     -- 'mean_pressure_index', 'mean_rtt_over18_share', or 'consultants_per_1000_fte'
    n                           integer,
    rho                          double,   -- Spearman rank correlation, point estimate
    p_value                        double,
    boot_ci_low_p5                   double,   -- 5,000-iteration Monte Carlo bootstrap CI
    boot_ci_high_p95                   double,
    boot_mean                            double
);
