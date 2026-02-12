# PyPSA-AR Data Sources (Aligned with 10/02/2026 Meeting)

This document defines the datasets required for PyPSA-AR-BASE v0.1,
aligned with the agreed modeling scope:

500 kV backbone + selected 220/132 kV nodes.

---

## 1. Transmission Network

### Scope

- 500 kV national backbone (primary layer)
- Selected 220 kV and 132 kV nodes where:
  - Major generation assets connect
  - Structural bottlenecks are relevant
  - Data is sufficiently reliable

### Data Required

- Buses (coordinates, voltage level)
- Lines (bus0, bus1, voltage, length)
- Thermal limits (s_nom)
- Electrical parameters (r, x)
- Interconnections with neighboring countries

### Sources

- CAMMESA (technical reports, posoperativos)
- ATEERA transport reference guides
- Secretaría de Energía (where available)
- PyPSA-Earth South America run (baseline structure)

Status:
Public transport data collected.
Some provincial trunk data not publicly available.
Further validation required.

---

## 2. Generation Assets

### Data Required

- Installed capacity (MW)
- Technology type
- Location (bus assignment)
- Availability factors
- Marginal cost inputs
- Fuel type
- Emission factors

### Sources

- CAMMESA reports
- Secretaría de Energía
- Official plant documentation
- PyPSA-Earth baseline (for structural comparison)

Status:
Identification phase ongoing.

---

## 3. Demand Profiles

### Data Required

- Hourly national demand (2023–2024)
- Regional disaggregation (if available)
- Seasonal patterns
- Peak values

### Sources

- CAMMESA public demand reports
- Monthly demand summaries

Status:
Historical data collected.
Cleaning and structuring pending.

---

## 4. Renewable Resource Data (VRE)

### Wind

- ERA5 wind speeds (10m / 100m)
- Capacity factor estimation (atlite)

### Solar

- ERA5 irradiance
- Atlas Solar Argentina
- Capacity factor estimation

Status:
Not yet processed.

---

## 5. Hydro Data

### Data Required

- Installed hydro capacity
- Type (run-of-river / storage)
- Historical generation (if available)

Sources:

- CAMMESA
- Official hydro documentation

Status:
Preliminary identification.

---

## 6. Fuel Prices & Emissions

### Data Required

- Natural gas price assumptions
- Liquid fuel prices
- Nuclear cost assumptions
- Emission factors (tCO2/MWh)

Sources:

- ENARGAS
- CAMMESA
- IRENA
- NREL ATB
- International references

Status:
To be structured.

---

## 7. PyPSA-Earth Baseline (South America Run)

The project has access to CSV files generated from a PyPSA-Earth
South America run.

These files include:

- Buses
- Lines
- Generators
- Demand structure
- Transmission parameters

Purpose:

- Structural template
- Understanding required PyPSA input format
- Initial topology reference

Important:

The South America dataset is NOT considered validated Argentine data.

It will be:
- Filtered to Argentina
- Cross-validated with national sources
- Calibrated against CAMMESA dispatch

---

## Data Governance Principles

- All datasets must have source reference.
- Date of extraction must be recorded.
- Large datasets are stored outside Git.
- Only scripts, metadata, and documentation are version-controlled.
- All transformations must be reproducible.

---

This document will evolve as datasets are consolidated and validated.
