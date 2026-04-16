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
| `19_run_optimization.py` | DC economic dispatch (OPF) — `n.optimize()` | ✅ built, full-year run pending |


Notes:
- Script 19 parameterized: configurable period (`START_DATE`/`END_DATE`), day chunking (`CHUNK_DAYS`), virtual load shedding to guarantee feasibility

---

## Phase 5 — Incorporate 220, 330, 132 kV levels 🔲 NEXT PHASE

Same pipeline as 500 kV, level by level.
Scripts 01–08 are reusable with different voltage filters.
Incorporate inter-level transformers.

---

## Phase 6 — Expansion scenarios 🔲 PENDING

With the validated base model, run energy policy and network expansion scenarios.
Requires: validated model (Phase 5), future demand scenario definitions,
new technology cost curves, and decision on clustering levels to use.

Project deadline: 30/04/2026
