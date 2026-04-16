"""
07b_export_qgis.py
Exports the 500 kV network to a GeoPackage for visualization in QGIS.

Depends : data/network_500kv/buses_final.csv          (script 05 — all buses)
          data/network_500kv/lines_500kv_final.csv    (script 06 — lines with geometry)
          data/network_500kv/trafos_500kv_raw.csv     (script 03 — transformers)
          GEOSADI/GEOJSON/lineas_alta_tension.geojson (external — download from GitHub Releases, place in external_data_dir/GEOSADI/GEOJSON/)

Output  : data/GIS_psse_geosadi_pypsaearth/network_500kv_qgis.gpkg

    Layers:
        buses_500kv       : points — 500 kV buses with GeoSADI coordinates
        secondary_buses   : points — secondary buses inheriting parent coordinates
        lines_500kv       : lines with GeoSADI geometry
        transformers_500kv: points — transformers at 500 kV parent bus coordinates

Run from the repository root (pypsa-ar-base/):
    python scripts/network_500kv/07b_export_qgis.py

Useful categories for QGIS symbology:
    lines_500kv.match_status : direct | parallel | manual_geo | series_compensator |
                               pending_bus | no_match
    lines_500kv.element_type : line | series_compensator
    secondary_buses.ide_desc : PQ | PV | slack | isolated
    secondary_buses.baskv_kv : secondary bus voltage

Special case — Argentina–Brazil interconnection:
    The GARABI substation (Brazil) and the Rincón de Santa María–Garabi
    interconnection line are added manually for visualization purposes.
    This line is modeled as a Link in PyPSA (script 08), not as a Branch
    in PSS/E, so it does not appear in lines_500kv_final.csv.
    Geometry is taken from GeoSADI line id=1408.
    GARABI coordinates: lat=-28.2545246970571, lon=-55.6718056442151.
    RINCÓN DE SANTA MARÍA is already in buses_final.csv (bus_id=5002).
"""

import os
import sys
import json
from pathlib import Path
import yaml
import pandas as pd
import geopandas as gpd
from shapely import wkt
from shapely.geometry import Point, shape

# =============================================================================
# CONFIGURATION
# =============================================================================

_cfg = yaml.safe_load(open(Path(__file__).parents[2] / "config.yaml"))
REPO_DIR     = Path(_cfg["repo_dir"])
EXTERNAL_DIR = Path(_cfg["external_data_dir"])

DATA_DIR    = REPO_DIR / "data/network_500kv"
GIS_DIR     = REPO_DIR / "data/GIS_psse_geosadi_pypsaearth"
BUSES_FILE  = DATA_DIR / "buses_final.csv"
LINES_FILE  = DATA_DIR / "lines_500kv_final.csv"
TRAFOS_FILE = DATA_DIR / "trafos_500kv_raw.csv"
GEOJSON_FILE = EXTERNAL_DIR / "GEOSADI/GEOJSON/lineas_alta_tension.geojson"
OUTPUT_FILE = GIS_DIR / "network_500kv_qgis.gpkg"

CRS = "EPSG:4326"

# --- Argentina–Brazil interconnection (hardcoded for visualization) ---
GARABI_LAT             = -28.2545246970571
GARABI_LON             = -55.6718056442151
RINCON_BUS_ID          = 5002
BRASIL_LINE_GEOSADI_ID = 1408


# =============================================================================
# MAIN
# =============================================================================

