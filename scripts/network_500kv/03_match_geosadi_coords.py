"""
03_match_geosadi_coords.py
Asigna coordenadas geograficas (lat/lon) y nombre GeoSADI a los buses 500 kV
del PSS/E usando el diccionario curado buses_PSSE_vs_geosadi.xlsx.

Fuente buses  : data/network_500kv/buses_500kv_raw.csv       (output script 01)
Diccionario   : data/network_500kv/buses_PSSE_vs_geosadi.xlsx (curado por el equipo)
Output        : data/network_500kv/buses_500kv_final.csv

Correr desde WSL:
    python /mnt/c/Work/pypsa-ar-base/scripts/network_500kv/03_match_geosadi_coords.py

Columnas del output:
    bus_id, bus_name       : identificacion PSS/E
    name_geosadi           : nombre canonico en GeoSADI (vacio si no existe en GeoSADI)
    lat, lon               : coordenadas geograficas
    match_status           : 'ok' | 'consultar' | 'pendiente'
    baskv_kv               : tension nominal [kV]
    ide, ide_desc          : tipo de bus PSS/E
    area, zone, owner      : datos de area/zona
    vm_pu, va_deg          : condicion operativa del caso base

Logica de match_status:
    'ok'        : VERIFICADO? == 'OK' en el diccionario
    'consultar' : VERIFICADO? == 'CONSULTAR' -- requiere decision del equipo
    'pendiente' : bus_id no encontrado en el diccionario (no deberia ocurrir
                  si el diccionario esta completo)

Notas:
    - Los buses con name_geosadi vacio son barras internas, nodos de compensacion
      o endpoints de linea que no existen como estacion en GeoSADI.
      Tienen coordenadas asignadas manualmente y son validos para el modelo.
    - El script 04 usara name_geosadi para matchear geometria de lineas.
      Buses con name_geosadi vacio quedaran sin geometria (pendiente_bus), lo
      cual es correcto.
    - R9B5RS (bus 5013) no tiene coordenadas -- es un nodo de shunt sin
      ubicacion fisica propia. Queda con match_status='consultar'.
"""

import os
import sys
import pandas as pd
import numpy as np

# =============================================================================
# CONFIGURACION
# =============================================================================

DATA_DIR    = "/mnt/c/Work/pypsa-ar-base/data/network_500kv"
BUSES_RAW   = os.path.join(DATA_DIR, "buses_500kv_raw.csv")
DICT_FILE   = os.path.join(DATA_DIR, "buses_PSSE_vs_geosadi.xlsx")
OUTPUT_FILE = os.path.join(DATA_DIR, "buses_500kv_final.csv")

# Offset en grados para separar buses con exactamente las mismas coordenadas (~10m)
COORD_OFFSET = 0.0001


# =============================================================================
# FUNCIONES
# =============================================================================

def apply_coord_offset(df):
    """
    Si multiples buses comparten exactamente la misma (lat, lon),
    aplica un offset incremental en lon para separarlos (~10m por paso).
    Solo se aplica a buses con coordenadas validas.
    """
    df = df.copy()
    df["coord_offset_applied"] = False
    valid = df["lat"].notna() & df["lon"].notna()
    coord_counts = df[valid].groupby(["lat", "lon"]).cumcount()
    mask = coord_counts > 0
    if mask.any():
        df.loc[mask[mask].index, "lon"] += coord_counts[mask] * COORD_OFFSET
        df.loc[mask[mask].index, "coord_offset_applied"] = True
        print(f"  Offset aplicado a {mask.sum()} buses con coordenadas duplicadas")
    return df


# =============================================================================
# MAIN
# =============================================================================

def main():
    print("=" * 60)
    print("03_match_geosadi_coords.py -- coordenadas a buses 500 kV")
    print("=" * 60)

    # --- Verificar archivos ---
    for f in [BUSES_RAW, DICT_FILE]:
        if not os.path.isfile(f):
            print(f"[ERROR] Archivo no encontrado:\n  {f}")
            sys.exit(1)

    # --- Cargar buses PSS/E ---
    buses = pd.read_csv(BUSES_RAW)
    print(f"\nBuses PSS/E cargados      : {len(buses)}")

    # --- Cargar diccionario curado ---
    dic = pd.read_excel(DICT_FILE, usecols=[
        "bus_id", "name_geosadi", "lat", "lon", "VERIFICADO?"
    ])
    dic = dic.rename(columns={"VERIFICADO?": "verificado"})
    dic["bus_id"] = dic["bus_id"].astype(int)
    print(f"Diccionario cargado       : {len(dic)} entradas")

    # --- Join por bus_id ---
    merged = buses.merge(dic, on="bus_id", how="left")

    # --- Asignar match_status ---
    def get_status(row):
        if pd.isna(row.get("verificado")):
            return "pendiente"   # bus_id no estaba en el diccionario
        v = str(row["verificado"]).strip().upper()
        if v == "OK":
            return "ok"
        elif v == "CONSULTAR":
            return "consultar"
        return "pendiente"

    merged["match_status"] = merged.apply(get_status, axis=1)

    # --- Aplicar offset a coordenadas duplicadas ---
    print("\nVerificando coordenadas duplicadas...")
    merged = apply_coord_offset(merged)

    # --- Reporte ---
    n_ok        = (merged["match_status"] == "ok").sum()
    n_consultar = (merged["match_status"] == "consultar").sum()
    n_pendiente = (merged["match_status"] == "pendiente").sum()
    n_sin_geo   = merged["name_geosadi"].isna().sum()
    n_sin_coord = merged["lat"].isna().sum()

    print("\n" + "=" * 60)
    print("RESUMEN")
    print("=" * 60)
    print(f"  ok               : {n_ok}")
    print(f"  consultar        : {n_consultar}")
    print(f"  pendiente        : {n_pendiente}")
    print(f"  TOTAL            : {len(merged)}")
    print(f"\n  Sin name_geosadi : {n_sin_geo}  (barras internas / sin equiv. GeoSADI)")
    print(f"  Sin coordenadas  : {n_sin_coord}")

    if n_consultar:
        print(f"\nBuses CONSULTAR:")
        for _, r in merged[merged["match_status"] == "consultar"].iterrows():
            coord_str = f"({r['lat']:.4f}, {r['lon']:.4f})" if pd.notna(r.get("lat")) else "sin coordenadas"
            print(f"  {r['bus_name']:<20}  {coord_str}")

    if n_pendiente:
        print(f"\nBuses PENDIENTES (no encontrados en diccionario):")
        for _, r in merged[merged["match_status"] == "pendiente"].iterrows():
            print(f"  bus_id={r['bus_id']}  {r['bus_name']}")

    # --- Exportar ---
    col_order = [
        "bus_id", "bus_name", "name_geosadi", "match_status",
        "baskv_kv", "lat", "lon",
        "ide", "ide_desc", "area", "zone", "owner",
        "vm_pu", "va_deg",
        "coord_offset_applied",
    ]
    col_order = [c for c in col_order if c in merged.columns]

    merged[col_order].sort_values("bus_id").reset_index(drop=True).to_csv(
        OUTPUT_FILE, index=False
    )

    print(f"\n✔ {OUTPUT_FILE}  ({len(merged)} filas)")
    print("Proximo: 04_match_geosadi_geometry.py")


if __name__ == "__main__":
    main()
