-- Monte Carlo weight-sensitivity outputs for the pressure index. Built by
-- scripts/pressure_index_sensitivity.py (2,000-iteration bootstrap resample
-- of the 11,913 complete-case rows, refitting StandardScaler+PCA(1) each
-- time). See that script's header and docs/STATUS.md for the full method.
--
-- Headline result (2026-08-08): dm01_breach's negative PC1 loading (flagged
-- as a real, not-yet-tested finding when the index was first built) is
-- negative in 98.8% of resamples — a stable, repeatable pattern, not
-- sampling noise. Provider-level pressure RANKING is extremely stable under
-- weight resampling (mean Spearman rho 0.9985 vs. baseline, worst single
-- resample 0.986) even though PC1 only explains ~32% of the six signals'
-- variance — i.e. the low explained-variance caveat matters much more for
-- trusting the exact composite SCORE than for trusting relative rankings
-- between providers.

create table if not exists ref_pressure_index_weight_sensitivity (
    feature                    text primary key,
    point_estimate              double,   -- original single-fit loading, from build_pressure_index.py
    boot_mean                   double,   -- mean loading across 2,000 bootstrap resamples
    boot_std                    double,
    ci_low_p5                   double,   -- 5th percentile of the bootstrap loading distribution
    ci_high_p95                 double,   -- 95th percentile
    pct_bootstrap_negative      double,   -- share of resamples where this loading was negative
    pct_bootstrap_positive      double,
    sign_stable                 boolean   -- true if >=95% of resamples agree on sign
);

create table if not exists ref_pressure_index_rank_stability (
    n_bootstrap                 integer,
    mean_rank_correlation       double,   -- mean Spearman rho, bootstrap provider ranking vs. baseline
    std_rank_correlation        double,
    p5_rank_correlation         double,
    p95_rank_correlation        double,
    min_rank_correlation        double
);
