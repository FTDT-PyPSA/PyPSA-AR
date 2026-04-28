"""
20B_network_clustering.py
Generates spatially clustered versions of the simplified 500 kV SADI network
using PyPSA's native k-means clustering. For each aggregation level defined
in CLUSTER_SIZES it produces a functional clustered network ready for scenario
runs, plus visualization files (GeoPackage + CSV summary).

Inputs:
    networks/network_500kv_simplified.nc   (script 20A)

Outputs — all in data/network_500kv/clusters/:
    clusters.gpkg
        One layer per N in CLUSTER_SIZES:
            k{N}_buses      : original buses with assigned cluster_id
            k{N}_centroids  : super-buses (centroid of each cluster)
            k{N}_lines      : equivalent lines between clusters

    cluster_summary_k{N}.csv
        One row per cluster. Fields:
            cluster_id, centroid_lat, centroid_lon, n_buses,
            p_nom_hydro_mw, p_nom_nuclear_mw, p_nom_thermal_mw,
            p_nom_wind_mw, p_nom_solar_mw, p_nom_bioenergy_mw,
            p_nom_total_mw, mean_demand_mw

    cluster_k{N}.nc
        PyPSA clustered network with generators, profiles, demand and costs
        inherited from the simplified network. Ready for scenario-runner
        scripts without additional preprocessing.

Logic:
    1. Load network_500kv_simplified.nc. Data for 2024 (generators, profiles,
       demand, marginal costs) is already attached by script 20A.
    2. Remove buses listed in BUSES_TO_REMOVE: topological islands (T PEPE,
       PBUENA2) and the inactive Brazil interconnection (BRASIL, GARABI).
    3. For each N in CLUSTER_SIZES:
       a. Compute per-bus weights according to BUS_WEIGHTING mode.
       b. Build a metric-projected copy of the network (EPSG:5347, POSGAR 2007
          / Argentina 3) so k-means distances are geographically correct.
       c. Run busmap_by_kmeans with N clusters on all remaining (Argentine) buses.
       d. Apply the full busmap to the original network (EPSG:4326 coords)
          via get_clustering_from_busmap. Centroids are produced in WGS84
          for direct use in GeoPackage / QGIS.
       e. Export .nc, GeoPackage layers, summary CSV.

Modeling decisions:
    - Isolated buses (T PEPE, PBUENA2) are removed. They are topological
      islands in the current PSS/E model (script 19 also excludes them from
      the OPF).
    - The Argentina-Brazil interconnection is dropped at this stage. The
      base .nc carries a BRASIL virtual bus and the importacion_brasil link,
      but no generator on the Brazilian side, so the model cannot actually
      use the import. Keeping the node would only add noise to the
      clustering. Future scenarios that want to model imports can add a
      virtual generator in the cluster that previously hosted GARABI.
    - Number of final clusters = N. All clusters are Argentine.
    - K-means distance is computed on metric coordinates (EPSG:5347). The
      output .nc and GeoPackage use WGS84 (EPSG:4326) — standard for the project.
    - Slack bus and virtual load shedding are NOT added here. They are
      responsibility of scenario-runner scripts that consume the clustered
      .nc files.
    - Custom bus columns inherited from earlier pipeline steps are dropped
      before clustering (PyPSA's clustering routines fail on non-standard
      columns with mixed dtypes).

Bus weighting modes (BUS_WEIGHTING):
    - "uniform"       : all buses weighted equally.
    - "p_nom"         : weight = installed generation capacity (MW).
    - "demand"        : weight = annual peak demand (MW).
    - "activity_sum"  : weight = p_nom_mw + peak_demand_mw.
    - "activity_max"  : weight = max(p_nom_mw, peak_demand_mw).

    The demand component uses ANNUAL PEAK (not mean) to reflect the Argentine
    system's asymmetry: AMBA concentrates demand (~11 GW peak) while generation
    is spread across Comahue, Patagonia, NEA, NOA and Cuyo. Peak weighting
    ensures consumption hubs are proportionally represented at the moments
    the grid is most stressed. Using mean demand would under-represent AMBA
    (its mean is ~5 GW vs ~8 GW p_nom in the region).

    activity_sum and activity_max are designed so active nodes (generation
    hubs or load hubs) weigh more than pass-through transit nodes. See
    project Bible / clustering discussion for the rationale.

Run from the repository root (pypsa-ar-base/):
    python scripts/network_500kv/20B_network_clustering.py
"""

