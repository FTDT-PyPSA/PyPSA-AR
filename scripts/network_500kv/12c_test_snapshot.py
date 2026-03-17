"""
12c_test_snapshot.py
Carga generadores y cargas del snapshot PSS/E al network PyPSA y corre
un flujo DC lineal (lpf) para validar topologia y flujos.

El flujo DC siempre converge (ecuaciones lineales) y es el paso correcto
en esta etapa del pipeline. El flujo AC queda para el paso 20, despues
de la optimizacion con datos reales 2024.

Inputs:
    networks/network_500kv.nc                      (script 08)
    data/network_500kv/generators_final.csv        (script 12)
    data/network_500kv/loads_mapped.csv            (script 10)

Slack bus:
    ATUCHA 2_21kV — bus 2620, central nuclear, 21 kV.
    En la red argentina 500 kV no hay generacion directamente conectada
    en 500 kV — toda la generacion entra por transformadores. Por eso el
    slack es un bus secundario de un generador (terminal de maquina).

Validaciones reportadas:
    - Balance generacion/carga (el slack absorbe la diferencia)
    - Angulos nodales resultantes del DC (referencia: slack en 0 rad)
    - Carga de lineas como % de s_nom (solo lineas con rating definido)
    - Top 10 lineas mas cargadas
    - Flujo neto por bus (top generadores y consumidores)

Correr desde WSL:
    python /mnt/c/Work/pypsa-ar-base/scripts/network_500kv/12c_test_snapshot.py
"""

import os
import sys
import pandas as pd
import numpy as np
import pypsa

# =============================================================================
# CONFIGURACION
# =============================================================================

DATA_DIR   = "/mnt/c/Work/pypsa-ar-base/data/network_500kv"
NET_FILE   = "/mnt/c/Work/pypsa-ar-base/networks/network_500kv.nc"
GEN_FILE   = os.path.join(DATA_DIR, "generators_final.csv")
LOADS_FILE = os.path.join(DATA_DIR, "loads_mapped.csv")

SLACK_BUS  = "ATUCHA 2_21kV"


# =============================================================================
# MAIN
# =============================================================================

