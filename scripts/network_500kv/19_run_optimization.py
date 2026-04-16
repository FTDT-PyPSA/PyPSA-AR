"""
19_run_optimization.py
Runs the linear DC economic dispatch (OPF) on the Argentine 500 kV network for
the configured 2024 period.

Inputs:
    networks/network_500kv.nc
    data/network_500kv/generators_2024.csv
    data/network_500kv/loads_2024.csv
    data/network_500kv/marginal_costs_2024.csv
    external_data_dir/gen_profiles_2024.csv
    external_data_dir/valores_2024_clean.csv

Output:
    networks/results_2024_YYYYMMDD_YYYYMMDD.nc

Modeling decisions:
    - Linear DC OPF: no losses, no voltages, active power flows only.
    - Slack bus: ATUCHA 2_21kV.
    - Brazil link: import only (p_min_pu=0), free for the solver.
    - Load shedding: LOAD_SHED_COST USD/MWh per bus, guarantees feasibility.
    - Wind, solar, nuclear: marginal_cost = 0 (dispatched first by the solver).
    - Hydro/hydro_renewable: p_max_pu limited by real 2024 operated output profile.
    - Thermal and Brazil imports: real marginal costs.
    - Generators without profile in gen_profiles_2024.csv: excluded from the network.

Run from the repository root (pypsa-ar-base/):
    python scripts/network_500kv/19_run_optimization.py
"""

import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
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
COSTS_FILE = REPO_DIR / "data/network_500kv/marginal_costs_2024.csv"
PROFILES_FILE = EXTERNAL_DIR / "gen_profiles_2024.csv"
VALORES_FILE = EXTERNAL_DIR / "valores_2024_clean.csv"

OUTPUT_DIR = REPO_DIR / "networks"
OUTPUT_RESULTS_DIR = REPO_DIR / "results"

# Simulation period
START_DATE = "2024-02-01"
END_DATE = "2024-02-07"

# Chunking: None = single problem | 7 = weekly | 30 = monthly
CHUNK_DAYS = None

# Optimizable generators without marginal cost
# False: marginal_cost = 0 | True: excluded
EXCLUDE_NO_COST = False

# Carriers with marginal cost forced to 0
ZERO_COST_CARRIERS = {"wind", "solar", "nuclear"}

# Virtual load shedding per bus
LOAD_SHED_COST = 10_000.0
LOAD_SHED_PNOM = 99_999.0

SLACK_BUS = "ATUCHA 2_21kV"
BRAZIL_LINK = "importacion_brasil"

BUSES_TO_EXCLUDE_OPF = {"T PEPE", "PBUENA2", "PBUENA2_20kV"}

# Report groupings
THERMAL_CARRIERS = {"ocgt", "ccgt", "steam", "diesel"}
HYDRO_CARRIERS = {"hydro", "pumped_hydro"}


# =============================================================================
# HELPERS
# =============================================================================

def verify_inputs():
    files = {
        "network_500kv.nc": NETWORK_FILE,
        "generators_2024.csv": GEN_FILE,
        "loads_2024.csv": LOADS_FILE,
        "marginal_costs_2024.csv": COSTS_FILE,
        "gen_profiles_2024.csv": PROFILES_FILE,
    }

    ok = True
    for name, path in files.items():
        if not os.path.isfile(path):
            print(f"  [ERROR] Not found: {name}")
            print(f"          Expected path: {path}")
            ok = False

    if not ok:
        sys.exit(1)

    print("  All inputs verified.")


def build_output_name(start_date, end_date):
    ini = pd.Timestamp(start_date).strftime("%Y%m%d")
    fin = pd.Timestamp(end_date).strftime("%Y%m%d")
    return OUTPUT_DIR / f"results_2024_{ini}_{fin}.nc"


def parse_snapshot_csv(series):
    return pd.to_datetime(series, dayfirst=True, format="%d/%m/%Y %H:%M")


def solver_status_ok(status):
    if status is None:
        return False
    if isinstance(status, str):
        return status.strip().lower() in {"ok", "optimal"}
    if isinstance(status, (tuple, list)):
        status_norm = tuple(str(x).strip().lower() for x in status)
        return status_norm in {("ok",), ("optimal",), ("ok", "optimal"), ("optimal", "ok")}
    return str(status).strip().lower() in {"ok", "optimal"}


