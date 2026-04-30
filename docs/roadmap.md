# PyPSA-AR Roadmap

Objective: calibrated and reproducible model of the Argentine power grid using PyPSA.

Construction strategy: start with the complete 500 kV network and close it before
incorporating lower voltage levels. Each level is validated before moving to the next.

---

## Phase 0 — Repository and structure ✅ COMPLETED

- GitHub repository initialized
- Folder structure defined
- Base documentation created
- Reproducible environment configured (pypsa-earth-lock on WSL)

---

## Phase 1 — PyPSA-Earth audit for Argentina ✅ COMPLETED

Objective: understand what PyPSA-Earth modeled for AR and decide whether to reuse or replace.

Result: decision made to replace all OSM data with GeoSADI + PSS/E.
Reasons documented in `docs/aprendizaje_pypsaearth_ar.md`.

Key findings:
- PyPSA-Earth has 125 transformers vs 1,132 real ones (11% coverage)
- 500 kV lines using European conductor type (380 kV)
- No active impedances (r=0, x=0)

---

## Phase 2 — 500 kV network construction ✅ COMPLETED

Sources: GeoSADI (geometry) + PSS/E ver2526pid.raw (topology and impedances)

| Script | Description | Status |
|--------|-------------|--------|
| `01_parse_raw_buses.py` | Extracts 500 kV buses from PSS/E | ✅ |
| `02_parse_raw_lines.py` | Extracts 500 kV lines from PSS/E | ✅ |
| `03_parse_raw_transformers.py` | Extracts transformers with a 500 kV winding | ✅ |
| `04_parse_raw_buses_sec.py` | Extracts secondary buses from transformers | ✅ |
| `05_match_geosadi_coords.py` | Assigns coordinates and consolidates all buses | ✅ |
| `06_match_geosadi_geometry.py` | Assigns WKT geometry to lines | ✅ |
| `07_validate_topology.py` | Validates network topology | ✅ |
| `07b_export_qgis.py` | Exports to GeoPackage for QGIS | ✅ |
| `08_build_network.py` | Builds the PyPSA Network object | ✅ |

500 kV network status:
- 95 500 kV buses + 249 secondary buses = 344 buses in the network
- 103 active lines (including series compensators)
- 300 transformers
- Bus coupler fusion applied: 17 buses merged to their group representative
- 1 connected component, 0 isolated buses
- Argentina–Brazil interconnection included: Link `importacion_brasil` (p_nom=2200 MW)

---

## Phase 3 — Generation and demand 500 kV ✅ COMPLETED

Objective: incorporate real 2024 generation and demand into the model and validate with DC flow.

| Script | Description | Status |
|--------|-------------|--------|
| `09_map_generators.py` | Maps PSS/E generators → model buses | ✅ |
| `10_map_loads.py` | Maps PSS/E loads → model buses | ✅ |
| `10b_visualize_qgis.py` | Exports generation/load balance to QGIS | ✅ |
| `11_add_geo_to_generators.py` | Assigns GeoSADI coordinates to generators | ✅ |
| `12_build_generators_final.py` | Definitive generator table for PyPSA | ✅ |
| `12b_export_qgis_generators.py` | Adds power plant layer to GeoPackage | ✅ |
| `13_clean_valores_2024.py` | Cleaning and normalization of VALORES_2024.csv | ✅ |
| `14_detect_generator_conflicts.py` | Detects PSS/E vs CAMMESA mismatches | ✅ |
| `14b_build_generators_2024.py` | Generators with real 2024 p_nom from CAMMESA | ✅ |
| `15_build_loads_2024.py` | 2024 hourly demand per bus in long format | ✅ |
| `16_snapshot_dc_peak2024.py` | DC validation at peak demand snapshot | ✅ |
| `17_build_gen_profiles_2024.py` | Hourly availability profiles (p_max_pu) | ✅ |

Validation snapshot results (01/02/2024 14:00 — 2024 peak demand):
- Dispatched generation: 26,374 MW | Slack injection: 1,013 MW | Demand: 27,439 MW
- Generation/demand gap explained by Brazilian imports (~2,267 MW, not modeled)
- Mix: 59% thermal, 26% hydro, 8% nuclear, 5% wind, 4% solar
- 1 line at 133% of its rating (C.COSTA-P.BAND.-1) — congestion consistent with expected as line has lower MVA than the normal for a 500kV line.

---

## Phase 4 — Marginal costs and optimization ✅ COMPLETED

Objective: incorporate marginal costs, run the 2024 economic dispatch and analyze results.

| Script | Description | Status |
|--------|-------------|--------|
| `18_diagnose_marginal_costs.py` | Cost coverage audit per unit | ✅ |
| `18b_build_marginal_costs_2024.py` | Fixed annual marginal cost table | ✅ |
| `19_run_optimization.py` | DC economic dispatch (OPF) — `n.optimize()` | ✅ |


Notes:
- Script 19 parameterized: configurable period (`START_DATE`/`END_DATE`), day chunking (`CHUNK_DAYS`), virtual load shedding to guarantee feasibility

---

## Phase 5 — Scenarios on top of the 500 kV network ✅ COMPLETED

Objective: build and optimize future-year scenarios on a clustered version of
the 500 kV base network. The clustering aggregates the ~80 simplified buses
into K regions (typical: 10) and the scenario builder scales demand,
recomputes marginal costs at target-year fuel prices, and adds expandable
generators and lines.

| Script | Description | Status |
|--------|-------------|--------|
| `20A_simplify_network.py` | Collapses secondary buses to their 500 kV parents and exports a self-contained simplified PyPSA network with all 2024 generators, loads, profiles, marginal costs and per-unit efficiencies attached | ✅ |
| `20B_network_clustering.py` | Spatial k-means clustering of the simplified network into K regions (default: 10, 20, 30) | ✅ |
| `21_build_scenario.py` | Builds a future-year scenario: scales demand, applies TSAM time aggregation (16 typical days × 24 h), adds expandable generators with ATB-2035 costs, recomputes marginal cost of every existing thermal generator at target-year fuel prices using its real CAMMESA efficiency (or ATB fallback when missing), enforces per-cluster RES expansion caps, makes inter-cluster lines expandable, and adds load shedding | ✅ |
| `22_run_scenario.py` | Solves the joint capacity-expansion + dispatch LP and produces a results directory with summary CSVs (global, by carrier, by cluster, by line, by fuel, new capacity, fuel by generator) plus the post-optimization `.nc` | ✅ |

First validated scenario — **2035 BAU at K=10**:
- Demand: 188 TWh (+38% over 2024)
- Time aggregation: TSAM 16 typical days, 384 snapshots
- New RES capped at 5,000 MW solar + 3,000 MW wind (total)
- Total annual cost: ~5.65 billion USD
- Renewable share: ~35%
- CO2 emissions: ~42 MtCO2 (~227 kgCO2/MWh)

---

## Phase 6 — Incorporate 220, 330, 132 kV levels 🔲 NEXT PHASE

Same pipeline as 500 kV, level by level.
Scripts 01–08 are reusable with different voltage filters.
Incorporate inter-level transformers.

Project deadline: 30/04/2026
