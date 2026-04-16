# scripts/network_500kv

500 kV network construction pipeline for PyPSA.
Run in order from WSL using the `pypsa-earth-lock` environment.

---

## Script index

| Script | Brief description | Input | Output |
|--------|-------------------|-------|--------|
| `01_parse_raw_buses.py` | Extracts 500 kV buses from PSS/E | `ver2526pid.raw` | `buses_500kv_raw.csv` |
| `02_parse_raw_lines.py` | Extracts lines and series compensators from PSS/E | `ver2526pid.raw` + `buses_500kv_raw.csv` | `lines_500kv_raw.csv` |
| `03_parse_raw_transformers.py` | Extracts transformers with at least one 500 kV winding | `ver2526pid.raw` + `buses_500kv_raw.csv` | `trafos_500kv_raw.csv` |
| `04_parse_raw_buses_sec.py` | Extracts secondary buses from transformers | `ver2526pid.raw` + `trafos_500kv_raw.csv` | `buses_sec_raw.csv` |
| `05_match_geosadi_coords.py` | Assigns coordinates and consolidates all buses | `buses_500kv_raw.csv` + `buses_sec_raw.csv` + `buses_PSSE_vs_geosadi.xlsx` | `buses_final.csv` |
| `06_match_geosadi_geometry.py` | Assigns WKT geometry to lines | `lines_500kv_raw.csv` + `buses_final.csv` + GeoSADI | `lines_500kv_final.csv` |
| `07_validate_topology.py` | Validates network topology | `buses_final.csv` + `lines_500kv_final.csv` + `trafos_500kv_raw.csv` | `topology_report.csv` |
| `07b_export_qgis.py` | Exports network to GeoPackage for QGIS | `buses_final.csv` + `lines_500kv_final.csv` + `trafos_500kv_raw.csv` | `red_500kv_qgis.gpkg` |
| `08_build_network.py` | Builds the PyPSA Network object | `buses_final.csv` + `lines_500kv_final.csv` + `trafos_500kv_raw.csv` | `network_500kv.nc` |
| `09_map_generators.py` | Maps PSS/E generators → model buses via BFS | `ver2526pid.raw` + `buses_final.csv` | `generators_mapped.csv` |
| `10_map_loads.py` | Maps PSS/E loads → model buses via BFS | `ver2526pid.raw` + `buses_final.csv` | `loads_mapped.csv` |
| `10b_visualize_qgis.py` | Exports generation/load balance per bus to GeoPackage | `generators_mapped.csv` + `loads_mapped.csv` + `buses_final.csv` | `balance_gen_carga.gpkg` |
| `11_add_geo_to_generators.py` | Assigns GeoSADI coordinates to generators | `generators_mapped.csv` + `buses_final.csv` + GeoSADI | `generators_readypypsa.csv` + `generators_pendingmanualpypsa.csv` |
| `12_build_generators_final.py` | Automatic + manual join → definitive generator table for PyPSA | `generators_readypypsa.csv` + `generators_manualpypsa.csv` | `generators_final.csv` |
| `12b_export_qgis_generators.py` | Adds power plant layer to the balance GeoPackage | `generators_final.csv` + `balance_gen_carga.gpkg` | `centrales_electricas` layer in `balance_gen_carga.gpkg` |
| `13_clean_valores_2024.py` | Cleaning and normalization of VALORES_2024.csv | `VALORES_2024.csv` (external) | `valores_2024_clean.csv` (external) |
| `14_detect_generator_conflicts.py` | Detects mismatches between PSS/E unit names and CAMMESA codes | `generators_final.csv` + `valores_2024_clean.csv` (external) | `conflicts_psse_cammesa.csv` |
| `14b_build_generators_2024.py` | Builds generator table with real 2024 capacity from CAMMESA | `generators_final.csv` + `conflicts_psse_cammesa.csv` + `valores_2024_clean.csv` (external) | `generators_2024.csv` |
| `15_build_loads_2024.py` | Builds 2024 hourly demand per 500 kV bus in long format | `Dda_horaria_x_trafo_2024.csv` (external) + `buses_final.csv` + `lines_500kv_final.csv` | `loads_2024.csv` |
| `16_snapshot_dc_peak2024.py` | Linearized DC flow at the 2024 peak demand snapshot | `network_500kv.nc` + `generators_2024.csv` + `loads_2024.csv` + `valores_2024_clean.csv` (external) | (console only — no output file) |
| `17_build_gen_profiles_2024.py` | Builds hourly availability profiles (p_max_pu) for all generator units | `generators_2024.csv` + `valores_2024_clean.csv` (external) | `gen_profiles_2024.csv` (external) |
| `18_diagnose_marginal_costs.py` | Diagnoses marginal cost coverage per generator unit | `generators_2024.csv` + `CVP_Termica.csv` (external) + `CVP_renovar.csv` (external) | `marginal_costs_diagnostic.csv` |
| `18b_build_marginal_costs_2024.py` | Builds final annual marginal cost table per generator unit | `generators_2024.csv` + `marginal_costs_diagnostic_completed.csv` + `CVP_Termica.csv` (external) + `CVP_renovar.csv` (external) | `marginal_costs_2024.csv` |
| `19_run_optimization.py` | Linear DC economic dispatch (OPF) over the 500 kV network | `network_500kv.nc` + `generators_2024.csv` + `loads_2024.csv` + `marginal_costs_2024.csv` + `gen_profiles_2024.csv` (external) | `results_2024_YYYYMMDD_YYYYMMDD.nc` |
| `aliases_500kv.py` | Alias dictionary for GeoSADI matching | — | (helper module) |