# =============================================================================
# STEP 1 — Load base network
# =============================================================================

def load_network():
    print("\n[1/6] Loading base network ...")
    n = pypsa.Network(NETWORK_FILE)

    print(f"  Buses         : {len(n.buses)}")
    print(f"  Lines         : {len(n.lines)}")
    print(f"  Transformers  : {len(n.transformers)}")
    print(f"  Links         : {len(n.links)}")

    if SLACK_BUS in n.buses.index:
        n.buses.loc[SLACK_BUS, "control"] = "Slack"
        print(f"  Slack bus     : {SLACK_BUS}")
    else:
        print(f"  [WARNING] Slack bus '{SLACK_BUS}' not found")

    if BRAZIL_LINK in n.links.index:
        n.links.loc[BRAZIL_LINK, "p_min_pu"] = 0.0
        print("  Brazil link   : p_min_pu=0 (import only)")
    else:
        print(f"  [WARNING] Link '{BRAZIL_LINK}' not found")

    _exclude_isolated_buses(n)

    print(f"  Final buses   : {len(n.buses)}")
    print(f"  Final lines   : {len(n.lines)}")
    return n


def _exclude_isolated_buses(n):
    buses_present = [b for b in BUSES_TO_EXCLUDE_OPF if b in n.buses.index]
    if not buses_present:
        return

    print(f"  Excluding isolated buses: {sorted(buses_present)}")

    for name in n.lines[n.lines["bus0"].isin(buses_present) | n.lines["bus1"].isin(buses_present)].index:
        n.remove("Line", name)
    for name in n.transformers[n.transformers["bus0"].isin(buses_present) | n.transformers["bus1"].isin(buses_present)].index:
        n.remove("Transformer", name)
    for name in n.links[n.links["bus0"].isin(buses_present) | n.links["bus1"].isin(buses_present)].index:
        n.remove("Link", name)
    for bus in buses_present:
        n.remove("Bus", bus)


# =============================================================================
# STEP 2 — Prepare snapshots
# =============================================================================

def prepare_snapshots():
    print("\n[2/6] Preparing snapshots ...")

    snapshots = pd.date_range(
        start=START_DATE,
        end=pd.Timestamp(END_DATE) + pd.Timedelta(hours=23),
        freq="h",
    )

    print(f"  Period    : {START_DATE} -> {END_DATE}")
    print(f"  Snapshots : {len(snapshots)} hours")
    return snapshots


# =============================================================================
# STEP 3 — Add generators
# =============================================================================

def add_generators(n, snapshots):
    print("\n[3/6] Adding generators ...")

    gen = pd.read_csv(GEN_FILE)
    costs = pd.read_csv(COSTS_FILE)[["gen_key", "marginal_cost"]].copy()
    gen = gen.merge(costs, on="gen_key", how="left")

    mask_zero = gen["carrier"].isin(ZERO_COST_CARRIERS)
    gen.loc[mask_zero, "marginal_cost"] = 0.0
    print(f"  Forced cost=0 : {mask_zero.sum()} generators ({', '.join(sorted(ZERO_COST_CARRIERS))})")

    no_cost = gen["marginal_cost"].isna()
    n_no_cost = no_cost.sum()

    if EXCLUDE_NO_COST:
        gen = gen[~no_cost].copy()
        print(f"  {n_no_cost} generators without cost excluded")
    else:
        gen.loc[no_cost, "marginal_cost"] = 0.0
        if n_no_cost:
            print(f"  {n_no_cost} generators without cost -> marginal_cost=0")

    buses_in_network = set(n.buses.index)
    n_added = 0
    n_missing_bus = 0

    for _, row in gen.iterrows():
        bus = row.get("bus_conexion500kv_name")
        if pd.isna(bus) or bus not in buses_in_network:
            n_missing_bus += 1
            continue

        n.add(
            "Generator",
            row["gen_key"],
            bus=bus,
            p_nom=float(row["p_nom"]),
            carrier=row["carrier"],
            marginal_cost=float(row["marginal_cost"]),
        )
        n_added += 1

    print(f"  Generators added   : {n_added}")
    if n_missing_bus:
        print(f"  [WARNING] {n_missing_bus} skipped — bus not found in network")

    return gen[gen["bus_conexion500kv_name"].isin(buses_in_network)].copy()


