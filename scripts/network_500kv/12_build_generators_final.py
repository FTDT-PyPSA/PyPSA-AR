"""
12_build_generators_final.py
Une generators_readypypsa.csv con los generadores resueltos manualmente de
generators_manualpypsa.csv para producir generators_final.csv — la tabla
definitiva de generadores que entra a PyPSA.

Inputs:
    data/network_500kv/generators_readypypsa.csv   (script 11)
    data/network_500kv/generators_manualpypsa.csv  (completado manualmente)
    Official data/geosadi/csv/centrales_electricas.csv

Output:
    data/network_500kv/generators_final.csv
        Una fila por generador. Contiene todos los generadores con
        nombre_geosadi Y bus_conexion500kv resueltos.
        Es el input del modelo junto con buses_final.csv y lines_500kv_final.csv.

        Columna 'nemo': codigo CAMMESA de 4 caracteres (ej: YACY, EMBA, ATU2).
        Se obtiene haciendo join nombre_geosadi -> Nombre en centrales_electricas.csv.
        Es la clave para el join con VALORES_2024.csv (datos reales de generacion).

        Columna 'stat': estado del generador en el snapshot PSS/E (pico verano 25/26).
        stat=1 en servicio, stat=0 fuera de servicio en ese caso base.

Reasignacion CAPE/ACAJ:
    CAPEX (CAPE en CAMMESA) y Agua del Cajon (ACAJ) son comercialmente
    separados pero fisicamente la misma central. Las unidades TG01, TG06
    y TV07 pertenecen a CAPE. 

Correr desde WSL:
    python /mnt/c/Work/pypsa-ar-base/scripts/network_500kv/12_build_generators_final.py
"""

import os
import sys
import pandas as pd

# =============================================================================
# CONFIGURACION
# =============================================================================

READY_FILE     = "/mnt/c/Work/pypsa-ar-base/data/network_500kv/generators_readypypsa.csv"
MANUAL_FILE    = "/mnt/c/Work/pypsa-ar-base/data/network_500kv/generators_manualpypsa.csv"
CENTRALES_FILE = "/mnt/c/Work/pypsa-ar-sandbox/Official data/geosadi/csv/centrales_electricas.csv"
OUTPUT_DIR     = "/mnt/c/Work/pypsa-ar-base/data/network_500kv"
OUTPUT_FILE    = os.path.join(OUTPUT_DIR, "generators_final.csv")

COLS = [
    'gen_key', 'bus_name_origen', 'nombre_geosadi', 'nemo',
    'bus_conexion500kv', 'bus_conexion500kv_name',
    'carrier', 'lat', 'lon',
    'pg_mw', 'pt_mw', 'stat',
    'match_type', 'n_saltos', 'camino',
]

# Reasignacion de nemo por gen_key individual.
# CAPEX (CAPE en CAMMESA) y Agua del Cajon (ACAJ) son comercialmente
# separados pero fisicamente la misma central.
# TG01, TG06 y TV07 pertenecen a CAPE.
NEMO_OVERRIDE = {
    '1601-1': 'CAPE',   # ACAJTG01 -> CAPEX
    '1600-6': 'CAPE',   # ACAJTG06 -> CAPEX
    '1606-1': 'CAPE',   # ACAJTV07 -> CAPEX
}


