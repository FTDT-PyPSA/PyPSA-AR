# PyPSA-AR Data Sources

This document describes the project's data sources and their current status.

---

## 1. Transmission network — 500 kV

### Primary source: PSS/E ver2526pid.raw (CAMMESA)

Case: *Peak Weekday Daytime Summer 25/26 — SADI Demand 30,960 MW*

Contains:
- BUS DATA: buses with voltage level, type (PQ/PV/slack), area
- BRANCH DATA: lines and series compensators with r, x, b in pu (Sbase=100 MVA) and MVA ratings
- TRANSFORMER DATA: inter-level transformers (2W and 3W)

Processed by: `01_parse_raw_buses.py`, `02_parse_raw_lines.py`, `03_parse_raw_transformers.py`, `04_parse_raw_buses_sec.py`

### Geographic source: GeoSADI (CAMMESA)

URL: https://www.arcgis.com/apps/instant/sidebar/index.html?appid=4b0ffba2055745a3afdbe1444d2db6d7

Layers used:
- `estaciones_transformadoras.geojson` — substation coordinates and names by voltage level
- `lineas_alta_tension.geojson` — line geometry with name and voltage
- `centrales_electricas.csv` — power plants with name, nemo and coordinates

Processed by: `05_match_geosadi_coords.py`, `06_match_geosadi_geometry.py`, `11_add_geo_to_generators.py`

### Manual matching dictionaries

`data/network_500kv/buses_PSSE_vs_geosadi.xlsx` — curated coordinates for the 95 500 kV buses. Versioned in Git.

`data/network_500kv/manual_line_mappings.csv` — manual mapping line_key → geosadi_line_id. Versioned in Git.

`data/network_500kv/generators_manualpypsa.csv` — manual assignments for pending generators. Versioned in Git.

`data/network_500kv/conflicts_psse_cammesa.csv` — manual resolution of mismatches between PSS/E names and CAMMESA GRUPOs. Versioned in Git.

### Status

✅ 95 500 kV buses + 249 secondary buses in the network (344 total after coupler fusion)
✅ 103 active lines processed
✅ 300 transformers processed
✅ Topology validated (1 connected component, 0 isolated buses)
✅ Visual verification in QGIS

---

## 2. Generation

### Primary source: CAMMESA — VALORES_2024.csv

Hourly generation file from the Argentine Wholesale Electricity Market (MEM) for 2024.
Contains ENERGIA (MWh), POT_DISP (MW), ENERG_OPERADA (MWh) and POT_DISP_GN (MW) per
GRUPO and hour, for all dispatch units.

Processed by: `13_clean_valores_2024.py` → `valores_2024_clean.csv`

Transformations applied:
- Filter year 2024
- Datetime format normalization to DD/MM/YYYY HH:MM
- Exclusion of YACYHIPY (Paraguayan side of Yacyretá)
- Factor 0.5 to SGDE (Salto Grande — binational plant Argentina/Uruguay)
- Outlier detection per GRUPO (flag_outlier)

Output file: `valores_2024_clean.csv` — external to GitHub (~580 MB).

### Complementary source: GeoSADI — centrales_electricas

Coordinates and nemo for 436 SADI power plants. Used to assign geographic
coordinates to the model's generator units.

### Status

✅ 669 generator units in `generators_final.csv`
✅ 626 units in `generators_2024.csv` with real 2024 p_nom (p95 POT_DISP)
✅ 77 PSS/E vs CAMMESA conflicts detected and resolved manually
✅ Total system p_nom: ~40,084 MW
✅ Hourly p_max_pu profiles 2024: `gen_profiles_2024.csv` (external to GitHub, ~5.3M rows, ~577 units)
✅ Marginal costs: `marginal_costs_2024.csv` (cost + per-unit efficiency and heat rate from CAMMESA)

---

## 3. Demand

### Source: CAMMESA — Dda_horaria_x_trafo_2024.csv

2024 hourly demand by distribution transformer. Wide format: one row per
transformer, 8784 hourly value columns in MW. Includes metadata for each
transformer: 500 kV connection bus, region, province and share of provincial demand.

Processed by: `15_build_loads_2024.py` → `loads_2024.csv`

Output file: `loads_2024.csv` — versioned in Git (72 buses × 8784 hours).

### Status

✅ 72 buses with assigned demand
✅ System peak demand: 27,439 MW (01/02/2024 14:00)
✅ Annual average: ~15,963 MW | Minimum: ~9,365 MW (25/12/2024 07:00)

---

## 4. DC validation — 2024 peak demand snapshot

### Script: `16_snapshot_dc_peak2024.py`

Linearized DC flow on the maximum peak demand snapshot of 2024.

