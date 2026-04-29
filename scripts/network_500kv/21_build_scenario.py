"""
21_build_scenario.py
Builds a future scenario on top of a clustered network produced by script 20B.
The scenario applies a uniform demand growth, adds expandable generators in
each cluster for the technologies that can grow (CCGT, OCGT, diesel, solar,
wind), enables expansion of existing transmission lines, and inserts virtual
load-shedding generators to guarantee feasibility.

The result is a PyPSA Network ready to be optimized by script 22 (capacity
expansion + dispatch in a single optimization).

Inputs:
    networks/clusters/cluster_k{K}.nc                                 (script 20B)
    data/external/technology_data/costs_2035_US.csv                   (ATB)

Output:
    networks/scenarios/scenario_{SCENARIO_NAME}_k{K}.nc

What this script does (high level):
    1. Loads the base clustered network (year 2024 already attached).
    2. Scales every demand series by (1 + growth)^(target_year - base_year).
    3. Reads ATB cost CSV and normalizes to USD/MW with EUR->USD conversion.
    4. For each cluster + each expandable carrier:
         a. Computes annualized capital_cost using the ATB WACC for the carrier.
         b. Computes marginal_cost from VOM + fuel_price/efficiency.
         c. For solar/wind, attaches an hourly p_max_pu profile inherited from
            the closest existing generator of the same carrier (heuristic).
         d. Adds a Generator with p_nom=0, p_nom_extendable=True.
    5. Marks all inter-cluster lines as s_nom_extendable=True with
       capital_cost = annualized HVAC overhead per MW per km, multiplied by
       the geodesic length of the line between cluster centroids.
    6. Adds a virtual load-shedding generator per cluster with very high
       marginal cost, so the optimization is always feasible.
    7. Saves the .nc and prints a summary.

What this script does NOT do:
    - It does not optimize. That is script 22.
    - It does not produce results, reports or KPIs.
    - It does not regenerate clusters. The clustering is fixed (script 20B).

Modeling decisions (set in CONFIGURATION below — edit there to vary scenarios):
    - Demand grows uniformly: every load series is multiplied by the same factor.
    - Capacity expansion is endogenous (the model decides how much to build).
    - No locational constraints on new generators (model is free to put solar
      anywhere, wind anywhere, etc.). First scenario only — to be refined.
    - Existing 2024 generators are kept untouched (p_nom_extendable=False by
      default in PyPSA when not specified).
    - WACC is taken from ATB per technology (CCGT 5.36%, solar 4.68%, etc.).
      Technologies coming from Danish Energy Agency (OCGT, oil) do not bring
      a discount rate — DEFAULT_WACC is used for them.
    - The override variable WACC_OVERRIDE allows running a future iteration
      with a single uniform WACC (e.g. 0.16 for Argentina) without changing
      the script structure.

Run from the repository root:
    python scripts/network_500kv/21_build_scenario.py
"""

import os
import sys
import math
from pathlib import Path

import pandas as pd
import yaml
import pypsa


# =============================================================================
# CONFIGURATION
# =============================================================================

_cfg = yaml.safe_load(open(Path(__file__).parents[2] / "config.yaml"))
REPO_DIR     = Path(_cfg["repo_dir"])
EXTERNAL_DIR = Path(_cfg["external_data_dir"])

# --- Scenario identity ---
SCENARIO_NAME = "2035_BAU"
BASE_YEAR     = 2024
TARGET_YEAR   = 2035
K             = 10           # which cluster_kN.nc to use

# --- Demand growth ---
DEMAND_GROWTH_RATE = 0.03    # annual compound rate

# --- Time aggregation ---
# Three modes are supported. Choose one with TIME_AGGREGATION:
#
#   "none"    : full hourly resolution (8784 snapshots). Most accurate, slowest.
#   "uniform" : uniform downsampling. Keeps every TIME_RESOLUTION_HOURS-th snapshot.
#               Each snapshot is weighted by TIME_RESOLUTION_HOURS hours so yearly
#               totals are preserved. Fast but loses peaks (averages over the
#               skipped hours when the model dispatches against a single hour).
#   "tsam"    : typical-period clustering via the tsam library (FZJ-IEK-3).
#               The full year is reduced to N typical days (24h periods) chosen
#               by hierarchical clustering on the joint time series of demand
#               and renewable availability profiles. Each typical day is weighted
#               by the number of real days it represents. This is the standard
#               approach in PyPSA-Eur and academic literature for capacity
#               expansion problems with high renewable share.
#
# Trade-offs at K=10 expansion problem (rough estimates on a 16 GB laptop):
#   - "none"    : ~5.7 M variables, 2-4 hours solve, can fail numerically.
#   - "uniform" : ~1.9 M variables (factor 3), 30-60 min solve.
#   - "tsam"    : ~250 k variables (16 days * 24 h), 5-15 min solve.
TIME_AGGREGATION = "tsam"

# Used only when TIME_AGGREGATION = "uniform"
TIME_RESOLUTION_HOURS = 3

