"""
12b_export_qgis_generators.py
Adds a power plants layer to the network GeoPackage for visualization in QGIS.

Depends : data/network_500kv/generators_final.csv         (script 12)
          data/GIS_psse_geosadi_pypsaearth/network_500kv_qgis.gpkg  (script 07b)

Output  : adds layer 'power_plants' to network_500kv_qgis.gpkg

    Layer attributes:
        gen_key                : unique PSS/E key
        bus_name_origen        : PSS/E origin bus name
        geosadi_name           : power plant name in GeoSADI
        bus_conexion500kv_name : model node the generator connects to
        carrier                : technology type
        pg_mw                  : dispatch in PSS/E snapshot (MW)
        pt_mw                  : installed capacity (MW)
        stat                   : PSS/E snapshot status (1=in service)
        match_type             : how the model connection was resolved

    Generators with PT >= 9000 MVA (PSS/E fictitious equivalents) and
    generators without geographic coordinates are excluded.

Run from the repository root (pypsa-ar-base/):
    python scripts/network_500kv/12b_export_qgis_generators.py

Suggested QGIS symbology:
    Symbology -> Categorized by 'carrier'
    Point size proportional to pt_mw:
        sqrt(pt_mw) / 3
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

DATA_DIR  = REPO_DIR / "data/network_500kv"
GIS_DIR   = REPO_DIR / "data/GIS_psse_geosadi_pypsaearth"

GEN_FILE  = DATA_DIR / "generators_final.csv"
GPKG_FILE = GIS_DIR  / "network_500kv_qgis.gpkg"

LAYER_NAME = "power_plants"
CRS        = "EPSG:4326"


# =============================================================================
# MAIN
# =============================================================================

def main():
    print("=" * 60)
    print("12b_export_qgis_generators.py -- power plants layer -> QGIS")
    print("=" * 60)

    if not os.path.isfile(GEN_FILE):
        print(f"[ERROR] File not found:\n  {GEN_FILE}")
        sys.exit(1)

    gen = pd.read_csv(GEN_FILE)
    print(f"Generators loaded : {len(gen)}")

    # Exclude fictitious PSS/E equivalents (PT >= 9000)
    n_fictitious = len(gen[gen['pt_mw'] >= 9000])
    if n_fictitious > 0:
        print(f"  Excluded PT=9999 (fictitious equivalents): {n_fictitious}")
    gen = gen[gen['pt_mw'] < 9000].copy()

    # Split by coordinate availability
    df_with_coord    = gen[gen['lat'].notna() & gen['lon'].notna()].copy()
    df_without_coord = gen[gen['lat'].isna()  | gen['lon'].isna()].copy()

    print(f"  With coordinates    : {len(df_with_coord)}")
    print(f"  Without coordinates : {len(df_without_coord)}  (excluded from layer)")

    if not df_without_coord.empty:
        print("\n  Power plants without coordinates:")
        for _, r in df_without_coord.iterrows():
            print(f"    {str(r['bus_name_origen']):<15}"
                  f"  carrier={str(r['carrier']):<12}"
                  f"  pt={round(r['pt_mw'], 1)} MW")

    # Build GeoDataFrame
    gdf = gpd.GeoDataFrame(
        df_with_coord,
        geometry=[Point(r['lon'], r['lat']) for _, r in df_with_coord.iterrows()],
        crs=CRS
    )

    cols = [
        'gen_key', 'bus_name_origen', 'geosadi_name',
        'bus_conexion500kv_name', 'carrier',
        'pg_mw', 'pt_mw', 'stat', 'match_type',
        'geometry',
    ]
    gdf = gdf[cols]

    # Summary by carrier
    print("\n" + "=" * 60)
    print("SUMMARY BY CARRIER")
    print("=" * 60)
    for carrier, grp in gdf.groupby('carrier'):
        mw = grp['pt_mw'].sum()
        print(f"  {str(carrier):<15}: {len(grp):>4} power plants   {round(mw, 1):>10} MW")

    mw_total = gdf['pt_mw'].sum()
    print(f"\n  TOTAL              : {len(gdf):>4} power plants   {round(mw_total, 1):>10} MW")

    # Export layer to GPKG
    os.makedirs(GIS_DIR, exist_ok=True)
    gdf.to_file(GPKG_FILE, layer=LAYER_NAME, driver="GPKG")

    print(f"\nLayer '{LAYER_NAME}' added to {GPKG_FILE}")
    print(f"  {len(gdf)} power plants exported")
    print("Next: 13_clean_valores_2024")


if __name__ == "__main__":
    main()
