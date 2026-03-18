"""
16_snapshot_dc_pico2024.py
Flujo DC linealizado sobre el snapshot de maximo pico de demanda 2024.
Snapshot: 2024-02-01 14:00 (27.439 MW de demanda, 28.689 MW de generacion).

Inputs:
    networks/network_500kv.nc
    data/network_500kv/generators_final.csv
    data/network_500kv/loads_2024.csv
    Official data/valores_2024_clean.csv  (archivo externo a GitHub)

Output:
    Reporte en consola. Sin archivo de salida.

Logica de generacion:
    Para cada unidad del modelo se busca su ENERGIA en el snapshot
    usando el mismo criterio de match que el script 14:

    Match exacto (bus_name_origen existe como GRUPO en CAMMESA):
        p_set = ENERGIA de ese GRUPO en el timestamp del pico.

    Sin match exacto (ej: Yacyreta — GRUPO es la central entera):
        Se toman todos los GRUPOs de esa Central por nemo4,
        se suma su ENERGIA, y se distribuye proporcional a pt_mw
        entre las unidades del modelo.

    Unidades sin datos en CAMMESA para ese timestamp: p_set = 0.

Logica de demanda:
    p_set por bus = valor de loads_2024.csv en el timestamp del pico.

Flujo DC:
    n.lpf() — flujo DC linealizado. Usa reactancias X de lineas y
    transformadores. No calcula perdidas (aproximacion DC estandar).

Reporte:
    - Balance generacion vs demanda del snapshot
    - Mix de generacion por tecnologia (termica agrupada)
    - 10 lineas mas cargadas (flujo / capacidad %)
    - Angulos nodales extremos (indicador de estres de la red)

Correr desde WSL:
    python /mnt/c/Work/pypsa-ar-base/scripts/network_500kv/16_snapshot_dc_pico2024.py
"""

import os
import sys
import pandas as pd
import numpy as np
import pypsa

# =============================================================================
# CONFIGURACION
# =============================================================================

NETWORK_FILE  = "/mnt/c/Work/pypsa-ar-base/networks/network_500kv.nc"
GEN_FILE      = "/mnt/c/Work/pypsa-ar-base/data/network_500kv/generators_final.csv"
LOADS_FILE    = "/mnt/c/Work/pypsa-ar-base/data/network_500kv/loads_2024.csv"
VALORES_FILE  = "/mnt/c/Work/pypsa-ar-sandbox/Official data/valores_2024_clean.csv"

# Timestamp del pico de demanda 2024 — formato DD/MM/YYYY HH:MM
# Mismo formato en loads_2024.csv y valores_2024_clean.csv
SNAPSHOT = "01/02/2024 14:00" 



# Carriers que se agrupan como TERMICA en el reporte
CARRIERS_TERMICA = {'steam', 'ocgt', 'ccgt', 'diesel'}


# =============================================================================
# PASO 1 — Extraer generacion del snapshot desde valores_2024_clean
# =============================================================================

def extraer_generacion_snapshot():
    """
    Lee valores_2024_clean.csv y extrae ENERGIA por GRUPO en el timestamp
    del pico. Excluye GRUPOs no argentinos.

    Retorna:
        energia_por_grupo  — dict {GRUPO: ENERGIA_MW}
        central_por_grupo  — dict {GRUPO: Central}
    """
    print("\n[1/5] Extrayendo generacion del snapshot ...")

    df = pd.read_csv(
        VALORES_FILE,
        usecols=['datetime', 'GRUPO', 'Central', 'TIPO', 'ENERGIA', 'flag_outlier'],
        low_memory=False,
    )

    df_pico = df[df['datetime'] == SNAPSHOT].copy()


    print(f"  GRUPOs en el snapshot   : {len(df_pico)}")
    print(f"  Generacion total CAMMESA: {df_pico['ENERGIA'].sum():,.1f} MW")

    outliers = df_pico['flag_outlier'].sum()
    if outliers > 0:
        print(f"  [AVISO] {outliers} GRUPOs con flag_outlier=True en este timestamp")

    energia_por_grupo = df_pico.set_index('GRUPO')['ENERGIA'].to_dict()
    central_por_grupo = df_pico.set_index('GRUPO')['Central'].to_dict()

    return energia_por_grupo, central_por_grupo, df_pico