# Used only when TIME_AGGREGATION = "tsam"
TSAM_TYPICAL_PERIODS  = 16          # number of representative days
TSAM_HOURS_PER_PERIOD = 24          # 24 h per period = daily clustering
TSAM_CLUSTER_METHOD   = "hierarchical"  # tsam options: "hierarchical", "k_means", "k_medoids"
TSAM_REPRESENTATION   = "distributionAndMinMaxRepresentation"
# "distributionAndMinMax" keeps both the distribution shape AND the extreme
# values within each cluster, which is important for capacity sizing
# (otherwise typical periods can underestimate peak demand).

# --- ATB filtering ---
ATB_FINANCIAL_CASE = "Market"
ATB_SCENARIO       = "Moderate"

# --- Currency conversion (EUR -> USD) ---
# Some entries in the ATB CSV come from the Danish Energy Agency in EUR.
# We normalize everything to USD using a single conversion rate.
EUR_TO_USD = 1.10

# --- Fuel prices (USD/MWh thermal) at TARGET_YEAR ---
# Provided by Gustavo from EIA AEO 2024, file Precios_PyPSA.xlsx.
# Conversion: 1 USD/MMBtu = 3.412 USD/MWh_th (1 MMBtu = 0.293 MWh_th).
GAS_PRICE_USD_MWH_TH      = 5.05  * 3.412   # ~17.2  Henry Hub natural gas
DIESEL_PRICE_USD_MWH_TH   = 22.99 * 3.412   # ~78.5  distillate fuel oil
FUEL_OIL_PRICE_USD_MWH_TH = 16.07 * 3.412   # ~54.9  residual fuel oil (not used yet)

# --- Cost of capital (WACC) ---
# WACC_OVERRIDE = None  -> use ATB's per-technology discount rate, with
#                          DEFAULT_WACC for technologies that don't bring one.
# WACC_OVERRIDE = float -> override all technologies with this single rate.
#
# First run: ATB defaults (Tavo: "primera corrida tomamos WACC de ATB").
# Future runs: WACC_OVERRIDE = 0.16 (Gustavo: typical Argentina WACC).
WACC_OVERRIDE = None
DEFAULT_WACC  = 0.0536        # CCGT-like, used for OCGT/oil (no rate in DEA data)

# --- Carriers that can be expanded by the optimizer ---
# Each entry maps the PyPSA carrier name (used in our network) to the ATB
# technology name (used as key in the costs CSV).
EXPANDABLE_CARRIERS = {
    "ccgt"  : "CCGT",
    "ocgt"  : "OCGT",
    "diesel": "oil",
    "solar" : "solar-utility",
    "wind"  : "onwind",
}

# Carriers whose marginal cost depends on natural gas
GAS_CARRIERS = {"ccgt", "ocgt"}

# --- Load shedding ---
# A virtual generator added at each cluster with infinite p_nom and very high
# marginal cost. Guarantees feasibility. If shedding shows up in results, it
# means the system couldn't meet demand even at this price — it is a real
# scenario output, not a modeling failure.
LOAD_SHEDDING_COST_USD_MWH = 5_000
LOAD_SHEDDING_CARRIER      = "load_shedding"

# --- Transmission expansion (HVAC overhead) ---
# From ATB / Danish Energy Agency Technology Data for Energy Transport (Jul 2025).
HVAC_INVESTMENT_EUR_MW_KM = 720.0
HVAC_FOM_PCT              = 1.5      # %/year
HVAC_LIFETIME_YEARS       = 40
HVAC_WACC_FALLBACK        = 0.0536   # transmission has no scenario in ATB

# --- Paths ---
INPUT_NETWORK = REPO_DIR / f"data/network_500kv/clusters/cluster_k{K}.nc"
ATB_FILE      = EXTERNAL_DIR / "Technology_data/costs_2035_US.csv"
OUTPUT_DIR    = REPO_DIR / "networks/scenarios"
OUTPUT_FILE   = OUTPUT_DIR / f"scenario_{SCENARIO_NAME}_k{K}.nc"

# --- Derived ---
N_YEARS       = TARGET_YEAR - BASE_YEAR
DEMAND_FACTOR = (1 + DEMAND_GROWTH_RATE) ** N_YEARS

# --- Expansion limits per technology (MW per cluster) ---
EXPANSION_LIMITS_MW = {
    "solar": 5000 / K,   # Total cap: 5000 MW distributed across K clusters
    "wind":  3000 / K,   # Total cap: 3000 MW distributed across K clusters
}

# =============================================================================
# HELPERS
# =============================================================================

