"""
15_build_loads_2024.py
Construye la tabla de demanda horaria 2024 por bus 500 kV en formato largo.

Inputs:
    Official data/Dda_horaria_x_trafo_2024.csv  (archivo externo a GitHub)
        Demanda horaria 2024 por trafo. Formato ancho: una fila por trafo,
        8784 columnas de valores horarios en MW.
        Encabezado multi-nivel de 4 filas:
            Fila 1: hora del dia (1-24)
            Fila 2: hora acumulada del anio (1-8784)
            Fila 3: fecha calendario
            Fila 4: nombres de columnas de metadata + etiquetas de mes
    data/network_500kv/buses_final.csv
    data/network_500kv/lines_500kv_final.csv
        Se usa para calcular el mapa de fusion de acopladores de barra,
        replicando la logica del script 08. Los buses fusionados en el
        network reciben la demanda acumulada de todos los buses colapsados.

Output:
    data/network_500kv/loads_2024.csv
        Formato largo: una fila por bus 500 kV por hora.
        Columnas: bus_id, bus_name, datetime, p_mw
        ~95 buses x 8784 horas = ~834.000 filas

Logica:
    1. Parsear encabezado para construir el indice datetime de las 8784 columnas
       usando fecha (fila 3) + hora del dia (fila 1).
    2. Leer cuerpo de datos con columnas de metadata + valores horarios.
    3. Pivotear a formato largo por trafo.
    4. Agrupar por bus_id + datetime sumando todos los trafos del mismo
       bus 500 kV.
    5. Verificar cobertura contra buses_final.csv.
    6. Exportar loads_2024.csv.

Correr desde WSL:
    python /mnt/c/Work/pypsa-ar-base/scripts/network_500kv/15_build_loads_2024.py
"""

import os
import sys
import pandas as pd
import numpy as np

# =============================================================================
# CONFIGURACION
# =============================================================================

DDA_FILE    = "/mnt/c/Work/pypsa-ar-sandbox/Official data/Dda_horaria_x_trafo_2024.csv"
BUSES_FILE  = "/mnt/c/Work/pypsa-ar-base/data/network_500kv/buses_final.csv"
LINES_FILE  = "/mnt/c/Work/pypsa-ar-base/data/network_500kv/lines_500kv_final.csv" 
OUTPUT_DIR  = "/mnt/c/Work/pypsa-ar-base/data/network_500kv"
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "loads_2024.csv")

# Columnas de metadata en fila 4 (indices 0-25)
N_META_COLS = 26

# Columnas de metadata que se conservan
COLS_META = ['trafo_id', 'bus_id', 'bus_name']


# =============================================================================
# FUNCIONES AUXILIARES
# =============================================================================

def construir_datetimes(fila_fecha, fila_hora):
    """
    Construye una lista de timestamps a partir de los vectores de fecha y hora
    del encabezado del archivo.

    fila_fecha: lista de strings tipo '1/1/2024', '1/1/2024', ..., '31/12/2024'
    fila_hora : lista de strings tipo '1', '2', ..., '24'
    """
    datetimes = []
    for fecha_str, hora_str in zip(fila_fecha, fila_hora):
        if fecha_str == 'nan' or hora_str == 'nan':
            continue
        fecha = pd.to_datetime(fecha_str.strip(), dayfirst=True, errors='coerce')
        hora  = int(hora_str) - 1  # HORA=1 -> 00:00, HORA=24 -> 23:00
        datetimes.append(fecha + pd.Timedelta(hours=hora))
    return datetimes


# =============================================================================
# FUSION MAP — replica la logica Union-Find del script 08
# Los buses fusionados en el network deben recibir la demanda acumulada
# de todos los buses que fueron colapsados sobre ellos.
# =============================================================================

