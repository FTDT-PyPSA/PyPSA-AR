"""
17_build_gen_profiles_2024.py
Construye los perfiles horarios de disponibilidad (p_max_pu) para todas las
unidades generadoras del modelo, para las 8784 horas de 2024.

Inputs:
    Official data/valores_2024_clean.csv  (archivo externo a GitHub)
    data/network_500kv/generators_2024.csv

Output:
    Official data/gen_profiles_2024.csv   (archivo externo a GitHub)
        Columnas: gen_key, bus_conexion500kv_name, carrier, datetime, p_max_pu
        Una fila por unidad por hora. ~650 unidades x 8784 horas ~ 5.7M filas.

Logica de p_max_pu:
    Solar, eolica, biogas, biomass:
        p_max_pu = ENERGIA / p_nom
        Se usa ENERGIA porque se asume que en 2024 se tomaba el maximo
        disponible del recurso en cada hora.

    Resto de tecnologias (termica, hidro, nuclear, pumped_hydro, diesel):
        p_max_pu = POT_DISP / p_nom
        POT_DISP refleja la capacidad disponible real hora a hora,
        incorporando paradas programadas, mantenimientos e indisponibilidades.

    En ambos casos el resultado se clipea entre 0 y 1.
    Horas sin datos en CAMMESA: p_max_pu = 0.

Matching GRUPO -> unidad del modelo:
    Match directo: bus_name_origen existe como GRUPO en CAMMESA.
        El valor se asigna directamente a esa unidad.
    Sin match directo: se busca la Central por nemo4.
        El valor de la Central se distribuye proporcionalmente al pt_mw
        de cada unidad (campo pt_mw de generators_2024.csv).

Correr desde WSL:
    python /mnt/c/Work/pypsa-ar-base/scripts/network_500kv/17_build_gen_profiles_2024.py
"""

import os
import sys
import pandas as pd
import numpy as np

# =============================================================================
# CONFIGURACION
# =============================================================================

VALORES_FILE = "/mnt/c/Work/pypsa-ar-sandbox/Official data/valores_2024_clean.csv"
GEN_FILE     = "/mnt/c/Work/pypsa-ar-base/data/network_500kv/generators_2024.csv"
OUTPUT_FILE  = "/mnt/c/Work/pypsa-ar-sandbox/Official data/gen_profiles_2024.csv"

CHUNK_SIZE = 500_000

CARRIERS_ENERGIA = {'solar', 'wind', 'biogas', 'biomass'}


# =============================================================================
# MAIN
# =============================================================================

def main():
    print("=" * 60)
    print("17_build_gen_profiles_2024.py -- perfiles horarios 2024")
    print("=" * 60)

    for f in [VALORES_FILE, GEN_FILE]:
        if not os.path.isfile(f):
            print(f"[ERROR] Archivo no encontrado:\n  {f}")
            sys.exit(1)

    # =========================================================
    # CARGAR GENERADORES
    # =========================================================
    gen = pd.read_csv(GEN_FILE)
    gen['nemo4'] = gen['nemo'].str[:4].str.strip()
    print(f"\nUnidades en modelo: {len(gen)}")

    COLS_GEN = ['gen_key', 'bus_conexion500kv_name', 'carrier', 'p_nom',
                'bus_name_origen', 'nemo4']
    gen = gen[COLS_GEN].copy()

    pnom_sum = (
        gen.groupby('nemo4')['p_nom']
        .sum()
        .rename('p_nom_total')
    )
    gen = gen.merge(pnom_sum, on='nemo4', how='left')
    gen['peso'] = gen.apply(
        lambda r: (r['p_nom'] / r['p_nom_total'])
        if r['p_nom_total'] > 0 else 0.0,
        axis=1
    )

    # =========================================================
    # PROCESAR EN CHUNKS
    # =========================================================
    print(f"\nProcesando valores_2024_clean.csv en chunks ...")

    lector = pd.read_csv(
        VALORES_FILE,
        usecols=['datetime', 'GRUPO', 'Central', 'ENERGIA', 'POT_DISP', 'flag_outlier'],
        chunksize=CHUNK_SIZE,
        low_memory=False,
    )

    primer_chunk = True
    n_chunks     = 0
    n_filas_out  = 0

    for chunk in lector:
        n_chunks += 1

        chunk = chunk[chunk['flag_outlier'] == False].copy()
        chunk['nemo4_central'] = chunk['Central'].str[:4].str.strip()

        directo = chunk.merge(
            gen[['gen_key', 'bus_conexion500kv_name', 'carrier', 'p_nom', 'bus_name_origen']],
            left_on='GRUPO',
            right_on='bus_name_origen',
            how='inner'
        )

        grupos_directos  = set(directo['GRUPO'].unique())
        gen_keys_directos = set(directo['gen_key'].unique())
        chunk_sin_match  = chunk[~chunk['GRUPO'].isin(grupos_directos)]

        distribuido = chunk_sin_match.merge(
            gen[['gen_key', 'bus_conexion500kv_name', 'carrier', 'p_nom', 'nemo4', 'peso']],
            left_on='nemo4_central',
            right_on='nemo4',
            how='inner'
        )
        distribuido = distribuido[~distribuido['gen_key'].isin(gen_keys_directos)]

        directo['valor'] = np.where(
            directo['carrier'].isin(CARRIERS_ENERGIA),
            directo['ENERGIA'],
            directo['POT_DISP']
        )
        directo['p_max_pu'] = np.clip(directo['valor'] / directo['p_nom'], 0, 1)

        distribuido['valor_central'] = np.where(
            distribuido['carrier'].isin(CARRIERS_ENERGIA),
            distribuido['ENERGIA'],
            distribuido['POT_DISP']
        )
        distribuido['valor'] = distribuido['valor_central'] * distribuido['peso']
        distribuido['p_max_pu'] = np.clip(
            distribuido['valor'] / distribuido['p_nom'], 0, 1
        )

        COLS_OUT = ['gen_key', 'bus_conexion500kv_name', 'carrier', 'datetime', 'p_max_pu']
        df_out = pd.concat([
            directo[COLS_OUT],
            distribuido[COLS_OUT],
        ], ignore_index=True)

        df_out['p_max_pu'] = df_out['p_max_pu'].round(6)

        modo = 'w' if primer_chunk else 'a'
        df_out.to_csv(OUTPUT_FILE, index=False, mode=modo, header=primer_chunk)
        n_filas_out += len(df_out)
        primer_chunk = False

        if n_chunks % 5 == 0:
            print(f"  ... chunk {n_chunks}, filas escritas: {n_filas_out:,}")

    # =========================================================
    # REPORTE
    # =========================================================
    print(f"\n{'='*60}")
    print(f"REPORTE FINAL")
    print(f"{'='*60}")
    print(f"  Chunks procesados : {n_chunks}")
    print(f"  Filas en output   : {n_filas_out:,}")
    print(f"  Output            : {OUTPUT_FILE}")
    print("=" * 60)


if __name__ == "__main__":
    main()