def verify_inputs():
    files = {
        f"cluster_k{K}.nc"  : INPUT_NETWORK,
        "costs_2035_US.csv" : ATB_FILE,
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


def annualize(capex, wacc, lifetime):
    """Capital recovery factor: converts upfront CAPEX into a constant
    annual payment over `lifetime` years at discount rate `wacc`."""
    if wacc <= 0:
        return capex / lifetime
    crf = (wacc * (1 + wacc) ** lifetime) / ((1 + wacc) ** lifetime - 1)
    return capex * crf


def haversine_km(lat1, lon1, lat2, lon2):
    """Great-circle distance in km between two points (decimal degrees)."""
    R = 6371.0  # Earth radius in km
    lat1_r, lat2_r = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1_r) * math.cos(lat2_r) * math.sin(dlon / 2) ** 2
    c = 2 * math.asin(math.sqrt(a))
    return R * c


# =============================================================================
# STEP 1 — Load base clustered network
# =============================================================================

def load_network():
    print("\n[1/7] Loading base clustered network ...")
    n = pypsa.Network(INPUT_NETWORK)
    print(f"  Buses (clusters)  : {len(n.buses)}")
    print(f"  Generators        : {len(n.generators)}")
    print(f"  Loads             : {len(n.loads)}")
    print(f"  Lines             : {len(n.lines)}")
    print(f"  Links             : {len(n.links)}")
    print(f"  Snapshots         : {len(n.snapshots)}")
    return n


# =============================================================================
# STEP 2 — Scale demand
# =============================================================================

def scale_demand(n):
    print(f"\n[2/7] Scaling demand by factor {DEMAND_FACTOR:.4f} "
          f"({DEMAND_GROWTH_RATE:.0%} for {N_YEARS} years) ...")

    if n.loads_t.p_set.empty:
        print("  [WARN] No demand time series found in network.")
        return

    pre_peak = n.loads_t.p_set.sum(axis=1).max()
    n.loads_t.p_set = n.loads_t.p_set * DEMAND_FACTOR
    post_peak = n.loads_t.p_set.sum(axis=1).max()

    print(f"  System peak before : {pre_peak:>10,.1f} MW")
    print(f"  System peak after  : {post_peak:>10,.1f} MW")


def resample_snapshots(n):
    """Dispatcher for time aggregation. Routes to the appropriate method
    according to TIME_AGGREGATION. Each method is responsible for setting
    n.snapshots and n.snapshot_weightings consistently so that yearly totals
    (energy, costs, emissions) are preserved."""
    print(f"\n[2b/7] Time aggregation ...")
    print(f"  Mode : {TIME_AGGREGATION}")

    if TIME_AGGREGATION == "none":
        print(f"  Full hourly resolution kept ({len(n.snapshots)} snapshots).")
        return

    if TIME_AGGREGATION == "uniform":
        _aggregate_uniform(n)
        return

    if TIME_AGGREGATION == "tsam":
        _aggregate_tsam(n)
        return

    raise ValueError(f"Unknown TIME_AGGREGATION mode: {TIME_AGGREGATION!r}. "
                     f"Use 'none', 'uniform' or 'tsam'.")


def _aggregate_uniform(n):
    """Uniform downsampling: keep every TIME_RESOLUTION_HOURS-th snapshot."""
    if TIME_RESOLUTION_HOURS == 1:
        print(f"  TIME_RESOLUTION_HOURS = 1, no downsampling needed.")
        return

    n_before = len(n.snapshots)
    new_snapshots = n.snapshots[::TIME_RESOLUTION_HOURS]
    n.set_snapshots(new_snapshots)
    n.snapshot_weightings.loc[:, :] = float(TIME_RESOLUTION_HOURS)
    n_after = len(n.snapshots)

    print(f"  Resolution         : 1 h  ->  {TIME_RESOLUTION_HOURS} h")
    print(f"  Snapshots          : {n_before}  ->  {n_after}")
    print(f"  Weight per snapshot: {TIME_RESOLUTION_HOURS} h")
    weighted_total = n.snapshot_weightings["objective"].sum()
    print(f"  Total weighted hrs : {weighted_total:.0f}  (expected ~ {n_before})")


