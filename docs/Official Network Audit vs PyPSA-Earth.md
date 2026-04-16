# Official Network Audit vs PyPSA-Earth

Document recording the comparison process between the official Argentine network and the PyPSA-Earth model,
and the decision to migrate to GeoSADI + PSS/E as the source of truth.

---

## Objective

Build a reproducible process to:
- Audit the official Argentine network
- Map lines to a curated master list of electrical substations
- Separate international interconnections
- Structurally compare against PyPSA-Earth (OSM)

---

## Stage 1 — Audit with Secretaría de Energía data (deprecated)

> **Note:** This stage worked with data from the Secretaría de Energía.
> It was replaced by GeoSADI from 26/02/2026 onward.
> The scripts in `scripts/qa_network/` are deprecated.

### Data used

**Official HV lines shapefile:** `transporte-electrico-at-lineas-shp.shp`
- Total records: 1,299 (1,247 LineString + 50 MultiLineString)

**Substation master list:** `official_stations_master.csv`
- 310 curated substations
- Fields: `station_uid`, `station_name`, `source_id`, `lon`, `lat`, `tension_levels`, `status`

### Matching diagnosis by voltage level

| Voltage | Median distance endpoint → substation | Quality |
|---------|---------------------------------------|---------|
| 500 kV | ~0.2 km | ✅ Very good |
| 330 kV | ~0.1 km | ✅ Very good |
| 132 kV | ~7 km | ⚠️ Needs refinement |
| 220 kV | ~15–20 km | ❌ Problematic |
| 66/33 kV | very high | ❌ Not represented |

### Problem identified

The official shapefile fragments corridors into multiple segments.
Example: Güemes – Formosa – Clorinda split into 3 segments.
If an intermediate substation is missing (e.g. ESPINILLO), the intermediate segments produce large errors.
This is not an algorithm error — it is segmentation combined with incomplete master list coverage.

---

## Stage 2 — Migration to GeoSADI (26/02/2026)

Full access to GeoSADI (CAMMESA) was obtained:
https://www.arcgis.com/apps/instant/sidebar/index.html?appid=4b0ffba2055745a3afdbe1444d2db6d7

Layers available in `.csv` and `.geojson`:
- `lineas_alta_tension`
- `estaciones_transformadoras`
- `centrales_electricas`

A PyPSA-Earth AR `.gpkg` was loaded alongside GeoSADI in QGIS for visual comparison.

---

## Macro comparison GeoSADI vs PyPSA-Earth (28/02/2026)

### Lines

| | GeoSADI | PyPSA-Earth | Difference |
|---|---|---|---|
| Number of lines | 1,332 | 1,091 | PyPSA has 82% |
| Total kilometers | 53,129 km | 65,018 km | PyPSA overestimates +22% |

- 33 kV and 150 kV not represented in PyPSA
- 500 kV is the best-represented voltage level (88% of circuits)

### Transformers — critical finding

| | GeoSADI | PyPSA-Earth | Coverage |
|---|---|---|---|
| Total | 1,132 | 125 | **11%** |
| 132 kV | 895 | 31 | **3%** |

> This finding definitively validates the decision to replace OSM with GeoSADI.

### Generation

| | GeoSADI | PyPSA-Earth | Coverage |
|---|---|---|---|
| Power plants | 436 | 80 | 18% |
| Installed MW | 48,099 MW | 21,732 MW | 45% |

- Nuclear: well represented (3 real vs 4 in PyPSA ≈ OK)
- Hydro: 12,153 MW absent in PyPSA
- Wind: 4,390 MW absent in PyPSA
- Solar: 2,404 MW absent in PyPSA

> Note: hydro/wind/solar were also absent by deliberate choice — the `elec.nc` step with renewables was not run.

---

## Strategic decision — Start with the 500 kV network

The decision is made to build the complete 500 kV network first before incorporating lower voltage levels.

Reasons:
- Only ~112 lines and ~70 substations — manageable scale
- Clean line names, few problematic abbreviations
- It is the backbone of the SADI
- Geospatial snapping issues are less severe than at 132 kV

From here on: PSS/E as source (topology + impedances) + GeoSADI (coordinates + geometry).