# =============================================================================
# PASO 2 — Mapear generacion a unidades del modelo
# =============================================================================

def mapear_generacion(gen, energia_por_grupo, central_por_grupo):
    """
    Asigna p_set a cada unidad del modelo usando la misma logica que script 14:
        - Match exacto GRUPO = bus_name_origen -> p_set directo
        - Sin match -> distribuir ENERGIA de la Central por pt_mw

    Retorna DataFrame con columnas gen_key, bus_conexion500kv, p_set, carrier.
    """
    print("\n[2/5] Mapeando generacion a unidades del modelo ...")

    grupos_disponibles = set(energia_por_grupo.keys())

    # Construir mapa central -> GRUPOs
    central_a_grupos = {}
    for grupo, central in central_por_grupo.items():
        if central not in central_a_grupos:
            central_a_grupos[central] = []
        central_a_grupos[central].append(grupo)

    gen = gen.copy()
    gen['nemo4'] = gen['nemo'].fillna('').str[:4].str.strip()

    p_set_list     = []
    match_type_list = []

    for _, row in gen.iterrows():
        bus_origen = row['bus_name_origen']
        nemo4      = row['nemo4']
        pt_mw      = row['pt_mw'] if row['pt_mw'] < 9000 else 0.0

        # Match exacto GRUPO
        if bus_origen in grupos_disponibles:
            valor = energia_por_grupo[bus_origen]
            match_type_list.append('directo')

        # Sin match: buscar por Central (nemo4)
        elif nemo4 in central_a_grupos:
            grupos_central = central_a_grupos[nemo4]
            e_central = sum(energia_por_grupo.get(g, 0) for g in grupos_central)

            unidades_central = gen[gen['nemo4'] == nemo4]
            pt_total = unidades_central['pt_mw'].apply(
                lambda x: x if x < 9000 else 0
            ).sum()

            valor = e_central * (pt_mw / pt_total) if pt_total > 0 else 0.0
            match_type_list.append('distribuido')

        else:
            valor = 0.0
            match_type_list.append('sin_datos')

        p_set_list.append(max(valor, 0.0))

    gen['p_set']      = p_set_list
    gen['match_snap'] = match_type_list

    n_directo     = match_type_list.count('directo')
    n_distribuido = match_type_list.count('distribuido')
    n_sin_datos   = match_type_list.count('sin_datos')

    print(f"  Match directo     : {n_directo} unidades")
    print(f"  Match distribuido : {n_distribuido} unidades")
    print(f"  Sin datos CAMMESA : {n_sin_datos} unidades  (p_set=0)")
    print(f"  p_set total modelo: {gen['p_set'].sum():,.1f} MW")

    return gen


# =============================================================================
# PASO 3 — Cargar snapshot en el network y correr LPF
# =============================================================================

