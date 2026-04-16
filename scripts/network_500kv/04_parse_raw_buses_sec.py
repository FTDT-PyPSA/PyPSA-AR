"""
04_parse_raw_buses_sec.py
Extracts secondary buses (low-voltage side) from the 500 kV transformers in PSS/E.

Source  : Official data/PSSE/ver2526pid.raw  (external — download from GitHub Releases, place in external_data_dir/PSSE/)
Depends : data/network_500kv/buses_500kv_raw.csv  (script 01)
          data/network_500kv/trafos_500kv_raw.csv  (script 03)
Output  : data/network_500kv/buses_sec_raw.csv

Run from the repository root (pypsa-ar-base/):
    python scripts/network_500kv/04_parse_raw_buses_sec.py

Logic:
    1. Load all unique bus_j values from the transformer CSV.
    2. Exclude those already in buses_500kv_raw.csv (valid_500).
       -> Any bus_j found in valid_500 is reported as a warning (autotransformer).
    3. For each secondary bus, look up in the raw: bus_name_psse, baskv_kv, ide.
    4. Generate a custom bus_name in the format: PARENT_kVkV or PARENT_kVkV_N
       where PARENT is the name of the 500 kV bus it connects to,
       and N is a sequential index when multiple secondary buses share the same
       voltage level under the same 500 kV parent.

Output columns:
    bus_id         : PSS/E numeric bus ID
    bus_name       : generated name (PARENT_kVkV or PARENT_kVkV_N)
    bus_name_psse  : original name from the raw (traceability to PSS/E)
    baskv_kv       : base voltage in kV
    ide            : PSS/E bus type (1=PQ, 2=PV, 3=slack)
    vm_pu          : voltage magnitude from PSS/E base case (pu)
    va_deg         : voltage angle from PSS/E base case (degrees)
    parent_bus_id  : bus_id of the 500 kV bus it connects to via transformer

Notes:
    - ALL secondary buses are included without voltage filter.
      This covers machine terminals (11-22 kV) and network nodes (33-345 kV).
      Decision taken to reflect the full network and connect generation at the
      exact point matching the single-line diagram.
    - Geographic coordinates are assigned in script 05, inherited from the
      500 kV parent bus (same physical substation).
"""

import os
import sys
from pathlib import Path
import yaml
import pandas as pd
from collections import defaultdict

# =============================================================================
# CONFIGURATION
# =============================================================================

_cfg = yaml.safe_load(open(Path(__file__).parents[2] / "config.yaml"))
REPO_DIR     = Path(_cfg["repo_dir"])
EXTERNAL_DIR = Path(_cfg["external_data_dir"])

RAW_FILE    = EXTERNAL_DIR / "PSSE/ver2526pid.raw"
BUSES_FILE  = REPO_DIR / "data/network_500kv/buses_500kv_raw.csv"
TRAFOS_FILE = REPO_DIR / "data/network_500kv/trafos_500kv_raw.csv"
OUTPUT_DIR  = REPO_DIR / "data/network_500kv"
OUTPUT_FILE = OUTPUT_DIR / "buses_sec_raw.csv"


# =============================================================================
# FUNCTIONS
# =============================================================================

def parse_all_buses(raw_lines):
    """Parses the full BUS DATA section of the raw. Returns dict bus_id -> attributes."""
    buses = {}
    inside = False
    for line in raw_lines:
        if "BEGIN BUS DATA" in line:
            inside = True; continue
        if inside and "END OF BUS DATA" in line:
            break
        if inside:
            l = line.strip()
            if not l or l.startswith('@') or l.startswith('/'):
                continue
            try:
                bus_id = int(l[:l.index(',')].strip())
                q1 = l.index("'"); q2 = l.index("'", q1+1)
                bus_name = l[q1+1:q2].strip()
                parts = [p.strip() for p in l[q2+1:].split(',')]
                if parts[0] == '': parts = parts[1:]
                buses[bus_id] = {
                    'bus_name_psse': bus_name,
                    'baskv_kv':      float(parts[0]),
                    'ide':           int(parts[1]),
                    'vm_pu':         float(parts[5]),
                    'va_deg':        float(parts[6]),
                }
            except:
                pass
    return buses


IDE_DESC = {
    1: "PQ",
    2: "PV - active generator",
    3: "slack",
    4: "isolated - unit offline in snapshot",
}


def build_bus_name(parent_name, kv, index=None):
    """
    Generates secondary bus name.
    Format: PARENT_kVkV  or  PARENT_kVkV_N when multiple buses share the same voltage level.
    Voltage is formatted without decimals if integer, with 1 decimal otherwise.
    """
    kv_str = f"{int(kv)}kV" if kv == int(kv) else f"{kv:.1f}kV"
    base = f"{parent_name}_{kv_str}"
    return base if index is None else f"{base}_{index}"


# =============================================================================
# MAIN
# =============================================================================

