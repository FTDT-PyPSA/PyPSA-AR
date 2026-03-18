"""
13_clean_valores_2024.py
Limpieza y validacion de VALORES_2024.csv (datos horarios de generacion CAMMESA).
Produce valores_2024_clean.csv — archivo confiable que usan todos los scripts
downstream (15, 17, 18).

Input:
    Official data/VALORES_2024.csv (archivo externo a github)
        Archivo horario de generacion 2024 del Mercado Electrico Mayorista.
        ~8.8 millones de filas. Una fila por unidad (GRUPO) por hora.
        Separador: punto y coma. Encoding: latin-1.

Output:
    Official data/valores_2024_clean.csv
        Solo filas del año 2024 (el archivo original contiene tambien datos de 2025).
        Misma estructura por fila que el input (no se eliminan filas de 2024).
        Columnas normalizadas + columna datetime + columna flag_outlier.

Transformaciones aplicadas:
    1. Se leen solo las columnas de interes fisico/operativo.
       Se excluye POT_RECONOC (campo de liquidacion economica sin uso en el modelo).

    2. Normalizacion de fechas:
       Formatos detectados en el archivo original:
         - 'd/mm/yy'         (dias 1-9, enero/mayo/junio)
         - 'dd/mm/yy'        (resto de enero/mayo/junio)
         - 'dd/mm/yy 00:00'  (febrero a diciembre)
       Todos se convierten a 'dd/mm/yyyy' (zero-pad del dia, anio 4 digitos).

    3. Filtro de anio: se descartan todas las filas cuya fecha normalizada
       no pertenece a 2024. El archivo original contiene datos hasta junio 2025.

    4. Se agrega columna datetime = FECHA + HORA (timestamp completo).
       HORA va de 1 a 24 siguiendo convencion CAMMESA.
       Se convierte como: datetime = fecha + (HORA - 1) horas.
       Ejemplo: FECHA=01/01/2024, HORA=1  -> 2024-01-01 00:00:00
                FECHA=01/01/2024, HORA=24 -> 2024-01-01 23:00:00

    5. Deteccion de outliers por GRUPO:
       Se marca flag_outlier = True si cualquiera de estas condiciones aplica:
         a. ENERGIA  < 0
         b. POT_DISP < 0
         c. ENERGIA  > percentil 99.9 de ENERGIA  del GRUPO en el anio
         d. POT_DISP > percentil 99.9 de POT_DISP del GRUPO en el anio
       No se eliminan filas. El flag permite que scripts downstream
       decidan como tratar cada caso.

Correr desde WSL:
    python /mnt/c/Work/pypsa-ar-base/scripts/network_500kv/13_clean_valores_2024.py
"""

import os
import sys
import pandas as pd
import numpy as np

# =============================================================================
# CONFIGURACION
# =============================================================================

VALORES_FILE = "/mnt/c/Work/pypsa-ar-sandbox/Official data/valores_2024.csv"
OUTPUT_FILE  = "/mnt/c/Work/pypsa-ar-sandbox/Official data/valores_2024_clean.csv"

# Filas por chunk — reducir si hay problemas de memoria
CHUNK_SIZE = 500_000

# Columnas a leer del archivo original
# Se excluye POT_RECONOC (campo de liquidacion economica)
COLS_LEER = [
    'FECHA', 'HORA', 'GRUPO', 'TIPO', 'Central', 'Region',
    'ENERGIA', 'POT_DISP', 'ENERG_OPERADA', 'POT_DISP_GN', 'PIND',
]

# Columnas en el output
COLS_OUTPUT = [
    'FECHA', 'HORA', 'datetime', 'GRUPO', 'TIPO', 'Central', 'Region',
    'ENERGIA', 'POT_DISP', 'ENERG_OPERADA', 'POT_DISP_GN', 'PIND',
    'flag_outlier',
]

# Percentil para deteccion de outliers por exceso
OUTLIER_PERCENTIL = 99.9

