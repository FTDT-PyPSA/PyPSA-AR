"""
13_build_generators_2024.py
Construye la tabla definitiva de generadores con datos reales de CAMMESA 2024,
reemplazando los valores de potencia del snapshot PSS/E.

Inputs:
    data/network_500kv/generators_final.csv
    Official data/VALORES_2024.csv

Output:
    data/network_500kv/generators_2024.csv

Logica de p_nom:
    Para cada central (nemo4), p_nom = percentil 95 de POT_DISP del año en CAMMESA.
    Se usa p95 en lugar del maximo para evitar outliers (datos erroneos puntuales).
    El valor se distribuye proporcionalmente al pt_mw del PSS/E de cada unidad
    dentro de la central. Esto respeta la capacidad relativa de cada maquina
    (una TV de 280 MW no es igual que una TG de 51 MW).

    Excepcion SGDE (Salto Grande): central binacional Argentina-Uruguay.
    CAMMESA reporta la potencia total de la represa. Se divide por 2
    antes de distribuir entre las unidades argentinas del modelo.

Reasignacion CAPE/ACAJ:
    CAPEX (CAPE en CAMMESA) y Agua del Cajon (ACAJ) son comercialmente
    separados pero fisicamente la misma central. Las unidades TG01, TG06
    y TV07 pertenecen a CAPE. Se reasigna su nemo4 antes del join con CAMMESA.

Centrales excluidas:
    Las que no tienen match en CAMMESA por nemo4 — autoproductores y centrales
    fuera del Mercado Electrico Mayorista. Se listan en el reporte.

Correr desde WSL:
    python /mnt/c/Work/pypsa-ar-base/scripts/network_500kv/13_build_generators_2024.py
"""

import os
import sys
import pandas as pd
import numpy as np

# =============================================================================
# CONFIGURACION
# =============================================================================

GEN_FILE      = "/mnt/c/Work/pypsa-ar-base/data/network_500kv/generators_final.csv"
VALORES_FILE  = "/mnt/c/Work/pypsa-ar-sandbox/Official data/VALORES_2024.csv"
OUTPUT_DIR    = "/mnt/c/Work/pypsa-ar-base/data/network_500kv"
OUTPUT_FILE   = os.path.join(OUTPUT_DIR, "generators_2024.csv")

# Central binacional: CAMMESA reporta potencia total, dividir por 2
# para quedarse solo con la parte argentina
BINACIONAL_FACTOR = {
    'SGDE': 0.5,   # Salto Grande — Argentina/Uruguay
}

# Percentil para p_nom (evita outliers en POT_DISP)
P_NOM_PERCENTILE = 95

# Reasignacion de nemo por gen_key individual
# Unidades que en el PSS/E figuran bajo ACAJ pero comercialmente son CAPE
NEMO_OVERRIDE = {
    '1601-1': 'CAPE',   # ACAJTG01 → CAPEX
    '1600-6': 'CAPE',   # ACAJTG06 → CAPEX
    '1606-1': 'CAPE',   # ACAJTV07 → CAPEX
}


# =============================================================================
# MAIN
# =============================================================================