def _aggregate_tsam(n):
    """TSAM-based clustering: reduces the year to TSAM_TYPICAL_PERIODS typical
    days (24 h each) chosen by hierarchical clustering on demand + RES profiles.
    Each typical day is weighted by the number of real days it represents.

    Implementation outline:
      1. Build the input DataFrame for tsam: one column per time series we
         want to capture (loads + p_max_pu of solar + wind generators).
      2. Run TimeSeriesAggregation. tsam returns a `clusterPeriodIdx` that maps
         each real day to a typical-day cluster, plus the typical periods'
         time series themselves.
      3. Construct the new snapshot list and weightings. Each typical day's 24
         hours becomes 24 snapshots; each gets weight = (#real days mapped to
         this cluster), so yearly totals integrate correctly.
      4. Replace n.loads_t.p_set and n.generators_t.p_max_pu with the typical-
         day series.
    """
    from tsam.timeseriesaggregation import TimeSeriesAggregation

    n_before = len(n.snapshots)
    print(f"  Snapshots before   : {n_before}")
    print(f"  Typical periods    : {TSAM_TYPICAL_PERIODS}")
    print(f"  Hours per period   : {TSAM_HOURS_PER_PERIOD}")
    print(f"  Cluster method     : {TSAM_CLUSTER_METHOD}")
    print(f"  Representation     : {TSAM_REPRESENTATION}")

    # Save original loads time series for proportional redistribution later.
    # After TSAM aggregation we replace n.loads_t.p_set, so we need to
    # remember the original per-Load shares before we overwrite them.
    _orig_loads_p_set = n.loads_t.p_set.copy() if not n.loads_t.p_set.empty else pd.DataFrame()

    # ---- Step 1: collect the time series that drive the system dynamics ----
    # tsam needs all relevant time series in a single DataFrame indexed by time.
    # We include:
    #   - per-cluster total demand
    #   - per-generator p_max_pu for solar and wind (the variable RES carriers)
    # Other carriers (thermal, hydro, nuclear) are dispatchable so their
    # availability is constant and does not drive day variability.

    raw_index = n.snapshots
    raw_inputs = pd.DataFrame(index=raw_index)

    # Demand: sum loads per bus to get one demand series per cluster
    if not n.loads_t.p_set.empty and len(n.loads) > 0:
        load_to_bus = n.loads["bus"]
        demand_per_bus = (
            n.loads_t.p_set.T.groupby(load_to_bus).sum().T
        )
        for col in demand_per_bus.columns:
            raw_inputs[f"demand__{col}"] = demand_per_bus[col]

   # Generator availability profiles: one column per (carrier, cluster) pair.
    # Instead of feeding TSAM all individual generators (would be hundreds, very
    # slow), we aggregate them into a per-carrier per-cluster weighted average
    # profile:
    #
    #     perfil[carrier, cluster](t) = Σ_g (p_max_pu_g(t) × p_nom_g) / Σ_g p_nom_g
    #
    # where the sum runs over generators g of the given carrier sitting on
    # the given cluster. This captures the aggregate dispatch ceiling pattern
    # of each carrier in each region (e.g. all hydro in Comahue), which is
    # what really drives system dynamics. After TSAM, each individual generator
    # recovers the profile of its carrier-cluster pair.
    #
    # We only include carrier-cluster pairs whose aggregate profile actually
    # varies along the year (relative range > eps). Carriers with constant
    # availability (typical of thermal generators where p_max_pu = 1 always)
    # are skipped — TSAM doesn't need them to find typical periods, and the
    # generators recover p_max_pu = 1 downstream.
    carrier_cluster_profiles = {}   # (carrier, bus) -> Series
    if not n.generators_t.p_max_pu.empty:
        eps_relative = 0.05
        # Group p_max_pu columns by (carrier, bus)
        for (carrier, bus), gens_in_group in n.generators.groupby(["carrier", "bus"]):
            cols_with_profile = [g for g in gens_in_group.index
                                 if g in n.generators_t.p_max_pu.columns]
            if not cols_with_profile:
                continue
            p_nom = n.generators.loc[cols_with_profile, "p_nom"].astype(float)
            total_p_nom = float(p_nom.sum())
            if total_p_nom <= 0:
                continue
            # Weighted average profile across all generators in this group
            weighted_profile = (
                n.generators_t.p_max_pu[cols_with_profile]
                .multiply(p_nom, axis=1).sum(axis=1) / total_p_nom
            )
            pmax = float(weighted_profile.max())
            if pmax <= 0:
                continue
            relative_range = (pmax - float(weighted_profile.min())) / pmax
            if relative_range <= eps_relative:
                continue   # effectively constant, skip
            carrier_cluster_profiles[(carrier, bus)] = weighted_profile
            raw_inputs[f"pmaxpu__{carrier}__{bus}"] = weighted_profile

        print(f"  Aggregate (carrier, cluster) profiles fed to tsam : "
              f"{len(carrier_cluster_profiles)}")

    print(f"  Series fed to tsam : {raw_inputs.shape[1]} columns "
          f"({n_before} rows)")

    # ---- Step 2: run TSAM ----
    n_periods_real = n_before // TSAM_HOURS_PER_PERIOD
    if n_periods_real * TSAM_HOURS_PER_PERIOD != n_before:
        # The year has 8784 hours / 24 h = 366 days exactly for a leap year,
        # which is the case here. If somehow it doesn't divide evenly, drop
        # the remainder so tsam can run.
        print(f"  [WARN] Snapshots ({n_before}) not divisible by hours-per-period "
              f"({TSAM_HOURS_PER_PERIOD}); truncating to {n_periods_real * TSAM_HOURS_PER_PERIOD}.")
        raw_inputs = raw_inputs.iloc[:n_periods_real * TSAM_HOURS_PER_PERIOD]

    aggregation = TimeSeriesAggregation(
        timeSeries        = raw_inputs,
        noTypicalPeriods  = TSAM_TYPICAL_PERIODS,
        hoursPerPeriod    = TSAM_HOURS_PER_PERIOD,
        clusterMethod     = TSAM_CLUSTER_METHOD,
        representationMethod = TSAM_REPRESENTATION,
    )
    typical_periods = aggregation.createTypicalPeriods()

    # cluster_index_per_period: array of length n_periods_real giving, for each
    # real day in the year, which typical-day cluster it belongs to.
    cluster_per_real_period = aggregation.clusterPeriodIdx
    # cluster_period_no_occur: dict {cluster_id -> number of real periods mapped}
    occurrences = aggregation.clusterPeriodNoOccur

    print(f"  Typical periods generated: {len(occurrences)}")
    for cid, occ in sorted(occurrences.items()):
        print(f"    Period {cid}: represents {occ} real days")

    # ---- Step 3: build new snapshots and weights ----
    # We name new snapshots after the medoid period's first hour so they remain
    # interpretable in QGIS / time series plots.
    new_snapshots = []
    new_weights   = []
    new_data      = {col: [] for col in raw_inputs.columns}

    # Find a representative real period for each cluster (the first one mapped to it)
    cluster_to_first_real_period = {}
    for real_period_idx, cluster_id in enumerate(cluster_per_real_period):
        if cluster_id not in cluster_to_first_real_period:
            cluster_to_first_real_period[cluster_id] = real_period_idx

    for cluster_id in sorted(occurrences.keys()):
        n_occ = occurrences[cluster_id]
        # Slice the typical_periods DataFrame for this cluster
        period_df = typical_periods.loc[cluster_id]
        # Use a synthetic timestamp anchored in 2024 for traceability:
        # day 1 of the year + cluster_id, hour by hour.
        base_day = pd.Timestamp(f"{BASE_YEAR}-01-01") + pd.Timedelta(days=cluster_id)
        for h in range(TSAM_HOURS_PER_PERIOD):
            ts = base_day + pd.Timedelta(hours=h)
            new_snapshots.append(ts)
            new_weights.append(n_occ)
            for col in raw_inputs.columns:
                new_data[col].append(period_df.loc[h, col])

    new_snapshots = pd.DatetimeIndex(new_snapshots, name="snapshot")
    new_inputs    = pd.DataFrame(new_data, index=new_snapshots)

    # ---- Step 4: apply to the network ----
    n.set_snapshots(new_snapshots)
    weights_series = pd.Series(new_weights, index=new_snapshots, dtype=float)
    for col in n.snapshot_weightings.columns:
        n.snapshot_weightings[col] = weights_series

    # Re-attach demand series (one Load per bus, sum recovered from prefix).
    #
    # IMPORTANT: per_bus_new[bus] is the TOTAL demand at that bus (sum of all
    # original Loads attached to it). When the network has multiple Loads on
    # the same bus, we must DISTRIBUTE the bus total among them in the same
    # proportion they had originally — otherwise each Load receives the full
    # bus demand and the network total gets multiplied by ~ N_loads_per_bus.
    if not n.loads_t.p_set.empty and len(n.loads) > 0:
        load_to_bus = n.loads["bus"]
        # Build per-bus demand from new_inputs
        per_bus_new = pd.DataFrame(index=new_snapshots)
        for col in new_inputs.columns:
            if col.startswith("demand__"):
                bus = col[len("demand__"):]
                per_bus_new[bus] = new_inputs[col]

        # Compute each Load's share of its bus's demand using the ORIGINAL
        # (pre-aggregation) hourly time series. We use the mean over the year
        # as a stable proxy. If a bus has only one Load, its share is 1.
        # n.loads_t.p_set has already been replaced by this point in the
        # function — we need the PRE-aggregation series. Save it before TSAM
        # runs (see top of _aggregate_tsam).
        # Workaround: compute shares directly from the demand_per_bus DataFrame
        # we built earlier, which is still in scope as `demand_per_bus`.
        load_shares = {}
        for load_name in n.loads.index:
            bus = n.loads.at[load_name, "bus"]
            # Original mean of this Load
            orig_mean_load = float(_orig_loads_p_set[load_name].mean())
            # Original mean total demand at this bus
            orig_mean_bus  = float(_orig_loads_p_set[load_to_bus[load_to_bus == bus].index].sum(axis=1).mean())
            if orig_mean_bus > 0:
                load_shares[load_name] = orig_mean_load / orig_mean_bus
            else:
                load_shares[load_name] = 0.0

        # Build new loads_t.p_set: each Load gets its share of its bus total.
        new_loads_p_set = pd.DataFrame(index=new_snapshots,
                                       columns=n.loads.index, dtype=float)
        for load_name in n.loads.index:
            bus = n.loads.at[load_name, "bus"]
            share = load_shares[load_name]
            if bus in per_bus_new.columns:
                new_loads_p_set[load_name] = per_bus_new[bus].values * share
            else:
                new_loads_p_set[load_name] = 0.0
        n.loads_t.p_set = new_loads_p_set

    # Re-attach generator availability profiles. Each generator inherits the
    # typical-day profile of its (carrier, cluster) group. Generators whose
    # group was skipped (constant aggregate profile) get p_max_pu = 1.
    if not n.generators_t.p_max_pu.empty:
        new_pmaxpu = pd.DataFrame(index=new_snapshots,
                                  columns=n.generators_t.p_max_pu.columns,
                                  dtype=float)
        for gen in n.generators_t.p_max_pu.columns:
            if gen not in n.generators.index:
                new_pmaxpu[gen] = 1.0
                continue
            carrier = n.generators.at[gen, "carrier"]
            bus     = n.generators.at[gen, "bus"]
            col_key = f"pmaxpu__{carrier}__{bus}"
            if col_key in new_inputs.columns:
                new_pmaxpu[gen] = new_inputs[col_key].values
            else:
                # Group's aggregate profile was constant or absent — broadcast 1.0
                new_pmaxpu[gen] = 1.0
        n.generators_t.p_max_pu = new_pmaxpu

    # Sanity check: total weighted hours must equal original hourly count
    weighted_total = n.snapshot_weightings["objective"].sum()
    print(f"  Snapshots after    : {len(n.snapshots)}")
    print(f"  Total weighted hrs : {weighted_total:.0f}  (expected ~ {n_before})")

    if abs(weighted_total - n_before) > TSAM_HOURS_PER_PERIOD:
        print(f"  [WARN] Weighted hour count differs from original by more than "
              f"one period ({abs(weighted_total - n_before):.0f} h). "
              f"Yearly totals may be slightly off.")


