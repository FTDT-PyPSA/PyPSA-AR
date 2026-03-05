"""
07_validate_topology.py
Valida la topologia de la red 500 kV antes de cargarla en PyPSA.

Inputs:
    data/network_500kv/buses_final.csv        (script 05 — todos los buses)
    data/network_500kv/lines_500kv_final.csv  (script 06 — lineas con geometria)
    data/network_500kv/trafos_500kv_raw.csv   (script 03 — transformadores)

Output:
    data/network_500kv/topology_report.csv    -> problemas encontrados (si hay)

Correr desde WSL:
    python /mnt/c/Work/pypsa-ar-base/scripts/network_500kv/07_validate_topology.py

Validaciones realizadas:
    1. Lineas huerfanas      : lineas con bus_i o bus_j ausente en el set de buses
    2. Trafos huerfanos      : trafos con bus_i o bus_j ausente en el set de buses
    3. Buses sin conexion    : buses 500 kV sin ninguna linea 500 kV conectada
                               -> barra central de compensador serie : esperado
                               -> nodo solo con trafos               : esperado
                               -> bus genuinamente aislado           : error
    4. Componentes conexas   : cuantos bloques desconectados tiene la red
                               (usando solo buses 500 kV y lineas 500 kV)
    5. Parametros electricos : lineas con r=0 y x=0 simultaneamente
    6. Ratings               : lineas sin ratea_mva definido (NaN)
    7. Ramas fuera de servicio: informativo, no es error
"""

import os
import sys
import pandas as pd
import numpy as np
from collections import defaultdict, deque

# =============================================================================
# CONFIGURACION
# =============================================================================

DATA_DIR      = "/mnt/c/Work/pypsa-ar-base/data/network_500kv"

BUSES_FILE    = os.path.join(DATA_DIR, "buses_final.csv")
LINES_FILE    = os.path.join(DATA_DIR, "lines_500kv_final.csv")
TRAFOS_FILE   = os.path.join(DATA_DIR, "trafos_500kv_raw.csv")
OUTPUT_REPORT = os.path.join(DATA_DIR, "topology_report.csv")


# =============================================================================
# FUNCIONES
# =============================================================================

def find_connected_components(bus_ids, edges):
    adj = defaultdict(set)
    for i, j in edges:
        adj[i].add(j)
        adj[j].add(i)
    visited    = set()
    components = []
    for bus in bus_ids:
        if bus in visited:
            continue
        component = set()
        queue = deque([bus])
        while queue:
            node = queue.popleft()
            if node in visited:
                continue
            visited.add(node)
            component.add(node)
            for neighbor in adj[node]:
                if neighbor not in visited:
                    queue.append(neighbor)
        components.append(component)
    return components


# =============================================================================
# MAIN
# =============================================================================