# GRUPOs excluidos del archivo limpio.
# YACYHIPY: lado paraguayo de Yacyreta — no forma parte del modelo argentino.
GRUPOS_EXCLUIR = {'YACYHIPY'}

# Centrales binacionales: CAMMESA reporta potencia total de la represa.
# Se aplica el factor antes de escribir al output para quedarse solo
# con la parte argentina.
# SGDE (Salto Grande): Argentina comparte la central con Uruguay al 50%.
FACTOR_BINACIONAL = {'SGDE': 0.5}


# =============================================================================
# FUNCIONES AUXILIARES
# =============================================================================

def normalizar_fecha(serie):
    """
    Convierte todos los formatos de fecha del archivo a 'dd/mm/yyyy'.

    Formatos de entrada:
        'd/mm/yy'        -> '01/01/2024'
        'dd/mm/yy'       -> '01/01/2024'
        'dd/mm/yy 00:00' -> '01/01/2024'
    """
    s = serie.str.strip().str.split(' ').str[0]
    partes = s.str.split('/')
    dia  = partes.str[0].str.zfill(2)
    mes  = partes.str[1].str.zfill(2)
    anio = partes.str[2].apply(lambda x: '20' + x if len(str(x)) == 2 else str(x))
    return dia + '/' + mes + '/' + anio


def construir_datetime(fecha_norm, hora):
    """
    Construye timestamp a partir de fecha normalizada y columna HORA (1-24).
    HORA=1 -> 00:00:00, HORA=24 -> 23:00:00.
    """
    base = pd.to_datetime(fecha_norm, format='%d/%m/%Y', errors='coerce')
    return base + pd.to_timedelta(hora - 1, unit='h')


# =============================================================================
# PASADA 1 — Calcular percentiles 99.9 por GRUPO (solo filas 2024)
# =============================================================================

def pasada_1_percentiles():
    """
    Recorre el archivo en chunks acumulando los valores de ENERGIA y POT_DISP
    por GRUPO, usando unicamente filas de 2024.
    Al final calcula el percentil 99.9 anual para cada GRUPO.

    Retorna dos Series indexadas por GRUPO:
        p999_energia  — umbral de outlier para ENERGIA
        p999_pot_disp — umbral de outlier para POT_DISP
    """
    print("\n[PASADA 1/2] Calculando percentiles 99.9 por GRUPO ...")
    print(f"  Chunk size: {CHUNK_SIZE:,} filas")

    acumulador = {}

    lector = pd.read_csv(
        VALORES_FILE,
        sep=';',
        encoding='latin-1',
        usecols=['FECHA', 'GRUPO', 'ENERGIA', 'POT_DISP'],
        chunksize=CHUNK_SIZE,
        low_memory=False,
    )

    n_chunks  = 0
    n_filas   = 0
    n_descart = 0

    for chunk in lector:
        n_chunks += 1

        # Normalizar fecha y filtrar solo 2024
        chunk['FECHA'] = normalizar_fecha(chunk['FECHA'])
        mask_2024 = chunk['FECHA'].str.endswith('2024')
        n_descart += (~mask_2024).sum()
        chunk = chunk[mask_2024]

        n_filas += len(chunk)

        for grupo, grp in chunk.groupby('GRUPO'):
            if grupo in GRUPOS_EXCLUIR:
                continue
            if grupo not in acumulador:
                acumulador[grupo] = {'e': [], 'p': []}
            acumulador[grupo]['e'].append(grp['ENERGIA'].values)
            acumulador[grupo]['p'].append(grp['POT_DISP'].values)

        if n_chunks % 5 == 0:
            print(f"  ... chunk {n_chunks}, filas 2024 acumuladas: {n_filas:,}")

    print(f"  Pasada 1 completa — {n_filas:,} filas 2024, {n_descart:,} filas descartadas (2025)")
    print(f"  GRUPOs encontrados: {len(acumulador)}")

    p999_energia  = {}
    p999_pot_disp = {}

    for grupo, vals in acumulador.items():
        e_all = np.concatenate(vals['e'])
        p_all = np.concatenate(vals['p'])
        p999_energia[grupo]  = np.nanpercentile(e_all,  OUTLIER_PERCENTIL)
        p999_pot_disp[grupo] = np.nanpercentile(p_all, OUTLIER_PERCENTIL)

    return pd.Series(p999_energia), pd.Series(p999_pot_disp)


