# PyPSA-AR Architecture

## Objective

Build a calibrated and reproducible model of the Argentine high-voltage power grid using PyPSA.

The strategy is to build the network level by level, validating each one before incorporating the next.
The 500 kV network is the backbone of the SADI and the starting point.

---

## Model scope

**v0.1 — Complete 500 kV network + scenario pipeline (current state):**
- All 500 kV buses and their secondary buses (transformer low-side)
- Lines with real PSS/E impedances (r, x, b in pu, Sbase=100 MVA)
- Series compensators identified and modeled as Line with negative x
- 3-winding transformers decomposed into 2 × 2W with the 500 kV bus as reference
- Bus coupler fusion (series_compensator with r=0): internal buses collapsed
  to the group representative before building the network
- Argentina–Brazil interconnection: fictitious BRASIL bus, RINCON-GARABI-1 line with
  real PSS/E data, Link `importacion_brasil` (p_nom=2200 MW, marginal_cost=110 USD/MWh,
  import only)
- 626 generator units with p_nom from real CAMMESA 2024 data (~577 with hourly profile —
  the remaining units without a CAMMESA match are excluded from the network at optimization time)
- 2024 hourly demand per bus (72 buses, 8784 hours)
- Hourly availability profiles (p_max_pu) for all units with a CAMMESA match
- Fixed annual marginal costs per unit from CAMMESA CVP files
- Per-unit efficiency and net heat rate from CAMMESA `efficencies.xlsx` for thermal generators
- Network simplification (secondary buses collapsed to their 500 kV parents)
- Spatial k-means clustering into K regions (default: 10, 20, 30)
- Future-year scenario builder with TSAM time aggregation, ATB-2035 cost data
  for new builds, target-year fuel prices for existing thermal recomputation
  and per-cluster RES expansion caps
- Joint capacity-expansion + dispatch LP solver (HiGHS) with reporting of
  fuel consumption (in CAMMESA reporting units) and CO2 emissions (Tercer BUR factors)

**v0.2 and beyond:**
- Incorporate 220, 330, 132 kV levels one by one
- Inter-level transformers
- Complete generation and demand

**Out of scope:**
- Distribution (MV/LV)

---

## Data sources

| Component | Source | Format |
|-----------|--------|--------|
| Topology and impedances | PSS/E ver2526pid.raw (CAMMESA) | .raw |
| Bus coordinates | GeoSADI — estaciones_transformadoras | .geojson |
| Line geometry | GeoSADI — lineas_alta_tension | .geojson |
| 2024 hourly generation | CAMMESA — VALORES_2024.csv | .csv |
| 2024 hourly demand | Internal file — Dda_horaria_x_trafo_2024.csv | .csv |
| Marginal costs | CAMMESA — CVP_Termica.csv + CVP_renovar.csv | .csv |
| Per-unit efficiency and heat rate | CAMMESA — efficencies.xlsx | .xlsx |
| Future technology costs | NREL Annual Technology Baseline (ATB) — costs_2035_US.csv | .csv |
| Fuel properties (heating values, CO2 factors) | Internal — fuel_properties.yaml + carrier_defaults.yaml | .yaml |

GeoSADI: https://www.arcgis.com/apps/instant/sidebar/index.html?appid=4b0ffba2055745a3afdbe1444d2db6d7

---

## Construction pipeline

