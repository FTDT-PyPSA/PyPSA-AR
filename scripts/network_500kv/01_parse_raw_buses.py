"""
01_parse_raw_buses.py
Extracts 500 kV buses from the PSS/E .raw file and exports them to CSV.

Source  : Official data/PSSE/ver2526pid.raw  # (external — download from GitHub Releases, place in external_data_dir/PSSE/)
Output  : data/network_500kv/buses_500kv_raw.csv

Run from the repository root (pypsa-ar-base/):
    python scripts/network_500kv/01_parse_raw_buses.py

PSS/E v34 BUS DATA format:
    I,'NAME',BASKV,IDE,AREA,ZONE,OWNER,VM,VA,NVHI,NVLO,EVHI,EVLO

    IDE=4 (isolated) is excluded — buses disconnected from the system, no active branches.

Fields not extracted:
    NVHI, NVLO, EVHI, EVLO : voltage limits — all 1.1/0.9 in this base case
"""

import os
import sys
from pathlib import Path
import yaml
import pandas as pd

# =============================================================================
# CONFIGURATION
# =============================================================================

_cfg = yaml.safe_load(open(Path(__file__).parents[2] / "config.yaml"))
REPO_DIR     = Path(_cfg["repo_dir"])
EXTERNAL_DIR = Path(_cfg["external_data_dir"])

RAW_FILE    = EXTERNAL_DIR / "PSSE/ver2526pid.raw"
OUTPUT_DIR  = REPO_DIR / "data/network_500kv"
OUTPUT_FILE = OUTPUT_DIR / "buses_500kv_raw.csv"

KV_MIN = 490.0  # includes nominal 500 kV
KV_MAX = 530.0  # includes 525 kV assigned by PSS/E to some generators

# International buses identified by AREA per CAMMESA nomenclature (from AREA DATA in .raw)
INTERNATIONAL_AREAS = {
    18: "Paraguay",
    19: "Chile (SING)",
    20: "Brazil",
    22: "Bolivia",
    99: "Uruguay",
}

# Buses to exclude manually (genuinely isolated or insufficient data)
# Add bus_name to this set to exclude it from output
EXCLUDE_BUSES = {
    'R9B5RS',   # genuinely isolated bus, no connections in the raw
}

# True  -> excludes international buses from CSV
# False -> includes them flagged with is_international=True (default)
EXCLUDE_INTERNATIONAL = True


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


def parse_bus_line(line):
    line = line.strip()
    if not line or line.startswith('@') or line.startswith('/'):
        return None
    try:
        bus_id   = int(line[:line.index(',')].strip())
        q1       = line.index("'");  q2 = line.index("'", q1+1)
        bus_name = line[q1+1:q2].strip()
        parts    = [p.strip() for p in line[q2+1:].split(',')]
        if parts[0] == '': parts = parts[1:]
        return {
            'bus_id':   bus_id,
            'bus_name': bus_name,
            'baskv_kv': float(parts[0]),
            'ide':      int(parts[1]),
            'area':     int(parts[2]),
            'zone':     int(parts[3]),
            'owner':    int(parts[4]),
            'vm_pu':    float(parts[5]),
            'va_deg':   float(parts[6]),
        }
    except Exception as e:
        print(f"  [WARNING] line could not be parsed: {line[:80]} -- {e}")
        return None


IDE_DESC = {1: "PQ", 2: "PV", 3: "slack", 4: "isolated"}


# =============================================================================
# MAIN
# =============================================================================

def main():
    print("=" * 60)
    print("01_parse_raw_buses.py -- 500 kV buses from PSS/E RAW")
    print("=" * 60)

    if not os.path.isfile(RAW_FILE):
        print(f"[ERROR] File not found:\n  {RAW_FILE}"); sys.exit(1)

    with open(RAW_FILE, 'r', encoding='ISO-8859-1') as f:
        lines = f.readlines()

    print(f"Case  : {lines[2].rstrip()}")
    print(f"Lines in file: {len(lines)}")

    bus_lines = find_section(lines, "BEGIN BUS DATA", "END OF BUS DATA")
    all_buses = [b for b in (parse_bus_line(l) for l in bus_lines) if b]

    # Filter by voltage and exclude IDE=4 (disconnected from system)
    buses_500 = [b for b in all_buses
                 if KV_MIN <= b['baskv_kv'] <= KV_MAX and b['ide'] != 4]

    print(f"\nTotal buses parsed     : {len(all_buses)}")
    print(f"Active 500 kV buses    : {len(buses_500)}  (IDE=4 excluded)")

    # Flag international buses by area
    for b in buses_500:
        b['ide_desc'] = IDE_DESC.get(b['ide'], 'unknown')
        country = INTERNATIONAL_AREAS.get(b['area'])
        b['is_international'] = bool(country)
        b['country']          = country or ''

    n_intl = sum(1 for b in buses_500 if b['is_international'])
    print(f"International (by area): {n_intl}")

    if EXCLUDE_INTERNATIONAL:
        buses_500 = [b for b in buses_500 if not b['is_international']]
        print(f"-> Excluded. Remaining: {len(buses_500)} buses")
    else:
        print("-> Included with is_international=True  (EXCLUDE_INTERNATIONAL=False)")

    # Manually excluded buses
    if EXCLUDE_BUSES:
        before = len(buses_500)
        buses_500 = [b for b in buses_500 if b['bus_name'] not in EXCLUDE_BUSES]
        excluded = before - len(buses_500)
        if excluded:
            print(f"\nManually excluded buses (EXCLUDE_BUSES): {excluded}")
            for name in EXCLUDE_BUSES:
                print(f"  {name}")

    df = pd.DataFrame(buses_500)

    print("\nBy IDE type:")
    for ide_val, grp in df.groupby('ide'):
        print(f"  IDE={ide_val} ({IDE_DESC.get(ide_val)}): {len(grp)}")

    intl = df[df['is_international']]
    if not intl.empty:
        print("\nInternational buses in 500 kV range:")
        for _, r in intl.iterrows():
            print(f"  {int(r.bus_id):6}  {r.bus_name:12}  area={int(r.area)}  {r.country}")

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    col_order = [
        'bus_id', 'bus_name', 'baskv_kv', 'ide', 'ide_desc',
        'area', 'zone', 'owner', 'vm_pu', 'va_deg',
        'is_international', 'country',
    ]
    df[col_order].sort_values('bus_id').reset_index(drop=True).to_csv(OUTPUT_FILE, index=False)

    print(f"\n✔ {OUTPUT_FILE}  ({len(df)} rows)")
    print("Next: 02_parse_raw_lines.py")


if __name__ == "__main__":
    main()
