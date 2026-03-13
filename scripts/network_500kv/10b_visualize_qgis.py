"""
10b_visualize_qgis.py
Agrega un layer de balance de generacion y demanda por nodo al GeoPackage
existente para visualizacion en QGIS.

Depende:
    data/network_500kv/generators_mapped.csv   (script 09)
    data/network_500kv/loads_mapped.csv        (script 10)
    data/network_500kv/buses_final.csv         (script 05)

Output:
    data/GIS_psse_geosadi_pypsaearth/balance_gen_carga.gpkg
    Layer: 'balance_por_bus'

    Atributos del layer:
        bus_id           : ID del bus en el modelo
        bus_name         : nombre del bus
        bus_type         : '500kV' o 'secundario'
        baskv_kv         : tension base del bus
        pg_mw            : generacion activa total asignada al nodo (STAT=1, excluye PT=9999)
        pl_mw            : demanda activa total asignada al nodo (STAT=1)
        balance_mw       : pg_mw - pl_mw (positivo = generacion neta, negativo = carga neta)
        n_generadores    : cantidad de generadores asignados
        n_cargas         : cantidad de cargas asignadas

Correr desde WSL:
    python /mnt/c/Work/pypsa-ar-base/scripts/network_500kv/10b_visualize_qgis.py
"""

import os
import sys
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point

# =============================================================================
# CONFIGURACION
# =============================================================================

DATA_DIR   = "/mnt/c/Work/pypsa-ar-base/data/network_500kv"
GIS_DIR    = "/mnt/c/Work/pypsa-ar-base/data/GIS_psse_geosadi_pypsaearth"

BUSES_FILE = os.path.join(DATA_DIR, "buses_final.csv")
GEN_FILE   = os.path.join(DATA_DIR, "generators_mapped.csv")
LOADS_FILE = os.path.join(DATA_DIR, "loads_mapped.csv")
GPKG_FILE  = os.path.join(GIS_DIR,  "balance_gen_carga.gpkg")

LAYER_NAME = "balance_por_bus"
CRS        = "EPSG:4326"


# =============================================================================
# MAIN
# =============================================================================

