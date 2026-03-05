"""
05_match_geosadi_coords.py
Asigna coordenadas geograficas a todos los buses del modelo y consolida
en un unico archivo buses_final.csv.

Fuente geo    : Official data/geosadi/csv/estaciones_transformadoras.csv
Depende       : data/network_500kv/buses_500kv_raw.csv   (script 01)
                data/network_500kv/buses_sec_raw.csv      (script 04)
                data/network_500kv/buses_PSSE_vs_geosadi.xlsx  (diccionario manual)
Output        : data/network_500kv/buses_final.csv

Correr desde WSL:
    python /mnt/c/Work/pypsa-ar-base/scripts/network_500kv/05_match_geosadi_coords.py

Logica:
    BUSES 500 kV:
        Las coordenadas vienen del diccionario manual buses_PSSE_vs_geosadi.xlsx
        que contiene lat/lon curadas para los 95 buses 500 kV.
        match_status = 'manual'

    BUSES SECUNDARIOS:
        Heredan las coordenadas del bus 500 kV padre (mismo parent_bus_id).
        Fisicamente correcto: estan en la misma estacion que el trafo que los conecta.
        match_status = 'heredado'

    CONSOLIDACION:
        Ambos grupos se unen en un unico DataFrame con columnas comunes.
        El campo bus_type indica '500kV' o 'secundario'.

Columnas del output:
    bus_id         : ID numerico PSS/E
    bus_name       : nombre del bus en el modelo
    bus_name_psse  : nombre original PSS/E (NaN para buses 500kV donde coincide)
    bus_type       : '500kV' o 'secundario'
    baskv_kv       : tension base en kV
    ide            : tipo de bus PSS/E (1=PQ, 2=PV, 3=slack, 4=isolated)
    ide_desc       : descripcion del tipo
    lat            : latitud decimal (WGS84)
    lon            : longitud decimal (WGS84)
    parent_bus_id  : bus 500kV padre (NaN para buses 500kV)
    name_geosadi   : nombre GeoSADI asignado (solo buses 500kV)
"""

import os
import sys
import pandas as pd
import numpy as np

# =============================================================================
# CONFIGURACION
# =============================================================================