# =============================================================================
# PASADA 2 — Transformar y escribir output
# =============================================================================

def pasada_2_transformar(p999_energia, p999_pot_disp):
    """
    Recorre el archivo de nuevo en chunks.
    Para cada chunk:
        - Normaliza fechas
        - Filtra solo filas de 2024
        - Construye datetime
        - Marca flag_outlier usando los umbrales de la pasada 1
        - Escribe al output (append incremental)

    Retorna diccionario con estadisticas para el reporte final.
    """
    print(f"\n[PASADA 2/2] Transformando y escribiendo output ...")
    print(f"  Output: {OUTPUT_FILE}")

    lector = pd.read_csv(
        VALORES_FILE,
        sep=';',
        encoding='latin-1',
        usecols=COLS_LEER,
        chunksize=CHUNK_SIZE,
        low_memory=False,
    )

    n_chunks        = 0
    n_filas         = 0
    n_outliers      = 0
    n_nat           = 0
    primer_chunk    = True
    fechas_unicas   = set()
    grupos_horas    = {}

    cnt_energia_neg  = 0
    cnt_potdisp_neg  = 0
    cnt_energia_p999 = 0
    cnt_potdisp_p999 = 0

    for chunk in lector:
        n_chunks += 1

        # --- Normalizar fechas ---
        chunk['FECHA'] = normalizar_fecha(chunk['FECHA'])

        # --- Filtrar solo 2024 ---
        chunk = chunk[chunk['FECHA'].str.endswith('2024')].copy()

        # --- Excluir GRUPOs no argentinos ---
        chunk = chunk[~chunk['GRUPO'].isin(GRUPOS_EXCLUIR)].copy()

        if len(chunk) == 0:
            continue

        # --- Aplicar factor binacional (ej: SGDE x0.5) ---
        for central, factor in FACTOR_BINACIONAL.items():
            mask_bin = chunk['Central'] == central
            if mask_bin.sum() > 0:
                chunk.loc[mask_bin, 'ENERGIA']       *= factor
                chunk.loc[mask_bin, 'POT_DISP']      *= factor
                chunk.loc[mask_bin, 'ENERG_OPERADA'] *= factor
                chunk.loc[mask_bin, 'POT_DISP_GN']   *= factor

        n_filas += len(chunk)
        fechas_unicas.update(chunk['FECHA'].unique())

        # --- Construir datetime ---
        chunk['datetime'] = construir_datetime(chunk['FECHA'], chunk['HORA'])
        n_nat += chunk['datetime'].isna().sum()
        chunk['datetime'] = chunk['datetime'].dt.strftime('%d/%m/%Y %H:%M')

        # --- Marcar outliers ---
        um_e  = chunk['GRUPO'].map(p999_energia)
        um_pd = chunk['GRUPO'].map(p999_pot_disp)

        crit_a = chunk['ENERGIA']  < 0
        crit_b = chunk['POT_DISP'] < 0
        crit_c = chunk['ENERGIA']  > um_e
        crit_d = chunk['POT_DISP'] > um_pd

        chunk['flag_outlier'] = crit_a | crit_b | crit_c | crit_d

        cnt_energia_neg  += int(crit_a.sum())
        cnt_potdisp_neg  += int(crit_b.sum())
        cnt_energia_p999 += int(crit_c.sum())
        cnt_potdisp_p999 += int(crit_d.sum())
        n_outliers       += int(chunk['flag_outlier'].sum())

        # --- Acumular horas por GRUPO para verificacion ---
        for grupo, grp in chunk.groupby('GRUPO'):
            if grupo not in grupos_horas:
                grupos_horas[grupo] = set()
            grupos_horas[grupo].update(grp['HORA'].unique())

        # --- Escribir al output incrementalmente ---
        modo   = 'w' if primer_chunk else 'a'
        header = primer_chunk
        chunk[COLS_OUTPUT].to_csv(OUTPUT_FILE, index=False, mode=modo, header=header)
        primer_chunk = False

        if n_chunks % 5 == 0:
            print(f"  ... chunk {n_chunks}, filas escritas: {n_filas:,}")

    return {
        'n_filas'        : n_filas,
        'n_outliers'     : n_outliers,
        'n_nat'          : n_nat,
        'fechas_unicas'  : fechas_unicas,
        'grupos_horas'   : grupos_horas,
        'cnt_energia_neg': cnt_energia_neg,
        'cnt_potdisp_neg': cnt_potdisp_neg,
        'cnt_energia_p99': cnt_energia_p999,
        'cnt_potdisp_p99': cnt_potdisp_p999,
    }


