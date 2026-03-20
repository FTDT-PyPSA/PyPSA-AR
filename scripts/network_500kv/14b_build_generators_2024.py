"""
14b_build_generators_2024.py
Construye generators_2024.csv con p_nom calculado desde datos reales de
CAMMESA 2024. Requiere que conflictos_psse_cammesa.csv este completado
(generado por script 14).

Inputs:
    data/network_500kv/generators_final.csv
    data/network_500kv/conflictos_psse_cammesa.csv
    Official data/valores_2024_clean.csv  (archivo externo a GitHub)

Output:
    data/network_500kv/generators_2024.csv

Logica de p_nom:
    Para cada central (nemo4), p_nom = percentil 95 de POT_DISP anual.
    Se usa p95 para evitar outliers puntuales.
    El valor se distribuye proporcionalmente al pt_mw del PSS/E de cada
    unidad dentro de la central.

    Central binacional SGDE (Salto Grande, Argentina/Uruguay):
    CAMMESA reporta la potencia total. Se aplica factor 0.5 para
    quedarse con la parte argentina antes de distribuir.

Resolucion de conflictos:
    Se aplican los overrides de conflictos_psse_cammesa.csv:
        excluir = si              → unidad excluida del modelo
        bus_name_origen_correcto  → reemplaza bus_name_origen para el
                                    match con CAMMESA
        revisado = si (sin match) → va al nemo4 normalmente

    Si hay conflictos pendientes (ni excluir ni revisado ni match),
    el script avisa y termina sin generar el output.

Correr desde WSL:
    python /mnt/c/Work/pypsa-ar-base/scripts/network_500kv/14b_build_generators_2024.py
"""

import os
import sys
import pandas as pd
import numpy as np

# =============================================================================
# CONFIGURACION
# =============================================================================

GEN_FILE        = "/mnt/c/Work/pypsa-ar-base/data/network_500kv/generators_final.csv"
CONFLICTOS_FILE = "/mnt/c/Work/pypsa-ar-base/data/network_500kv/conflictos_psse_cammesa.csv"
VALORES_FILE    = "/mnt/c/Work/pypsa-ar-sandbox/Official data/valores_2024_clean.csv"
OUTPUT_DIR      = "/mnt/c/Work/pypsa-ar-base/data/network_500kv"
OUTPUT_FILE     = os.path.join(OUTPUT_DIR, "generators_2024.csv")

BINACIONAL_FACTOR = {'SGDE': 0.5}
P_NOM_PERCENTILE  = 95


# =============================================================================
# MAIN
# =============================================================================