def correr_lpf(n, gen, loads_snap):
    """
    Agrega generadores y cargas al network con los valores del snapshot
    y corre el flujo DC linealizado.
    """
    print("\n[3/5] Cargando snapshot en el network y corriendo LPF ...")

    snapshot = pd.DatetimeIndex([pd.to_datetime(SNAPSHOT, dayfirst=True, format='%d/%m/%Y %H:%M')])
    n.set_snapshots(snapshot)

    # --- Agregar generadores ---
    # Eliminar generadores previos si existen
    n.generators.drop(n.generators.index, inplace=True)
    if not n.generators_t.p_set.empty:
        n.generators_t.p_set = pd.DataFrame(index=snapshot)

    for _, row in gen.iterrows():
        bus = row.get('bus_conexion500kv_name')
        if pd.isna(bus) or bus not in n.buses.index:
            continue
        if row['p_set'] <= 0:
            continue

        nombre = row['gen_key']
        n.add("Generator",
              nombre,
              bus=bus,
              p_nom=row['p_set'] * 1.1,   # p_nom ligeramente mayor que p_set
              p_set=row['p_set'],
              carrier=row['carrier'],
              marginal_cost=0.0,
              )

    # --- Agregar cargas ---
    n.loads.drop(n.loads.index, inplace=True)
    if not n.loads_t.p_set.empty:
        n.loads_t.p_set = pd.DataFrame(index=snapshot)

    for _, row in loads_snap.iterrows():
        bus = row.get('bus_name')
        if pd.isna(bus) or bus not in n.buses.index:
            continue
        if row['p_mw'] <= 0:
            continue

        n.add("Load",
              f"load_{bus}",
              bus=bus,
              p_set=row['p_mw'],
              )

    print(f"  Generadores cargados: {len(n.generators)}")
    print(f"  Cargas cargadas     : {len(n.loads)}")
    gen_total_display = n.generators['p_set'].sum()
    print(f"  Generacion total    : {gen_total_display:,.1f} MW")
    dem_total_display = n.loads["p_set"].sum()
    print(f"  Demanda total       : {dem_total_display:,.1f} MW")

    # --- Asignar slack bus ---
    # En la red 500 kV argentina toda la generacion entra por transformadores.
    # Se asigna el slack a ATUCHA 2_21kV (bus 2620, terminal de maquina nuclear)
    # que es el bus de referencia del caso PSS/E original.
    SLACK_BUS = "ATUCHA 2_21kV"
    if SLACK_BUS in n.buses.index:
        n.buses.loc[SLACK_BUS, 'control'] = 'Slack'
        print(f"  Slack bus           : {SLACK_BUS}")
    else:
        print(f"  [AVISO] Slack bus {SLACK_BUS} no encontrado — PyPSA asigna automaticamente")

    # --- Correr LPF ---
    n.lpf()
    print("  LPF: completado")

    return n


# =============================================================================
# PASO 4 — Reporte
# =============================================================================

