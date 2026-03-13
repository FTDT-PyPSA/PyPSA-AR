"""
09_map_generators.py
Mapea todos los generadores del PSS/E a nodos del modelo (buses_final.csv).

Para generadores que conectan directamente a un nodo del modelo -> match_type='directo'
Para el resto -> BFS sobre el grafo completo del PSS/E hasta encontrar
                el primer nodo del modelo -> match_type='bfs'
Si BFS no encuentra ningun nodo del modelo -> match_type='sin_conexion'

Fuente : Official data/PSSE/ver2526pid.raw
Depende: data/network_500kv/buses_final.csv

Output:
    data/network_500kv/generators_mapped.csv
        Un generador por fila. Para todos los match_type.
        Usado por el script 11 para asignar coordenadas GeoSADI y
        construir generators_readypypsa + generators_pendingmanualpypsa.

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
    de buses_final.csv simultaneamente, se elige el nodo con mayor baskv_kv.
    Razon: los buses de mayor tension representan el punto de conexion
    electrica mas natural.

FILTRO DE INTERNACIONALES:
    Se excluyen generadores cuyo bus pertenece a areas CAMMESA de
    sistemas electricos vecinos:
        18=Paraguay, 19=Chile (SING), 20=Brasil, 22=Bolivia, 99=Uruguay

CAMPO CARRIER:
    Extraido del campo O1 (Owner 1) de GENERATOR DATA, resuelto contra
    OWNER DATA del mismo raw. Los owner IDs en OWNER_ID_TO_CARRIER se
    mapean a carriers PyPSA estandar. El resto conservan su nombre
    original de OWNER DATA (ej: DEMANDA, SS.AA., TRANSPORTE).

FILTRO Y CORRECCION DE CARRIERS NO VALIDOS:
    Si el carrier resuelto NO pertenece a GENERATION_CARRIERS, se
    inspecciona el bus_name_origen buscando un codigo de tecnologia
    en las posiciones [4:6] o [4:8] para nuclear.

    Codigos reconocidos:
        TG -> ocgt       TV -> steam      HI -> hydro
        DI -> diesel     CC -> ccgt       FV -> solar
        EO -> wind       BG -> biogas     BM -> biomass
        HB -> pumped_hydro   NUCL[4:8] -> nuclear

    Si se encuentra un codigo valido: se sobreescribe el carrier.
    Si no se encuentra: el generador se descarta del output.

COLUMNAS DEL OUTPUT generators_mapped.csv:
    gen_key               : bus_id_origen-gen_id, clave unica PSS/E
    bus_id_origen         : bus_id PSS/E donde conecta el generador
    bus_name_origen       : nombre del bus origen en PSS/E
    carrier               : tipo tecnologico
    pg_mw                 : despacho activo en snapshot (MW)
    pt_mw                 : potencia maxima PSS/E (MW)
    stat                  : estado en snapshot (1=en servicio, 0=fuera)
    match_type            : 'directo' / 'bfs' / 'sin_conexion'
    bus_conexion500kv     : bus_id del nodo de buses_final.csv asignado
    bus_conexion500kv_name: nombre del nodo destino en el modelo
    n_saltos              : saltos BFS hasta destino (0=directo, -1=sin_conexion)
    camino                : ruta de buses PSS/E desde origen hasta destino
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
OUTPUT_CSV = os.path.join(OUTPUT_DIR, "generators_mapped.csv")

INTERNATIONAL_AREAS = {18, 19, 20, 22, 99}

OWNER_ID_TO_CARRIER = {
    4:  'ocgt',
    5:  'steam',
    6:  'hydro',
    7:  'diesel',
    8:  'ccgt',
    9:  'nuclear',
    11: 'wind',
    12: 'solar',
    13: 'biogas',
    14: 'biomass',
    15: 'battery',
}

GENERATION_CARRIERS = set(OWNER_ID_TO_CARRIER.values())

NAME_CODE_TO_CARRIER = {
    'TG': 'ocgt',
    'TV': 'steam',
    'HI': 'hydro',
    'DI': 'diesel',
    'CC': 'ccgt',
    'FV': 'solar',
    'EO': 'wind',
    'BG': 'biogas',
    'BM': 'biomass',
    'HB': 'pumped_hydro',
}


def carrier_from_name(bus_name):
    """Intenta inferir carrier desde posiciones [4:6] o [4:8] del bus_name."""
    name = bus_name.upper().strip()
    if len(name) >= 8 and name[4:8] == 'NUCL':
        return 'nuclear'
    if len(name) >= 6:
        code = name[4:6]
        if code in NAME_CODE_TO_CARRIER:
            return NAME_CODE_TO_CARRIER[code]
    return None


# =============================================================================
# PARSEO DEL RAW
# =============================================================================

def get_section(lines, begin_marker, end_marker):
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


def parse_owner_data(lines):
    owner_to_carrier = {}
    for line in get_section(lines, 'BEGIN OWNER DATA', 'END OF OWNER DATA'):
        try:
            q1 = line.index("'"); q2 = line.index("'", q1+1)
            owner_id   = int(line[:q1].strip().rstrip(','))
            owner_name = line[q1+1:q2].strip()
            owner_to_carrier[owner_id] = OWNER_ID_TO_CARRIER.get(owner_id, owner_name)
        except:
            continue
    return owner_to_carrier


def parse_area_data(lines):
    area_to_name = {}
    for line in get_section(lines, 'BEGIN AREA DATA', 'END OF AREA DATA'):
        try:
            q1 = line.index("'"); q2 = line.index("'", q1+1)
            area_id   = int(line[:q1].strip().split(',')[0])
            area_name = line[q1+1:q2].strip()
            area_to_name[area_id] = area_name
        except:
            continue
    return area_to_name


def parse_all_buses(lines):
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
            bi, bj, bk = int(parts[0]), int(parts[1]), int(parts[2])
            adj[bi].add(bj); adj[bj].add(bi)
            if bk != 0:
                adj[bi].add(bk); adj[bk].add(bi)
                adj[bj].add(bk); adj[bk].add(bj)
            i += (5 if bk != 0 else 4)
        except:
            i += 1
    return adj


def parse_generators(lines, all_bus_ids, id_to_area, owner_to_carrier):
    gens   = []
    n_intl = 0
    for line in get_section(lines, 'BEGIN GENERATOR DATA', 'END OF GENERATOR DATA'):
        try:
            bus_id = int(line[:line.index(',')].strip())
            if bus_id not in all_bus_ids:
                continue
            if id_to_area.get(bus_id, 0) in INTERNATIONAL_AREAS:
                n_intl += 1
                continue
            q1 = line.index("'"); q2 = line.index("'", q1+1)
            gen_id = line[q1+1:q2].strip()
            rest = [x.strip() for x in line[q2+1:].split(',')]
            if rest[0] == '': rest = rest[1:]
            pg   = float(rest[0])
            stat = int(rest[12])
            pt   = float(rest[14])
            try:
                o1      = int(rest[16])
                carrier = owner_to_carrier.get(o1, 'unknown')
            except (IndexError, ValueError):
                carrier = 'unknown'
            gens.append({
                'bus_id_origen': bus_id,
                'gen_id'       : gen_id,
                'gen_key'      : f"{bus_id}-{gen_id}",
                '_carrier_raw' : carrier,
                'pg_mw'        : pg,
                'pt_mw'        : pt,
                'stat'         : stat,
            })
        except:
            continue
    print(f"  Generadores internacionales excluidos : {n_intl}")
    return gens, n_intl


def resolve_carriers(gens, id_to_name):
    out         = []
    n_corrected = 0
    n_dropped   = 0
    for g in gens:
        carrier = g['_carrier_raw']
        if carrier not in GENERATION_CARRIERS:
            bus_name = id_to_name.get(g['bus_id_origen'], '')
            inferred = carrier_from_name(bus_name)
            if inferred is not None:
                carrier = inferred
                n_corrected += 1
            else:
                n_dropped += 1
                continue
        g2 = {k: v for k, v in g.items() if k != '_carrier_raw'}
        g2['carrier'] = carrier
        out.append(g2)
    return out, n_corrected, n_dropped


# =============================================================================
# BFS
# =============================================================================

def bfs_to_model(start_bus, adj, model_bus_ids, id_to_name, id_to_baskv):
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
            camino_names = [id_to_name.get(b, str(b)) for b in path]
            return bus_dest, len(path) - 1, camino_names
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

    buses_df          = pd.read_csv(BUSES_FILE)
    model_bus_ids     = set(buses_df['bus_id'].astype(int))
    model_id_to_name  = dict(zip(buses_df['bus_id'].astype(int), buses_df['bus_name']))
    model_id_to_baskv = dict(zip(buses_df['bus_id'].astype(int), buses_df['baskv_kv']))
    print(f"Nodos del modelo cargados: {len(model_bus_ids)}")

    print(f"\nLeyendo {RAW_FILE}...")
    with open(RAW_FILE, 'r', encoding='ISO-8859-1') as f:
        raw_lines = f.readlines()
    print(f"  {len(raw_lines)} lineas")

    print(f"\nParsando OWNER DATA...")
    owner_to_carrier = parse_owner_data(raw_lines)
    print(f"  {len(owner_to_carrier)} owners cargados")

    print(f"\nParsando AREA DATA...")
    area_to_name = parse_area_data(raw_lines)
    print(f"  {len(area_to_name)} areas cargadas")

    print(f"\nParsando BUS DATA...")
    id_to_name, id_to_baskv, id_to_area = parse_all_buses(raw_lines)
    all_bus_ids = set(id_to_name.keys())
    print(f"  {len(all_bus_ids)} buses totales en el sistema")

    print(f"\nConstruyendo grafo completo (BRANCH + TRANSFORMER)...")
    adj = parse_graph(raw_lines)
    n_edges = sum(len(v) for v in adj.values()) // 2
    print(f"  {len(adj)} nodos con conexiones")
    print(f"  {n_edges} aristas")

    print(f"\nParsando GENERATOR DATA...")
    gens_raw, n_intl = parse_generators(raw_lines, all_bus_ids, id_to_area, owner_to_carrier)
    print(f"  {len(gens_raw)} generadores argentinos (pre-filtro carrier)")

    print(f"\nResolviendo carriers...")
    gens, n_corrected, n_dropped = resolve_carriers(gens_raw, id_to_name)
    print(f"  Corregidos desde nombre del bus : {n_corrected}")
    print(f"  Descartados (sin carrier valido): {n_dropped}")
    print(f"  Generadores finales             : {len(gens)}")

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
                'bus_name_origen'      : orig_name,
                'match_type'           : 'directo',
                'bus_conexion500kv'    : bus_orig,
                'bus_conexion500kv_name': model_id_to_name[bus_orig],
                'n_saltos'             : 0,
                'camino'               : '',
            })
            n_directo += 1
        else:
            bus_dest, n_saltos, camino_names = bfs_to_model(
                bus_orig, adj, model_bus_ids, id_to_name, id_to_baskv
            )
            if bus_dest is not None:
                rows.append({
                    **g,
                    'bus_name_origen'      : orig_name,
                    'match_type'           : 'bfs',
                    'bus_conexion500kv'    : bus_dest,
                    'bus_conexion500kv_name': model_id_to_name.get(bus_dest, str(bus_dest)),
                    'n_saltos'             : n_saltos,
                    'camino'               : ' -> '.join(camino_names),
                })
                n_bfs += 1
            else:
                rows.append({
                    **g,
                    'bus_name_origen'      : orig_name,
                    'match_type'           : 'sin_conexion',
                    'bus_conexion500kv'    : '',
                    'bus_conexion500kv_name': '',
                    'n_saltos'             : -1,
                    'camino'               : '',
                })
                n_sin_con += 1

    df = pd.DataFrame(rows)
    df = df[[
        'gen_key', 'bus_id_origen', 'bus_name_origen', 'carrier',
        'pg_mw', 'pt_mw', 'stat',
        'match_type', 'bus_conexion500kv', 'bus_conexion500kv_name',
        'n_saltos', 'camino',
    ]]

    # ==========================================================
    # REPORTE
    # ==========================================================
    print(f"\n{'='*60}")
    print(f"RESUMEN")
    print(f"{'='*60}")
    print(f"  Total generadores  : {len(df)}")
    print(f"  directo            : {n_directo}  ({n_directo/len(df)*100:.1f}%)")
    print(f"  bfs                : {n_bfs}  ({n_bfs/len(df)*100:.1f}%)")
    print(f"  sin_conexion       : {n_sin_con}  ({n_sin_con/len(df)*100:.1f}%)")

    print(f"\n  MW por match_type (pt_mw, excluye PT=9999):")
    for mt, grp in df.groupby('match_type'):
        mw = grp[grp['pt_mw'] < 9990]['pt_mw'].abs().sum()
        print(f"    {mt:<15}: {mw:>10,.1f} MW")

    print(f"\n  Distribucion por carrier (STAT=1, pt < 9999):")
    activos = df[(df['stat'] == 1) & (df['pt_mw'] < 9990)]
    for carrier, grp in activos.groupby('carrier'):
        print(f"    {carrier:<15}: {len(grp):>4} gen   {grp['pt_mw'].sum():>10,.1f} MW")

    print(f"\n  Distribucion de n_saltos (solo bfs):")
    for saltos, grp in df[df['match_type'] == 'bfs'].groupby('n_saltos'):
        print(f"    {saltos:>2} salto(s): {len(grp):>4} generadores")

    print(f"\n  Top 10 nodos por potencia recibida:")
    valid = df[df['bus_conexion500kv'] != ''].copy()
    valid['pt_abs'] = valid['pt_mw'].apply(lambda x: abs(x) if abs(x) < 9990 else 0)
    top = (valid.groupby('bus_conexion500kv_name')
                .agg(n_gen=('gen_key','count'), mw_total=('pt_abs','sum'))
                .sort_values('mw_total', ascending=False).head(10))
    for name, row in top.iterrows():
        print(f"    {name:<30}: {row['n_gen']:>4.0f} gen   {row['mw_total']:>8,.1f} MW")

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    df.to_csv(OUTPUT_CSV, index=False)
    print(f"\n✔ {OUTPUT_CSV}  ({len(df)} filas)")
    print(f"\nProximo: 11_add_geo_to_generators.py")


if __name__ == "__main__":
    main()
