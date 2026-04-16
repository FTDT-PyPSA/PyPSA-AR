"""
07_validate_topology.py
Validates the 500 kV network topology before loading it into PyPSA.

Inputs:
    data/network_500kv/buses_final.csv        (script 05 — all buses)
    data/network_500kv/lines_500kv_final.csv  (script 06 — lines with geometry)
    data/network_500kv/trafos_500kv_raw.csv   (script 03 — transformers)

Output:
    data/network_500kv/topology_report.csv    -> issues found (if any)

Run from the repository root (pypsa-ar-base/):
    python scripts/network_500kv/07_validate_topology.py

Validations performed:
    1. Orphan lines        : lines with bus_i or bus_j absent from the bus set
    2. Orphan transformers : transformers with bus_i or bus_j absent from the bus set
    3. Unconnected buses   : 500 kV buses with no 500 kV line connected
                               -> series compensator central bus : expected
                               -> transformer-only node          : expected
                               -> genuinely isolated bus         : error
    4. Connected components: how many disconnected islands the network has
                               (using only 500 kV buses and 500 kV lines)
    5. Electrical parameters: lines with r=0 and x=0 simultaneously
    6. Ratings             : lines with undefined ratea_mva (NaN)
    7. Out-of-service branches: informational, not an error
"""

import os
import sys
from pathlib import Path
import yaml
import pandas as pd
import numpy as np
from collections import defaultdict, deque

# =============================================================================
# CONFIGURATION
# =============================================================================

_cfg = yaml.safe_load(open(Path(__file__).parents[2] / "config.yaml"))
REPO_DIR = Path(_cfg["repo_dir"])

DATA_DIR      = REPO_DIR / "data/network_500kv"
BUSES_FILE    = DATA_DIR / "buses_final.csv"
LINES_FILE    = DATA_DIR / "lines_500kv_final.csv"
TRAFOS_FILE   = DATA_DIR / "trafos_500kv_raw.csv"
OUTPUT_REPORT = DATA_DIR / "topology_report.csv"