def main():
    print("=" * 60)
    print("07_validate_topology.py -- validacion red 500 kV")
    print("=" * 60)

    for f in [BUSES_FILE, LINES_FILE, TRAFOS_FILE]:
        if not os.path.isfile(f):
            print(f"[ERROR] Archivo no encontrado:\n  {f}")
            sys.exit(1)

    buses  = pd.read_csv(BUSES_FILE)
    lines  = pd.read_csv(LINES_FILE)
    trafos = pd.read_csv(TRAFOS_FILE)

    # Separar buses 500kV de secundarios
    buses_500  = buses[buses['bus_type'] == '500kV']
    buses_sec  = buses[buses['bus_type'] == 'secundario']

    all_bus_ids = set(buses['bus_id'].astype(int))
    bus_ids_500 = set(buses_500['bus_id'].astype(int))
    bus_name_map = dict(zip(buses['bus_id'].astype(int), buses['bus_name']))

    print(f"\n  Buses 500 kV      : {len(buses_500)}")
    print(f"  Buses secundarios : {len(buses_sec)}")
    print(f"  Lineas            : {len(lines)}")
    print(f"  Trafos            : {len(trafos)}")

    problems = []

    # ==========================================================
    # VALIDACION 1 — Lineas huerfanas
    # ==========================================================
    print("\n[1] Lineas huerfanas (bus_i o bus_j ausente en buses)...")
    orphan_lines = lines[
        ~lines["bus_i"].isin(all_bus_ids) | ~lines["bus_j"].isin(all_bus_ids)
    ]
    if orphan_lines.empty:
        print("    ✔ Ninguna")
    else:
        print(f"    ✘ {len(orphan_lines)} lineas huerfanas")
        for _, r in orphan_lines.iterrows():
            missing = []
            if r["bus_i"] not in all_bus_ids: missing.append(f"bus_i={r['bus_i']}")
            if r["bus_j"] not in all_bus_ids: missing.append(f"bus_j={r['bus_j']}")
            print(f"      {r.get('line_key', r['line_id'])} — {', '.join(missing)}")
            problems.append({
                "tipo":     "linea_huerfana",
                "elemento": r.get("line_key", f"line_{r['line_id']}"),
                "detalle":  f"buses ausentes: {', '.join(missing)}",
            })

    valid_lines = lines[
        lines["bus_i"].isin(all_bus_ids) & lines["bus_j"].isin(all_bus_ids)
    ]

    # ==========================================================
    # VALIDACION 2 — Trafos huerfanos
    # ==========================================================
    print("\n[2] Trafos huerfanos (bus_i o bus_j ausente en buses)...")
    orphan_trafos = trafos[
        ~trafos["bus_i"].isin(all_bus_ids) | ~trafos["bus_j"].isin(all_bus_ids)
    ]
    if orphan_trafos.empty:
        print("    ✔ Ninguno")
    else:
        print(f"    ✘ {len(orphan_trafos)} trafos huerfanos")
        for _, r in orphan_trafos.iterrows():
            missing = []
            if r["bus_i"] not in all_bus_ids: missing.append(f"bus_i={r['bus_i']}")
            if r["bus_j"] not in all_bus_ids: missing.append(f"bus_j={r['bus_j']}")
            print(f"      {r['trafo_key']} — {', '.join(missing)}")
            problems.append({
                "tipo":     "trafo_huerfano",
                "elemento": r["trafo_key"],
                "detalle":  f"buses ausentes: {', '.join(missing)}",
            })

    # ==========================================================
    # VALIDACION 3 — Buses 500 kV sin lineas
    # ==========================================================
    print("\n[3] Buses 500 kV sin lineas 500 kV conectadas...")

    lines_only = valid_lines[
        valid_lines.get("element_type", pd.Series(["line"]*len(valid_lines))) == "line"
    ] if "element_type" in valid_lines.columns else valid_lines

    comp_lines = valid_lines[
        valid_lines["element_type"] == "series_compensator"
    ] if "element_type" in valid_lines.columns else pd.DataFrame()

    buses_en_lineas       = set(lines_only["bus_i"]).union(set(lines_only["bus_j"]))
    buses_en_compensadores = set(comp_lines["bus_i"]).union(set(comp_lines["bus_j"])) if not comp_lines.empty else set()
    buses_en_trafos       = set(trafos["bus_i"].astype(int)).union(set(trafos["bus_j"].astype(int)))

    isolated_500 = bus_ids_500 - buses_en_lineas
    n_compensador = 0
    n_trafo_only  = 0
    n_aislados    = 0
    excluded_buses = set()

    if not isolated_500:
        print("    ✔ Ninguno")
    else:
        for bus_id in sorted(isolated_500):
            bus_name = bus_name_map.get(bus_id, str(bus_id))
            if bus_id in buses_en_compensadores:
                print(f"      ℹ {bus_name} — barra central de compensador serie")
                n_compensador += 1
                excluded_buses.add(bus_id)
            elif bus_id in buses_en_trafos:
                print(f"      ℹ {bus_name} — nodo solo con transformadores")
                n_trafo_only += 1
                excluded_buses.add(bus_id)
            else:
                print(f"      ✘ {bus_name} — bus genuinamente aislado")
                n_aislados += 1
                problems.append({
                    "tipo":     "bus_aislado",
                    "elemento": bus_name,
                    "detalle":  "sin lineas, compensadores ni transformadores",
                })

        if n_compensador:
            print(f"    ℹ {n_compensador} barras centrales de compensador (esperado)")
        if n_trafo_only:
            print(f"    ℹ {n_trafo_only} nodos solo con transformadores (esperado)")
        if n_aislados:
            print(f"    ✘ {n_aislados} buses genuinamente aislados")
        else:
            print(f"    ✔ Ningun bus 500 kV genuinamente aislado")

    # ==========================================================
    # VALIDACION 4 — Componentes conexas (solo red 500 kV)
    # ==========================================================
    print("\n[4] Componentes conexas (red 500 kV)...")
    bus_ids_for_comp = bus_ids_500 - excluded_buses
    edges      = list(zip(valid_lines["bus_i"], valid_lines["bus_j"]))
    components = find_connected_components(bus_ids_for_comp, edges)
    main_comp  = max(components, key=len)

    print(f"    Componentes encontradas : {len(components)}")
    print(f"    Componente principal    : {len(main_comp)} buses")

    if len(components) > 1:
        print(f"    ✘ Red fragmentada en {len(components)} bloques")
        for i, comp in enumerate(sorted(components, key=len, reverse=True)):
            if i == 0:
                continue
            comp_names = [bus_name_map.get(b, str(b)) for b in comp]
            detalle = ", ".join(comp_names)
            print(f"      Isla {i}: {detalle}")
            problems.append({
                "tipo":     "isla_desconectada",
                "elemento": f"isla_{i}",
                "detalle":  detalle,
            })
    else:
        print("    ✔ Red completamente conectada")

    # ==========================================================
    # VALIDACION 5 — Parametros electricos
    # ==========================================================
    print("\n[5] Parametros electricos (r=0 y x=0 simultaneamente)...")
    zero_imp = valid_lines[(valid_lines["r_pu"] == 0) & (valid_lines["x_pu"] == 0)]
    if "element_type" in valid_lines.columns:
        zero_imp = zero_imp[zero_imp["element_type"] != "series_compensator"]
    if zero_imp.empty:
        print("    ✔ Ninguna")
    else:
        print(f"    ⚠ {len(zero_imp)} lineas con r=0 y x=0")
        for _, r in zero_imp.iterrows():
            problems.append({
                "tipo":     "impedancia_cero",
                "elemento": r.get("line_key", f"line_{r['line_id']}"),
                "detalle":  "r_pu=0 y x_pu=0",
            })

    # ==========================================================
    # VALIDACION 6 — Ratings
    # ==========================================================
    print("\n[6] Ratings no definidos (ratea_mva = NaN)...")
    no_rating = valid_lines[valid_lines["ratea_mva"].isna()]
    if no_rating.empty:
        print("    ✔ Todas las lineas tienen rating")
    else:
        print(f"    ⚠ {len(no_rating)} lineas sin rating")
        for _, r in no_rating.iterrows():
            key = r.get("line_key", f"line_{r['line_id']}")
            print(f"      {key}")
            problems.append({
                "tipo":     "sin_rating",
                "elemento": key,
                "detalle":  "ratea_mva = NaN",
            })

    # ==========================================================
    # VALIDACION 7 — Ramas fuera de servicio (informativo)
    # ==========================================================
    print("\n[7] Ramas fuera de servicio (in_service=False)...")
    if "in_service" in valid_lines.columns:
        out_svc = valid_lines[valid_lines["in_service"] == False]
        if out_svc.empty:
            print("    ✔ Todas las ramas en servicio")
        else:
            print(f"    ℹ {len(out_svc)} ramas fuera de servicio (informativo)")
            for _, r in out_svc.iterrows():
                print(f"      {r.get('line_key', r['line_id'])}")
    else:
        print("    ℹ columna in_service no disponible")

    # ==========================================================
    # REPORTE FINAL
    # ==========================================================
    print("\n" + "=" * 60)
    print("RESUMEN")
    print("=" * 60)
    print(f"  Buses 500 kV          : {len(buses_500)}")
    print(f"  Buses secundarios     : {len(buses_sec)}")
    print(f"  Lineas validas        : {len(valid_lines)}")
    print(f"  Trafos                : {len(trafos)}")
    print(f"  Lineas huerfanas      : {len(orphan_lines)}")
    print(f"  Trafos huerfanos      : {len(orphan_trafos)}")
    print(f"  Buses 500 sin lineas  : {len(isolated_500)}  (compensadores: {n_compensador}, solo trafos: {n_trafo_only}, aislados: {n_aislados})")
    print(f"  Componentes conexas   : {len(components)}")
    print(f"  Impedancia cero       : {len(zero_imp)}")
    print(f"  Sin rating            : {len(no_rating)}")
    print(f"  Problemas totales     : {len(problems)}")

    if problems:
        df_prob = pd.DataFrame(problems)
        df_prob.to_csv(OUTPUT_REPORT, index=False)
        print(f"\n  Reporte guardado en: {OUTPUT_REPORT}")
    else:
        print("\n  ✔ Red sin problemas — lista para 08_build_pypsa_network.py")

    print(f"\nProximo: 08_build_pypsa_network.py")


if __name__ == "__main__":
    main()