# =============================================================================
# STEP 4 — Add p_max_pu profiles from gen_profiles_2024.csv
# =============================================================================

def add_profiles(n, snapshots):
    print("\n[4/6] Loading profiles (gen_profiles_2024.csv) ...")

    chunks = []
    ts_start = snapshots[0]
    ts_end = snapshots[-1]

    for chunk in pd.read_csv(PROFILES_FILE, chunksize=500_000, low_memory=False):
        chunk["ts"] = parse_snapshot_csv(chunk["datetime"])
        chunk = chunk[(chunk["ts"] >= ts_start) & (chunk["ts"] <= ts_end)]
        if not chunk.empty:
            chunks.append(chunk[["gen_key", "ts", "p_max_pu"]])

    if not chunks:
        print("  [ERROR] No profiles found for the configured period.")
        sys.exit(1)

    profiles = pd.concat(chunks, ignore_index=True)
    profiles_wide = profiles.pivot_table(
        index="ts", columns="gen_key", values="p_max_pu", aggfunc="first"
    )
    profiles_wide.index.name = None
    profiles_wide = profiles_wide.reindex(snapshots).fillna(0.0)

    gens_in_network = set(n.generators.index)
    valid_cols = [c for c in profiles_wide.columns if c in gens_in_network]
    profiles_wide = profiles_wide[valid_cols]

    n.generators_t.p_max_pu = profiles_wide
    print(f"  Generators with profile : {len(valid_cols)}")

    gens_without_profile = gens_in_network - set(valid_cols)
    if gens_without_profile:
        for gkey in sorted(gens_without_profile):
            n.remove("Generator", gkey)
        print(f"  {len(gens_without_profile)} generators without profile excluded")


# =============================================================================
# STEP 5 — Add hourly demand
# =============================================================================

def add_demand(n, snapshots):
    print("\n[5/6] Loading hourly demand ...")

    loads = pd.read_csv(LOADS_FILE)
    loads["ts"] = parse_snapshot_csv(loads["datetime"])
    ts_start = snapshots[0]
    ts_end = snapshots[-1]
    loads = loads[(loads["ts"] >= ts_start) & (loads["ts"] <= ts_end)].copy()

    loads_wide = loads.pivot_table(
        index="ts", columns="bus_name", values="p_mw", aggfunc="sum"
    )
    loads_wide.index.name = None
    loads_wide = loads_wide.reindex(snapshots).fillna(0.0)

    buses_in_network = set(n.buses.index)
    n_loads = 0

    for bus_name in loads_wide.columns:
        if bus_name not in buses_in_network:
            continue
        n.add("Load", f"load_{bus_name}", bus=bus_name)
        n_loads += 1

    load_names = [f"load_{b}" for b in loads_wide.columns if b in buses_in_network]
    loads_wide.columns = [f"load_{b}" for b in loads_wide.columns]
    valid_cols = [c for c in load_names if c in loads_wide.columns]
    n.loads_t.p_set = loads_wide[valid_cols]

    demand_max = loads_wide[valid_cols].sum(axis=1).max()
    print(f"  Buses with demand : {n_loads}")
    print(f"  Peak demand       : {demand_max:,.1f} MW")

    print(f"  Adding virtual load shedding ({LOAD_SHED_COST:,.0f} USD/MWh) ...")
    for bus in n.buses.index:
        n.add(
            "Generator",
            f"loadshed_{bus}",
            bus=bus,
            p_nom=LOAD_SHED_PNOM,
            carrier="load_shedding",
            marginal_cost=LOAD_SHED_COST,
        )


# =============================================================================
# STEP 6 — Run optimization
# =============================================================================

def run_optimization(n, snapshots):
    print("\n[6/6] Running DC optimization ...")
    print("  Solver     : HiGHS")
    print(f"  Snapshots  : {len(snapshots)} hours")
    print(f"  Chunk days : {CHUNK_DAYS if CHUNK_DAYS else 'no chunking'}")

    if CHUNK_DAYS is None:
        return _run_single_chunk(n, snapshots)
    return _run_with_chunks(n, snapshots)


