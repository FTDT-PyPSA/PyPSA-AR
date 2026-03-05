"""
05_validate_topology.py
Valida la topologia de la red 500 kV antes de cargarla en PyPSA.

Modo de operacion (se detecta automaticamente):

  MODO COMPLETO   : buses_500kv_final.csv existe y no tiene pendientes
                    + lines_500kv_final.csv existe
                    -> valida con coordenadas y geometria

  MODO TOPOLOGIA  : buses_500kv_final.csv no existe, o tiene pendientes,
                    o lines_500kv_final.csv no existe
                    -> valida solo conectividad, sin geometria

Inputs (segun modo):
  COMPLETO  : data/network_500kv/buses_500kv_final.csv
              data/network_500kv/lines_500kv_final.csv
  TOPOLOGIA : data/network_500kv/buses_500kv_raw.csv
              data/network_500kv/lines_500kv_raw.csv

Output:
  data/network_500kv/topology_report.csv  -> problemas encontrados (si hay)

Correr desde WSL:
    python /mnt/c/Work/pypsa-ar-base/scripts/network_500kv/05_validate_topology.py

Validaciones realizadas:
  1. Lineas huerfanas      : lineas con bus_i o bus_j ausente en el set de buses
  2. Buses sin lineas      : buses sin ninguna linea 500 kV conectada
                             -> nodo de compensador : tiene ramas series_compensator
                             -> nodo de transformador: aparece en TRANSFORMER DATA del raw
                             -> bus genuinamente aislado: ninguno de los anteriores
  3. Componentes conexas   : cuantos bloques desconectados tiene la red
                             (excluye nodos de compensador y transformador)
  4. Parametros electricos : lineas con r=0 y x=0 simultaneamente
  5. Ratings               : lineas sin ratea_mva definido (NaN)
"""

import os
import pandas as pd
import numpy as np
from collections import defaultdict, deque

# =============================================================================
# CONFIGURACION
# =============================================================================

DATA_DIR = "/mnt/c/Work/pypsa-ar-base/data/network_500kv"

BUSES_FINAL    = os.path.join(DATA_DIR, "buses_500kv_final.csv")
LINES_FINAL    = os.path.join(DATA_DIR, "lines_500kv_final.csv")
BUSES_RAW      = os.path.join(DATA_DIR, "buses_500kv_raw.csv")
LINES_RAW      = os.path.join(DATA_DIR, "lines_500kv_raw.csv")
PSSE_RAW_FILE  = "/mnt/c/Work/pypsa-ar-sandbox/Official data/PSSE/ver2526pid.raw"
OUTPUT_REPORT  = os.path.join(DATA_DIR, "topology_report.csv")


# =============================================================================
# FUNCIONES
# =============================================================================

def detect_mode():
    buses_final_ok = False
    if os.path.isfile(BUSES_FINAL):
        df = pd.read_csv(BUSES_FINAL)
        if "match_status" in df.columns:
            n_pending = (df["match_status"] == "pendiente").sum()
            if n_pending == 0:
                buses_final_ok = True
            else:
                print(f"  [!] buses_500kv_final.csv tiene {n_pending} pendientes -> MODO TOPOLOGIA")
        else:
            buses_final_ok = True

    if buses_final_ok and os.path.isfile(LINES_FINAL):
        return BUSES_FINAL, LINES_FINAL, "COMPLETO"
    else:
        if not os.path.isfile(BUSES_RAW):
            raise FileNotFoundError(f"No se encontro buses_500kv_raw.csv en {DATA_DIR}")
        if not os.path.isfile(LINES_RAW):
            raise FileNotFoundError(f"No se encontro lines_500kv_raw.csv en {DATA_DIR}")
        return BUSES_RAW, LINES_RAW, "TOPOLOGIA"


