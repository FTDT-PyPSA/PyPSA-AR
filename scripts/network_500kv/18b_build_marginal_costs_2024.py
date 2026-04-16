"""
18b_build_marginal_costs_2024.py
Builds the final marginal cost table for generators_2024.csv using the
completed diagnostic file plus CAMMESA source files.

Inputs:
    data/network_500kv/generators_2024.csv
    data/network_500kv/marginal_costs_diagnostic_completed.csv
    external_data_dir/marginal_cost/CVP_Termica.csv
    external_data_dir/marginal_cost/CVP_renovar.csv

Output:
    data/network_500kv/marginal_costs_2024.csv

    Columns:
        gen_key, bus_name_origen, geosadi_name, nemo,
        bus_conexion500kv, bus_conexion500kv_name,
        carrier, p_nom, lat, lon,
        marginal_cost

Run from the repository root (pypsa-ar-base/):
    python scripts/network_500kv/18b_build_marginal_costs_2024.py
"""

import os
import sys
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

# =============================================================================
# CONFIGURATION
# =============================================================================

_cfg = yaml.safe_load(open(Path(__file__).parents[2] / "config.yaml"))
REPO_DIR = Path(_cfg["repo_dir"])
EXTERNAL_DIR = Path(_cfg["external_data_dir"])

GEN_FILE = REPO_DIR / "data/network_500kv/generators_2024.csv"
DIAG_FILE = REPO_DIR / "data/network_500kv/marginal_costs_diagnostic_completed.csv"
THERMAL_FILE = EXTERNAL_DIR / "marginal_cost/CVP_Termica.csv"
RENOVAR_FILE = EXTERNAL_DIR / "marginal_cost/CVP_renovar.csv"
OUTPUT_FILE = REPO_DIR / "data/network_500kv/marginal_costs_2024.csv"

THERMAL_CARRIERS = {"ocgt", "ccgt", "steam", "diesel", "nuclear"}
RENOVAR_CARRIERS = {"wind", "solar", "biomass", "biogas"}
HYDRO_CARRIERS = {"hydro", "pumped_hydro"}

MONTH_COLS_2024 = [
    "Jan-24", "Feb-24", "Mar-24", "Apr-24", "May-24", "Jun-24",
    "Jul-24", "Aug-24", "Sep-24", "Oct-24", "Nov-24", "Dec-24",
]

OUTPUT_COLS = [
    "gen_key",
    "bus_name_origen",
    "geosadi_name",
    "nemo",
    "bus_conexion500kv",
    "bus_conexion500kv_name",
    "carrier",
    "p_nom",
    "lat",
    "lon",
    "marginal_cost",
]

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


def parse_number(value):
    if pd.isna(value):
        return np.nan
    text = str(value).strip()
    if text == "":
        return np.nan
    text = text.replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return np.nan


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
        for fuel in group["Tipo_Comb"].dropna().astype(str).str.strip().str.upper().unique()
        if fuel != ""
    )

    if "GN" in fuels:
        return "GN"

    if len(fuels) == 1:
        return fuels[0]

    if set(fuels) == {"FO", "GO"}:
        return "FO"

    return None


def build_thermal_lookups(thermal):
    lookup_machine = {}
    lookup_direct = {}
    lookup_average = {}

    for machine, group in thermal.groupby("Maquina"):
        selected_fuel = select_fuel_type(group)
        if selected_fuel is None:
            continue

        selected_group = group[group["Tipo_Comb"] == selected_fuel].copy()
        selected_row = selected_group.sort_values("CVP_Total_Utilizado").iloc[0]

        lookup_machine[machine] = {
            "tipo_comb": selected_fuel,
            "cost": float(selected_row["CVP_Total_Utilizado"]),
        }

    for key, group in thermal.groupby("thermal_key"):
        selected_fuel = select_fuel_type(group)
        if selected_fuel is None:
            continue

        selected_group = group[group["Tipo_Comb"] == selected_fuel].copy()
        selected_row = selected_group.sort_values("CVP_Total_Utilizado").iloc[0]

        lookup_direct[key] = {
            "tipo_comb": selected_fuel,
            "cost": float(selected_row["CVP_Total_Utilizado"]),
        }

    for pref6, group in thermal.groupby("prefix_6"):
        selected_fuel = select_fuel_type(group)
        if selected_fuel is None:
            continue

        selected_group = group[group["Tipo_Comb"] == selected_fuel].copy()

        lookup_average[pref6] = {
            "tipo_comb": selected_fuel,
            "cost": float(selected_group["CVP_Total_Utilizado"].mean()),
        }

    return lookup_machine, lookup_direct, lookup_average


