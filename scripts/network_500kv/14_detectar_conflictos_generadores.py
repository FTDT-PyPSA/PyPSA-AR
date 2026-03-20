"""
14_detectar_conflictos_generadores.py
Detecta conflictos entre los nombres de unidades del modelo (PSS/E) y los
GRUPOs de CAMMESA, y genera un CSV para resolverlos manualmente.

Un conflicto existe cuando una unidad del modelo no tiene match directo en
CAMMESA (bus_name_origen no es un GRUPO valido) Y la central a la que
pertenece tiene mas de un GRUPO en CAMMESA. En ese caso no es posible
determinar automaticamente que GRUPO de CAMMESA le corresponde.

Inputs:
    data/network_500kv/generators_final.csv
    Official data/valores_2024_clean.csv  (archivo externo a GitHub)

Output:
    data/network_500kv/conflictos_psse_cammesa.csv
        Una fila por unidad con conflicto.
        Columnas a completar manualmente:
            bus_name_origen_correcto: GRUPO de CAMMESA que corresponde a
                esta unidad segun el unifilar. Dejar vacio si no hay match.
            comentario: observaciones del unifilar.

        Si el archivo ya existe se preservan las resoluciones completadas.
        Las filas nuevas se agregan con bus_name_origen_correcto vacio.

Flujo:
    14  → genera/actualiza conflictos_psse_cammesa.csv
    completar manualmente el CSV
    14b → lee CSV resuelto + genera generators_2024.csv

Correr desde WSL:
    python /mnt/c/Work/pypsa-ar-base/scripts/network_500kv/14_detectar_conflictos_generadores.py
"""

import os
import sys
import pandas as pd

# =============================================================================
# CONFIGURACION
# =============================================================================

GEN_FILE        = "/mnt/c/Work/pypsa-ar-base/data/network_500kv/generators_final.csv"
VALORES_FILE    = "/mnt/c/Work/pypsa-ar-sandbox/Official data/valores_2024_clean.csv"
CONFLICTOS_FILE = "/mnt/c/Work/pypsa-ar-base/data/network_500kv/conflictos_psse_cammesa.csv"


# =============================================================================
# MAIN
# =============================================================================

def main():
    print("=" * 60)
    print("14_detectar_conflictos_generadores.py")
    print("=" * 60)

    for f in [GEN_FILE, VALORES_FILE]:
        if not os.path.isfile(f):
            print(f"[ERROR] Archivo no encontrado:\n  {f}")
            sys.exit(1)

    # =========================================================
    # CARGAR DATOS
    # =========================================================
    gen = pd.read_csv(GEN_FILE)
    gen['nemo4'] = gen['nemo'].fillna('').str[:4].str.strip()

    print(f"\nUnidades en modelo: {len(gen)}")

    vals = pd.read_csv(
        VALORES_FILE,
        usecols=['GRUPO', 'Central'],
        low_memory=False,
    ).drop_duplicates()

    grupos_cammesa = set(vals['GRUPO'].unique())

    grupos_por_central = (
        vals.groupby('Central')['GRUPO']
        .apply(lambda x: sorted(x.unique()))
    )
    n_grupos_por_central = grupos_por_central.apply(len)

    print(f"GRUPOs en CAMMESA : {len(grupos_cammesa)}")

    # =========================================================
    # DETECTAR CONFLICTOS
    # =========================================================
    sin_match_directo = gen[~gen['bus_name_origen'].isin(grupos_cammesa)].copy()

    conflictos = sin_match_directo[
        sin_match_directo['nemo4'].isin(
            n_grupos_por_central[n_grupos_por_central > 1].index
        )
    ].copy()

    print(f"\nUnidades sin match directo : {len(sin_match_directo)}")
    print(f"Conflictos detectados      : {len(conflictos)}")
    print(f"Centrales con conflicto    : {conflictos['nemo4'].nunique()}")

    # =========================================================
    # PRESERVAR RESOLUCIONES EXISTENTES
    # =========================================================
    resoluciones_previas = {}
    comentarios_previos  = {}
    revisados_previos    = {}
    excluir_previos      = {}

    if os.path.isfile(CONFLICTOS_FILE):
        existente = pd.read_csv(CONFLICTOS_FILE, encoding='latin-1')
        for _, row in existente.iterrows():
            gkey = row['gen_key']
            val  = row['bus_name_origen_correcto']
            com  = row['comentario']
            rev  = row.get('revisado', '')
            if pd.notna(val) and str(val).strip() != '':
                resoluciones_previas[gkey] = str(val).strip()
            if pd.notna(com) and str(com).strip() != '':
                comentarios_previos[gkey] = str(com).strip()
            if pd.notna(rev) and str(rev).strip() != '':
                revisados_previos[gkey] = str(rev).strip()
            excl = row.get('excluir', '')
            if pd.notna(excl) and str(excl).strip() != '':
                excluir_previos[gkey] = str(excl).strip()

        n_previas = len(resoluciones_previas)
        print(f"\nResoluciones previas preservadas: {n_previas}")

    # =========================================================
    # CONSTRUIR CSV
    # =========================================================
    conflictos['grupos_cammesa'] = conflictos['nemo4'].map(
        grupos_por_central.apply(lambda x: '|'.join(x))
    )
    conflictos['n_grupos_cammesa'] = conflictos['nemo4'].map(n_grupos_por_central)

    conflictos['bus_name_origen_correcto'] = conflictos['gen_key'].map(
        resoluciones_previas
    ).fillna('')

    conflictos['comentario'] = conflictos['gen_key'].map(
        comentarios_previos
    ).fillna('')

    conflictos['revisado'] = conflictos['gen_key'].map(
        revisados_previos
    ).fillna('')

    conflictos['excluir'] = conflictos['gen_key'].map(
        excluir_previos
    ).fillna('')

    cols_out = [
        'gen_key', 'bus_name_origen', 'nombre_geosadi',
        'bus_conexion500kv_name', 'nemo4', 'carrier',
        'grupos_cammesa', 'n_grupos_cammesa',
        'bus_name_origen_correcto', 'revisado', 'excluir', 'comentario',
    ]

    conflictos[cols_out].sort_values(['nemo4', 'gen_key']).to_csv(
        CONFLICTOS_FILE, index=False
    )

    tiene_match    = conflictos['bus_name_origen_correcto'] != ''
    es_excluido    = conflictos['excluir'].str.strip().str.lower() == 'si'
    es_revisado    = (conflictos['revisado'].str.strip().str.lower() == 'si') & ~tiene_match & ~es_excluido

    n_con_match    = tiene_match.sum()
    n_excluidos    = es_excluido.sum()
    n_revisados    = es_revisado.sum()
    n_pendientes   = len(conflictos) - n_con_match - n_excluidos - n_revisados

    print(f"\nCon match asignado : {n_con_match}")
    print(f"Excluidos          : {n_excluidos}")
    print(f"Revisados sin match: {n_revisados}")
    print(f"Pendientes         : {n_pendientes}")
    print(f"\nOutput: {CONFLICTOS_FILE}")
    print("\nCompletar 'bus_name_origen_correcto' en el CSV y correr script 14b.")
    print("=" * 60)


if __name__ == "__main__":
    main()
