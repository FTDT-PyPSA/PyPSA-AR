"""
16_snapshot_dc_peak2024.py
Linearized DC power flow on the 2024 peak-demand snapshot.

Snapshot: 2024-02-01 14:00

Inputs:
    networks/network_500kv.nc
    data/network_500kv/generators_2024.csv
    data/network_500kv/loads_2024.csv
    external_data_dir/valores_2024_clean.csv

Output:
    Console report (no file output).

Generation logic:
    For each unit in the model, energy_mwh is assigned at the snapshot
    using the same matching logic as script 14:

    Direct match (bus_name_origen exists as unit in CAMMESA):
        p_set = energy_mwh of that unit at the snapshot timestamp.

    No direct match (e.g. Yacyreta — unit is the whole plant):
        All units of that plant (via nemo4/code) are summed and distributed
        proportionally to p_nom across model units.

    Units without CAMMESA data at that timestamp: p_set = 0.

Load logic:
    p_set per bus = value from loads_2024.csv at snapshot timestamp.

DC flow:
    n.lpf() — linearized DC flow using line/transformer reactances.
    No losses are computed.

Report:
    - Generation vs demand balance
    - Generation mix by technology (thermal aggregated)
    - Top 10 most loaded lines (% loading)
    - Extreme nodal angles (network stress indicator)

Run from the repository root (pypsa-ar-base/):
    python scripts/network_500kv/16_snapshot_dc_peak2024.py
"""

import os
import sys
from pathlib import Path

import pandas as pd
import numpy as np
import pypsa
import yaml

# =============================================================================
# CONFIGURATION
# =============================================================================

_cfg = yaml.safe_load(open(Path(__file__).parents[2] / "config.yaml"))
REPO_DIR = Path(_cfg["repo_dir"])
EXTERNAL_DIR = Path(_cfg["external_data_dir"])

NETWORK_FILE = REPO_DIR / "networks/network_500kv.nc"
GEN_FILE = REPO_DIR / "data/network_500kv/generators_2024.csv"
LOADS_FILE = REPO_DIR / "data/network_500kv/loads_2024.csv"
VALORES_FILE = EXTERNAL_DIR / "valores_2024_clean.csv"

# Peak demand timestamp — format DD/MM/YYYY HH:MM
SNAPSHOT = "01/02/2024 14:00"

# Carriers grouped as thermal in report
THERMAL_CARRIERS = {"steam", "ocgt", "ccgt", "diesel"}


# =============================================================================
# STEP 1 — Extract generation from snapshot
# =============================================================================

def extract_snapshot_generation():
    """
    Reads valores_2024_clean.csv and extracts energy_mwh by unit at the peak snapshot.

    Returns:
        energy_by_group  — dict {unit: energy_mwh}
        plant_by_group   — dict {unit: code}
        df_peak          — filtered snapshot DataFrame
    """
    print("\n[1/5] Extracting generation from snapshot ...")

    df = pd.read_csv(
        VALORES_FILE,
        usecols=[
            "datetime",
            "unit",
            "code",
            "carrier",
            "energy_mwh",
            "flag_outlier",
        ],
        low_memory=False,
    )

    df_peak = df[df["datetime"] == SNAPSHOT].copy()

    print(f"  Groups in snapshot       : {len(df_peak)}")
    print(f"  Total CAMMESA generation: {df_peak['energy_mwh'].sum():,.1f} MW")

    outliers = df_peak["flag_outlier"].sum()
    if outliers > 0:
        print(f"  [WARNING] {outliers} groups flagged as outliers")

    energy_by_group = df_peak.set_index("unit")["energy_mwh"].to_dict()
    plant_by_group = df_peak.set_index("unit")["code"].to_dict()

    return energy_by_group, plant_by_group, df_peak


# =============================================================================
# STEP 2 — Map generation to model units
# =============================================================================

