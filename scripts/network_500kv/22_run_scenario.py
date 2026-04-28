"""
22_run_scenario.py
Optimizes a scenario network produced by script 21. Solves a joint
capacity-expansion + dispatch LP: the optimizer decides simultaneously
how much of each expandable generator/line to build and how to dispatch
all hours of the target year.

Outputs are saved to networks/scenarios/results_<scenario>_k<K>/, including:
    - results_<scenario>_k<K>.nc      Full PyPSA network post-optimization
                                       (with hourly dispatch, optimal capacities,
                                       flows, marginal prices).
    - summary_global.csv              One-row-per-scenario KPIs.
    - summary_by_carrier.csv          Annual generation, capacity, costs by carrier.
    - summary_by_cluster.csv          Generation, demand and balance per cluster.
    - summary_by_line.csv             Annual flow and usage per inter-cluster line.
    - new_capacity.csv                Capacity built by the optimizer
                                       (carrier × cluster) and per-line MW added.

Inputs:
    networks/scenarios/scenario_<scenario>_k<K>.nc   (script 21)

Usage:
    # Default: 2035_BAU at K=10 with HiGHS
    python scripts/network_500kv/22_run_scenario.py

    # Custom scenario / cluster level
    python scripts/network_500kv/22_run_scenario.py --scenario 2035_BAU --k 10

    # Custom solver (requires the solver to be installed and licensed)
    python scripts/network_500kv/22_run_scenario.py --solver gurobi

Notes:
    - The optimization horizon is the entire year (8784 hours). No chunking
      is used because expansion decisions are annual and cannot be chunked.
    - HiGHS is the default solver (open source, included with PyPSA). Gurobi
      and CPLEX can be selected if installed.
    - Solve time on a typical laptop with HiGHS for K=10 is on the order of
      15-60 minutes. Larger K or more carriers will scale this up.
    - The input scenario .nc is never modified. The optimizer's results are
      written into a fresh copy that is exported separately.
"""

import argparse
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
import pypsa


# =============================================================================
# CONFIGURATION
# =============================================================================

_cfg = yaml.safe_load(open(Path(__file__).parents[2] / "config.yaml"))
REPO_DIR = Path(_cfg["repo_dir"])

SCENARIOS_DIR = REPO_DIR / "networks/scenarios"
CLUSTERS_DIR  = REPO_DIR / "data/network_500kv/clusters"

# Default values when not overridden via CLI
DEFAULT_SCENARIO = "2035_BAU"
DEFAULT_K        = 10
DEFAULT_SOLVER   = "highs"

# Which carriers count as "renewable" for the renewable-share KPI.
RENEWABLE_CARRIERS = {
    "solar", "wind", "hydro", "pumped_hydro", "biomass", "biogas", "bioenergy",
}

# Carriers we consider "new built" for the new-capacity report. These are the
# ones that script 21 added as expandable. Existing generators sit on other
# names not prefixed with "new_".
NEW_GENERATOR_PREFIX = "new_"

# Conversion factors used in summary CSVs to keep numbers human-readable.
MWH_TO_GWH = 1.0 / 1_000.0
MWH_TO_TWH = 1.0 / 1_000_000.0


# =============================================================================
# HELPERS
# =============================================================================

def parse_args():
    p = argparse.ArgumentParser(
        description="Optimize a PyPSA-AR scenario (capacity expansion + dispatch)."
    )
    p.add_argument(
        "--scenario", default=DEFAULT_SCENARIO,
        help=f"Scenario name as built by script 21 (default: {DEFAULT_SCENARIO})"
    )
    p.add_argument(
        "--k", type=int, default=DEFAULT_K,
        help=f"Cluster aggregation level (default: {DEFAULT_K})"
    )
    p.add_argument(
        "--solver", default=DEFAULT_SOLVER,
        help=f"LP solver to use: highs, gurobi, cplex, glpk, cbc (default: {DEFAULT_SOLVER})"
    )
    return p.parse_args()


def get_paths(scenario, k):
    input_file = SCENARIOS_DIR / f"scenario_{scenario}_k{k}.nc"
    output_dir = SCENARIOS_DIR / f"results_{scenario}_k{k}"
    return input_file, output_dir


