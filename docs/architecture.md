# PyPSA-AR Architecture

## Objective

Build a calibrated and reproducible model of the Argentine high-voltage power grid using PyPSA.

The strategy is to build the network level by level, validating each one before incorporating the next.
The 500 kV network is the backbone of the SADI and the starting point.

---

## Model scope

**v0.1 — Complete 500 kV network (current state):**
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
- Fixed annual marginal costs per unit (~433 with assigned cost)

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
