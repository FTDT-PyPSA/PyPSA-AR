"""
12_build_generators_final.py
Merges generators_readypypsa.csv with manually resolved generators from
generators_manualpypsa.csv to produce generators_final.csv — the definitive
generator table that enters PyPSA.

Inputs:
    data/network_500kv/generators_readypypsa.csv  (script 11)
    data/network_500kv/generators_manualpypsa.csv (completed manually)
    Official data/GEOSADI/CSV/centrales_electricas.csv  (external — download from GitHub Releases, place in external_data_dir/GEOSADI/CSV/)

Output:
    data/network_500kv/generators_final.csv
        One row per generator. Contains all generators with geosadi_name
        AND bus_conexion500kv resolved.
        Used as model input together with buses_final.csv and lines_500kv_final.csv.

        Column 'nemo': 4-character CAMMESA code (e.g. YACY, EMBA, ATU2).
        Obtained by joining geosadi_name -> Nombre in centrales_electricas.csv.
        Key for joining with VALORES_2024.csv (real generation data).

        Column 'stat': generator status in PSS/E snapshot (summer peak 2025/2026).
        stat=1 in service, stat=0 out of service in that base case.

CAPE/ACAJ reassignment:
    CAPEX (CAPE in CAMMESA) and Agua del Cajon (ACAJ) are commercially
    separate but physically the same power plant. Units TG01, TG06 and
    TV07 belong to CAPE.

Run from the repository root (pypsa-ar-base/):
    python scripts/network_500kv/12_build_generators_final.py
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

READY_FILE        = REPO_DIR / "data/network_500kv/generators_readypypsa.csv"
MANUAL_FILE       = REPO_DIR / "data/network_500kv/generators_manualpypsa.csv"
POWER_PLANTS_FILE = EXTERNAL_DIR / "GEOSADI/CSV/centrales_electricas.csv"
OUTPUT_DIR        = REPO_DIR / "data/network_500kv"
OUTPUT_FILE       = OUTPUT_DIR / "generators_final.csv"

COLS = [
    'gen_key', 'bus_name_origen', 'geosadi_name', 'nemo',
    'bus_conexion500kv', 'bus_conexion500kv_name',
    'carrier', 'lat', 'lon',
    'pg_mw', 'pt_mw', 'stat',
    'match_type', 'n_jumps', 'path',
]

# Nemo reassignment by individual gen_key.
# CAPEX (CAPE in CAMMESA) and Agua del Cajon (ACAJ) are commercially
# separate but physically the same power plant.
# TG01, TG06 and TV07 belong to CAPE.
NEMO_OVERRIDE = {
    '1601-1': 'CAPE',   # ACAJTG01 -> CAPEX
    '1600-6': 'CAPE',   # ACAJTG06 -> CAPEX
    '1606-1': 'CAPE',   # ACAJTV07 -> CAPEX
}


def main():
    print("=" * 60)
    print("12_build_generators_final.py -- definitive generator table for PyPSA")
    print("=" * 60)

    for f in [READY_FILE, MANUAL_FILE, POWER_PLANTS_FILE]:
        if not os.path.isfile(f):
            print(f"[ERROR] File not found:\n  {f}")
            sys.exit(1)

    ready        = pd.read_csv(READY_FILE)
    manual       = pd.read_csv(MANUAL_FILE)
    power_plants = pd.read_csv(POWER_PLANTS_FILE, encoding='latin-1')

    # Dictionary geosadi_name -> nemo from centrales_electricas.csv
    # 'Nombre' and 'Nemo' are GeoSADI field names — kept as-is
    nemo_map = power_plants.drop_duplicates('Nombre').set_index('Nombre')['Nemo'].to_dict()

    print(f"generators_readypypsa  : {len(ready)} generators")
    print(f"generators_manualpypsa : {len(manual)} generators")
    print(f"centrales_electricas   : {len(nemo_map)} entries in geosadi_name->nemo index")

    # Filter manual: only missing='ok' and match_type != 'no_connection'
    mask      = (manual['missing'] == 'ok') & (manual['match_type'] != 'no_connection')
    manual_ok = manual[mask].copy()

    n_captive = len(manual[(manual['missing'] == 'ok') & (manual['match_type'] == 'no_connection')])
    n_pending = len(manual[manual['missing'] != 'ok'])

    print(f"\n  Resolved from manual   : {len(manual_ok)}")
    print(f"  Captive excluded       : {n_captive}  (ALUAR, El Trapial, internal generation)")
    print(f"  Still unresolved       : {n_pending}")

    if n_pending > 0:
        still = manual[manual['missing'] != 'ok'][['gen_key', 'bus_name_origen', 'carrier', 'pt_mw']]
        print(still.to_string(index=False))

    # Concat and sort
    df_final = pd.concat([ready.copy(), manual_ok], ignore_index=True)
    df_final = df_final.sort_values('pt_mw', ascending=False).reset_index(drop=True)

    # Add nemo via join: geosadi_name -> Nombre in centrales_electricas.csv
    df_final['nemo'] = df_final['geosadi_name'].map(nemo_map).fillna('')

    # For rows without nemo (geosadi_name corrupted by encoding),
    # fall back to first 4 chars of bus_name_origen
    mask_no_nemo = df_final['nemo'] == ''
    if mask_no_nemo.sum() > 0:
        df_final.loc[mask_no_nemo, 'nemo'] = (
            df_final.loc[mask_no_nemo, 'bus_name_origen'].str[:4].str.strip()
        )
        print(f"  {mask_no_nemo.sum()} nemos resolved from bus_name_origen[:4] (encoding issue in geosadi_name)")

    # Apply CAPE/ACAJ nemo reassignment
    n_override = 0
    for gen_key, new_nemo in NEMO_OVERRIDE.items():
        mask_ov = df_final['gen_key'] == gen_key
        if mask_ov.sum() > 0:
            df_final.loc[mask_ov, 'nemo'] = new_nemo
            n_override += mask_ov.sum()
    if n_override:
        print(f"  CAPE/ACAJ reassignment applied: {n_override} units -> CAPE")

    n_with_nemo    = (df_final['nemo'] != '').sum()
    n_without_nemo = (df_final['nemo'] == '').sum()
    print(f"\n  With nemo resolved     : {n_with_nemo}")
    if n_without_nemo:
        print(f"  Without nemo           : {n_without_nemo}")
        no_nemo = df_final[df_final['nemo'] == ''][['gen_key', 'geosadi_name', 'carrier']]
        print(no_nemo.to_string(index=False))

    # Select and order final columns
    df_final = df_final[COLS]

    # ==========================================================
    # SUMMARY
    # ==========================================================
    print(f"\n{'='*60}")
    print(f"GENERATORS_FINAL")
    print(f"{'='*60}")
    print(f"  Total generators   : {len(df_final)}")

    mw_total = df_final[df_final['pt_mw'] < 9000]['pt_mw'].sum()
    print(f"  Total capacity     : {mw_total:,.1f} MW  (excludes PT=9999)")

    print(f"\n  By carrier (pt < 9999):")
    active = df_final[df_final['pt_mw'] < 9990]
    for carrier, grp in active.groupby('carrier'):
        print(f"    {carrier:<15}: {len(grp):>4} units   {grp['pt_mw'].sum():>10,.1f} MW")

    print(f"\n  By match_type:")
    for mt, grp in df_final.groupby('match_type'):
        mw = grp[grp['pt_mw'] < 9000]['pt_mw'].sum()
        print(f"    {mt:<15}: {len(grp):>4} units   {mw:>10,.1f} MW")

    n_no_coord = df_final['lat'].isna().sum()
    if n_no_coord > 0:
        print(f"\n  Without coordinates : {n_no_coord} generators (added to PyPSA without map point)")

    # ==========================================================
    # EXPORT
    # ==========================================================
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    df_final.to_csv(OUTPUT_FILE, index=False)
    print(f"\n  Output: {OUTPUT_FILE}  ({len(df_final)} rows)")
    print("Next: 12b_export_qgis_generators.py")


if __name__ == "__main__":
    main()