# =============================================================================
# STEP 3 — Load and normalize ATB costs
# =============================================================================

def load_atb_costs():
    """Returns a dict: {tech_name -> {parameter -> value_in_normalized_units}}.

    Normalization:
      - investment    : USD/MW   (converted from USD/kW or EUR/kW)
      - FOM           : %/year   (kept as %)
      - VOM           : USD/MWh  (converted from EUR/MWh)
      - fuel          : USD/MWh_th (converted from EUR/MWh_th)
      - lifetime      : years
      - efficiency    : per unit
      - CO2 intensity : tCO2/MWh_th
      - discount rate : per unit
    """
    print("\n[3/7] Loading ATB cost data ...")
    df = pd.read_csv(ATB_FILE)

    techs_needed = set(EXPANDABLE_CARRIERS.values())
    df = df[df["technology"].isin(techs_needed)].copy()

    # Filter scenario where applicable. Some rows have NaN in financial_case/scenario
    # (those entries that come from Danish Energy Agency are scenario-agnostic).
    has_scenario = df["scenario"].notna() & df["financial_case"].notna()
    scen_filter = (
        (~has_scenario) |
        ((df["financial_case"] == ATB_FINANCIAL_CASE) & (df["scenario"] == ATB_SCENARIO))
    )
    df = df[scen_filter].copy()

    costs = {tech: {} for tech in techs_needed}

    for _, row in df.iterrows():
        tech  = row["technology"]
        param = row["parameter"]
        value = row["value"]
        unit  = row["unit"]

        # Normalize investment to USD/MW
        if param == "investment":
            if unit == "USD/kW":
                value = value * 1_000
            elif unit == "EUR/kW":
                value = value * 1_000 * EUR_TO_USD
            else:
                print(f"  [WARN] Unknown investment unit '{unit}' for {tech}")
                continue

        # Normalize VOM to USD/MWh
        elif param == "VOM":
            if unit == "USD/MWh":
                pass
            elif unit == "EUR/MWh":
                value = value * EUR_TO_USD
            else:
                print(f"  [WARN] Unknown VOM unit '{unit}' for {tech}")
                continue

        # Normalize fuel cost to USD/MWh_th
        elif param == "fuel":
            if unit == "USD/MWh_th":
                pass
            elif unit == "EUR/MWh_th":
                value = value * EUR_TO_USD
            else:
                print(f"  [WARN] Unknown fuel unit '{unit}' for {tech}")
                continue

        costs[tech][param] = value

    # Print summary table
    print(f"\n  ATB normalized cost table (Market+Moderate, fallbacks for DEA-sourced):")
    print(f"  {'Tech':<15} {'CAPEX USD/MW':>14} {'FOM %':>8} {'VOM USD/MWh':>13} "
          f"{'Eff':>7} {'Life':>6} {'WACC':>8}")
    print(f"  {'-'*15} {'-'*14} {'-'*8} {'-'*13} {'-'*7} {'-'*6} {'-'*8}")
    for tech in sorted(techs_needed):
        c = costs[tech]
        capex = c.get("investment",    None)
        fom   = c.get("FOM",           None)
        vom   = c.get("VOM",           0.0)
        eff   = c.get("efficiency",    None)
        life  = c.get("lifetime",      None)
        wacc  = c.get("discount rate", DEFAULT_WACC)

        capex_s = f"{capex:>14,.0f}" if capex is not None else f"{'NA':>14}"
        fom_s   = f"{fom:>8.2f}"     if fom   is not None else f"{'NA':>8}"
        vom_s   = f"{vom:>13,.2f}"
        eff_s   = f"{eff:>7.3f}"     if eff   is not None else f"{'NA':>7}"
        life_s  = f"{life:>6.0f}"    if life  is not None else f"{'NA':>6}"
        wacc_s  = f"{wacc:>8.4f}"
        print(f"  {tech:<15} {capex_s} {fom_s} {vom_s} {eff_s} {life_s} {wacc_s}")

    return costs


