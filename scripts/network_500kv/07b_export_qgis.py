"""
07b_export_qgis.py
Exporta la red 500 kV a GeoPackage para visualizacion en QGIS.

Depende de:
    data/network_500kv/buses_final.csv          (script 05 — todos los buses)
    data/network_500kv/lines_500kv_final.csv    (script 06 — lineas con geometria)
    data/network_500kv/trafos_500kv_raw.csv     (script 03 — transformadores)

Output:
    data/GIS_psse_geosadi_pypsaearth/red_500kv_qgis.gpkg

    Layers:
        buses_500kv  : puntos — buses 500 kV con coordenadas GeoSADI
        buses_sec    : puntos — buses secundarios heredando coordenadas del padre
        lines_500kv  : lineas con geometria GeoSADI
        trafos_500kv : puntos — transformadores en coordenadas del bus 500 kV padre

Correr desde WSL:
    python /mnt/c/Work/pypsa-ar-base/scripts/network_500kv/07b_export_qgis.py

Categorias utiles para simbologia en QGIS:
    lines_500kv.match_status : directo | paralela | manual_geo | compensador |
                                pendiente_bus | sin_match
    lines_500kv.element_type : line | series_compensator
    buses_sec.ide_desc       : PQ | PV | slack | isolated
    buses_sec.baskv_kv       : tension del bus secundario
"""

import os
import sys
import pandas as pd
import geopandas as gpd
from shapely import wkt
from shapely.geometry import Point

# =============================================================================
# CONFIGURACION
# =============================================================================

DATA_DIR     = "/mnt/c/Work/pypsa-ar-base/data/network_500kv"
BUSES_FILE   = os.path.join(DATA_DIR, "buses_final.csv")
LINES_FILE   = os.path.join(DATA_DIR, "lines_500kv_final.csv")
TRAFOS_FILE  = os.path.join(DATA_DIR, "trafos_500kv_raw.csv")
OUTPUT_FILE  = "/mnt/c/Work/pypsa-ar-base/data/GIS_psse_geosadi_pypsaearth/red_500kv_qgis.gpkg"

CRS = "EPSG:4326"   # WGS84


# =============================================================================
# MAIN
# =============================================================================

