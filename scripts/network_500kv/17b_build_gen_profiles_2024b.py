"""
17b_build_gen_profiles_2024b.py
Construye los perfiles horarios de disponibilidad (p_max_pu) para todas las
unidades generadoras del modelo, para las 8784 horas de 2024.

Variante del script 17 donde hidro, pumped_hydro y nuclear usan ENERG_OPERADA
como base del p_max_pu en lugar de POT_DISP. Esto refleja el despacho real
observado en 2024 como techo de lo que el optimizador puede tomar de esas
tecnologias, respetando las decisiones de embalse y despacho base ya tomadas.

Inputs:
    Official data/valores_2024_clean.csv  (archivo externo a GitHub)
    data/network_500kv/generators_2024.csv

Output:
    Official data/gen_profiles_2024b.csv  (archivo externo a GitHub)
        Columnas: gen_key, bus_conexion500kv_name, carrier, datetime, p_max_pu
        Una fila por unidad por hora.

Logica de p_max_pu:
    Solar, eolica, biogas, biomass:
        p_max_pu = ENERGIA / p_nom
        Se usa ENERGIA porque refleja el recurso meteorologico disponible
        en cada hora.

    Hidro, pumped_hydro, nuclear:
        p_max_pu = ENERG_OPERADA / p_nom
        Se usa ENERG_OPERADA (energia efectivamente despachada) como techo
        real de lo que el sistema puede tomar de estas tecnologias, sin
        forzar al optimizador a despacharlas exactamente en ese valor.

    Resto de tecnologias (termica, diesel):
        p_max_pu = POT_DISP / p_nom
        POT_DISP refleja la capacidad disponible real hora a hora.

    En todos los casos el resultado se clipea entre 0 y 1.
    Horas sin datos en CAMMESA: p_max_pu = 0.

Matching GRUPO -> unidad del modelo:
    Match directo: bus_name_origen existe como GRUPO en CAMMESA.
        El valor se asigna directamente a esa unidad.
    Sin match directo: se busca la Central por nemo4.
        El valor de la Central se distribuye proporcionalmente al p_nom
        de cada unidad.

Correr desde WSL:
    python /mnt/c/Work/pypsa-ar-base/scripts/network_500kv/17b_build_gen_profiles_2024b.py
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
OUTPUT_FILE  = "/mnt/c/Work/pypsa-ar-sandbox/Official data/gen_profiles_2024b.csv"

CHUNK_SIZE = 500_000

# Carriers que usan ENERGIA como base
CARRIERS_ENERGIA = {'solar', 'wind', 'biogas', 'biomass'}

# Carriers que usan ENERG_OPERADA como base
CARRIERS_OPERADA = {'hydro', 'pumped_hydro', 'nuclear'}

# Resto usa POT_DISP


# =============================================================================
# MAIN
# =============================================================================

def main():
    print("=" * 60)
    print("17b_build_gen_profiles_2024b.py -- perfiles horarios 2024b")
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
        usecols=['datetime', 'GRUPO', 'Central', 'ENERGIA', 'POT_DISP',
                 'ENERG_OPERADA', 'flag_outlier'],
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

        # Match directo
        directo = chunk.merge(
            gen[['gen_key', 'bus_conexion500kv_name', 'carrier', 'p_nom', 'bus_name_origen']],
            left_on='GRUPO',
            right_on='bus_name_origen',
            how='inner'
        )

        grupos_directos   = set(directo['GRUPO'].unique())
        gen_keys_directos = set(directo['gen_key'].unique())
        chunk_sin_match   = chunk[~chunk['GRUPO'].isin(grupos_directos)]

        # Match por nemo4
        distribuido = chunk_sin_match.merge(
            gen[['gen_key', 'bus_conexion500kv_name', 'carrier', 'p_nom', 'nemo4', 'peso']],
            left_on='nemo4_central',
            right_on='nemo4',
            how='inner'
        )
        distribuido = distribuido[~distribuido['gen_key'].isin(gen_keys_directos)]

        # Calcular valor segun carrier
        def seleccionar_valor(df):
            return np.select(
                [
                    df['carrier'].isin(CARRIERS_ENERGIA),
                    df['carrier'].isin(CARRIERS_OPERADA),
                ],
                [
                    df['ENERGIA'],
                    df['ENERG_OPERADA'].fillna(0.0),
                ],
                default=df['POT_DISP']
            )

        directo['valor'] = seleccionar_valor(directo)
        directo['p_max_pu'] = np.clip(directo['valor'] / directo['p_nom'], 0, 1)

        distribuido['valor_central'] = seleccionar_valor(distribuido)
        distribuido['valor']   = distribuido['valor_central'] * distribuido['peso']
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