---

## Detail

### `01_parse_raw_buses.py`
Reads the `BUS DATA` section of the PSS/E `.raw` file and extracts all buses in the
490–530 kV range. Excludes buses with IDE=4 (isolated) and international buses (by
CAMMESA area).

Configurable parameters:
- `KV_MIN` / `KV_MAX` — voltage range
- `EXCLUDE_INTERNATIONAL` — include or exclude buses from neighboring countries
- `EXCLUDE_BUSES` — set of bus_name values to exclude manually

---

### `02_parse_raw_lines.py`
Reads the `BRANCH DATA` section of the PSS/E file and extracts all branches whose
both terminals are 500 kV buses. Classifies each branch as `line` or
`series_compensator` (x < 0).

Configurable parameters:
- `FORCE_ALL_IN_SERVICE` — force all branches as in-service regardless of ST field in the raw file

---

### `03_parse_raw_transformers.py`
Reads the `TRANSFORMER DATA` section of the PSS/E file and extracts transformers
with at least one 500 kV winding. 3-winding transformers are decomposed into two
2-winding transformers using the 500 kV winding as the common reference, avoiding
the need for fictitious star buses in PyPSA.

Configurable parameters:
- `FORCE_ALL_IN_SERVICE` — force all transformers as in-service

---

### `04_parse_raw_buses_sec.py`
Extracts the secondary buses (bus_j) from `trafos_500kv_raw.csv` and assigns them a
descriptive name in the format `PARENT_kVkV` or `PARENT_kVkV_N` when multiple buses
of the same voltage level exist for the same 500 kV parent bus.
Includes all voltage levels: network busbars (33–345 kV) and generator terminals
(11–22 kV).

---

### `05_match_geosadi_coords.py`
Assigns geographic coordinates to all buses and consolidates them into `buses_final.csv`:
- 500 kV buses: coordinates from the manual dictionary `buses_PSSE_vs_geosadi.xlsx`
- Secondary buses: inherit coordinates from their 500 kV parent bus (same physical substation)

---

### `06_match_geosadi_geometry.py`
For each PSS/E line, searches for the corresponding geometry in the GeoSADI GeoJSON.
Matching follows this priority order:
1. Manual dictionary `manual_line_mappings.csv`
2. Token-based name matching (via `aliases_500kv.py`)
3. Circuit number disambiguation for parallel lines

Possible values in `match_status`:
- `direct` — unique match found
- `parallel` — disambiguated by circuit number
- `manual_geo` — assigned from manual dictionary
- `compensator` — series compensator, no line geometry in GeoSADI
- `pending_bus` — one or both terminal buses have no coordinates assigned

---

### `07_validate_topology.py`
Validates the full network (500 kV buses + secondary + transformers) before loading
into PyPSA. Detects:
1. Orphan lines (terminal bus missing from buses_final.csv)
2. Orphan transformers (terminal bus missing from buses_final.csv)
3. 500 kV buses without lines — classified as series compensator central bus, transformer-only node, or truly isolated bus
4. Connected components of the 500 kV network (disconnected islands)
5. Lines with r=0 and x=0 simultaneously
6. Lines without a rating defined
7. Out-of-service branches (informational)

---

### `07b_export_qgis.py`
Exports the full network to a GeoPackage with four layers:
- `buses_500kv` — points with GeoSADI coordinates
- `buses_sec` — secondary bus points (coordinates inherited from parent)
- `lines_500kv` — lines with GeoSADI geometry
- `trafos_500kv` — transformers as points at the 500 kV parent bus coordinates

