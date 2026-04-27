"""
20A_simplify_network.py
Collapses all secondary buses of the 500 kV SADI network into their 500 kV
parent buses, producing a simplified network with 2024 operational data
already attached (generators, availability profiles, demand, costs). The
output .nc is self-contained and ready to be consumed by script 20B
(spatial clustering).

Inputs:
    networks/network_500kv.nc                             (script 08)
    data/network_500kv/buses_final.csv                    (script 05)
    data/network_500kv/fusion_map.csv                     (script 08)
    data/network_500kv/generators_2024.csv                (script 14b)
    data/network_500kv/loads_2024.csv                     (script 15)
    data/network_500kv/marginal_costs_2024.csv            (script 18b)
    external_data_dir/gen_profiles_2024.csv               (external)

Output:
    networks/network_500kv_simplified.nc

Logic:
    1. Load topology + 2024 operational data into the PyPSA network:
       generators (with p_nom and marginal_cost), hourly availability
       profiles (p_max_pu), hourly demand per bus.
    2. Identify secondary buses via parent_bus_id in buses_final.csv.
    3. Reassign every Generator sitting on a secondary bus to its 500 kV parent.
    4. Reassign every Load sitting on a secondary bus to its 500 kV parent.
       Load identities are preserved (no collapsing): multiple loads under
       the same parent remain as separate Load objects. PyPSA aggregates
       them at the bus level during optimization.
    5. Remove every Transformer from the network.
    6. Remove the secondary Bus objects.
    7. Run an integrity report and decide OK / WARN / FAIL.
    8. Export network_500kv_simplified.nc if status is not FAIL.

Why load 2024 data here (instead of topology-only):
    - The base network_500kv.nc holds only topology — generators/loads are
      attached at runtime from CSVs.
    - To make the simplified network meaningful for downstream weighting
      in the clustering step, it must carry operational data so k-means
      can weight nodes by real p_nom / demand.
    - The simplified network represents "the 2024 system with secondary
      buses collapsed". Future-scenario data (2030, 2050, etc.) is
      swapped in by downstream scenario scripts; the cluster partition
      remains fixed as a structural decision derived from 2024 reality.

Modeling decisions:
    - Original .nc and CSV inputs are never modified. Only a new .nc is written.
    - BRASIL virtual bus and its import Link are preserved (BRASIL has no
      parent_bus_id, so it is outside the secondary set by construction).
    - parent_bus_id is read from buses_final.csv because it is NOT stored
      in network_500kv.nc. The parent bus name is then resolved transitively
      against fusion_map.csv (from script 08) so that secondaries whose
      parent was merged via bus section couplers are correctly remapped to
      the surviving root primary in the .nc.
    - Lines are not touched — by assumption the 500 kV network is pure
      (no lines connect to secondary buses, only transformers do).
    - Generators whose marginal_cost is missing: marginal_cost = 0 (unless
      EXCLUDE_NO_COST = True, which drops them).
    - Generators without an hourly profile in gen_profiles_2024.csv are
      removed from the network, matching the behavior expected by the
      optimization pipeline (script 19).
    - The move_loads step is defensive. In the current pipeline loads are
      already assigned to 500 kV parents by script 15, but the logic
      supports future schemas where loads sit on secondary buses.

Run from the repository root (pypsa-ar-base/):
    python scripts/network_500kv/20A_simplify_network.py
"""

import os
import sys
from pathlib import Path

import pandas as pd
import yaml
import pypsa
import networkx as nx


# =============================================================================
# CONFIGURATION
# =============================================================================

_cfg = yaml.safe_load(open(Path(__file__).parents[2] / "config.yaml"))
REPO_DIR     = Path(_cfg["repo_dir"])
EXTERNAL_DIR = Path(_cfg["external_data_dir"])

