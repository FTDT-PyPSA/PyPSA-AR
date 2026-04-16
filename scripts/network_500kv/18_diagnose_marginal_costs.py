"""
18_diagnose_marginal_costs.py
Diagnoses marginal cost coverage for generators_2024.csv.

Checks which generators in generators_2024.csv have marginal cost data available
in CAMMESA source files, separating by technology type.

Analysis groups:

    - Hydro:
        data pending, no automatic match attempted

    - Thermal and nuclear:
        matched against CVP_Termica.csv with fuel selection logic
        Filter: Año inicio = 2026, Semana inicio = 1
        Direct match by reduced key: first 4 characters + last 2 digits
        Fuel priority:
            1) GN
            2) if GN is not available and there is only one tipo_comb, use it
            3) if only FO and GO are available, use FO
        If no direct match:
            fallback average using first 6 characters

    - Renewables:
        match by geosadi_name against Proyecto in CVP_renovar.csv
        Proyecto is normalized by removing accents and converting to uppercase

Inputs:
    data/network_500kv/generators_2024.csv
    external_data_dir/marginal_cost/CVP_Termica.csv (external — download from GitHub Releases, place in external_data_dir/marginal_cost/)
    external_data_dir/marginal_cost/CVP_renovar.csv (external — download from GitHub Releases, place in external_data_dir/marginal_cost/)

Output:
    data/network_500kv/marginal_costs_diagnostic.csv

    Columns:
        bus_name_origen, geosadi_name, nemo, carrier, p_nom,
        marginal_cost_match, cost_source, CVP_manual

Run from the repository root (pypsa-ar-base/):
    python scripts/network_500kv/18_diagnose_marginal_costs.py
"""

import os
import sys
import unicodedata
from pathlib import Path

import pandas as pd
import yaml

# =============================================================================
# CONFIGURATION
# =============================================================================

_cfg = yaml.safe_load(open(Path(__file__).parents[2] / "config.yaml"))
REPO_DIR = Path(_cfg["repo_dir"])
EXTERNAL_DIR = Path(_cfg["external_data_dir"])

GEN_FILE = REPO_DIR / "data/network_500kv/generators_2024.csv"
THERMAL_FILE = EXTERNAL_DIR / "marginal_cost/CVP_Termica.csv"
RENOVAR_FILE = EXTERNAL_DIR / "marginal_cost/CVP_renovar.csv"
OUTPUT_FILE = REPO_DIR / "data/network_500kv/marginal_costs_diagnostic.csv"

HYDRO_CARRIERS = {"hydro", "pumped_hydro"}
THERMAL_CARRIERS = {"ocgt", "ccgt", "steam", "diesel", "nuclear"}
RENOVAR_CARRIERS = {"wind", "solar", "biomass", "biogas"}


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def normalize_text(value):
    if pd.isna(value):
        return ""
    text = str(value).strip().upper()
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return text


def build_thermal_key(value):
    if pd.isna(value):
        return ""
    text = str(value).strip().upper()
    if len(text) < 6:
        return text
    return text[:4] + text[-2:]


def prefix_6(value):
    if pd.isna(value):
        return ""
    text = str(value).strip().upper()
    return text[:6]


def select_fuel_type(group):
    fuels = sorted(
        fuel
        for fuel in group["tipo_comb"].dropna().astype(str).str.strip().str.upper().unique()
        if fuel != ""
    )

    if "GN" in fuels:
        return "GN"

    if len(fuels) == 1:
        return fuels[0]

    if set(fuels) == {"FO", "GO"}:
        return "FO"

    return None


# =============================================================================
# MAIN
# =============================================================================