The `.gpkg` is saved to `data/GIS_psse_geosadi_pypsaearth/red_500kv_qgis.gpkg`.

---

### `08_build_network.py`
Builds the `pypsa.Network` object with the 500 kV network and exports it to `.nc`.

Modeling decisions:
- PSS/E impedances in pu (Sbase=100 MVA confirmed in raw file header)
- Conversion to physical units using dynamic Zbase per line: Z_base = baskv² / S_base
- Series compensators modeled as `Line` with negative x
- 3-winding transformers already decomposed into 2W from script 03
- Bus section couplers (series_compensator with r=0 exactly) detected and merged automatically: buses are collapsed to the lowest bus_id representative before adding lines and transformers. Original CSVs are not modified.
- PSS/E voltage profile (v_mag_pu, v_ang_deg) stored as bus attributes for warm start
- Argentina–Brazil interconnection included: fictitious BRASIL bus, RINCON-GARABI-1 line (real PSS/E data), `importacion_brasil` Link (p_nom=2200 MW, marginal_cost=110 USD/MWh)
- Output in `networks/network_500kv.nc` (not versioned in git)

---

### `09_map_generators.py`
Parses the `GENERATOR DATA`, `OWNER DATA` and `AREA DATA` sections of the PSS/E file
and maps each generator unit to the topologically nearest model bus (`buses_final.csv`)
using BFS over `BRANCH DATA` + `TRANSFORMER DATA`.

**Carrier resolution:**
Extracted from the Owner 1 (O1) field of each generator, cross-referenced against
`OWNER DATA`. Known owner IDs are mapped to standard PyPSA carriers (ocgt, steam,
hydro, diesel, ccgt, nuclear, wind, solar, biogas, biomass, battery).
If the resolved carrier does not correspond to generation, it is inferred from
positions [4:6] of the bus_name:
- TG → ocgt, TV → steam, HI → hydro, DI → diesel, CC → ccgt
- FV → solar, EO → wind, BG → biogas, BM → biomass, HB → pumped_hydro
- Positions [4:8] = NUCL → nuclear

---

### `10_map_loads.py`
Same BFS logic as `09_map_generators.py` applied to PSS/E loads.
Excludes loads from international areas (Paraguay, Chile SING, Brazil, Bolivia, Uruguay).

---

### `10b_visualize_qgis.py`
Exports the generation/load balance per model bus to a GeoPackage for QGIS.

---

### `11_add_geo_to_generators.py`
Assigns GeoSADI coordinates and power plant name to each generator in
`generators_mapped.csv`.

Geographic matching: compares the first 4 characters of `bus_name_origen` against
the `Nemo` field of `centrales_electricas.csv`. Ambiguities are resolved by
technology type using the carrier → GeoSADI type index. Irreducible cases are
resolved via the `NEMO_PREFERIDO` dictionary hardcoded in the script.

---

### `12_build_generators_final.py`
Merges `generators_readypypsa.csv` with rows from `generators_manualpypsa.csv` that
have `geosadi_name` and `bus_conexion500kv` filled in.

The `nemo` field is resolved by joining `geosadi_name` → `Nombre` in GeoSADI's
`centrales_electricas.csv`.

CAPE/ACAJ reassignment: units TG01, TG06 and TV07 of Agua del Cajón are reassigned
to `nemo = CAPE` (CAPEX Autoprod.) directly in this script.

---

### `12b_export_qgis_generators.py`
Adds a power plant layer to the `balance_gen_carga.gpkg` GeoPackage.

---

### `13_clean_valores_2024.py`
Cleaning and normalization of `VALORES_2024.csv` — the hourly generation file of the
Argentine Wholesale Electricity Market (MEM) provided by CAMMESA.

Transformations applied:
- Read in chunks (500,000 rows) — the file exceeds 8 million rows and includes data through 2025
- Date format normalization to `DD/MM/YYYY`
- Filter: only rows from year 2024
- `datetime` column built as date + (HORA-1) hours (CAMMESA convention: HORA=1 → 00:00)
- `YACYHIPY` excluded (Paraguayan side of Yacyretá — outside the Argentine model)
- Factor 0.5 applied to SGDE (Salto Grande — binational plant Argentina/Uruguay)
- Outlier detection per unit (GRUPO): flag_outlier=True if energy_mwh < 0, available_capacity_mw < 0, or if either exceeds the 99.9th annual percentile for that unit
- Column names translated from CAMMESA Spanish originals to English

Output: `valores_2024_clean.csv` — external to GitHub due to size (~580 MB).

---

