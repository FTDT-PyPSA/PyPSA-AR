"""
10_map_loads.py
Mapea todas las cargas del PSS/E a nodos del modelo (buses_final.csv).

Para cargas que conectan directamente a un nodo del modelo -> match_type='directo'
Para el resto -> BFS sobre el grafo completo del PSS/E hasta encontrar
                el primer nodo del modelo -> match_type='bfs'
Si BFS no encuentra ningun nodo del modelo -> match_type='sin_conexion'

Fuente : Official data/PSSE/ver2526pid.raw
Depende: data/network_500kv/buses_final.csv

Output : data/network_500kv/loads_mapped.csv

Correr desde WSL:
    python /mnt/c/Work/pypsa-ar-base/scripts/network_500kv/10_map_loads.py

============================================================
DECISIONES DE MODELADO
============================================================

CONSTRUCCION DEL GRAFO:
    Identica al script 09. Nodos: todos los buses del raw.
    Aristas: BRANCH DATA + TRANSFORMER DATA, todas forzadas in_service.

ALGORITMO BFS:
    Identico al script 09. Para cada carga cuyo bus_id NO esta en
    buses_final.csv se ejecuta BFS hasta encontrar el primer nodo
    del modelo. Desempate por mayor baskv_kv.

FILTRO DE INTERNACIONALES:
    Se excluyen cargas cuyo bus pertenece a areas CAMMESA de
    sistemas vecinos:
        18=Paraguay, 19=Chile (SING), 20=Brasil, 22=Bolivia, 99=Uruguay

CARGA TOTAL POR BUS:
    En este raw las componentes IP e YP son todas cero, por lo que
    PL = carga activa total del bus. Se verifica en el reporte.

COLUMNAS DEL OUTPUT loads_mapped.csv:
    load_key         : bus_id_origen-load_id  clave unica en PSS/E
    bus_id_origen    : bus_id PSS/E donde conecta fisicamente la carga
    bus_name_origen  : nombre del bus origen en PSS/E
    pl_mw            : carga activa en snapshot (MW)
    stat             : estado en snapshot (1=activo, 0=inactivo)
    match_type       : 'directo' / 'bfs' / 'sin_conexion'
    bus_destino      : bus_id del nodo de buses_final.csv asignado
    bus_destino_name : nombre del nodo destino
    n_saltos         : saltos BFS hasta destino (0 si directo, -1 si sin_conexion)
    camino           : secuencia de nombres de buses desde origen hasta destino
                       vacio si directo (origen == destino)
"""

import os
import sys
import pandas as pd
from collections import deque, defaultdict

# =============================================================================
# CONFIGURACION
# =============================================================================

RAW_FILE   = "/mnt/c/Work/pypsa-ar-sandbox/Official data/PSSE/ver2526pid.raw"
BUSES_FILE = "/mnt/c/Work/pypsa-ar-base/data/network_500kv/buses_final.csv"
OUTPUT_DIR = "/mnt/c/Work/pypsa-ar-base/data/network_500kv"
OUTPUT_CSV = os.path.join(OUTPUT_DIR, "loads_mapped.csv")

# Areas CAMMESA de sistemas vecinos -- cargas de estos buses se excluyen
INTERNATIONAL_AREAS = {18, 19, 20, 22, 99}


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


def parse_loads(lines, all_bus_ids, id_to_area):
    """
    Parsea LOAD DATA.
    Formato: I, 'ID', STAT, AREA, ZONE, PL, QL, IP, IQ, YP, YQ, OWNER, SCALE, INTRPT
    Excluye cargas de areas internacionales.
    Retorna lista de dicts.
    """
    loads  = []
    n_intl = 0
    ip_total = 0.0
    yp_total = 0.0

    for line in get_section(lines, 'BEGIN LOAD DATA', 'END OF LOAD DATA'):
        try:
            bus_id = int(line[:line.index(',')].strip())
            if bus_id not in all_bus_ids:
                continue
            area = id_to_area.get(bus_id, 0)
            if area in INTERNATIONAL_AREAS:
                n_intl += 1
                continue
            q1 = line.index("'"); q2 = line.index("'", q1+1)
            load_id = line[q1+1:q2].strip()
            rest = [x.strip() for x in line[q2+1:].split(',')]
            if rest[0] == '': rest = rest[1:]
            stat = int(rest[0])
            # rest[1]=AREA, rest[2]=ZONE ya parseados
            pl = float(rest[3])   # PL: potencia activa constante (MW)
            ip = float(rest[5])   # IP: componente corriente constante activa
            yp = float(rest[7])   # YP: componente admitancia constante activa
            ip_total += ip
            yp_total += yp
            loads.append({
                'bus_id_origen': bus_id,
                'load_id'      : load_id,
                'load_key'     : f"{bus_id}-{load_id}",
                'pl_mw'        : pl,
                'stat'         : stat,
            })
        except:
            continue

    print(f"  Cargas internacionales excluidas: {n_intl}")
    print(f"  Verificacion IP total: {ip_total:.1f} MW  (debe ser ~0)")
    print(f"  Verificacion YP total: {yp_total:.1f} MW  (debe ser ~0)")
    return loads


