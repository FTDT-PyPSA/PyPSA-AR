"""
10b_visualize_qgis.py
Exports a generation/load balance layer per node to a GeoPackage for
visualization in QGIS.

Depends : data/network_500kv/generators_mapped.csv  (script 09)
          data/network_500kv/loads_mapped.csv        (script 10)
          data/network_500kv/buses_final.csv         (script 05)

Output  : data/GIS_psse_geosadi_pypsaearth/generation_load_balance.gpkg
    Layer: 'generation_load_balance'

    Layer attributes:
        bus_id       : bus ID in the model
        bus_name     : bus name
        bus_type     : '500kV' or 'secondary'
        baskv_kv     : base voltage in kV
        pg_mw        : total active generation assigned to node (stat=1, excludes pt=9999)
        pl_mw        : total active demand assigned to node (stat=1)
        balance_mw   : pg_mw - pl_mw (positive = net generation, negative = net load)
        n_generators : number of generators assigned
        n_loads      : number of loads assigned

Run from the repository root (pypsa-ar-base/):
    python scripts/network_500kv/10b_visualize_qgis.py
"""

import os
import sys
from pathlib import Path
import yaml
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point

# =============================================================================
# CONFIGURATION
# =============================================================================

_cfg = yaml.safe_load(open(Path(__file__).parents[2] / "config.yaml"))
REPO_DIR = Path(_cfg["repo_dir"])

DATA_DIR   = REPO_DIR / "data/network_500kv"
GIS_DIR    = REPO_DIR / "data/GIS_psse_geosadi_pypsaearth"

BUSES_FILE = DATA_DIR / "buses_final.csv"
GEN_FILE   = DATA_DIR / "generators_mapped.csv"
LOADS_FILE = DATA_DIR / "loads_mapped.csv"
GPKG_FILE  = GIS_DIR  / "generation_load_balance.gpkg"

LAYER_NAME = "generation_load_balance"
CRS        = "EPSG:4326"


# =============================================================================
# MAIN
# =============================================================================