def fmt_seconds(s):
    if s < 60:
        return f"{s:.1f} s"
    if s < 3600:
        return f"{s/60:.1f} min"
    return f"{s/3600:.2f} h"


def weighted_sum(df, weights):
    """Sum a time-indexed DataFrame applying snapshot_weightings.
    df: DataFrame with snapshots as index.
    weights: Series with the same index, weight per snapshot in hours.
    Returns: float = sum over both axes of df.multiply(weights, axis=0)."""
    if df is None or df.empty:
        return 0.0
    return float(df.multiply(weights, axis=0).sum().sum())


def weighted_sum_per_column(df, weights):
    """Sum each column of df applying snapshot_weightings.
    Returns: Series indexed by columns of df."""
    if df is None or df.empty:
        return pd.Series(dtype=float)
    return df.multiply(weights, axis=0).sum()


def get_year_factor(n):
    """Returns the number of years represented by the network's snapshots,
    following PyPSA-Eur convention (snapshot_weightings.objective.sum() / 8760).
    For a single year of simulation this should be very close to 1.0
    (or slightly above for leap years: 8784/8760 = 1.0027)."""
    return float(n.snapshot_weightings.objective.sum()) / 8760.0


def load_cluster_names(k):
    """Loads the cluster_id -> human-readable name mapping from a CSV file.
    Falls back to identity mapping (name = cluster_id) if the file is missing.
    The CSV must have columns 'cluster_id' and 'name'."""
    fp = CLUSTERS_DIR / f"cluster_names_k{k}.csv"
    if not fp.is_file():
        print(f"  [INFO] Cluster names file not found at {fp}.")
        print(f"         Output CSVs will use the raw cluster_id values.")
        return {}
    df = pd.read_csv(fp)
    if not {"cluster_id", "name"}.issubset(df.columns):
        print(f"  [WARN] Cluster names file {fp.name} is missing 'cluster_id' "
              f"or 'name' column. Skipping.")
        return {}
    return dict(zip(df["cluster_id"], df["name"]))


def name_of(cluster_id, names):
    """Returns the human name of a cluster, falling back to the id."""
    return names.get(cluster_id, cluster_id)


# =============================================================================
# STEP 1 — Load scenario network
# =============================================================================

def load_scenario(input_file):
    print(f"\n[1/4] Loading scenario network ...")
    if not os.path.isfile(input_file):
        print(f"  [ERROR] Not found: {input_file}")
        print(f"          Run script 21 first.")
        sys.exit(1)

    n = pypsa.Network(input_file)

    # Counts to validate against expectations
    n_existing    = (~n.generators.index.str.startswith(NEW_GENERATOR_PREFIX) &
                     ~n.generators.index.str.startswith("loadshed_")).sum()
    n_extendable  = n.generators.index.str.startswith(NEW_GENERATOR_PREFIX).sum()
    n_loadshed    = n.generators.index.str.startswith("loadshed_").sum()
    n_lines_ext   = n.lines["s_nom_extendable"].sum() if len(n.lines) > 0 else 0

    print(f"  Source : {input_file}")
    print(f"  Buses (clusters)        : {len(n.buses)}")
    print(f"  Snapshots               : {len(n.snapshots)}")
    print(f"  Existing generators     : {int(n_existing)}")
    print(f"  Extendable generators   : {int(n_extendable)}")
    print(f"  Load-shedding gens      : {int(n_loadshed)}")
    print(f"  Lines (extendable)      : {len(n.lines)} ({int(n_lines_ext)} extendable)")
    return n


# =============================================================================
# STEP 2 — Solve
# =============================================================================

def solve(n, solver):
    print(f"\n[2/4] Solving capacity expansion + dispatch ...")
    print(f"  Solver         : {solver}")
    print(f"  Snapshots      : {len(n.snapshots)}")
    print(f"  Generators     : {len(n.generators)}")
    print(f"  This is a single LP over the entire year — no chunking.")
    print(f"  Solve may take from 15 minutes to over an hour depending on scale.")
    print(f"  Starting at: {time.strftime('%Y-%m-%d %H:%M:%S')}")

    t0 = time.perf_counter()
    status, condition = n.optimize(solver_name=solver)
    elapsed = time.perf_counter() - t0

    print(f"\n  Status         : {status}")
    print(f"  Condition      : {condition}")
    print(f"  Solve time     : {fmt_seconds(elapsed)}")

    if status != "ok" or condition != "optimal":
        print(f"\n  [WARNING] Optimization did not return an optimal solution.")
        print(f"            Outputs may be inconsistent. Inspect carefully.")

    return status, condition, elapsed


