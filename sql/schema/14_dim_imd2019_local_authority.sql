-- IMD 2019 reference table, Cheshire and Merseyside's 9 upper-tier local
-- authorities. A dimension table, not a fact table — IMD 2019 is a single
-- point-in-time publication (26 Sep 2019), not a time series like every
-- other source in this warehouse, so there's no fiscal_year grain here.
-- See scripts/load_imd.py header for the full scope rationale (upper-tier
-- LA grain rather than LSOA, IMD + Health domain only rather than all 9
-- domains, and why provider-to-LA mapping is deliberately NOT done here).
--
-- Rank columns are national ranks out of 151 upper-tier local authorities
-- in England — rank 1 is the MOST deprived, not the least (this trips
-- people up, so it's called out here rather than left implicit). Score
-- columns are the underlying continuous measure the ranks are derived
-- from; average_rank/average_score summarise across an LA's constituent
-- LSOAs (population-weighted), not just its single worst or best area.
--
-- Confirms the charter's own rationale for choosing this ICB: Liverpool
-- and Knowsley sit at ranks 3-4 (out of 151, most deprived end) on both
-- overall IMD and the Health domain specifically, while Cheshire East and
-- Cheshire West and Chester sit at ranks 106-131 (least deprived end) —
-- a genuine, stark within-ICB contrast, not a marginal one.

create table if not exists dim_imd2019_local_authority (
    la_code                                       text primary key,   -- 2019 ONS code, e.g. 'E08000012' (Liverpool)
    la_name                                        text not null,

    imd_avg_rank                                    numeric,             -- overall IMD, population-weighted average rank across LSOAs in this LA
    imd_rank_of_avg_rank                             integer,             -- 1 = most deprived of 151 upper-tier LAs nationally
    imd_avg_score                                    numeric,
    imd_rank_of_avg_score                             integer,
    imd_pct_lsoas_most_deprived_decile                 numeric,             -- share of this LA's LSOAs in the most-deprived 10% nationally
    imd_rank_of_pct_most_deprived_decile                integer,

    health_avg_rank                                  numeric,             -- Health Deprivation and Disability domain specifically
    health_rank_of_avg_rank                           integer,
    health_avg_score                                  numeric,
    health_rank_of_avg_score                           integer,
    health_pct_lsoas_most_deprived_decile               numeric,
    health_rank_of_pct_most_deprived_decile              integer,

    source_file                                        text,
    loaded_at                                            timestamp default now()
);