# =============================================================================
# MAIN
# =============================================================================

def main():
    print("=" * 60)
    print("13_clean_valores_2024.py -- limpieza VALORES_2024.csv")
    print("=" * 60)

    if not os.path.isfile(VALORES_FILE):
        print(f"[ERROR] Archivo no encontrado:\n  {VALORES_FILE}")
        sys.exit(1)

    # --- Pasada 1: calcular percentiles ---
    p999_energia, p999_pot_disp = pasada_1_percentiles()

    # --- Pasada 2: transformar y escribir ---
    stats = pasada_2_transformar(p999_energia, p999_pot_disp)

    # --- Reporte final ---
    print(f"\n{'='*60}")
    print("REPORTE FINAL")
    print(f"{'='*60}")

    n     = stats['n_filas']
    n_out = stats['n_outliers']
    pct   = 100 * n_out / n if n > 0 else 0

    print(f"\n  Filas escritas        : {n:,}")
    print(f"  Columnas output       : {len(COLS_OUTPUT)}")

    # Fechas unicas
    n_fechas = len(stats['fechas_unicas'])
    if n_fechas == 366:
        print(f"  Fechas unicas         : {n_fechas}  OK (2024 bisiesto)")
    else:
        print(f"  Fechas unicas         : {n_fechas}  [AVISO] se esperaban 366")

    # Datetime NaT
    if stats['n_nat'] == 0:
        print(f"  Valores NaT           : 0  OK")
    else:
        print(f"  Valores NaT           : {stats['n_nat']:,}  [AVISO] revisar fechas")

    # GRUPOs con horas incompletas
    grupos_incompletos = {g: h for g, h in stats['grupos_horas'].items()
                          if len(h) < 24}
    if grupos_incompletos:
        print(f"  GRUPOs con < 24 h     : {len(grupos_incompletos)}  [AVISO]")
        for g, h in list(grupos_incompletos.items())[:5]:
            print(f"    {g}: {sorted(h)}")
    else:
        print(f"  GRUPOs con < 24 h     : 0  OK")

    # Outliers
    print(f"\n  Outliers marcados     : {n_out:,}  ({pct:.3f}%)")
    print(f"    ENERGIA  < 0        : {stats['cnt_energia_neg']:,}")
    print(f"    POT_DISP < 0        : {stats['cnt_potdisp_neg']:,}")
    print(f"    ENERGIA  > p99.9    : {stats['cnt_energia_p99']:,}")
    print(f"    POT_DISP > p99.9    : {stats['cnt_potdisp_p99']:,}")

    print(f"\n  Output: {OUTPUT_FILE}")
    print("=" * 60)


if __name__ == "__main__":
    main()