def main():
    print("=" * 60)
    print("12c_test_snapshot.py -- validacion DC snapshot PSS/E")
    print("=" * 60)

    for f in [NET_FILE, GEN_FILE, LOADS_FILE]:
        if not os.path.isfile(f):
            print("[ERROR] Archivo no encontrado:")
            print("  " + f)
            sys.exit(1)

    n = pypsa.Network(NET_FILE)
    print("Network cargado:")
    print("  Buses          : " + str(len(n.buses)))
    print("  Lineas         : " + str(len(n.lines)))
    print("  Transformadores: " + str(len(n.transformers)))

    gen   = pd.read_csv(GEN_FILE)
    loads = pd.read_csv(LOADS_FILE)

    if SLACK_BUS not in n.buses.index:
        print("[ERROR] Slack bus no encontrado: " + SLACK_BUS)
        sys.exit(1)

    # ==========================================================
    # ELIMINAR SUBREDES AISLADAS
    # ==========================================================
    print("\n[0] Detectando y eliminando subredes aisladas...")

    n.determine_network_topology()
    subred_counts = n.buses.groupby('sub_network').size().sort_values(ascending=False)
    print("  Subredes encontradas:")
    for sn, cnt in subred_counts.items():
        slack = n.sub_networks.loc[sn, 'slack_bus'] if sn in n.sub_networks.index else '?'
        print("    SubNetwork " + str(sn) + ": " + str(cnt) + " buses  (slack=" + str(slack) + ")")

    sn_principal = n.buses.loc[SLACK_BUS, 'sub_network']
    buses_aislados = n.buses[n.buses['sub_network'] != sn_principal].index.tolist()

    if buses_aislados:
        print("  Eliminando " + str(len(buses_aislados)) + " buses aislados: " + str(buses_aislados))
        for bus in buses_aislados:
            n.remove("Bus", bus)
        lines_drop = n.lines[
            (~n.lines['bus0'].isin(n.buses.index)) |
            (~n.lines['bus1'].isin(n.buses.index))
        ].index.tolist()
        trafos_drop = n.transformers[
            (~n.transformers['bus0'].isin(n.buses.index)) |
            (~n.transformers['bus1'].isin(n.buses.index))
        ].index.tolist()
        for l in lines_drop:
            n.remove("Line", l)
        for t in trafos_drop:
            n.remove("Transformer", t)
        print("  Lineas removidas      : " + str(len(lines_drop)))
        print("  Trafos removidos      : " + str(len(trafos_drop)))
    else:
        print("  Sin subredes aisladas")

    # ==========================================================
    # AGREGAR GENERADORES
    # ==========================================================
    print("\n[1] Agregando generadores...")

    n_added = 0
    n_skip  = 0
    activos = gen[(gen['stat'] == 1) & (gen['pt_mw'] < 9000)].copy()

    for _, row in activos.iterrows():
        bus_name = str(row['bus_conexion500kv_name'])
        if bus_name not in n.buses.index:
            n_skip += 1
            continue
        n.add(
            "Generator",
            str(row['gen_key']),
            bus     = bus_name,
            p_nom   = float(row['pt_mw']),
            p_set   = float(row['pg_mw']),
            carrier = str(row['carrier']),
            control = 'Slack' if bus_name == SLACK_BUS else 'PQ',
        )
        n_added += 1

    mw_gen = activos[activos['bus_conexion500kv_name'].isin(n.buses.index)]['pg_mw'].sum()
    print("  Generadores agregados : " + str(n_added))
    if n_skip:
        print("  Omitidos (bus ausente): " + str(n_skip))
    print("  Despacho total        : " + str(round(mw_gen, 1)) + " MW")

    slack_gens = n.generators[n.generators['bus'] == SLACK_BUS]
    if slack_gens.empty:
        print("[ERROR] No hay generador en el slack bus " + SLACK_BUS)
        sys.exit(1)
    print("  Generadores en slack  : " + str(len(slack_gens)) + " (" + SLACK_BUS + ")")

    # ==========================================================
    # AGREGAR CARGAS
    # ==========================================================
    print("\n[2] Agregando cargas...")

    n_loads_added = 0
    n_loads_skip  = 0
    activas = loads[(loads['stat'] == 1) & (loads['pl_mw'] > 0)].copy()

    for _, row in activas.iterrows():
        bus_name = str(row['bus_destino_name'])
        if bus_name not in n.buses.index:
            n_loads_skip += 1
            continue
        n.add(
            "Load",
            str(row['load_key']),
            bus   = bus_name,
            p_set = float(row['pl_mw']),
        )
        n_loads_added += 1

    mw_load = activas[activas['bus_destino_name'].isin(n.buses.index)]['pl_mw'].sum()
    print("  Cargas agregadas      : " + str(n_loads_added))
    if n_loads_skip:
        print("  Omitidas (bus ausente): " + str(n_loads_skip))
    print("  Demanda total         : " + str(round(mw_load, 1)) + " MW")
    print("  Balance (gen - carga) : " + str(round(mw_gen - mw_load, 1)) + " MW  (slack absorbe diferencia)")

    # ==========================================================
    # FLUJO DC LINEAL
    # ==========================================================
    print("\n[3] Corriendo flujo DC lineal (lpf)...")

    try:
        n.lpf()
    except Exception as e:
        print("[ERROR] Flujo DC fallo:")
        print("  " + str(e))
        sys.exit(1)

    print("✔ Flujo DC completado")

    # ==========================================================
    # RESULTADOS
    # ==========================================================
    print("\n" + "=" * 60)
    print("RESULTADOS")
    print("=" * 60)

    # Angulos nodales — en PyPSA 0.30 el lpf guarda angulos en v_ang (radianes)
    if 'v_ang' in n.buses_t.keys():
        va = n.buses_t.v_ang.iloc[0] * 180 / np.pi
    else:
        print("  ⚠ Angulos nodales no disponibles en buses_t — omitido")
        va = pd.Series(dtype=float)
    if not va.empty:
        print("\n  Angulos nodales (grados, referencia slack=0):")
        print("    Min : " + str(round(va.min(), 3)) + " deg  bus: " + str(va.idxmin()))
        print("    Max : " + str(round(va.max(), 3)) + " deg  bus: " + str(va.idxmax()))
        buses_angulo_critico = va[va.abs() > 30]
        if not buses_angulo_critico.empty:
            print("    ⚠ Buses con angulo > 30 deg (posible isla o desconexion):")
            for bus, ang in buses_angulo_critico.sort_values().items():
                print("      " + str(bus).ljust(30) + " " + str(round(ang, 2)) + " deg")
        else:
            print("    Todos los angulos dentro de ±30 deg — topologia sana")

    # Carga de lineas
    if len(n.lines_t.p0) > 0:
        p0 = n.lines_t.p0.iloc[0].abs()
        s_nom = n.lines['s_nom'].replace(0, np.nan)
        loading = (p0 / s_nom * 100).dropna().sort_values(ascending=False)
        sobrecargadas = loading[loading > 100]

        print("\n  Carga de lineas (DC):")
        print("    Con rating definido : " + str(len(loading)))
        print("    Sobrecargadas >100% : " + str(len(sobrecargadas)))
        print("    Carga maxima        : " + str(round(loading.iloc[0], 1)) + "%  (" + str(loading.index[0]) + ")")
        print("    Carga promedio      : " + str(round(loading.mean(), 1)) + "%")

        if not sobrecargadas.empty:
            print("\n  Top 10 lineas mas cargadas:")
            for line, pct in sobrecargadas.head(10).items():
                print("    " + str(line).ljust(35) + " " + str(round(pct, 1)) + "%")

    # Flujo neto por bus
    print("\n  Flujo neto por bus (top 10 generadores netos):")
    p_gen  = n.generators_t.p.iloc[0].groupby(n.generators.bus).sum()
    p_load = n.loads_t.p.iloc[0].groupby(n.loads.bus).sum()
    balance = p_gen.subtract(p_load, fill_value=0).sort_values(ascending=False)
    for bus, mw in balance.head(10).items():
        print("    " + str(bus).ljust(30) + " " + str(round(mw, 1)) + " MW")

    print("\n  Flujo neto por bus (top 10 consumidores netos):")
    for bus, mw in balance.tail(10).sort_values().items():
        print("    " + str(bus).ljust(30) + " " + str(round(mw, 1)) + " MW")

    print("\nProximo: paso 12 — reemplazar generacion PSS/E por inventario real 2024")


if __name__ == "__main__":
    main()