def main():
    print("=" * 60)
    print("18_diagnose_marginal_costs.py")
    print("=" * 60)

    for file_path in [GEN_FILE, THERMAL_FILE, RENOVAR_FILE]:
        if not os.path.isfile(file_path):
            print(f"[ERROR] File not found: {file_path}")
            sys.exit(1)

    # =========================================================================
    # STEP 1 — Read generators_2024
    # =========================================================================

    gen = pd.read_csv(GEN_FILE)

    cols_base = ["bus_name_origen", "geosadi_name", "nemo", "carrier", "p_nom"]
    gen = gen[cols_base].copy()

    gen["marginal_cost_match"] = "NO"
    gen["cost_source"] = ""
    gen["CVP_manual"] = ""

    print(f"\nTotal units: {len(gen)}")

    # =========================================================================
    # STEP 2 — Prepare thermal CVP
    # =========================================================================

    thermal_raw = pd.read_csv(THERMAL_FILE, encoding="latin-1")
    thermal_raw.columns = thermal_raw.columns.str.strip()

    thermal = thermal_raw[
        (thermal_raw["Año inicio"] == 2026) &
        (thermal_raw["Semana inicio"] == 1)
    ].copy()

    thermal["Maquina"] = thermal["Máquina"].astype(str).str.strip().str.upper()
    thermal["thermal_key"] = thermal["Maquina"].apply(build_thermal_key)
    thermal["prefix_6"] = thermal["Maquina"].apply(prefix_6)
    thermal["tipo_comb"] = thermal["Tipo_Comb"].astype(str).str.strip().str.upper()

    thermal_lookup = {}
    thermal_average_lookup = {}

    for key, group in thermal.groupby("thermal_key"):
        selected_fuel = select_fuel_type(group)
        if selected_fuel is None:
            continue

        selected_group = group[group["tipo_comb"] == selected_fuel].copy()
        selected_row = selected_group.sort_values("CVP_Total_Utilizado").iloc[0]

        thermal_lookup[key] = {
            "tipo_comb": selected_fuel,
            "cost": selected_row["CVP_Total_Utilizado"],
            "maquina": selected_row["Maquina"],
        }

    for pref6, group in thermal.groupby("prefix_6"):
        selected_fuel = select_fuel_type(group)
        if selected_fuel is None:
            continue

        selected_group = group[group["tipo_comb"] == selected_fuel].copy()

        thermal_average_lookup[pref6] = {
            "tipo_comb": selected_fuel,
            "average_cost": selected_group["CVP_Total_Utilizado"].mean(),
        }

    # =========================================================================
    # STEP 3 — Prepare renovar CVP
    # =========================================================================

    renovar_raw = pd.read_csv(RENOVAR_FILE, encoding="latin-1")
    renovar_raw.columns = renovar_raw.columns.str.strip()

    renovar_raw["Proyecto_norm"] = renovar_raw["Proyecto"].apply(normalize_text)
    renovar_projects = set(renovar_raw["Proyecto_norm"])

    # =========================================================================
    # STEP 4 — Match
    # =========================================================================

    thermal_matches = 0
    renovar_matches = 0
    pending = 0

    for idx, row in gen.iterrows():
        carrier = row["carrier"]

        if carrier in HYDRO_CARRIERS:
            gen.at[idx, "marginal_cost_match"] = "PENDING"
            pending += 1
            continue

        if carrier in THERMAL_CARRIERS:
            thermal_key = build_thermal_key(row["bus_name_origen"])
            pref6 = prefix_6(row["bus_name_origen"])

            if thermal_key in thermal_lookup:
                gen.at[idx, "marginal_cost_match"] = "YES"
                gen.at[idx, "cost_source"] = "CVP_THERMAL"
                thermal_matches += 1

            elif pref6 in thermal_average_lookup:
                gen.at[idx, "marginal_cost_match"] = "YES"
                gen.at[idx, "cost_source"] = "CVP_THERMAL_AVERAGE"
                thermal_matches += 1

        elif carrier in RENOVAR_CARRIERS:
            project_name = normalize_text(row["geosadi_name"])

            if project_name in renovar_projects:
                gen.at[idx, "marginal_cost_match"] = "YES"
                gen.at[idx, "cost_source"] = "CVP_RENOVAR"
                renovar_matches += 1

    # =========================================================================
    # STEP 5 — Report
    # =========================================================================

    total_yes = (gen["marginal_cost_match"] == "YES").sum()
    total_no = (gen["marginal_cost_match"] == "NO").sum()
    total_pending = (gen["marginal_cost_match"] == "PENDING").sum()

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"  With cost      : {total_yes}")
    print(f"  Without cost   : {total_no}")
    print(f"  Pending        : {total_pending}")
    print(f"  Thermal match  : {thermal_matches}")
    print(f"  Renovar match  : {renovar_matches}")
    print("=" * 60)

    # =========================================================================
    # STEP 6 — Export
    # =========================================================================

    os.makedirs(OUTPUT_FILE.parent, exist_ok=True)
    gen.to_csv(OUTPUT_FILE, index=False)

    print(f"\nOutput: {OUTPUT_FILE}")
    print("Next: 18b_build_marginal_costs_2024.py")
    print("=" * 60)


if __name__ == "__main__":
    main()