"""
09_map_generators.py
Mapea todos los generadores del PSS/E a nodos del modelo (buses_final.csv).

Para generadores que conectan directamente a un nodo del modelo -> match_type='directo'
Para el resto -> BFS sobre el grafo completo del PSS/E hasta encontrar
                el primer nodo del modelo -> match_type='bfs'
Si BFS no encuentra ningun nodo del modelo -> match_type='sin_conexion'

Fuente : Official data/PSSE/ver2526pid.raw
Depende: data/network_500kv/buses_final.csv

Outputs:
    data/network_500kv/generators_mapped.csv
        Un generador por fila. Para todos los match_type.

    data/network_500kv/generators_manual_assignment.csv
        Una central por fila. Solo centrales sin_conexion relevantes
        (excluye redes industriales aisladas y equivalentes PSS/E).
        Columnas bus_destino_manual y nombre_geosadi vacias para
        completar manualmente antes de correr el script 11.

Correr desde WSL:
    python /mnt/c/Work/pypsa-ar-base/scripts/network_500kv/09_map_generators.py

============================================================
DECISIONES DE MODELADO
============================================================

CONSTRUCCION DEL GRAFO:
    Nodos  : todos los buses del raw (BUS DATA completo)
    Aristas: todas las ramas de BRANCH DATA
           + todos los transformadores de TRANSFORMER DATA
    Estado : TODAS las ramas se tratan como activas (in_service=True)
             independientemente del campo ST/STAT del raw.
             Razon: en los scripts 02 y 03 se uso FORCE_ALL_IN_SERVICE=True
             al construir el PyPSA Network. El grafo debe ser consistente
             con la red que efectivamente cargamos en PyPSA.

ALGORITMO BFS:
    Para cada generador cuyo bus_id NO esta en buses_final.csv se ejecuta
    un BFS (Breadth-First Search) desde ese bus_id explorando nivel por
    nivel (1 salto, 2 saltos, ...) hasta encontrar el primer nodo que
    este en buses_final.csv.
    BFS garantiza que se encuentra el camino de minimo numero de saltos.

DESEMPATE EN BFS:
    Si en el mismo nivel de exploracion el BFS encuentra multiples nodos
    de buses_final.csv simultaneamente (igual numero de saltos, distintos
    destinos posibles), se elige el nodo con mayor v_nom (baskv_kv).
    Razon: los buses de mayor tension tienen menor impedancia acumulada
    y representan el punto de conexion electrica mas natural.

FILTRO DE INTERNACIONALES:
    Se excluyen generadores cuyo bus pertenece a areas CAMMESA
    correspondientes a sistemas electricos vecinos:
        18=Paraguay, 19=Chile (SING), 20=Brasil, 22=Bolivia, 99=Uruguay

COLUMNAS DEL OUTPUT generators_mapped.csv:
    gen_key          : bus_id_origen-gen_id  clave unica en PSS/E
    bus_id_origen    : bus_id PSS/E donde conecta fisicamente el generador
    bus_name_origen  : nombre del bus origen en PSS/E
    pg_mw            : despacho activo en snapshot (MW) -- solo referencia
    pt_mw            : potencia maxima PSS/E (MW) -- solo referencia
    stat             : estado en snapshot (1=en servicio, 0=fuera de servicio)
    match_type       : 'directo' / 'bfs' / 'sin_conexion'
    bus_destino      : bus_id del nodo de buses_final.csv asignado
    bus_destino_name : nombre del nodo destino
    n_saltos         : saltos BFS hasta destino (0 si directo, -1 si sin_conexion)
    camino           : secuencia de nombres de buses desde origen hasta destino
                       formato: "BUS_A -> BUS_B -> BUS_DESTINO"
                       vacio si directo (origen == destino)

COLUMNAS DEL OUTPUT generators_manual_assignment.csv:
    central_prefix   : primeros 6 caracteres del bus_name_origen (identifica central)
    n_gen            : cantidad de generadores de esa central
    pg_total_mw      : PG total en snapshot (solo STAT=1)
    pt_total_mw      : PT total (excluye PT=9999)
    gen_keys         : lista de gen_key separados por | (trazabilidad a generators_mapped)
    bus_ids          : lista de bus_id_origen separados por |
    bus_destino_manual : completar manualmente: nombre exacto del bus en buses_final.csv
    nombre_geosadi   : completar manualmente: nombre en centrales_electricas.csv
"""

