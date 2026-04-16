"""
15_build_loads_2024.py
Builds the 2024 hourly demand table by 500 kV bus in long format.

Inputs:
    Official data/Dda_horaria_x_trafo_2024.csv  (external — download from GitHub Releases, place in external_data_dir/)
        Hourly demand by transformer for 2024. Wide format: one row per transformer,
        8784 hourly value columns in MW.
        4-row multi-level header:
            Row 1: hour of day (1-24)
            Row 2: cumulative hour of year (1-8784)
            Row 3: calendar date
            Row 4: metadata column names + month labels
    data/network_500kv/buses_final.csv
    data/network_500kv/lines_500kv_final.csv
        Used to compute the bus coupler fusion map, replicating the logic
        from script 08. Buses fused in the network receive the aggregated
        demand of all buses collapsed onto them.

Output:
    data/network_500kv/loads_2024.csv
        Long format: one row per 500 kV bus per hour.
        Columns: bus_id, bus_name, datetime, p_mw
        ~72 buses x 8784 hours

Logic:
    1. Parse the header to build the datetime index of the 8784 hourly columns
       using date (row 3) + hour of day (row 1).
    2. Read the data body with metadata columns + hourly values.
    3. Pivot to long format by transformer.
    4. Group by bus_id + datetime, summing all transformers connected to the same
       500 kV bus.
    5. Verify coverage against buses_final.csv.
    6. Export loads_2024.csv.

Run from the repository root (pypsa-ar-base/):
    python scripts/network_500kv/15_build_loads_2024.py
"""

import os
import sys
from pathlib import Path

import pandas as pd
import yaml

# =============================================================================
# CONFIGURATION
# =============================================================================

_cfg = yaml.safe_load(open(Path(__file__).parents[2] / "config.yaml"))
REPO_DIR = Path(_cfg["repo_dir"])
EXTERNAL_DIR = Path(_cfg["external_data_dir"])

DDA_FILE = EXTERNAL_DIR / "Dda_horaria_x_trafo_2024.csv"
BUSES_FILE = REPO_DIR / "data/network_500kv/buses_final.csv"
LINES_FILE = REPO_DIR / "data/network_500kv/lines_500kv_final.csv"
OUTPUT_DIR = REPO_DIR / "data/network_500kv"
OUTPUT_FILE = OUTPUT_DIR / "loads_2024.csv"

# Metadata columns in header row 4 (indices 0-25)
N_META_COLS = 26

# Metadata columns kept from the source file
COLS_META = ["trafo_id", "bus_id", "bus_name"]


# =============================================================================
# FUNCTIONS
# =============================================================================

def build_datetimes(row_date, row_hour):
    """
    Builds a list of timestamps from the date and hour vectors
    in the file header.

    row_date: list of strings like '1/1/2024', '1/1/2024', ..., '31/12/2024'
    row_hour: list of strings like '1', '2', ..., '24'
    """
    timestamps = []
    for date_str, hour_str in zip(row_date, row_hour):
        if date_str == "nan" or hour_str == "nan":
            continue
        date = pd.to_datetime(date_str.strip(), dayfirst=True, errors="coerce")
        hour = int(hour_str) - 1  # HOUR=1 -> 00:00, HOUR=24 -> 23:00
        timestamps.append(date + pd.Timedelta(hours=hour))
    return timestamps


# =============================================================================
# FUSION MAP — replicates the Union-Find logic from script 08
# Fused buses in the network must receive the aggregated demand
# of all buses collapsed onto them.
# =============================================================================