INPUT_NETWORK   = REPO_DIR / "networks/network_500kv.nc"
BUSES_FILE      = REPO_DIR / "data/network_500kv/buses_final.csv"
FUSION_MAP_FILE = REPO_DIR / "data/network_500kv/fusion_map.csv"
GEN_FILE        = REPO_DIR / "data/network_500kv/generators_2024.csv"
LOADS_FILE      = REPO_DIR / "data/network_500kv/loads_2024.csv"
COSTS_FILE      = REPO_DIR / "data/network_500kv/marginal_costs_2024.csv"
PROFILES_FILE   = EXTERNAL_DIR / "gen_profiles_2024.csv"
OUTPUT_NETWORK  = REPO_DIR / "networks/network_500kv_simplified.nc"

# Virtual bus that must always survive the simplify (no parent by construction).
BRAZIL_BUS = "BRASIL"

# Generators without marginal cost:
# False : assign marginal_cost = 0
# True  : exclude from network
EXCLUDE_NO_COST = False


# =============================================================================
# HELPERS
# =============================================================================

def verify_inputs():
    files = {
        "network_500kv.nc"        : INPUT_NETWORK,
        "buses_final.csv"         : BUSES_FILE,
        "fusion_map.csv"          : FUSION_MAP_FILE,
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


def capture_stats(n):
    """Captures a snapshot of network size and key invariants for later validation."""
    peak_demand = 0.0
    if not n.loads_t.p_set.empty:
        peak_demand = n.loads_t.p_set.sum(axis=1).max()

    return {
        "n_buses"        : len(n.buses),
        "n_generators"   : len(n.generators),
        "p_nom_total_mw" : float(n.generators["p_nom"].sum()) if len(n.generators) else 0.0,
        "n_loads"        : len(n.loads),
        "peak_demand_mw" : float(peak_demand),
        "n_transformers" : len(n.transformers),
        "n_lines"        : len(n.lines),
        "n_links"        : len(n.links),
    }


# =============================================================================
# STEP 1 — Load base network
# =============================================================================

def load_network():
    print("\n[1/11] Loading base network ...")
    n = pypsa.Network(INPUT_NETWORK)
    print(f"  Buses          : {len(n.buses)}")
    print(f"  Lines          : {len(n.lines)}")
    print(f"  Transformers   : {len(n.transformers)}")
    print(f"  Links          : {len(n.links)}")
    return n


# =============================================================================
# STEP 2 — Add generators with p_nom and marginal_cost
# =============================================================================

def add_generators(n):
    print("\n[2/11] Adding generators ...")

    gen  = pd.read_csv(GEN_FILE)
    cost = pd.read_csv(COSTS_FILE)[["gen_key", "marginal_cost"]].copy()
    gen  = gen.merge(cost, on="gen_key", how="left")

    no_cost   = gen["marginal_cost"].isna()
    n_no_cost = int(no_cost.sum())

    if EXCLUDE_NO_COST:
        gen = gen[~no_cost].copy()
        print(f"  {n_no_cost} generators without cost excluded (EXCLUDE_NO_COST=True)")
    else:
        gen.loc[no_cost, "marginal_cost"] = 0.0
        if n_no_cost:
            print(f"  {n_no_cost} generators without cost -> marginal_cost = 0")

    buses_in_network = set(n.buses.index)
    n_added       = 0
    n_missing_bus = 0

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

    print(f"  Generators added     : {n_added}")
    if n_missing_bus:
        print(f"  [WARN] {n_missing_bus} generators skipped (bus not in network)")


# =============================================================================
# STEP 3 — Add hourly availability profiles (p_max_pu)
# =============================================================================

def add_profiles(n):
    print("\n[3/11] Loading availability profiles ...")

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

    # Set network snapshots from the profile's time index BEFORE assigning p_max_pu.
    # Without this, PyPSA silently truncates the time series to the single default
    # snapshot ("now") inherited from the base .nc, collapsing 8784 hours into 1.
    n.set_snapshots(profiles_wide.index)

    n.generators_t.p_max_pu = profiles_wide

    print(f"  Generators with profile : {len(valid_cols)}")
    print(f"  Snapshots covered       : {len(profiles_wide)}")

    # Remove generators without a profile, matching script 19's expectation.
    gens_without_profile = gens_in_network - set(valid_cols)
    if gens_without_profile:
        for gen_key in gens_without_profile:
            n.remove("Generator", gen_key)
        print(f"  {len(gens_without_profile)} generators without profile removed")


# =============================================================================
# STEP 4 — Add hourly demand by bus
# =============================================================================

def add_demand(n):
    print("\n[4/11] Loading hourly demand ...")

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
    n_loads = 0

    for bus_name in loads_wide.columns:
        if bus_name not in buses_in_network:
            continue
        n.add("Load", f"load_{bus_name}", bus=bus_name)
        n_loads += 1

    load_names         = [f"load_{b}" for b in loads_wide.columns if b in buses_in_network]
    loads_wide.columns = [f"load_{b}" for b in loads_wide.columns]
    valid_cols         = [c for c in load_names if c in loads_wide.columns]

    # Reindex to the network's snapshots so loads and profiles share the same
    # time index. Buses that exist in the loads file but not in the simplified
    # .nc are already filtered out above by the buses_in_network check.
    loads_final = loads_wide[valid_cols].reindex(n.snapshots).fillna(0.0)
    n.loads_t.p_set = loads_final

    demand_max = loads_final.sum(axis=1).max()
    print(f"  Buses with demand : {n_loads}")
    print(f"  Snapshots covered : {len(loads_final)}")
    print(f"  Peak demand       : {demand_max:,.1f} MW")


# =============================================================================
# STEP 5 — Build parent-bus map
# =============================================================================

def build_parent_map():
    """
    Reads buses_final.csv + fusion_map.csv and returns a dict
    {secondary_bus_name -> parent_bus_name_as_present_in_network}.

    A bus qualifies as secondary iff parent_bus_id is present and non-null in
    buses_final.csv. The parent_bus_id is resolved to a bus name via the bus_id
    lookup, then the fusion_map (produced by script 08) is applied transitively:
    if a primary bus was merged into another primary by the bus-section-coupler
    logic, the mapping chases the chain until it reaches a "root" primary that
    actually exists in network_500kv.nc.

    Without the fusion_map resolution, secondaries whose parent was merged in
    script 08 would map to a bus name that does not exist in the .nc, causing
    broken bus references when generators/loads are moved.
    """
    print("\n[5/11] Building parent-bus map ...")
    buses = pd.read_csv(BUSES_FILE)

    required_cols = {"bus_id", "bus_name", "parent_bus_id"}
    missing = required_cols - set(buses.columns)
    if missing:
        print(f"  [ERROR] buses_final.csv missing columns: {sorted(missing)}")
        sys.exit(1)

    id_to_name = dict(zip(buses["bus_id"].astype(int), buses["bus_name"]))

    # Load fusion_map and build a transitive resolver.
    fusion_df = pd.read_csv(FUSION_MAP_FILE)
    raw_fusion = dict(zip(fusion_df["child_bus_name"], fusion_df["root_bus_name"]))

    def resolve_fusion(name):
        """Follows the fusion chain until a non-merged primary is reached."""
        seen = set()
        while name in raw_fusion:
            if name in seen:
                print(f"  [ERROR] Cycle detected in fusion_map at '{name}'")
                sys.exit(1)
            seen.add(name)
            name = raw_fusion[name]
        return name

    print(f"  fusion_map entries    : {len(raw_fusion)}")

    parent_map   = {}
    n_orphans    = 0
    n_refused    = 0
    secondaries  = buses[buses["parent_bus_id"].notna()]

    for _, row in secondaries.iterrows():
        parent_id   = int(row["parent_bus_id"])
        parent_name = id_to_name.get(parent_id)
        if parent_name is None:
            n_orphans += 1
            print(f"  [WARN] Secondary bus '{row['bus_name']}' has parent_bus_id={parent_id} "
                  f"but no bus with that id exists in buses_final.csv")
            continue

        # Apply transitive fusion resolution
        resolved = resolve_fusion(parent_name)
        if resolved != parent_name:
            n_refused += 1

        parent_map[row["bus_name"]] = resolved

    print(f"  Secondary buses found : {len(secondaries)}")
    print(f"  Mappings resolved     : {len(parent_map)}")
    if n_refused:
        print(f"  Mappings redirected   : {n_refused}  (parent was merged via fusion_map)")
    if n_orphans:
        print(f"  [WARN] Orphan secondaries (no parent found): {n_orphans}")

    return parent_map


# =============================================================================
# STEP 6 — Move generators to parent buses
# =============================================================================

def move_generators(n, parent_map):
    print("\n[6/11] Moving generators to parent buses ...")
    if len(n.generators) == 0:
        print("  No generators in network — nothing to move.")
        return

    on_secondary = n.generators["bus"].isin(parent_map.keys())
    n_moving = int(on_secondary.sum())

    if n_moving == 0:
        print("  No generators on secondary buses — nothing to move.")
        return

    n.generators.loc[on_secondary, "bus"] = (
        n.generators.loc[on_secondary, "bus"].map(parent_map)
    )

    print(f"  Generators moved : {n_moving}")
    print(f"  Generators total : {len(n.generators)} (unchanged)")


# =============================================================================
# STEP 7 — Move loads to parent buses
# =============================================================================

def move_loads(n, parent_map):
    print("\n[7/11] Moving loads to parent buses ...")
    if len(n.loads) == 0:
        print("  No loads in network — nothing to move.")
        return

    on_secondary = n.loads["bus"].isin(parent_map.keys())
    n_moving = int(on_secondary.sum())

    if n_moving == 0:
        print("  No loads on secondary buses — nothing to move.")
        return

    n.loads.loc[on_secondary, "bus"] = (
        n.loads.loc[on_secondary, "bus"].map(parent_map)
    )

    print(f"  Loads moved : {n_moving}")
    print(f"  Loads total : {len(n.loads)} (unchanged, identities preserved)")


# =============================================================================
# STEP 8 — Remove transformers
# =============================================================================

def remove_transformers(n):
    print("\n[8/11] Removing transformers ...")
    n_trafos = len(n.transformers)
    if n_trafos == 0:
        print("  No transformers to remove.")
        return

    for tf in list(n.transformers.index):
        n.remove("Transformer", tf)

    print(f"  Transformers removed : {n_trafos}")


# =============================================================================
# STEP 9 — Remove secondary buses
# =============================================================================

def remove_secondary_buses(n, parent_map):
    print("\n[9/11] Removing secondary buses ...")

    secondaries_in_net = [b for b in parent_map.keys() if b in n.buses.index]

    if not secondaries_in_net:
        print("  No secondary buses left in network.")
        return

    # Defensive check: confirm nothing still references these buses.
    still_referenced = set()
    for comp_name, comp_df in [
        ("Generator", n.generators),
        ("Load",      n.loads),
        ("Line",      n.lines),
        ("Link",      n.links),
    ]:
        if len(comp_df) == 0:
            continue
        bus_cols = [c for c in ("bus", "bus0", "bus1") if c in comp_df.columns]
        for col in bus_cols:
            hits = comp_df[col].isin(secondaries_in_net)
            if hits.any():
                still_referenced.update(comp_df.loc[hits, col].unique())

    if still_referenced:
        print(f"  [ERROR] {len(still_referenced)} secondary buses still referenced by "
              f"components. Aborting before removal to avoid dangling references.")
        print(f"          Sample: {sorted(still_referenced)[:5]}")
        sys.exit(1)

    for b in secondaries_in_net:
        n.remove("Bus", b)

    print(f"  Secondary buses removed : {len(secondaries_in_net)}")
    print(f"  Buses remaining         : {len(n.buses)}")


# =============================================================================
# STEP 10 — Integrity validation
# =============================================================================

def run_validation(n, stats_before):
    """
    Runs integrity checks against the pre-simplify state and prints a report.
    Returns one of: "OK" | "WARN" | "FAIL".
    """
    print(f"\n{'='*60}")
    print("INTEGRITY VALIDATION")
    print(f"{'='*60}")

    stats_after = capture_stats(n)
    warnings = []
    failures = []

    # --------------------------------------------------------------
    # Block 1: Component balance
    # --------------------------------------------------------------
    print("\n[Block 1] Component balance")
    print(f"  {'Component':<20} {'Before':>10} {'After':>10} {'Expected':>15}")
    print(f"  {'-'*20} {'-'*10} {'-'*10} {'-'*15}")

    checks = [
        ("Buses",        "n_buses",        "decreases",   None),
        ("Generators",   "n_generators",   "unchanged",   stats_before["n_generators"]),
        ("Loads",        "n_loads",        "unchanged",   stats_before["n_loads"]),
        ("Transformers", "n_transformers", "= 0",         0),
        ("Lines",        "n_lines",        "unchanged",   stats_before["n_lines"]),
        ("Links",        "n_links",        "unchanged",   stats_before["n_links"]),
    ]

    for label, key, expected_desc, expected_val in checks:
        before = stats_before[key]
        after  = stats_after[key]
        print(f"  {label:<20} {before:>10} {after:>10} {expected_desc:>15}")

        if expected_val is not None and after != expected_val:
            failures.append(f"{label}: after={after}, expected={expected_val}")

    if stats_after["n_buses"] >= stats_before["n_buses"]:
        failures.append(f"Buses: did not decrease ({stats_before['n_buses']} -> {stats_after['n_buses']})")

    # --------------------------------------------------------------
    # Block 2: Physical invariants
    # --------------------------------------------------------------
    print("\n[Block 2] Physical invariants")
    p_nom_before  = stats_before["p_nom_total_mw"]
    p_nom_after   = stats_after["p_nom_total_mw"]
    demand_before = stats_before["peak_demand_mw"]
    demand_after  = stats_after["peak_demand_mw"]

    p_nom_diff_mw  = abs(p_nom_after  - p_nom_before)
    demand_diff_mw = abs(demand_after - demand_before)

    print(f"  Total p_nom (MW)   before: {p_nom_before:>12,.2f}")
    print(f"  Total p_nom (MW)   after : {p_nom_after:>12,.2f}")
    print(f"  Difference         (MW)  : {p_nom_diff_mw:>12,.4f}   (tolerance: 0.01)")

    print(f"  Peak demand (MW)   before: {demand_before:>12,.2f}")
    print(f"  Peak demand (MW)   after : {demand_after:>12,.2f}")
    print(f"  Difference         (MW)  : {demand_diff_mw:>12,.4f}   (tolerance: 0.01)")

    if p_nom_diff_mw > 0.01:
        failures.append(f"p_nom changed by {p_nom_diff_mw:.4f} MW (expected 0)")
    if demand_diff_mw > 0.01:
        failures.append(f"peak demand changed by {demand_diff_mw:.4f} MW (expected 0)")

    # --------------------------------------------------------------
    # Block 3: Referential integrity
    # --------------------------------------------------------------
    print("\n[Block 3] Referential integrity")

    existing_buses = set(n.buses.index)
    ref_issues = []
    for comp_name, comp_df in [
        ("Generator", n.generators),
        ("Load",      n.loads),
        ("Line",      n.lines),
        ("Link",      n.links),
    ]:
        if len(comp_df) == 0:
            continue
        bus_cols = [c for c in ("bus", "bus0", "bus1") if c in comp_df.columns]
        for col in bus_cols:
            broken = comp_df[~comp_df[col].isin(existing_buses)]
            if not broken.empty:
                ref_issues.append((comp_name, col, len(broken), broken.index[:3].tolist()))

    if not ref_issues:
        print("  All component -> bus references are valid.")
    else:
        for comp_name, col, count, sample in ref_issues:
            print(f"  [FAIL] {count} {comp_name}(s) with broken '{col}' reference. Sample: {sample}")
            failures.append(f"{count} {comp_name}(s) with broken {col}")

    # --------------------------------------------------------------
    # Block 4: Topological connectivity
    # --------------------------------------------------------------
    print("\n[Block 4] Topological connectivity")

    G = nx.Graph()
    G.add_nodes_from(n.buses.index)
    for _, line in n.lines.iterrows():
        G.add_edge(line["bus0"], line["bus1"])
    for _, link in n.links.iterrows():
        G.add_edge(link["bus0"], link["bus1"])

    components   = list(nx.connected_components(G))
    n_components = len(components)
    print(f"  Connected components : {n_components}")

    if n_components == 1:
        print("  Network is fully connected.")
    else:
        sizes = sorted((len(c) for c in components), reverse=True)
        print(f"  Component sizes      : {sizes}")
        for i, comp in enumerate(sorted(components, key=len)):
            if len(comp) <= 5:
                print(f"  Island {i+1} ({len(comp)} bus[es]): {sorted(comp)}")
        warnings.append(f"Network has {n_components} connected components (expected 1)")

    # --------------------------------------------------------------
    # Block 5: Special cases
    # --------------------------------------------------------------
    print("\n[Block 5] Special cases")

    if BRAZIL_BUS in n.buses.index:
        print(f"  '{BRAZIL_BUS}' bus   : present [OK]")
    else:
        print(f"  '{BRAZIL_BUS}' bus   : MISSING [FAIL]")
        failures.append(f"Virtual bus '{BRAZIL_BUS}' was removed")

    gens_per_bus  = n.generators.groupby("bus").size() if len(n.generators) else pd.Series(dtype=int)
    loads_per_bus = n.loads.groupby("bus").size()      if len(n.loads)      else pd.Series(dtype=int)
    buses_with_gen    = set(gens_per_bus.index)
    buses_with_load   = set(loads_per_bus.index)
    buses_active      = buses_with_gen | buses_with_load
    buses_passthrough = set(n.buses.index) - buses_active

    print(f"  Buses with generation: {len(buses_with_gen):>4}")
    print(f"  Buses with demand    : {len(buses_with_load):>4}")
    print(f"  Pass-through buses   : {len(buses_passthrough):>4}   (info only — not an error)")

    # --------------------------------------------------------------
    # Verdict
    # --------------------------------------------------------------
    print(f"\n{'='*60}")
    if failures:
        print(f"[FAIL] Simplify broke the network — do NOT use the output file")
        print(f"       {len(failures)} failure(s):")
        for f in failures:
            print(f"         - {f}")
        if warnings:
            print(f"       Also {len(warnings)} warning(s):")
            for w in warnings:
                print(f"         - {w}")
        print(f"{'='*60}")
        return "FAIL"

    if warnings:
        print(f"[WARN] Simplify completed with {len(warnings)} warning(s) — review output above")
        for w in warnings:
            print(f"         - {w}")
        print(f"{'='*60}")
        return "WARN"

    print(f"[OK] Simplify completed without integrity issues")
    print(f"{'='*60}")
    return "OK"


# =============================================================================
# STEP 11 — Save
# =============================================================================

def save_network(n):
    os.makedirs(OUTPUT_NETWORK.parent, exist_ok=True)
    n.export_to_netcdf(OUTPUT_NETWORK)
    print(f"\n  Saved: {OUTPUT_NETWORK}")


# =============================================================================
# MAIN
# =============================================================================

def main():
    print("=" * 60)
    print("20A_simplify_network.py -- collapse secondary buses to 500 kV parents")
    print("=" * 60)

    print("\n[0/11] Verifying inputs ...")
    verify_inputs()

    n = load_network()
    add_generators(n)
    add_profiles(n)
    add_demand(n)

    parent_map = build_parent_map()

    stats_before = capture_stats(n)

    move_generators(n, parent_map)
    move_loads(n, parent_map)
    remove_transformers(n)
    remove_secondary_buses(n, parent_map)

    status = run_validation(n, stats_before)

    if status == "FAIL":
        print("\n[ABORTED] Output file not written.")
        sys.exit(1)

    save_network(n)

    print(f"\n{'='*60}")
    print(f"Simplify completed with status: {status}")
    print(f"Output: {OUTPUT_NETWORK}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