Results (01/02/2024 14:00):
- Dispatched generation: 26,374 MW
- Slack injection (ATUCHA 2): 1,013 MW
- Total demand: 27,439 MW
- Gap explained by Brazilian imports (~2,267 MW, not modeled)
- Most loaded line: C.COSTA-P.BAND.-1 at 133% of its PSS/E rating (rating identified at 866 MVA, conservative for the line's real operating conditions)

### Status

✅ DC flow converges
✅ Generation/demand balance consistent with CAMMESA data
✅ Congestion at C.COSTA-P.BAND. corridor coherent with the limitation of modeling only the 500 kV network without lower-voltage parallel paths

---

## 5. Marginal costs and efficiencies

### Source: CAMMESA — CVP_Termica.csv + CVP_renovar.csv + efficencies.xlsx

Variable production costs per plant, extracted from CAMMESA post-operative files,
plus a per-machine table of net electrical efficiency and net heat rate
(`C.E.NETO`) used by the scenario pipeline.

Processed by:
- `18_diagnose_marginal_costs.py` → `marginal_costs_diagnostic.csv` (coverage audit)
- `18b_build_marginal_costs_2024.py` → `marginal_costs_2024.csv` (final table with cost + efficiency)

Assignment logic:
- Thermal/nuclear: match by reduced key (nemo4 + unit number) against CVP_Termica
- Renewables: match by normalized plant name against CVP_renovar (annual average Jan-24 to Dec-24)
- Hydro and pending: `CVP_manual` column filled manually in the diagnostic file
- Per-unit `efficiency`, `heat_rate_kcal_per_kwh` and `efficiency_fuel`:
  attached to the same output table by matching against `efficencies.xlsx`,
  using the GN > FO > GO fuel hierarchy

Source CVP files and `efficencies.xlsx`: external to GitHub.
Output file: `marginal_costs_2024.csv` — versioned in Git.

### Status

✅ Marginal cost and efficiency table built and used downstream by scripts 19, 20A and 21

---

## 6. Optimization

### Script: `19_run_optimization.py`

Linear DC economic dispatch (OPF) over the 500 kV network for the configured period.
Uses `n.optimize()` with the HiGHS solver. Configurable parameters: time period,
day chunking for memory management, treatment of generators with no cost.

Output file: `results_2024_YYYYMMDD_YYYYMMDD.nc` in `networks/` — external to GitHub.

### Status

✅ Built and run on 2024 data

---

## 7. Scenarios

### Pipeline: 20A → 20B → 21 → 22

Future-year scenarios are built on top of a clustered version of the 500 kV
base network. The pipeline simplifies the network, clusters it spatially,
constructs the scenario inputs (demand growth, expandable generators,
target-year fuel prices) and solves the joint capacity-expansion + dispatch LP.

Processed by:
- `20A_simplify_network.py` → `network_500kv_simplified.nc` (collapses
  secondary buses to their 500 kV parents and attaches all 2024 inputs)
- `20B_network_clustering.py` → `cluster_k{N}.nc` + `clusters_k{N}.gpkg`
  (k-means clustering into K regions, default K = 10, 20, 30)
- `21_build_scenario.py` → `scenario_<name>_k{N}.nc` (scales demand, applies
  TSAM time aggregation, adds expandable generators with ATB-2035 costs,
  recomputes existing thermal marginal cost at target-year fuel prices,
  enforces per-cluster RES expansion caps)
- `22_run_scenario.py` → `results_<name>_k{N}/` (LP solver output: post-optimization
  `.nc` plus summary CSVs by carrier, cluster, line, fuel, plus per-generator
  fuel and CO2 traceability)

### Inputs (external to GitHub)

- `costs_2035_US.csv` — NREL Annual Technology Baseline Market+Moderate
  scenario for 2035: capex, FOM, VOM, efficiency, lifetime, WACC per technology.
  Used by 21 to annualize capital and to set new-build efficiencies and
  fallback efficiencies for unmatched existing units.
- `efficencies.xlsx` — already described in section 5; also used downstream
  by the scenario pipeline through `marginal_costs_2024.csv`.
- `fuel_properties.yaml` — physical heating values, reporting units and
  IPCC / Tercer BUR CO2 emission factors per fuel code (GN, FO, GO, CM).
  Used by 21 (marginal cost computation) and 22 (fuel and emissions reporting).
- `carrier_defaults.yaml` — per-carrier default fuel codes and ATB-based
  fallback efficiencies for thermal units missing a CAMMESA match.

### Status

✅ Pipeline built end-to-end. First validated scenario: **2035 BAU at K = 10**
(demand 188 TWh, RES capped at 5 GW solar + 3 GW wind, total annual cost
~5.65 billion USD, ~42 MtCO2)

---

## 8. Renewables (VRE) — for future stages

### Wind and solar

- ERA5 (wind speeds, irradiance)
- Argentine Solar Atlas
- Processing with atlite for hourly capacity factors

In the current version, solar and wind profiles are built from real CAMMESA 2024 ENERGIA
(script 17). ERA5/atlite meteorological profiles will be incorporated in future stages
for prospective scenarios.

Status: 🔲 not started.

---

## 9. Fuel prices and emissions

### Sources

- ENARGAS (natural gas)
- CAMMESA (reference prices)
- IRENA / NREL ATB (international references)
- Argentine Tercer BUR / IPCC: emission factors per fuel and net heating values

### Status

✅ Partial. The scenario pipeline (script 21) uses 2035 fuel prices for natural
gas, fuel oil and gas oil from internal references, and applies CO2 emission
factors per fuel code from `fuel_properties.yaml` (Tercer BUR / IPCC defaults).
Coal (`CM`) is declared in the fuel properties file but not yet wired into
scenario pricing. A more granular price structure (e.g. monthly, regional)
remains pending.

---

## Data management principles

- Every source must have a reference and extraction date.
- Large raw files (.raw, .geojson, .nc, .csv >50 MB) are stored outside of Git.
- Only versioned: scripts, lightweight processed CSVs, matching dictionaries and documentation.
- All transformations are reproducible from the source files.
