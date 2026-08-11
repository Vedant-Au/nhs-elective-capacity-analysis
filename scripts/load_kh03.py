"""
Loader for KH03 (Bed Availability and Occupancy), overnight beds only.

Unlike RTT/DM01/A&E, this source can't be loaded with a single SQL COPY/
INSERT per file, because the two source shapes genuinely don't match:

  - The three consolidated CSVs NHS publishes (KH03-Available-Overnight-only,
    KH03-Occupied-Overnight-only) are long format: one row per
    (provider, sector, quarter), covering 2001 through 2024-06-30. Checked
    the actual dates in the files rather than trusting "onwards" in the
    page copy — they stop at Q1 2024-25, which is why the second source
    below exists at all.
  - The individual quarterly "Beds-Open-Overnight-Web_File-QX-20XX-XX.xlsx"
    releases (used here for Q2 2024-25 through Q4 2025-26, the gap after the
    consolidated CSVs stop) are wide format: one row per provider, with
    Available and Occupied for each of the four sectors as parallel column
    blocks. Header is at row 15, data from row 18 (row 16 is an England
    national total, row 17 a blank spacer) — confirmed by inspection on
    2026-08-07, not assumed from a template.

This script reshapes both into the same long (provider, sector, quarter,
available, occupied) shape and inserts into stg_kh03_raw, matching
sql/schema/08_staging_kh03.sql. Run this after loading 08_staging_kh03.sql
and before 09_fact_kh03_provider_quarter.sql against a real DuckDB/Postgres
connection — it's a plain Python function, not a standalone CLI, so wire it
into whatever the Phase 2 warehouse-build driver ends up being.

Usage:
    import duckdb
    from load_kh03 import load_kh03
    con = duckdb.connect('nhs_warehouse.db')
    con.execute(open('sql/schema/08_staging_kh03.sql').read())
    load_kh03(con, kh03_dir='data_raw/kh03')
    con.execute(open('sql/schema/09_fact_kh03_provider_quarter.sql').read())
"""

import csv
import openpyxl
from datetime import datetime

# Consolidated CSVs stop here — everything after this date must come from
# the individual quarterly Excel files instead. Verified 2026-08-07 by
# checking the actual max date in both KH03-Available-Overnight-only.csv
# and KH03-Occupied-Overnight-only.csv (both stop at the same date, which
# is reassuring — a genuine collection cutoff, not one file lagging the other).
CSV_CUTOFF_DATE = datetime(2024, 6, 30).date()

# Gap-filling quarterly Excel files — Q2 2024-25 through Q4 2025-26, i.e.
# everything after CSV_CUTOFF_DATE through the end of this project's window
# (FY2025-26). Filenames are exactly what landed in data_raw/kh03/ on
# 2026-08-07; if a future run needs to extend the window forward, add the
# new quarter's filename here after confirming it against the real
# "Bed Availability and Occupancy Data – Overnight" page, not by guessing
# the naming pattern (NHS has changed the Overnight file's hash-suffix
# convention before, see the A&E and DM01 loaders for what "guessing NHS
# filenames" gets you).
GAP_FILLER_FILES = [
    'Beds-Open-Overnight-Web_File-Q2-2024-25.xlsx',
    'Beds-Open-Overnight-Web_File-Q3-2024-25-revised.xlsx',
    'Beds-Open-Overnight-Web_File-Q4-2024-25.xlsx',
    'Beds-Open-Overnight-Web_File-Q1-2025-26-revised.xlsx',
    'Beds-Open-Overnight-Web_File-Q2-2025-26.xlsx',
    'Beds-Open-Overnight-Web_File-Q3-2025-26.xlsx',
    'Beds-Open-Overnight-Web_File-Q4-2025-26.xlsx',
]

# Project window start — no point loading 2001-2019 history into the
# warehouse when the charter's agreed window is FY2019-20 onwards.
WINDOW_START_DATE = datetime(2019, 4, 1).date()

_SECTOR_MAP = {
    'general & acute': 'General & Acute',
    'maternity': 'Maternity',
    'mental illness': 'Mental Illness',
    'learning disabilities': 'Learning Disability',
    'learning disability': 'Learning Disability',
}

_MONTH_MAP = {'June': (6, 30), 'September': (9, 30), 'December': (12, 31), 'March': (3, 31)}