import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
import pypsa
import geopandas as gpd
from shapely.geometry import Point, LineString
from pypsa.clustering.spatial import busmap_by_kmeans, get_clustering_from_busmap


# =============================================================================
# CONFIGURATION — edit as needed for each run
# =============================================================================

# Desired aggregation levels. Total clusters per run = N (all Argentine).
CLUSTER_SIZES = [10, 20, 30]

# Weighting criterion. Options: "uniform" | "p_nom" | "demand"
#                              | "activity_sum" | "activity_max"
BUS_WEIGHTING = "activity_sum"

# Isolated buses and non-functional foreign nodes that should not enter the
# clustering. They are dropped before k-means so the K clusters are entirely
# Argentine and the resulting network represents the SADI cleanly.
#
# - T PEPE, PBUENA2 : topological islands in the current PSS/E model with no
#   operational meaning (script 19 also excludes them from the OPF).
# - BRASIL          : virtual node for the Argentina-Brazil interconnection.
#   Dropped because the link importacion_brasil is not connected to any
#   generator on the Brazilian side, so the model cannot actually import
#   from Brazil. Keeping the node would only add noise to the clustering.
#   Future scenarios that want to model imports can add a virtual generator
#   in the cluster that previously hosted GARABI (see project notes).
# - GARABI          : intermediate bus that only exists to host the link to
#   BRASIL. With BRASIL removed it has no purpose.
BUSES_TO_REMOVE = {"T PEPE", "PBUENA2", "BRASIL", "GARABI"}

_cfg = yaml.safe_load(open(Path(__file__).parents[2] / "config.yaml"))
REPO_DIR = Path(_cfg["repo_dir"])

INPUT_NETWORK = REPO_DIR / "networks/network_500kv_simplified.nc"
OUTPUT_DIR    = REPO_DIR / "data/network_500kv/clusters"
GPKG_FILE     = OUTPUT_DIR / "clusters.gpkg"

CRS_SOURCE = "EPSG:4326"   # WGS84 (what the .nc uses)
CRS_METRIC = "EPSG:5347"   # POSGAR 2007 / Argentina 3 (metric)

# Carrier groups for the summary CSV
CARRIERS_HYDRO     = {"hydro", "pumped_hydro"}
CARRIERS_NUCLEAR   = {"nuclear"}
CARRIERS_THERMAL   = {"ccgt", "ocgt", "steam", "diesel"}
CARRIERS_WIND      = {"wind"}
CARRIERS_SOLAR     = {"solar"}
CARRIERS_BIOENERGY = {"biomass", "biogas"}

# Custom (non-PyPSA-standard) columns that may leak in from earlier pipeline
# steps and break get_clustering_from_busmap. Dropped defensively.
CUSTOM_BUS_COLS = [
    "v_mag_pu_psse", "v_ang_deg_psse", "bus_type",
    "ide", "ide_desc", "parent_bus_id", "name_geosadi", "bus_name_psse",
]


# =============================================================================
# HELPERS
# =============================================================================

def verify_inputs():
    if not os.path.isfile(INPUT_NETWORK):
        print(f"  [ERROR] Not found: {INPUT_NETWORK}")
        print("          Run script 20A first to generate the simplified network.")
        sys.exit(1)
    print(f"  Input verified: {INPUT_NETWORK}")


def drop_custom_columns(n):
    """Removes non-PyPSA-standard columns that break clustering routines."""
    for col in CUSTOM_BUS_COLS:
        if col in n.buses.columns:
            n.buses.drop(columns=[col], inplace=True)


