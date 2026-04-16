# PypsaEarth[AR] - Macro Audit

GeoSADI (Real Network) vs PyPSA-Earth (OSM) — February 2026

---

## 1. High-Voltage Lines

Comparison of circuit count and total kilometers by voltage level.
Edenor and Edesur layers are excluded (urban AMBA distribution network, ~7,000 additional lines)
as they are not comparable with the national transmission model.

| Voltage (kV) | GeoSADI # Lines | GeoSADI km | PyPSA # Lines | PyPSA km | Coverage # | Coverage km |
|---|---|---|---|---|---|---|
| 33 | 15 | 88 | 0 | 0 | 0% | 0% |
| 66 | 127 | 1,989 | 33 | 866 | 26% | 44% |
| 132 | 1,025 | 32,325 | 913 | 41,171 | 89% | 127% |
| 150 | 2 | 51 | 0 | 0 | 0% | 0% |
| 220 | 39 | 2,117 | 43 | 3,125 | 110% | 148% |
| 330 | 6 | 1,116 | 2 | 1,506 | 33% | 135% |
| 345 | 6 | 269 | 1 | 21 | 17% | 8% |
| 500 | 112 | 15,174 | 99 | 18,327 | 88% | 121% |
| **TOTAL** | **1,332** | **53,129** | **1,091** | **65,016** | **82%** | **122%** |

Reference: ≥ 80% good coverage · 50–79% partial coverage · < 50% insufficient coverage

### Observations

- In terms of circuit count, PyPSA-Earth has 82% of the GeoSADI total, which appears reasonable. However in kilometers this rises to 122% — PyPSA overestimates distances at 500 kV and 132 kV, possibly due to OSM fragmentation or different routing.
- Voltage levels 33 kV and 150 kV are not represented in PyPSA-Earth.
- The 330 kV level has only 2 circuits in PyPSA vs 6 in reality.
- The 500 kV level shows the best relative coverage (88% of circuits).

---

## 2. Transformers

Transformers in GeoSADI represent transformation positions at each substation (one row per transformer, with the high-side voltage level). PyPSA-Earth models transformers as connections between buses of different voltage levels.

| High-side Voltage (kV) | GeoSADI # Transformers | PyPSA # Transformers | Coverage | Gap |
|---|---|---|---|---|
| 132 | 895 | 31 | 3% | 864 missing |
| 220 | 41 | 35 | 85% | 6 missing |
| 330 | 3 | 2 | 67% | 1 missing |
| 345 | 5 | 2 | 40% | 3 missing |
| 500 | 70 | 55 | 79% | 15 missing |
| **TOTAL** | **1,014** | **125** | **12%** | **889 missing** |

### Observations

- The gap is critical: PyPSA-Earth has only 125 transformers vs 1,132 records in GeoSADI (11% coverage). This is the most significant finding of the analysis.
- At 132 kV, PyPSA has 31 vs 895 in reality — 3% coverage.
- This difference is explained by PyPSA-Earth collapsing complex substations to 1–2 buses, eliminating all internal topology.
- 500 kV is the best-represented level with 55 out of 70 (79%).

---

## 3. Generation

> Note: the PyPSA-Earth run used here intentionally excluded renewable generation (hydro, wind, solar)
> to simplify the topological analysis.
> GeoSADI data comes from the power plants layer (436 plants, 48,099 MW installed).

| Technology | GeoSADI Units | GeoSADI MW | PyPSA Units | PyPSA MW | MW Coverage | Status |
|---|---|---|---|---|---|---|
| Hydro (HI/HB/HR) | 72 | 12,153 | — | — | — | Missing |
| CCGT / Gas Steam (VG) | 24 | 10,281 | 65 | 16,838 | 164% | Aggregated |
| Gas Turbine (TG) | 68 | 9,260 | — | — | — | Aggregated |
| Coal/Oil Steam (TV) | 26 | 6,170 | 1 | 240 | 4% | Partial |
| Wind (EO) | 71 | 4,390 | — | — | — | Missing |
| Solar PV (FV) | 69 | 2,404 | — | — | — | Missing |
| Nuclear (NU) | 3 | 1,755 | 4 | 1,792 | 102% | OK |
| Diesel/Oil (DI) | 102 | 1,685 | 10 | 2,861 | 170% | Aggregated |
| **TOTAL** | **435** | **48,098** | **80** | **21,731** | **45%** | |

### Observations

- PyPSA covers only 45% of real installed capacity. The gap is mainly explained by the absence of hydro (12,153 MW), wind (4,390 MW), and solar (2,404 MW).
- Gas-fired thermal (VG + TG) is partially represented: PyPSA aggregates both into CCGT with 16,838 MW vs 19,541 MW in reality — a 14% difference.
- Nuclear: 3 real plants (1,755 MW) vs 4 in PyPSA (1,792 MW). Minor difference, possibly due to inclusion of CAREM or a different nominal capacity.
- Steam (TV): PyPSA has 240 MW (1 plant) vs 6,170 MW in reality — 4% coverage, severely underrepresented.
- Diesel/Oil: PyPSA has 2,861 MW vs 1,685 MW in reality — 70% overestimate, possibly due to decommissioned units still present in OSM.

---

## 4. Executive Summary

| Element | GeoSADI | PyPSA-Earth (OSM) | Coverage |
|---|---|---|---|
| HV lines (circuits) | 1,332 | 1,091 | 82% |
| HV lines (km) | 53,129 km | 65,018 km | +22% overestimate |
| Transformers | 1,132 | 125 | 11% |
| Generation (MW) | 48,099 MW (436 plants) | 21,732 MW (80 units) | 45% (excl. renewables and hydro) |

### Conclusion

The line topology of PyPSA-Earth (OSM) is reasonably complete for voltage levels ≥ 220 kV. However the transformer model is critically insufficient (11% coverage). This validates the decision to replace the data source with GeoSADI as the input to the PyPSA-AR pipeline.

### Next steps (at the time of writing — February 2026)

1. Clean and process GeoSADI layers into PyPSA-compatible format (buses, lines, transformers)
2. Infer transformer topology from substations with multiple voltage levels
3. Resolve the geospatial snapping problem
4. Incorporate hydro, wind, and solar generation from official CAMMESA/MINEM sources
