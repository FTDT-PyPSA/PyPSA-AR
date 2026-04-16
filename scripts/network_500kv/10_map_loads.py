"""
10_map_loads.py
Maps all PSS/E loads to model nodes (buses_final.csv).

For loads connecting directly to a model node -> match_type='direct'
For the rest -> BFS over the full PSS/E graph until the first model node
               is found -> match_type='bfs'
If BFS finds no model node -> match_type='no_connection'

Source : Official data/PSSE/ver2526pid.raw  (external — download from GitHub Releases, place in external_data_dir/PSSE/)
Depends: data/network_500kv/buses_final.csv

Output:
    data/network_500kv/loads_mapped.csv

Run from the repository root (pypsa-ar-base/):
    python scripts/network_500kv/10_map_loads.py

============================================================
MODELING DECISIONS
============================================================

GRAPH CONSTRUCTION:
    Nodes : all buses from the raw (full BUS DATA)
    Edges : BRANCH DATA + TRANSFORMER DATA, all forced in_service.

BFS ALGORITHM:
    Identical to script 09. For each load whose bus_id is NOT in
    buses_final.csv, BFS is run until the first model node is found.
    Tiebreaking by highest baskv_kv.

INTERNATIONAL FILTER:
    Loads whose bus belongs to CAMMESA areas of neighboring systems
    are excluded:
        18=Paraguay, 19=Chile (SING), 20=Brazil, 22=Bolivia, 99=Uruguay

TOTAL LOAD PER BUS:
    In this raw the IP and YP components are all zero, so
    PL = total active load of the bus. Verified in the report.

OUTPUT COLUMNS — loads_mapped.csv:
    load_key             : bus_id_origen-load_id  unique PSS/E key
    bus_id_origen        : PSS/E bus_id where the load connects physically
    bus_name_origen      : name of the origin bus in PSS/E
    pl_mw                : active load in snapshot (MW)
    stat                 : snapshot status (1=active, 0=inactive)
    match_type           : 'direct' / 'bfs' / 'no_connection'
    bus_destination      : bus_id of the assigned node in buses_final.csv
    bus_destination_name : name of the destination node
    n_jumps              : BFS hops to destination (0=direct, -1=no_connection)
    path                 : sequence of bus names from origin to destination
                           empty if direct (origin == destination)
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
OUTPUT_CSV = OUTPUT_DIR / "loads_mapped.csv"

INTERNATIONAL_AREAS = {18, 19, 20, 22, 99}


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


def parse_all_buses(lines):
    """
    Parses full BUS DATA.
    Returns:
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


def parse_loads(lines, all_bus_ids, id_to_area):
    """
    Parses LOAD DATA.
    Format: I, 'ID', STAT, AREA, ZONE, PL, QL, IP, IQ, YP, YQ, OWNER, SCALE, INTRPT
    Excludes international loads.
    Returns list of dicts.
    """
    loads    = []
    n_intl   = 0
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
            pl   = float(rest[3])   # PL: constant active power (MW)
            ip   = float(rest[5])   # IP: constant current active component
            yp   = float(rest[7])   # YP: constant admittance active component
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

    print(f"  International loads excluded : {n_intl}")
    print(f"  IP total check : {ip_total:.1f} MW  (should be ~0)")
    print(f"  YP total check : {yp_total:.1f} MW  (should be ~0)")
    return loads


# =============================================================================
# BFS
# =============================================================================