def remove_isolated_buses(n):
    """Removes buses listed in BUSES_TO_REMOVE and everything attached to them.
    Includes both topological islands and the Argentina-Brazil interconnection
    (which is non-functional in the current model — see module docstring)."""
    print("\n[2/4] Removing non-operational buses ...")
    to_remove = [b for b in BUSES_TO_REMOVE if b in n.buses.index]

    if not to_remove:
        print("  No isolated buses to remove.")
        return

    # Defensive cleanup: anything attached to these buses must be removed first.
    for comp, bus_cols in [
        ("Generator",  ["bus"]),
        ("Load",       ["bus"]),
        ("Line",       ["bus0", "bus1"]),
        ("Transformer",["bus0", "bus1"]),
        ("Link",       ["bus0", "bus1"]),
    ]:
        comp_df = getattr(n, comp.lower() + "s")
        if len(comp_df) == 0:
            continue
        mask = pd.Series(False, index=comp_df.index)
        for col in bus_cols:
            if col in comp_df.columns:
                mask |= comp_df[col].isin(to_remove)
        for name in comp_df[mask].index:
            n.remove(comp, name)

    for b in to_remove:
        n.remove("Bus", b)

    print(f"  Removed buses : {sorted(to_remove)}")
    print(f"  Buses now     : {len(n.buses)}")


def compute_bus_weights(n, mode):
    """Returns a pd.Series (index = bus names) with the weight per bus.

    Demand component uses the ANNUAL PEAK (max over snapshots) per bus,
    not the mean. Rationale: in the SADI, AMBA concentrates demand while
    generation is spread across Comahue, Patagonia, NEA, NOA and Cuyo.
    Using peak demand ensures the consumption hubs weigh proportionally
    to their stress on the system, which is when the grid matters most.
    """
    idx = n.buses.index

    # p_nom aggregated per bus
    if len(n.generators) > 0:
        p_nom_per_bus = n.generators.groupby("bus")["p_nom"].sum()
    else:
        p_nom_per_bus = pd.Series(dtype=float)
    p_nom_per_bus = p_nom_per_bus.reindex(idx).fillna(0.0)

    # Peak annual demand per bus (MW)
    if not n.loads_t.p_set.empty and len(n.loads) > 0:
        # loads_t.p_set columns are load names (e.g. "load_BUSNAME");
        # group by the Load.bus attribute so we get demand per bus.
        # For multi-load buses, the peak is computed AFTER summing loads
        # at each snapshot, then taking the max over snapshots.
        load_to_bus = n.loads["bus"]
        # For each bus, sum its loads' time series, then take the peak
        demand_per_bus = (
            n.loads_t.p_set
            .T.groupby(load_to_bus).sum()   # aggregate loads per bus (MW per snapshot)
            .T.max(axis=0)                  # peak over snapshots
        )
    else:
        demand_per_bus = pd.Series(dtype=float)
    demand_per_bus = demand_per_bus.reindex(idx).fillna(0.0)

    if mode == "uniform":
        w = pd.Series(1.0, index=idx)
    elif mode == "p_nom":
        w = p_nom_per_bus
    elif mode == "demand":
        w = demand_per_bus
    elif mode == "activity_sum":
        w = p_nom_per_bus + demand_per_bus
    elif mode == "activity_max":
        w = pd.concat([p_nom_per_bus, demand_per_bus], axis=1).max(axis=1)
    else:
        raise ValueError(f"Unknown BUS_WEIGHTING: {mode!r}")

    # Floor weights at a small positive value so k-means doesn't get zero-weight
    # pass-through buses (they still need to be assigned to some cluster).
    w = w.clip(lower=1e-3)

    return w