def map_generation(gen, energy_by_group, plant_by_group):
    """
    Assigns p_set to each model unit using the same logic as script 14:
        - Direct match: unit == bus_name_origen
        - No direct match: distribute plant energy by p_nom

    Returns:
        DataFrame with p_set and match_snapshot columns added.
    """
    print("\n[2/5] Mapping generation to model units ...")

    available_groups = set(energy_by_group.keys())

    # Build plant -> groups mapping
    plant_to_groups = {}
    for group, plant in plant_by_group.items():
        if plant not in plant_to_groups:
            plant_to_groups[plant] = []
        plant_to_groups[plant].append(group)

    gen = gen.copy()
    gen["nemo4"] = gen["nemo"].fillna("").str[:4].str.strip()

    # Total p_nom by nemo4 for proportional distribution
    pnom_total = gen.groupby("nemo4")["p_nom"].sum().to_dict()

    p_set_values = []
    match_types = []

    for _, row in gen.iterrows():
        bus_origen = row["bus_name_origen"]
        nemo4 = row["nemo4"]
        p_nom = row["p_nom"]

        # Direct unit match
        if bus_origen in available_groups:
            value = energy_by_group[bus_origen]
            match_types.append("direct")

        # No direct match: distribute plant energy proportionally by p_nom
        elif nemo4 in plant_to_groups:
            plant_groups = plant_to_groups[nemo4]
            plant_energy = sum(energy_by_group.get(g, 0) for g in plant_groups)
            total_pnom = pnom_total.get(nemo4, 0)
            value = plant_energy * (p_nom / total_pnom) if total_pnom > 0 else 0.0
            match_types.append("distributed")

        else:
            value = 0.0
            match_types.append("no_data")

        p_set_values.append(max(value, 0.0))

    gen["p_set"] = p_set_values
    gen["match_snapshot"] = match_types

    print(f"  Direct matches     : {match_types.count('direct')}")
    print(f"  Distributed matches: {match_types.count('distributed')}")
    print(f"  No data            : {match_types.count('no_data')}")
    print(f"  Total p_set model  : {gen['p_set'].sum():,.1f} MW")

    return gen


# =============================================================================
# STEP 3 — Load snapshot into network and run LPF
# =============================================================================

def run_lpf(n, gen, snapshot_loads):
    """
    Loads generators and loads into the network at the snapshot
    and runs linearized DC power flow.
    """
    print("\n[3/5] Loading snapshot into network and running LPF ...")

    snapshot = pd.DatetimeIndex([
        pd.to_datetime(SNAPSHOT, dayfirst=True, format="%d/%m/%Y %H:%M")
    ])
    n.set_snapshots(snapshot)

    # --- Generators ---
    n.generators.drop(n.generators.index, inplace=True)
    n.generators_t.p_set = pd.DataFrame(index=snapshot)

    for _, row in gen.iterrows():
        bus = row.get("bus_conexion500kv_name")
        if pd.isna(bus) or bus not in n.buses.index:
            continue
        if row["p_set"] <= 0:
            continue

        n.add(
            "Generator",
            row["gen_key"],
            bus=bus,
            p_nom=row["p_set"] * 1.1,  # slightly above p_set
            p_set=row["p_set"],
            carrier=row["carrier"],
            marginal_cost=0.0,
        )

    # --- Loads ---
    n.loads.drop(n.loads.index, inplace=True)
    n.loads_t.p_set = pd.DataFrame(index=snapshot)

    for _, row in snapshot_loads.iterrows():
        bus = row.get("bus_name")
        if pd.isna(bus) or bus not in n.buses.index:
            continue
        if row["p_mw"] <= 0:
            continue

        n.add(
            "Load",
            f"load_{bus}",
            bus=bus,
            p_set=row["p_mw"],
        )

    print(f"  Generators loaded : {len(n.generators)}")
    print(f"  Loads loaded      : {len(n.loads)}")
    print(f"  Total generation  : {n.generators['p_set'].sum():,.1f} MW")
    print(f"  Total demand      : {n.loads['p_set'].sum():,.1f} MW")

    # --- Slack bus ---
    # In the Argentine 500 kV network, all generation enters through transformers.
    # Slack is assigned to ATUCHA 2_21kV (bus 2620, nuclear machine terminal),
    # which is the reference bus in the original PSS/E case.
    slack_bus = "ATUCHA 2_21kV"
    if slack_bus in n.buses.index:
        n.buses.loc[slack_bus, "control"] = "Slack"
        print(f"  Slack bus         : {slack_bus}")
    else:
        print(f"  [WARNING] Slack bus {slack_bus} not found — PyPSA will assign it automatically")

    # --- Run LPF ---
    n.lpf()
    print("  LPF completed")

    return n


# =============================================================================
# STEP 4 — Report
# =============================================================================