BUSES_500_FILE  = "/mnt/c/Work/pypsa-ar-base/data/network_500kv/buses_500kv_raw.csv"
BUSES_SEC_FILE  = "/mnt/c/Work/pypsa-ar-base/data/network_500kv/buses_sec_raw.csv"
MANUAL_FILE     = "/mnt/c/Work/pypsa-ar-base/data/network_500kv/buses_PSSE_vs_geosadi.xlsx"
OUTPUT_DIR      = "/mnt/c/Work/pypsa-ar-base/data/network_500kv"
OUTPUT_FILE     = os.path.join(OUTPUT_DIR, "buses_final.csv")

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
    print("05_match_geosadi_coords.py -- consolidar buses con coordenadas")
    print("=" * 60)

    for f in [BUSES_500_FILE, BUSES_SEC_FILE, MANUAL_FILE]:
        if not os.path.isfile(f):
            print(f"[ERROR] Archivo no encontrado:\n  {f}")
            sys.exit(1)

    # ==========================================================
    # BUSES 500 kV — coordenadas desde diccionario manual
    # ==========================================================
    buses_500 = pd.read_csv(BUSES_500_FILE)
    manual    = pd.read_excel(MANUAL_FILE)
    print(f"\nBuses 500 kV cargados     : {len(buses_500)}")
    print(f"Entradas en diccionario   : {len(manual)}")

    # Merge por bus_id
    manual_coords = manual[['bus_id', 'name_geosadi', 'lat', 'lon']].copy()
    buses_500 = buses_500.merge(manual_coords, on='bus_id', how='left')

    n_sin_coord = buses_500['lat'].isna().sum()
    if n_sin_coord:
        print(f"  ⚠ {n_sin_coord} buses 500 kV sin coordenadas en el diccionario:")
        for _, r in buses_500[buses_500['lat'].isna()].iterrows():
            print(f"    {r['bus_name']}")

    buses_500['bus_type']      = '500kV'
    buses_500['bus_name_psse'] = np.nan  # para 500kV bus_name ya es el nombre PSS/E

    buses_500['parent_bus_id'] = np.nan
    buses_500['ide_desc']      = buses_500['ide'].map(IDE_DESC).fillna('unknown')

    print(f"  ✔ Coordenadas asignadas via diccionario manual")

    # ==========================================================
    # BUSES SECUNDARIOS — heredar coordenadas del padre 500 kV
    # ==========================================================
    buses_sec = pd.read_csv(BUSES_SEC_FILE)
    print(f"\nBuses secundarios cargados: {len(buses_sec)}")

    # Mapa parent_bus_id -> (lat, lon)
    parent_coords = buses_500[['bus_id', 'lat', 'lon']].set_index('bus_id')

    buses_sec['lat'] = buses_sec['parent_bus_id'].map(parent_coords['lat'])
    buses_sec['lon'] = buses_sec['parent_bus_id'].map(parent_coords['lon'])

    n_sin_padre = buses_sec['lat'].isna().sum()
    if n_sin_padre:
        print(f"  ⚠ {n_sin_padre} buses secundarios sin coordenadas (padre sin coord):")
        for _, r in buses_sec[buses_sec['lat'].isna()].iterrows():
            print(f"    {r['bus_name']}  parent={r['parent_bus_id']}")

    buses_sec['bus_type']     = 'secundario'

    buses_sec['name_geosadi'] = np.nan

    print(f"  ✔ Coordenadas heredadas del bus 500 kV padre")

    # Sin offset — buses secundarios de la misma estacion comparten coordenadas
    # intencionalmente (estan en el mismo lugar fisico)

    # ==========================================================
    # CONSOLIDAR
    # ==========================================================
    col_500 = [
        'bus_id', 'bus_name', 'bus_name_psse', 'bus_type',
        'baskv_kv', 'ide', 'ide_desc',
        'vm_pu', 'va_deg',
        'lat', 'lon',
        'parent_bus_id', 'name_geosadi',
    ]
    col_sec = [
        'bus_id', 'bus_name', 'bus_name_psse', 'bus_type',
        'baskv_kv', 'ide', 'ide_desc',
        'vm_pu', 'va_deg',
        'lat', 'lon',
        'parent_bus_id', 'name_geosadi',
    ]

    df_500 = buses_500[col_500].copy()
    df_sec = buses_sec[col_sec].copy()

    df_final = pd.concat([df_500, df_sec], ignore_index=True)
    df_final = df_final.sort_values(['bus_type', 'bus_id']).reset_index(drop=True)

    # ==========================================================
    # REPORTE
    # ==========================================================
    print(f"\n{'='*60}")
    print(f"RESUMEN")
    print(f"{'='*60}")
    print(f"  Buses 500 kV      : {(df_final['bus_type']=='500kV').sum()}")
    print(f"  Buses secundarios : {(df_final['bus_type']=='secundario').sum()}")
    print(f"  TOTAL             : {len(df_final)}")
    print(f"\n  Con coordenadas   : {df_final['lat'].notna().sum()}")
    print(f"  Sin coordenadas   : {df_final['lat'].isna().sum()}")

    print(f"\nDistribucion por tension:")
    for kv, grp in df_final.groupby('baskv_kv'):
        kv_str = f"{int(kv)}kV" if kv == int(kv) else f"{kv:.1f}kV"
        print(f"  {kv_str:<10}: {len(grp)} buses")

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    df_final.to_csv(OUTPUT_FILE, index=False)

    print(f"\n✔ {OUTPUT_FILE}  ({len(df_final)} filas)")
    print("Proximo: 06_match_geosadi_geometry.py")


if __name__ == "__main__":
    main()
