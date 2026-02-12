# PyPSA-AR Architecture (v0.1 – Defined Scope)

## Objective

Build a calibrated and reproducible base model of Argentina’s high-voltage electricity system using PyPSA.

The objective of v0.1 is not to model the entire distribution network,
but to create a realistic backbone representation suitable for dispatch replication and scenario analysis.

---

## Modeling Scope (Agreed Definition)

The model will represent:

- 500 kV national backbone transmission network
- Selected 220 kV and 132 kV nodes where:
  - Major generation assets are connected
  - Structural constraints are relevant
  - Data availability allows reliable representation

This hybrid approach balances:

- Technical realism
- Data availability constraints
- Computational tractability

---

## System Components Included in v0.1

1. Transmission Network
   - 500 kV backbone
   - Strategic 220/132 kV injections
   - Interconnections with neighboring countries

2. Generation Fleet
   - Thermal (CCGT, steam, turbogas, diesel)
   - Hydro (run-of-river and storage)
   - Nuclear
   - Wind
   - Solar

3. Demand
   - Hourly demand profiles (2023–2024)
   - Allocation by regional nodes

4. Renewable Resource Profiles
   - Wind (ERA5-based)
   - Solar (ERA5 / Atlas-based)

5. Fuel Prices and Emissions
   - Gas and liquid fuels
   - Emission factors per technology

---

## Architecture Layers

### 1. Data Layer
Validated datasets from:
- CAMMESA (demand, generation, posoperativos)
- ATEERA transport references
- PyPSA-Earth baseline (South America run)
- ERA5 / atlite

### 2. ETL Layer
Scripts to:
- Clean and validate raw data
- Standardize structure
- Convert to PyPSA-compatible format
- Perform quality control

### 3. PyPSA Model Layer
- Network topology definition
- Generator mapping
- Demand allocation
- DC power flow modeling
- Operational constraints

### 4. Calibration Layer (Core of v0.1)
- Full-year 8760h simulation (2024)
- Dispatch comparison vs CAMMESA
- Cost adjustments
- Transmission constraint validation
- Target error ≤ ±5%

---

## Design Principles

- Reproducibility
- Transparency of assumptions
- Modular data structure
- Lightweight Git repository
- Progressive refinement of Argentine-specific data

---

This document will evolve as the architecture becomes more concrete.

