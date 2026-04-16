"""
09_map_generators.py
Maps all PSS/E generators to model nodes (buses_final.csv).

For generators connecting directly to a model node -> match_type='direct'
For the rest -> BFS over the full PSS/E graph until the first model node
               is found -> match_type='bfs'
If BFS finds no model node -> match_type='no_connection'

Source : Official data/PSSE/ver2526pid.raw  (external — download from GitHub Releases, place in external_data_dir/PSSE/)
Depends: data/network_500kv/buses_final.csv

Output:
    data/network_500kv/generators_mapped.csv
        One generator per row. Includes all match_type values.
        Used by script 11 to assign GeoSADI coordinates and build
        generators_readypypsa + generators_pendingmanualpypsa.

Run from the repository root (pypsa-ar-base/):
    python scripts/network_500kv/09_map_generators.py

============================================================
MODELING DECISIONS
============================================================

GRAPH CONSTRUCTION:
    Nodes : all buses from the raw (full BUS DATA)
    Edges : all branches from BRANCH DATA
          + all transformers from TRANSFORMER DATA
    Status: ALL branches treated as active (in_service=True)
            regardless of ST/STAT field in the raw.
            Reason: scripts 02 and 03 used FORCE_ALL_IN_SERVICE=True
            when building the PyPSA Network. The graph must be
            consistent with the network actually loaded into PyPSA.

BFS ALGORITHM:
    For each generator whose bus_id is NOT in buses_final.csv, a BFS
    (Breadth-First Search) is run from that bus_id, exploring level by
    level (1 hop, 2 hops, ...) until the first node in buses_final.csv
    is found. BFS guarantees the minimum-hop path.

BFS TIEBREAKING:
    If at the same BFS level multiple model nodes are found simultaneously,
    the node with the highest baskv_kv is chosen.
    Reason: higher-voltage buses represent the most natural electrical
    connection point.

INTERNATIONAL FILTER:
    Generators whose bus belongs to CAMMESA areas of neighboring systems
    are excluded:
        18=Paraguay, 19=Chile (SING), 20=Brazil, 22=Bolivia, 99=Uruguay

CARRIER FIELD:
    Extracted from O1 (Owner 1) field in GENERATOR DATA, resolved against
    OWNER DATA in the same raw. Owner IDs in OWNER_ID_TO_CARRIER are mapped
    to standard PyPSA carriers. Others retain their original OWNER DATA name
    (e.g. DEMANDA, SS.AA., TRANSPORTE).

INVALID CARRIER CORRECTION:
    If the resolved carrier does NOT belong to GENERATION_CARRIERS, the
    bus_name_origen is inspected for a technology code at positions [4:6]
    or [4:8] for nuclear.

    Recognized codes:
        TG -> ocgt       TV -> steam      HI -> hydro
        DI -> diesel     CC -> ccgt       FV -> solar
        EO -> wind       BG -> biogas     BM -> biomass
        HB -> pumped_hydro   NUCL[4:8] -> nuclear

    If a valid code is found: carrier is overridden.
    If not found: generator is dropped from output.

OUTPUT COLUMNS — generators_mapped.csv:
    gen_key                : bus_id_origen-gen_id, unique PSS/E key
    bus_id_origen          : PSS/E bus_id where the generator connects
    bus_name_origen        : name of the origin bus in PSS/E
    carrier                : technology type
    pg_mw                  : active dispatch in snapshot (MW)
    pt_mw                  : PSS/E maximum power (MW)
    stat                   : snapshot status (1=in service, 0=out of service)
    match_type             : 'direct' / 'bfs' / 'no_connection'
    bus_conexion500kv      : bus_id of the assigned node in buses_final.csv
    bus_conexion500kv_name : name of the destination node in the model
    n_jumps                : BFS hops to destination (0=direct, -1=no_connection)
    path                   : PSS/E bus path from origin to destination
"""

import os
import sys
from pathlib import Path
import yaml
import pandas as pd
from collections import deque, defaultdict

# =============================================================================
# CONFIGURATION
# =============================================================================

_cfg = yaml.safe_load(open(Path(__file__).parents[2] / "config.yaml"))
REPO_DIR     = Path(_cfg["repo_dir"])
EXTERNAL_DIR = Path(_cfg["external_data_dir"])

RAW_FILE   = EXTERNAL_DIR / "PSSE/ver2526pid.raw"
BUSES_FILE = REPO_DIR / "data/network_500kv/buses_final.csv"
OUTPUT_DIR = REPO_DIR / "data/network_500kv"
OUTPUT_CSV = OUTPUT_DIR / "generators_mapped.csv"

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
    """Attempts to infer carrier from positions [4:6] or [4:8] of bus_name."""
    name = bus_name.upper().strip()
    if len(name) >= 8 and name[4:8] == 'NUCL':
        return 'nuclear'
    if len(name) >= 6:
        code = name[4:6]
        if code in NAME_CODE_TO_CARRIER:
            return NAME_CODE_TO_CARRIER[code]
    return None