def _run_single_chunk(n, snapshots_chunk):
    n.set_snapshots(snapshots_chunk)

    if not n.generators_t.p_max_pu.empty:
        n.generators_t.p_max_pu = n.generators_t.p_max_pu.reindex(snapshots_chunk).fillna(0.0)
    if not n.loads_t.p_set.empty:
        n.loads_t.p_set = n.loads_t.p_set.reindex(snapshots_chunk).fillna(0.0)

    result = n.optimize(solver_name="highs")
    status = n.optimization_status if hasattr(n, "optimization_status") else result

    if not solver_status_ok(status):
        print(f"\n  [ERROR] Solver status: {status}")
        print("  Possible causes: severe congestion or insufficient generation.")
        return None

    return n


def _run_with_chunks(n, snapshots_total):
    p_max_pu_full = n.generators_t.p_max_pu.copy() if not n.generators_t.p_max_pu.empty else pd.DataFrame()
    p_set_full = n.loads_t.p_set.copy() if not n.loads_t.p_set.empty else pd.DataFrame()

    chunks = []
    delta = pd.Timedelta(days=CHUNK_DAYS)
    t = snapshots_total[0]
    end = snapshots_total[-1]

    while t <= end:
        t_end = min(t + delta - pd.Timedelta(hours=1), end)
        chunk = snapshots_total[(snapshots_total >= t) & (snapshots_total <= t_end)]
        if len(chunk) > 0:
            chunks.append(chunk)
        t += delta

    print(f"  Total chunks : {len(chunks)}")
    acc_gen_p = []
    acc_lines_p0 = []
    acc_links_p0 = []

    for i, chunk in enumerate(chunks, 1):
        print(f"\n  Chunk {i}/{len(chunks)}: {chunk[0].date()} -> {chunk[-1].date()} ({len(chunk)} h)")

        if not p_max_pu_full.empty:
            n.generators_t.p_max_pu = p_max_pu_full.reindex(chunk).fillna(0.0)
        if not p_set_full.empty:
            n.loads_t.p_set = p_set_full.reindex(chunk).fillna(0.0)

        n.set_snapshots(chunk)
        result = n.optimize(solver_name="highs")
        status = n.optimization_status if hasattr(n, "optimization_status") else result

        if not solver_status_ok(status):
            print(f"    [ERROR] Chunk {i}: {status}. Aborting.")
            return None

        acc_gen_p.append(n.generators_t.p.copy())
        acc_lines_p0.append(n.lines_t.p0.copy())
        if not n.links_t.p0.empty:
            acc_links_p0.append(n.links_t.p0.copy())

        print(f"    OK — average generation: {n.generators_t.p.sum(axis=1).mean():,.1f} MW")

    print(f"\n  Concatenating {len(chunks)} chunks ...")
    n.set_snapshots(snapshots_total)
    n.generators_t.p = pd.concat(acc_gen_p)
    n.lines_t.p0 = pd.concat(acc_lines_p0)
    if acc_links_p0:
        n.links_t.p0 = pd.concat(acc_links_p0)

    n.generators_t.p_max_pu = p_max_pu_full
    n.loads_t.p_set = p_set_full
    return n


# =============================================================================
# SAVE AND REPORT
# =============================================================================

def save_results(n):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    output_file = build_output_name(START_DATE, END_DATE)
    n.export_to_netcdf(output_file)
    print(f"\n  Saved: {output_file}")
    return output_file


def report_load_shedding(n):
    print(f"\n{'='*60}")
    print("LOAD SHEDDING REPORT")
    print(f"{'='*60}")

    gen_p = n.generators_t.p
    loadshed_cols = [c for c in gen_p.columns if c.startswith("loadshed_")]

    if not loadshed_cols:
        print("  No load shedding columns found in results.")
        return

    ls_total = gen_p[loadshed_cols].sum(axis=1)
    ls_sum = ls_total.sum()

    if ls_sum < 0.01:
        print("  No load shedding activated.")
    else:
        hours_with_ls = (ls_total > 0.01).sum()
        print("  [WARNING] Load shedding activated:")
        print(f"    Total accumulated : {ls_sum:,.1f} MWh")
        print(f"    Affected hours    : {hours_with_ls} of {len(ls_total)}")
        print(f"    Peak hour         : {ls_total.idxmax()}  ({ls_total.max():,.1f} MW)")

        ls_by_bus = gen_p[loadshed_cols].sum().sort_values(ascending=False)
        ls_by_bus.index = ls_by_bus.index.str.replace("loadshed_", "", regex=False)
        print("\n  Top 5 buses with highest load shedding:")
        for bus, mwh in ls_by_bus.head(5).items():
            if mwh > 0.01:
                print(f"    {bus:<30}  {mwh:>10,.1f} MWh")