def compute_fusion_map(buses, lines):
    """
    Detects bus couplers (series_compensator with r_pu=0) and computes
    the map bus_name -> representative_bus_name using Union-Find.
    This is the same logic as block [1b] in script 08.
    """
    id_to_name = dict(zip(buses["bus_id"].astype(int), buses["bus_name"]))
    all_bus_ids = set(buses["bus_id"].astype(int))

    couplers = lines[
        (lines["element_type"] == "series_compensator") &
        (lines["r_pu"] == 0.0)
    ]

    parent = {}

    def find(x):
        while parent.get(x, x) != x:
            parent[x] = parent.get(parent.get(x, x), parent.get(x, x))
            x = parent.get(x, x)
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra == rb:
            return
        try:
            if int(ra) > int(rb):
                ra, rb = rb, ra
        except (ValueError, TypeError):
            pass
        parent[rb] = ra

    for _, row in couplers.iterrows():
        union(str(int(row["bus_i"])), str(int(row["bus_j"])))

    all_bus_id_strs = {str(bid) for bid in all_bus_ids}
    fusion_map_ids = {b: find(b) for b in all_bus_id_strs if find(b) != b}

    fusion_map = {}
    for child_id_str, root_id_str in fusion_map_ids.items():
        child_name = id_to_name.get(int(child_id_str))
        root_name = id_to_name.get(int(root_id_str))
        if child_name and root_name:
            fusion_map[child_name] = root_name

    return fusion_map


# =============================================================================
# MAIN
# =============================================================================

