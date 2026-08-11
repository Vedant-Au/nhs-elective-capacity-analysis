-- Staging layer for RTT Full CSV extracts.
-- Source: NHS England "Full CSV data file" (one zip per month), confirmed
-- against the actual Mar-2026 and Mar-2022 files on 2026-08-07 — 121 columns,
-- Period/Provider/Commissioner/Part-Type/Treatment-Function keys, then 106
-- weekly wait-band columns (Gt 00 To 01 Weeks ... Gt 104 Weeks), then
-- Total / Patients with unknown clock start date / Total All.
--
-- Loading straight into a 121-column table and unpivoting in SQL, rather than
-- unpivoting in Python before load, so the raw extract is queryable as-is if
-- something downstream looks wrong and I need to check against the source.

create table if not exists stg_rtt_raw (
    period                              text not null,   -- e.g. 'RTT-March-2026'
    provider_parent_org_code            text,             -- ICB the provider sits under
    provider_parent_name                text,
    provider_org_code                   text not null,    -- ODS code, e.g. 'REM'
    provider_org_name                   text,
    commissioner_parent_org_code        text,
    commissioner_parent_name            text,
    commissioner_org_code               text,
    commissioner_org_name               text,
    rtt_part_type                       text not null,    -- Part_1A / Part_1B / Part_2 / Part_2A / Part_3
    rtt_part_description                text,             -- human-readable version of the above
    treatment_function_code             text not null,    -- e.g. 'C_100'
    treatment_function_name             text,

    -- 106 weekly bands, Gt 00 To 01 through Gt 104 Weeks (last one has no
    -- upper bound). Named wk_00, wk_01 ... wk_104 rather than keeping the
    -- source's spaced-out column names — Postgres would need every reference
    -- quoted otherwise, which gets unreadable fast across 106 columns.
    wk_00 integer, wk_01 integer, wk_02 integer, wk_03 integer, wk_04 integer,
    wk_05 integer, wk_06 integer, wk_07 integer, wk_08 integer, wk_09 integer,
    wk_10 integer, wk_11 integer, wk_12 integer, wk_13 integer, wk_14 integer,
    wk_15 integer, wk_16 integer, wk_17 integer, wk_18 integer, wk_19 integer,
    wk_20 integer, wk_21 integer, wk_22 integer, wk_23 integer, wk_24 integer,
    wk_25 integer, wk_26 integer, wk_27 integer, wk_28 integer, wk_29 integer,
    wk_30 integer, wk_31 integer, wk_32 integer, wk_33 integer, wk_34 integer,
    wk_35 integer, wk_36 integer, wk_37 integer, wk_38 integer, wk_39 integer,
    wk_40 integer, wk_41 integer, wk_42 integer, wk_43 integer, wk_44 integer,
    wk_45 integer, wk_46 integer, wk_47 integer, wk_48 integer, wk_49 integer,
    wk_50 integer, wk_51 integer, wk_52 integer, wk_53 integer, wk_54 integer,
    wk_55 integer, wk_56 integer, wk_57 integer, wk_58 integer, wk_59 integer,
    wk_60 integer, wk_61 integer, wk_62 integer, wk_63 integer, wk_64 integer,
    wk_65 integer, wk_66 integer, wk_67 integer, wk_68 integer, wk_69 integer,
    wk_70 integer, wk_71 integer, wk_72 integer, wk_73 integer, wk_74 integer,
    wk_75 integer, wk_76 integer, wk_77 integer, wk_78 integer, wk_79 integer,
    wk_80 integer, wk_81 integer, wk_82 integer, wk_83 integer, wk_84 integer,
    wk_85 integer, wk_86 integer, wk_87 integer, wk_88 integer, wk_89 integer,
    wk_90 integer, wk_91 integer, wk_92 integer, wk_93 integer, wk_94 integer,
    wk_95 integer, wk_96 integer, wk_97 integer, wk_98 integer, wk_99 integer,
    wk_100 integer, wk_101 integer, wk_102 integer, wk_103 integer,
    wk_104_plus integer,                -- 'Gt 104 Weeks' — no upper bound, the long-wait tail

    total                                integer,
    unknown_clock_start                 integer,          -- 'Patients with unknown clock start date'
    total_all                           integer,

    source_file                         text,             -- which zip this row came from, for traceability
    loaded_at                           timestamp default now()
);