# =============================================================================
# STEP 4 — Add expandable generators
# =============================================================================

def get_carrier_profile_template(n, carrier):
    """For a given carrier (e.g. "solar"), returns a representative hourly
    p_max_pu series taken from existing generators of that carrier. Used as
    template for new expandable generators. Returns None if no generator of
    that carrier exists in the network."""
    gens_of_carrier = n.generators[n.generators["carrier"] == carrier]
    if len(gens_of_carrier) == 0:
        return None
    if n.generators_t.p_max_pu.empty:
        return None

    available = [g for g in gens_of_carrier.index if g in n.generators_t.p_max_pu.columns]
    if not available:
        return None

    # Average across all existing generators of this carrier as template.
    # This gives a single representative profile for the whole country and
    # simplicity. Future refinement: per-cluster profile from local generators.
    return n.generators_t.p_max_pu[available].mean(axis=1)


def compute_marginal_cost(carrier, costs):
    """marginal_cost (USD/MWh_e) = VOM + fuel_price / efficiency"""
    atb_tech = EXPANDABLE_CARRIERS[carrier]
    c = costs[atb_tech]
    vom = c.get("VOM", 0.0)
    eff = c.get("efficiency", None)

    if carrier in GAS_CARRIERS:
        fuel_price = GAS_PRICE_USD_MWH_TH
    elif carrier == "diesel":
        fuel_price = DIESEL_PRICE_USD_MWH_TH
    else:
        fuel_price = 0.0   # solar, wind: no fuel

    if fuel_price == 0.0 or eff is None:
        return vom

    return vom + fuel_price / eff


