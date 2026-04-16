"""
02_parse_raw_lines.py
Extracts 500 kV lines from the PSS/E .raw file and exports them to CSV.

Source  : Official data/PSSE/ver2526pid.raw  (external — download from GitHub Releases, place in external_data_dir/PSSE/)
Depends : data/network_500kv/buses_500kv_raw.csv  (output script 01)
Output  : data/network_500kv/lines_500kv_raw.csv

Run from the repository root (pypsa-ar-base/):
    python scripts/network_500kv/02_parse_raw_lines.py

PSS/E v34 BRANCH DATA format:
    I,J,'CKT',R,X,B,'NAME',RATEA..RATEK,GI,BI,GJ,BJ,ST,MET,LEN,...

Extracted fields:
    I, J       : terminal buses
    CKT        : circuit ID -- identifies parallel lines between the same buses
    R, X, B    : resistance, reactance, susceptance [pu, Sbase=100 MVA]
    RATEA      : thermal rating [MVA] (Rating Set 1 in PSS/E)
    ST         : status (1=in service, 0=out of service)
    LEN        : length [km]

Discarded fields:
    RATEB..K        : alternative ratings -- equal to RATEA in this model
    GI,BI,GJ,BJ     : shunt admittances at terminals -- negligible in transmission
    MET             : loss measurement reference -- not relevant for PyPSA
    O1,F1...        : owner and fraction

International filter:
    valid_ids comes from the script 01 CSV. If that CSV excludes internationals
    (EXCLUDE_INTERNATIONAL=True), branches with those buses are excluded automatically.

Classification criteria:
    element_type=series_compensator : X<0 (capacitive series compensator)
    element_type=line               : all others
    rating_defined=False            : RATEA=0 in the .raw (no thermal rating defined)
                                      ratea_mva is set to NaN in those cases

in_service field:
    FORCE_ALL_IN_SERVICE=True  -> all branches set to in_service=True
                                  represents the full network under normal conditions
    FORCE_ALL_IN_SERVICE=False -> in_service reflects ST from the raw (point-in-time snapshot)
"""

import os
import sys
from pathlib import Path
import yaml
import numpy as np
import pandas as pd
from collections import Counter

# =============================================================================
# CONFIGURATION
# =============================================================================

_cfg = yaml.safe_load(open(Path(__file__).parents[2] / "config.yaml"))
REPO_DIR     = Path(_cfg["repo_dir"])
EXTERNAL_DIR = Path(_cfg["external_data_dir"])

RAW_FILE    = EXTERNAL_DIR / "PSSE/ver2526pid.raw"
BUSES_FILE  = REPO_DIR / "data/network_500kv/buses_500kv_raw.csv"
OUTPUT_DIR  = REPO_DIR / "data/network_500kv"
OUTPUT_FILE = OUTPUT_DIR / "lines_500kv_raw.csv"

# True  -> includes ST=0 branches in the CSV
# False -> in-service branches only
INCLUDE_OUT_OF_SERVICE = True

# True  -> forces in_service=True on all branches (full network, normal conditions)
# False -> in_service reflects ST from the raw as-is (PSS/E point-in-time snapshot)
FORCE_ALL_IN_SERVICE = True


# =============================================================================
# FUNCTIONS
# =============================================================================

def find_section(lines, start_marker, end_marker):
    inside, result = False, []
    for line in lines:
        if start_marker in line:
            inside = True; continue
        if end_marker in line:
            break
        if inside:
            result.append(line.rstrip())
    return result


def parse_branch_line(line):
    """
    Format: I,J,'CKT',R,X,B,'NAME',RATEA..RATEK,GI,BI,GJ,BJ,ST,MET,LEN,...
    Two quoted strings: CKT and line name (ignored).
    Layout after the name (12 rating sets):
      rest[0..11]=RATEA..RATEK  rest[12..15]=GI,BI,GJ,BJ  rest[16]=ST  rest[17]=MET  rest[18]=LEN
    """
    line = line.strip()
    if not line or line.startswith('@') or line.startswith('/'):
        return None
    Q = "'"
    try:
        p1 = line.index(Q);  p2 = line.index(Q, p1+1)
        p3 = line.index(Q, p2+1); p4 = line.index(Q, p3+1)
        ij   = [x.strip() for x in line[:p1].split(',') if x.strip()]
        rxb  = [x.strip() for x in line[p2+1:p3].split(',') if x.strip()]
        rest = [x.strip() for x in line[p4+1:].split(',') if x.strip()]
        return {
            'bus_i':     ij[0],
            'bus_j':     ij[1],
            'ckt':       line[p1+1:p2].strip(),
            'r_pu':      float(rxb[0]),
            'x_pu':      float(rxb[1]),
            'b_pu':      float(rxb[2]),
            'ratea_mva': float(rest[0]),
            'st':        int(rest[16]),
            'len_km':    float(rest[18]),
        }
    except Exception as e:
        print(f"  [WARNING] line could not be parsed: {line[:80]} -- {e}")
        return None


