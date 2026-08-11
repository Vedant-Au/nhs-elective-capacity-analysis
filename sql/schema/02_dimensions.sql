-- Dimension tables. Deliberately thin for now — enough to join the fact
-- table cleanly, not trying to pre-build every attribute Phase 2+ might
-- eventually want (deprivation join, workforce join etc. land later once
-- those sources are actually pulled and I know what keys they use).

create table if not exists dim_provider (
    provider_org_code    text primary key,          -- ODS code, e.g. 'REM'
    provider_org_name    text not null,
    provider_type        text not null,              -- acute | specialist | mental_health | independent_sector
    icb_code              text,                       -- 'QYG' for NHS Cheshire and Merseyside — confirmed 2026-08-07 from the DM01 extract's Provider Parent Org Code column (RTT only carries the full name, not the short code, for provider_parent)
    icb_name              text,
    in_core_analysis      boolean not null default true
    -- in_core_analysis = false for independent-sector / non-acute providers that
    -- appear in the RTT extract (they do NHS-funded elective work and should stay
    -- in the raw warehouse) but that the Phase 4 capacity model treats separately
    -- from the ICB's own trusts, since "additional outsourced capacity" as a lever
    -- literally means routing more volume to these providers — folding them into
    -- the same baseline would double-count the intervention.
);

comment on table dim_provider is
    'Seeded from sql/reference/cheshire_merseyside_providers.csv, which was built by '
    'grepping the actual Mar-2026 RTT extract for Provider Parent Name = NHS Cheshire '
    'and Merseyside ICB, not from a web search of "member trusts" pages (those turned '
    'out to list the whole North West region, not just this ICB, and can''t be trusted '
    'as a source of truth for who actually reports RTT data under this ICB).';

create table if not exists dim_treatment_function (
    treatment_function_code    text primary key,     -- e.g. 'C_100'
    treatment_function_name    text not null,
    specialty_group             text                  -- surgical / medical / diagnostic-adjacent etc. — TODO Phase 2, needs a manual mapping, NHS doesn't publish one
);

create table if not exists dim_date (
    period_month    date primary key,                 -- first of month, e.g. 2026-03-01
    period_label    text not null,                     -- 'RTT-March-2026', matches stg_rtt_raw.period for joining
    fiscal_year     text not null,                      -- '2025-26'
    calendar_year   integer not null,
    calendar_month  integer not null
);

-- Added 2026-08-07 alongside the DM01 pull. The 15 diagnostic test codes are
-- a closed, stable set (confirmed identical across Apr-2019, Jan-2021 and
-- Mar-2026 — NHS hasn't added or renamed a modality in 7 years of this
-- collection), so this is safe to hardcode rather than derive dynamically
-- from stg_dm01_raw. category is a manual grouping for Phase 2 (e.g. rolling
-- up MRI/CT/NON_OBSTETRIC_ULTRASOUND into "imaging" for the pressure index) —
-- NHS doesn't publish this grouping, it's an analytical judgment call, not
-- sourced from anywhere.
create table if not exists dim_diagnostic_test (
    diagnostic_test_code    text primary key,     -- e.g. 'MRI', matches stg_dm01_raw.diagnostic_test_code, excludes the 'TOTAL' pseudo-row
    diagnostic_test_name    text not null,
    sort_order               integer not null,     -- NHS's own publication order, 1-15
    category                 text                   -- imaging | physiological_measurement | endoscopy — TODO Phase 2, manual mapping
);

insert into dim_diagnostic_test (diagnostic_test_code, diagnostic_test_name, sort_order, category) values
    ('MRI',                        'Magnetic Resonance Imaging',        1,  'imaging'),
    ('CT',                         'Computed Tomography',               2,  'imaging'),
    ('NON_OBSTETRIC_ULTRASOUND',   'Non-obstetric Ultrasound',          3,  'imaging'),
    ('BARIUM_ENEMA',               'Barium Enema',                      4,  'imaging'),
    ('DEXA_SCAN',                  'DEXA Scan',                         5,  'imaging'),
    ('AUDIOLOGY_ASSESSMENTS',      'Audiology - Audiology Assessments', 6,  'physiological_measurement'),
    ('ECHOCARDIOGRAPHY',           'Cardiology - Echocardiography',     7,  'physiological_measurement'),
    ('ELECTROPHYSIOLOGY',          'Cardiology - Electrophysiology',    8,  'physiological_measurement'),
    ('PERIPHERAL_NEUROPHYS',       'Neurophysiology - Peripheral Neurophysiology', 9, 'physiological_measurement'),
    ('SLEEP_STUDIES',              'Respiratory Physiology - Sleep Studies',        10, 'physiological_measurement'),
    ('URODYNAMICS',                'Urodynamics - Pressures & Flows',   11, 'physiological_measurement'),
    ('COLONOSCOPY',                'Colonoscopy',                       12, 'endoscopy'),
    ('FLEXI_SIGMOIDOSCOPY',        'Flexi Sigmoidoscopy',               13, 'endoscopy'),
    ('CYSTOSCOPY',                 'Cystoscopy',                        14, 'endoscopy'),
    ('GASTROSCOPY',                'Gastroscopy',                       15, 'endoscopy')
on conflict (diagnostic_test_code) do nothing;
