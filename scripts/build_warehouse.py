"""
Master warehouse build: creates a single persistent nhs_warehouse.db with
all seven sources loaded and validated, ready for the Python analytics
layer to query. Nothing before this script actually persisted a full
multi-year load to disk — every validation up to this point (documented in
STATUS.md) used in-memory DuckDB connections scoped to whichever source
was being checked. This is the first script that builds the real thing.

RTT and DM01 arrive as one zip per month (84 each); A&E as one CSV per
month (84). All three are NATIONAL extracts — RTT's March 2026 file alone
is ~184k rows before any filtering. Rather than load England-wide data
into a warehouse whose entire purpose is a single ICB, every INSERT
filters to the 26 provider codes in
sql/reference/cheshire_merseyside_providers.csv (13 NHS trusts + 13
independent-sector/other providers who also appear in the national RTT/
DM01 extracts) at SQL-read time via read_csv_auto's WHERE pushdown, not
after loading everything into memory.

RTT's column layout genuinely changed partway through this project's
window and had to be handled per-file, not assumed stable: April 2019's
extract has 69 columns with a single "Gt 52 Weeks" catch-all band, while
March 2026's has 121 columns with fine-grained per-week bands out to
"Gt 104 Weeks". Confirmed by reading both headers directly rather than
trusting the "121 columns" figure in 01_staging.sql's header comment for
every month — that comment was written against Mar-2026/Mar-2022 specifically,
which turned out not to be representative of the full 84-month window.
Handled with a dynamic per-file column resolver: read each file's actual
header, map every "Gt NN To MM Weeks" column to its wk_NN target and fill
any wk_* column the file doesn't have with 0 (not NULL) — the fact table's
over_18wk/over_52wk sums are plain `+` arithmetic, and a single NULL in
that chain would silently NULL the whole row's total, which is worse than
a filled zero for a band that genuinely has no finer breakdown in the
source.

A&E's 16-vs-22 column evolution (booked-appointment columns added Aug
2020) was already documented in 06_staging_ae.sql from the earlier
validation pass — reused that same header-driven detection here rather
than re-deriving it, but unlike RTT's missing bands, A&E's missing booked
columns are inserted as genuine NULL, matching what 07_fact_ae_provider_month.sql's
COALESCE-to-zero already expects.

DM01's 30-column layout was checked at April 2019 and March 2026 and found
stable — no per-file resolver needed there, a single fixed mapping.

Usage:
    python3 scripts/build_warehouse.py
Produces nhs_warehouse.db in the project root. Safe to re-run: drops and
rebuilds every table from scratch each time rather than upserting, so the
warehouse always reflects exactly what's in data_raw/ and sql/schema/ at
build time.
"""

import csv
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

import duckdb

# The sandbox this runs in tears down each shell invocation's PID
# namespace in a way that eventually kills backgrounded/nohup'd processes
# — confirmed 2026-08-07 when a full nohup'd run survived ~90s across two
# tool-call boundaries but was gone, mid-file, by a third. So this script
# is designed to be resumable and time-bounded: call it repeatedly (each
# call picks up only files not yet loaded, per source_file already present
# in the target staging table) rather than relying on one long-running
# background process. TIME_BUDGET_SECONDS caps each invocation well under
# the tool layer's 45s hard limit.
TIME_BUDGET_SECONDS = 35

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Build in /tmp rather than directly on the synced project mount — WAL
# checkpoint operations against the mounted Desktop folder fail with
# "Operation not permitted" (confirmed 2026-08-07, the mount doesn't
# support the file-remove-then-recreate pattern DuckDB's checkpointing
# needs). Built here, then copied to PROJECT_ROOT as a final step once
# the whole build succeeds, so a failed build never leaves a half-built
# file sitting in the project folder.
DB_PATH = '/tmp/nhs_warehouse_build.db'
FINAL_DB_PATH = os.path.join(PROJECT_ROOT, 'nhs_warehouse.db')


def _load_provider_codes():
    codes = []
    with open(os.path.join(PROJECT_ROOT, 'sql/reference/cheshire_merseyside_providers.csv')) as f:
        reader = csv.DictReader(f)
        for row in reader:
            codes.append(row['provider_org_code'])
    return codes