def _norm_sector(s):
    return _SECTOR_MAP.get(s.strip().lower(), s.strip())


def _fiscal_year(d):
    start = d.year if d.month >= 4 else d.year - 1
    return f"{start}-{str(start + 1)[2:]}"


def _load_consolidated_csvs(con, kh03_dir):
    def read_rows(fname):
        with open(f'{kh03_dir}/{fname}', encoding='utf-8-sig') as f:
            return list(csv.reader(f))[1:]

    avail_rows = read_rows('KH03-Available-Overnight-only.csv')
    occ_rows = read_rows('KH03-Occupied-Overnight-only.csv')

    def to_map(rows):
        m = {}
        for r in rows:
            if not r[3].strip():
                continue
            try:
                d = datetime.strptime(r[3], '%d/%m/%Y').date()
            except ValueError:
                continue
            if not (WINDOW_START_DATE <= d <= CSV_CUTOFF_DATE):
                continue
            key = (r[0], _norm_sector(r[1]), d)
            # Number_Of_Beds is occasionally comma-thousands-formatted for
            # 4-digit bed counts (e.g. '2,079') and plain for smaller ones —
            # found on 2026-08-07 when a naive float() blew up on 27 of the
            # ~56k rows in the consolidated CSVs. Not a rare one-off: strip
            # commas unconditionally rather than special-casing it.
            raw_val = r[2].strip().replace(',', '')
            m[key] = float(raw_val) if raw_val != '' else None
        return m

    avail_map = to_map(avail_rows)
    occ_map = to_map(occ_rows)
    all_keys = set(avail_map) | set(occ_map)

    n = 0
    for (org, sector, d) in all_keys:
        con.execute(
            """insert into stg_kh03_raw
               (provider_org_code, provider_org_name, quarter_end_date, fiscal_year,
                sector, available_beds, occupied_beds, source_file)
               values (?, NULL, ?, ?, ?, ?, ?, ?)""",
            [org, d, _fiscal_year(d), sector, avail_map.get((org, sector, d)),
             occ_map.get((org, sector, d)), 'KH03-consolidated-csv'],
        )
        n += 1
    return n


def _load_gap_filler_excel(con, kh03_dir):
    n = 0
    for fname in GAP_FILLER_FILES:
        wb = openpyxl.load_workbook(f'{kh03_dir}/{fname}', data_only=True)
        ws = wb['NHS Trust by Sector']
        for row in ws.iter_rows(min_row=18, values_only=True):
            org_code, org_name = row[4], row[5]
            if not org_code:
                continue
            period_end_month, year_label = row[2], row[1]
            mm, dd = _MONTH_MAP[period_end_month]
            fy_start = int(year_label.split('-')[0])
            cal_year = fy_start if mm >= 4 else fy_start + 1
            qdate = datetime(cal_year, mm, dd).date()
            if qdate <= CSV_CUTOFF_DATE:
                # shouldn't happen given the gap-filler file list, but don't
                # silently double-load a quarter the CSVs already cover
                continue

            pairs = [
                ('General & Acute', row[7], row[13]),
                ('Learning Disability', row[8], row[14]),
                ('Maternity', row[9], row[15]),
                ('Mental Illness', row[10], row[16]),
            ]
            for sector, av, oc in pairs:
                con.execute(
                    """insert into stg_kh03_raw
                       (provider_org_code, provider_org_name, quarter_end_date, fiscal_year,
                        sector, available_beds, occupied_beds, source_file)
                       values (?, ?, ?, ?, ?, ?, ?, ?)""",
                    [org_code, org_name, qdate, _fiscal_year(qdate), sector, av, oc, fname],
                )
                n += 1
    return n


def load_kh03(con, kh03_dir='data_raw/kh03'):
    """Load all KH03 overnight-bed data for FY2019-20 through FY2025-26 into
    stg_kh03_raw on the given DB connection (DuckDB or psycopg2-style)."""
    n_csv = _load_consolidated_csvs(con, kh03_dir)
    n_xlsx = _load_gap_filler_excel(con, kh03_dir)
    print(f"KH03: loaded {n_csv} rows from consolidated CSVs, {n_xlsx} rows from gap-filler Excel files")
    return n_csv + n_xlsx