# =============================================================================
# STEP 3 — Compute summaries
# =============================================================================

def compute_summary_global(n, scenario, k, solver, status, elapsed):
    """One-row global summary of the scenario.
    All time-series sums apply snapshot_weightings so yearly totals are correct."""
    weights = n.snapshot_weightings.objective

    gen_p = n.generators_t.p
    if gen_p.empty:
        total_generation_mwh = 0.0
        loadshed_mwh = 0.0
    else:
        total_generation_mwh = weighted_sum(gen_p, weights)
        loadshed_mask = n.generators["carrier"] == "load_shedding"
        if loadshed_mask.any():
            loadshed_cols = n.generators[loadshed_mask].index
            loadshed_mwh = weighted_sum(gen_p[loadshed_cols], weights)
        else:
            loadshed_mwh = 0.0

    total_demand_mwh = weighted_sum(n.loads_t.p_set, weights)

    # Renewable share (excludes load_shedding by construction)
    if not gen_p.empty:
        ren_mask = n.generators["carrier"].isin(RENEWABLE_CARRIERS)
        ren_cols = n.generators[ren_mask].index
        renewable_mwh = weighted_sum(gen_p[ren_cols], weights)
    else:
        renewable_mwh = 0.0

    served_mwh = total_generation_mwh - loadshed_mwh
    ren_share_pct = (100 * renewable_mwh / served_mwh) if served_mwh > 0 else 0.0

    # Total cost = objective value, reported by PyPSA
    objective = float(n.objective) if hasattr(n, "objective") else None

    summary = {
        "scenario"                     : scenario,
        "cluster_level_k"              : k,
        "solver"                       : solver,
        "solver_status"                : status,
        "solve_time_seconds"           : round(elapsed, 1),
        "year_factor"                  : round(get_year_factor(n), 4),
        "total_demand_TWh"             : round(total_demand_mwh * MWH_TO_TWH, 3),
        "total_generation_TWh"         : round(total_generation_mwh * MWH_TO_TWH, 3),
        "load_shedding_GWh"            : round(loadshed_mwh * MWH_TO_GWH, 1),
        "load_shedding_%_of_demand"    : round(100 * loadshed_mwh / total_demand_mwh, 4)
                                         if total_demand_mwh > 0 else 0.0,
        "renewable_generation_TWh"     : round(renewable_mwh * MWH_TO_TWH, 3),
        "renewable_share_%"            : round(ren_share_pct, 2),
        "total_annual_cost_USD"        : round(objective, 0) if objective is not None else None,
        "total_annual_cost_billion_USD": round(objective / 1e9, 3) if objective is not None else None,
    }
    return pd.DataFrame([summary])