def calcular_fusion_map(buses, lines):
    """
    Detecta acopladores de barra (series_compensator con r_pu=0) y calcula
    el mapa bus_name -> bus_name_representante usando Union-Find.
    Es la misma logica que el bloque [1b] del script 08.
    """
    id_to_name = dict(zip(buses['bus_id'].astype(int), buses['bus_name']))
    all_bus_ids = set(buses['bus_id'].astype(int))

    couplers = lines[
        (lines['element_type'] == 'series_compensator') &
        (lines['r_pu'] == 0.0)
    ]

    parent = {}

    def find(x):
        while parent.get(x, x) != x:
            parent[x] = parent.get(parent.get(x, x), parent.get(x, x))
            x = parent.get(x, x)
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra == rb:
            return
        try:
            if int(ra) > int(rb):
                ra, rb = rb, ra
        except (ValueError, TypeError):
            pass
        parent[rb] = ra

    for _, row in couplers.iterrows():
        union(str(int(row['bus_i'])), str(int(row['bus_j'])))

    all_bus_id_strs = set(str(bid) for bid in all_bus_ids)
    fusion_map_ids  = {b: find(b) for b in all_bus_id_strs if find(b) != b}

    fusion_map = {}
    for child_id_str, root_id_str in fusion_map_ids.items():
        child_name = id_to_name.get(int(child_id_str))
        root_name  = id_to_name.get(int(root_id_str))
        if child_name and root_name:
            fusion_map[child_name] = root_name

    return fusion_map


# =============================================================================
# MAIN
# =============================================================================