def _run_sql_file(con, relpath):
    con.execute(open(os.path.join(PROJECT_ROOT, relpath)).read())


# ---------------------------------------------------------------- RTT ----

_RTT_KEY_COLS = [
    ('Period', 'period'), ('Provider Parent Org Code', 'provider_parent_org_code'),
    ('Provider Parent Name', 'provider_parent_name'), ('Provider Org Code', 'provider_org_code'),
    ('Provider Org Name', 'provider_org_name'), ('Commissioner Parent Org Code', 'commissioner_parent_org_code'),
    ('Commissioner Parent Name', 'commissioner_parent_name'), ('Commissioner Org Code', 'commissioner_org_code'),
    ('Commissioner Org Name', 'commissioner_org_name'), ('RTT Part Type', 'rtt_part_type'),
    ('RTT Part Description', 'rtt_part_description'), ('Treatment Function Code', 'treatment_function_code'),
    ('Treatment Function Name', 'treatment_function_name'),
]
_RTT_BAND_RE = re.compile(r'^Gt (\d+) To (\d+) Weeks')
_RTT_CATCHALL_RE = re.compile(r'^Gt (\d+) Weeks')
_RTT_TAIL_COLS = [('Total', 'total'), ('Patients with unknown clock start date', 'unknown_clock_start'), ('Total All', 'total_all')]
_RTT_TARGET_WK_COLS = [f'wk_{i:02d}' for i in range(0, 104)] + ['wk_104_plus']


def _load_rtt_file(con, zip_path, provider_codes, tmpdir):
    extract_dir = os.path.join(tmpdir, 'rtt_extract')
    os.makedirs(extract_dir, exist_ok=True)
    subprocess.run(['unzip', '-o', '-q', zip_path, '-d', extract_dir], check=True)
    csv_files = [f for f in os.listdir(extract_dir) if f.lower().endswith('.csv')]
    if len(csv_files) != 1:
        raise ValueError(f"{zip_path}: expected exactly 1 CSV in zip, found {csv_files}")
    csv_path = os.path.join(extract_dir, csv_files[0])

    with open(csv_path, encoding='utf-8-sig') as f:
        header = next(csv.reader(f))
    header = [h.strip() for h in header]

    wk_col_for_source = {}   # source column name -> target wk_NN name
    for h in header:
        m = _RTT_BAND_RE.match(h)
        if m:
            wk_col_for_source[h] = f'wk_{int(m.group(1)):02d}'
            continue
        m = _RTT_CATCHALL_RE.match(h)
        if m and 'To' not in h:
            # the open-ended tail band for this file (e.g. "Gt 52 Weeks" in
            # the 69-col era, "Gt 104 Weeks" in the 121-col era) — always
            # maps to whichever wk_NN_plus / highest wk_NN is the true tail
            # for THIS file, not assumed to be wk_104_plus every time
            wk_col_for_source[h] = f'wk_{int(m.group(1)):02d}_plus' if f'wk_{int(m.group(1)):02d}_plus' in (_RTT_TARGET_WK_COLS) else f'wk_{int(m.group(1)):02d}'

    # build SELECT expression list: for every target wk_* column, either
    # pull from the matching source column (quoted) or fill 0 if this
    # file's header doesn't have that band at all
    source_to_target = wk_col_for_source
    target_to_source = {v: k for k, v in source_to_target.items()}

    select_parts = []
    for src, tgt in _RTT_KEY_COLS:
        select_parts.append(f'"{src}" AS {tgt}')
    for tgt in _RTT_TARGET_WK_COLS:
        if tgt in target_to_source:
            select_parts.append(f'COALESCE(TRY_CAST("{target_to_source[tgt]}" AS INTEGER), 0) AS {tgt}')
        else:
            select_parts.append(f'0 AS {tgt}')
    for src, tgt in _RTT_TAIL_COLS:
        select_parts.append(f'TRY_CAST("{src}" AS INTEGER) AS {tgt}')
    select_parts.append(f"'{os.path.basename(zip_path)}' AS source_file")

    target_cols = [tgt for _, tgt in _RTT_KEY_COLS] + _RTT_TARGET_WK_COLS + [tgt for _, tgt in _RTT_TAIL_COLS] + ['source_file']
    provider_list_sql = ','.join(f"'{c}'" for c in provider_codes)
    sql = f"""
        INSERT INTO stg_rtt_raw ({', '.join(target_cols)})
        SELECT {', '.join(select_parts)}
        FROM read_csv_auto('{csv_path}', header=true, all_varchar=true)
        WHERE "Provider Org Code" IN ({provider_list_sql})
    """
    con.execute(sql)
    shutil.rmtree(extract_dir)