def compute_summary_by_carrier(n):
    """Per-carrier annual generation, capacity (existing + new), capacity factor,
    and average dispatch cost. Sums use snapshot_weightings."""
    if n.generators_t.p.empty:
        return pd.DataFrame()

    weights         = n.snapshot_weightings.objective
    total_year_hrs  = float(weights.sum())   # ~8760 (or 8784 for leap years)
    gens            = n.generators

    # Total system generation for share calculations
    total_gen_mwh = weighted_sum(n.generators_t.p, weights)

    rows = []
    for carrier in sorted(gens["carrier"].unique()):
        cols = gens[gens["carrier"] == carrier].index

        # Annual generation (MWh): apply weightings
        gen_mwh = weighted_sum(n.generators_t.p[cols], weights)

        # Installed capacity (MW): split between existing and new (extendable)
        existing_mw = 0.0
        new_built_mw = 0.0
        for g in cols:
            if gens.at[g, "p_nom_extendable"]:
                p_opt = float(gens.at[g, "p_nom_opt"])
                # Capacity that started at p_nom_min stays as existing,
                # the rest is new. For our setup, expandable gens start at 0
                # so the entire p_nom_opt is new.
                p_min = float(gens.at[g, "p_nom_min"])
                existing_mw  += p_min
                new_built_mw += max(0.0, p_opt - p_min)
            else:
                existing_mw += float(gens.at[g, "p_nom"])
        total_capacity_mw = existing_mw + new_built_mw

        # Average marginal cost (weighted by dispatch). Useful as sanity check.
        if gen_mwh > 0:
            mc_series = gens.loc[cols, "marginal_cost"]
            disp_per_gen = weighted_sum_per_column(n.generators_t.p[cols], weights)
            weighted_mc = float((mc_series * disp_per_gen).sum() / gen_mwh)
        else:
            weighted_mc = 0.0

        # Capacity factor (% of theoretical maximum)
        if total_capacity_mw > 0:
            cf_pct = 100 * gen_mwh / (total_capacity_mw * total_year_hrs)
        else:
            cf_pct = 0.0

        # Share of system generation
        share_pct = 100 * gen_mwh / total_gen_mwh if total_gen_mwh > 0 else 0.0

        rows.append({
            "carrier"                          : carrier,
            "generation_GWh"                   : round(gen_mwh * MWH_TO_GWH, 1),
            "share_of_total_generation_%"      : round(share_pct, 2),
            "existing_capacity_MW"             : round(existing_mw, 1),
            "new_capacity_built_MW"            : round(new_built_mw, 1),
            "total_capacity_MW"                : round(total_capacity_mw, 1),
            "capacity_factor_%"                : round(cf_pct, 2),
            "avg_marginal_cost_USD_per_MWh"    : round(weighted_mc, 2),
        })

    return pd.DataFrame(rows).sort_values("generation_GWh", ascending=False)


def compute_summary_by_cluster(n, names):
    """Per-cluster annual generation, demand and net balance. Sums use
    snapshot_weightings. The 'names' dict maps cluster_id to a human name."""
    if n.generators_t.p.empty or n.loads_t.p_set.empty:
        return pd.DataFrame()

    weights = n.snapshot_weightings.objective

    rows = []
    for cluster in sorted(n.buses.index):
        gens_here = n.generators[n.generators["bus"] == cluster].index
        gen_mwh = (weighted_sum(n.generators_t.p[gens_here], weights)
                   if len(gens_here) > 0 else 0.0)

        loads_here = n.loads[n.loads["bus"] == cluster].index
        if len(loads_here) > 0:
            demand_mwh = weighted_sum(n.loads_t.p_set[loads_here], weights)
        else:
            demand_mwh = 0.0

        net_export_mwh = gen_mwh - demand_mwh

        # Renewable generation specifically in this cluster
        ren_mask = n.generators.loc[gens_here, "carrier"].isin(RENEWABLE_CARRIERS)
        ren_cols = gens_here[ren_mask] if ren_mask.any() else []
        ren_mwh  = (weighted_sum(n.generators_t.p[ren_cols], weights)
                    if len(ren_cols) else 0.0)

        # Trade balance as %: positive = net exporter, negative = net importer
        if demand_mwh > 0:
            net_export_pct_of_demand = 100 * net_export_mwh / demand_mwh
        else:
            net_export_pct_of_demand = 0.0

        rows.append({
            "region_name"                  : name_of(cluster, names),
            "cluster_id"                   : cluster,
            "demand_GWh"                   : round(demand_mwh * MWH_TO_GWH, 1),
            "generation_GWh"               : round(gen_mwh * MWH_TO_GWH, 1),
            "net_export_GWh"               : round(net_export_mwh * MWH_TO_GWH, 1),
            "net_export_%_of_demand"       : round(net_export_pct_of_demand, 1),
            "renewable_generation_GWh"     : round(ren_mwh * MWH_TO_GWH, 1),
            "renewable_share_in_region_%"  : round(100 * ren_mwh / gen_mwh, 2)
                                             if gen_mwh > 0 else 0.0,
        })

    df = pd.DataFrame(rows)
    return df.sort_values("demand_GWh", ascending=False).reset_index(drop=True)


