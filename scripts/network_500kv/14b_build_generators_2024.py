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
    Match directo (bus_name_origen existe como GRUPO en CAMMESA):
        p_nom = percentil 95 de POT_DISP de ese GRUPO especifico.

    Match por nemo4 (bus_name_origen no existe como GRUPO, pero nemo4
    existe como Central en CAMMESA):
        p_nom = percentil 95 de POT_DISP de la Central entera,
        distribuido proporcionalmente al pt_mw del PSS/E entre las
        unidades de esa central.

    En ambos casos se usa p95 para evitar outliers puntuales.

    Central binacional SGDE (Salto Grande, Argentina/Uruguay):
    CAMMESA reporta la potencia total. Se aplica factor 0.5 antes
    de calcular p_nom para quedarse con la parte argentina.

    Validacion de carrier vs TIPO CAMMESA:
    Unidades cuyo carrier en el modelo no es compatible con el TIPO
    reportado por CAMMESA para esa Central o GRUPO se excluyen
    automaticamente. Evita que unidades mal clasificadas en el PSS/E
    reciban perfiles de generacion de una tecnologia distinta.

Resolucion de conflictos:
    Se aplican los overrides de conflictos_psse_cammesa.csv:
        excluir = si              -> unidad excluida del modelo
        bus_name_origen_correcto  -> reemplaza bus_name_origen para el
                                     match con CAMMESA
        revisado = si (sin match) -> va al nemo4 normalmente

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

