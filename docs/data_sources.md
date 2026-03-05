# PyPSA-AR Data Sources

Este documento describe las fuentes de datos del proyecto y su estado actual.

---

## 1. Red de transporte — 500 kV

### Fuente principal: PSS/E ver2526pid.raw (CAMMESA)

Caso: *Pico Hábil Diurno del Verano 25/26 — Demanda SADI 30.960 MW*

Contiene:
- BUS DATA: buses con nivel de tensión, tipo (PQ/PV/slack), área
- BRANCH DATA: líneas y compensadores serie con r, x, b en pu (Sbase=100 MVA) y ratings MVA
- TRANSFORMER DATA: transformadores inter-nivel

Procesado por: `01_parse_raw_buses.py`, `02_parse_raw_lines.py`


### Fuente geográfica: GeoSADI (CAMMESA)

URL: https://www.arcgis.com/apps/instant/sidebar/index.html?appid=4b0ffba2055745a3afdbe1444d2db6d7

Layers utilizados:
- `estaciones_transformadoras.geojson` — coordenadas y nombre de estaciones por nivel de tensión
- `lineas_alta_tension.geojson` — geometría de líneas con nombre y tensión

Procesado por: `03_match_geosadi_coords.py`, `04_match_geosadi_geometry.py`


### Diccionario de matching manual

`data/network_500kv/buses_PSSE_vs_geosadi.xlsx` — mapeo manual bus PSS/E → nombre GeoSADI.
Versionado en Git.

`data/network_500kv/manual_line_mappings.csv` — mapeo manual line_key → geosadi_line_id.
Versionado en Git.

### Estado

✅ 96 buses procesados (94 OK, 2 CONSULTAR)
✅ 122 líneas procesadas (sin_match = 0)
✅ Topología validada
✅ Check visual en QGIS 

---

## 2. Generación

### Fuente: GeoSADI — centrales_electricas

436 centrales / 48.099 MW instalados.

Incluye: térmica, hidro, nuclear, eólica, solar.

Estado: 🔲 pendiente .

### Fuente complementaria: CAMMESA posoperativos

Para calibración: despacho horario real 2024 por tecnología.

Estado: 🔲 pendiente.

---

## 3. Demanda

### Fuente: CAMMESA

Perfiles horarios de demanda 2024.
Desagregación regional por nodo.

Estado: 🔲 pendiente —
---

## 4. Renovables (VRE)

### Viento y solar

- ERA5 (velocidades de viento, irradiancia)
- Atlas Solar Argentina
- Procesamiento con atlite para factores de capacidad horarios

Estado: 🔲 no iniciado.

---

## 5. Precios de combustibles y emisiones

### Fuentes

- ENARGAS (gas natural)
- CAMMESA (precios de referencia)
- IRENA / NREL ATB (referencias internacionales)
- Factores de emisión por tecnología (tCO2/MWh)

Estado: 🔲 a estructurar en fase de calibración.

---

## Principios de gestión de datos

- Toda fuente debe tener referencia y fecha de extracción.
- Archivos crudos pesados (.raw, .geojson, .nc) se almacenan en googledrive, fuera de Git.
- Solo se versionan: scripts, CSVs procesados, diccionarios de matching y documentación.
- Todas las transformaciones son reproducibles desde los archivos fuente.