def build_renovar_lookup(renovar):
    renovar = renovar.copy()
    renovar["Proyecto_norm"] = renovar["Proyecto"].apply(normalize_text)

    for col in MONTH_COLS_2024:
        renovar[col] = pd.to_numeric(renovar[col], errors="coerce")

    renovar["average_cost_2024"] = renovar[MONTH_COLS_2024].mean(axis=1, skipna=True)

    lookup = (
        renovar.groupby("Proyecto_norm", as_index=False)["average_cost_2024"]
        .mean()
        .set_index("Proyecto_norm")["average_cost_2024"]
        .to_dict()
    )

    return lookup


def resolve_thermal_cost_automatic(bus_name_origen, lookup_direct, lookup_average):
    key = build_thermal_key(bus_name_origen)
    pref6 = prefix_6(bus_name_origen)

    if key in lookup_direct:
        return float(lookup_direct[key]["cost"]), "CVP_THERMAL"

    if pref6 in lookup_average:
        return float(lookup_average[pref6]["cost"]), "CVP_THERMAL_AVERAGE"

    return np.nan, ""


def resolve_thermal_cost_manual(machine_manual, lookup_machine):
    machine = str(machine_manual).strip().upper()
    if machine in lookup_machine:
        return float(lookup_machine[machine]["cost"]), "CVP_THERMAL"
    return np.nan, ""


def resolve_renovar_cost(project_name, lookup_renovar):
    project = normalize_text(project_name)
    if project in lookup_renovar:
        return float(lookup_renovar[project]), "CVP_RENOVAR"
    return np.nan, ""


def merge_with_diagnostic(gen, diag):
    diag = diag.copy()

    if "gen_key" in diag.columns:
        return gen.merge(
            diag[["gen_key", "marginal_cost_match", "cost_source", "CVP_manual"]],
            on="gen_key",
            how="left",
        )

    merge_cols = [
        c for c in ["bus_name_origen", "geosadi_name", "nemo", "carrier", "p_nom"]
        if c in diag.columns
    ]

    if len(merge_cols) == 0:
        print("[ERROR] No sufficient columns found to merge with diagnostic file.")
        sys.exit(1)

    gen = gen.copy()
    diag = diag.copy()

    gen["_merge_idx"] = gen.groupby(merge_cols).cumcount()
    diag["_merge_idx"] = diag.groupby(merge_cols).cumcount()

    merged = gen.merge(
        diag[merge_cols + ["_merge_idx", "marginal_cost_match", "cost_source", "CVP_manual"]],
        on=merge_cols + ["_merge_idx"],
        how="left",
    )

    merged = merged.drop(columns="_merge_idx")
    return merged


# =============================================================================
# MAIN
# =============================================================================

