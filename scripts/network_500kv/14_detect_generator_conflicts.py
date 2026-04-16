"""
14_detect_generator_conflicts.py
Detects conflicts between model unit names (PSS/E) and CAMMESA unit codes,
and generates a CSV to resolve them manually.

A conflict exists when a model unit has no direct match in CAMMESA
(bus_name_origen is not a valid CAMMESA unit code) AND the plant it belongs to
has more than one unit code in CAMMESA. In that case it is not possible to
automatically determine which CAMMESA unit corresponds to it.

Inputs:
    data/network_500kv/generators_final.csv
    Official data/valores_2024_clean.csv  (external — download from GitHub Releases, place in external_data_dir/)

Output:
    data/network_500kv/conflicts_psse_cammesa.csv
        One row per conflicted unit.
        Columns to fill manually:
            corrected_unit_name : CAMMESA unit code that corresponds to this unit
                                  according to the single-line diagram. Leave empty if no match.
            comment             : observations from the single-line diagram review.

        If the file already exists, previously completed resolutions are preserved.
        New rows are added with corrected_unit_name empty.

Workflow:
    14  -> generates/updates conflictos_psse_cammesa.csv
    complete the CSV manually
    14b -> reads resolved CSV + generates generators_2024.csv

Run from the repository root (pypsa-ar-base/):
    python scripts/network_500kv/14_detect_generator_conflicts.py
"""

import os
import sys
from pathlib import Path
import yaml
import pandas as pd

# =============================================================================
# CONFIGURATION
# =============================================================================

_cfg = yaml.safe_load(open(Path(__file__).parents[2] / "config.yaml"))
REPO_DIR     = Path(_cfg["repo_dir"])
EXTERNAL_DIR = Path(_cfg["external_data_dir"])

GEN_FILE       = REPO_DIR / "data/network_500kv/generators_final.csv"
VALORES_FILE   = EXTERNAL_DIR / "valores_2024_clean.csv"
CONFLICTS_FILE = REPO_DIR / "data/network_500kv/conflicts_psse_cammesa.csv"


# =============================================================================
# MAIN
# =============================================================================

def main():
    print("=" * 60)
    print("14_detect_generator_conflicts.py")
    print("=" * 60)

    for f in [GEN_FILE, VALORES_FILE]:
        if not os.path.isfile(f):
            print(f"[ERROR] File not found:\n  {f}")
            sys.exit(1)

    # =========================================================
    # LOAD DATA
    # =========================================================
    gen = pd.read_csv(GEN_FILE)
    gen['nemo4'] = gen['nemo'].fillna('').str[:4].str.strip()

    print(f"\nUnits in model    : {len(gen)}")

    vals = pd.read_csv(
        VALORES_FILE,
        usecols=['unit', 'code'],
        low_memory=False,
    ).drop_duplicates()

    cammesa_units = set(vals['unit'].unique())

    units_per_plant = (
        vals.groupby('code')['unit']
        .apply(lambda x: sorted(x.unique()))
    )
    n_units_per_plant = units_per_plant.apply(len)

    print(f"CAMMESA units     : {len(cammesa_units)}")
    print(f"CAMMESA power plants    : {len(units_per_plant)}")

    # =========================================================
    # DETECT CONFLICTS
    # =========================================================
    no_direct_match = gen[~gen['bus_name_origen'].isin(cammesa_units)].copy()

    conflicts = no_direct_match[
        no_direct_match['nemo4'].isin(
            n_units_per_plant[n_units_per_plant > 1].index
        )
    ].copy()

    print(f"\nUnits without direct match : {len(no_direct_match)}")
    print(f"Conflicts detected         : {len(conflicts)}")
    print(f"Power plants with conflict       : {conflicts['nemo4'].nunique()}")

    # =========================================================
    # PRESERVE EXISTING RESOLUTIONS
    # =========================================================
    prev_corrections = {}
    prev_comments    = {}
    prev_reviewed    = {}
    prev_exclude     = {}

    if os.path.isfile(CONFLICTS_FILE):
        existing = pd.read_csv(CONFLICTS_FILE, encoding='latin-1')
        for _, row in existing.iterrows():
            gkey = row['gen_key']
            val  = row['corrected_unit_name']
            com  = row['comment']
            rev  = row.get('reviewed', '')
            excl = row.get('exclude', '')
            if pd.notna(val) and str(val).strip() != '':
                prev_corrections[gkey] = str(val).strip()
            if pd.notna(com) and str(com).strip() != '':
                prev_comments[gkey] = str(com).strip()
            if pd.notna(rev) and str(rev).strip() != '':
                prev_reviewed[gkey] = str(rev).strip()
            if pd.notna(excl) and str(excl).strip() != '':
                prev_exclude[gkey] = str(excl).strip()

        print(f"\nPrevious resolutions preserved: {len(prev_corrections)}")

    # =========================================================
    # BUILD OUTPUT CSV
    # =========================================================
    conflicts['cammesa_units'] = conflicts['nemo4'].map(
        units_per_plant.apply(lambda x: '|'.join(x))
    )
    conflicts['n_cammesa_units'] = conflicts['nemo4'].map(n_units_per_plant)

    conflicts['corrected_unit_name'] = conflicts['gen_key'].map(
        prev_corrections
    ).fillna('')

    conflicts['comment'] = conflicts['gen_key'].map(
        prev_comments
    ).fillna('')

    conflicts['reviewed'] = conflicts['gen_key'].map(
        prev_reviewed
    ).fillna('')

    conflicts['exclude'] = conflicts['gen_key'].map(
        prev_exclude
    ).fillna('')

    cols_out = [
        'gen_key', 'bus_name_origen', 'geosadi_name',
        'bus_conexion500kv_name', 'nemo4', 'carrier',
        'cammesa_units', 'n_cammesa_units',
        'corrected_unit_name', 'reviewed', 'exclude', 'comment',
    ]

    conflicts[cols_out].sort_values(['nemo4', 'gen_key']).to_csv(
        CONFLICTS_FILE, index=False
    )

    has_match  = conflicts['corrected_unit_name'] != ''
    is_excl    = conflicts['exclude'].str.strip().str.lower() == 'yes'
    is_reviewed = (conflicts['reviewed'].str.strip().str.lower() == 'yes') & ~has_match & ~is_excl

    n_matched   = has_match.sum()
    n_excluded  = is_excl.sum()
    n_reviewed  = is_reviewed.sum()
    n_pending   = len(conflicts) - n_matched - n_excluded - n_reviewed

    print(f"\nWith match assigned : {n_matched}")
    print(f"Excluded            : {n_excluded}")
    print(f"Reviewed, no match  : {n_reviewed}")
    print(f"Pending             : {n_pending}")
    print(f"\nOutput: {CONFLICTS_FILE}")
    print("\nFill in 'corrected_unit_name' in the CSV and run script 14b.")
    print("=" * 60)


if __name__ == "__main__":
    main()