def reportar(n, gen, vals_pico):
    print(f"\n{'='*60}")
    print(f"REPORTE SNAPSHOT DC — {SNAPSHOT}")
    print(f"{'='*60}")

    gen_despacho = n.generators['p_set'].sum()
    dem_total    = n.loads_t.p.sum(axis=1).values[0]
    gen_lpf      = n.generators_t.p.sum(axis=1).values[0]
    slack_mw     = gen_lpf - gen_despacho

    print(f"\n  BALANCE")
    print(f"    Generacion despachada (p_set) : {gen_despacho:>10,.1f} MW")
    print(f"    Inyeccion del slack           : {slack_mw:>10,.1f} MW")
    print(f"    Demanda total                 : {dem_total:>10,.1f} MW")

    # --- Top 3 generadores CAMMESA no representados (solo si slack > 0) ---
    if slack_mw > 0:
        grupos_directo  = set(gen['bus_name_origen'].str.strip())
        nemos4_modelo   = set(gen['nemo'].str[:4].str.strip().dropna())
        vals_pico_pos   = vals_pico[vals_pico['ENERGIA'] > 0].copy()
        vals_pico_pos['nemo4'] = vals_pico_pos['Central'].str[:4].str.strip()
        vals_pico_pos['en_modelo'] = (
            vals_pico_pos['GRUPO'].isin(grupos_directo) |
            vals_pico_pos['nemo4'].isin(nemos4_modelo)
        )
        fuera = (
            vals_pico_pos[~vals_pico_pos['en_modelo']]
            .sort_values('ENERGIA', ascending=False)
            .head(3)
        )
        if len(fuera) > 0:
            print(f"\n  TOP 3 FUENTES NO REPRESENTADAS EN EL MODELO")
            for _, row in fuera.iterrows():
                nota = " (Es una importacion de energia de un pais limitrofe, no modelada en esta instancia)" if row['TIPO'] == 'XM' else ""
                print(f"    {row['GRUPO']:<12} {row['Central']:<6} {row['ENERGIA']:>8,.1f} MW{nota}")

    # --- Mix de generacion por tecnologia ---
    print(f"\n  MIX DE GENERACION POR TECNOLOGIA")

    gen_desp = n.generators_t.p.iloc[0]
    gen_df   = n.generators[['carrier']].copy()
    gen_df['p_desp'] = gen_desp

    def agrupar_carrier(c):
        if c in CARRIERS_TERMICA:
            return 'termica'
        return c

    gen_df['tecnologia'] = gen_df['carrier'].apply(agrupar_carrier)
    mix = gen_df.groupby('tecnologia')['p_desp'].sum().sort_values(ascending=False)

    for tec, mw in mix.items():
        pct = 100 * mw / gen_despacho if gen_despacho > 0 else 0
        print(f"    {tec:<15}: {mw:>8,.1f} MW  ({pct:>5.1f}%)")

    # --- 10 lineas mas cargadas ---
    print(f"\n  10 LINEAS MAS CARGADAS")

    p0    = n.lines_t.p0.iloc[0].abs()
    s_nom = n.lines['s_nom'].replace(0, np.nan)
    carga = (p0 / s_nom * 100).dropna().sort_values(ascending=False)

    print(f"    {'Linea':<30} {'Flujo MW':>10} {'Capac MW':>10} {'Carga %':>8}")
    for linea, pct in carga.head(10).items():
        flujo  = p0[linea]
        capac  = n.lines.loc[linea, 's_nom']
        print(f"    {linea:<30} {flujo:>10,.1f} {capac:>10,.1f} {pct:>8.1f}%")

    # --- Angulos nodales extremos ---
    print(f"\n  ANGULOS NODALES EXTREMOS (indicador de estres de red)")

    angulos = n.buses_t.v_ang.iloc[0] * (180 / np.pi)
    angulos = angulos.sort_values()

    print(f"    {'Bus':<20} {'Angulo (deg)':>14}")
    for bus, ang in list(angulos.head(5).items()) + list(angulos.tail(5).items()):
        nombre = n.buses.loc[bus, 'v_nom'] if bus in n.buses.index else ''
        print(f"    {bus:<20} {ang:>14.2f}")

    ang_max = angulos.max()
    ang_min = angulos.min()
    print(f"\n    Rango de angulos: {ang_min:.2f} deg  a  {ang_max:.2f} deg")
    if abs(ang_max - ang_min) > 30:
        print(f"    [AVISO] Diferencia de angulos > 30 deg — posible estres severo en la red")


# =============================================================================
# MAIN
# =============================================================================

def main():
    print("=" * 60)
    print("16_snapshot_dc_pico2024.py -- flujo DC pico demanda 2024")
    print("=" * 60)

    for f in [NETWORK_FILE, GEN_FILE, LOADS_FILE, VALORES_FILE]:
        if not os.path.isfile(f):
            print(f"[ERROR] Archivo no encontrado:\n  {f}")
            sys.exit(1)

    # Cargar network
    print("\nCargando network_500kv.nc ...")
    n = pypsa.Network(NETWORK_FILE)
    print(f"  Buses: {len(n.buses)}  Lineas: {len(n.lines)}  Trafos: {len(n.transformers)}")

    # Cargar generadores del modelo
    gen = pd.read_csv(GEN_FILE)

    # Cargar demanda del snapshot
    loads = pd.read_csv(LOADS_FILE)
    loads_snap = loads[loads['datetime'] == SNAPSHOT][['bus_id', 'bus_name', 'p_mw']].copy()
    print(f"\nDemanda en snapshot: {loads_snap['p_mw'].sum():,.1f} MW  ({len(loads_snap)} buses)")

    # Pasos
    energia_por_grupo, central_por_grupo, vals_pico = extraer_generacion_snapshot()
    gen = mapear_generacion(gen, energia_por_grupo, central_por_grupo)
    n   = correr_lpf(n, gen, loads_snap)
    reportar(n, gen, vals_pico)

    print("\n" + "=" * 60)


if __name__ == "__main__":
    main()