def project_coords_to_metric(n):
    """Converts bus x, y in-place from WGS84 to EPSG:5347 (metric).
    Returns the original coords as a DataFrame so the caller can restore them.
    Avoids n.copy() because it is unreliable for networks with many snapshots."""
    original = n.buses[["x", "y"]].copy()

    coords = n.buses[["x", "y"]].dropna()
    if coords.empty:
        return original

    gdf = gpd.GeoDataFrame(
        coords,
        geometry=gpd.points_from_xy(coords["x"], coords["y"]),
        crs=CRS_SOURCE,
    ).to_crs(CRS_METRIC)

    n.buses.loc[gdf.index, "x"] = gdf.geometry.x.values
    n.buses.loc[gdf.index, "y"] = gdf.geometry.y.values
    return original


def restore_coords(n, original):
    """Restores bus x, y from a backup DataFrame."""
    n.buses.loc[original.index, "x"] = original["x"].values
    n.buses.loc[original.index, "y"] = original["y"].values


def group_carrier(carrier):
    if carrier in CARRIERS_HYDRO:     return "hydro"
    if carrier in CARRIERS_NUCLEAR:   return "nuclear"
    if carrier in CARRIERS_THERMAL:   return "thermal"
    if carrier in CARRIERS_WIND:      return "wind"
    if carrier in CARRIERS_SOLAR:     return "solar"
    if carrier in CARRIERS_BIOENERGY: return "bioenergy"
    return "other"


# =============================================================================
# STEP 1 — Load simplified network
# =============================================================================

def load_network():
    print("\n[1/4] Loading simplified network ...")
    n = pypsa.Network(INPUT_NETWORK)

    drop_custom_columns(n)

    print(f"  Buses       : {len(n.buses)}")
    print(f"  Generators  : {len(n.generators)}")
    print(f"  Loads       : {len(n.loads)}")
    print(f"  Lines       : {len(n.lines)}")
    print(f"  Links       : {len(n.links)}")

    return n


# =============================================================================
# STEP 3 — Run clustering for each N
# =============================================================================

def run_clustering(n):
    print(f"\n[3/4] Running spatial k-means clustering ...")
    print(f"  Aggregation levels    : {CLUSTER_SIZES}")
    print(f"  Weighting             : {BUS_WEIGHTING}")
    print(f"  Metric CRS for k-means: {CRS_METRIC}")

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Clean .gpkg to avoid stale layers from previous runs
    if os.path.isfile(GPKG_FILE):
        os.remove(GPKG_FILE)
        print(f"  Previous .gpkg removed")

    # Build weights once — they are input-data driven, not K-dependent
    weights = compute_bus_weights(n, BUS_WEIGHTING)
    print(f"  Bus weights computed  : {len(weights)} buses")

    # Save original WGS84 coords. We will project in-place to metric for k-means
    # and restore WGS84 before get_clustering_from_busmap (which we want to run
    # on the WGS84 network so centroids end up in lat/lon directly).
    original_coords = n.buses[["x", "y"]].copy()

    results = {}
    for N in CLUSTER_SIZES:
        print(f"\n  --- K = {N} ---")

        if N < 1:
            print(f"    [SKIP] N={N} is too small")
            continue

        # --- Phase 1: k-means on metric coords ---
        project_coords_to_metric(n)
        try:
            busmap = busmap_by_kmeans(
                n,
                bus_weightings=weights,
                n_clusters=N,
                buses_i=n.buses.index,
            )
        finally:
            # Always restore WGS84, even if k-means crashed
            restore_coords(n, original_coords)

        # Ensure cluster IDs are stringy
        busmap = busmap.astype(str).apply(lambda s: f"cluster_{s}")

        # Sanity: every bus must be in the busmap
        missing_in_busmap = set(n.buses.index) - set(busmap.index)
        if missing_in_busmap:
            print(f"    [ERROR] Buses missing from busmap: {sorted(missing_in_busmap)[:5]}")
            sys.exit(1)

        # --- Phase 2: apply busmap on WGS84 network ---
        clustering = get_clustering_from_busmap(n, busmap)
        nc = clustering.network

        # Guard: clustering should preserve snapshots; if it doesn't, restore them
        # manually. Some PyPSA versions lose time index for empty per-Load data.
        if len(nc.snapshots) != len(n.snapshots):
            print(f"    [INFO] Clustered network lost snapshots "
                  f"({len(nc.snapshots)} vs {len(n.snapshots)}); restoring from base.")
            nc.set_snapshots(n.snapshots)

        # Validation: did time series actually survive?
        orig_shape = n.loads_t.p_set.shape
        clus_shape = nc.loads_t.p_set.shape
        if clus_shape[0] != orig_shape[0]:
            print(f"    [WARN] loads_t.p_set lost time dimension: "
                  f"{orig_shape} -> {clus_shape}")
            print(f"           Rebuilding from original via busmap ...")
            nc = rebuild_time_series(n, nc, busmap)

        # Export clustered network
        nc_path = OUTPUT_DIR / f"cluster_k{N}.nc"
        nc.export_to_netcdf(nc_path)

        print(f"    Super-buses generated : {len(nc.buses)}")
        print(f"    Equivalent lines      : {len(nc.lines)}")
        print(f"    Equivalent links      : {len(nc.links)}")
        print(f"    Snapshots             : {len(nc.snapshots)}")
        print(f"    loads_t.p_set shape   : {nc.loads_t.p_set.shape}")
        print(f"    Saved                 : {nc_path.name}")

        results[N] = {"nc": nc, "busmap": busmap}

    return results