```
PSS/E .raw ──→ 01_parse_raw_buses.py          ──→ buses_500kv_raw.csv
               02_parse_raw_lines.py           ──→ lines_500kv_raw.csv
               03_parse_raw_transformers.py    ──→ trafos_500kv_raw.csv
               04_parse_raw_buses_sec.py       ──→ buses_sec_raw.csv
                        │
GeoSADI ────→ 05_match_geosadi_coords.py      ──→ buses_final.csv
              06_match_geosadi_geometry.py     ──→ lines_500kv_final.csv
                        │
              07_validate_topology.py          ──→ topology_report.csv
              07b_export_qgis.py               ──→ red_500kv_qgis.gpkg
                        │
              08_build_network.py              ──→ network_500kv.nc
                        │
              09_map_generators.py             ──→ generators_mapped.csv
              10_map_loads.py                  ──→ loads_mapped.csv
              10b_visualize_qgis.py            ──→ balance_gen_carga.gpkg
              11_add_geo_to_generators.py      ──→ generators_readypypsa.csv
              12_build_generators_final.py     ──→ generators_final.csv
              12b_export_qgis_generators.py    ──→ layer centrales en .gpkg
                        │
CAMMESA ────→ 13_clean_valores_2024.py        ──→ valores_2024_clean.csv *
              14_detect_generator_conflicts.py ──→ conflicts_psse_cammesa.csv
              14b_build_generators_2024.py     ──→ generators_2024.csv
              15_build_loads_2024.py           ──→ loads_2024.csv
              16_snapshot_dc_peak2024.py       ──→ (DC validation — no output)
              17_build_gen_profiles_2024.py    ──→ gen_profiles_2024.csv *
                        │
CVP CAMMESA → 18_diagnose_marginal_costs.py   ──→ marginal_costs_diagnostic.csv
              18b_build_marginal_costs_2024.py ──→ marginal_costs_2024.csv
                        │
              19_run_optimization.py           ──→ results_2024_*.nc *
                        │
              20A_simplify_network.py          ──→ network_500kv_simplified.nc *
              20B_network_clustering.py        ──→ cluster_k{N}.nc *
                        │
ATB + YAMLs → 21_build_scenario.py             ──→ scenario_<name>_k{N}.nc *
              22_run_scenario.py               ──→ results_<name>_k{N}/ *

* Files external to GitHub due to size
```

---

## PyPSA model layers

### 1. Physical network
- 500 kV buses with GeoSADI coordinates and voltage level
- Secondary buses inheriting coordinates from their 500 kV parent bus
- Lines with r, x, b, s_nom (from ratea_mva in PSS/E)
- Series compensators as Line with negative x
- Transformers with x, s_nom
- Link `importacion_brasil`: p_nom=2200 MW, import only (p_min_pu=0), marginal_cost=110 USD/MWh

### 2. Generation
- ~577 active generator units in the network (626 total; ~49 excluded for having no CAMMESA match)
- `p_nom` per unit: 95th percentile of annual CAMMESA 2024 POT_DISP, distributed
  proportionally to the PSS/E pt_mw among the units of each plant
- `p_max_pu` hourly: ENERGIA/p_nom for solar, wind, biogas and biomass;
  POT_DISP/p_nom for the rest
- Carriers: ocgt, steam, ccgt, hydro, nuclear, wind, solar, diesel, biogas, biomass, pumped_hydro
- `marginal_cost` per unit: from `marginal_costs_2024.csv` (~433 with value)

### 3. Demand
- Hourly profiles 8784h (year 2024, leap year)
- 72 buses with assigned demand
- Source: Dda_horaria_x_trafo_2024.csv — demand by distribution transformer

### 4. Validation
- Linearized DC flow (n.lpf()) on the peak demand snapshot (01/02/2024 14:00)
- Slack bus: ATUCHA 2_21kV (bus 2620, nuclear machine terminal, PSS/E reference)

### 5. Optimization
- `n.optimize()` linear DC with HiGHS solver
- Objective: minimize total generation cost subject to network and capacity constraints
- No additional constraints in this version: no minimum technical outputs or ramp rates
- Virtual load shedding at each bus (cost=10,000 USD/MWh) to guarantee feasibility
- Configurable period: `START_DATE`, `END_DATE`, `CHUNK_DAYS` parameters
- Output: `results_2024_YYYYMMDD_YYYYMMDD.nc`

### 6. Scenarios
- Built on top of clustered networks (`cluster_k{N}.nc`) generated by 20A + 20B
- Demand scaled to a target year using a constant annual growth rate
  (default: 3% / year, 2024 → 2035 = factor 1.384)
- Time aggregation via TSAM: 16 typical days × 24 h = 384 snapshots,
  hierarchical clustering, `distributionAndMinMaxRepresentation` to preserve peaks.
  Per-cluster demand and per-(carrier, cluster) weighted-average availability
  profiles are aggregated; each generator's `p_max_pu` is then reassigned from
  its (carrier, cluster) typical profile so hourly availability constraints
  are preserved (in particular the 2024 hydro dispatch ceiling)
- Expandable generators added per (carrier, cluster) for `ccgt`, `ocgt`,
  `diesel`, `solar`, `wind`. Capital cost annualized using ATB lifetime + WACC.
  Marginal cost for new thermal builds: `VOM + fuel_price_target_year / efficiency`
- Per-cluster expansion caps for variable RES via `p_nom_max`
  (default: 5,000 MW solar + 3,000 MW wind total, distributed uniformly across K)