def bfs_to_model(start_bus, adj, model_bus_ids, id_to_name, id_to_baskv):
    """
    BFS from start_bus to the first node in model_bus_ids.
    Returns (bus_destination, n_jumps, path_names) or (None, None, None).
    Tiebreaking: if multiple destinations found at the same level,
    choose the one with highest baskv_kv.
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
            n_jumps      = len(path) - 1
            path_names   = [id_to_name.get(b, str(b)) for b in path]
            return bus_dest, n_jumps, path_names

    return None, None, None


# =============================================================================
# MAIN
# =============================================================================

def main():
    print("=" * 60)
    print("10_map_loads.py -- map PSS/E loads to model nodes")
    print("=" * 60)

    for f in [RAW_FILE, BUSES_FILE]:
        if not os.path.isfile(f):
            print(f"[ERROR] File not found:\n  {f}")
            sys.exit(1)

    # --- Load model buses ---
    buses_df          = pd.read_csv(BUSES_FILE)
    model_bus_ids     = set(buses_df['bus_id'].astype(int))
    model_id_to_name  = dict(zip(buses_df['bus_id'].astype(int), buses_df['bus_name']))
    model_id_to_baskv = dict(zip(buses_df['bus_id'].astype(int), buses_df['baskv_kv']))
    print(f"Model nodes loaded: {len(model_bus_ids)}")

    # --- Read raw ---
    print(f"\nReading {RAW_FILE}...")
    with open(RAW_FILE, 'r', encoding='ISO-8859-1') as f:
        raw_lines = f.readlines()
    print(f"  {len(raw_lines)} lines")

    # --- Parse full bus data ---
    print(f"\nParsing BUS DATA...")
    id_to_name, id_to_baskv, id_to_area = parse_all_buses(raw_lines)
    all_bus_ids = set(id_to_name.keys())
    print(f"  {len(all_bus_ids)} total buses in system")

    # --- Build graph ---
    print(f"\nBuilding full graph (BRANCH + TRANSFORMER)...")
    adj = parse_graph(raw_lines)
    n_edges = sum(len(v) for v in adj.values()) // 2
    print(f"  {len(adj)} nodes with connections")
    print(f"  {n_edges} edges (all forced in_service)")

    # --- Parse loads ---
    print(f"\nParsing LOAD DATA...")
    loads = parse_loads(raw_lines, all_bus_ids, id_to_area)
    print(f"  {len(loads)} Argentine loads")

    # --- Map loads ---
    print(f"\nMapping loads to model nodes...")
    rows     = []
    n_direct = 0
    n_bfs    = 0
    n_no_con = 0

    for load in loads:
        bus_orig  = load['bus_id_origen']
        orig_name = id_to_name.get(bus_orig, str(bus_orig))

        if bus_orig in model_bus_ids:
            rows.append({
                **load,
                'bus_name_origen'    : orig_name,
                'match_type'         : 'direct',
                'bus_destination'    : bus_orig,
                'bus_destination_name': model_id_to_name[bus_orig],
                'n_jumps'            : 0,
                'path'               : '',
            })
            n_direct += 1

        else:
            bus_dest, n_jumps, path_names = bfs_to_model(
                bus_orig, adj, model_bus_ids, id_to_name, id_to_baskv
            )

            if bus_dest is not None:
                path_str = ' -> '.join(path_names) if path_names else ''
                rows.append({
                    **load,
                    'bus_name_origen'    : orig_name,
                    'match_type'         : 'bfs',
                    'bus_destination'    : bus_dest,
                    'bus_destination_name': model_id_to_name.get(bus_dest, str(bus_dest)),
                    'n_jumps'            : n_jumps,
                    'path'               : path_str,
                })
                n_bfs += 1
            else:
                rows.append({
                    **load,
                    'bus_name_origen'    : orig_name,
                    'match_type'         : 'no_connection',
                    'bus_destination'    : '',
                    'bus_destination_name': '',
                    'n_jumps'            : -1,
                    'path'               : '',
                })
                n_no_con += 1

    df = pd.DataFrame(rows)
    df = df[[
        'load_key', 'bus_id_origen', 'bus_name_origen',
        'pl_mw', 'stat',
        'match_type', 'bus_destination', 'bus_destination_name',
        'n_jumps', 'path',
    ]]

    # ==========================================================
    # SUMMARY
    # ==========================================================
    print(f"\n{'='*60}")
    print(f"SUMMARY")
    print(f"{'='*60}")
    print(f"  Total loads               : {len(df)}")
    print(f"  direct                    : {n_direct}  ({n_direct/len(df)*100:.1f}%)")
    print(f"  bfs                       : {n_bfs}  ({n_bfs/len(df)*100:.1f}%)")
    print(f"  no_connection             : {n_no_con}  ({n_no_con/len(df)*100:.1f}%)")

    activas = df[df['stat'] == 1]
    print(f"\n  PL balance snapshot (stat=1 only):")
    print(f"    PL total                : {activas['pl_mw'].sum():>10,.1f} MW")
    print(f"    PL direct               : {activas[activas['match_type']=='direct']['pl_mw'].sum():>10,.1f} MW")
    print(f"    PL bfs                  : {activas[activas['match_type']=='bfs']['pl_mw'].sum():>10,.1f} MW")
    print(f"    PL no_connection        : {activas[activas['match_type']=='no_connection']['pl_mw'].sum():>10,.1f} MW")

    print(f"\n  BFS hops distribution:")
    bfs_df = df[df['match_type'] == 'bfs']
    for jumps, grp in bfs_df.groupby('n_jumps'):
        pl = grp[grp['stat']==1]['pl_mw'].sum()
        print(f"    {jumps:>2} hop(s): {len(grp):>4} loads   PL={pl:>8,.1f} MW")

    print(f"\n  No_connection loads ({n_no_con}) — isolated from model:")
    sin = df[df['match_type'] == 'no_connection']
    if sin.empty:
        print(f"    none")
    else:
        pl_sin = sin[sin['stat']==1]['pl_mw'].sum()
        print(f"    Total isolated PL (stat=1): {pl_sin:,.1f} MW")
        print(f"    Origin buses:")
        for bus_id, grp in sin.groupby('bus_id_origen'):
            pl = grp[grp['stat']==1]['pl_mw'].sum()
            print(f"      bus={bus_id:<6} {grp['bus_name_origen'].iloc[0]:<20} "
                  f"{len(grp)} load(s)  PL={pl:.1f} MW")

    print(f"\n  Top 10 nodes by total received load (PL, stat=1):")
    valid = df[(df['bus_destination'] != '') & (df['stat'] == 1)].copy()
    top = (valid.groupby('bus_destination_name')
               .agg(n_loads=('load_key', 'count'), pl_total=('pl_mw', 'sum'))
               .sort_values('pl_total', ascending=False)
               .head(10))
    for name, row in top.iterrows():
        print(f"    {name:<30}: {row['n_loads']:>4.0f} loads   {row['pl_total']:>8,.1f} MW")

    # ==========================================================
    # EXPORT
    # ==========================================================
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    df.to_csv(OUTPUT_CSV, index=False)
    print(f"\n✔ {OUTPUT_CSV}  ({len(df)} rows)")
    print("Next: 10b_visualize_qgis.py")


if __name__ == "__main__":
    main()
