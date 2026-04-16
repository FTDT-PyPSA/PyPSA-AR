"""
03_parse_raw_transformers.py
Extracts transformers with at least one 500 kV winding from the PSS/E .raw file.
3-winding transformers are decomposed into two 2-winding transformers using the
500 kV winding as the common reference, avoiding the need for fictitious star buses
in PyPSA.

Source  : Official data/PSSE/ver2526pid.raw  (external — download from GitHub Releases, place in external_data_dir/PSSE/)
Depends : data/network_500kv/buses_500kv_raw.csv  (output script 01)
Output  : data/network_500kv/trafos_500kv_raw.csv

Run from the repository root (pypsa-ar-base/):
    python scripts/network_500kv/03_parse_raw_transformers.py

tap_ratio field:
    WINDV of the 500 kV winding normalized according to the CW field in L1:
    - CW=1: WINDV already in pu -> tap_ratio = WINDV directly
    - CW=2: WINDV in kV         -> tap_ratio = WINDV / baskv_kv of the winding
    Expected values: typically between 0.90 and 1.10 pu.
    Value 1.0 indicates no deviation from nominal tap.

r_pu / x_pu fields:
    Impedances on the transformer's own base (sbase_mva).
    PyPSA Transformer expects r and x on that base when s_nom = sbase_mva.
    The CZ field in L1 indicates the original base in PSS/E:
    - CZ=1: R,X on system base (S_BASE_MVA=100 MVA) -> converted to transformer own base
    - CZ=2: R,X already on transformer own base -> used directly

in_service field:
    FORCE_ALL_IN_SERVICE=True  -> all transformers set to in_service=True
                                  represents the full network under normal conditions
    FORCE_ALL_IN_SERVICE=False -> in_service reflects STAT from the raw (point-in-time snapshot)
"""

import os
import sys
from pathlib import Path
import yaml
import pandas as pd
import numpy as np

# =============================================================================
# CONFIGURATION
# =============================================================================

_cfg = yaml.safe_load(open(Path(__file__).parents[2] / "config.yaml"))
REPO_DIR     = Path(_cfg["repo_dir"])
EXTERNAL_DIR = Path(_cfg["external_data_dir"])

RAW_FILE    = EXTERNAL_DIR / "PSSE/ver2526pid.raw"
BUSES_FILE  = REPO_DIR / "data/network_500kv/buses_500kv_raw.csv"
OUTPUT_DIR  = REPO_DIR / "data/network_500kv"
OUTPUT_FILE = OUTPUT_DIR / "trafos_500kv_raw.csv"

# True  -> all transformers set to in_service=True (full network, normal conditions)
# False -> in_service reflects STAT from the raw as-is (PSS/E point-in-time snapshot)
FORCE_ALL_IN_SERVICE = True

# PSS/E system base — confirmed in .raw header (line 2, SBASE field)
# Required to convert impedances when CZ=1 (system base -> transformer own base)
S_BASE_MVA = 100.0


# =============================================================================
# FUNCTIONS
# =============================================================================

def find_section_lines(all_lines, start_marker, end_marker):
    inside, result = False, []
    for line in all_lines:
        if start_marker in line:
            inside = True; continue
        if inside and end_marker in line:
            break
        if inside:
            result.append(line.rstrip())
    return result