def rebuild_time_series(n_orig, nc, busmap):
    """Rebuilds nc.loads_t.p_set and nc.generators_t.p_max_pu by aggregating
    the original network's time series through the busmap. Used as a fallback
    when get_clustering_from_busmap drops the time dimension in PyPSA versions
    that don't preserve it correctly."""

    # --- Loads: sum original load series per destination cluster ---
    # In the ORIGINAL network, each Load sits on a bus. The busmap tells us
    # which cluster that bus belongs to.
    if not n_orig.loads_t.p_set.empty and len(n_orig.loads) > 0:
        load_bus_orig = n_orig.loads["bus"]                   # Load -> bus
        load_cluster  = load_bus_orig.map(busmap)             # Load -> cluster
        # Aggregate: sum all original load series that map to the same cluster
        new_load_ts = (
            n_orig.loads_t.p_set
            .T.groupby(load_cluster).sum().T
        )
        # get_clustering_from_busmap creates one Load per cluster, usually named
        # by the cluster id. We rename columns to match what nc.loads has.
        # Map: cluster_id -> Load name in nc
        cluster_to_load_nc = {b: f"{b}" for b in nc.buses.index}
        # nc.loads may already name them differently; match by 'bus' field.
        if len(nc.loads) > 0:
            nc_load_by_bus = {row["bus"]: idx for idx, row in nc.loads.iterrows()}
            rename = {cl: nc_load_by_bus[cl] for cl in new_load_ts.columns
                      if cl in nc_load_by_bus}
            new_load_ts = new_load_ts.rename(columns=rename)
        nc.loads_t.p_set = new_load_ts

    # --- Generator availability profiles: preserve per-generator (no aggregation) ---
    # Generators are not merged — only their bus attribute changes. So the
    # original p_max_pu matrix is valid as-is, just needs to be reattached.
    if not n_orig.generators_t.p_max_pu.empty:
        valid_cols = [c for c in n_orig.generators_t.p_max_pu.columns
                      if c in nc.generators.index]
        nc.generators_t.p_max_pu = n_orig.generators_t.p_max_pu[valid_cols]

    return nc


# =============================================================================
# STEP 4 — Export GeoPackage and summaries
# =============================================================================

