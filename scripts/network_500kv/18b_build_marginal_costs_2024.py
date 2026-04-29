"""
18b_build_marginal_costs_2024.py
Builds the final marginal cost table for generators_2024.csv using the
completed diagnostic file plus CAMMESA source files. Also attaches the
machine-level efficiency and net heat rate from the CAMMESA efficiency
table when a match by bus_name_origen is available.

Inputs:
    data/network_500kv/generators_2024.csv
    data/network_500kv/marginal_costs_diagnostic_completed.csv
    external_data_dir/marginal_cost/CVP_Termica.csv (external — download from GitHub Releases, place in external_data_dir/marginal_cost/)
    external_data_dir/marginal_cost/CVP_renovar.csv (external — download from GitHub Releases, place in external_data_dir/marginal_cost/)
    external_data_dir/efficencies.xlsx              (external — download from GitHub Releases, place in external_data_dir/) 

Output:
    data/network_500kv/marginal_costs_2024.csv

    Columns:
        gen_key, bus_name_origen, geosadi_name, nemo,
        bus_conexion500kv, bus_conexion500kv_name,
        carrier, p_nom, lat, lon,
        marginal_cost,
        efficiency, heat_rate_kcal_per_kwh, efficiency_fuel

Efficiency lookup logic:
    Match is exact: bus_name_origen <-> GENERADOR column in the Excel.
    When a machine has multiple fuel rows in the Excel, the fuel is chosen
    using the same hierarchy as in CVP_Termica:
        1) GN if available
        2) FO if GN is absent
        3) GO if neither GN nor FO are available
    Other fuels (CM, U2, UA, UE, etc.) are not used.

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
EFFICIENCY_FILE = EXTERNAL_DIR / "efficencies.xlsx"
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
    "efficiency",
    "heat_rate_kcal_per_kwh",
    "efficiency_fuel",
    "efficiency_source",
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


def select_efficiency_fuel(group):
    """Picks the fuel type to use for a given machine in the efficiency table.
    Same hierarchy as in the CVP_Termica logic, restricted to the three
    fuels that matter for thermal generation cost/efficiency analysis:
        1) GN if available
        2) FO if GN is not available and FO is present
        3) GO if neither GN nor FO is available
        4) None if the machine has only other fuels (CM, U2, UA, UE, etc.).
           Those rows are dropped because we don't model coal/uranium-driven
           efficiency through this path.
    """
    fuels = sorted(
        f
        for f in group["COMBUSTIBLE"].dropna().astype(str).str.strip().str.upper().unique()
        if f != ""
    )
    if "GN" in fuels:
        return "GN"
    if "FO" in fuels:
        return "FO"
    if "GO" in fuels:
        return "GO"
    return None


def build_efficiency_lookup(eff_df):
    """Builds a dict: GENERADOR -> {fuel, efficiency, heat_rate} using the
    fuel hierarchy GN > FO > GO. Machines whose only fuels are coal/uranium/
    other are skipped and won't appear in the lookup."""
    lookup = {}
    for machine, group in eff_df.groupby("GENERADOR"):
        fuel = select_efficiency_fuel(group)
        if fuel is None:
            continue
        row = group[group["COMBUSTIBLE"] == fuel].iloc[0]
        eff_value = float(row["Eficiencia (%)"])
        heat_rate = float(row["C.E.NETO (kcal/kWh)"])
        lookup[str(machine).strip().upper()] = {
            "fuel"      : fuel,
            "efficiency": eff_value,
            "heat_rate" : heat_rate,
        }
    return lookup


def build_cc_lookup(eff_df):
    """Builds a per-plant combined-cycle (CC) lookup: prefix_4 -> {fuel,
    efficiency, heat_rate}. The prefix is the first 4 chars of GENERADOR
    (e.g. 'ACAJ' from 'ACAJCC01').

    Used to handle the physical reality that in Argentina many gas plants
    are combined cycles where the gas turbines (TG) and the recovery steam
    turbine (TV) operate together as a single CC. CAMMESA reports each TG
    individually with its own (lower) open-cycle efficiency, but those TGs
    never operate alone — they always feed the TV. So when a plant has any
    'XXXXCC??' record in the table, every TG and TV at that plant
    physically belongs to the CC and should inherit the CC efficiency
    and heat rate.

    When multiple CC records exist with different values (a few plants
    have e.g. CC25 and CC26 with slightly different efficiencies), the
    most efficient one (lowest heat rate) is picked as representative —
    this corresponds to the most modern equipment.

    Fuel hierarchy GN > FO > GO is the same as for individual machines.
    """
    eff_df = eff_df.copy()
    eff_df["GENERADOR_clean"] = eff_df["GENERADOR"].astype(str).str.strip().str.upper()
    eff_df["prefix_4"]        = eff_df["GENERADOR_clean"].str[:4]
    eff_df["unit_type"]       = eff_df["GENERADOR_clean"].str[4:6]

    cc_rows = eff_df[eff_df["unit_type"] == "CC"].copy()
    if cc_rows.empty:
        return {}

    lookup = {}
    for prefix, group in cc_rows.groupby("prefix_4"):
        fuel = select_efficiency_fuel(group)
        if fuel is None:
            continue
        candidates = group[group["COMBUSTIBLE"] == fuel].copy()
        # Pick the row with the lowest heat rate (most efficient unit at
        # the plant). For plants where all CC have identical values this
        # is harmless — any row gives the same result.
        candidates = candidates.sort_values("C.E.NETO (kcal/kWh)")
        row = candidates.iloc[0]
        lookup[prefix] = {
            "fuel"      : fuel,
            "efficiency": float(row["Eficiencia (%)"]),
            "heat_rate" : float(row["C.E.NETO (kcal/kWh)"]),
        }
    return lookup


