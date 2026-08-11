#!/usr/bin/env bash
# Pulls the monthly "Full CSV data file" RTT extracts (provider+commissioner,
# all part types, all treatment functions, one file per month) for FY2019-20
# through FY2026-27 (year to date).
#
# Why the full CSV and not the split Incomplete/Admitted/NonAdmitted files:
# fewer files to reconcile, and the part-type column lets us pivot in SQL
# instead of joining three separate extracts per month.
#
# NHS England reshuffles the upload path and appends a random hash to each
# filename on every publish/revision, so URLs can't be constructed from a
# pattern — this scrapes each fiscal-year index page for the real links.
#
# Run this locally (needs real internet access, which the build sandbox
# doesn't have). Re-run any time — it skips files already on disk.

set -euo pipefail

OUT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/data_raw/rtt"
mkdir -p "$OUT_DIR"

FISCAL_YEARS=(2019-20 2020-21 2021-22 2022-23 2023-24 2024-25 2025-26 2026-27)

UA="Mozilla/5.0 (compatible; nhs-capacity-optimiser-fetch/1.0)"

for fy in "${FISCAL_YEARS[@]}"; do
  page="https://www.england.nhs.uk/statistics/statistical-work-areas/rtt-waiting-times/rtt-data-${fy}/"
  echo "== ${fy} =="
  html="$(curl -sL -A "$UA" "$page" || true)"
  if [ -z "$html" ]; then
    echo "  could not fetch index page, skipping"
    continue
  fi

  # pull every href pointing at a "Full-CSV-data-file...zip"
  links="$(echo "$html" | grep -oE 'https://[^"'"'"']*Full-CSV-data-file[^"'"'"']*\.zip' | sort -u)"

  if [ -z "$links" ]; then
    echo "  no Full CSV links found on page — check page structure hasn't changed"
    continue
  fi

  while IFS= read -r url; do
    fname="$(basename "$url")"
    dest="$OUT_DIR/$fname"
    if [ -f "$dest" ]; then
      echo "  skip (already have) $fname"
      continue
    fi
    echo "  fetching $fname"
    curl -sL -A "$UA" -o "$dest" "$url"
  done <<< "$links"
done

echo ""
echo "Done. Files in $OUT_DIR:"
ls -la "$OUT_DIR"