# =============================================================================
# FUNCTIONS
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
    print("07_validate_topology.py -- 500 kV network topology validation")
    print("=" * 60)

    for f in [BUSES_FILE, LINES_FILE, TRAFOS_FILE]:
        if not os.path.isfile(f):
            print(f"[ERROR] File not found:\n  {f}")
            sys.exit(1)

    buses  = pd.read_csv(BUSES_FILE)
    lines  = pd.read_csv(LINES_FILE)
    trafos = pd.read_csv(TRAFOS_FILE)

    # Separate 500 kV buses from secondary buses
    buses_500 = buses[buses['bus_type'] == '500kV']
    buses_sec = buses[buses['bus_type'] == 'secondary']

    all_bus_ids  = set(buses['bus_id'].astype(int))
    bus_ids_500  = set(buses_500['bus_id'].astype(int))
    bus_name_map = dict(zip(buses['bus_id'].astype(int), buses['bus_name']))

    print(f"\n  500 kV buses      : {len(buses_500)}")
    print(f"  Secondary buses   : {len(buses_sec)}")
    print(f"  Lines             : {len(lines)}")
    print(f"  Transformers      : {len(trafos)}")

    problems = []

    # ==========================================================
    # VALIDATION 1 — Orphan lines
    # ==========================================================
    print("\n[1] Orphan lines (bus_i or bus_j absent from bus set)...")
    orphan_lines = lines[
        ~lines["bus_i"].isin(all_bus_ids) | ~lines["bus_j"].isin(all_bus_ids)
    ]
    if orphan_lines.empty:
        print("    ✔ None")
    else:
        print(f"    ✘ {len(orphan_lines)} orphan lines")
        for _, r in orphan_lines.iterrows():
            missing = []
            if r["bus_i"] not in all_bus_ids: missing.append(f"bus_i={r['bus_i']}")
            if r["bus_j"] not in all_bus_ids: missing.append(f"bus_j={r['bus_j']}")
            print(f"      {r.get('line_key', r['line_id'])} — {', '.join(missing)}")
            problems.append({
                "type":    "orphan_line",
                "element": r.get("line_key", f"line_{r['line_id']}"),
                "detail":  f"missing buses: {', '.join(missing)}",
            })

    valid_lines = lines[
        lines["bus_i"].isin(all_bus_ids) & lines["bus_j"].isin(all_bus_ids)
    ]

    # ==========================================================
    # VALIDATION 2 — Orphan transformers
    # ==========================================================
    print("\n[2] Orphan transformers (bus_i or bus_j absent from bus set)...")
    orphan_trafos = trafos[
        ~trafos["bus_i"].isin(all_bus_ids) | ~trafos["bus_j"].isin(all_bus_ids)
    ]
    if orphan_trafos.empty:
        print("    ✔ None")
    else:
        print(f"    ✘ {len(orphan_trafos)} orphan transformers")
        for _, r in orphan_trafos.iterrows():
            missing = []
            if r["bus_i"] not in all_bus_ids: missing.append(f"bus_i={r['bus_i']}")
            if r["bus_j"] not in all_bus_ids: missing.append(f"bus_j={r['bus_j']}")
            print(f"      {r['trafo_key']} — {', '.join(missing)}")
            problems.append({
                "type":    "orphan_transformer",
                "element": r["trafo_key"],
                "detail":  f"missing buses: {', '.join(missing)}",
            })

    # ==========================================================
    # VALIDATION 3 — 500 kV buses without lines
    # ==========================================================
    print("\n[3] 500 kV buses with no 500 kV lines connected...")

    lines_only = valid_lines[
        valid_lines["element_type"] == "line"
    ] if "element_type" in valid_lines.columns else valid_lines

    comp_lines = valid_lines[
        valid_lines["element_type"] == "series_compensator"
    ] if "element_type" in valid_lines.columns else pd.DataFrame()

    buses_in_lines        = set(lines_only["bus_i"]).union(set(lines_only["bus_j"]))
    buses_in_compensators = set(comp_lines["bus_i"]).union(set(comp_lines["bus_j"])) if not comp_lines.empty else set()
    buses_in_trafos       = set(trafos["bus_i"].astype(int)).union(set(trafos["bus_j"].astype(int)))

    isolated_500  = bus_ids_500 - buses_in_lines
    n_compensator = 0
    n_trafo_only  = 0
    n_isolated    = 0
    excluded_buses = set()

    if not isolated_500:
        print("    ✔ None")
    else:
        for bus_id in sorted(isolated_500):
            bus_name = bus_name_map.get(bus_id, str(bus_id))
            if bus_id in buses_in_compensators:
                print(f"      ℹ {bus_name} — series compensator central bus")
                n_compensator += 1
                excluded_buses.add(bus_id)
            elif bus_id in buses_in_trafos:
                print(f"      ℹ {bus_name} — transformer-only node")
                n_trafo_only += 1
                excluded_buses.add(bus_id)
            else:
                print(f"      ✘ {bus_name} — genuinely isolated bus")
                n_isolated += 1
                problems.append({
                    "type":    "isolated_bus",
                    "element": bus_name,
                    "detail":  "no lines, compensators or transformers connected",
                })

        if n_compensator:
            print(f"    ℹ {n_compensator} series compensator central buses (expected)")
        if n_trafo_only:
            print(f"    ℹ {n_trafo_only} transformer-only nodes (expected)")
        if n_isolated:
            print(f"    ✘ {n_isolated} genuinely isolated buses")
        else:
            print(f"    ✔ No genuinely isolated 500 kV buses")

    # ==========================================================
    # VALIDATION 4 — Connected components (500 kV network only)
    # ==========================================================
    print("\n[4] Connected components (500 kV network)...")
    bus_ids_for_comp = bus_ids_500 - excluded_buses
    edges      = list(zip(valid_lines["bus_i"], valid_lines["bus_j"]))
    components = find_connected_components(bus_ids_for_comp, edges)
    main_comp  = max(components, key=len)

    print(f"    Components found  : {len(components)}")
    print(f"    Main component    : {len(main_comp)} buses")

    if len(components) > 1:
        print(f"    ✘ Network fragmented into {len(components)} islands")
        for i, comp in enumerate(sorted(components, key=len, reverse=True)):
            if i == 0:
                continue
            comp_names = [bus_name_map.get(b, str(b)) for b in comp]
            detail = ", ".join(comp_names)
            print(f"      Island {i}: {detail}")
            problems.append({
                "type":    "disconnected_island",
                "element": f"island_{i}",
                "detail":  detail,
            })
    else:
        print("    ✔ Network fully connected")

    # ==========================================================
    # VALIDATION 5 — Electrical parameters
    # ==========================================================
    print("\n[5] Electrical parameters (r=0 and x=0 simultaneously)...")
    zero_imp = valid_lines[(valid_lines["r_pu"] == 0) & (valid_lines["x_pu"] == 0)]
    if "element_type" in valid_lines.columns:
        zero_imp = zero_imp[zero_imp["element_type"] != "series_compensator"]
    if zero_imp.empty:
        print("    ✔ None")
    else:
        print(f"    ⚠ {len(zero_imp)} lines with r=0 and x=0")
        for _, r in zero_imp.iterrows():
            problems.append({
                "type":    "zero_impedance",
                "element": r.get("line_key", f"line_{r['line_id']}"),
                "detail":  "r_pu=0 and x_pu=0",
            })

    # ==========================================================
    # VALIDATION 6 — Ratings
    # ==========================================================
    print("\n[6] Undefined ratings (ratea_mva = NaN)...")
    no_rating = valid_lines[valid_lines["ratea_mva"].isna()]
    if no_rating.empty:
        print("    ✔ All lines have a rating defined")
    else:
        print(f"    ⚠ {len(no_rating)} lines without rating")
        for _, r in no_rating.iterrows():
            key = r.get("line_key", f"line_{r['line_id']}")
            print(f"      {key}")
            problems.append({
                "type":    "no_rating",
                "element": key,
                "detail":  "ratea_mva = NaN",
            })

    # ==========================================================
    # VALIDATION 7 — Out-of-service branches (informational)
    # ==========================================================
    print("\n[7] Out-of-service branches (in_service=False)...")
    if "in_service" in valid_lines.columns:
        out_svc = valid_lines[valid_lines["in_service"] == False]
        if out_svc.empty:
            print("    ✔ All branches in service")
        else:
            print(f"    ℹ {len(out_svc)} out-of-service branches (informational)")
            for _, r in out_svc.iterrows():
                print(f"      {r.get('line_key', r['line_id'])}")
    else:
        print("    ℹ in_service column not available")

    # ==========================================================
    # FINAL SUMMARY
    # ==========================================================
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"  500 kV buses           : {len(buses_500)}")
    print(f"  Secondary buses        : {len(buses_sec)}")
    print(f"  Valid lines            : {len(valid_lines)}")
    print(f"  Transformers           : {len(trafos)}")
    print(f"  Orphan lines           : {len(orphan_lines)}")
    print(f"  Orphan transformers    : {len(orphan_trafos)}")
    print(f"  500 kV buses no lines  : {len(isolated_500)}  (compensators: {n_compensator}, trafo-only: {n_trafo_only}, isolated: {n_isolated})")
    print(f"  Connected components   : {len(components)}")
    print(f"  Zero impedance         : {len(zero_imp)}")
    print(f"  No rating              : {len(no_rating)}")
    print(f"  Total issues           : {len(problems)}")

    if problems:
        df_prob = pd.DataFrame(problems)
        df_prob.to_csv(OUTPUT_REPORT, index=False)
        print(f"\n  Report saved to: {OUTPUT_REPORT}")
    else:
        print("\n  ✔ Network has no issues — ready for 08_build_pypsa_network.py")

    print(f"\nNext: 08_build_pypsa_network.py")


if __name__ == "__main__":
    main()
