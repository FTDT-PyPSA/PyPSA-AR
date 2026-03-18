"""
14_build_generators_2024.py
Construye la tabla definitiva de generadores con capacidades reales de 2024,
reemplazando las potencias del snapshot PSS/E por datos de CAMMESA.

Inputs:
    data/network_500kv/generators_final.csv
    Official data/valores_2024_clean.csv  (archivo externo a GitHub)

Output:
    data/network_500kv/generators_2024.csv

Logica de p_nom:
    Para cada unidad del modelo se intenta match exacto entre bus_name_origen
    y GRUPO de CAMMESA.

    Match exacto (ej: ACAJTV07 existe como GRUPO en CAMMESA):
        p_nom = p95 de POT_DISP de ese GRUPO en el anio.
        Asignacion directa, sin distribucion.

    Sin match exacto (ej: YACYHI01 no existe como GRUPO en CAMMESA):
        Se busca la Central correspondiente por nemo4.
        p_nom = p95 de POT_DISP de los GRUPOs de esa Central,
        distribuido proporcionalmente al pt_mw del PSS/E entre las
        unidades del modelo. Esto respeta la capacidad relativa de
        cada maquina dentro de la central.

    El p95 se calcula excluyendo filas marcadas con flag_outlier=True.

Reasignacion CAPE/ACAJ:
    CAPEX (CAPE en CAMMESA) y Agua del Cajon (ACAJ) son comercialmente
    separados pero fisicamente la misma central. Las unidades TG01, TG06
    y TV07 pertenecen a CAPE. Se reasigna su nemo4 antes del join.

Central binacional:
    SGDE (Salto Grande): CAMMESA reporta la potencia total de la represa.
    Se aplica factor 0.5 para quedarse solo con la parte argentina.

Centrales excluidas:
    Las que no tienen match en CAMMESA por nemo4. Se listan en el reporte.

Correr desde WSL:
    python /mnt/c/Work/pypsa-ar-base/scripts/network_500kv/14_build_generators_2024.py
"""

import os
import sys
import pandas as pd
import numpy as np

# =============================================================================
# CONFIGURACION
# =============================================================================

GEN_FILE     = "/mnt/c/Work/pypsa-ar-base/data/network_500kv/generators_final.csv"
VALORES_FILE = "/mnt/c/Work/pypsa-ar-sandbox/Official data/valores_2024_clean.csv"
OUTPUT_DIR   = "/mnt/c/Work/pypsa-ar-base/data/network_500kv"
OUTPUT_FILE  = os.path.join(OUTPUT_DIR, "generators_2024.csv")

CHUNK_SIZE = 500_000

P_NOM_PERCENTILE = 95

BINACIONAL_FACTOR = {
    'SGDE': 0.5,
}

NEMO_OVERRIDE = {
    '1601-1': 'CAPE',
    '1600-6': 'CAPE',
    '1606-1': 'CAPE',
}

# GRUPOs de CAMMESA excluidos del calculo de p_nom.
# YACYHIPY: lado paraguayo de Yacyreta — no forma parte del modelo argentino.
GRUPOS_EXCLUIR = {'YACYHIPY'}

COLS_OUTPUT = [
    'gen_key', 'bus_name_origen', 'nombre_geosadi', 'nemo',
    'bus_conexion500kv', 'bus_conexion500kv_name',
    'carrier', 'p_nom', 'lat', 'lon',
    'n_saltos', 'camino',
]


# =============================================================================
# PASO 1 — Calcular p95 de POT_DISP por GRUPO desde valores_2024_clean
# =============================================================================

def calcular_p95_por_grupo():
    """
    Lee valores_2024_clean.csv en chunks y acumula POT_DISP por GRUPO,
    excluyendo filas con flag_outlier=True.
    Retorna dos Series indexadas por GRUPO:
        p95_por_grupo — p95 de POT_DISP
        central_por_grupo — Central correspondiente a cada GRUPO
    """
    print("\n[1/3] Calculando p95 de POT_DISP por GRUPO ...")

    acumulador  = {}
    central_map = {}

    lector = pd.read_csv(
        VALORES_FILE,
        usecols=['GRUPO', 'Central', 'POT_DISP', 'flag_outlier'],
        chunksize=CHUNK_SIZE,
        low_memory=False,
    )

    n_filas = 0
    for chunk in lector:
        n_filas += len(chunk)
        chunk = chunk[chunk['flag_outlier'] == False]

        for grupo, grp in chunk.groupby('GRUPO'):
            if grupo in GRUPOS_EXCLUIR:
                continue
            if grupo not in acumulador:
                acumulador[grupo] = []
                central_map[grupo] = grp['Central'].iloc[0]
            acumulador[grupo].append(grp['POT_DISP'].values)

    print(f"  Filas leidas: {n_filas:,}")
    print(f"  GRUPOs encontrados: {len(acumulador)}")

    p95 = {}
    for grupo, vals in acumulador.items():
        all_vals = np.concatenate(vals)
        p95[grupo] = np.nanpercentile(all_vals, P_NOM_PERCENTILE)

    return pd.Series(p95), central_map


# =============================================================================
# PASO 2 — Calcular p_nom por unidad del modelo
# =============================================================================

