# PyPSA-AR Roadmap (Aligned with 10/02/2026 Meeting)

This roadmap reflects the agreed modeling scope:
500 kV backbone + selected 220/132 kV nodes.

The objective is to reach a calibrated PyPSA-AR-BASE v0.1 model.

---

## Phase 0 – Repository & Structure (Completed)

- GitHub repository initialized
- Documentation structure created
- Data dictionary defined
- Scope clarified

---

## Phase 1 – Review Existing PyPSA Data (Immediate Task)

Objective:
Identify what Argentina-specific data already exists in the PyPSA-Earth South America run.

Tasks:
- Extract Argentina buses
- Review transmission lines (500 kV focus)
- Review generation assets
- Review topology consistency
- Assess parameter completeness (x, r, s_nom, etc.)

Deliverable:
Technical memo:
“What does PyPSA already know about Argentina?”

---

## Phase 2 – Data Consolidation

Objective:
Consolidate national datasets.

Tasks:
- Validate CAMMESA demand series
- Consolidate transport data (ATEERA)
- Map generation assets
- Identify missing transmission segments
- Detect data gaps

Deliverable:
Validated data inventory ready for ETL.

---

## Phase 3 – Base Model Construction

Objective:
Build first runnable PyPSA-AR network.

Tasks:
- Import 500 kV backbone
- Add selected 220/132 kV nodes
- Map generators to nodes
- Assign demand
- Integrate renewable profiles

Deliverable:
First operational PyPSA-AR model.

---

## Phase 4 – Calibration (2024 Base Year)

Objective:
Replicate historical dispatch.

Tasks:
- Run full 8760h simulation
- Compare generation by technology vs CAMMESA
- Adjust marginal costs
- Validate transmission limits
- Ensure no energy-not-served

Success Criteria:
- Dispatch error ≤ ±5%
- Stable solver convergence

Deliverable:
PyPSA-AR-BASE v0.1 calibrated model.

---

## Phase 5 – Scenario Preparation (v0.2)

Objective:
Prepare architecture for policy and expansion scenarios.

Tasks:
- Scenario configuration structure
- Emission constraints
- Renewable targets
- Fuel price sensitivities
- Expansion enablement

Deliverable:
Scenario-ready architecture.

---

This roadmap will be updated as modeling progresses.