-- one row per (period, provider, commissioner, part type, treatment function)
-- in the source — this is the natural key, used for load idempotency (delete
-- + reload by period rather than upsert, since NHS republishes whole months
-- on revision rather than patching individual rows)
create index if not exists idx_stg_rtt_period on stg_rtt_raw (period);
create index if not exists idx_stg_rtt_provider on stg_rtt_raw (provider_org_code);


-- Unpivoted long view. 106 columns -> 106 rows per source row is a lot of
-- expansion (the Mar-2026 file alone is ~184k source rows -> ~19.5M long
-- rows), so this stays a view rather than a materialized table until Phase 2
-- actually needs band-level granularity for something. Most of the warehouse
-- fact table below only needs a handful of derived aggregates (18wk, 52wk,
-- total), which can be computed straight off stg_rtt_raw without unpivoting
-- at all — this view exists for the cases where true band-level detail is
-- worth the row explosion (e.g. building the >52-week long-wait tail curve
-- for Tableau).
create or replace view stg_rtt_long as
select period, provider_org_code, provider_org_name,
       commissioner_org_code, commissioner_org_name,
       rtt_part_type, rtt_part_description,
       treatment_function_code, treatment_function_name,
       band, patient_count
from stg_rtt_raw
cross join lateral (
    values
        ('00', wk_00), ('01', wk_01), ('02', wk_02), ('03', wk_03), ('04', wk_04),
        ('05', wk_05), ('06', wk_06), ('07', wk_07), ('08', wk_08), ('09', wk_09),
        ('10', wk_10), ('11', wk_11), ('12', wk_12), ('13', wk_13), ('14', wk_14),
        ('15', wk_15), ('16', wk_16), ('17', wk_17), ('18', wk_18), ('19', wk_19),
        ('20', wk_20), ('21', wk_21), ('22', wk_22), ('23', wk_23), ('24', wk_24),
        ('25', wk_25), ('26', wk_26), ('27', wk_27), ('28', wk_28), ('29', wk_29),
        ('30', wk_30), ('31', wk_31), ('32', wk_32), ('33', wk_33), ('34', wk_34),
        ('35', wk_35), ('36', wk_36), ('37', wk_37), ('38', wk_38), ('39', wk_39),
        ('40', wk_40), ('41', wk_41), ('42', wk_42), ('43', wk_43), ('44', wk_44),
        ('45', wk_45), ('46', wk_46), ('47', wk_47), ('48', wk_48), ('49', wk_49),
        ('50', wk_50), ('51', wk_51), ('52', wk_52), ('53', wk_53), ('54', wk_54),
        ('55', wk_55), ('56', wk_56), ('57', wk_57), ('58', wk_58), ('59', wk_59),
        ('60', wk_60), ('61', wk_61), ('62', wk_62), ('63', wk_63), ('64', wk_64),
        ('65', wk_65), ('66', wk_66), ('67', wk_67), ('68', wk_68), ('69', wk_69),
        ('70', wk_70), ('71', wk_71), ('72', wk_72), ('73', wk_73), ('74', wk_74),
        ('75', wk_75), ('76', wk_76), ('77', wk_77), ('78', wk_78), ('79', wk_79),
        ('80', wk_80), ('81', wk_81), ('82', wk_82), ('83', wk_83), ('84', wk_84),
        ('85', wk_85), ('86', wk_86), ('87', wk_87), ('88', wk_88), ('89', wk_89),
        ('90', wk_90), ('91', wk_91), ('92', wk_92), ('93', wk_93), ('94', wk_94),
        ('95', wk_95), ('96', wk_96), ('97', wk_97), ('98', wk_98), ('99', wk_99),
        ('100', wk_100), ('101', wk_101), ('102', wk_102), ('103', wk_103),
        ('104+', wk_104_plus)
) as bands(band, patient_count)
where patient_count is not null and patient_count <> 0;  -- most cells are 0; skip them, no analytical value and it's most of the row explosion