def calcular_p_nom(gen, p95_grupo, central_map):
    """
    Asigna p_nom a cada unidad del modelo.

    Para cada unidad:
        - Si bus_name_origen matchea exactamente con un GRUPO de CAMMESA
          -> p_nom = p95 de ese GRUPO (asignacion directa)
        - Si no matchea
          -> buscar los GRUPOs de la Central por nemo4
          -> p_nom = suma de p95 de esos GRUPOs, distribuido por pt_mw

    Aplica factor binacional donde corresponde.
    """
    grupos_disponibles = set(p95_grupo.index)

    grupo_a_central = pd.Series(central_map)
    central_a_grupos = {}
    for grupo, central in central_map.items():
        if central not in central_a_grupos:
            central_a_grupos[central] = []
        central_a_grupos[central].append(grupo)

    p_nom_list = []

    for _, row in gen.iterrows():
        bus_origen = row['bus_name_origen']
        nemo4      = row['nemo4']
        pt_mw      = row['pt_mw']

        # --- Match exacto GRUPO ---
        if bus_origen in grupos_disponibles:
            valor = p95_grupo[bus_origen]

        # --- Sin match: buscar por Central (nemo4) ---
        elif nemo4 in central_a_grupos:
            grupos_central = central_a_grupos[nemo4]
            p95_central = sum(p95_grupo.get(g, 0) for g in grupos_central)

            # Distribuir por pt_mw entre unidades del modelo de la misma central
            unidades_central = gen[gen['nemo4'] == nemo4]
            pt_total = unidades_central['pt_mw'].sum()

            if pt_total > 0:
                valor = p95_central * (pt_mw / pt_total)
            else:
                valor = 0.0

        else:
            valor = None

        # --- Factor binacional ---
        if valor is not None and nemo4 in BINACIONAL_FACTOR:
            valor = valor * BINACIONAL_FACTOR[nemo4]

        p_nom_list.append(valor)

    gen = gen.copy()
    gen['p_nom'] = p_nom_list
    return gen


# =============================================================================
# MAIN
# =============================================================================

def main():
    print("=" * 60)
    print("14_build_generators_2024.py -- generadores reales 2024")
    print("=" * 60)

    for f in [GEN_FILE, VALORES_FILE]:
        if not os.path.isfile(f):
            print(f"[ERROR] Archivo no encontrado:\n  {f}")
            sys.exit(1)

    # =========================================================
    # CARGAR GENERADORES
    # =========================================================
    gen = pd.read_csv(GEN_FILE)
    print(f"\nGeneradores en modelo: {len(gen)}")

    # Extraer nemo4
    gen['nemo4'] = gen['nemo'].fillna('').str[:4].str.strip()

    # Aplicar overrides CAPE/ACAJ
    for gkey, nuevo_nemo in NEMO_OVERRIDE.items():
        mask = gen['gen_key'] == gkey
        if mask.sum() > 0:
            gen.loc[mask, 'nemo4'] = nuevo_nemo
            gen.loc[mask, 'nemo']  = nuevo_nemo
    print(f"Overrides CAPE/ACAJ aplicados: {len(NEMO_OVERRIDE)} unidades")

    # =========================================================
    # CALCULAR p95 POR GRUPO
    # =========================================================
    p95_grupo, central_map = calcular_p95_por_grupo()

    # =========================================================
    # ASIGNAR p_nom
    # =========================================================
    print(f"\n[2/3] Asignando p_nom por unidad ...")
    gen = calcular_p_nom(gen, p95_grupo, central_map)

    # =========================================================
    # SEPARAR CON Y SIN MATCH
    # =========================================================
    gen_match    = gen[gen['p_nom'].notna()].copy()
    gen_excluded = gen[gen['p_nom'].isna()].copy()

    # =========================================================
    # REPORTE
    # =========================================================
    print(f"\n[3/3] Reporte")
    print(f"{'='*60}")
    print(f"\n  Unidades con p_nom asignado : {len(gen_match)}")
    print(f"  Unidades excluidas          : {len(gen_excluded)}")

    if len(gen_excluded) > 0:
        excl = gen_excluded.drop_duplicates('nemo4')[
            ['nombre_geosadi', 'nemo4', 'carrier']
        ].sort_values('nemo4')
        print("\n  Centrales excluidas (sin match en CAMMESA):")
        for _, row in excl.iterrows():
            print(f"    {row['nemo4']:<8} {row['carrier']:<12} {row['nombre_geosadi']}")

    print(f"\n  p_nom total del sistema: {gen_match['p_nom'].sum():,.1f} MW")
    print(f"\n  Por carrier:")
    for carrier, grp in gen_match.groupby('carrier'):
        print(f"    {carrier:<15}: {len(grp):>4} unidades   "
              f"p_nom={grp['p_nom'].sum():>10,.1f} MW")

    # =========================================================
    # EXPORTAR
    # =========================================================
    gen_match['p_nom'] = gen_match['p_nom'].round(4)
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    gen_match[COLS_OUTPUT].to_csv(OUTPUT_FILE, index=False)
    print(f"\n  Output: {OUTPUT_FILE}  ({len(gen_match)} filas)")
    print("=" * 60)


if __name__ == "__main__":
    main()