def compute_capital_cost(carrier, costs):
    """capital_cost (USD/MW/year) = annualized CAPEX + FOM × CAPEX
    where annualization uses ATB's discount rate (or override / default)."""
    atb_tech = EXPANDABLE_CARRIERS[carrier]
    c = costs[atb_tech]

    capex    = c["investment"]              # USD/MW
    fom_pct  = c.get("FOM", 0.0)            # %/year
    lifetime = c.get("lifetime", 25)        # years
    wacc     = WACC_OVERRIDE if WACC_OVERRIDE is not None \
               else c.get("discount rate", DEFAULT_WACC)

    annualized = annualize(capex, wacc, lifetime)
    fixed_om   = capex * (fom_pct / 100.0)
    return annualized + fixed_om


def add_expandable_generators(n, costs):
    print("\n[4/7] Adding expandable generators ...")

    n_added = 0
    profile_cache = {}

    for carrier in EXPANDABLE_CARRIERS.keys():
        capital_cost  = compute_capital_cost(carrier, costs)
        marginal_cost = compute_marginal_cost(carrier, costs)
        atb_tech      = EXPANDABLE_CARRIERS[carrier]
        eff           = costs[atb_tech].get("efficiency", None)

        # Profile template (only needed for variable RES)
        profile = None
        if carrier in {"solar", "wind"}:
            profile = get_carrier_profile_template(n, carrier)
            if profile is None:
                print(f"  [WARN] No existing {carrier} generator to derive profile; "
                      f"new {carrier} generators will use p_max_pu = 1 (always available).")

        profile_cache[carrier] = profile

        for cluster in n.buses.index:
            gen_name = f"new_{carrier}_{cluster}"

            kwargs = dict(
                bus               = cluster,
                carrier           = carrier,
                p_nom             = 0,
                p_nom_extendable  = True,
                p_nom_max         = EXPANSION_LIMITS_MW.get(carrier, float("inf")), 
                capital_cost      = capital_cost,
                marginal_cost     = marginal_cost,
            )
            if eff is not None:
                kwargs["efficiency"] = eff

            n.add("Generator", gen_name, **kwargs)
            n_added += 1

        # Attach profile after creating all generators of this carrier
        if profile is not None:
            new_gens = [f"new_{carrier}_{c}" for c in n.buses.index]
            df = pd.DataFrame({g: profile.values for g in new_gens}, index=n.snapshots)
            for col in df.columns:
                n.generators_t.p_max_pu[col] = df[col]

        print(f"  {carrier:<8} : {len(n.buses):>3} new generators  "
              f"capital_cost={capital_cost:>10,.0f} USD/MW/yr  "
              f"marginal_cost={marginal_cost:>7.2f} USD/MWh")

    print(f"  Total new expandable generators : {n_added}")


# =============================================================================
# STEP 5 — Make existing lines expandable
# =============================================================================