def report_summary(n):
    print(f"\n{'='*60}")
    print("RUN SUMMARY")
    print(f"{'='*60}")

    gen_p = n.generators_t.p
    real_gens = [c for c in gen_p.columns if not c.startswith("loadshed_")]
    gen_real = gen_p[real_gens]

    total_gen_mwh = gen_real.sum().sum()
    print(f"\n  Total generation: {total_gen_mwh:,.0f} MWh")

    carriers_raw = n.generators.loc[real_gens, "carrier"]
    carriers_grouped = carriers_raw.map(
        lambda c: "thermal" if c in THERMAL_CARRIERS else
                  "hydro" if c in HYDRO_CARRIERS else c
    )

    mix = gen_real.sum().groupby(carriers_grouped).sum().sort_values(ascending=False)
    print("\n  Generation mix by technology:")
    for carrier, mwh in mix.items():
        pct = 100 * mwh / total_gen_mwh if total_gen_mwh > 0 else 0
        print(f"    {carrier:<20}: {mwh:>12,.0f} MWh  ({pct:>5.1f}%)")

    if not n.lines_t.p0.empty and not n.lines["s_nom"].eq(0).all():
        p0_abs = n.lines_t.p0.abs()
        s_nom = n.lines["s_nom"].replace(0, np.nan)
        util = (p0_abs / s_nom * 100).mean().dropna().sort_values(ascending=False)

        print("\n  Top 10 most loaded lines (% average utilization):")
        print(f"    {'Line':<35} {'Avg. util.':>15}")
        for line, pct in util.head(10).items():
            print(f"    {line:<35} {pct:>14.1f}%")

    if BRAZIL_LINK in n.links_t.p0.columns:
        brazil_import_mwh = n.links_t.p0[BRAZIL_LINK].clip(lower=0).sum()
        print(f"\n  Accumulated Brazil imports: {brazil_import_mwh:,.0f} MWh")


# =============================================================================
# EXPORT RESULTS
# =============================================================================