### `14_detect_generator_conflicts.py`
Detects mismatches between model unit names (PSS/E) and CAMMESA unit codes in
`valores_2024_clean.csv`.

A conflict exists when a unit has no direct match in CAMMESA (`bus_name_origen` is
not a valid CAMMESA unit code) AND the power plant it belongs to has more than one
unit code in CAMMESA — in that case it is not possible to automatically determine
which CAMMESA unit corresponds to that model unit.

Generates `conflicts_psse_cammesa.csv` for manual completion. If the file already
exists, previously completed resolutions are preserved and only new rows are added.

Columns to fill manually:
- `corrected_unit_name` — CAMMESA unit code corresponding to this model unit according to the single-line diagram. Leave empty if no match.
- `reviewed` — `yes` if the row was reviewed and has no possible match (goes to nemo4 matching)
- `exclude` — `yes` if the unit must be excluded from the model (does not enter via nemo4 either)
- `comment` — observations from the single-line diagram review

Once the CSV is completed, run script 14b.

---

### `14b_build_generators_2024.py`
Builds `generators_2024.csv` with `p_nom` calculated from real CAMMESA 2024 data.
Requires `conflicts_psse_cammesa.csv` to be completed (generated by script 14).

If there are pending conflicts (rows without `exclude`, `reviewed` or
`corrected_unit_name` filled), the script warns and exits without generating output.

**p_nom logic:**
- Direct match (`bus_name_origen` exists as a CAMMESA unit code): p_nom = 95th percentile of `available_capacity_mw` for that specific unit.
- Match by nemo4 (`bus_name_origen` not a CAMMESA unit, but nemo4 exists as a plant code): p_nom = 95th percentile of `available_capacity_mw` for the entire plant, distributed proportionally to `pt_mw` from PSS/E among the plant's units.
- In both cases p95 is used to avoid point outliers.

**Conflict resolution:**
- `exclude = yes` → unit excluded from the model
- `corrected_unit_name` filled → replaces `bus_name_origen` for CAMMESA matching
- `reviewed = yes` with no match → goes to nemo4 matching normally

**Binational plant:**
Salto Grande (SGDE): factor 0.5 applied before computing p_nom (Argentina/Uruguay share).

**Carrier validation:**
Units whose model carrier is incompatible with the CAMMESA type reported for that
plant or unit are automatically excluded. This prevents PSS/E-misclassified units
from receiving profiles of a different technology.

Configurable parameters:
- `P_NOM_PERCENTILE` — percentile used for p_nom (default: 95)
- `BINATIONAL_FACTOR` — dictionary nemo4 → factor for binational plants

---

### `15_build_loads_2024.py`
Builds the 2024 hourly demand table by 500 kV bus in long format.

Main input: `Dda_horaria_x_trafo_2024.csv` — hourly demand by transformer. Wide
format: one row per transformer, 8784 hourly value columns in MW. 4-row multi-level
header.

Bus coupler fusion: replicates the Union-Find logic from script 08 using
`lines_500kv_final.csv` to redirect demand from fused buses to the representative
bus that exists in the network. Guarantees that `bus_name` values in the output
match the bus index in `network_500kv.nc`.

Output: `loads_2024.csv` — long format with columns `bus_id`, `bus_name`,
`datetime`, `p_mw`. 72 buses × 8784 hours.

---

### `16_snapshot_dc_peak2024.py`
Linearized DC flow at the 2024 peak demand snapshot.
Snapshot: 01/02/2024 14:00 — 27,439 MW demand, 28,590 MW CAMMESA generation.

Demand from `loads_2024.csv` and generation from `valores_2024_clean.csv`, applying
the same matching as script 14b: direct match by `bus_name_origen` or proportional
distribution by p_nom via nemo4.

Slack bus: `ATUCHA 2_21kV` (bus 2620, nuclear plant, 21 kV).

Console report:
- Balance: dispatched generation, slack injection, total demand
- Generation mix by technology (thermal grouped: steam + ocgt + ccgt + diesel)
- 10 most loaded lines (flow / capacity %)
- Extreme nodal angles (network stress indicator)
- Top 3 sources not represented in the model (only if slack > 0)

No output file — validation script only.

---

### `17_build_gen_profiles_2024.py`
Builds hourly availability profiles (`p_max_pu`) for all generator units in the
model, for the 8784 hours of 2024.

**p_max_pu logic:**
- Solar, wind, biogas, biomass: `p_max_pu = energy_mwh / p_nom`
  `energy_mwh` is used because it reflects the meteorological resource available in each hour.