def export_outputs(n, results):
    print(f"\n[4/4] Exporting GeoPackage and summaries ...")

    buses_coords = n.buses[["x", "y"]].copy()
    buses_coords.columns = ["lon", "lat"]

    for N, res in results.items():
        nc     = res["nc"]
        busmap = res["busmap"]

        print(f"\n  Exporting K = {N} ...")

        # --------------------------------------------------------------
        # Layer 1: original buses colored by cluster
        # --------------------------------------------------------------
        buses_df = buses_coords.copy()
        buses_df["cluster_id"] = busmap.reindex(buses_df.index)
        buses_df = buses_df.dropna(subset=["lat", "lon", "cluster_id"])

        gdf_buses = gpd.GeoDataFrame(
            buses_df.reset_index().rename(columns={"index": "bus_name"}),
            geometry=[Point(row["lon"], row["lat"]) for _, row in buses_df.iterrows()],
            crs=CRS_SOURCE,
        )
        gdf_buses.to_file(GPKG_FILE, layer=f"k{N}_buses", driver="GPKG")
        print(f"    Layer k{N}_buses     : {len(gdf_buses)} buses")

        # --------------------------------------------------------------
        # Layer 2: centroids (super-buses)
        # --------------------------------------------------------------
        centroids_df = nc.buses[["x", "y"]].copy()
        centroids_df.columns = ["lon", "lat"]

        n_buses_per_cluster = busmap.value_counts().to_dict()
        centroids_df["n_buses"] = centroids_df.index.map(n_buses_per_cluster).fillna(0).astype(int)

        if len(nc.generators) > 0:
            p_nom_per_cluster = nc.generators.groupby("bus")["p_nom"].sum()
            centroids_df["p_nom_total_mw"] = centroids_df.index.map(p_nom_per_cluster).fillna(0.0)
        else:
            centroids_df["p_nom_total_mw"] = 0.0

        centroids_plot = centroids_df.dropna(subset=["lat", "lon"])
        gdf_centroids = gpd.GeoDataFrame(
            centroids_plot.reset_index().rename(columns={"index": "super_bus"}),
            geometry=[Point(row["lon"], row["lat"]) for _, row in centroids_plot.iterrows()],
            crs=CRS_SOURCE,
        )
        gdf_centroids.to_file(GPKG_FILE, layer=f"k{N}_centroids", driver="GPKG")
        print(f"    Layer k{N}_centroids : {len(gdf_centroids)} super-buses")

        # --------------------------------------------------------------
        # Layer 3: equivalent lines between clusters
        # --------------------------------------------------------------
        line_rows = []
        for line_name, line in nc.lines.iterrows():
            bus0, bus1 = line["bus0"], line["bus1"]
            if bus0 not in centroids_df.index or bus1 not in centroids_df.index:
                continue
            lon0 = centroids_df.loc[bus0, "lon"]
            lat0 = centroids_df.loc[bus0, "lat"]
            lon1 = centroids_df.loc[bus1, "lon"]
            lat1 = centroids_df.loc[bus1, "lat"]
            if pd.isna(lon0) or pd.isna(lon1):
                continue
            line_rows.append({
                "line_name" : line_name,
                "bus0"      : bus0,
                "bus1"      : bus1,
                "s_nom_mw"  : line.get("s_nom", 0),
                "geometry"  : LineString([(lon0, lat0), (lon1, lat1)]),
            })

        if line_rows:
            gdf_lines = gpd.GeoDataFrame(line_rows, crs=CRS_SOURCE)
            gdf_lines.to_file(GPKG_FILE, layer=f"k{N}_lines", driver="GPKG")
            print(f"    Layer k{N}_lines     : {len(gdf_lines)} equivalent lines")
        else:
            print(f"    Layer k{N}_lines     : no lines to export")

        export_summary(nc, busmap, centroids_df, N)

    print(f"\n  Final GeoPackage: {GPKG_FILE}")
    print(f"\n  Suggested QGIS symbology:")
    print(f"    Buses     -> Categorized by 'cluster_id'")
    print(f"    Centroids -> Size proportional to 'p_nom_total_mw': sqrt(p_nom_total_mw) / 5")
    print(f"    Lines     -> Width proportional to 's_nom_mw'")