def export_results(n):
    """
    Exports two CSVs with run results:

    results_generators_DATES.csv
        One row per generator (excluding load shedding).
        Fields: gen_key, bus_name_origen, geosadi_name, carrier, bus,
                p_nom_mw, total_energy_mwh, average_power_mw,
                peak_power_mw, capacity_factor_pct
        Sorted by total_energy_mwh descending.

    results_lines_DATES.csv
        One row per line with flow and saturation metrics.
        Fields: line_id, line_key, s_nom_mva, average_flow_mw,
                peak_flow_mw, average_saturation_pct,
                peak_saturation_pct, hours_above_90pct
        Sorted by average_saturation_pct descending.
    """
    os.makedirs(OUTPUT_RESULTS_DIR, exist_ok=True)
    ini = pd.Timestamp(START_DATE).strftime("%Y%m%d")
    fin = pd.Timestamp(END_DATE).strftime("%Y%m%d")
    suffix = f"{ini}_{fin}"

    gen_p = n.generators_t.p
    real_gens = [c for c in gen_p.columns if not c.startswith("loadshed_")]
    gen_real = gen_p[real_gens]
    n_snapshots = len(n.snapshots)

    gen_meta = pd.read_csv(GEN_FILE)[["gen_key", "bus_name_origen", "geosadi_name"]].copy()
    gen_meta["gen_key"] = gen_meta["gen_key"].astype(str)

    rows = []
    for gkey in real_gens:
        series = gen_real[gkey]
        p_nom = n.generators.loc[gkey, "p_nom"]
        carrier = n.generators.loc[gkey, "carrier"]
        bus = n.generators.loc[gkey, "bus"]
        e_total = series.sum()
        p_avg = series.mean()
        p_peak = series.max()
        cf = (e_total / (p_nom * n_snapshots) * 100) if p_nom > 0 else 0.0

        rows.append({
            "gen_key": gkey,
            "carrier": carrier,
            "bus": bus,
            "p_nom_mw": round(p_nom, 4),
            "total_energy_mwh": round(e_total, 2),
            "average_power_mw": round(p_avg, 2),
            "peak_power_mw": round(p_peak, 2),
            "capacity_factor_pct": round(cf, 2),
        })

    df_gen = pd.DataFrame(rows)
    df_gen["gen_key"] = df_gen["gen_key"].astype(str)
    df_gen = df_gen.merge(gen_meta, on="gen_key", how="left")

    cols_gen = [
        "gen_key", "bus_name_origen", "geosadi_name", "carrier", "bus",
        "p_nom_mw", "total_energy_mwh", "average_power_mw",
        "peak_power_mw", "capacity_factor_pct"
    ]
    df_gen = df_gen[cols_gen].sort_values("total_energy_mwh", ascending=False)

    out_gen = OUTPUT_RESULTS_DIR / f"results_generators_{suffix}.csv"
    df_gen.to_csv(out_gen, index=False)
    print(f"  Generators : {out_gen}  ({len(df_gen)} rows)")

    if n.lines_t.p0.empty:
        print("  Lines      : no flow data — skipped")
        return

    p0_abs = n.lines_t.p0.abs()
    s_nom = n.lines["s_nom"].replace(0, np.nan)
    util = p0_abs.divide(s_nom, axis=1) * 100

    rows_l = []
    for line in n.lines.index:
        if line not in p0_abs.columns:
            continue
        sn = n.lines.loc[line, "s_nom"]
        flow_series = p0_abs[line]
        util_series = util[line] if sn > 0 else pd.Series(np.nan, index=p0_abs.index)

        rows_l.append({
            "line_key": line,
            "s_nom_mva": round(sn, 1),
            "average_flow_mw": round(flow_series.mean(), 2),
            "peak_flow_mw": round(flow_series.max(), 2),
            "average_saturation_pct": round(util_series.mean(), 2) if sn > 0 else None,
            "peak_saturation_pct": round(util_series.max(), 2) if sn > 0 else None,
            "hours_above_90pct": int((util_series > 90).sum()) if sn > 0 else None,
        })

    df_lines = pd.DataFrame(rows_l)

    lines_meta_path = REPO_DIR / "data/network_500kv/lines_500kv_final.csv"
    if os.path.isfile(lines_meta_path):
        lines_meta = pd.read_csv(lines_meta_path)[["line_id", "line_key"]].copy()
        lines_meta["line_key"] = lines_meta["line_key"].astype(str)
        df_lines = df_lines.merge(lines_meta, on="line_key", how="left")
        cols_lines = [
            "line_id", "line_key", "s_nom_mva", "average_flow_mw",
            "peak_flow_mw", "average_saturation_pct",
            "peak_saturation_pct", "hours_above_90pct"
        ]
    else:
        cols_lines = [
            "line_key", "s_nom_mva", "average_flow_mw",
            "peak_flow_mw", "average_saturation_pct",
            "peak_saturation_pct", "hours_above_90pct"
        ]

    df_lines = df_lines[cols_lines].sort_values("average_saturation_pct", ascending=False)

    out_lines = OUTPUT_RESULTS_DIR / f"results_lines_{suffix}.csv"
    df_lines.to_csv(out_lines, index=False)
    print(f"  Lines      : {out_lines}  ({len(df_lines)} rows)")


# =============================================================================
# MODEL VS CAMMESA REAL COMPARISON
# =============================================================================