def main():
    print("=" * 60)
    print("07b_export_qgis.py -- export 500 kV network to GeoPackage")
    print("=" * 60)

    for f in [BUSES_FILE, LINES_FILE, TRAFOS_FILE, GEOJSON_FILE]:
        if not os.path.isfile(f):
            print(f"[ERROR] File not found:\n  {f}")
            sys.exit(1)

    buses  = pd.read_csv(BUSES_FILE)
    lines  = pd.read_csv(LINES_FILE)
    trafos = pd.read_csv(TRAFOS_FILE)

    buses_500 = buses[buses['bus_type'] == '500kV'].copy()
    buses_sec = buses[buses['bus_type'] == 'secondary'].copy()

    # --- Layer buses_500kv ---
    print(f"\nProcessing 500 kV buses...")
    b500_con = buses_500[buses_500["lat"].notna() & buses_500["lon"].notna()].copy()
    b500_sin = buses_500[buses_500["lat"].isna()  | buses_500["lon"].isna()].copy()
    if not b500_sin.empty:
        print(f"  ⚠ {len(b500_sin)} 500 kV buses without coordinates (excluded):")
        for _, r in b500_sin.iterrows():
            print(f"    {r['bus_name']}")

    # Add GARABI as extra bus for visualization
    rincon = buses_500[buses_500['bus_id'] == RINCON_BUS_ID]
    garabi_row = pd.DataFrame([{
        'bus_id':        99999,
        'bus_name':      'GARABI',
        'bus_name_psse': 'GARABI',
        'bus_type':      '500kV',
        'baskv_kv':      500.0,
        'ide':           1,
        'ide_desc':      'PQ',
        'lat':           GARABI_LAT,
        'lon':           GARABI_LON,
        'parent_bus_id': None,
        'name_geosadi':  'GARABI',
        'note':          'Brazil interconnection — visualization only',
    }])
    b500_con = pd.concat([b500_con, garabi_row], ignore_index=True)

    gdf_buses_500 = gpd.GeoDataFrame(
        b500_con,
        geometry=[Point(r["lon"], r["lat"]) for _, r in b500_con.iterrows()],
        crs=CRS
    )
    print(f"  ✔ {len(gdf_buses_500)} buses exported (includes GARABI)")

    # --- Layer secondary_buses ---
    print(f"\nProcessing secondary buses...")
    bsec_con = buses_sec[buses_sec["lat"].notna() & buses_sec["lon"].notna()].copy()
    bsec_sin = buses_sec[buses_sec["lat"].isna()  | buses_sec["lon"].isna()].copy()
    if not bsec_sin.empty:
        print(f"  ⚠ {len(bsec_sin)} secondary buses without coordinates (excluded):")
        for _, r in bsec_sin.iterrows():
            print(f"    {r['bus_name']}")
    gdf_buses_sec = gpd.GeoDataFrame(
        bsec_con,
        geometry=[Point(r["lon"], r["lat"]) for _, r in bsec_con.iterrows()],
        crs=CRS
    )
    print(f"  ✔ {len(gdf_buses_sec)} secondary buses exported")

    # --- Layer lines_500kv ---
    print(f"\nProcessing lines...")
    lines_con = lines[lines["geometry"].notna() & (lines["geometry"] != "")].copy()
    lines_sin = lines[lines["geometry"].isna()  | (lines["geometry"] == "")].copy()
    if not lines_sin.empty:
        print(f"  ℹ {len(lines_sin)} lines without geometry (compensators/pending_bus/no_match — excluded from geometry layer)")
    gdf_lines = gpd.GeoDataFrame(
        lines_con,
        geometry=lines_con["geometry"].apply(lambda g: wkt.loads(g) if g else None),
        crs=CRS
    )
    print(f"  ✔ {len(gdf_lines)} lines with geometry exported")

    # --- Add Argentina–Brazil interconnection line ---
    print(f"\nAdding Argentina–Brazil interconnection line (GeoSADI id={BRASIL_LINE_GEOSADI_ID})...")
    with open(GEOJSON_FILE, encoding='utf-8') as f:
        gj = json.load(f)

    brasil_feat = next(
        (feat for feat in gj['features'] if feat['properties'].get('id') == BRASIL_LINE_GEOSADI_ID),
        None
    )
    if brasil_feat:
        brasil_geom = shape(brasil_feat['geometry'])
        rincon_name = rincon['bus_name'].values[0] if not rincon.empty else 'RINCON'
        brasil_row = gpd.GeoDataFrame([{
            'line_id':      99999,
            'line_key':     f'{rincon_name}-GARABI-1',
            'bus_i':        RINCON_BUS_ID,
            'bus_j':        99999,
            'element_type': 'interconnection',
            'match_status': 'manual_geo',
            'geo_nombre':   brasil_feat['properties'].get('Nombre', ''),
            'geometry':     brasil_geom,
            'note':         'Argentina–Brazil interconnection — visualization only',
        }], crs=CRS)
        gdf_lines = pd.concat([gdf_lines, brasil_row], ignore_index=True)
        gdf_lines = gpd.GeoDataFrame(gdf_lines, geometry='geometry', crs=CRS)
        print(f"  ✔ Interconnection line added: {brasil_feat['properties'].get('Nombre', '')}")
    else:
        print(f"  ⚠ GeoSADI line id={BRASIL_LINE_GEOSADI_ID} not found in GeoJSON")

    # --- Layer transformers_500kv ---
    print(f"\nProcessing transformers...")
    bus_coords = buses_500.set_index('bus_id')[['lat', 'lon']]
    trafos = trafos.copy()
    trafos['lat'] = trafos['bus_i'].map(bus_coords['lat'])
    trafos['lon'] = trafos['bus_i'].map(bus_coords['lon'])

    trafos_con = trafos[trafos["lat"].notna() & trafos["lon"].notna()].copy()
    trafos_sin = trafos[trafos["lat"].isna()  | trafos["lon"].isna()].copy()
    if not trafos_sin.empty:
        print(f"  ⚠ {len(trafos_sin)} transformers without coordinates (excluded):")
        for _, r in trafos_sin.iterrows():
            print(f"    {r['trafo_key']}")
    gdf_trafos = gpd.GeoDataFrame(
        trafos_con,
        geometry=[Point(r["lon"], r["lat"]) for _, r in trafos_con.iterrows()],
        crs=CRS
    )
    print(f"  ✔ {len(gdf_trafos)} transformers exported")

    # --- Export ---
    os.makedirs(GIS_DIR, exist_ok=True)
    print(f"\nExporting to {OUTPUT_FILE}...")
    gdf_buses_500.to_file(OUTPUT_FILE, layer="buses_500kv",        driver="GPKG")
    gdf_buses_sec.to_file(OUTPUT_FILE, layer="secondary_buses",    driver="GPKG")
    gdf_lines.to_file(    OUTPUT_FILE, layer="lines_500kv",        driver="GPKG")
    gdf_trafos.to_file(   OUTPUT_FILE, layer="transformers_500kv", driver="GPKG")

    # --- Summary ---
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"  buses_500kv        : {len(gdf_buses_500)} / {len(buses_500) + 1} (includes GARABI)")
    print(f"  secondary_buses    : {len(gdf_buses_sec)} / {len(buses_sec)}")
    print(f"  lines_500kv        : {len(gdf_lines)} / {len(lines) + 1} (includes interconnection)")
    print(f"  transformers_500kv : {len(gdf_trafos)} / {len(trafos)}")

    print("\nLines by match_status:")
    for status, grp in gdf_lines.groupby("match_status"):
        print(f"  {status:<22} : {len(grp):>3}")

    print(f"\n✔ {OUTPUT_FILE}")
    print("Open in QGIS: Layer -> Add Vector Layer -> select .gpkg")
    print("Next: 08_build_pypsa_network.py")


if __name__ == "__main__":
    main()