def main():
    print("=" * 60)
    print("07b_export_qgis.py -- exportar red 500 kV a GeoPackage")
    print("=" * 60)

    for f in [BUSES_FILE, LINES_FILE, TRAFOS_FILE]:
        if not os.path.isfile(f):
            print(f"[ERROR] Archivo no encontrado:\n  {f}")
            sys.exit(1)

    buses  = pd.read_csv(BUSES_FILE)
    lines  = pd.read_csv(LINES_FILE)
    trafos = pd.read_csv(TRAFOS_FILE)

    buses_500 = buses[buses['bus_type'] == '500kV'].copy()
    buses_sec = buses[buses['bus_type'] == 'secundario'].copy()

    # --- Layer buses_500kv ---
    print(f"\nProcesando buses 500 kV...")
    b500_con = buses_500[buses_500["lat"].notna() & buses_500["lon"].notna()].copy()
    b500_sin = buses_500[buses_500["lat"].isna() | buses_500["lon"].isna()].copy()
    if not b500_sin.empty:
        print(f"  ⚠ {len(b500_sin)} buses 500 kV sin coordenadas (excluidos):")
        for _, r in b500_sin.iterrows():
            print(f"    {r['bus_name']}")
    gdf_buses_500 = gpd.GeoDataFrame(
        b500_con,
        geometry=[Point(r["lon"], r["lat"]) for _, r in b500_con.iterrows()],
        crs=CRS
    )
    print(f"  ✔ {len(gdf_buses_500)} buses exportados")

    # --- Layer buses_sec ---
    print(f"\nProcesando buses secundarios...")
    bsec_con = buses_sec[buses_sec["lat"].notna() & buses_sec["lon"].notna()].copy()
    bsec_sin = buses_sec[buses_sec["lat"].isna() | buses_sec["lon"].isna()].copy()
    if not bsec_sin.empty:
        print(f"  ⚠ {len(bsec_sin)} buses secundarios sin coordenadas (excluidos):")
        for _, r in bsec_sin.iterrows():
            print(f"    {r['bus_name']}")
    gdf_buses_sec = gpd.GeoDataFrame(
        bsec_con,
        geometry=[Point(r["lon"], r["lat"]) for _, r in bsec_con.iterrows()],
        crs=CRS
    )
    print(f"  ✔ {len(gdf_buses_sec)} buses exportados")

    # --- Layer lines_500kv ---
    print(f"\nProcesando lineas...")
    lines_con = lines[lines["geometry"].notna() & (lines["geometry"] != "")].copy()
    lines_sin = lines[lines["geometry"].isna() | (lines["geometry"] == "")].copy()
    if not lines_sin.empty:
        print(f"  ⚠ {len(lines_sin)} lineas sin geometria (excluidas):")
        for _, r in lines_sin.iterrows():
            print(f"    {r['line_key']:<40}  [{r['match_status']}]")

    geoms, failed = [], []
    for idx, row in lines_con.iterrows():
        try:
            geoms.append(wkt.loads(row["geometry"]))
        except:
            geoms.append(None)
            failed.append(row["line_key"])
    if failed:
        print(f"  ⚠ {len(failed)} geometrias no parseables:")
        for k in failed:
            print(f"    {k}")

    lines_con["geom"] = geoms
    lines_con = lines_con[lines_con["geom"].notna()].copy()
    gdf_lines = gpd.GeoDataFrame(lines_con, geometry="geom", crs=CRS)
    gdf_lines = gdf_lines.drop(columns=["geometry"], errors="ignore")
    print(f"  ✔ {len(gdf_lines)} lineas exportadas")

    # --- Layer trafos_500kv ---
    # Los trafos se plotean en las coordenadas del bus_i (500kV padre)
    print(f"\nProcesando transformadores...")
    coord_map = buses_500[['bus_id', 'lat', 'lon']].set_index('bus_id')
    trafos['lat'] = trafos['bus_i'].map(coord_map['lat'])
    trafos['lon'] = trafos['bus_i'].map(coord_map['lon'])
    trafos_con = trafos[trafos["lat"].notna() & trafos["lon"].notna()].copy()
    trafos_sin = trafos[trafos["lat"].isna() | trafos["lon"].isna()].copy()
    if not trafos_sin.empty:
        print(f"  ⚠ {len(trafos_sin)} trafos sin coordenadas (excluidos):")
        for _, r in trafos_sin.iterrows():
            print(f"    {r['trafo_key']}")
    gdf_trafos = gpd.GeoDataFrame(
        trafos_con,
        geometry=[Point(r["lon"], r["lat"]) for _, r in trafos_con.iterrows()],
        crs=CRS
    )
    print(f"  ✔ {len(gdf_trafos)} trafos exportados")

    # --- Exportar ---
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    print(f"\nExportando a {OUTPUT_FILE}...")
    gdf_buses_500.to_file(OUTPUT_FILE, layer="buses_500kv",  driver="GPKG")
    gdf_buses_sec.to_file(OUTPUT_FILE, layer="buses_sec",    driver="GPKG")
    gdf_lines.to_file(    OUTPUT_FILE, layer="lines_500kv",  driver="GPKG")
    gdf_trafos.to_file(   OUTPUT_FILE, layer="trafos_500kv", driver="GPKG")

    # --- Reporte ---
    print("\n" + "=" * 60)
    print("RESUMEN")
    print("=" * 60)
    print(f"  buses_500kv  : {len(gdf_buses_500)} / {len(buses_500)}")
    print(f"  buses_sec    : {len(gdf_buses_sec)} / {len(buses_sec)}")
    print(f"  lines_500kv  : {len(gdf_lines)} / {len(lines)}")
    print(f"  trafos_500kv : {len(gdf_trafos)} / {len(trafos)}")

    print("\nLineas por match_status:")
    for status, grp in lines.groupby("match_status"):
        con_geo = (grp["geometry"].notna() & (grp["geometry"] != "")).sum()
        print(f"  {status:<20} : {len(grp):>3} total  ({con_geo} con geometria)")

    print(f"\n✔ {OUTPUT_FILE}")
    print("Abrir en QGIS: Capa -> Agregar capa vectorial -> seleccionar .gpkg")


if __name__ == "__main__":
    main()
