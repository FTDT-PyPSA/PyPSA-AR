"""
17_build_gen_profiles_2024.py
Builds hourly availability profiles (p_max_pu) for all generator units
in the model for the 8784 hours of 2024.

Inputs:
    external_data_dir/valores_2024_clean.csv
    data/network_500kv/generators_2024.csv

Output:
    external_data_dir/gen_profiles_2024.csv
        Columns: gen_key, bus_conexion500kv_name, carrier, datetime, p_max_pu
        One row per generator unit per hour.

p_max_pu logic:
    Solar, wind, biogas, biomass:
        p_max_pu = energy_mwh / p_nom
        energy_mwh is used because it reflects the meteorological resource
        available in each hour.

    Hydro, pumped_hydro, nuclear:
        p_max_pu = operated_energy_mwh / p_nom
        operated_energy_mwh is used as a realistic upper bound of what the
        system can take from these technologies, without forcing the optimizer
        to dispatch them exactly at that value.

    Remaining technologies (thermal, diesel):
        p_max_pu = available_capacity_mw / p_nom
        available_capacity_mw reflects real hourly availability.

    In all cases the result is clipped between 0 and 1.
    Hours without CAMMESA data: p_max_pu = 0.

Matching unit -> model generator:
    Direct match: bus_name_origen exists as unit in CAMMESA.
        The value is assigned directly to that generator.
    No direct match: the power plant is matched by nemo4/code.
        The plant value is distributed proportionally by p_nom
        across the model generators.

Run from the repository root (pypsa-ar-base/):
    python scripts/network_500kv/17_build_gen_profiles_2024.py
"""

import os
import sys
from pathlib import Path

import pandas as pd
import numpy as np
import yaml

# =============================================================================
# CONFIGURATION
# =============================================================================

_cfg = yaml.safe_load(open(Path(__file__).parents[2] / "config.yaml"))
REPO_DIR = Path(_cfg["repo_dir"])
EXTERNAL_DIR = Path(_cfg["external_data_dir"])

VALORES_FILE = EXTERNAL_DIR / "valores_2024_clean.csv"
GEN_FILE = REPO_DIR / "data/network_500kv/generators_2024.csv"
OUTPUT_FILE = EXTERNAL_DIR / "gen_profiles_2024.csv"

CHUNK_SIZE = 500_000

# Carriers using energy_mwh
CARRIERS_ENERGY = {"solar", "wind", "biogas", "biomass"}

# Carriers using operated_energy_mwh
CARRIERS_OPERATED = {"hydro", "pumped_hydro", "nuclear"}

# All remaining carriers use available_capacity_mw


# =============================================================================
# FUNCTIONS
# =============================================================================

def select_value(df):
    """
    Selects the source value used to compute p_max_pu according to carrier.
    """
    return np.select(
        [
            df["carrier"].isin(CARRIERS_ENERGY),
            df["carrier"].isin(CARRIERS_OPERATED),
        ],
        [
            df["energy_mwh"],
            df["operated_energy_mwh"].fillna(0.0),
        ],
        default=df["available_capacity_mw"],
    )


# =============================================================================
# MAIN
# =============================================================================

def main():
    print("=" * 60)
    print("17_build_gen_profiles_2024.py -- hourly availability profiles 2024")
    print("=" * 60)

    for f in [VALORES_FILE, GEN_FILE]:
        if not os.path.isfile(f):
            print(f"[ERROR] File not found:\n  {f}")
            sys.exit(1)

    # =========================================================
    # LOAD MODEL GENERATORS
    # =========================================================
    gen = pd.read_csv(GEN_FILE)
    gen["nemo4"] = gen["nemo"].astype(str).str[:4].str.strip()
    print(f"\nUnits in model: {len(gen)}")

    cols_gen = [
        "gen_key",
        "bus_conexion500kv_name",
        "carrier",
        "p_nom",
        "bus_name_origen",
        "nemo4",
    ]
    gen = gen[cols_gen].copy()

    pnom_sum = (
        gen.groupby("nemo4")["p_nom"]
        .sum()
        .rename("p_nom_total")
    )
    gen = gen.merge(pnom_sum, on="nemo4", how="left")

    gen["weight"] = gen.apply(
        lambda r: (r["p_nom"] / r["p_nom_total"]) if r["p_nom_total"] > 0 else 0.0,
        axis=1,
    )

    # =========================================================
    # PROCESS IN CHUNKS
    # =========================================================
    print("\nProcessing valores_2024_clean.csv in chunks ...")

    reader = pd.read_csv(
        VALORES_FILE,
        usecols=[
            "datetime",
            "unit",
            "code",
            "energy_mwh",
            "available_capacity_mw",
            "operated_energy_mwh",
            "flag_outlier",
        ],
        chunksize=CHUNK_SIZE,
        low_memory=False,
    )

    first_chunk = True
    n_chunks = 0
    n_rows_out = 0

    for chunk in reader:
        n_chunks += 1

        chunk = chunk[chunk["flag_outlier"] == False].copy()
        chunk["nemo4_code"] = chunk["code"].astype(str).str[:4].str.strip()

        # Direct match
        direct = chunk.merge(
            gen[[
                "gen_key",
                "bus_conexion500kv_name",
                "carrier",
                "p_nom",
                "bus_name_origen",
            ]],
            left_on="unit",
            right_on="bus_name_origen",
            how="inner",
        )

        direct_groups = set(direct["unit"].unique())
        direct_gen_keys = set(direct["gen_key"].unique())
        chunk_unmatched = chunk[~chunk["unit"].isin(direct_groups)]

        # Distributed match by nemo4/code
        distributed = chunk_unmatched.merge(
            gen[[
                "gen_key",
                "bus_conexion500kv_name",
                "carrier",
                "p_nom",
                "nemo4",
                "weight",
            ]],
            left_on="nemo4_code",
            right_on="nemo4",
            how="inner",
        )
        distributed = distributed[~distributed["gen_key"].isin(direct_gen_keys)]

        # Compute value by carrier
        direct["value"] = select_value(direct)
        direct["p_max_pu"] = np.clip(direct["value"] / direct["p_nom"], 0, 1)

        distributed["plant_value"] = select_value(distributed)
        distributed["value"] = distributed["plant_value"] * distributed["weight"]
        distributed["p_max_pu"] = np.clip(
            distributed["value"] / distributed["p_nom"], 0, 1
        )

        cols_out = [
            "gen_key",
            "bus_conexion500kv_name",
            "carrier",
            "datetime",
            "p_max_pu",
        ]
        df_out = pd.concat(
            [
                direct[cols_out],
                distributed[cols_out],
            ],
            ignore_index=True,
        )

        df_out["p_max_pu"] = df_out["p_max_pu"].round(6)

        mode = "w" if first_chunk else "a"
        df_out.to_csv(OUTPUT_FILE, index=False, mode=mode, header=first_chunk)
        n_rows_out += len(df_out)
        first_chunk = False

        if n_chunks % 5 == 0:
            print(f"  ... chunk {n_chunks}, rows written: {n_rows_out:,}")

    # =========================================================
    # FINAL REPORT
    # =========================================================
    print(f"\n{'=' * 60}")
    print("FINAL REPORT")
    print(f"{'=' * 60}")
    print(f"  Chunks processed : {n_chunks}")
    print(f"  Output rows      : {n_rows_out:,}")
    print(f"  Output file      : {OUTPUT_FILE}")
    print("=" * 60)
    print("Next: 18_diagnose_marginal_costs.py")


if __name__ == "__main__":
    main()