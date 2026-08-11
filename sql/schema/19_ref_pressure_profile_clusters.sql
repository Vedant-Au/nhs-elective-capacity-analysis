-- Provider-specialty pressure-profile clusters. Built by
-- scripts/cluster_pressure_profiles.py: each of the 172 provider-specialty
-- combinations reporting in this warehouse gets ONE row, its pressure-index
-- input signals averaged across all months it appears in, then KMeans-
-- clustered on those (standardized) averages. k=4 chosen by silhouette
-- score across k=2..8 (statistically derived, not asserted).
--
-- HONEST CAVEAT, front and centre rather than buried: the resulting split
-- is heavily imbalanced (135 of 172 series in one large "no strongly
-- distinguishing feature" middle cluster, 31 in a genuinely low-pressure
-- cluster, and two tiny outlier clusters of 5 and 1) and Monte Carlo
-- resampling (1,000 bootstrap iterations, Adjusted Rand Index vs. the
-- baseline clustering) shows only MODERATE stability: mean ARI 0.46,
-- ranging 0.13-0.97 across resamples. Read this as: most provider-
-- specialty series don't segment into clean, stable bands on these six
-- signals — pressure is fairly continuous across the bulk of them, with a
-- handful of genuine, robust outliers (the low-pressure cluster and the
-- single-series extreme cluster are the parts of this result worth relying
-- on; the boundary within the large middle cluster is not).

create table if not exists ref_pressure_profile_clusters (
    provider_org_code        text    not null,
    treatment_function_code   text    not null,
    n_months                   integer,           -- how many of the 84 months this series had a complete-case row
    cluster                     integer,
    pressure_index_0_100        double,            -- mean across the series' months, label only, not a clustering input
    rtt_growth                   double,            -- means of the 6 clustering input features, unstandardized
    rtt_over18_share              double,
    rtt_over52_share              double,
    dm01_breach                   double,
    ae_pressure                   double,
    kh03_occupancy                double,
    primary key (provider_org_code, treatment_function_code)
);

create table if not exists ref_pressure_cluster_centroids (
    cluster              integer primary key,
    n_series              integer,
    mean_pressure_index    double,
    rtt_growth_z            double,   -- centroid position in STANDARDIZED units, so magnitudes are comparable across features
    rtt_over18_share_z       double,
    rtt_over52_share_z       double,
    dm01_breach_z             double,
    ae_pressure_z              double,
    kh03_occupancy_z            double
);

create table if not exists ref_pressure_cluster_stability (
    k                integer,
    n_bootstrap       integer,
    mean_ari           double,
    std_ari             double,
    p5_ari               double,
    p95_ari               double
);