def main():
    print("=" * 60)
    print("13_build_generators_2024.py -- generadores reales 2024")
    print("=" * 60)

    for f in [GEN_FILE, VALORES_FILE]:
        if not os.path.isfile(f):
            print(f"[ERROR] Archivo no encontrado:\n  {f}")
            sys.exit(1)

    # ==========================================================
    # CARGAR GENERADORES DEL MODELO
    # ==========================================================
    gen = pd.read_csv(GEN_FILE)
    gen['nemo4'] = gen['nemo'].fillna('').str[:4].str.strip()

    print(f"\nGeneradores en modelo         : {len(gen)}")

    # Aplicar reasignaciones de nemo por gen_key
    n_override = 0
    for gkey, nuevo_nemo in NEMO_OVERRIDE.items():
        mask = gen['gen_key'] == gkey
        if mask.sum() > 0:
            gen.loc[mask, 'nemo4'] = nuevo_nemo
            gen.loc[mask, 'nemo']  = nuevo_nemo
            n_override += 1
    if n_override:
        print(f"Reasignaciones CAPE/ACAJ      : {n_override} unidades → CAPE")

    # ==========================================================
    # CALCULAR p_nom DESDE CAMMESA (percentil 95 de POT_DISP)
    # ==========================================================
    print(f"\nLeyendo VALORES_2024.csv (puede demorar)...")
    df = pd.read_csv(VALORES_FILE, sep=';', encoding='latin-1',
                     usecols=['Central', 'POT_DISP'])

    pot_p95 = df.groupby('Central')['POT_DISP'].quantile(P_NOM_PERCENTILE / 100)
    centrales_cammesa = set(pot_p95.index)

    print(f"Centrales en CAMMESA          : {len(centrales_cammesa)}")

    # Aplicar factor de centrales binacionales
    for nemo4, factor in BINACIONAL_FACTOR.items():
        if nemo4 in pot_p95.index:
            pot_p95[nemo4] = pot_p95[nemo4] * factor
            print(f"  ℹ {nemo4}: p_nom CAMMESA × {factor} (central binacional)")

    # ==========================================================
    # SEPARAR CON Y SIN MATCH
    # ==========================================================
    mask_match = gen['nemo4'].isin(centrales_cammesa) & (gen['nemo4'] != '')
    gen_match    = gen[mask_match].copy()
    gen_excluded = gen[~mask_match].copy()

    print(f"\nCon match en CAMMESA          : {len(gen_match)} unidades")
    print(f"Sin match (excluidos)         : {len(gen_excluded)} unidades")
    if len(gen_excluded) > 0:
        excl_summary = gen_excluded.drop_duplicates('nemo4')[
            ['nombre_geosadi', 'nemo4', 'carrier']
        ].sort_values('nemo4')
        print("\n  Centrales excluidas:")
        for _, row in excl_summary.iterrows():
            print(f"    {row['nemo4']:<8} {row['carrier']:<12} {row['nombre_geosadi']}")

    # ==========================================================
    # DISTRIBUIR p_nom PROPORCIONALMENTE AL pt_mw DEL PSS/E
    # El pt_mw del PSS/E refleja la capacidad tecnica de cada maquina
    # y es valido como ponderador de distribucion (no es dato de despacho)
    # ==========================================================
    pt_sum_por_central = gen_match.groupby('nemo4')['pt_mw'].transform('sum')
    p95_por_central    = gen_match['nemo4'].map(pot_p95)

    gen_match['p_nom'] = (p95_por_central * gen_match['pt_mw'] / pt_sum_por_central).round(4)

    # ==========================================================
    # REPORTE
    # ==========================================================
    print(f"\n{'='*60}")
    print(f"GENERATORS_2024")
    print(f"{'='*60}")
    print(f"\n  p_nom total del sistema       : {gen_match['p_nom'].sum():,.1f} MW")

    print(f"\n  Por carrier:")
    for carrier, grp in gen_match.groupby('carrier'):
        print(f"    {carrier:<15}: {len(grp):>4} unidades   p_nom={grp['p_nom'].sum():>10,.1f} MW")

    # ==========================================================
    # EXPORTAR
    # ==========================================================
    cols_out = [
        'gen_key', 'bus_name_origen', 'nombre_geosadi', 'nemo',
        'bus_conexion500kv', 'bus_conexion500kv_name',
        'carrier', 'p_nom',
        'lat', 'lon',
        'n_saltos', 'camino',
    ]
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    gen_match[cols_out].to_csv(OUTPUT_FILE, index=False)

    print(f"\n✔ {OUTPUT_FILE}  ({len(gen_match)} filas)")
    print(f"\nProximo: 14_build_loads_2024.py")


if __name__ == "__main__":
    main()