# =============================================================================
# BFS
# =============================================================================

def bfs_to_model(start_bus, adj, model_bus_ids, id_to_name, id_to_baskv):
    """
    BFS desde start_bus hasta el primer nodo en model_bus_ids.
    Retorna (bus_destino, n_saltos, camino_nombres) o (None, None, None).
    Desempate: si hay multiples destinos al mismo nivel, se elige el de mayor baskv_kv.
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
    print("10_map_loads.py -- mapeo cargas PSS/E -> modelo")
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

    # --- Parsear cargas ---
    print(f"\nParsando LOAD DATA...")
    loads = parse_loads(raw_lines, all_bus_ids, id_to_area)
    print(f"  {len(loads)} cargas argentinas")

    # --- Mapear cargas ---
    print(f"\nMapeando cargas al modelo...")
    rows      = []
    n_directo = 0
    n_bfs     = 0
    n_sin_con = 0

    for load in loads:
        bus_orig  = load['bus_id_origen']
        orig_name = id_to_name.get(bus_orig, str(bus_orig))

        if bus_orig in model_bus_ids:
            rows.append({
                **load,
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
                    **load,
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
                    **load,
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
        'load_key', 'bus_id_origen', 'bus_name_origen',
        'pl_mw', 'stat',
        'match_type', 'bus_destino', 'bus_destino_name',
        'n_saltos', 'camino',
    ]]

    # ==========================================================
    # REPORTE
    # ==========================================================
    print(f"\n{'='*60}")
    print(f"RESUMEN")
    print(f"{'='*60}")
    print(f"  Total cargas              : {len(df)}")
    print(f"  directo                   : {n_directo}  ({n_directo/len(df)*100:.1f}%)")
    print(f"  bfs                       : {n_bfs}  ({n_bfs/len(df)*100:.1f}%)")
    print(f"  sin_conexion              : {n_sin_con}  ({n_sin_con/len(df)*100:.1f}%)")

    activas = df[df['stat'] == 1]
    print(f"\n  Balance PL snapshot (solo STAT=1):")
    print(f"    PL total                : {activas['pl_mw'].sum():>10,.1f} MW")
    print(f"    PL directo              : {activas[activas['match_type']=='directo']['pl_mw'].sum():>10,.1f} MW")
    print(f"    PL bfs                  : {activas[activas['match_type']=='bfs']['pl_mw'].sum():>10,.1f} MW")
    print(f"    PL sin_conexion         : {activas[activas['match_type']=='sin_conexion']['pl_mw'].sum():>10,.1f} MW")

    print(f"\n  Distribucion de n_saltos (solo bfs):")
    bfs_df = df[df['match_type'] == 'bfs']
    for saltos, grp in bfs_df.groupby('n_saltos'):
        pl = grp[grp['stat']==1]['pl_mw'].sum()
        print(f"    {saltos:>2} salto(s): {len(grp):>4} cargas   PL={pl:>8,.1f} MW")

    print(f"\n  Cargas sin_conexion ({n_sin_con}) — aisladas del modelo:")
    sin = df[df['match_type'] == 'sin_conexion']
    if sin.empty:
        print(f"    ninguna")
    else:
        pl_sin = sin[sin['stat']==1]['pl_mw'].sum()
        print(f"    PL total aislada (STAT=1): {pl_sin:,.1f} MW")
        print(f"    Buses de origen:")
        for bus_id, grp in sin.groupby('bus_id_origen'):
            pl = grp[grp['stat']==1]['pl_mw'].sum()
            print(f"      bus={bus_id:<6} {grp['bus_name_origen'].iloc[0]:<20} "
                  f"{len(grp)} carga(s)  PL={pl:.1f} MW")

    print(f"\n  Top 10 nodos por carga total recibida (PL, STAT=1):")
    valid = df[(df['bus_destino'] != '') & (df['stat'] == 1)].copy()
    top = (valid.groupby('bus_destino_name')
               .agg(n_cargas=('load_key', 'count'), pl_total=('pl_mw', 'sum'))
               .sort_values('pl_total', ascending=False)
               .head(10))
    for name, row in top.iterrows():
        print(f"    {name:<30}: {row['n_cargas']:>4.0f} cargas   {row['pl_total']:>8,.1f} MW")

    # ==========================================================
    # EXPORTAR
    # ==========================================================
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    df.to_csv(OUTPUT_CSV, index=False)
    print(f"\n✔ {OUTPUT_CSV}  ({len(df)} filas)")
    print(f"\nProximo: 10b_visualize_qgis.py")


if __name__ == "__main__":
    main()