def main():
    print("=" * 60)
    print("15_build_loads_2024.py -- 2024 hourly demand by bus")
    print("=" * 60)

    for f in [DDA_FILE, BUSES_FILE, LINES_FILE]:
        if not os.path.isfile(f):
            print(f"[ERROR] File not found:\n  {f}")
            sys.exit(1)

    # Compute fusion_map upfront to apply it in step 4
    buses_df = pd.read_csv(BUSES_FILE)
    lines_df = pd.read_csv(LINES_FILE)
    fusion_map = compute_fusion_map(buses_df, lines_df)
    print(f"  Fused buses detected: {len(fusion_map)}")

    # =========================================================
    # 1. PARSE HEADER — build datetime index
    # =========================================================
    print("\n[1/5] Parsing header ...")

    header_raw = pd.read_csv(
        DDA_FILE,
        sep=";",
        encoding="latin-1",
        header=None,
        nrows=4,
    )

    # Extract date and hour vectors for the value columns
    row_hour = header_raw.iloc[0, N_META_COLS:].astype(str).tolist()
    row_date = header_raw.iloc[2, N_META_COLS:].astype(str).tolist()

    timestamps = build_datetimes(row_date, row_hour)
    n_hours = len(timestamps)

    print(f"  Hours in file       : {n_hours}")
    print(f"  Range               : {timestamps[0]}  ->  {timestamps[-1]}")

    if n_hours != 8784:
        print("  [WARNING] Expected 8784 hours (leap year 2024)")

    n_nat = sum(1 for ts in timestamps if pd.isna(ts))
    if n_nat > 0:
        print(f"  [WARNING] {n_nat} NaT timestamps — check header")

    # =========================================================
    # 2. READ DATA BODY
    # =========================================================
    print("\n[2/5] Reading data body ...")

    # Column names: metadata from row 4 + timestamps for the remaining columns
    col_names_meta = header_raw.iloc[3, :N_META_COLS].tolist()
    col_names_hours = [str(ts) for ts in timestamps]

    # The file may contain trailing empty columns — add dummy names to align
    n_file_cols = pd.read_csv(
        DDA_FILE,
        sep=";",
        encoding="latin-1",
        header=None,
        nrows=1,
    ).shape[1]

    n_dummy = n_file_cols - N_META_COLS - len(col_names_hours)
    col_names_dummy = [f"_dummy_{i}" for i in range(n_dummy)]
    col_names = col_names_meta + col_names_hours + col_names_dummy

    df = pd.read_csv(
        DDA_FILE,
        sep=";",
        encoding="latin-1",
        header=None,
        skiprows=4,
        names=col_names,
        low_memory=False,
    )

    # Drop trailing empty row if present
    df = df.dropna(subset=["trafo_id"])
    df["trafo_id"] = df["trafo_id"].astype(int)
    df["bus_id"] = pd.to_numeric(df["bus_id"], errors="coerce").astype("Int64")

    print(f"  Transformers read   : {len(df)}")
    print(f"  Unique bus_id       : {df['bus_id'].nunique()}")

    # =========================================================
    # 3. PIVOT TO LONG FORMAT
    # =========================================================
    print("\n[3/5] Pivoting to long format ...")

    # Convert hourly columns to numeric
    hour_cols = col_names_hours
    df[hour_cols] = df[hour_cols].apply(pd.to_numeric, errors="coerce")

    # Melt: one row per transformer per hour
    df_long = df[COLS_META + hour_cols].melt(
        id_vars=COLS_META,
        var_name="datetime",
        value_name="p_mw",
    )

    df_long["datetime"] = pd.to_datetime(
        df_long["datetime"], errors="coerce"
    ).dt.strftime("%d/%m/%Y %H:%M")

    print(f"  Rows after melt     : {len(df_long):,}")

    # =========================================================
    # 4. GROUP BY BUS + DATETIME
    # =========================================================
    # Apply fusion_map: redirect demand from fused buses to the representative.
    # bus_name is remapped and bus_id updated to the representative bus_id
    # so the groupby consolidates demand correctly.
    name_to_id = dict(zip(buses_df["bus_name"], buses_df["bus_id"]))
    df_long["bus_name"] = df_long["bus_name"].map(lambda x: fusion_map.get(x, x))
    df_long["bus_id"] = df_long["bus_name"].map(name_to_id)

    print("\n[4/5] Grouping by bus_id + datetime ...")

    loads = (
        df_long
        .groupby(["bus_id", "bus_name", "datetime"], as_index=False)["p_mw"]
        .sum()
    )

    loads["_sort"] = pd.to_datetime(loads["datetime"], format="%d/%m/%Y %H:%M")
    loads = (
        loads
        .sort_values(["bus_id", "_sort"])
        .drop(columns="_sort")
        .reset_index(drop=True)
    )

    print(f"  Output rows         : {len(loads):,}")
    print(f"  Unique buses        : {loads['bus_id'].nunique()}")
    print(f"  Unique hours        : {loads['datetime'].nunique()}")
    print(f"  Average p_mw        : {loads['p_mw'].mean():,.1f} MW")

    # =========================================================
    # 5. VERIFY COVERAGE
    # Compare against 500 kV buses present in the network
    # (excluding fused buses that disappear from the network).
    # =========================================================
    print("\n[5/5] Verifying coverage ...")

    buses_500_names = set(
        buses_df[buses_df["baskv_kv"] == 500]["bus_name"]
    ) - set(fusion_map.keys())

    load_bus_names = set(loads["bus_name"].unique())

    in_network_without_load = buses_500_names - load_bus_names
    in_load_file_not_in_network = load_bus_names - buses_500_names

    print(f"  500 kV buses in network      : {len(buses_500_names)}")
    print(f"  Buses with load in DDA       : {len(load_bus_names)}")

    if in_network_without_load:
        print(f"  [WARNING] Buses in network without load: {len(in_network_without_load)}")
        for bus_name in sorted(in_network_without_load)[:10]:
            print(f"    {bus_name}")
    else:
        print("  All network buses have load  OK")

    if in_load_file_not_in_network:
        print(f"  [WARNING] Buses in DDA not found in network: {len(in_load_file_not_in_network)}")
        for bus_name in sorted(in_load_file_not_in_network)[:10]:
            print(f"    {bus_name}")

    # =========================================================
    # EXPORT
    # =========================================================
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    loads.to_csv(OUTPUT_FILE, index=False)

    print(f"\n{'=' * 60}")
    print(f"  Output: {OUTPUT_FILE}")
    print(f"  Rows  : {len(loads):,}")
    print(f"  Buses : {loads['bus_id'].nunique()}")
    print(f"{'=' * 60}")
    print("Next: 16_snapshot_dc_pico2024.py")


if __name__ == "__main__":
    main()