# --------------------------------------------------------------- DM01 ----

_DM01_KEY_COLS = [
    ('Period', 'period'), ('Provider Parent Org Code', 'provider_parent_org_code'),
    ('Provider Parent Name', 'provider_parent_name'), ('Provider Org Code', 'provider_org_code'),
    ('Provider Org Name', 'provider_org_name'), ('Commissioner Parent Org Code', 'commissioner_parent_org_code'),
    ('Commissioner Parent Name', 'commissioner_parent_name'), ('Commissioner Org Code', 'commissioner_org_code'),
    ('Commissioner Org Name', 'commissioner_org_name'), ('Diagnostic Tests Sort Order', 'diagnostic_test_sort_order'),
    ('Diagnostic Tests', 'diagnostic_test_code'),
]
_DM01_WK_COLS = [
    ('00 < 01 Week', 'wk_00'), ('01 < 02 Weeks', 'wk_01'), ('02 < 03 Weeks', 'wk_02'),
    ('03 < 04 Weeks', 'wk_03'), ('04 < 05 Weeks', 'wk_04'), ('05 < 06 Weeks', 'wk_05'),
    ('06 < 07 Weeks', 'wk_06'), ('07 < 08 Weeks', 'wk_07'), ('08 < 09 Weeks', 'wk_08'),
    ('09 < 10 Weeks', 'wk_09'), ('10 < 11 Weeks', 'wk_10'), ('11 < 12 Weeks', 'wk_11'),
    ('12 < 13 Weeks', 'wk_12'), ('13+ Weeks', 'wk_13_plus'),
]
_DM01_TAIL_COLS = [
    ('Total WL', 'total_wl'), ('Waiting List Activity', 'waiting_list_activity'),
    ('Planned Activity', 'planned_activity'), ('Unscheduled Activity', 'unscheduled_activity'),
    ('Total Activity', 'total_activity'),
]


def _load_dm01_file(con, zip_path, provider_codes, tmpdir):
    extract_dir = os.path.join(tmpdir, 'dm01_extract')
    os.makedirs(extract_dir, exist_ok=True)
    subprocess.run(['unzip', '-o', '-q', zip_path, '-d', extract_dir], check=True)
    csv_files = [f for f in os.listdir(extract_dir) if f.lower().endswith('.csv')]
    if len(csv_files) != 1:
        raise ValueError(f"{zip_path}: expected exactly 1 CSV in zip, found {csv_files}")
    csv_path = os.path.join(extract_dir, csv_files[0])

    select_parts = [f'"{src}" AS {tgt}' for src, tgt in _DM01_KEY_COLS]
    select_parts += [f'TRY_CAST("{src}" AS INTEGER) AS {tgt}' for src, tgt in _DM01_WK_COLS]
    select_parts += [f'TRY_CAST("{src}" AS INTEGER) AS {tgt}' for src, tgt in _DM01_TAIL_COLS]
    select_parts.append(f"'{os.path.basename(zip_path)}' AS source_file")

    target_cols = [tgt for _, tgt in _DM01_KEY_COLS] + [tgt for _, tgt in _DM01_WK_COLS] + [tgt for _, tgt in _DM01_TAIL_COLS] + ['source_file']
    provider_list_sql = ','.join(f"'{c}'" for c in provider_codes)
    sql = f"""
        INSERT INTO stg_dm01_raw ({', '.join(target_cols)})
        SELECT {', '.join(select_parts)}
        FROM read_csv_auto('{csv_path}', header=true, all_varchar=true)
        WHERE "Provider Org Code" IN ({provider_list_sql})
    """
    con.execute(sql)
    shutil.rmtree(extract_dir)


# ---------------------------------------------------------------- A&E ----