def parse_transformers(trafo_lines, valid_500, id_to_name, bus_vnom):
    """
    Parses the TRANSFORMER DATA block from PSS/E.
    Decomposes 3W transformers into two 2W transformers with the 500 kV bus as reference.
    Returns a list of dicts ready to export to CSV.

    bus_vnom: dict bus_id -> baskv_kv, required to normalize WINDV when CW=2.
    """
    rows = []
    i = 0
    while i < len(trafo_lines):
        line = trafo_lines[i].strip()
        if not line or line.startswith('@') or line.startswith('0 /'):
            i += 1
            continue

            # --- Line 1 (L1): bus IDs, CKT, CW, CZ, CM, MAG1, MAG2, NMETR, NAME, STAT, ...
        try:
            parts = line.split(',')
            bus_i = int(parts[0].strip())
            bus_j = int(parts[1].strip())
            bus_k = int(parts[2].strip())
            n_wind = 2 if bus_k == 0 else 3

            # Format:
            # I,J,K,'CKT',CW,CZ,CM,MAG1,MAG2,NMETR,'NAME',STAT,...
            # Extract CKT, then the numeric block between the two quoted strings,
            # then STAT after the transformer name.
            q = "'"
            q1 = line.index(q)
            q2 = line.index(q, q1 + 1)
            q3 = line.index(q, q2 + 1)
            q4 = line.index(q, q3 + 1)

            ckt = line[q1 + 1:q2].strip()
            mid = [x.strip() for x in line[q2 + 1:q3].split(',') if x.strip()]
            post = [x.strip() for x in line[q4 + 1:].split(',') if x.strip()]

            cw = int(mid[0]) if len(mid) > 0 else 1   # CW=1 pu, CW=2 kV
            cz = int(mid[1]) if len(mid) > 1 else 2   # CZ=1 system base, CZ=2 transformer base
            stat = int(post[0]) if len(post) > 0 else 1

        except Exception as e:
            i += 1
            continue

        # --- Line 2 (L2): R, X, SBASE (and more for 3W)
        try:
            l2 = trafo_lines[i+1].strip()
            l2p = [x.strip() for x in l2.split(',') if x.strip()]
        except:
            i += (4 if n_wind == 2 else 5)
            continue

        # --- Lines 3/4/5: WINDV (tap ratio) per winding
        try:
            l3 = trafo_lines[i+2].strip()
            l3p = [x.strip() for x in l3.split(',') if x.strip()]
            windv1 = float(l3p[0]) if len(l3p) > 0 else 1.0

            l4 = trafo_lines[i+3].strip()
            l4p = [x.strip() for x in l4.split(',') if x.strip()]
            windv2 = float(l4p[0]) if len(l4p) > 0 else 1.0

            windv3 = float(trafo_lines[i+4].strip().split(',')[0]) if n_wind == 3 else 1.0

            # Normalize to pu according to CW
            # CW=1: WINDV already in pu -> no conversion needed
            # CW=2: WINDV in kV -> divide by baskv_kv of the corresponding winding
            if cw == 2:
                windv1 = windv1 / bus_vnom.get(bus_i, windv1) if bus_vnom.get(bus_i, 0) > 0 else 1.0
                windv2 = windv2 / bus_vnom.get(bus_j, windv2) if bus_vnom.get(bus_j, 0) > 0 else 1.0
                if n_wind == 3:
                    windv3 = windv3 / bus_vnom.get(bus_k, windv3) if bus_vnom.get(bus_k, 0) > 0 else 1.0

            # Advance index to next transformer
            i += (4 if n_wind == 2 else 5)

            # Filter: at least one side must be 500 kV
            buses = {bus_i, bus_j} if n_wind == 2 else {bus_i, bus_j, bus_k}
            if not buses & valid_500:
                continue

            in_service = True if FORCE_ALL_IN_SERVICE else (stat == 1)

            if n_wind == 2:
                # --- 2-winding transformer: single row ---
                r12  = float(l2p[0]) if len(l2p) > 0 else np.nan
                x12  = float(l2p[1]) if len(l2p) > 1 else np.nan
                sb12 = float(l2p[2]) if len(l2p) > 2 else np.nan
                # CZ=1: R,X on system base (100 MVA) -> convert to transformer own base
                # CZ=2: R,X already on transformer own base -> used directly by PyPSA
                if cz == 1 and sb12 > 0:
                    r12 = r12 * sb12 / S_BASE_MVA
                    x12 = x12 * sb12 / S_BASE_MVA
                ni = id_to_name.get(bus_i, str(bus_i))
                nj = id_to_name.get(bus_j, str(bus_j))
                # tap from 500 kV side: WINDV1 if bus_i is 500 kV, WINDV2 if bus_j
                tap = windv1 if bus_i in valid_500 else windv2
                rows.append({
                    'bus_i':      bus_i,
                    'bus_j':      bus_j,
                    'ckt':        ckt,
                    'r_pu':       r12,
                    'x_pu':       x12,
                    'sbase_mva':  sb12,
                    'tap_ratio':  tap,
                    'in_service': in_service,
                    'origin':     '2W',
                    'trafo_key':  f"{ni}-{nj}-{ckt}",
                })

            else:
                # --- 3-winding transformer: decompose into two 2W transformers ---
                # L2: R1-2, X1-2, SBASE1-2, R2-3, X2-3, SBASE2-3, R3-1, X3-1, SBASE3-1
                r12  = float(l2p[0]); x12  = float(l2p[1]); sb12 = float(l2p[2])
                r23  = float(l2p[3]); x23  = float(l2p[4]); sb23 = float(l2p[5])
                r31  = float(l2p[6]); x31  = float(l2p[7]); sb31 = float(l2p[8])
                # CZ=1: convert each R,X pair to its winding's own base
                if cz == 1:
                    if sb12 > 0: r12 = r12 * sb12 / S_BASE_MVA; x12 = x12 * sb12 / S_BASE_MVA
                    if sb23 > 0: r23 = r23 * sb23 / S_BASE_MVA; x23 = x23 * sb23 / S_BASE_MVA
                    if sb31 > 0: r31 = r31 * sb31 / S_BASE_MVA; x31 = x31 * sb31 / S_BASE_MVA

                # Identify 500 kV bus and assign impedances
                if bus_i in valid_500:
                    bus_500, bus_s1, bus_s2 = bus_i, bus_j, bus_k
                    r_a, x_a, sb_a = r12, x12, sb12   # I-J
                    r_b, x_b, sb_b = r31, x31, sb31   # K-I -> used as I-K
                    tap_500 = windv1
                elif bus_j in valid_500:
                    bus_500, bus_s1, bus_s2 = bus_j, bus_i, bus_k
                    r_a, x_a, sb_a = r12, x12, sb12   # I-J -> used as J-I
                    r_b, x_b, sb_b = r23, x23, sb23   # J-K
                    tap_500 = windv2
                else:
                    bus_500, bus_s1, bus_s2 = bus_k, bus_i, bus_j
                    r_a, x_a, sb_a = r31, x31, sb31   # K-I
                    r_b, x_b, sb_b = r23, x23, sb23   # J-K -> used as K-J
                    tap_500 = windv3

                n500  = id_to_name.get(bus_500, str(bus_500))
                ns1   = id_to_name.get(bus_s1,  str(bus_s1))
                ns2   = id_to_name.get(bus_s2,  str(bus_s2))

                rows.append({
                    'bus_i':      bus_500,
                    'bus_j':      bus_s1,
                    'ckt':        ckt,
                    'r_pu':       r_a,
                    'x_pu':       x_a,
                    'sbase_mva':  sb_a,
                    'tap_ratio':  tap_500,
                    'in_service': in_service,
                    'origin':     '3W_decomp',
                    'trafo_key':  f"{n500}-{ns1}-{ckt}",
                })
                rows.append({
                    'bus_i':      bus_500,
                    'bus_j':      bus_s2,
                    'ckt':        ckt,
                    'r_pu':       r_b,
                    'x_pu':       x_b,
                    'sbase_mva':  sb_b,
                    'tap_ratio':  tap_500,
                    'in_service': in_service,
                    'origin':     '3W_decomp',
                    'trafo_key':  f"{n500}-{ns2}-{ckt}",
                })

        except Exception as e:
            print(f"  [WARNING] transformer could not be parsed at line {i}: {e}")
            i += (4 if n_wind == 2 else 5)
            continue

    return rows