# =============================================================================
# PSS/E PARSING
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
    """
    Builds adjacency graph from BRANCH DATA + TRANSFORMER DATA.
    All branches treated as active (FORCE_ALL_IN_SERVICE).
    Returns dict: bus_id -> set of neighbor bus_ids.
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


def parse_generators(lines, all_bus_ids, id_to_area, owner_to_carrier):
    """
    Parses GENERATOR DATA.
    Format: I,'ID',PG,QG,QT,QB,VS,IREG,MBASE,ZR,ZX,RT,XT,GTAP,STAT,RMPCT,PT,PB,O1,F1,...
    Excludes international generators.
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
    print(f"  International generators excluded : {n_intl}")
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
    print("09_map_generators.py -- map PSS/E generators to model nodes")
    print("=" * 60)

    for f in [RAW_FILE, BUSES_FILE]:
        if not os.path.isfile(f):
            print(f"[ERROR] File not found:\n  {f}")
            sys.exit(1)

    buses_df          = pd.read_csv(BUSES_FILE)
    model_bus_ids     = set(buses_df['bus_id'].astype(int))
    model_id_to_name  = dict(zip(buses_df['bus_id'].astype(int), buses_df['bus_name']))
    model_id_to_baskv = dict(zip(buses_df['bus_id'].astype(int), buses_df['baskv_kv']))
    print(f"Model nodes loaded: {len(model_bus_ids)}")

    print(f"\nReading {RAW_FILE}...")
    with open(RAW_FILE, 'r', encoding='ISO-8859-1') as f:
        raw_lines = f.readlines()
    print(f"  {len(raw_lines)} lines")

    print(f"\nParsing OWNER DATA...")
    owner_to_carrier = parse_owner_data(raw_lines)
    print(f"  {len(owner_to_carrier)} owners loaded")

    print(f"\nParsing AREA DATA...")
    area_to_name = parse_area_data(raw_lines)
    print(f"  {len(area_to_name)} areas loaded")

    print(f"\nParsing BUS DATA...")
    id_to_name, id_to_baskv, id_to_area = parse_all_buses(raw_lines)
    all_bus_ids = set(id_to_name.keys())
    print(f"  {len(all_bus_ids)} total buses in system")

    print(f"\nBuilding full graph (BRANCH + TRANSFORMER)...")
    adj = parse_graph(raw_lines)
    n_edges = sum(len(v) for v in adj.values()) // 2
    print(f"  {len(adj)} nodes with connections")
    print(f"  {n_edges} edges")

    print(f"\nParsing GENERATOR DATA...")
    gens_raw, n_intl = parse_generators(raw_lines, all_bus_ids, id_to_area, owner_to_carrier)
    print(f"  {len(gens_raw)} Argentine generators (pre-carrier filter)")

    print(f"\nResolving carriers...")
    gens, n_corrected, n_dropped = resolve_carriers(gens_raw, id_to_name)
    print(f"  Corrected from bus name : {n_corrected}")
    print(f"  Dropped (no valid carrier): {n_dropped}")
    print(f"  Final generators          : {len(gens)}")

    print(f"\nMapping generators to model nodes...")
    rows      = []
    n_direct  = 0
    n_bfs     = 0
    n_no_con  = 0

    for g in gens:
        bus_orig  = g['bus_id_origen']
        orig_name = id_to_name.get(bus_orig, str(bus_orig))

        if bus_orig in model_bus_ids:
            rows.append({
                **g,
                'bus_name_origen'      : orig_name,
                'match_type'           : 'direct',
                'bus_conexion500kv'    : bus_orig,
                'bus_conexion500kv_name': model_id_to_name[bus_orig],
                'n_jumps'              : 0,
                'path'                 : '',
            })
            n_direct += 1
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
                    'n_jumps'              : n_saltos,
                    'path'                 : ' -> '.join(camino_names),
                })
                n_bfs += 1
            else:
                rows.append({
                    **g,
                    'bus_name_origen'      : orig_name,
                    'match_type'           : 'no_connection',
                    'bus_conexion500kv'    : '',
                    'bus_conexion500kv_name': '',
                    'n_jumps'              : -1,
                    'path'                 : '',
                })
                n_no_con += 1

    df = pd.DataFrame(rows)

    print(f"\n{'='*60}")
    print(f"MAPPING SUMMARY")
    print(f"{'='*60}")
    print(f"  Direct match     : {n_direct}")
    print(f"  BFS match        : {n_bfs}")
    print(f"  No connection    : {n_no_con}")
    print(f"  TOTAL            : {len(df)}")

    print(f"\n  MW by match_type (pt_mw, excludes PT=9999):")
    for mt, grp in df.groupby('match_type'):
        mw = grp[grp['pt_mw'] < 9990]['pt_mw'].abs().sum()
        print(f"    {mt:<15}: {mw:>10,.1f} MW")

    print(f"\n  By carrier (stat=1, pt < 9999):")
    activos = df[(df['stat'] == 1) & (df['pt_mw'] < 9990)]
    for carrier, grp in activos.groupby('carrier'):
        print(f"    {carrier:<15}: {len(grp):>4} units   {grp['pt_mw'].sum():>10,.1f} MW")

    print(f"\n  BFS hops distribution:")
    for jumps, grp in df[df['match_type'] == 'bfs'].groupby('n_jumps'):
        print(f"    {jumps:>2} hop(s): {len(grp):>4} generators")

    print(f"\n  Top 10 nodes by received capacity:")
    valid = df[df['bus_conexion500kv'] != ''].copy()
    valid['pt_abs'] = valid['pt_mw'].apply(lambda x: abs(x) if abs(x) < 9990 else 0)
    top = (valid.groupby('bus_conexion500kv_name')
                .agg(n_gen=('gen_key','count'), mw_total=('pt_abs','sum'))
                .sort_values('mw_total', ascending=False).head(10))
    for name, row in top.iterrows():
        print(f"    {name:<30}: {row['n_gen']:>4.0f} units   {row['mw_total']:>8,.1f} MW")

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    col_order = [
        'gen_key', 'bus_id_origen', 'bus_name_origen',
        'carrier', 'pg_mw', 'pt_mw', 'stat',
        'match_type',
        'bus_conexion500kv', 'bus_conexion500kv_name',
        'n_jumps', 'path',
    ]
    df[col_order].to_csv(OUTPUT_CSV, index=False)

    print(f"\n✔ {OUTPUT_CSV}  ({len(df)} rows)")
    print("Next: 10_map_loads.py")


if __name__ == "__main__":
    main()