- **Existing thermal generators have their `marginal_cost` recomputed** at the
  target-year fuel price using the real CAMMESA efficiency (when available)
  and the same VOM as new builds. Units without a CAMMESA match use the ATB
  fallback efficiency for their carrier
- Existing inter-cluster lines are made expandable using overhead HVAC capex
  from ATB / Danish Energy Agency Technology Data, annualized at 40 yr / 5.36% WACC
- Joint LP solved by HiGHS: minimize annualized capex + dispatch cost
  subject to power balance, line and generator capacity limits, and per-cluster
  RES caps. Output is the post-optimization `.nc` plus summary CSVs (global,
  per carrier, per cluster, per line, per fuel, plus per-generator fuel and
  emissions for traceability)
- Fuel consumption and CO2 emissions are reported using physical heating
  values (kcal/m³ for gas, kcal/kg for fuel oil and coal, kcal/l for gas oil)
  and IPCC / Tercer BUR emission factors loaded from `fuel_properties.yaml`

---

## Modeling decisions

### Network
- Impedances in pu (Sbase=100 MVA confirmed in PSS/E header)
- Conversion to physical units: Z_base = baskv² / S_base per line
- Bus couplers fused in memory — original CSVs are not modified
- s_nom from PSS/E ratea_mva (operational thermal rating; may be conservative
  relative to the conductor's actual thermal capacity)

### Generation
- p_nom from 95th percentile of POT_DISP — avoids outliers without discarding real peaks
- Yacyretá: CAMMESA reports the entire plant; distributed by p_nom across the 20 units
- Salto Grande (SGDE): factor 0.5 on POT_DISP (binational plant Argentina/Uruguay)
- Units without a CAMMESA match (self-producers, outside the MEM): excluded from the network
- International imports (Brazil): modeled as Link with a fixed reference cost

### Marginal costs
- Fixed annual cost per unit (does not vary by hour or fuel in this version)
- Thermal/nuclear: from CAMMESA CVP_Termica, filter year 2026 week 1
- Renewables: annual average from CAMMESA CVP_renovar 2024
- Hydro pending of costs until but capped to maximum actual production of each day until better ways of modelling are implemented.

### Scenarios
- Single target-year snapshot ("end-state" scenario), not a multi-year trajectory.
  Capacity decisions reflect the optimal mix at the target year; the model does
  not specify when each unit gets built nor track investment timing
- Demand growth: constant annual rate applied uniformly across hours and clusters
- Costs for new builds: NREL ATB Market+Moderate scenario for the target year,
  in USD; FOM as a percentage of capex, VOM in USD/MWh, WACC per technology
- Costs for existing thermal: recomputed at the target-year fuel price using
  real CAMMESA efficiency (or ATB fallback) and ATB VOM. The original CVP-2024
  marginal cost is overwritten in the scenario `.nc` so existing and new units
  compete on the same price basis at the target year
- Fuel codes assigned to existing generators come from the CAMMESA efficiency
  table when matched (GN > FO > GO hierarchy). Unmatched thermal units fall
  back to per-carrier defaults (CCGT/OCGT → GN, diesel → GO, steam → FO)
- Time aggregation: 16 typical days × 24 h via TSAM with the
  `distributionAndMinMaxRepresentation` method, which preserves the
  distribution of values plus the min/max within each cluster. Snapshot
  weightings sum to ~8,784 (full year). Capacity-factor and saturation-hour
  metrics derived from these weightings are estimates, not directly observed
  hours
- Expansion limits on variable RES are imposed via `p_nom_max` per cluster.
  Limits are simplifications that stand in for unmodeled constraints
  (land availability, resource quality, grid hosting capacity per region)
- No storage modeled in v0.1 (no batteries, no pumped hydro flexibility,
  no seasonal storage). Hydro respects its 2024 dispatch ceiling but does
  not model reservoir state
- No emission cap is imposed; CO2 is reported as a post-optimization output

### DC flow
- Standard DC approximation: no losses, small angles
- The slack absorbs the generation/demand imbalance (difference between dispatched p_set
  and total demand, mainly explained by unmodeled imports)

---

## Design principles

- **Reproducibility**: the entire pipeline is scriptable from the .raw to the .nc
- **Primary sources**: GeoSADI + PSS/E are the source of truth, not OSM
- **Modularity**: each voltage level is built and validated separately
- **Lightweight git**: only scripts, documentation and processed CSVs. No .nc or large files
- **Flexibility**: configurable parameters in the CONFIGURATION section of each script — without modifying logic