- Hydro, pumped_hydro, nuclear: `p_max_pu = operated_energy_mwh / p_nom`
  `operated_energy_mwh` is used as a realistic upper bound of what the system can take from these technologies, without forcing the optimizer to dispatch them exactly at that value.
- Remaining technologies (thermal, diesel): `p_max_pu = available_capacity_mw / p_nom`
  `available_capacity_mw` reflects real hourly availability, including planned outages and maintenance.
- In all cases the result is clipped between 0 and 1.
- Units without a match in CAMMESA (auto-producers, outside the MEM): excluded from the output.
  Script 19 removes from the network any generator without a profile in this file.

**Matching GRUPO → model unit:**
Same criterion as script 14b: direct match by `bus_name_origen`, or proportional
distribution by `p_nom` via nemo4 when the CAMMESA GRUPO represents the entire plant.
Distribution is vectorized with a pandas merge — no row-by-row iteration.

Processing in chunks (500,000 rows) to avoid exceeding RAM.

Output: `gen_profiles_2024.csv` — external to GitHub due to size (~5.3M rows).
Columns: `gen_key`, `bus_conexion500kv_name`, `carrier`, `datetime`, `p_max_pu`.

---

### `18_diagnose_marginal_costs.py`
Diagnoses marginal cost coverage for the units in `generators_2024.csv`.
Does not build the final file — it is an audit step prior to 18b.

Analysis groups:
- **Thermal and nuclear**: matched against `CVP_Termica.csv` by reduced key (first 4 characters + last 2 digits). Filter: year 2026, week 1. Fuel priority: GN > single fuel available > FO over GO. Fallback: average using first 6 characters.
- **Renewables**: matched by normalized `geosadi_name` against the `Proyecto` field of `CVP_renovar.csv`.
- **Hydro**: data pending, no automatic match attempted.

Output: `marginal_costs_diagnostic.csv` — coverage table with columns
`bus_name_origen`, `geosadi_name`, `nemo`, `carrier`, `p_nom`,
`marginal_cost_match`, `cost_source`, `CVP_manual`.
The `CVP_manual` column must be filled manually before running script 18b.

---

### `18b_build_marginal_costs_2024.py`
Builds `marginal_costs_2024.csv` with a fixed annual marginal cost per generator unit.
Requires `marginal_costs_diagnostic_completed.csv` to be completed (generated by 18).

**Cost source by technology:**
- Thermal/nuclear: single cost from `CVP_Termica.csv` (filter year 2026, week 1)
- Renewables: annual average of Jan-24 to Dec-24 columns from `CVP_renovar.csv`
- Hydro and pending: from the `CVP_manual` column of the completed diagnostic file

**CVP_manual logic:**
- If numeric: used directly as marginal cost
- If text: that name is looked up in the corresponding CVP file according to technology

Configurable parameters:
- `EXCLUDE_NO_COST` — False (default): assigns cost=0 to units with no data. True: excludes them from the output.

---

### `19_run_optimization.py`
Linear DC economic dispatch (OPF) over the 500 kV network for the configured period.
Uses `n.optimize()` from PyPSA with the HiGHS solver.

The script dynamically loads generators, profiles and demand onto `network_500kv.nc`
without modifying that base file. Results are saved to a separate `.nc` file.

**Modeling decisions:**
- DC OPF: no losses, no voltages, active power flows only
- No additional constraints: no minimum technical outputs or ramp rates
- Slack bus: `ATUCHA 2_21kV`
- Wind, solar, nuclear: marginal_cost forced to 0 (dispatched first by the solver)
- Hydro/pumped_hydro: p_max_pu from real 2024 operated output profiles (`gen_profiles_2024.csv`)
- Brazil Link: import only (`p_min_pu=0`), free for the solver
- Virtual load shedding at each bus (cost=10,000 USD/MWh) to guarantee feasibility
- Generators without a marginal cost in `marginal_costs_2024.csv`: cost=0 by default
- Generators without a profile in `gen_profiles_2024.csv`: excluded from the network

**Configurable parameters:**
- `START_DATE` / `END_DATE` — simulation period
- `CHUNK_DAYS` — None (single problem) or number of days per block (reduces RAM)
- `EXCLUDE_NO_COST` — False (cost=0) or True (exclude from model)

Output: `results_2024_YYYYMMDD_YYYYMMDD.nc` in `networks/` (not versioned in git).
The date suffix prevents overwriting results from different periods.

---

### `aliases_500kv.py`
Helper module used by `06_match_geosadi_geometry.py`.
Contains the alias dictionary to resolve abbreviations and name variants of
substations in GeoSADI line names.
Not run directly.