def get_transformer_bus_ids(raw_file):
    """
    Lee TRANSFORMER DATA del raw PSS/E y devuelve el set de bus_ids
    que aparecen en al menos un transformador.
    """
    if not os.path.isfile(raw_file):
        return set()
    trafo_buses = set()
    inside = False
    with open(raw_file, "r", encoding="ISO-8859-1") as f:
        for line in f:
            if "BEGIN TRANSFORMER DATA" in line:
                inside = True; continue
            if "END OF TRANSFORMER DATA" in line:
                break
            if not inside:
                continue
            s = line.strip()
            if not s or s.startswith("@") or s.startswith("/"):
                continue
            try:
                parts = s.split(",")
                i = int(parts[0].strip())
                j = int(parts[1].strip())
                k = int(parts[2].strip())
                trafo_buses.add(i)
                if j != 0: trafo_buses.add(j)
                if k != 0: trafo_buses.add(k)
            except:
                pass
    return trafo_buses


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
    print("05_validate_topology.py -- validacion red 500 kV")
    print("=" * 60)

    print("\nDetectando modo de operacion...")
    buses_file, lines_file, mode = detect_mode()

    print(f"\n  MODO      : {mode}")
    print(f"  Buses     : {os.path.basename(buses_file)}")
    print(f"  Lineas    : {os.path.basename(lines_file)}")

    buses = pd.read_csv(buses_file)
    lines = pd.read_csv(lines_file)

    print(f"\n  Buses cargados : {len(buses)}")
    print(f"  Lineas cargadas: {len(lines)}")

    bus_ids  = set(buses["bus_id"].astype(int))
    problems = []

    # ==========================================================
    # VALIDACION 1 — Lineas huerfanas
    # ==========================================================
    print("\n[1] Lineas huerfanas (bus_i o bus_j ausente en buses)...")
    orphan_lines = lines[
        ~lines["bus_i"].isin(bus_ids) | ~lines["bus_j"].isin(bus_ids)
    ]
    if orphan_lines.empty:
        print("    ✔ Ninguna")
    else:
        print(f"    ✘ {len(orphan_lines)} lineas huerfanas")
        for _, r in orphan_lines.iterrows():
            missing = []
            if r["bus_i"] not in bus_ids: missing.append(f"bus_i={r['bus_i']}")
            if r["bus_j"] not in bus_ids: missing.append(f"bus_j={r['bus_j']}")
            problems.append({
                "tipo":    "linea_huerfana",
                "elemento": r.get("line_key", f"line_{r['line_id']}"),
                "detalle": f"buses ausentes: {', '.join(missing)}",
            })

    valid_lines = lines[
        lines["bus_i"].isin(bus_ids) & lines["bus_j"].isin(bus_ids)
    ]

    # ==========================================================
    # VALIDACION 2 — Buses sin lineas 500 kV
    # ==========================================================
    print("\n[2] Buses sin lineas 500 kV conectadas...")

    # Buses que aparecen en lineas tipo 'line' (excluye compensadores)
    lines_only = valid_lines[valid_lines.get("element_type", pd.Series(["line"]*len(valid_lines))) == "line"]         if "element_type" in valid_lines.columns else valid_lines
    buses_en_lineas = set(lines_only["bus_i"]).union(set(lines_only["bus_j"]))

    # Buses que aparecen en ramas series_compensator
    if "element_type" in valid_lines.columns:
        comp_lines = valid_lines[valid_lines["element_type"] == "series_compensator"]
        buses_en_compensadores = set(comp_lines["bus_i"]).union(set(comp_lines["bus_j"]))
    else:
        buses_en_compensadores = set()

    isolated = bus_ids - buses_en_lineas
    n_compensador  = 0
    n_trafo        = 0
    n_aislados     = 0
    excluded_buses = set()   # compensadores + trafos, excluidos del analisis de componentes

    if not isolated:
        print("    ✔ Ninguno")
    else:
        trafo_buses    = get_transformer_bus_ids(PSSE_RAW_FILE)
        raw_disponible = bool(trafo_buses)

        for bus_id in isolated:
            bus_name = buses[buses["bus_id"] == bus_id]["bus_name"].values[0]

            if bus_id in buses_en_compensadores:
                # Conectado solo via compensadores — esperado
                print(f"      ℹ {bus_name} — barra central (sin lineas 500 kV propias)")
                n_compensador += 1
                excluded_buses.add(bus_id)

            elif raw_disponible and bus_id in trafo_buses:
                # Aparece en transformadores del raw — esperado
                print(f"      ℹ {bus_name} — nodo de transformador (sin lineas 500 kV propias)")
                n_trafo += 1
                excluded_buses.add(bus_id)

            else:
                # Genuinamente aislado
                print(f"      ✘ {bus_name} — bus genuinamente aislado")
                n_aislados += 1
                problems.append({
                    "tipo":     "bus_aislado",
                    "elemento": bus_name,
                    "detalle":  "sin lineas, compensadores ni transformadores",
                })

        if n_compensador:
            print(f"    ℹ {n_compensador} barras centrales (esperado, no es error)")
        if n_trafo:
            print(f"    ℹ {n_trafo} nodos de transformador (esperado, no es error)")
        if n_aislados:
            print(f"    ✘ {n_aislados} buses genuinamente aislados")
        else:
            print(f"    ✔ Ningún bus genuinamente aislado")

    # ==========================================================
    # VALIDACION 3 — Componentes conexas
    # (excluye nodos de compensador y transformador)
    # ==========================================================
    print("\n[3] Componentes conexas...")
    bus_ids_for_components = bus_ids - excluded_buses
    edges      = list(zip(valid_lines["bus_i"], valid_lines["bus_j"]))
    components = find_connected_components(bus_ids_for_components, edges)
    main_comp  = max(components, key=len)

    print(f"    Componentes encontradas : {len(components)}")
    print(f"    Componente principal    : {len(main_comp)} buses")

    if len(components) > 1:
        print(f"    ✘ Red fragmentada en {len(components)} bloques")
        for i, comp in enumerate(sorted(components, key=len, reverse=True)):
            if i == 0:
                continue
            comp_names = buses[buses["bus_id"].isin(comp)]["bus_name"].tolist()
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
    # VALIDACION 4 — Parametros electricos
    # ==========================================================
    print("\n[4] Parametros electricos (r=0 y x=0 simultaneamente)...")
    zero_impedance = valid_lines[
        (valid_lines["r_pu"] == 0) & (valid_lines["x_pu"] == 0)
    ]
    if "element_type" in valid_lines.columns:
        zero_impedance = zero_impedance[
            zero_impedance["element_type"] != "series_compensator"
        ]
    if zero_impedance.empty:
        print("    ✔ Ninguna")
    else:
        print(f"    ⚠ {len(zero_impedance)} lineas con r=0 y x=0")
        for _, r in zero_impedance.iterrows():
            problems.append({
                "tipo":     "impedancia_cero",
                "elemento": r.get("line_key", f"line_{r['line_id']}"),
                "detalle":  "r_pu=0 y x_pu=0",
            })

    # ==========================================================
    # VALIDACION 5 — Ratings
    # ==========================================================
    print("\n[5] Ratings no definidos (ratea_mva = NaN)...")
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
    # REPORTE FINAL.
    # ==========================================================
    print("\n" + "=" * 60)
    print("RESUMEN")
    print("=" * 60)
    print(f"  Modo                  : {mode}")
    print(f"  Buses                 : {len(buses)}")
    print(f"  Lineas validas        : {len(valid_lines)}")
    print(f"  Lineas huerfanas      : {len(orphan_lines)}")
    print(f"  Sin lineas 500 kV     : {len(isolated)}  (barras centrales: {n_compensador}, trafos: {n_trafo}, aislados reales: {n_aislados})")
    print(f"  Componentes conexas   : {len(components)}")
    print(f"  Impedancia cero       : {len(zero_impedance)}")
    print(f"  Sin rating            : {len(no_rating)}")
    print(f"  Problemas totales     : {len(problems)}")

    # ==========================================================
    # VALIDACION 6 — Ramas fuera de servicio
    # ==========================================================
    print("\n[6] Ramas fuera de servicio (in_service=False)...")
    if "in_service" in valid_lines.columns:
        out_of_service = valid_lines[valid_lines["in_service"] == False]
        if out_of_service.empty:
            print("    ✔ Todas las ramas en servicio")
        else:
            print(f"    ⚠ {len(out_of_service)} ramas fuera de servicio en este caso base (no es error)")
            for _, r in out_of_service.iterrows():
                key = r.get("line_key", f"line_{r['line_id']}")
                print(f"      {key}")
    else:
        print("    ℹ columna in_service no disponible en este modo")

    if problems:
        df_problems = pd.DataFrame(problems)
        df_problems.to_csv(OUTPUT_REPORT, index=False)
        print(f"\n  Reporte guardado en: {OUTPUT_REPORT}")
    else:
        print("\n  ✔ Red sin problemas — lista para build_pypsa_network")

    print(f"\nProximo: 06_build_pypsa_network.py")


if __name__ == "__main__":
    main()