def main():
    print("=" * 60)
    print("14b_build_generators_2024.py -- generadores reales 2024")
    print("=" * 60)

    for f in [GEN_FILE, CONFLICTOS_FILE, VALORES_FILE]:
        if not os.path.isfile(f):
            print(f"[ERROR] Archivo no encontrado:\n  {f}")
            sys.exit(1)

    # =========================================================
    # CARGAR GENERADORES Y CONFLICTOS
    # =========================================================
    gen = pd.read_csv(GEN_FILE)
    gen['nemo4'] = gen['nemo'].fillna('').str[:4].str.strip()

    conflictos = pd.read_csv(CONFLICTOS_FILE, encoding='latin-1')

    print(f"\nUnidades en modelo : {len(gen)}")

    # Verificar conflictos pendientes
    tiene_match  = conflictos['bus_name_origen_correcto'].fillna('').str.strip() != ''
    es_excluido  = conflictos['excluir'].fillna('').str.strip().str.lower() == 'si'
    es_revisado  = conflictos['revisado'].fillna('').str.strip().str.lower() == 'si'
    pendientes   = conflictos[~tiene_match & ~es_excluido & ~es_revisado]

    if len(pendientes) > 0:
        print(f"\n[ERROR] Hay {len(pendientes)} conflictos pendientes en {CONFLICTOS_FILE}")
        print(pendientes[['gen_key', 'bus_name_origen', 'nemo4']].to_string(index=False))
        print("\nCompletar el CSV y volver a correr el script 14.")
        sys.exit(1)

    # =========================================================
    # APLICAR RESOLUCIONES
    # =========================================================

    # Excluir
    excluir_keys = set(conflictos[es_excluido]['gen_key'].astype(str))
    gen = gen[~gen['gen_key'].astype(str).isin(excluir_keys)].copy()
    print(f"Unidades excluidas : {len(excluir_keys)}")

    # Aplicar bus_name_origen_correcto
    match_map = conflictos[tiene_match].set_index('gen_key')['bus_name_origen_correcto'].to_dict()
    mask_override = gen['gen_key'].astype(str).isin(match_map)
    gen.loc[mask_override, 'bus_name_origen'] = gen.loc[mask_override, 'gen_key'].astype(str).map(match_map)
    print(f"Overrides aplicados: {mask_override.sum()}")

    gen['nemo4'] = gen['nemo'].fillna('').str[:4].str.strip()

    # =========================================================
    # CALCULAR p_nom DESDE CAMMESA
    # =========================================================
    print(f"\nLeyendo valores_2024_clean.csv ...")

    df = pd.read_csv(
        VALORES_FILE,
        usecols=['Central', 'POT_DISP'],
        low_memory=False,
    )

    pot_p95 = df.groupby('Central')['POT_DISP'].quantile(P_NOM_PERCENTILE / 100)

    for nemo4, factor in BINACIONAL_FACTOR.items():
        if nemo4 in pot_p95.index:
            pot_p95[nemo4] *= factor
            

    centrales_cammesa = set(pot_p95.index)
    print(f"Centrales en CAMMESA: {len(centrales_cammesa)}")

    # =========================================================
    # SEPARAR CON Y SIN MATCH
    # =========================================================
    mask_match   = gen['nemo4'].isin(centrales_cammesa) & (gen['nemo4'] != '')
    gen_match    = gen[mask_match].copy()
    gen_excluded = gen[~mask_match].copy()

    print(f"\nCon match en CAMMESA : {len(gen_match)}")
    print(f"Sin match (excluidos): {len(gen_excluded)}")

    if len(gen_excluded) > 0:
        excl_summary = gen_excluded.drop_duplicates('nemo4')[
            ['nombre_geosadi', 'nemo4', 'carrier']
        ].sort_values('nemo4')
        print("\n  Centrales sin match en CAMMESA:")
        for _, row in excl_summary.iterrows():
            print(f"    {row['nemo4']:<8} {row['carrier']:<12} {row['nombre_geosadi']}")

    # =========================================================
    # DISTRIBUIR p_nom PROPORCIONALMENTE AL pt_mw
    # =========================================================
    pt_sum_por_central = gen_match.groupby('nemo4')['pt_mw'].transform('sum')
    p95_por_central    = gen_match['nemo4'].map(pot_p95)
    gen_match['p_nom'] = (p95_por_central * gen_match['pt_mw'] / pt_sum_por_central).round(4)

    # =========================================================
    # REPORTE
    # =========================================================
    print(f"\n{'='*60}")
    print(f"GENERATORS_2024")
    print(f"{'='*60}")
    print(f"\n  p_nom total : {gen_match['p_nom'].sum():,.1f} MW")
    print(f"\n  Por carrier:")
    for carrier, grp in gen_match.groupby('carrier'):
        print(f"    {carrier:<15}: {len(grp):>4} unidades   p_nom={grp['p_nom'].sum():>10,.1f} MW")

    # =========================================================
    # EXPORTAR
    # =========================================================
    cols_out = [
        'gen_key', 'bus_name_origen', 'nombre_geosadi', 'nemo',
        'bus_conexion500kv', 'bus_conexion500kv_name',
        'carrier', 'p_nom', 'lat', 'lon', 'n_saltos', 'camino',
    ]
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    gen_match[cols_out].to_csv(OUTPUT_FILE, index=False)

    print(f"\n  Output: {OUTPUT_FILE}  ({len(gen_match)} filas)")
    print("=" * 60)


if __name__ == "__main__":
    main()
