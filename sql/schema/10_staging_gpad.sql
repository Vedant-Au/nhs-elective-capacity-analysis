-- Staging layer for GPAD (Appointments in General Practice), NHS Digital/
-- NHS England's monthly primary-care appointments publication.
--
-- Scope decision, flagged explicitly (same discipline as KH03's day-only-
-- beds deferral): this warehouse takes ONE snapshot per fiscal year (the
-- March "Summary" xlsx release) rather than all 84 monthly files. GPAD's
-- own per-month downloadable files are wildly disproportionate to every
-- other source here — the daily-counts zip alone runs 41-55MB/month, the
-- practice-level crosstab another ~20MB/month, versus A&E's ~32KB/month
-- for the same time span. GPAD's role in this build is to support the
-- "why is the system under pressure" narrative (primary-care demand as a
-- pressure valve on secondary care) rather than to feed the elective
-- pressure index directly, so an annual snapshot trend is enough — monthly
-- primary-care granularity is a Phase 2+ enhancement if the analysis later
-- needs it, not a corner cut silently.
--
-- Within each year's Summary xlsx, two tables are loaded:
--   Table 3a: appointments by status (Total/Attended/DNA/Unknown), at
--     National/Region/STP-or-ICB tier, plus practice counts.
--   Table 4: total appointment count + patient list size at the same
--     geography tiers — this is what makes an appointments-per-registered-
--     patient demand metric possible, which Table 3a alone can't give.
-- Both tables share an identical Type/NHS Area Code/ONS Code/Name geography
-- key structure across all 7 years, confirmed by inspection on 2026-08-07,
-- which is what makes a single staging table for both tables workable.
--
-- Geography identity is NOT stable across this window and that had to be
-- handled explicitly rather than assumed:
--   - NHS Cheshire and Merseyside ICB (QYG) was formed 1 Jul 2022 from the
--     "Cheshire and Merseyside STP", which itself existed from ~2020. The
--     ONS code (E54000008) is the ONE identifier that stays constant across
--     the entire FY19-20-FY25-26 window — the "NHS Area Code" column is
--     NOT: the March 2020 file carries 'E54000008' in the NHS Area Code
--     column too (not yet assigned the QYG letter-code), while March 2021
--     onwards uses 'QYG'. The "Type" label also changes (Regional Local
--     Office / STP pre-2022, ICB from 2022-23). None of this is a data
--     error — it's the real organisational history of the geography, and
--     ons_code is what this warehouse joins and trends on rather than
--     nhs_area_code or the type label.
--   - Sub-ICB-level and CCG-level rows are NOT loaded here — pre-2022 files
--     only go down to CCG (which don't map 1:1 onto today's Sub ICB
--     Locations), and loading both tiers doubles the reconciliation work
--     for a level of granularity this build doesn't currently need at the
--     GPAD layer (Sub-ICB granularity already exists via KH03/DM01/A&E's
--     provider-level data). Scoped to National / Region / STP-or-ICB tier
--     only, identified by ons_code prefix (ENG / E40xxxxxx / E54xxxxxx)
--     rather than by the type label text, since the label text is exactly
--     the thing that isn't stable across years.

create table if not exists stg_gpad_raw (
    fiscal_year           text not null,     -- '2019-20' etc — always the March snapshot of that FY
    period_end_date        date not null,     -- 31 March of the relevant calendar year

    source_table            text not null,     -- 'Table 3a' | 'Table 4'
    geog_type_raw           text not null,     -- as published: 'National' | 'Region' | 'Regional Local Office' | 'STP' | 'ICB'
    nhs_area_code           text,               -- as published — NOT stable pre-2021, see header note
    ons_code                text not null,     -- stable join key across the full window
    geog_name               text not null,

    open_active_practices   integer,            -- Table 3a only
    included_practices      integer,            -- Table 3a only

    appointments_total      numeric,            -- both tables carry this, cross-checked at load time
    appointments_attended   numeric,            -- Table 3a only
    appointments_dna        numeric,            -- Table 3a only
    appointments_unknown    numeric,            -- Table 3a only

    patient_list_size       numeric,            -- Table 4 only

    source_file              text,
    loaded_at                 timestamp default now()
);

create index if not exists idx_stg_gpad_ons on stg_gpad_raw (ons_code);
create index if not exists idx_stg_gpad_fy on stg_gpad_raw (fiscal_year);