def report_results(n, gen, df_peak):
    print(f"\n{'=' * 60}")
    print(f"SNAPSHOT DC REPORT — {SNAPSHOT}")
    print(f"{'=' * 60}")

    scheduled_generation = n.generators["p_set"].sum()
    total_demand = n.loads_t.p.sum(axis=1).values[0]
    lpf_generation = n.generators_t.p.sum(axis=1).values[0]
    slack_mw = lpf_generation - scheduled_generation

    print(f"\n  BALANCE")
    print(f"    Scheduled generation : {scheduled_generation:>10,.1f} MW")
    print(f"    Slack injection      : {slack_mw:>10,.1f} MW")
    print(f"    Total demand         : {total_demand:>10,.1f} MW")

    # --- Top 3 non-represented sources in CAMMESA (only if slack > 0) ---
    if slack_mw > 0:
        direct_groups = set(gen["bus_name_origen"].astype(str).str.strip())
        model_nemo4 = set(gen["nemo"].astype(str).str[:4].str.strip())

        df_peak_pos = df_peak[df_peak["energy_mwh"] > 0].copy()
        df_peak_pos["nemo4"] = df_peak_pos["code"].astype(str).str[:4].str.strip()
        df_peak_pos["in_model"] = (
            df_peak_pos["unit"].isin(direct_groups) |
            df_peak_pos["nemo4"].isin(model_nemo4)
        )

        outside_model = (
            df_peak_pos[~df_peak_pos["in_model"]]
            .sort_values("energy_mwh", ascending=False)
            .head(3)
        )

        if len(outside_model) > 0:
            print(f"\n  TOP 3 SOURCES NOT REPRESENTED IN THE MODEL")
            for _, row in outside_model.iterrows():
                note = (
                    " (Energy import from neighboring country, not modeled at this stage)"
                    if row["carrier"] == "international_import"
                    else ""
                )
                print(
                    f"    {row['unit']:<12} {row['code']:<6} "
                    f"{row['energy_mwh']:>8,.1f} MW{note}"
                )

    # --- Generation mix by technology ---
    print(f"\n  GENERATION MIX BY TECHNOLOGY")

    gen_dispatch = n.generators_t.p.iloc[0]
    gen_df = n.generators[["carrier"]].copy()
    gen_df["p_dispatch"] = gen_dispatch

    def group_carrier(carrier):
        if carrier in THERMAL_CARRIERS:
            return "thermal"
        return carrier

    gen_df["technology"] = gen_df["carrier"].apply(group_carrier)
    mix = gen_df.groupby("technology")["p_dispatch"].sum().sort_values(ascending=False)

    for tech, mw in mix.items():
        pct = 100 * mw / scheduled_generation if scheduled_generation > 0 else 0
        print(f"    {tech:<15}: {mw:>8,.1f} MW  ({pct:>5.1f}%)")

    # --- Top 10 most loaded lines ---
    print(f"\n  TOP 10 MOST LOADED LINES")

    p0 = n.lines_t.p0.iloc[0].abs()
    s_nom = n.lines["s_nom"].replace(0, np.nan)
    loading = (p0 / s_nom * 100).dropna().sort_values(ascending=False)

    print(f"    {'Line':<30} {'Flow MW':>10} {'Cap MW':>10} {'Load %':>8}")
    for line, pct in loading.head(10).items():
        flow = p0[line]
        cap = n.lines.loc[line, "s_nom"]
        print(f"    {line:<30} {flow:>10,.1f} {cap:>10,.1f} {pct:>8.1f}%")

    # --- Extreme nodal angles ---
    print(f"\n  EXTREME NODAL ANGLES (network stress indicator)")

    angles = n.buses_t.v_ang.iloc[0] * (180 / np.pi)
    angles = angles.sort_values()

    print(f"    {'Bus':<20} {'Angle (deg)':>14}")
    for bus, angle in list(angles.head(5).items()) + list(angles.tail(5).items()):
        print(f"    {bus:<20} {angle:>14.2f}")

    angle_max = angles.max()
    angle_min = angles.min()
    print(f"\n    Angle range: {angle_min:.2f} deg  to  {angle_max:.2f} deg")
    if abs(angle_max - angle_min) > 30:
        print(f"    [WARNING] Angle spread > 30 deg — possible severe network stress")


# =============================================================================
# MAIN
# =============================================================================

def main():
    print("=" * 60)
    print("16_snapshot_dc_peak2024.py -- DC flow peak demand 2024")
    print("=" * 60)

    for f in [NETWORK_FILE, GEN_FILE, LOADS_FILE, VALORES_FILE]:
        if not os.path.isfile(f):
            print(f"[ERROR] File not found:\n  {f}")
            sys.exit(1)

    # Load network
    print("\nLoading network_500kv.nc ...")
    n = pypsa.Network(NETWORK_FILE)
    print(f"  Buses: {len(n.buses)}  Lines: {len(n.lines)}  Transformers: {len(n.transformers)}")

    # Load model generators
    gen = pd.read_csv(GEN_FILE)

    # Load snapshot demand
    loads = pd.read_csv(LOADS_FILE)
    snapshot_loads = loads[loads["datetime"] == SNAPSHOT][["bus_id", "bus_name", "p_mw"]].copy()
    print(f"\nDemand at snapshot: {snapshot_loads['p_mw'].sum():,.1f} MW  ({len(snapshot_loads)} buses)")

    # Steps
    energy_by_group, plant_by_group, df_peak = extract_snapshot_generation()
    gen = map_generation(gen, energy_by_group, plant_by_group)
    n = run_lpf(n, gen, snapshot_loads)
    report_results(n, gen, df_peak)

    print("\n" + "=" * 60)
    print("Next: 17_build_gen_profiles_2024.py")


if __name__ == "__main__":
    main()