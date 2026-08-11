-- Provider-to-local-authority mapping, seeded from
-- sql/reference/provider_local_authority.csv. A deliberate, documented
-- single-site simplification, not a claim about true patient-flow
-- catchments — see scripts/load_imd.py's header comment (written before
-- this table existed) for why this wasn't baked into the IMD loader
-- itself. Every specialist trust (RBQ/RBS/REN/REP/RET) and the mental
-- health trust (RW4) in particular draws from well beyond its single
-- assigned LA — that's flagged per-row in catchment_caveat rather than
-- pretending the mapping is more precise than it is. Exists specifically
-- to let the inequality-of-access analysis join RTT/DM01/A&E/KH03 fact
-- tables (keyed on provider_org_code) through to
-- dim_imd2019_local_authority (keyed on la_code) — a join this warehouse
-- had no path for until now.

create table if not exists dim_provider_local_authority (
    provider_org_code    text primary key,
    provider_org_name    text not null,
    primary_site_name    text not null,
    la_code               text not null references dim_imd2019_local_authority(la_code),
    la_name               text not null,
    catchment_caveat      text    -- non-null wherever the single-LA assignment materially understates the true catchment
);