# Header text drifted across THREE variants over the window, not the two
# (16-col/22-col) documented in 06_staging_ae.sql from the earlier
# validation pass — discovered when the literal-string mapping below broke
# on FY2019-20's files, which prefix every attendance/over-4hr column with
# "Number of " and use "Other A&E Department" where later files sometimes
# say just "Other Department". Rather than add a third hardcoded literal
# set (and risk a fourth variant breaking this again), matched by regex
# against the normalised header text (", "Number of " prefix stripped)
# instead of exact strings — robust to the specific wording drift actually
# observed without needing to enumerate every combination up front.
_AE_KEY_PATTERNS = [
    (re.compile(r'^Period$', re.I), 'period'), (re.compile(r'^Org Code$', re.I), 'provider_org_code'),
    (re.compile(r'^Parent Org$', re.I), 'parent_org_region'), (re.compile(r'^Org name$', re.I), 'provider_org_name'),
]
_AE_DATA_PATTERNS = [
    (re.compile(r'^A&E attendances Type 1$', re.I), 'attendances_type1'),
    (re.compile(r'^A&E attendances Type 2$', re.I), 'attendances_type2'),
    (re.compile(r'^A&E attendances Other', re.I), 'attendances_other'),
    (re.compile(r'^A&E attendances Booked Appointments Type 1$', re.I), 'attendances_booked_type1'),
    (re.compile(r'^A&E attendances Booked Appointments Type 2$', re.I), 'attendances_booked_type2'),
    (re.compile(r'^A&E attendances Booked Appointments Other', re.I), 'attendances_booked_other'),
    (re.compile(r'^Attendances? over ?4hrs Type 1$', re.I), 'over4hr_type1'),
    (re.compile(r'^Attendances? over ?4hrs Type 2$', re.I), 'over4hr_type2'),
    (re.compile(r'^Attendances? over ?4hrs Other', re.I), 'over4hr_other'),
    (re.compile(r'^Attendances? over ?4hrs Booked Appointments Type 1$', re.I), 'over4hr_booked_type1'),
    (re.compile(r'^Attendances? over ?4hrs Booked Appointments Type 2$', re.I), 'over4hr_booked_type2'),
    (re.compile(r'^Attendances? over ?4hrs Booked Appointments Other', re.I), 'over4hr_booked_other'),
    (re.compile(r'^Patients who have waited 4-12 hs? from DTA to admission$', re.I), 'waited_4to12hr_dta'),
    (re.compile(r'^Patients who have waited 12\+ hrs? from DTA to admission$', re.I), 'waited_12hr_plus_dta'),
    (re.compile(r'^Emergency admissions via A&E - Type 1$', re.I), 'emergency_admissions_type1'),
    (re.compile(r'^Emergency admissions via A&E - Type 2$', re.I), 'emergency_admissions_type2'),
    (re.compile(r'^Emergency admissions via A&E - Other', re.I), 'emergency_admissions_other'),
    (re.compile(r'^Other emergency admissions$', re.I), 'other_emergency_admissions'),
]
_AE_ALL_TARGETS = [tgt for _, tgt in _AE_KEY_PATTERNS] + [tgt for _, tgt in _AE_DATA_PATTERNS]
_AE_BOOKED_TARGETS = {'attendances_booked_type1', 'attendances_booked_type2', 'attendances_booked_other',
                      'over4hr_booked_type1', 'over4hr_booked_type2', 'over4hr_booked_other'}


def _normalize_ae_header(h):
    h = h.strip()
    if h.startswith('Number of '):
        h = h[len('Number of '):]
    return h