import os
import sys
import pandas as pd
from collections import deque, defaultdict

# =============================================================================
# CONFIGURACION
# =============================================================================

RAW_FILE      = "/mnt/c/Work/pypsa-ar-sandbox/Official data/PSSE/ver2526pid.raw"
BUSES_FILE    = "/mnt/c/Work/pypsa-ar-base/data/network_500kv/buses_final.csv"
OUTPUT_DIR    = "/mnt/c/Work/pypsa-ar-base/data/network_500kv"
OUTPUT_CSV    = os.path.join(OUTPUT_DIR, "generators_mapped.csv")
OUTPUT_MANUAL = os.path.join(OUTPUT_DIR, "generators_manual_assignment.csv")

# Areas CAMMESA de sistemas vecinos -- generadores de estos buses se excluyen
INTERNATIONAL_AREAS = {18, 19, 20, 22, 99}

# Buses a excluir del output de asignacion manual:
# redes industriales aisladas (ALUAR, AEG) y equivalentes ficticios PSS/E
EXCLUIR_BUS_NOMBRES = {
    'AL-FIAT1', 'AL-FIAT2', 'AL-FIAT3', 'AL-FIAT4',
    'ALUATG05', 'ALUATG06', 'ALUATG07', 'ALUATG08', 'ALUATV01',
    'AEG', 'LPER2132', 'PT1-132R', 'PTRUN35R',
}


# =============================================================================
# PARSEO DEL RAW
# =============================================================================

def get_section(lines, begin_marker, end_marker):
    """Extrae lineas de una seccion del raw entre markers."""
    inside = False
    result = []
    for line in lines:
        if begin_marker in line:
            inside = True
            continue
        if inside and end_marker in line:
            break
        if inside:
            l = line.strip()
            if l and not l.startswith('@') and not l.startswith('0 /'):
                result.append(l)
    return result


def parse_all_buses(lines):
    """
    Parsea BUS DATA completo.
    Retorna:
        id_to_name  : dict bus_id -> bus_name
        id_to_baskv : dict bus_id -> baskv_kv
        id_to_area  : dict bus_id -> area
    """
    id_to_name  = {}
    id_to_baskv = {}
    id_to_area  = {}
    for line in get_section(lines, 'BEGIN BUS DATA', 'END OF BUS DATA'):
        try:
            bus_id = int(line[:line.index(',')].strip())
            q1 = line.index("'"); q2 = line.index("'", q1+1)
            bus_name = line[q1+1:q2].strip()
            parts = [p.strip() for p in line[q2+1:].split(',')]
            if parts[0] == '': parts = parts[1:]
            baskv = float(parts[0])
            area  = int(parts[2])
            id_to_name[bus_id]  = bus_name
            id_to_baskv[bus_id] = baskv
            id_to_area[bus_id]  = area
        except:
            continue
    return id_to_name, id_to_baskv, id_to_area


def parse_graph(lines):
    """
    Construye grafo de adyacencia con BRANCH DATA + TRANSFORMER DATA.
    Todas las ramas se tratan como activas (FORCE_ALL_IN_SERVICE).
    Retorna dict: bus_id -> set de bus_ids vecinos
    """
    adj = defaultdict(set)

    for line in get_section(lines, 'BEGIN BRANCH DATA', 'END OF BRANCH DATA'):
        try:
            q1 = line.index("'")
            parts = [p.strip() for p in line[:q1].split(',') if p.strip()]
            i = int(parts[0]); j = int(parts[1])
            adj[i].add(j); adj[j].add(i)
        except:
            continue

    trafo_lines = get_section(lines, 'BEGIN TRANSFORMER DATA', 'END OF TRANSFORMER DATA')
    i = 0
    while i < len(trafo_lines):
        line = trafo_lines[i]
        try:
            q1 = line.index("'")
            parts = [p.strip() for p in line[:q1].split(',') if p.strip()]
            bus_i = int(parts[0])
            bus_j = int(parts[1])
            bus_k = int(parts[2])
            if bus_k == 0:
                adj[bus_i].add(bus_j); adj[bus_j].add(bus_i)
                i += 4
            else:
                adj[bus_i].add(bus_j); adj[bus_j].add(bus_i)
                adj[bus_i].add(bus_k); adj[bus_k].add(bus_i)
                adj[bus_j].add(bus_k); adj[bus_k].add(bus_j)
                i += 5
        except:
            i += 1

    return adj