def compare_vs_real(n):
    """
    Reads valores_2024_clean.csv for the same run period and compares
    generation by technology (carrier) between the model and CAMMESA data.

    Approximate mapping from CAMMESA carrier to model groups:
        hydro                         -> hydro
        ocgt / ccgt / steam / diesel  -> thermal
        nuclear                       -> nuclear
        wind                          -> wind
        solar                         -> solar
        biomass / biogas              -> biofuels
        international_import          -> import
    """
    print(f"\n{'='*60}")
    print("MODEL VS REAL CAMMESA COMPARISON")
    print(f"{'='*60}")

    if not os.path.isfile(VALORES_FILE):
        print("  [WARNING] valores_2024_clean.csv not found — comparison skipped.")
        return

    ts_start = pd.Timestamp(START_DATE)
    ts_end = pd.Timestamp(END_DATE) + pd.Timedelta(hours=23)

    chunks = []
    for chunk in pd.read_csv(
        VALORES_FILE,
        usecols=["datetime", "carrier", "energy_mwh", "flag_outlier"],
        chunksize=500_000,
        low_memory=False,
    ):
        chunk = chunk[chunk["flag_outlier"] == False].copy()
        chunk["ts"] = pd.to_datetime(chunk["datetime"], dayfirst=True, format="%d/%m/%Y %H:%M")
        chunk = chunk[(chunk["ts"] >= ts_start) & (chunk["ts"] <= ts_end)]
        if not chunk.empty:
            chunks.append(chunk[["carrier", "energy_mwh"]])

    if not chunks:
        print(f"  [WARNING] No real data found for {START_DATE} - {END_DATE}.")
        return

    real = pd.concat(chunks, ignore_index=True)

    CARRIER_TO_GROUP = {
        "hydro": "hydro",
        "hydro_renewable": "hydro",
        "ocgt": "thermal",
        "ccgt": "thermal",
        "steam": "thermal",
        "diesel": "thermal",
        "nuclear": "nuclear",
        "wind": "wind",
        "solar": "solar",
        "biomass": "biofuels",
        "biogas": "biofuels",
        "international_import": "import",
    }

    real["group"] = real["carrier"].map(CARRIER_TO_GROUP).fillna("other")
    real_mwh = real.groupby("group")["energy_mwh"].sum()
    real_total = real_mwh.sum()

    gen_p = n.generators_t.p
    real_gens = [c for c in gen_p.columns if not c.startswith("loadshed_")]
    carriers = n.generators.loc[real_gens, "carrier"]

    model_groups = carriers.map(
        lambda c: "thermal" if c in THERMAL_CARRIERS else
                  "hydro" if c in HYDRO_CARRIERS else
                  "biofuels" if c in {"biomass", "biogas"} else c
    )
    model_mwh = gen_p[real_gens].sum().groupby(model_groups).sum()

    if BRAZIL_LINK in n.links_t.p0.columns:
        brazil_import = n.links_t.p0[BRAZIL_LINK].clip(lower=0).sum()
        if brazil_import > 0:
            model_mwh["import"] = model_mwh.get("import", 0) + brazil_import

    model_total = model_mwh.sum()
    all_groups = sorted(set(list(real_mwh.index) + list(model_mwh.index)))

    print(f"\n  {'Technology':<20} {'Model MWh':>13} {'Model %':>9} {'Real MWh':>13} {'Real %':>9} {'Diff pp':>9}")
    print(f"  {'-'*20} {'-'*13} {'-'*9} {'-'*13} {'-'*9} {'-'*9}")

    for group in all_groups:
        m_mwh = model_mwh.get(group, 0)
        r_mwh = real_mwh.get(group, 0)
        m_pct = m_mwh / model_total * 100 if model_total > 0 else 0
        r_pct = r_mwh / real_total * 100 if real_total > 0 else 0
        diff = m_pct - r_pct
        print(f"  {group:<20} {m_mwh:>13,.0f} {m_pct:>8.1f}% {r_mwh:>13,.0f} {r_pct:>8.1f}% {diff:>+8.1f}%")

    print(f"  {'-'*20} {'-'*13} {'-'*9} {'-'*13} {'-'*9} {'-'*9}")
    print(f"  {'TOTAL':<20} {model_total:>13,.0f} {'100.0%':>9} {real_total:>13,.0f} {'100.0%':>9}")


# =============================================================================
# MAIN
# =============================================================================

def main():
    print("=" * 60)
    print("19_run_optimization.py -- 2024 DC economic dispatch")
    print("=" * 60)
    print(f"\nPeriod      : {START_DATE} -> {END_DATE}")
    print(f"Chunk days  : {CHUNK_DAYS if CHUNK_DAYS else 'no chunking'}")
    print(f"No-cost gens: {'exclude' if EXCLUDE_NO_COST else 'cost=0'}")

    print("\n[0/6] Verifying inputs ...")
    verify_inputs()

    n = load_network()
    snapshots = prepare_snapshots()
    add_generators(n, snapshots)
    add_profiles(n, snapshots)
    add_demand(n, snapshots)

    n = run_optimization(n, snapshots)

    if n is None:
        print("\n[ABORTED] Optimization did not converge.")
        sys.exit(1)

    output_file = save_results(n)
    report_load_shedding(n)
    report_summary(n)

    print("\n[Exporting result CSVs ...]")
    export_results(n)

    compare_vs_real(n)

    print(f"\n{'='*60}")
    print("Run completed.")
    print(f"Output: {output_file}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()