# Tipos CAMMESA validos por carrier del modelo.
# Unidades cuyo TIPO en CAMMESA no corresponde a ningun tipo valido
# para su carrier son excluidas automaticamente.
CARRIER_TIPO_VALIDO = {
    'hydro'       : ['Hidraulica', 'Hidraulica renovable'],
    'pumped_hydro': ['Hidraulica'],
    'ocgt'        : ['Turbina a gas', 'Ciclos Combinados', 'Turbovapor'],
    'ccgt'        : ['Ciclos Combinados', 'Turbina a gas'],
    'steam'       : ['Vapor', 'Ciclos Combinados', 'Turbovapor', 'Turbina a gas'],
    'nuclear'     : ['Nuclear'],
    'wind'        : ['Eolica'],
    'solar'       : ['Solar'],
    'diesel'      : ['Motor Diesel'],
    'biogas'      : ['Biogas'],
    'biomass'     : ['Biomasa'],
}


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
    tiene_match = conflictos['bus_name_origen_correcto'].fillna('').str.strip() != ''
    es_excluido = conflictos['excluir'].fillna('').str.strip().str.lower() == 'si'
    es_revisado = conflictos['revisado'].fillna('').str.strip().str.lower() == 'si'
    pendientes  = conflictos[~tiene_match & ~es_excluido & ~es_revisado]

    if len(pendientes) > 0:
        print(f"\n[ERROR] Hay {len(pendientes)} conflictos pendientes en {CONFLICTOS_FILE}")
        print(pendientes[['gen_key', 'bus_name_origen', 'nemo4']].to_string(index=False))
        print("\nCompletar el CSV y volver a correr el script 14.")
        sys.exit(1)

    # =========================================================
    # APLICAR RESOLUCIONES DE CONFLICTOS
    # =========================================================
    excluir_keys = set(conflictos[es_excluido]['gen_key'].astype(str))
    gen = gen[~gen['gen_key'].astype(str).isin(excluir_keys)].copy()
    print(f"Unidades excluidas por conflicto : {len(excluir_keys)}")

    match_map = conflictos[tiene_match].set_index('gen_key')['bus_name_origen_correcto'].to_dict()
    mask_override = gen['gen_key'].astype(str).isin(match_map)
    gen.loc[mask_override, 'bus_name_origen'] = (
        gen.loc[mask_override, 'gen_key'].astype(str).map(match_map)
    )
    print(f"Overrides aplicados              : {mask_override.sum()}")

    gen['nemo4'] = gen['nemo'].fillna('').str[:4].str.strip()

    # =========================================================
    # CALCULAR p95 POR GRUPO Y POR CENTRAL DESDE CAMMESA
    # =========================================================
    print(f"\nLeyendo valores_2024_clean.csv ...")

    df = pd.read_csv(
        VALORES_FILE,
        usecols=['GRUPO', 'Central', 'TIPO', 'POT_DISP', 'flag_outlier'],
        low_memory=False,
    )
    df_clean = df[df['flag_outlier'] == False]

    # p95 por GRUPO — para match directo
    p95_por_grupo = (
        df_clean.groupby('GRUPO')['POT_DISP']
        .quantile(P_NOM_PERCENTILE / 100)
    )

    # p95 por Central — para match por nemo4
    p95_por_central = (
        df_clean.groupby('Central')['POT_DISP']
        .quantile(P_NOM_PERCENTILE / 100)
    )

    # Aplicar factor binacional
    for nemo4, factor in BINACIONAL_FACTOR.items():
        if nemo4 in p95_por_central.index:
            p95_por_central[nemo4] *= factor
            print(f"  {nemo4}: p_nom x {factor} (central binacional)")

    grupos_cammesa    = set(p95_por_grupo.index)
    centrales_cammesa = set(p95_por_central.index)

    # TIPO por GRUPO y por Central para validacion de carrier
    tipo_por_grupo    = df_clean.groupby('GRUPO')['TIPO'].apply(
        lambda x: list(x.unique())
    ).to_dict()
    tipo_por_central_map = df_clean.groupby('Central')['TIPO'].apply(
        lambda x: list(x.unique())
    ).to_dict()

    print(f"GRUPOs en CAMMESA   : {len(grupos_cammesa)}")
    print(f"Centrales en CAMMESA: {len(centrales_cammesa)}")

    # =========================================================
    # VALIDAR CARRIER VS TIPO CAMMESA
    # =========================================================
    def carrier_compatible(carrier, tipos):
        tipos_ok = CARRIER_TIPO_VALIDO.get(carrier, [])
        return any(t in tipos for t in tipos_ok)

    excluir_carrier = set()
    for _, row in gen.iterrows():
        carrier    = row['carrier']
        bus_origen = row['bus_name_origen']
        nemo4      = row['nemo4']
        tipos = tipo_por_grupo.get(bus_origen) or tipo_por_central_map.get(nemo4)
        if tipos and not carrier_compatible(carrier, tipos):
            excluir_carrier.add(row['gen_key'])

    if excluir_carrier:
        excluir_p_nom = gen[gen['gen_key'].isin(excluir_carrier)]['pt_mw']
        excluir_p_nom = excluir_p_nom[excluir_p_nom < 9000].sum()
        print(f"\nUnidades excluidas por carrier incompatible : {len(excluir_carrier)}")
        for gkey in sorted(excluir_carrier):
            fila       = gen[gen['gen_key'] == gkey].iloc[0]
            bus_origen = fila['bus_name_origen']
            nemo4      = fila['nemo4']
            tipos      = tipo_por_grupo.get(bus_origen) or tipo_por_central_map.get(nemo4) or []
            print(f"  {gkey:<10} {bus_origen:<12} carrier={fila['carrier']:<8} CAMMESA={tipos}")
        gen = gen[~gen['gen_key'].isin(excluir_carrier)].copy()

    # =========================================================
    # ASIGNAR p_nom POR UNIDAD
    # =========================================================
    p_nom_list      = []
    match_type_list = []

    pt_sum = gen.groupby('nemo4')['pt_mw'].transform('sum')

    for idx, row in gen.iterrows():
        bus_origen = row['bus_name_origen']
        nemo4      = row['nemo4']
        pt_mw      = row['pt_mw']

        if bus_origen in grupos_cammesa:
            p_nom = p95_por_grupo[bus_origen]
            match_type_list.append('directo')

        elif nemo4 in centrales_cammesa:
            pt_total  = pt_sum[idx]
            p_central = p95_por_central[nemo4]
            p_nom     = p_central * (pt_mw / pt_total) if pt_total > 0 else 0.0
            match_type_list.append('nemo4')

        else:
            p_nom = 0.0
            match_type_list.append('sin_match')

        p_nom_list.append(round(max(p_nom, 0.0), 4))

    gen['p_nom']      = p_nom_list
    gen['match_type'] = match_type_list

    # =========================================================
    # SEPARAR CON Y SIN MATCH
    # =========================================================
    gen_match    = gen[gen['match_type'] != 'sin_match'].copy()
    gen_excluded = gen[gen['match_type'] == 'sin_match'].copy()

    print(f"\nMatch directo por GRUPO : {(gen['match_type']=='directo').sum()}")
    print(f"Match por nemo4         : {(gen['match_type']=='nemo4').sum()}")
    print(f"Sin match               : {len(gen_excluded)}")

    if len(gen_excluded) > 0:
        excl_summary = gen_excluded.drop_duplicates('nemo4')[
            ['nombre_geosadi', 'nemo4', 'carrier']
        ].sort_values('nemo4')
        print("\n  Centrales sin match en CAMMESA:")
        for _, row in excl_summary.iterrows():
            print(f"    {row['nemo4']:<8} {row['carrier']:<12} {row['nombre_geosadi']}")

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