def resolve_efficiency(bus_name_origen, lookup, cc_lookup):
    """Returns (efficiency, heat_rate, fuel, source) for a generator.

    Resolution order:
        1) If the generator is a TG or TV at a plant that has CC records,
           inherit the CC values (CC_INHERITED).
        2) Otherwise, exact match by bus_name_origen against the
           per-machine table (DIRECT).
        3) Otherwise return (NaN, NaN, "", "").

    Rule 1 reflects the fact that in Argentina TG/TV pairs at CC plants
    physically operate together as a single combined cycle and never as
    standalone open-cycle gas turbines.
    """
    if pd.isna(bus_name_origen):
        return np.nan, np.nan, "", ""
    key       = str(bus_name_origen).strip().upper()
    prefix_4  = key[:4]
    unit_type = key[4:6] if len(key) >= 6 else ""

    # Rule 1 — inherit from plant CC if applicable
    if unit_type in {"TG", "TV"} and prefix_4 in cc_lookup:
        rec = cc_lookup[prefix_4]
        return rec["efficiency"], rec["heat_rate"], rec["fuel"], "CC_INHERITED"

    # Rule 2 — direct match
    if key in lookup:
        rec = lookup[key]
        return rec["efficiency"], rec["heat_rate"], rec["fuel"], "DIRECT"

    return np.nan, np.nan, "", ""


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

    for file_path in [GEN_FILE, DIAG_FILE, THERMAL_FILE, RENOVAR_FILE, EFFICIENCY_FILE]:
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
    efficiency_df = pd.read_excel(EFFICIENCY_FILE, sheet_name="CONS ESP NETO")

    thermal.columns = thermal.columns.str.strip()
    renovar.columns = renovar.columns.str.strip()
    efficiency_df.columns = efficiency_df.columns.str.strip()

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
    # PREPARE EFFICIENCY LOOKUP
    # =========================================================
    # Two lookups are built from the CAMMESA efficiency table:
    #   1) per-machine lookup (GENERADOR -> values), exact name match.
    #   2) per-plant CC lookup (prefix_4 -> values), used to inherit CC
    #      efficiency to all TG/TV units of a plant that has CC records.
    #      This reflects that in Argentina TG/TV pairs always operate as a
    #      combined cycle and never as standalone open-cycle gas turbines.
    # Fuel hierarchy applied in both cases is GN > FO > GO.
    efficiency_lookup = build_efficiency_lookup(efficiency_df)
    cc_lookup         = build_cc_lookup(efficiency_df)
    print(f"  Machines in efficiency lookup : {len(efficiency_lookup)}")
    print(f"  Plants with CC lookup         : {len(cc_lookup)}")

    # =========================================================
    # RESOLVE COSTS
    # =========================================================
    costs = []
    final_sources = []
    efficiencies = []
    heat_rates   = []
    eff_fuels    = []
    eff_sources  = []

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

        # -----------------------------------------------------
        # 4. EFFICIENCY LOOKUP (independent of cost resolution)
        # -----------------------------------------------------
        # Always try to match efficiency by bus_name_origen, regardless of
        # how the marginal_cost was resolved. Returns NaN for generators not
        # present in the CAMMESA efficiency table (typical of hydro, solar,
        # wind, and any thermal not covered). For TG/TV at CC plants the
        # CC efficiency is inherited.
        eff_value, heat_rate, eff_fuel, eff_source = resolve_efficiency(
            row["bus_name_origen"], efficiency_lookup, cc_lookup
        )

        costs.append(cost)
        final_sources.append(final_source)
        efficiencies.append(eff_value)
        heat_rates.append(heat_rate)
        eff_fuels.append(eff_fuel)
        eff_sources.append(eff_source)

    df["marginal_cost"]          = pd.to_numeric(costs, errors="coerce")
    df["final_cost_source"]      = final_sources
    df["efficiency"]             = pd.to_numeric(efficiencies, errors="coerce")
    df["heat_rate_kcal_per_kwh"] = pd.to_numeric(heat_rates, errors="coerce")
    df["efficiency_fuel"]        = eff_fuels
    df["efficiency_source"]      = eff_sources

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

    n_eff_total   = df["efficiency"].notna().sum()
    n_eff_direct  = (df["efficiency_source"] == "DIRECT").sum()
    n_eff_cc      = (df["efficiency_source"] == "CC_INHERITED").sum()

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"  With cost      : {with_cost}")
    print(f"  Without cost   : {without_cost}")
    print(f"  Pending        : {pending}")
    print(f"  With efficiency: {n_eff_total}")
    print(f"    via DIRECT match (own machine)   : {n_eff_direct}")
    print(f"    via CC_INHERITED (plant CC value): {n_eff_cc}")
    print("=" * 60)

    # =========================================================
    # EXPORT
    # =========================================================
    out = df[OUTPUT_COLS].copy()
    out["marginal_cost"]          = pd.to_numeric(out["marginal_cost"], errors="coerce").round(4)
    out["efficiency"]             = pd.to_numeric(out["efficiency"], errors="coerce").round(6)
    out["heat_rate_kcal_per_kwh"] = pd.to_numeric(out["heat_rate_kcal_per_kwh"], errors="coerce").round(2)

    out.to_csv(OUTPUT_FILE, index=False)

    print(f"\nOutput: {OUTPUT_FILE}  ({len(out)} rows)")
    print("=" * 60)
    print("Next: 19_run_optimization.py")


if __name__ == "__main__":
    main()