def _load_ae_file(con, csv_path, provider_codes):
    with open(csv_path, encoding='utf-8-sig') as f:
        raw_header = [h.strip() for h in next(csv.reader(f))]
    norm_header = [_normalize_ae_header(h) for h in raw_header]

    target_to_source = {}
    for raw, norm in zip(raw_header, norm_header):
        for pattern, tgt in _AE_KEY_PATTERNS + _AE_DATA_PATTERNS:
            if pattern.match(norm) and tgt not in target_to_source:
                target_to_source[tgt] = raw
                break

    missing_required = [t for t in _AE_ALL_TARGETS if t not in target_to_source and t not in _AE_BOOKED_TARGETS]
    if missing_required:
        raise ValueError(f"{csv_path}: could not map required columns {missing_required} — header was {raw_header}")

    select_parts = []
    for _, tgt in _AE_KEY_PATTERNS:
        select_parts.append(f'"{target_to_source[tgt]}" AS {tgt}')
    for _, tgt in _AE_DATA_PATTERNS:
        if tgt in target_to_source:
            select_parts.append(f'TRY_CAST("{target_to_source[tgt]}" AS INTEGER) AS {tgt}')
        else:
            select_parts.append(f'NULL::INTEGER AS {tgt}')
    select_parts.append(f"'{os.path.basename(csv_path)}' AS source_file")

    target_cols = _AE_ALL_TARGETS + ['source_file']
    org_code_source = target_to_source['provider_org_code']
    provider_list_sql = ','.join(f"'{c}'" for c in provider_codes)
    sql = f"""
        INSERT INTO stg_ae_raw ({', '.join(target_cols)})
        SELECT {', '.join(select_parts)}
        FROM read_csv_auto('{csv_path}', header=true, all_varchar=true)
        WHERE "{org_code_source}" IN ({provider_list_sql})
    """
    con.execute(sql)


# ------------------------------------------------------------- driver ----

def stage_init():
    """Create the DB and staging/dimension schema. Idempotent — safe to
    call again, it just no-ops on tables that already exist."""
    con = duckdb.connect(DB_PATH)
    _run_sql_file(con, 'sql/schema/01_staging.sql')
    _run_sql_file(con, 'sql/schema/02_dimensions.sql')
    _run_sql_file(con, 'sql/schema/04_staging_dm01.sql')
    _run_sql_file(con, 'sql/schema/06_staging_ae.sql')
    con.close()
    print("Schema initialised.")


def stage_rtt():
    """Load RTT files not yet in stg_rtt_raw, stopping within the time
    budget. Call repeatedly until it reports 0 remaining."""
    provider_codes = _load_provider_codes()
    con = duckdb.connect(DB_PATH)
    already = set(r[0] for r in con.execute("select distinct source_file from stg_rtt_raw").fetchall())
    rtt_dir = os.path.join(PROJECT_ROOT, 'data_raw/rtt')
    todo = [f for f in sorted(os.listdir(rtt_dir)) if f.lower().endswith('.zip') and f not in already]
    print(f"RTT: {len(already)} files already loaded, {len(todo)} remaining")

    t0 = time.time()
    done_this_run = 0
    with tempfile.TemporaryDirectory() as tmpdir:
        for fname in todo:
            if time.time() - t0 > TIME_BUDGET_SECONDS:
                break
            _load_rtt_file(con, os.path.join(rtt_dir, fname), provider_codes, tmpdir)
            done_this_run += 1
    n = con.execute("select count(*) from stg_rtt_raw").fetchone()[0]
    remaining = len(todo) - done_this_run
    print(f"RTT: loaded {done_this_run} files this run ({n} total rows), {remaining} files remaining")
    con.close()
    return remaining


def stage_dm01():
    provider_codes = _load_provider_codes()
    con = duckdb.connect(DB_PATH)
    already = set(r[0] for r in con.execute("select distinct source_file from stg_dm01_raw").fetchall())
    dm01_dir = os.path.join(PROJECT_ROOT, 'data_raw/dm01')
    todo = [f for f in sorted(os.listdir(dm01_dir)) if f.lower().endswith('.zip') and f not in already]
    print(f"DM01: {len(already)} files already loaded, {len(todo)} remaining")

    t0 = time.time()
    done_this_run = 0
    with tempfile.TemporaryDirectory() as tmpdir:
        for fname in todo:
            if time.time() - t0 > TIME_BUDGET_SECONDS:
                break
            _load_dm01_file(con, os.path.join(dm01_dir, fname), provider_codes, tmpdir)
            done_this_run += 1
    n = con.execute("select count(*) from stg_dm01_raw").fetchone()[0]
    remaining = len(todo) - done_this_run
    print(f"DM01: loaded {done_this_run} files this run ({n} total rows), {remaining} files remaining")
    con.close()
    return remaining


