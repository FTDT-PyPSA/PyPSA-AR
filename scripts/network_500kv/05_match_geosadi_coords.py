"""
05_match_geosadi_coords.py
Assigns geographic coordinates to all model buses and consolidates them
into a single buses_final.csv file.

Depends : data/network_500kv/buses_500kv_raw.csv          (script 01)
          data/network_500kv/buses_sec_raw.csv             (script 04)
          data/network_500kv/buses_PSSE_vs_geosadi.xlsx    (manual matching dictionary — versioned in repo)
Output  : data/network_500kv/buses_final.csv

Run from the repository root (pypsa-ar-base/):
    python scripts/network_500kv/05_match_geosadi_coords.py

Logic:
   500 kV BUSES:
    Coordinates come from the manual dictionary buses_PSSE_vs_geosadi.xlsx.
    Each PSS/E bus was matched against the GeoSADI public GIS viewer:
        https://www.arcgis.com/apps/instant/sidebar/index.html?appid=4b0ffba2055745a3afdbe1444d2db6d7
    For buses where the match was not straightforward, the full connection
    topology was studied to determine the correct substation location.
    match_status = 'manual'

    SECONDARY BUSES:
        Inherit coordinates from their 500 kV parent bus (same parent_bus_id).
        Physically correct: they are located at the same substation as the
        transformer connecting them.
        match_status = 'inherited'

    CONSOLIDATION:
        Both groups are merged into a single DataFrame with common columns.
        The bus_type field indicates '500kV' or 'secondary'.

Output columns:
    bus_id         : PSS/E numeric bus ID
    bus_name       : bus name in the model
    bus_name_psse  : original PSS/E name (NaN for 500 kV buses where it matches)
    bus_type       : '500kV' or 'secondary'
    baskv_kv       : base voltage in kV
    ide            : PSS/E bus type (1=PQ, 2=PV, 3=slack, 4=isolated)
    ide_desc       : bus type description
    lat            : decimal latitude (WGS84)
    lon            : decimal longitude (WGS84)
    parent_bus_id  : 500 kV parent bus (NaN for 500 kV buses)
    name_geosadi   : assigned GeoSADI name (500 kV buses only)
"""

import os
import sys
from pathlib import Path
import yaml
import pandas as pd
import numpy as np

# =============================================================================
# CONFIGURATION
# =============================================================================

_cfg = yaml.safe_load(open(Path(__file__).parents[2] / "config.yaml"))
REPO_DIR     = Path(_cfg["repo_dir"])

BUSES_500_FILE = REPO_DIR / "data/network_500kv/buses_500kv_raw.csv"
BUSES_SEC_FILE = REPO_DIR / "data/network_500kv/buses_sec_raw.csv"
MANUAL_FILE    = REPO_DIR / "data/network_500kv/buses_PSSE_vs_geosadi.xlsx"
OUTPUT_DIR     = REPO_DIR / "data/network_500kv"
OUTPUT_FILE    = OUTPUT_DIR / "buses_final.csv"

IDE_DESC = {
    1: "PQ",
    2: "PV",
    3: "slack",
    4: "isolated",
}


# =============================================================================
# MAIN
# =============================================================================

def main():
    print("=" * 60)
    print("05_match_geosadi_coords.py -- consolidate buses with coordinates")
    print("=" * 60)

    for f in [BUSES_500_FILE, BUSES_SEC_FILE, MANUAL_FILE]:
        if not os.path.isfile(f):
            print(f"[ERROR] File not found:\n  {f}")
            sys.exit(1)

    # ==========================================================
    # 500 kV BUSES — coordinates from manual dictionary
    # ==========================================================
    buses_500 = pd.read_csv(BUSES_500_FILE)
    manual    = pd.read_excel(MANUAL_FILE)
    print(f"\n500 kV buses loaded       : {len(buses_500)}")
    print(f"Dictionary entries        : {len(manual)}")

    # Merge by bus_id
    manual_coords = manual[['bus_id', 'name_geosadi', 'lat', 'lon']].copy()
    buses_500 = buses_500.merge(manual_coords, on='bus_id', how='left')

    n_no_coord = buses_500['lat'].isna().sum()
    if n_no_coord:
        print(f"  ⚠ {n_no_coord} 500 kV buses without coordinates in dictionary:")
        for _, r in buses_500[buses_500['lat'].isna()].iterrows():
            print(f"    {r['bus_name']}")

    buses_500['bus_type']      = '500kV'
    buses_500['bus_name_psse'] = np.nan  # for 500 kV buses, bus_name already is the PSS/E name
    buses_500['parent_bus_id'] = np.nan
    buses_500['ide_desc']      = buses_500['ide'].map(IDE_DESC).fillna('unknown')

    print(f"  ✔ Coordinates assigned via manual dictionary")

    # ==========================================================
    # SECONDARY BUSES — inherit coordinates from 500 kV parent
    # ==========================================================
    buses_sec = pd.read_csv(BUSES_SEC_FILE)
    print(f"\nSecondary buses loaded    : {len(buses_sec)}")

    # Map parent_bus_id -> (lat, lon)
    parent_coords = buses_500[['bus_id', 'lat', 'lon']].set_index('bus_id')

    buses_sec['lat'] = buses_sec['parent_bus_id'].map(parent_coords['lat'])
    buses_sec['lon'] = buses_sec['parent_bus_id'].map(parent_coords['lon'])

    n_no_parent = buses_sec['lat'].isna().sum()
    if n_no_parent:
        print(f"  ⚠ {n_no_parent} secondary buses without coordinates (parent has no coord):")
        for _, r in buses_sec[buses_sec['lat'].isna()].iterrows():
            print(f"    {r['bus_name']}  parent={r['parent_bus_id']}")

    buses_sec['bus_type']     = 'secondary'
    buses_sec['name_geosadi'] = np.nan

    print(f"  ✔ Coordinates inherited from 500 kV parent bus")

    # No offset — secondary buses at the same substation intentionally
    # share coordinates (they are at the same physical location)

    # ==========================================================
    # CONSOLIDATE
    # ==========================================================
    cols = [
        'bus_id', 'bus_name', 'bus_name_psse', 'bus_type',
        'baskv_kv', 'ide', 'ide_desc',
        'vm_pu', 'va_deg',
        'lat', 'lon',
        'parent_bus_id', 'name_geosadi',
    ]

    df_final = pd.concat([buses_500[cols], buses_sec[cols]], ignore_index=True)
    df_final = df_final.sort_values(['bus_type', 'bus_id']).reset_index(drop=True)

    # ==========================================================
    # SUMMARY
    # ==========================================================
    print(f"\n{'='*60}")
    print(f"SUMMARY")
    print(f"{'='*60}")
    print(f"  500 kV buses      : {(df_final['bus_type']=='500kV').sum()}")
    print(f"  Secondary buses   : {(df_final['bus_type']=='secondary').sum()}")
    print(f"  TOTAL             : {len(df_final)}")
    print(f"\n  With coordinates  : {df_final['lat'].notna().sum()}")
    print(f"  Without coordinates: {df_final['lat'].isna().sum()}")

    print(f"\nVoltage distribution:")
    for kv, grp in df_final.groupby('baskv_kv'):
        kv_str = f"{int(kv)}kV" if kv == int(kv) else f"{kv:.1f}kV"
        print(f"  {kv_str:<10}: {len(grp)} buses")

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    df_final.to_csv(OUTPUT_FILE, index=False)

    print(f"\n✔ {OUTPUT_FILE}  ({len(df_final)} rows)")
    print("Next: 06_match_geosadi_geometry.py")


if __name__ == "__main__":
    main()