def export_summary(nc, busmap, centroids_df, N):
    """Builds and saves cluster_summary_k{N}.csv."""

    # Peak demand per super-bus from the clustered network's time series.
    # Same formula as in compute_bus_weights so weights and summary stay consistent.
    if not nc.loads_t.p_set.empty and len(nc.loads) > 0:
        load_to_bus = nc.loads["bus"]
        peak_demand_per_cluster = (
            nc.loads_t.p_set
            .T.groupby(load_to_bus).sum()
            .T.max(axis=0)
        )
    else:
        peak_demand_per_cluster = pd.Series(dtype=float)

    rows = []
    for cluster_id, centroid_row in centroids_df.iterrows():
        cluster_gens = (
            nc.generators[nc.generators["bus"] == cluster_id]
            if len(nc.generators) > 0 else pd.DataFrame()
        )

        def sum_carriers(carriers):
            if cluster_gens.empty:
                return 0.0
            return cluster_gens.loc[cluster_gens["carrier"].isin(carriers), "p_nom"].sum()

        rows.append({
            "cluster_id"         : cluster_id,
            "centroid_lat"       : round(centroid_row["lat"], 4) if pd.notna(centroid_row["lat"]) else None,
            "centroid_lon"       : round(centroid_row["lon"], 4) if pd.notna(centroid_row["lon"]) else None,
            "n_buses"            : int(centroid_row["n_buses"]),
            "p_nom_hydro_mw"     : round(sum_carriers(CARRIERS_HYDRO),     1),
            "p_nom_nuclear_mw"   : round(sum_carriers(CARRIERS_NUCLEAR),   1),
            "p_nom_thermal_mw"   : round(sum_carriers(CARRIERS_THERMAL),   1),
            "p_nom_wind_mw"      : round(sum_carriers(CARRIERS_WIND),      1),
            "p_nom_solar_mw"     : round(sum_carriers(CARRIERS_SOLAR),     1),
            "p_nom_bioenergy_mw" : round(sum_carriers(CARRIERS_BIOENERGY), 1),
            "p_nom_total_mw"     : round(sum_carriers(
                CARRIERS_HYDRO | CARRIERS_NUCLEAR | CARRIERS_THERMAL |
                CARRIERS_WIND  | CARRIERS_SOLAR   | CARRIERS_BIOENERGY
            ), 1),
            "peak_demand_mw"     : round(float(peak_demand_per_cluster.get(cluster_id, 0.0)), 1),
        })

    summary      = pd.DataFrame(rows).sort_values("cluster_id").reset_index(drop=True)
    summary_path = OUTPUT_DIR / f"cluster_summary_k{N}.csv"
    summary.to_csv(summary_path, index=False)

    print(f"    Summary k{N}         : {summary_path.name}")
    print(f"      Total p_nom        : {summary['p_nom_total_mw'].sum():,.1f} MW")
    print(f"      Total peak demand  : {summary['peak_demand_mw'].sum():,.1f} MW (sum of cluster peaks — not simultaneous)")


# =============================================================================
# MAIN
# =============================================================================

def main():
    print("=" * 60)
    print("20B_network_clustering.py -- spatial k-means clustering")
    print("=" * 60)
    print(f"\nAggregation levels : {CLUSTER_SIZES}")
    print(f"Weighting mode     : {BUS_WEIGHTING}")
    print(f"Buses to remove    : {sorted(BUSES_TO_REMOVE)}")

    print("\n[0/4] Verifying inputs ...")
    verify_inputs()

    n = load_network()
    remove_isolated_buses(n)

    results = run_clustering(n)

    if not results:
        print("\n[ABORTED] No clusterings were produced.")
        sys.exit(1)

    export_outputs(n, results)

    print(f"\n{'='*60}")
    print(f"Clustering complete.")
    print(f"Outputs in: {OUTPUT_DIR}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