def parse_generators(lines, all_bus_ids, id_to_area):
    """
    Parsea GENERATOR DATA.
    Excluye generadores de areas internacionales (INTERNATIONAL_AREAS).
    Retorna lista de dicts.
    """
    gens   = []
    n_intl = 0
    for line in get_section(lines, 'BEGIN GENERATOR DATA', 'END OF GENERATOR DATA'):
        try:
            bus_id = int(line[:line.index(',')].strip())
            if bus_id not in all_bus_ids:
                continue
            area = id_to_area.get(bus_id, 0)
            if area in INTERNATIONAL_AREAS:
                n_intl += 1
                continue
            q1 = line.index("'"); q2 = line.index("'", q1+1)
            gen_id = line[q1+1:q2].strip()
            rest = [x.strip() for x in line[q2+1:].split(',')]
            if rest[0] == '': rest = rest[1:]
            pg   = float(rest[0])
            stat = int(rest[12])
            pt   = float(rest[14])
            gens.append({
                'bus_id_origen': bus_id,
                'gen_id'       : gen_id,
                'gen_key'      : f"{bus_id}-{gen_id}",
                'pg_mw'        : pg,
                'pt_mw'        : pt,
                'stat'         : stat,
            })
        except:
            continue
    print(f"  Generadores internacionales excluidos: {n_intl}")
    return gens


# =============================================================================
# BFS
# =============================================================================

def bfs_to_model(start_bus, adj, model_bus_ids, id_to_name, id_to_baskv):
    """
    BFS desde start_bus hasta el primer nodo en model_bus_ids.
    Retorna (bus_destino, n_saltos, camino_nombres) o (None, None, None).

    Desempate: si hay multiples destinos al mismo nivel BFS,
    se elige el de mayor baskv_kv.
    """
    if start_bus in model_bus_ids:
        return start_bus, 0, []

    visited = {start_bus}
    queue   = deque([(start_bus, [start_bus])])

    while queue:
        level_size = len(queue)
        level_hits = []

        for _ in range(level_size):
            node, path = queue.popleft()
            for neighbor in adj.get(node, set()):
                if neighbor in visited:
                    continue
                visited.add(neighbor)
                new_path = path + [neighbor]
                if neighbor in model_bus_ids:
                    level_hits.append((neighbor, new_path))
                else:
                    queue.append((neighbor, new_path))

        if level_hits:
            best = max(level_hits, key=lambda x: id_to_baskv.get(x[0], 0))
            bus_dest, path = best
            n_saltos = len(path) - 1
            camino_names = [id_to_name.get(b, str(b)) for b in path]
            return bus_dest, n_saltos, camino_names

    return None, None, None


# =============================================================================
# MAIN
# =============================================================================