def make_lines_expandable(n):
    print("\n[5/7] Making existing inter-cluster lines expandable ...")

    if len(n.lines) == 0:
        print("  No lines to expand.")
        return

    # Per-MW-per-km capital cost annualized
    capex_per_mw_km   = HVAC_INVESTMENT_EUR_MW_KM * EUR_TO_USD
    annual_per_mw_km  = annualize(capex_per_mw_km, HVAC_WACC_FALLBACK, HVAC_LIFETIME_YEARS)
    fom_per_mw_km     = capex_per_mw_km * (HVAC_FOM_PCT / 100.0)
    cost_per_mw_km    = annual_per_mw_km + fom_per_mw_km

    print(f"  HVAC overhead capex        : {capex_per_mw_km:,.2f} USD/MW/km")
    print(f"  Annualized + FOM (lifetime {HVAC_LIFETIME_YEARS}y, WACC {HVAC_WACC_FALLBACK:.2%})")
    print(f"                              : {cost_per_mw_km:,.2f} USD/MW/km/year")

    n_lines    = 0
    total_km   = 0.0
    for line_name, line in n.lines.iterrows():
        bus0 = line["bus0"]
        bus1 = line["bus1"]
        if bus0 not in n.buses.index or bus1 not in n.buses.index:
            print(f"  [WARN] Line {line_name} references missing bus, skipping.")
            continue

        lon0 = n.buses.at[bus0, "x"]
        lat0 = n.buses.at[bus0, "y"]
        lon1 = n.buses.at[bus1, "x"]
        lat1 = n.buses.at[bus1, "y"]
        if pd.isna(lon0) or pd.isna(lon1):
            print(f"  [WARN] Line {line_name} has missing coordinates, skipping.")
            continue

        length_km = haversine_km(lat0, lon0, lat1, lon1)

        # Mark expandable; preserve original capacity as floor.
        n.lines.at[line_name, "s_nom_extendable"] = True
        n.lines.at[line_name, "s_nom_min"]       = float(line.get("s_nom", 0.0))
        # Note: s_nom_max defaults to inf in PyPSA — model can grow without limit.
        n.lines.at[line_name, "capital_cost"]    = cost_per_mw_km * length_km
        n.lines.at[line_name, "length"]          = length_km

        n_lines  += 1
        total_km += length_km

    print(f"  Lines marked expandable    : {n_lines}")
    print(f"  Total inter-cluster length : {total_km:,.0f} km")


# =============================================================================
# STEP 6 — Add load-shedding virtual generators
# =============================================================================

def add_load_shedding(n):
    print("\n[6/7] Adding virtual load-shedding generators ...")

    n_added = 0
    for cluster in n.buses.index:
        gen_name = f"loadshed_{cluster}"
        n.add(
            "Generator",
            gen_name,
            bus              = cluster,
            carrier          = LOAD_SHEDDING_CARRIER,
            p_nom            = 1e6,             # effectively unlimited
            p_nom_extendable = False,
            marginal_cost    = LOAD_SHEDDING_COST_USD_MWH,
        )
        n_added += 1

    print(f"  Load-shedding generators added : {n_added}")
    print(f"  Cost per MWh shed              : {LOAD_SHEDDING_COST_USD_MWH:,} USD/MWh")


# =============================================================================
# STEP 7 — Save
# =============================================================================

def save_scenario(n):
    print(f"\n[7/7] Saving scenario network ...")
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    n.export_to_netcdf(OUTPUT_FILE)
    print(f"  Saved : {OUTPUT_FILE}")


# =============================================================================
# MAIN
# =============================================================================

def main():
    print("=" * 70)
    print(f"21_build_scenario.py -- build scenario {SCENARIO_NAME} for K={K}")
    print("=" * 70)
    print(f"\nBase year     : {BASE_YEAR}")
    print(f"Target year   : {TARGET_YEAR}  ({N_YEARS} years horizon)")
    print(f"Demand growth : {DEMAND_GROWTH_RATE:.0%} annual  ->  total factor {DEMAND_FACTOR:.4f}")
    if TIME_AGGREGATION == "tsam":
        print(f"Time aggreg.  : tsam ({TSAM_TYPICAL_PERIODS} typical days x "
              f"{TSAM_HOURS_PER_PERIOD} h, {TSAM_CLUSTER_METHOD})")
    elif TIME_AGGREGATION == "uniform":
        print(f"Time aggreg.  : uniform downsampling every {TIME_RESOLUTION_HOURS} h")
    else:
        print(f"Time aggreg.  : none (full hourly)")
    print(f"WACC override : {'None (using ATB rates)' if WACC_OVERRIDE is None else f'{WACC_OVERRIDE:.2%}'}")
    print(f"Cluster level : K = {K}")

    print("\n[0/7] Verifying inputs ...")
    verify_inputs()

    n     = load_network()
    scale_demand(n)
    resample_snapshots(n)
    costs = load_atb_costs()
    add_expandable_generators(n, costs)
    make_lines_expandable(n)
    add_load_shedding(n)
    save_scenario(n)

    print(f"\n{'='*70}")
    print(f"Scenario {SCENARIO_NAME} built successfully.")
    print(f"Next step: optimize with script 22.")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()