# =============================================================================
# MAIN
# =============================================================================

def main():
    print("=" * 60)
    print("03_parse_raw_transformers.py -- 500 kV transformers from PSS/E RAW")
    print("=" * 60)

    for f in [RAW_FILE, BUSES_FILE]:
        if not os.path.isfile(f):
            print(f"[ERROR] File not found:\n  {f}"); sys.exit(1)

    buses_df   = pd.read_csv(BUSES_FILE)
    valid_500  = set(buses_df['bus_id'].astype(int))
    id_to_name = dict(zip(buses_df['bus_id'].astype(int), buses_df['bus_name']))
    bus_vnom   = dict(zip(buses_df['bus_id'].astype(int), buses_df['baskv_kv'].astype(float)))
    print(f"500 kV buses loaded: {len(valid_500)}")

    with open(RAW_FILE, 'r', encoding='ISO-8859-1') as f:
        all_lines = f.readlines()

    trafo_lines = find_section_lines(all_lines, "BEGIN TRANSFORMER DATA", "0 / END OF TRANSFORMER DATA")
    print(f"Lines in TRANSFORMER DATA: {len(trafo_lines)}")

    rows = parse_transformers(trafo_lines, valid_500, id_to_name, bus_vnom)
    df = pd.DataFrame(rows)
    df.insert(0, 'trafo_id', range(1, len(df) + 1))

    # Summary
    orig_2w = (df['origin'] == '2W').sum()
    orig_3w = (df['origin'] == '3W_decomp').sum()
    print(f"\nTransformers in output:")
    print(f"  Original 2W                : {orig_2w}")
    print(f"  3W decomposed (x2)         : {orig_3w}  ({orig_3w//2} 3W transformers -> {orig_3w} rows)")
    print(f"  TOTAL rows                 : {len(df)}")

    if FORCE_ALL_IN_SERVICE:
        print(f"\n  -> FORCE_ALL_IN_SERVICE=True: all transformers set to in_service=True")
    else:
        in_svc = df['in_service'].sum()
        print(f"\n  -> FORCE_ALL_IN_SERVICE=False")
        print(f"     In service     : {in_svc}")
        print(f"     Out of service : {len(df) - in_svc}")

    tap_off = (df['tap_ratio'] != 1.0).sum()
    tap_min = df['tap_ratio'].min()
    tap_max = df['tap_ratio'].max()
    print(f"\n  Tap ratios:")
    print(f"     Transformers with tap != 1.0 : {tap_off}")
    print(f"     Range                        : [{tap_min:.4f}, {tap_max:.4f}]")

    col_order = [
        'trafo_id', 'trafo_key',
        'bus_i', 'bus_j',
        'ckt', 'origin',
        'r_pu', 'x_pu', 'sbase_mva',
        'tap_ratio',
        'in_service',
    ]
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    df[col_order].to_csv(OUTPUT_FILE, index=False)

    print(f"\n✔ {OUTPUT_FILE}  ({len(df)} rows)")
    print("Next: 04_parse_raw_buses_sec.py")


if __name__ == "__main__":
    main()