def main():
    print("=" * 60)
    print("09_map_generators.py -- mapeo generadores PSS/E -> modelo")
    print("=" * 60)

    for f in [RAW_FILE, BUSES_FILE]:
        if not os.path.isfile(f):
            print(f"[ERROR] Archivo no encontrado:\n  {f}")
            sys.exit(1)

    # --- Cargar buses del modelo ---
    buses_df          = pd.read_csv(BUSES_FILE)
    model_bus_ids     = set(buses_df['bus_id'].astype(int))
    model_id_to_name  = dict(zip(buses_df['bus_id'].astype(int), buses_df['bus_name']))
    model_id_to_baskv = dict(zip(buses_df['bus_id'].astype(int), buses_df['baskv_kv']))
    print(f"Nodos del modelo cargados: {len(model_bus_ids)}")

    # --- Leer raw ---
    print(f"\nLeyendo {RAW_FILE}...")
    with open(RAW_FILE, 'r', encoding='ISO-8859-1') as f:
        raw_lines = f.readlines()
    print(f"  {len(raw_lines)} lineas")

    # --- Parsear buses completos ---
    print(f"\nParsando BUS DATA...")
    id_to_name, id_to_baskv, id_to_area = parse_all_buses(raw_lines)
    all_bus_ids = set(id_to_name.keys())
    print(f"  {len(all_bus_ids)} buses totales en el sistema")

    # --- Construir grafo ---
    print(f"\nConstruyendo grafo completo (BRANCH + TRANSFORMER)...")
    adj = parse_graph(raw_lines)
    n_edges = sum(len(v) for v in adj.values()) // 2
    print(f"  {len(adj)} nodos con conexiones")
    print(f"  {n_edges} aristas (todas forzadas in_service)")

    # --- Parsear generadores ---
    print(f"\nParsando GENERATOR DATA...")
    gens = parse_generators(raw_lines, all_bus_ids, id_to_area)
    print(f"  {len(gens)} generadores argentinos")

    # --- Mapear generadores ---
    print(f"\nMapeando generadores al modelo...")
    rows      = []
    n_directo = 0
    n_bfs     = 0
    n_sin_con = 0

    for g in gens:
        bus_orig  = g['bus_id_origen']
        orig_name = id_to_name.get(bus_orig, str(bus_orig))

        if bus_orig in model_bus_ids:
            rows.append({
                **g,
                'bus_name_origen' : orig_name,
                'match_type'      : 'directo',
                'bus_destino'     : bus_orig,
                'bus_destino_name': model_id_to_name[bus_orig],
                'n_saltos'        : 0,
                'camino'          : '',
            })
            n_directo += 1

        else:
            bus_dest, n_saltos, camino_names = bfs_to_model(
                bus_orig, adj, model_bus_ids, id_to_name, id_to_baskv
            )

            if bus_dest is not None:
                camino_str = ' -> '.join(camino_names) if camino_names else ''
                rows.append({
                    **g,
                    'bus_name_origen' : orig_name,
                    'match_type'      : 'bfs',
                    'bus_destino'     : bus_dest,
                    'bus_destino_name': model_id_to_name.get(bus_dest, str(bus_dest)),
                    'n_saltos'        : n_saltos,
                    'camino'          : camino_str,
                })
                n_bfs += 1
            else:
                rows.append({
                    **g,
                    'bus_name_origen' : orig_name,
                    'match_type'      : 'sin_conexion',
                    'bus_destino'     : '',
                    'bus_destino_name': '',
                    'n_saltos'        : -1,
                    'camino'          : '',
                })
                n_sin_con += 1

    df = pd.DataFrame(rows)
    df = df[[
        'gen_key', 'bus_id_origen', 'bus_name_origen',
        'pg_mw', 'pt_mw', 'stat',
        'match_type', 'bus_destino', 'bus_destino_name',
        'n_saltos', 'camino',
    ]]

    # ==========================================================
    # REPORTE
    # ==========================================================
    print(f"\n{'='*60}")
    print(f"RESUMEN")
    print(f"{'='*60}")
    print(f"  Total generadores         : {len(df)}")
    print(f"  directo                   : {n_directo}  ({n_directo/len(df)*100:.1f}%)")
    print(f"  bfs                       : {n_bfs}  ({n_bfs/len(df)*100:.1f}%)")
    print(f"  sin_conexion              : {n_sin_con}  ({n_sin_con/len(df)*100:.1f}%)")

    print(f"\n  MW por match_type (pt_mw, excluye PT=9999):")
    for mt, grp in df.groupby('match_type'):
        mw = grp[grp['pt_mw'] < 9990]['pt_mw'].abs().sum()
        print(f"    {mt:<15}: {mw:>10,.1f} MW")

    print(f"\n  Balance PG snapshot (solo STAT=1, excluye PT=9999):")
    activos = df[(df['stat'] == 1) & (df['pt_mw'] < 9990)]
    print(f"    PG total STAT=1         : {activos['pg_mw'].sum():>10,.1f} MW")

    print(f"\n  Distribucion de n_saltos (solo bfs):")
    bfs_df = df[df['match_type'] == 'bfs']
    for saltos, grp in bfs_df.groupby('n_saltos'):
        print(f"    {saltos:>2} salto(s): {len(grp):>4} generadores")

    print(f"\n  Top 10 nodos por potencia total recibida:")
    valid = df[df['bus_destino'] != ''].copy()
    valid['pt_abs'] = valid['pt_mw'].apply(lambda x: abs(x) if abs(x) < 9990 else 0)
    top = (valid.groupby('bus_destino_name')
                .agg(n_gen=('gen_key', 'count'), mw_total=('pt_abs', 'sum'))
                .sort_values('mw_total', ascending=False)
                .head(10))
    for name, row in top.iterrows():
        print(f"    {name:<30}: {row['n_gen']:>4.0f} gen   {row['mw_total']:>8,.1f} MW")

    # ==========================================================
    # EXPORTAR generators_mapped.csv
    # ==========================================================
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    df.to_csv(OUTPUT_CSV, index=False)
    print(f"\n✔ {OUTPUT_CSV}  ({len(df)} filas)")

    # ==========================================================
    # EXPORTAR generators_manual_assignment.csv
    # Centrales sin_conexion relevantes para asignacion manual.
    # Excluye redes industriales aisladas y equivalentes PSS/E.
    # Columnas bus_destino_manual y nombre_geosadi vacias para
    # completar manualmente antes de correr el script 11.
    # ==========================================================
    sin_conn = df[df['match_type'] == 'sin_conexion'].copy()
    sin_conn = sin_conn[
        ~sin_conn['bus_name_origen'].isin(EXCLUIR_BUS_NOMBRES) &
        (sin_conn['pt_mw'] < 9000)
    ].copy()

    sin_conn['central_prefix'] = sin_conn['bus_name_origen'].str[:6]

    resumen = (
        sin_conn.groupby('central_prefix')
        .agg(
            n_gen       = ('gen_key',       'count'),
            pg_total_mw = ('pg_mw',         lambda x: x[sin_conn.loc[x.index, 'stat'] == 1].sum()),
            pt_total_mw = ('pt_mw',         lambda x: x[x < 9000].sum()),
            gen_keys    = ('gen_key',        lambda x: '|'.join(x.astype(str))),
            bus_ids     = ('bus_id_origen',  lambda x: '|'.join(x.astype(str))),
        )
        .reset_index()
        .sort_values('pg_total_mw', ascending=False)
    )

    resumen['bus_destino_manual'] = ''
    resumen['nombre_geosadi']     = ''

    resumen.to_csv(OUTPUT_MANUAL, index=False)

    print(f"\n{'='*60}")
    print(f"OUTPUT 2 — asignacion manual")
    print(f"{'='*60}")
    print(f"  {len(resumen)} centrales sin_conexion para revision")
    print(f"  PG total (STAT=1): {resumen['pg_total_mw'].sum():.0f} MW")
    print(f"\n  Top 15 por PG:")
    for _, r in resumen.head(15).iterrows():
        print(f"    {r.central_prefix:<12}  pg={r.pg_total_mw:>6.0f} MW  pt={r.pt_total_mw:>6.0f} MW  ({int(r.n_gen)} gen)")
    print(f"\n  Completar columnas 'bus_destino_manual' y 'nombre_geosadi'")
    print(f"  antes de correr el script 11.")
    print(f"\n✔ {OUTPUT_MANUAL}  ({len(resumen)} filas)")
    print(f"\nProximo: 10_map_loads.py")


if __name__ == "__main__":
    main()
