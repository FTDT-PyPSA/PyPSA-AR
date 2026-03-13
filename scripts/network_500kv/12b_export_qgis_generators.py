"""
12b_export_qgis_generators.py
Agrega un layer de centrales electricas al GeoPackage existente para
visualizacion en QGIS.

Depende:
    data/network_500kv/generators_final.csv        (script 12)
    data/GIS_psse_geosadi_pypsaearth/balance_gen_carga.gpkg  (script 10b)

Output:
    Agrega layer 'centrales_electricas' al GeoPackage existente.

    Atributos del layer:
        gen_key               : clave unica PSS/E
        bus_name_origen       : nombre del bus origen en PSS/E
        nombre_geosadi        : nombre de la central en GeoSADI
        bus_conexion500kv_name: nodo del modelo al que conecta
        carrier               : tipo tecnologico
        pg_mw                 : despacho en snapshot PSS/E (MW)
        pt_mw                 : potencia instalada (MW)
        stat                  : estado en snapshot PSS/E (1=en servicio)
        match_type            : como se resolvio la conexion al modelo

    Se excluyen generadores con PT >= 9000 MVA (equivalentes ficticios PSS/E)
    y generadores sin coordenadas geograficas.

Correr desde WSL:
    python /mnt/c/Work/pypsa-ar-base/scripts/network_500kv/12b_export_qgis_generators.py
"""

import os
import sys
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point

# =============================================================================
# CONFIGURACION
# =============================================================================

DATA_DIR  = "/mnt/c/Work/pypsa-ar-base/data/network_500kv"
GIS_DIR   = "/mnt/c/Work/pypsa-ar-base/data/GIS_psse_geosadi_pypsaearth"

GEN_FILE  = os.path.join(DATA_DIR, "generators_final.csv")
GPKG_FILE = os.path.join(GIS_DIR,  "balance_gen_carga.gpkg")

LAYER_NAME = "centrales_electricas"
CRS        = "EPSG:4326"


# =============================================================================
# MAIN
# =============================================================================

def main():
    print("=" * 60)
    print("12b_export_qgis_generators.py -- centrales electricas -> QGIS")
    print("=" * 60)

    if not os.path.isfile(GEN_FILE):
        print("[ERROR] Archivo no encontrado:")
        print("  " + GEN_FILE)
        sys.exit(1)

    gen = pd.read_csv(GEN_FILE)
    print("Generadores cargados : " + str(len(gen)))

    # Excluir equivalentes ficticios (PT >= 9000)
    n_ficticios = len(gen[gen['pt_mw'] >= 9000])
    if n_ficticios > 0:
        print("  Excluidos PT=9999 (equivalentes ficticios): " + str(n_ficticios))
    gen = gen[gen['pt_mw'] < 9000].copy()

    # Separar con y sin coordenadas
    df_con = gen[gen['lat'].notna() & gen['lon'].notna()].copy()
    df_sin = gen[gen['lat'].isna()  | gen['lon'].isna()].copy()

    print("  Con coordenadas    : " + str(len(df_con)))
    print("  Sin coordenadas    : " + str(len(df_sin)) + "  (excluidos del layer)")

    if not df_sin.empty:
        print("\n  Centrales sin coordenadas:")
        for _, r in df_sin.iterrows():
            print("    " + str(r['bus_name_origen']).ljust(15) +
                  " carrier=" + str(r['carrier']).ljust(12) +
                  " pt=" + str(round(r['pt_mw'], 1)) + " MW")

    # Construir GeoDataFrame
    gdf = gpd.GeoDataFrame(
        df_con,
        geometry=[Point(r['lon'], r['lat']) for _, r in df_con.iterrows()],
        crs=CRS
    )

    cols = [
        'gen_key', 'bus_name_origen', 'nombre_geosadi',
        'bus_conexion500kv_name', 'carrier',
        'pg_mw', 'pt_mw', 'stat', 'match_type',
        'geometry',
    ]
    gdf = gdf[cols]

    # Reporte por carrier
    print("\n" + "=" * 60)
    print("RESUMEN POR CARRIER")
    print("=" * 60)
    for carrier, grp in gdf.groupby('carrier'):
        mw = grp['pt_mw'].sum()
        print("  " + str(carrier).ljust(15) + ": " +
              str(len(grp)).rjust(4) + " centrales   " +
              str(round(mw, 1)).rjust(10) + " MW")

    mw_total = gdf['pt_mw'].sum()
    print("\n  TOTAL              : " +
          str(len(gdf)).rjust(4) + " centrales   " +
          str(round(mw_total, 1)).rjust(10) + " MW")

    # Exportar layer al GPKG
    os.makedirs(GIS_DIR, exist_ok=True)
    gdf.to_file(GPKG_FILE, layer=LAYER_NAME, driver="GPKG")

    print("\nLayer '" + LAYER_NAME + "' agregado a " + GPKG_FILE)
    print("  " + str(len(gdf)) + " centrales exportadas")
    print("\nSimbologia sugerida en QGIS:")
    print("  Simbologia -> Categorizado por 'carrier'")
    print("  Tamanio de punto proporcional a pt_mw:")
    print("    sqrt(pt_mw) / 3")
    print("\nProximo: 12c_test_snapshot.py")


if __name__ == "__main__":
    main()