def main():
    print("=" * 60)
    print("10b_visualize_qgis.py -- generation/load balance per node -> QGIS")
    print("=" * 60)

    for f in [BUSES_FILE, GEN_FILE, LOADS_FILE]:
        if not os.path.isfile(f):
            print(f"[ERROR] File not found:\n  {f}")
            sys.exit(1)

    buses = pd.read_csv(BUSES_FILE)
    gen   = pd.read_csv(GEN_FILE)
    loads = pd.read_csv(LOADS_FILE)

    print(f"\nBuses loaded       : {len(buses)}")
    print(f"Generators loaded  : {len(gen)}")
    print(f"Loads loaded       : {len(loads)}")

    # --- Generation per bus ---
    # stat=1 only, exclude no_connection and pt=9999
    gen_active = gen[
        (gen['match_type'] != 'no_connection') &
        (gen['stat'] == 1) &
        (gen['pt_mw'] < 9990)
    ].copy()

    gen_per_bus = (
        gen_active.groupby('bus_conexion500kv')
        .agg(
            pg_mw        = ('pg_mw',   'sum'),
            n_generators = ('gen_key', 'count'),
        )
        .reset_index()
        .rename(columns={'bus_conexion500kv': 'bus_id'})
    )
    gen_per_bus['bus_id'] = gen_per_bus['bus_id'].astype(int)

    # --- Load per bus ---
    loads_active = loads[
        (loads['match_type'] != 'no_connection') &
        (loads['stat'] == 1)
    ].copy()

    loads_per_bus = (
        loads_active.groupby('bus_destination')
        .agg(
            pl_mw   = ('pl_mw',    'sum'),
            n_loads = ('load_key', 'count'),
        )
        .reset_index()
        .rename(columns={'bus_destination': 'bus_id'})
    )
    loads_per_bus['bus_id'] = loads_per_bus['bus_id'].astype(int)

    # --- Merge with buses ---
    df = buses[['bus_id', 'bus_name', 'bus_type', 'baskv_kv', 'lat', 'lon']].copy()
    df = df.merge(gen_per_bus,   on='bus_id', how='left')
    df = df.merge(loads_per_bus, on='bus_id', how='left')

    df['pg_mw']        = df['pg_mw'].fillna(0.0)
    df['pl_mw']        = df['pl_mw'].fillna(0.0)
    df['n_generators'] = df['n_generators'].fillna(0).astype(int)
    df['n_loads']      = df['n_loads'].fillna(0).astype(int)
    df['balance_mw']   = df['pg_mw'] - df['pl_mw']

    # --- Summary ---
    print(f"\n{'='*60}")
    print(f"SUMMARY")
    print(f"{'='*60}")
    print(f"  Buses with generation : {(df['pg_mw'] > 0).sum()}")
    print(f"  Buses with demand     : {(df['pl_mw'] > 0).sum()}")
    print(f"  Buses with both       : {((df['pg_mw'] > 0) & (df['pl_mw'] > 0)).sum()}")
    print(f"  Buses with neither    : {((df['pg_mw'] == 0) & (df['pl_mw'] == 0)).sum()}")
    print(f"\n  Total PG in layer     : {df['pg_mw'].sum():>10,.1f} MW")
    print(f"  Total PL in layer     : {df['pl_mw'].sum():>10,.1f} MW")
    print(f"  Net balance           : {df['balance_mw'].sum():>10,.1f} MW")

    print(f"\n  Top 10 by PG:")
    for _, r in df.nlargest(10, 'pg_mw').iterrows():
        print(f"    {r.bus_name:<30} pg={r.pg_mw:>8,.1f} MW  pl={r.pl_mw:>8,.1f} MW  bal={r.balance_mw:>+8,.1f} MW")

    print(f"\n  Top 10 by PL:")
    for _, r in df.nlargest(10, 'pl_mw').iterrows():
        print(f"    {r.bus_name:<30} pg={r.pg_mw:>8,.1f} MW  pl={r.pl_mw:>8,.1f} MW  bal={r.balance_mw:>+8,.1f} MW")

    print(f"\n  Top 10 by surplus (net generation):")
    for _, r in df.nlargest(10, 'balance_mw').iterrows():
        print(f"    {r.bus_name:<30} bal={r.balance_mw:>+8,.1f} MW")

    print(f"\n  Top 10 by deficit (net load):")
    for _, r in df.nsmallest(10, 'balance_mw').iterrows():
        print(f"    {r.bus_name:<30} bal={r.balance_mw:>+8,.1f} MW")

    # --- Build GeoDataFrame ---
    df_with_coord    = df[df['lat'].notna() & df['lon'].notna()].copy()
    df_without_coord = df[df['lat'].isna()  | df['lon'].isna()].copy()

    if not df_without_coord.empty:
        print(f"\n  {len(df_without_coord)} buses without coordinates (excluded from layer):")
        for _, r in df_without_coord.iterrows():
            print(f"    {r.bus_name}")

    gdf = gpd.GeoDataFrame(
        df_with_coord,
        geometry=[Point(r['lon'], r['lat']) for _, r in df_with_coord.iterrows()],
        crs=CRS
    )

    gdf = gdf[[
        'bus_id', 'bus_name', 'bus_type', 'baskv_kv',
        'pg_mw', 'pl_mw', 'balance_mw',
        'n_generators', 'n_loads',
        'geometry',
    ]]

    os.makedirs(GIS_DIR, exist_ok=True)
    gdf.to_file(GPKG_FILE, layer=LAYER_NAME, driver="GPKG")

    print(f"\n✔ Layer '{LAYER_NAME}' exported to {GPKG_FILE}")
    print(f"  {len(gdf)} buses")
    print(f"\nSuggested QGIS symbology:")
    print(f"  Rule-based symbology:")
    print(f"    balance_mw > 0  -> green circle, size = sqrt(balance_mw) / 3")
    print(f"    balance_mw < 0  -> red circle,   size = sqrt(abs(balance_mw)) / 3")
    print(f"    balance_mw = 0  -> small grey circle")
    print("Next: 11_add_geo_to_generators.py")


if __name__ == "__main__":
    main()
