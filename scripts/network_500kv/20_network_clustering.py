"""
20_network_clustering.py
Generates simplified versions of the 500 kV network using PyPSA's native
spatial k-means clustering. For each aggregation level defined in CLUSTER_SIZES
it produces a functional clustered network ready for optimization and the
corresponding visualization files.

Inputs:
    networks/network_500kv.nc
    data/network_500kv/generators_2024.csv
    data/network_500kv/loads_2024.csv
    data/network_500kv/marginal_costs_2024.csv
    Official data/gen_profiles_2024.csv  (external — download from GitHub Releases, place in external_data_dir/)

Outputs — all in data/network_500kv/clusters/:
    clusters.gpkg
        One layer per N in CLUSTER_SIZES:
            k{N}_buses      : original buses with assigned cluster_id
            k{N}_centroids  : super-buses (centroid of each cluster)
            k{N}_lines      : equivalent lines between clusters

    cluster_summary_k{N}.csv
        One row per cluster. Fields:
            cluster_id, centroid_lat, centroid_lon, n_buses,
            p_nom_hydro_mw        (hydro + pumped_hydro)
            p_nom_nuclear_mw
            p_nom_thermal_mw      (ccgt + ocgt + steam + diesel)
            p_nom_wind_mw
            p_nom_solar_mw
            p_nom_bioenergy_mw    (biomass + biogas)
            p_nom_total_mw

    cluster_k{N}.nc
        PyPSA clustered network with generators, profiles, demand and
        costs loaded. Ready for n.optimize() without additional steps.

Logic:
    1. Load network_500kv.nc and add generators, costs, profiles and demand.
       The network must have all components so that get_clustering_from_busmap
       aggregates them correctly into super-buses.
    2. For each N in CLUSTER_SIZES:
       a. Run kmeans_clustering(n, N) -> obtain busmap (bus -> cluster_id)
          and clustered network.
       b. Export clustered network to .nc.
       c. Build GeoDataFrames for buses, centroids and equivalent lines
          and write them as layers to clusters.gpkg.
       d. Build cluster_summary_k{N}.csv grouping p_nom by technology.

Modeling notes:
    - Clustering uses geographic coordinates (x=lon, y=lat) of buses.
    - Buses without coordinates are excluded from the k-means calculation
      but merged with the nearest cluster via get_clustering_from_busmap.
    - Hourly profiles (gen_profiles_2024.csv) are loaded in full so that
      the clustered network is functional for future optimization.
    - Demand is loaded from loads_2024.csv in long format.
    - Generators without marginal cost receive marginal_cost = 0.

Run from the repository root (pypsa-ar-base/):
    python scripts/network_500kv/20_network_clustering.py
"""

import os
import sys
from pathlib import Path

import pandas as pd
import numpy as np
import pypsa
import geopandas as gpd
import yaml
from shapely.geometry import Point, LineString
from pypsa.clustering.spatial import kmeans_clustering

# =============================================================================
# CONFIGURATION — edit as needed for each run
# =============================================================================

# Desired aggregation levels. Add or remove values as needed.
CLUSTER_SIZES = [10, 20, 30]

# Weighting criterion for k-means clustering
# "uniform" : all buses weighted equally (purely geographic clustering)
# "p_nom"   : buses with more installed generation weighted more
# "demand"  : buses with more demand weighted more
BUS_WEIGHTING = "uniform"

_cfg = yaml.safe_load(open(Path(__file__).parents[2] / "config.yaml"))
REPO_DIR     = Path(_cfg["repo_dir"])
EXTERNAL_DIR = Path(_cfg["external_data_dir"])

NETWORK_FILE  = REPO_DIR / "networks/network_500kv.nc"
GEN_FILE      = REPO_DIR / "data/network_500kv/generators_2024.csv"
LOADS_FILE    = REPO_DIR / "data/network_500kv/loads_2024.csv"
COSTS_FILE    = REPO_DIR / "data/network_500kv/marginal_costs_2024.csv"
PROFILES_FILE = EXTERNAL_DIR / "gen_profiles_2024.csv"

OUTPUT_DIR = REPO_DIR / "data/network_500kv/clusters"
GPKG_FILE  = OUTPUT_DIR / "clusters.gpkg"

CRS = "EPSG:4326"

# Generators without marginal cost:
# False : assign marginal_cost = 0
# True  : exclude from model
EXCLUDE_NO_COST = False

# Carrier groups for the summary CSV
CARRIERS_HYDRO     = {"hydro", "pumped_hydro"}
CARRIERS_NUCLEAR   = {"nuclear"}
CARRIERS_THERMAL   = {"ccgt", "ocgt", "steam", "diesel"}
CARRIERS_WIND      = {"wind"}
CARRIERS_SOLAR     = {"solar"}
CARRIERS_BIOENERGY = {"biomass", "biogas"}