def main():
    print("=" * 60)
    print("18b_build_marginal_costs_2024.py")
    print("=" * 60)

    for file_path in [GEN_FILE, DIAG_FILE, THERMAL_FILE, RENOVAR_FILE]:
        if not os.path.isfile(file_path):
            print(f"[ERROR] File not found:\n  {file_path}")
            sys.exit(1)

    # =========================================================
    # LOAD INPUTS
    # =========================================================
    gen = pd.read_csv(GEN_FILE)
    diag = pd.read_csv(DIAG_FILE, encoding="latin-1")
    thermal = pd.read_csv(THERMAL_FILE, encoding="latin-1")
    renovar = pd.read_csv(RENOVAR_FILE, encoding="latin-1")

    thermal.columns = thermal.columns.str.strip()
    renovar.columns = renovar.columns.str.strip()

    df = merge_with_diagnostic(gen, diag)

    if "marginal_cost_match" not in df.columns:
        df["marginal_cost_match"] = ""
    if "cost_source" not in df.columns:
        df["cost_source"] = ""
    if "CVP_manual" not in df.columns:
        df["CVP_manual"] = ""

    print(f"\nUnits in generators_2024: {len(df)}")

    # =========================================================
    # PREPARE THERMAL CVP
    # =========================================================
    thermal = thermal[
        (thermal["Año inicio"] == 2026) &
        (thermal["Semana inicio"] == 1)
    ].copy()

    thermal["Maquina"] = thermal["Máquina"].astype(str).str.strip().str.upper()
    thermal["Tipo_Comb"] = thermal["Tipo_Comb"].astype(str).str.strip().str.upper()
    thermal["thermal_key"] = thermal["Maquina"].apply(build_thermal_key)
    thermal["prefix_6"] = thermal["Maquina"].apply(prefix_6)

    lookup_machine, lookup_direct, lookup_average = build_thermal_lookups(thermal)

    # =========================================================
    # PREPARE RENOVAR CVP
    # =========================================================
    missing_months = [c for c in MONTH_COLS_2024 if c not in renovar.columns]
    if len(missing_months) > 0:
        print("[ERROR] Missing 2024 monthly columns in CVP_renovar:")
        print("        " + ", ".join(missing_months))
        sys.exit(1)

    lookup_renovar = build_renovar_lookup(renovar)

    # =========================================================
    # RESOLVE COSTS
    # =========================================================
    costs = []
    final_sources = []

    for _, row in df.iterrows():
        carrier = str(row["carrier"]).strip()
        manual_raw = row.get("CVP_manual", "")
        manual_num = parse_number(manual_raw)

        cost = np.nan
        final_source = ""

        # -----------------------------------------------------
        # 1. NUMERIC MANUAL OVERRIDE
        # -----------------------------------------------------
        if not pd.isna(manual_num):
            cost = float(manual_num)
            final_source = "CVP_MANUAL"

        # -----------------------------------------------------
        # 2. TEXT MANUAL OVERRIDE
        # -----------------------------------------------------
        elif pd.notna(manual_raw) and str(manual_raw).strip() != "":
            manual_txt = str(manual_raw).strip()

            if carrier in THERMAL_CARRIERS:
                cost, final_source = resolve_thermal_cost_manual(manual_txt, lookup_machine)

            elif carrier in RENOVAR_CARRIERS or carrier in HYDRO_CARRIERS:
                cost, final_source = resolve_renovar_cost(manual_txt, lookup_renovar)

        # -----------------------------------------------------
        # 3. AUTOMATIC MATCH
        # -----------------------------------------------------
        if pd.isna(cost):
            if carrier in THERMAL_CARRIERS:
                cost, final_source = resolve_thermal_cost_automatic(
                    row["bus_name_origen"], lookup_direct, lookup_average
                )

            elif carrier in RENOVAR_CARRIERS:
                cost, final_source = resolve_renovar_cost(row["geosadi_name"], lookup_renovar)

        costs.append(cost)
        final_sources.append(final_source)

    df["marginal_cost"] = pd.to_numeric(costs, errors="coerce")
    df["final_cost_source"] = final_sources

    # =========================================================
    # REPORT
    # =========================================================
    with_cost = df["marginal_cost"].notna().sum()

    pending = (
        df["marginal_cost"].isna() &
        (df["marginal_cost_match"].fillna("").astype(str).str.upper() == "PENDING")
    ).sum()

    without_cost = (
        df["marginal_cost"].isna() &
        ~(df["marginal_cost_match"].fillna("").astype(str).str.upper() == "PENDING")
    ).sum()

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"  With cost      : {with_cost}")
    print(f"  Without cost   : {without_cost}")
    print(f"  Pending        : {pending}")
    print("=" * 60)

    # =========================================================
    # EXPORT
    # =========================================================
    out = df[OUTPUT_COLS].copy()
    out["marginal_cost"] = pd.to_numeric(out["marginal_cost"], errors="coerce").round(4)

    out.to_csv(OUTPUT_FILE, index=False)

    print(f"\nOutput: {OUTPUT_FILE}  ({len(out)} rows)")
    print("=" * 60)
    print("Next: 19_run_optimization.py")


if __name__ == "__main__":
    main()