def main():
    print("=" * 60)
    print("10b_visualize_qgis.py -- balance gen/carga por nodo -> QGIS")
    print("=" * 60)

    for f in [BUSES_FILE, GEN_FILE, LOADS_FILE]:
        if not os.path.isfile(f):
            print(f"[ERROR] Archivo no encontrado:\n  {f}")
            sys.exit(1)

    buses = pd.read_csv(BUSES_FILE)
    gen   = pd.read_csv(GEN_FILE)
    loads = pd.read_csv(LOADS_FILE)

    print(f"\nBuses cargados       : {len(buses)}")
    print(f"Generadores cargados : {len(gen)}")
    print(f"Cargas cargadas      : {len(loads)}")

    # --- Generacion por bus ---
    # Solo STAT=1, excluir sin_conexion y PT=9999
    gen_activo = gen[
        (gen['match_type'] != 'sin_conexion') &
        (gen['stat'] == 1) &
        (gen['pt_mw'] < 9990)
    ].copy()

    gen_por_bus = (
        gen_activo.groupby('bus_conexion500kv')
        .agg(
            pg_mw         = ('pg_mw',   'sum'),
            n_generadores = ('gen_key', 'count'),
        )
        .reset_index()
        .rename(columns={'bus_conexion500kv': 'bus_id'})
    )
    gen_por_bus['bus_id'] = gen_por_bus['bus_id'].astype(int)

    # --- Demanda por bus ---
    # loads_mapped aun usa columna bus_destino (script 10 no modificado)
    loads_activo = loads[
        (loads['match_type'] != 'sin_conexion') &
        (loads['stat'] == 1)
    ].copy()

    loads_por_bus = (
        loads_activo.groupby('bus_destino')
        .agg(
            pl_mw    = ('pl_mw',    'sum'),
            n_cargas = ('load_key', 'count'),
        )
        .reset_index()
        .rename(columns={'bus_destino': 'bus_id'})
    )
    loads_por_bus['bus_id'] = loads_por_bus['bus_id'].astype(int)

    # --- Merge con buses ---
    df = buses[['bus_id', 'bus_name', 'bus_type', 'baskv_kv', 'lat', 'lon']].copy()
    df = df.merge(gen_por_bus,   on='bus_id', how='left')
    df = df.merge(loads_por_bus, on='bus_id', how='left')

    df['pg_mw']         = df['pg_mw'].fillna(0.0)
    df['pl_mw']         = df['pl_mw'].fillna(0.0)
    df['n_generadores'] = df['n_generadores'].fillna(0).astype(int)
    df['n_cargas']      = df['n_cargas'].fillna(0).astype(int)
    df['balance_mw']    = df['pg_mw'] - df['pl_mw']

    # --- Reporte ---
    print(f"\n{'='*60}")
    print(f"RESUMEN")
    print(f"{'='*60}")
    print(f"  Buses con generacion : {(df['pg_mw'] > 0).sum()}")
    print(f"  Buses con demanda    : {(df['pl_mw'] > 0).sum()}")
    print(f"  Buses con ambos      : {((df['pg_mw'] > 0) & (df['pl_mw'] > 0)).sum()}")
    print(f"  Buses sin ninguno    : {((df['pg_mw'] == 0) & (df['pl_mw'] == 0)).sum()}")
    print(f"\n  PG total en layer   : {df['pg_mw'].sum():>10,.1f} MW")
    print(f"  PL total en layer   : {df['pl_mw'].sum():>10,.1f} MW")
    print(f"  Balance neto        : {df['balance_mw'].sum():>10,.1f} MW")

    print(f"\n  Top 10 por PG:")
    for _, r in df.nlargest(10, 'pg_mw').iterrows():
        print(f"    {r.bus_name:<30} pg={r.pg_mw:>8,.1f} MW  pl={r.pl_mw:>8,.1f} MW  bal={r.balance_mw:>+8,.1f} MW")

    print(f"\n  Top 10 por PL:")
    for _, r in df.nlargest(10, 'pl_mw').iterrows():
        print(f"    {r.bus_name:<30} pg={r.pg_mw:>8,.1f} MW  pl={r.pl_mw:>8,.1f} MW  bal={r.balance_mw:>+8,.1f} MW")

    print(f"\n  Top 10 por deficit (carga neta mayor):")
    for _, r in df.nsmallest(10, 'balance_mw').iterrows():
        print(f"    {r.bus_name:<30} bal={r.balance_mw:>+8,.1f} MW")

    # --- Construir GeoDataFrame ---
    df_con_coord = df[df['lat'].notna() & df['lon'].notna()].copy()
    df_sin_coord = df[df['lat'].isna() | df['lon'].isna()].copy()

    if not df_sin_coord.empty:
        print(f"\n  {len(df_sin_coord)} buses sin coordenadas (excluidos del layer):")
        for _, r in df_sin_coord.iterrows():
            print(f"    {r.bus_name}")

    gdf = gpd.GeoDataFrame(
        df_con_coord,
        geometry=[Point(r['lon'], r['lat']) for _, r in df_con_coord.iterrows()],
        crs=CRS
    )

    gdf = gdf[[
        'bus_id', 'bus_name', 'bus_type', 'baskv_kv',
        'pg_mw', 'pl_mw', 'balance_mw',
        'n_generadores', 'n_cargas',
        'geometry',
    ]]

    os.makedirs(GIS_DIR, exist_ok=True)
    gdf.to_file(GPKG_FILE, layer=LAYER_NAME, driver="GPKG")

    print(f"\n✔ Layer '{LAYER_NAME}' exportado a {GPKG_FILE}")
    print(f"  {len(gdf)} buses")
    print(f"\nSimbologia sugerida en QGIS:")
    print(f"  Simbologia -> Basada en reglas:")
    print(f"    balance_mw > 0  -> circulo verde, tamanio = sqrt(balance_mw) / 3")
    print(f"    balance_mw < 0  -> circulo rojo,  tamanio = sqrt(abs(balance_mw)) / 3")
    print(f"    balance_mw = 0  -> circulo gris pequenio")
    print(f"\nProximo: 11_add_geo_to_generators.py")


if __name__ == "__main__":
    main()