# =============================================================================
# HELPERS
# =============================================================================

def verify_inputs():
    files = {
        "network_500kv.nc"        : NETWORK_FILE,
        "generators_2024.csv"     : GEN_FILE,
        "loads_2024.csv"          : LOADS_FILE,
        "marginal_costs_2024.csv" : COSTS_FILE,
        "gen_profiles_2024.csv"   : PROFILES_FILE,
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


def parse_snapshot_csv(series):
    return pd.to_datetime(series, dayfirst=True, format="%d/%m/%Y %H:%M")


def group_carrier(carrier):
    """Maps individual carrier to summary category."""
    if carrier in CARRIERS_HYDRO:     return "hydro"
    if carrier in CARRIERS_NUCLEAR:   return "nuclear"
    if carrier in CARRIERS_THERMAL:   return "thermal"
    if carrier in CARRIERS_WIND:      return "wind"
    if carrier in CARRIERS_SOLAR:     return "solar"
    if carrier in CARRIERS_BIOENERGY: return "bioenergy"
    return "other"


# =============================================================================
# STEP 1 — Load base network
# =============================================================================

def load_network():
    print("\n[1/6] Loading base network...")
    n = pypsa.Network(NETWORK_FILE)
    print(f"  Buses          : {len(n.buses)}")
    print(f"  Lines          : {len(n.lines)}")
    print(f"  Transformers   : {len(n.transformers)}")
    return n


# =============================================================================
# STEP 2 — Add generators with p_nom and marginal cost
# =============================================================================

def add_generators(n):
    print(f"\n[2/6] Adding generators...")

    gen  = pd.read_csv(GEN_FILE)
    cost = pd.read_csv(COSTS_FILE)[["gen_key", "marginal_cost"]].copy()

    gen = gen.merge(cost, on="gen_key", how="left")

    no_cost   = gen["marginal_cost"].isna()
    n_no_cost = no_cost.sum()

    if EXCLUDE_NO_COST:
        gen = gen[~no_cost].copy()
        print(f"  [INFO] {n_no_cost} generators without cost excluded (EXCLUDE_NO_COST=True)")
    else:
        gen.loc[no_cost, "marginal_cost"] = 0.0
        print(f"  [INFO] {n_no_cost} generators without cost -> marginal_cost=0")

    buses_in_network = set(n.buses.index)
    n_added          = 0
    n_missing_bus    = 0

    for _, row in gen.iterrows():
        bus = row.get("bus_conexion500kv_name")
        if pd.isna(bus) or bus not in buses_in_network:
            n_missing_bus += 1
            continue
        n.add(
            "Generator",
            row["gen_key"],
            bus           = bus,
            p_nom         = float(row["p_nom"]),
            carrier       = row["carrier"],
            marginal_cost = float(row["marginal_cost"]),
        )
        n_added += 1

    print(f"  Generators added  : {n_added}")
    if n_missing_bus:
        print(f"  [WARNING] {n_missing_bus} generators skipped — bus not found in network")


# =============================================================================
# STEP 3 — Add hourly availability profiles (p_max_pu)
# =============================================================================

def add_profiles(n):
    print(f"\n[3/6] Loading availability profiles (gen_profiles_2024.csv)...")
    print(f"  External file: {PROFILES_FILE}")

    chunks     = []
    chunk_size = 500_000

    for chunk in pd.read_csv(PROFILES_FILE, chunksize=chunk_size, low_memory=False):
        chunk["ts"] = parse_snapshot_csv(chunk["datetime"])
        chunks.append(chunk[["gen_key", "ts", "p_max_pu"]])

    profiles = pd.concat(chunks, ignore_index=True)

    profiles_wide = profiles.pivot_table(
        index   = "ts",
        columns = "gen_key",
        values  = "p_max_pu",
        aggfunc = "first",
    )
    profiles_wide.index.name = None
    profiles_wide = profiles_wide.fillna(0.0)

    gens_in_network = set(n.generators.index)
    valid_cols      = [c for c in profiles_wide.columns if c in gens_in_network]
    profiles_wide   = profiles_wide[valid_cols]

    n.generators_t.p_max_pu = profiles_wide

    print(f"  Generators with profile : {len(valid_cols)}")
    print(f"  Snapshots covered       : {len(profiles_wide)}")

    # Remove generators without a profile in gen_profiles_2024.csv
    gens_without_profile = gens_in_network - set(valid_cols)
    if gens_without_profile:
        for gen_key in gens_without_profile:
            n.remove("Generator", gen_key)
        print(f"  {len(gens_without_profile)} generators without profile removed from network")


# =============================================================================
# STEP 4 — Add hourly demand by bus
# =============================================================================

def add_demand(n):
    print(f"\n[4/6] Loading hourly demand (loads_2024.csv)...")

    loads = pd.read_csv(LOADS_FILE)
    loads["ts"] = parse_snapshot_csv(loads["datetime"])

    loads_wide = loads.pivot_table(
        index   = "ts",
        columns = "bus_name",
        values  = "p_mw",
        aggfunc = "sum",
    )
    loads_wide.index.name = None
    loads_wide = loads_wide.fillna(0.0)

    buses_in_network = set(n.buses.index)
    n_loads          = 0

    for bus_name in loads_wide.columns:
        if bus_name not in buses_in_network:
            continue
        n.add("Load", f"load_{bus_name}", bus=bus_name)
        n_loads += 1

    load_names         = [f"load_{b}" for b in loads_wide.columns if b in buses_in_network]
    loads_wide.columns = [f"load_{b}" for b in loads_wide.columns]
    valid_cols         = [c for c in load_names if c in loads_wide.columns]
    n.loads_t.p_set    = loads_wide[valid_cols]

    demand_max = loads_wide[valid_cols].sum(axis=1).max()
    print(f"  Buses with demand : {n_loads}")
    print(f"  Peak demand       : {demand_max:,.1f} MW")


# =============================================================================
# STEP 5 — Clustering for each N
# =============================================================================

def run_clustering(n):
    print(f"\n[5/6] Running spatial k-means clustering...")
    print(f"  Aggregation levels: {CLUSTER_SIZES}")

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Remove custom columns not standard in PyPSA that break clustering
    CUSTOM_BUS_COLS = [
        "v_mag_pu_psse", "v_ang_deg_psse", "bus_type",
        "ide", "ide_desc", "parent_bus_id", "name_geosadi", "bus_name_psse"
    ]
    for col in CUSTOM_BUS_COLS:
        if col in n.buses.columns:
            n.buses.drop(columns=[col], inplace=True)

    results = {}

    for N in CLUSTER_SIZES:
        print(f"\n  --- K = {N} ---")

        if BUS_WEIGHTING == "p_nom":
            bus_weightings = (
                n.generators.groupby("bus")["p_nom"]
                .sum()
                .reindex(n.buses.index)
                .fillna(1.0)
            )
        elif BUS_WEIGHTING == "demand":
            bus_weightings = (
                n.loads_t.p_set.mean()
                .rename(lambda x: x.replace("load_", ""))
                .reindex(n.buses.index)
                .fillna(1.0)
            )
        else:  # uniform
            bus_weightings = pd.Series(1.0, index=n.buses.index)

        clustering = kmeans_clustering(n, n_clusters=N, bus_weightings=bus_weightings)

        nc     = clustering.network   # clustered network
        busmap = clustering.busmap    # Series: original_bus -> cluster_id

        print(f"  Super-buses generated : {len(nc.buses)}")
        print(f"  Equivalent lines      : {len(nc.lines)}")

        nc_path = OUTPUT_DIR / f"cluster_k{N}.nc"
        nc.export_to_netcdf(nc_path)
        print(f"  Network saved         : cluster_k{N}.nc")

        results[N] = {"nc": nc, "busmap": busmap}

    return results


# =============================================================================
# STEP 6 — Export GeoPackage and summaries
# =============================================================================

def export_outputs(n, results):
    print(f"\n[6/6] Exporting GeoPackage and summaries...")

    # Remove existing .gpkg to avoid duplicate layers from previous runs
    if os.path.isfile(GPKG_FILE):
        os.remove(GPKG_FILE)
        print(f"  Previous .gpkg removed — generating a clean new one")

    buses_coords = n.buses[["x", "y"]].copy()
    buses_coords.columns = ["lon", "lat"]

    for N, res in results.items():
        nc     = res["nc"]
        busmap = res["busmap"]

        print(f"\n  Exporting K = {N}...")

        # ------------------------------------------------------------------
        # Layer 1: original buses colored by cluster
        # ------------------------------------------------------------------
        buses_df = buses_coords.copy()
        buses_df["cluster_id"] = busmap.reindex(buses_df.index)
        buses_df = buses_df.dropna(subset=["lat", "lon", "cluster_id"])
        buses_df["cluster_id"] = buses_df["cluster_id"].astype(int)

        gdf_buses = gpd.GeoDataFrame(
            buses_df.reset_index().rename(columns={"index": "bus_name"}),
            geometry=[Point(row["lon"], row["lat"]) for _, row in buses_df.iterrows()],
            crs=CRS,
        )
        gdf_buses.to_file(GPKG_FILE, layer=f"k{N}_buses", driver="GPKG")
        print(f"    Layer k{N}_buses     : {len(gdf_buses)} buses")

        # ------------------------------------------------------------------
        # Layer 2: centroids (super-buses)
        # ------------------------------------------------------------------
        centroids_df = nc.buses[["x", "y"]].copy()
        centroids_df.columns = ["lon", "lat"]
        centroids_df = centroids_df.dropna()
        centroids_df["cluster_id"] = range(len(centroids_df))

        if len(nc.generators) > 0:
            p_nom_per_bus = nc.generators.groupby("bus")["p_nom"].sum()
            centroids_df["p_nom_total_mw"] = centroids_df.index.map(p_nom_per_bus).fillna(0.0)
        else:
            centroids_df["p_nom_total_mw"] = 0.0

        n_buses_per_cluster  = busmap.value_counts().to_dict()
        centroids_df["n_buses"] = centroids_df.index.map(n_buses_per_cluster).fillna(0).astype(int)

        gdf_centroids = gpd.GeoDataFrame(
            centroids_df.reset_index().rename(columns={"index": "super_bus"}),
            geometry=[Point(row["lon"], row["lat"]) for _, row in centroids_df.iterrows()],
            crs=CRS,
        )
        gdf_centroids.to_file(GPKG_FILE, layer=f"k{N}_centroids", driver="GPKG")
        print(f"    Layer k{N}_centroids : {len(gdf_centroids)} super-buses")

        # ------------------------------------------------------------------
        # Layer 3: equivalent lines between clusters
        # ------------------------------------------------------------------
        line_rows = []
        for line_name, line in nc.lines.iterrows():
            bus0 = line["bus0"]
            bus1 = line["bus1"]
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
            gdf_lines = gpd.GeoDataFrame(line_rows, crs=CRS)
            gdf_lines.to_file(GPKG_FILE, layer=f"k{N}_lines", driver="GPKG")
            print(f"    Layer k{N}_lines     : {len(gdf_lines)} equivalent lines")
        else:
            print(f"    Layer k{N}_lines     : no lines to export")

        export_summary(nc, busmap, centroids_df, N)

    print(f"\n  Final GeoPackage: {GPKG_FILE}")
    print(f"  Layers: {[f'k{N}_{t}' for N in CLUSTER_SIZES for t in ['buses', 'centroids', 'lines']]}")
    print(f"\n  Suggested QGIS symbology:")
    print(f"    Buses     -> Categorized by 'cluster_id'")
    print(f"    Centroids -> Size proportional to 'p_nom_total_mw': sqrt(p_nom_total_mw) / 5")
    print(f"    Lines     -> Width proportional to 's_nom_mw'")


def export_summary(nc, busmap, centroids_df, N):
    """Builds and saves cluster_summary_k{N}.csv."""

    rows = []

    for cluster_id, centroid_row in centroids_df.iterrows():
        cluster_gens = (
            nc.generators[nc.generators["bus"] == cluster_id]
            if len(nc.generators) > 0
            else pd.DataFrame()
        )

        def sum_carriers(carriers):
            if cluster_gens.empty:
                return 0.0
            return cluster_gens.loc[cluster_gens["carrier"].isin(carriers), "p_nom"].sum()

        rows.append({
            "cluster_id"         : cluster_id,
            "centroid_lat"       : round(centroid_row["lat"], 4),
            "centroid_lon"       : round(centroid_row["lon"], 4),
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
        })

    summary      = pd.DataFrame(rows).sort_values("cluster_id").reset_index(drop=True)
    summary_path = OUTPUT_DIR / f"cluster_summary_k{N}.csv"
    summary.to_csv(summary_path, index=False)

    print(f"    Summary k{N}         : {summary_path}")
    print(f"      Total system p_nom : {summary['p_nom_total_mw'].sum():,.1f} MW")


# =============================================================================
# MAIN
# =============================================================================

def main():
    print("=" * 60)
    print("20_network_clustering.py -- spatial k-means clustering")
    print("=" * 60)
    print(f"\nAggregation levels: {CLUSTER_SIZES}")

    print("\n[0/6] Verifying inputs...")
    verify_inputs()

    n = load_network()
    add_generators(n)
    add_profiles(n)
    add_demand(n)

    results = run_clustering(n)
    export_outputs(n, results)

    print(f"\n{'='*60}")
    print(f"Clustering complete.")
    print(f"Outputs in: {OUTPUT_DIR}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
