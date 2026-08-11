-- Elective pressure index, grain (provider, treatment_function/specialty, month).
-- Built by scripts/build_pressure_index.py (this file documents the resulting
-- shape; the Python script is the one that actually creates and populates it,
-- same division of labour as KH03/GPAD/Workforce/IMD elsewhere in this
-- warehouse — SQL DDL as the readable contract, Python where procedural work
-- was unavoidable).
--
-- WHY PCA, NOT FIXED WEIGHTS: Vedant's explicit call (continuation session,
-- 2026-08) was to derive the six input signals' weights statistically rather
-- than assert them, and to defer robustness/stress-testing of those weights
-- to the later Monte Carlo / sensitivity-analysis phase rather than doing it
-- here. So: PC1 loadings on the six standardized signals below ARE the
-- weights. They are NOT yet stress-tested — that's next.
--
-- GRAIN CHOICE: provider-specialty-month, the native RTT/DM01 grain (Vedant's
-- call over the coarser provider-month alternative). Real consequence, stated
-- plainly rather than glossed: dm01_breach, ae_pressure and kh03_occupancy
-- only exist at provider-month, so every specialty within a given provider-
-- month shares an identical value for those three columns. Only rtt_growth,
-- rtt_over18_share and rtt_over52_share vary within a provider across its
-- specialties.
--
-- SCOPE: the 12 trusts with dim_provider.in_core_analysis = true (real RTT
-- elective volume). Excludes independent-sector providers and RW4 (Mersey
-- Care, mental health, negligible RTT), consistent with every prior scoping
-- decision in this project.
--
-- HONEST CAVEATS FROM THE FIRST BUILD (2026-08-08), not glossed over:
--   1. PC1 explains only ~32% of the variance across the six standardized
--      signals — this is NOT a strongly unified single factor. Treat the
--      composite score as one useful lens, not a ground truth "the" pressure
--      number, until the sensitivity phase has stress-tested it.
--   2. dm01_breach loaded NEGATIVE on PC1 (weight approx -0.10, corr with
--      PC1 approx -0.13) — i.e. in this ICB and window, DM01's 6-week
--      diagnostic breach share moves weakly AGAINST the shared pressure
--      factor the other five signals track together, not with it. Plausible
--      real-world reading: targeted diagnostic-capacity investment (e.g.
--      Community Diagnostic Centres) may have held DM01 performance up even
--      as RTT/A&E/bed pressure rose elsewhere — a genuine finding worth
--      carrying into the narrative, not a bug to silently flip the sign on.
--   3. ae_pressure is imputed (cohort mean of the other 11 core providers for
--      that month) for REN (The Clatterbridge Cancer Centre), which has no
--      A&E department. Flagged per-row via ae_pressure_imputed rather than
--      left silently blended in.
--   4. kh03_occupancy is a calendar-quarter figure applied identically to
--      all three months within that quarter (KH03 is the only quarterly-
--      cadence source among the four feeding this index).

create table if not exists fact_elective_pressure_index_provider_specialty_month (
    provider_org_code          text    not null,
    treatment_function_code    text    not null,
    period                     text    not null,   -- native RTT period label, e.g. 'RTT-APRIL-2019'
    period_month               date    not null,   -- parsed first-of-month date, for time-series joins/plotting

    waiting_list_size          bigint,              -- RTT incomplete pathways (Part_2), same source as the RTT fact table
    baseline_wl                double,              -- provider-specialty's own Apr-Jun 2019 mean waiting list (or earliest available month if that window is missing)
    rtt_growth                 double,              -- waiting_list_size / baseline_wl - 1
    rtt_over18_share           double,              -- long_wait_share_18wk, carried through from fact_rtt_provider_specialty_month
    rtt_over52_share           double,              -- waiting_list_over_52wk / waiting_list_size

    dm01_breach                double,              -- long_wait_share_6wk, provider-month, broadcast across specialties
    ae_pressure                double,              -- 1 - pct_seen_within_4hr, provider-month, broadcast across specialties
    ae_pressure_imputed        boolean,             -- true where ae_pressure is a cohort-mean imputation (REN only, see caveat 3)
    kh03_occupancy             double,              -- pct_occupied_ga, calendar-quarter value, broadcast across the 3 months in that quarter and all specialties

    pressure_index_raw         double,              -- sum(standardized_signal * pca_loading) across the 6 signals; null if any input signal is null for this row
    pressure_index_0_100       double,              -- percentile rank of pressure_index_raw across the full panel, for readability

    primary key (provider_org_code, treatment_function_code, period)
);

-- Companion metadata table: the PCA loadings actually used to build the index
-- above, so the weighting is auditable rather than buried in a script run.
create table if not exists ref_pressure_index_pca_weights (
    feature                     text    primary key,
    pca_loading                 double,
    explained_variance_ratio    double,   -- PC1's share of total variance across the 6 standardized signals (see caveat 1)
    n_fit_rows                  integer,  -- complete-case rows used to fit the PCA
    built_date                  date
);