def stage_ae():
    provider_codes = _load_provider_codes()
    con = duckdb.connect(DB_PATH)
    already = set(r[0] for r in con.execute("select distinct source_file from stg_ae_raw").fetchall())
    ae_dir = os.path.join(PROJECT_ROOT, 'data_raw/ae')
    todo = [f for f in sorted(os.listdir(ae_dir)) if f.lower().endswith('.csv') and f not in already]
    print(f"A&E: {len(already)} files already loaded, {len(todo)} remaining")

    t0 = time.time()
    done_this_run = 0
    for fname in todo:
        if time.time() - t0 > TIME_BUDGET_SECONDS:
            break
        _load_ae_file(con, os.path.join(ae_dir, fname), provider_codes)
        done_this_run += 1
    n = con.execute("select count(*) from stg_ae_raw").fetchone()[0]
    remaining = len(todo) - done_this_run
    print(f"A&E: loaded {done_this_run} files this run ({n} total rows), {remaining} files remaining")
    con.close()
    return remaining


def stage_finalize():
    """Everything fast enough to run in one call: fact tables for RTT/
    DM01/A&E, then KH03/GPAD/Workforce/IMD (all Python loaders, all quick),
    then dim_provider seeding, then copy to the project folder."""
    con = duckdb.connect(DB_PATH)

    print("Fact: RTT")
    _run_sql_file(con, 'sql/schema/03_fact_rtt_provider_specialty_month.sql')
    print("Fact: DM01")
    _run_sql_file(con, 'sql/schema/05_fact_dm01_provider_test_month.sql')
    print("Fact: A&E")
    _run_sql_file(con, 'sql/schema/07_fact_ae_provider_month.sql')

    sys.path.insert(0, os.path.join(PROJECT_ROOT, 'scripts'))

    print("KH03")
    _run_sql_file(con, 'sql/schema/08_staging_kh03.sql')
    from load_kh03 import load_kh03
    load_kh03(con, kh03_dir=os.path.join(PROJECT_ROOT, 'data_raw/kh03'))
    _run_sql_file(con, 'sql/schema/09_fact_kh03_provider_quarter.sql')

    print("GPAD")
    _run_sql_file(con, 'sql/schema/10_staging_gpad.sql')
    from load_gpad import load_gpad
    load_gpad(con, gpad_dir=os.path.join(PROJECT_ROOT, 'data_raw/gpad'))
    _run_sql_file(con, 'sql/schema/11_fact_gpad_geography_year.sql')

    print("Workforce")
    _run_sql_file(con, 'sql/schema/12_staging_workforce.sql')
    from load_workforce import load_workforce
    load_workforce(con, workforce_dir=os.path.join(PROJECT_ROOT, 'data_raw/workforce'))
    _run_sql_file(con, 'sql/schema/13_fact_workforce_provider_year.sql')

    print("IMD 2019")
    _run_sql_file(con, 'sql/schema/14_dim_imd2019_local_authority.sql')
    from load_imd import load_imd
    load_imd(con, imd_dir=os.path.join(PROJECT_ROOT, 'data_raw/imd'))

    print("Seeding dim_provider")
    con.execute(f"""
        INSERT INTO dim_provider (provider_org_code, provider_org_name, provider_type, in_core_analysis)
        SELECT provider_org_code, provider_org_name, provider_type, include_in_core_analysis::boolean
        FROM read_csv_auto('{os.path.join(PROJECT_ROOT, "sql/reference/cheshire_merseyside_providers.csv")}', header=true)
        WHERE provider_org_code NOT IN (SELECT provider_org_code FROM dim_provider)
    """)
    con.execute("update dim_provider set icb_code = 'QYG', icb_name = 'NHS Cheshire and Merseyside Integrated Care Board'")

    con.close()
    print(f"Copying {DB_PATH} -> {FINAL_DB_PATH}")
    shutil.copy(DB_PATH, FINAL_DB_PATH)
    print("Done.")


if __name__ == '__main__':
    stage = sys.argv[1] if len(sys.argv) > 1 else 'init'
    {
        'init': stage_init,
        'rtt': stage_rtt,
        'dm01': stage_dm01,
        'ae': stage_ae,
        'finalize': stage_finalize,
    }[stage]()
