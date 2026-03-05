"""
05b_export_qgis.py
Exporta la red 500 kV a GeoPackage para visualizacion en QGIS.

Depende de:
    buses_500kv_final.csv   (output script 03)
    lines_500kv_final.csv   (output script 04)

Output:
    data/network_500kv/red_500kv_qgis.gpkg

    Layers:
        buses_500kv  : puntos con todos los atributos de los buses
        lines_500kv  : lineas con todos los atributos de las lineas
                       coloreables por match_status, in_service, element_type

Correr desde WSL:
    python /mnt/c/Work/pypsa-ar-base/scripts/network_500kv/05b_export_qgis.py

Uso en QGIS:
    Capa -> Agregar capa -> Agregar capa vectorial -> seleccionar .gpkg
    Seleccionar layer buses_500kv o lines_500kv

Categorias utiles para simbologia en QGIS:
    lines_500kv.match_status : directo | paralela | manual_geo | compensador |
                                pendiente_bus | sin_match
    lines_500kv.in_service   : True | False
    lines_500kv.element_type : line | series_compensator
    buses_500kv.match_status : ok | consultar | pendiente
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

DATA_DIR    = "/mnt/c/Work/pypsa-ar-base/data/network_500kv"
BUSES_FILE  = os.path.join(DATA_DIR, "buses_500kv_final.csv")
LINES_FILE  = os.path.join(DATA_DIR, "lines_500kv_final.csv")
OUTPUT_FILE = os.path.join(DATA_DIR, "red_500kv_qgis.gpkg")

CRS = "EPSG:4326"   # WGS84


# =============================================================================
# MAIN
# =============================================================================

def main():
    print("=" * 60)
    print("05b_export_qgis.py -- exportar red 500 kV a GeoPackage")
    print("=" * 60)

    for f in [BUSES_FILE, LINES_FILE]:
        if not os.path.isfile(f):
            print(f"[ERROR] Archivo no encontrado:\n  {f}")
            sys.exit(1)

    # --- Buses ---
    print("\nProcesando buses...")
    buses = pd.read_csv(BUSES_FILE)
    buses_con_coord = buses[buses["lat"].notna() & buses["lon"].notna()].copy()
    buses_sin_coord = buses[buses["lat"].isna() | buses["lon"].isna()].copy()

    if not buses_sin_coord.empty:
        print(f"  ⚠ {len(buses_sin_coord)} buses sin coordenadas (excluidos de la capa):")
        for _, r in buses_sin_coord.iterrows():
            print(f"    {r['bus_name']}")

    gdf_buses = gpd.GeoDataFrame(
        buses_con_coord,
        geometry=[Point(r["lon"], r["lat"]) for _, r in buses_con_coord.iterrows()],
        crs=CRS
    )
    print(f"  ✔ {len(gdf_buses)} buses con coordenadas")

    # --- Lineas ---
    print("\nProcesando lineas...")
    lines = pd.read_csv(LINES_FILE)

    lines_con_geo = lines[lines["geometry"].notna() & (lines["geometry"] != "")].copy()
    lines_sin_geo = lines[lines["geometry"].isna() | (lines["geometry"] == "")].copy()

    if not lines_sin_geo.empty:
        print(f"  ⚠ {len(lines_sin_geo)} lineas sin geometria (excluidas de la capa):")
        for _, r in lines_sin_geo.iterrows():
            print(f"    {r['line_key']:<40}  [{r['match_status']}]")

    geoms = []
    failed = []
    for idx, row in lines_con_geo.iterrows():
        try:
            geoms.append(wkt.loads(row["geometry"]))
        except Exception as e:
            geoms.append(None)
            failed.append(row["line_key"])

    if failed:
        print(f"  ⚠ {len(failed)} geometrias no parseables:")
        for k in failed:
            print(f"    {k}")

    lines_con_geo = lines_con_geo.copy()
    lines_con_geo["geom"] = geoms
    lines_con_geo = lines_con_geo[lines_con_geo["geom"].notna()]

    gdf_lines = gpd.GeoDataFrame(lines_con_geo, geometry="geom", crs=CRS)
    gdf_lines = gdf_lines.drop(columns=["geometry"], errors="ignore")
    print(f"  ✔ {len(gdf_lines)} lineas con geometria")

    # --- Exportar ---
    print(f"\nExportando a {OUTPUT_FILE}...")

    gdf_buses.to_file(OUTPUT_FILE, layer="buses_500kv", driver="GPKG")
    gdf_lines.to_file(OUTPUT_FILE, layer="lines_500kv", driver="GPKG")

    # --- Reporte ---
    print("\n" + "=" * 60)
    print("RESUMEN")
    print("=" * 60)
    print(f"  Buses exportados  : {len(gdf_buses)} / {len(buses)}")
    print(f"  Lineas exportadas : {len(gdf_lines)} / {len(lines)}")

    print("\nLineas por match_status:")
    for status, grp in lines.groupby("match_status"):
        con_geo = (grp["geometry"].notna() & (grp["geometry"] != "")).sum()
        print(f"  {status:<20} : {len(grp):>3} total  ({con_geo} con geometria)")

    print(f"\n✔ {OUTPUT_FILE}")
    print("Abrir en QGIS: Capa -> Agregar capa vectorial -> seleccionar .gpkg")


if __name__ == "__main__":
    main()