def main():
    print("=" * 60)
    print("04_parse_raw_buses_sec.py -- secondary buses from PSS/E RAW")
    print("=" * 60)

    for f in [RAW_FILE, BUSES_FILE, TRAFOS_FILE]:
        if not os.path.isfile(f):
            print(f"[ERROR] File not found:\n  {f}")
            sys.exit(1)

    # Load 500 kV buses
    buses_500_df = pd.read_csv(BUSES_FILE)
    valid_500    = set(buses_500_df['bus_id'].astype(int))
    id_to_name   = dict(zip(buses_500_df['bus_id'].astype(int), buses_500_df['bus_name']))
    print(f"500 kV buses loaded : {len(valid_500)}")

    # Load transformers — extract unique bus_j and their parent bus_i (500 kV)
    trafos_df = pd.read_csv(TRAFOS_FILE)
    print(f"Transformers loaded : {len(trafos_df)}")

    # Map bus_j -> parent bus_i (500 kV)
    # If a bus_j appears with multiple parents (rare), take the first one
    busj_to_parent = {}
    for _, row in trafos_df.iterrows():
        bj = int(row['bus_j'])
        bi = int(row['bus_i'])
        if bj not in busj_to_parent:
            busj_to_parent[bj] = bi

    # Filter: exclude those already in valid_500
    autotrafos = {bj for bj in busj_to_parent if bj in valid_500}
    if autotrafos:
        print(f"\n  ⚠ WARNING: {len(autotrafos)} bus_j found in valid_500 (autotransformers):")
        for b in sorted(autotrafos):
            print(f"    bus_id={b}  {id_to_name.get(b,'?')}")

    secondary_ids = {bj for bj in busj_to_parent if bj not in valid_500}
    print(f"\nUnique secondary buses: {len(secondary_ids)}")

    # Parse all buses from raw
    with open(RAW_FILE, 'r', encoding='ISO-8859-1') as f:
        raw_lines = f.readlines()
    all_buses = parse_all_buses(raw_lines)

    # Check all secondary buses are present in the raw
    not_found = secondary_ids - set(all_buses.keys())
    if not_found:
        print(f"  ⚠ {len(not_found)} secondary buses not found in raw:")
        for b in sorted(not_found):
            print(f"    {b}")

    # Build names: group by (parent, kv) to detect multiples
    # parent_kv -> list of bus_ids
    parent_kv_groups = defaultdict(list)
    for bid in sorted(secondary_ids):
        if bid not in all_buses:
            continue
        parent_id   = busj_to_parent[bid]
        parent_name = id_to_name.get(parent_id, str(parent_id))
        kv          = all_buses[bid]['baskv_kv']
        parent_kv_groups[(parent_name, kv)].append(bid)

    # Assign names
    bus_name_map = {}  # bus_id -> generated name
    for (parent_name, kv), bid_list in parent_kv_groups.items():
        if len(bid_list) == 1:
            bus_name_map[bid_list[0]] = build_bus_name(parent_name, kv)
        else:
            for idx, bid in enumerate(bid_list, start=1):
                bus_name_map[bid] = build_bus_name(parent_name, kv, index=idx)

    # Build output rows
    rows = []
    for bid in sorted(secondary_ids):
        if bid not in all_buses:
            continue
        attrs       = all_buses[bid]
        parent_id   = busj_to_parent[bid]
        rows.append({
            'bus_id':        bid,
            'bus_name':      bus_name_map.get(bid, f"SEC_{bid}"),
            'bus_name_psse': attrs['bus_name_psse'],
            'baskv_kv':      attrs['baskv_kv'],
            'ide':           attrs['ide'],
            'ide_desc':      IDE_DESC.get(attrs['ide'], 'unknown'),
            'vm_pu':         attrs['vm_pu'],
            'va_deg':        attrs['va_deg'],
            'parent_bus_id': parent_id,
        })

    df = pd.DataFrame(rows)

    # Summary by voltage level
    print("\nSecondary buses by voltage level (kV):")
    for kv, grp in df.groupby('baskv_kv'):
        print(f"  {kv:>7.1f} kV : {len(grp)} buses")

    print(f"\nBy IDE type:")
    for ide_val, grp in df.groupby('ide'):
        print(f"  IDE={ide_val} ({IDE_DESC.get(ide_val,'?')}): {len(grp)}")

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    col_order = [
        'bus_id', 'bus_name', 'bus_name_psse',
        'baskv_kv', 'ide', 'ide_desc',
        'vm_pu', 'va_deg',
        'parent_bus_id',
    ]
    df[col_order].sort_values('bus_id').reset_index(drop=True).to_csv(OUTPUT_FILE, index=False)

    print(f"\n✔ {OUTPUT_FILE}  ({len(df)} rows)")
    print("Next: 05_match_geosadi_coords.py")


if __name__ == "__main__":
    main()