def compute_summary_by_line(n, names):
    """Per-line annual flow, usage factor, and capacity built (if extendable).
    Flow integrals use snapshot_weightings; usage thresholds count snapshots
    weighted by their duration to give realistic hours-per-year metrics."""
    if len(n.lines) == 0 or n.lines_t.p0.empty:
        return pd.DataFrame()

    weights = n.snapshot_weightings.objective

    rows = []
    for line_name, line in n.lines.iterrows():
        flow = n.lines_t.p0[line_name]                     # MW per snapshot
        weighted_flow = flow.multiply(weights, axis=0)     # MWh per snapshot
        gross_flow_mwh = float(weighted_flow.abs().sum())
        net_flow_mwh   = float(weighted_flow.sum())        # signed; + bus0 -> bus1

        # Capacity that the optimizer chose
        if line.get("s_nom_extendable", False):
            s_nom_eff = float(line.get("s_nom_opt", line["s_nom"]))
        else:
            s_nom_eff = float(line["s_nom"])
        s_nom_initial = float(line["s_nom"])

        # Loading thresholds (in real hours per year, weighted by snapshot duration)
        if s_nom_eff > 0:
            loading = flow.abs() / s_nom_eff
            h_above_80 = float((loading > 0.80).astype(float).multiply(weights, axis=0).sum())
            h_above_90 = float((loading > 0.90).astype(float).multiply(weights, axis=0).sum())
            h_above_99 = float((loading > 0.99).astype(float).multiply(weights, axis=0).sum())
            mean_loading = float(loading.multiply(weights, axis=0).sum() / weights.sum())
        else:
            h_above_80 = h_above_90 = h_above_99 = 0.0
            mean_loading = 0.0

        rows.append({
            "line_id"               : line_name,
            "from_region"           : name_of(line["bus0"], names),
            "to_region"             : name_of(line["bus1"], names),
            "from_cluster_id"       : line["bus0"],
            "to_cluster_id"         : line["bus1"],
            "length_km"             : round(float(line.get("length", 0.0)), 1),
            "capacity_initial_MW"   : round(s_nom_initial, 1),
            "capacity_final_MW"     : round(s_nom_eff, 1),
            "capacity_added_MW"     : round(s_nom_eff - s_nom_initial, 1),
            "gross_flow_GWh"        : round(gross_flow_mwh * MWH_TO_GWH, 1),
            "net_flow_GWh"          : round(net_flow_mwh * MWH_TO_GWH, 1),
            "mean_loading_%"        : round(100 * mean_loading, 2),
            "hours_above_80%"       : round(h_above_80, 0),
            "hours_above_90%"       : round(h_above_90, 0),
            "hours_above_99%"       : round(h_above_99, 0),
        })

    return pd.DataFrame(rows).sort_values("gross_flow_GWh", ascending=False).reset_index(drop=True)


def compute_new_capacity(n, names):
    """Capacity that the optimizer chose to build, both for generators and
    for transmission lines. The 'names' dict maps cluster_id to a human name."""
    rows = []

    # Generator expansion: only those with the new_ prefix and extendable
    gens = n.generators
    new_mask = gens.index.str.startswith(NEW_GENERATOR_PREFIX) & gens["p_nom_extendable"]
    for g in gens[new_mask].index:
        bus = gens.at[g, "bus"]
        rows.append({
            "type"                   : "generator",
            "name"                   : g,
            "carrier"                : gens.at[g, "carrier"],
            "region"                 : name_of(bus, names),
            "cluster_id"             : bus,
            "new_capacity_MW"        : round(float(gens.at[g, "p_nom_opt"]), 2),
        })

    # Line expansion
    if len(n.lines) > 0:
        for line_name, line in n.lines.iterrows():
            if not line.get("s_nom_extendable", False):
                continue
            initial = float(line["s_nom"])
            final   = float(line.get("s_nom_opt", initial))
            added   = final - initial
            rows.append({
                "type"                   : "line",
                "name"                   : f"line_{line_name}",
                "carrier"                : "transmission",
                "region"                 : f"{name_of(line['bus0'], names)} <-> {name_of(line['bus1'], names)}",
                "cluster_id"             : f"{line['bus0']} <-> {line['bus1']}",
                "new_capacity_MW"        : round(added, 2),
            })

    return pd.DataFrame(rows)


# =============================================================================
# STEP 4 — Save
# =============================================================================