# =============================================================================
# MAIN
# =============================================================================

def main():
    print("=" * 60)
    print("02_parse_raw_lines.py -- 500 kV lines from PSS/E RAW")
    print("=" * 60)

    for f in [RAW_FILE, BUSES_FILE]:
        if not os.path.isfile(f):
            print(f"[ERROR] File not found:\n  {f}"); sys.exit(1)

    # valid_ids and id->name map come from script 01
    buses_df   = pd.read_csv(BUSES_FILE)
    valid_ids  = set(buses_df['bus_id'].astype(str))
    id_to_name = dict(zip(buses_df['bus_id'].astype(str), buses_df['bus_name']))
    print(f"Valid buses loaded from script 01 : {len(valid_ids)}")

    with open(RAW_FILE, 'r', encoding='ISO-8859-1') as f:
        lines = f.readlines()
    print(f"Case : {lines[2].rstrip()}")

    branch_lines = find_section(lines, "BEGIN BRANCH DATA", "END OF BRANCH DATA")
    all_branches = [b for b in (parse_branch_line(l) for l in branch_lines) if b]
    print(f"\nTotal branches in model          : {len(all_branches)}")

    # Both terminals must be in valid_ids
    branches_500 = [b for b in all_branches
                    if b['bus_i'] in valid_ids and b['bus_j'] in valid_ids]
    print(f"500 kV branches (both terminals) : {len(branches_500)}")

    in_svc  = sum(1 for b in branches_500 if b['st'] == 1)
    out_svc = sum(1 for b in branches_500 if b['st'] == 0)
    print(f"  In service     (ST=1) : {in_svc}")
    print(f"  Out of service (ST=0) : {out_svc}")

    if not INCLUDE_OUT_OF_SERVICE:
        branches_500 = [b for b in branches_500 if b['st'] == 1]
        print(f"  -> ST=0 excluded (INCLUDE_OUT_OF_SERVICE=False). Remaining: {len(branches_500)}")
    else:
        print(f"  -> ST=0 included (INCLUDE_OUT_OF_SERVICE=True)")

    # Assign in_service flag
    if FORCE_ALL_IN_SERVICE:
        for b in branches_500:
            b['in_service'] = True
        print(f"  -> FORCE_ALL_IN_SERVICE=True: all branches set to in_service=True")
    else:
        for b in branches_500:
            b['in_service'] = (b['st'] == 1)
        print(f"  -> FORCE_ALL_IN_SERVICE=False: in_service reflects ST from raw")

    for b in branches_500:
        name_i = id_to_name.get(b['bus_i'], b['bus_i'])
        name_j = id_to_name.get(b['bus_j'], b['bus_j'])
        ckt_map = {'A': '1', 'B': '2', 'C': '3', 'D': '4', 'E': '5'}
        b['ckt'] = ckt_map.get(b['ckt'].upper(), b['ckt'])
        b['line_key']       = f"{name_i}-{name_j}-{b['ckt']}"
        b['element_type']   = 'series_compensator' if (b['x_pu'] < 0) else 'line'
        b['rating_defined'] = (b['ratea_mva'] != 0)
        if not b['rating_defined']:
            b['ratea_mva'] = np.nan

    df = pd.DataFrame(branches_500)

    print("\nBy element type:")
    for etype, grp in df.groupby('element_type'):
        print(f"  {etype}: {len(grp)}")

    n_no_rating = (~df['rating_defined']).sum()
    if n_no_rating:
        print(f"\nBranches with no rating defined (ratea_mva=NaN): {n_no_rating}")
        for _, r in df[~df['rating_defined']].iterrows():
            print(f"  {r.line_key}")

    pair_counts = Counter(f"{r.bus_i}-{r.bus_j}" for _, r in df.iterrows())
    parallel = sorted([(k,v) for k,v in pair_counts.items() if v > 1], key=lambda x: -x[1])
    print(f"\nBus pairs with parallel circuits: {len(parallel)}")
    for k, v in parallel:
        print(f"  {k}: {v} circuits")

    df = df.sort_values(['bus_i', 'bus_j', 'ckt']).reset_index(drop=True)
    df.insert(0, 'line_id', range(1, len(df) + 1))

    col_order = [
        'line_id', 'line_key',
        'bus_i', 'bus_j', 'ckt',
        'r_pu', 'x_pu', 'b_pu',
        'ratea_mva', 'rating_defined',
        'len_km', 'element_type',
        'in_service',
    ]
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    df[col_order].to_csv(OUTPUT_FILE, index=False)

    print(f"\n✔ {OUTPUT_FILE}  ({len(df)} rows)")
    print("Next: 03_parse_raw_transformers.py")


if __name__ == "__main__":
    main()