def main():
    print("=" * 60)
    print("15_build_loads_2024.py -- demanda horaria 2024 por bus")
    print("=" * 60)

    for f in [DDA_FILE, BUSES_FILE, LINES_FILE]:
        if not os.path.isfile(f):
            print(f"[ERROR] Archivo no encontrado:\n  {f}")
            sys.exit(1)

    # Calcular fusion_map al inicio para usarlo en el paso 4
    buses_df   = pd.read_csv(BUSES_FILE)
    lines_df   = pd.read_csv(LINES_FILE)
    fusion_map = calcular_fusion_map(buses_df, lines_df)
    print(f"  Buses fusionados detectados: {len(fusion_map)}")

    # =========================================================
    # 1. PARSEAR ENCABEZADO — construir indice datetime
    # =========================================================
    print("\n[1/5] Parseando encabezado ...")

    header_raw = pd.read_csv(
        DDA_FILE, sep=';', encoding='latin-1',
        header=None, nrows=4
    )

    # Extraer vectores de fecha y hora para las columnas de valores
    fila_hora  = header_raw.iloc[0, N_META_COLS:].astype(str).tolist()
    fila_fecha = header_raw.iloc[2, N_META_COLS:].astype(str).tolist()

    datetimes = construir_datetimes(fila_fecha, fila_hora)
    n_horas   = len(datetimes)

    print(f"  Horas en el archivo : {n_horas}")
    print(f"  Rango               : {datetimes[0]}  ->  {datetimes[-1]}")

    if n_horas != 8784:
        print(f"  [AVISO] Se esperaban 8784 horas (2024 bisiesto)")

    n_nat = sum(1 for dt in datetimes if pd.isna(dt))
    if n_nat > 0:
        print(f"  [AVISO] {n_nat} timestamps NaT — revisar encabezado")

    # =========================================================
    # 2. LEER CUERPO DE DATOS
    # =========================================================
    print(f"\n[2/5] Leyendo cuerpo de datos ...")

    # Nombres de columnas: metadata desde fila 4 + datetimes para el resto
    col_names_meta   = header_raw.iloc[3, :N_META_COLS].tolist()
    col_names_horas  = [str(dt) for dt in datetimes]
    # El archivo tiene columnas vacías al final — agregar dummy para alinear
    n_cols_archivo   = pd.read_csv(DDA_FILE, sep=';', encoding='latin-1',
                                   header=None, nrows=1).shape[1]
    n_dummy          = n_cols_archivo - N_META_COLS - len(col_names_horas)
    col_names_dummy  = [f'_dummy_{i}' for i in range(n_dummy)]
    col_names        = col_names_meta + col_names_horas + col_names_dummy

    df = pd.read_csv(
        DDA_FILE, sep=';', encoding='latin-1',
        header=None, skiprows=4,
        names=col_names,
        low_memory=False,
    )

    # Eliminar fila final vacia si existe
    df = df.dropna(subset=['trafo_id'])
    df['trafo_id'] = df['trafo_id'].astype(int)
    df['bus_id']   = pd.to_numeric(df['bus_id'], errors='coerce').astype('Int64')

    print(f"  Trafos leidos       : {len(df)}")
    print(f"  bus_id unicos       : {df['bus_id'].nunique()}")

    # =========================================================
    # 3. PIVOTEAR A FORMATO LARGO
    # =========================================================
    print(f"\n[3/5] Pivoteando a formato largo ...")

    # Convertir columnas horarias a numerico
    hora_cols = col_names_horas
    df[hora_cols] = df[hora_cols].apply(pd.to_numeric, errors='coerce')

    # Melt: una fila por trafo por hora
    df_long = df[['trafo_id', 'bus_id', 'bus_name'] + hora_cols].melt(
        id_vars=['trafo_id', 'bus_id', 'bus_name'],
        var_name='datetime',
        value_name='p_mw',
    )

    df_long['datetime'] = pd.to_datetime(df_long['datetime'], errors='coerce').dt.strftime('%d/%m/%Y %H:%M')

    print(f"  Filas post-melt     : {len(df_long):,}")

    # =========================================================
    # 4. AGRUPAR POR BUS + DATETIME
    # =========================================================
    # Aplicar fusion_map: redirigir demanda de buses fusionados al representante.
    # Se remapea bus_name y se actualiza bus_id al del representante para que
    # el groupby consolide correctamente la demanda.
    name_to_id = dict(zip(buses_df['bus_name'], buses_df['bus_id']))
    df_long['bus_name'] = df_long['bus_name'].map(lambda x: fusion_map.get(x, x))
    df_long['bus_id']   = df_long['bus_name'].map(name_to_id)

    print(f"\n[4/5] Agrupando por bus_id + datetime ...")

    loads = (
        df_long
        .groupby(['bus_id', 'bus_name', 'datetime'], as_index=False)['p_mw']
        .sum()
    )

    loads['_sort'] = pd.to_datetime(loads['datetime'], format='%d/%m/%Y %H:%M')
    loads = loads.sort_values(['bus_id', '_sort']).drop(columns='_sort').reset_index(drop=True)

    print(f"  Filas output        : {len(loads):,}")
    print(f"  Buses unicos        : {loads['bus_id'].nunique()}")
    print(f"  Horas unicas        : {loads['datetime'].nunique()}")
    print(f"  p_mw total promedio : {loads['p_mw'].mean():,.1f} MW")

    # =========================================================
    # 5. VERIFICAR COBERTURA
    # Se compara contra los buses 500kV que existen en el network
    # (excluyendo los fusionados que desaparecen del network).
    # =========================================================
    print(f"\n[5/5] Verificando cobertura ...")

    buses_500_nombres = set(
        buses_df[buses_df['baskv_kv'] == 500]['bus_name']
    ) - set(fusion_map.keys())

    buses_load_nombres = set(loads['bus_name'].unique())

    en_red_sin_dda = buses_500_nombres - buses_load_nombres
    en_dda_sin_red = buses_load_nombres - buses_500_nombres

    print(f"  Buses 500kV en network        : {len(buses_500_nombres)}")
    print(f"  Buses con demanda en DDA      : {len(buses_load_nombres)}")

    if en_red_sin_dda:
        print(f"  [AVISO] Buses en network sin demanda: {len(en_red_sin_dda)}")
        for b in sorted(en_red_sin_dda)[:10]:
            print(f"    {b}")
    else:
        print(f"  Todos los buses del network tienen demanda  OK")

    if en_dda_sin_red:
        print(f"  [AVISO] Buses en DDA sin match en network: {len(en_dda_sin_red)}")
        for b in sorted(en_dda_sin_red)[:10]:
            print(f"    {b}")

    # =========================================================
    # EXPORTAR
    # =========================================================
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    loads.to_csv(OUTPUT_FILE, index=False)

    print(f"\n{'='*60}")
    print(f"  Output: {OUTPUT_FILE}")
    print(f"  Filas : {len(loads):,}")
    print(f"  Buses : {loads['bus_id'].nunique()}")
    print("=" * 60)


if __name__ == "__main__":
    main()