def save_results(n, output_dir, scenario, k, solver, status, elapsed):
    print(f"\n[3/4] Computing summaries ...")
    names = load_cluster_names(k)
    if names:
        print(f"  Cluster names loaded: {len(names)} regions")

    summary_global  = compute_summary_global(n, scenario, k, solver, status, elapsed)
    summary_carrier = compute_summary_by_carrier(n)
    summary_cluster = compute_summary_by_cluster(n, names)
    summary_line    = compute_summary_by_line(n, names)
    new_capacity    = compute_new_capacity(n, names)

    print(f"\n[4/4] Saving outputs to {output_dir} ...")
    os.makedirs(output_dir, exist_ok=True)

    nc_path = output_dir / f"results_{scenario}_k{k}.nc"
    n.export_to_netcdf(nc_path)
    print(f"  Saved : {nc_path.name}")

    summary_global.to_csv(output_dir / "summary_global.csv", index=False)
    print(f"  Saved : summary_global.csv")

    summary_carrier.to_csv(output_dir / "summary_by_carrier.csv", index=False)
    print(f"  Saved : summary_by_carrier.csv")

    summary_cluster.to_csv(output_dir / "summary_by_cluster.csv", index=False)
    print(f"  Saved : summary_by_cluster.csv")

    summary_line.to_csv(output_dir / "summary_by_line.csv", index=False)
    print(f"  Saved : summary_by_line.csv")

    new_capacity.to_csv(output_dir / "new_capacity.csv", index=False)
    print(f"  Saved : new_capacity.csv")

    return summary_global, summary_carrier, summary_cluster, summary_line, new_capacity


def print_headline(summary_global, summary_carrier, new_capacity):
    """Prints the key numbers at the very end so the user sees them clearly."""
    print(f"\n{'='*70}")
    print(f"HEADLINE RESULTS")
    print(f"{'='*70}")

    g = summary_global.iloc[0]
    print(f"\n  Total demand          : {g['total_demand_TWh']:>15.3f} TWh")
    print(f"  Total generation      : {g['total_generation_TWh']:>15.3f} TWh")
    print(f"  Load shedding         : {g['load_shedding_GWh']:>15.1f} GWh "
          f"({g['load_shedding_%_of_demand']:.4f}% of demand)")
    print(f"  Renewable share       : {g['renewable_share_%']:>15.2f} %")
    if g.get("total_annual_cost_USD") is not None:
        print(f"  Total annual cost     : {g['total_annual_cost_billion_USD']:>15.3f} billion USD")
    print(f"  Solve time            : {fmt_seconds(g['solve_time_seconds'])}")

    if not summary_carrier.empty:
        print(f"\n  Generation by carrier (top 5):")
        for _, row in summary_carrier.head(5).iterrows():
            print(f"    {row['carrier']:<15} : "
                  f"{row['generation_GWh']:>14,.1f} GWh   "
                  f"capacity {row['total_capacity_MW']:>10,.0f} MW   "
                  f"CF {row['capacity_factor_%']:>5.1f}%")

    if not new_capacity.empty:
        gen_built = new_capacity[new_capacity["type"] == "generator"]
        if not gen_built.empty:
            built_by_carrier = gen_built.groupby("carrier")["new_capacity_MW"].sum()
            print(f"\n  New generation built (by carrier):")
            for c, mw in built_by_carrier.sort_values(ascending=False).items():
                print(f"    {c:<15} : {mw:>10,.0f} MW")

        line_built = new_capacity[new_capacity["type"] == "line"]
        if not line_built.empty:
            total_line_mw = line_built["new_capacity_MW"].sum()
            print(f"\n  Transmission added    : {total_line_mw:>10,.0f} MW (sum across lines)")


# =============================================================================
# MAIN
# =============================================================================

def main():
    args = parse_args()

    print("=" * 70)
    print(f"22_run_scenario.py -- optimize scenario {args.scenario} K={args.k}")
    print("=" * 70)
    print(f"Scenario : {args.scenario}")
    print(f"K        : {args.k}")
    print(f"Solver   : {args.solver}")

    input_file, output_dir = get_paths(args.scenario, args.k)

    n = load_scenario(input_file)
    status, condition, elapsed = solve(n, args.solver)

    summary_global, summary_carrier, _, _, new_capacity = save_results(
        n, output_dir, args.scenario, args.k, args.solver, status, elapsed
    )

    print_headline(summary_global, summary_carrier, new_capacity)

    print(f"\n{'='*70}")
    print(f"Optimization complete.")
    print(f"All outputs in: {output_dir}")
    print(f"Next step: script 23 to compare scenarios.")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()