def main():
    print("=" * 60)
    print("12_build_generators_final.py -- tabla definitiva PyPSA")
    print("=" * 60)

    for f in [READY_FILE, MANUAL_FILE, CENTRALES_FILE]:
        if not os.path.isfile(f):
            print(f"[ERROR] Archivo no encontrado:\n  {f}")
            sys.exit(1)

    ready     = pd.read_csv(READY_FILE)
    manual    = pd.read_csv(MANUAL_FILE)
    centrales = pd.read_csv(CENTRALES_FILE, encoding='latin-1')

    # Diccionario nombre_geosadi -> nemo desde centrales_electricas.csv
    nemo_map = centrales.drop_duplicates('Nombre').set_index('Nombre')['Nemo'].to_dict()

    print(f"generators_readypypsa  : {len(ready)} generadores")
    print(f"generators_manualpypsa : {len(manual)} generadores")
    print(f"centrales_electricas   : {len(nemo_map)} entradas en indice nombre->nemo")

    # Filtrar manual: solo falta='ok' y match_type != 'sin_conexion'
    mask = (manual['falta'] == 'ok') & (manual['match_type'] != 'sin_conexion')
    manual_ok = manual[mask].copy()

    n_captivos = len(manual[(manual['falta'] == 'ok') & (manual['match_type'] == 'sin_conexion')])
    n_pending  = len(manual[manual['falta'] != 'ok'])

    print(f"\n  Resueltos desde manual : {len(manual_ok)}")
    print(f"  Captivos excluidos     : {n_captivos}  (ALUAR, El Trapial, autoproduccion)")
    print(f"  Aun sin resolver       : {n_pending}")

    # Concat y ordenar
    ready_out = ready.copy()
    df_final = pd.concat([ready_out, manual_ok], ignore_index=True)
    df_final = df_final.sort_values('pt_mw', ascending=False).reset_index(drop=True)

    # Agregar nemo via join por nombre_geosadi -> Nombre en centrales_electricas.csv
    df_final['nemo'] = df_final['nombre_geosadi'].map(nemo_map).fillna('')

    # Para los que quedaron sin nemo (nombre_geosadi corrupto por encoding),
    # tomar los primeros 4 chars de bus_name_origen
    mask_sin = df_final['nemo'] == ''
    if mask_sin.sum() > 0:
        df_final.loc[mask_sin, 'nemo'] = (
            df_final.loc[mask_sin, 'bus_name_origen'].str[:4].str.strip()
        )
        print(f"  {mask_sin.sum()} nemos resueltos desde bus_name_origen[:4] (encoding corrupto en nombre_geosadi)")

    # Aplicar reasignacion CAPE/ACAJ
    n_override = 0
    for gkey, nuevo_nemo in NEMO_OVERRIDE.items():
        mask_ov = df_final['gen_key'] == gkey
        if mask_ov.sum() > 0:
            df_final.loc[mask_ov, 'nemo'] = nuevo_nemo
            n_override += mask_ov.sum()
    if n_override:
        print(f"  Reasignacion CAPE/ACAJ aplicada: {n_override} unidades -> CAPE")

    n_con_nemo = (df_final['nemo'] != '').sum()
    n_sin_nemo = (df_final['nemo'] == '').sum()
    print(f"\n  Con nemo resuelto      : {n_con_nemo}")
    if n_sin_nemo:
        print(f"  Sin nemo               : {n_sin_nemo}")
        sin = df_final[df_final['nemo'] == ''][['gen_key','nombre_geosadi','carrier']].head(10)
        print(sin.to_string(index=False))

    # Seleccionar y ordenar columnas finales
    df_final = df_final[COLS]

    # ==========================================================
    # REPORTE
    # ==========================================================
    print(f"\n{'='*60}")
    print(f"GENERATORS_FINAL")
    print(f"{'='*60}")
    print(f"  Total generadores : {len(df_final)}")

    mw_total = df_final[df_final['pt_mw'] < 9000]['pt_mw'].sum()
    print(f"  Potencia total    : {mw_total:,.1f} MW  (excluye PT=9999)")

    print(f"\n  Por carrier (pt < 9999):")
    activos = df_final[df_final['pt_mw'] < 9990]
    for carrier, grp in activos.groupby('carrier'):
        print(f"    {carrier:<15}: {len(grp):>4} gen   {grp['pt_mw'].sum():>10,.1f} MW")

    print(f"\n  Por match_type:")
    for mt, grp in df_final.groupby('match_type'):
        mw = grp[grp['pt_mw'] < 9000]['pt_mw'].sum()
        print(f"    {mt:<15}: {len(grp):>4} gen   {mw:>10,.1f} MW")

    n_sin_coord = df_final['lat'].isna().sum()
    if n_sin_coord > 0:
        print(f"\n  Sin coordenadas : {n_sin_coord} generadores (entran a PyPSA sin punto en el mapa)")

    # ==========================================================
    # EXPORTAR
    # ==========================================================
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    df_final.to_csv(OUTPUT_FILE, index=False)
    print(f"\n  Output: {OUTPUT_FILE}  ({len(df_final)} filas)")


if __name__ == "__main__":
    main()
