# PyPSA-AR Data Sources

Este documento describe las fuentes de datos del proyecto y su estado actual.

---

## 1. Red de transporte — 500 kV

### Fuente principal: PSS/E ver2526pid.raw (CAMMESA)

Caso: *Pico Hábil Diurno del Verano 25/26 — Demanda SADI 30.960 MW*

Contiene:
- BUS DATA: buses con nivel de tensión, tipo (PQ/PV/slack), área
- BRANCH DATA: líneas y compensadores serie con r, x, b en pu (Sbase=100 MVA) y ratings MVA
- TRANSFORMER DATA: transformadores inter-nivel (2W y 3W)

Procesado por: `01_parse_raw_buses.py`, `02_parse_raw_lines.py`, `03_parse_raw_transformers.py`, `04_parse_raw_buses_sec.py`

### Fuente geográfica: GeoSADI (CAMMESA)

URL: https://www.arcgis.com/apps/instant/sidebar/index.html?appid=4b0ffba2055745a3afdbe1444d2db6d7

Layers utilizados:
- `estaciones_transformadoras.geojson` — coordenadas y nombre de estaciones por nivel de tensión
- `lineas_alta_tension.geojson` — geometría de líneas con nombre y tensión
- `centrales_electricas.csv` — centrales con nombre, nemo y coordenadas

Procesado por: `05_match_geosadi_coords.py`, `06_match_geosadi_geometry.py`, `11_add_geo_to_generators.py`

### Diccionarios de matching manual

`data/network_500kv/buses_PSSE_vs_geosadi.xlsx` — coordenadas curadas para los 95 buses 500 kV. Versionado en Git.

`data/network_500kv/manual_line_mappings.csv` — mapeo manual line_key → geosadi_line_id. Versionado en Git.

`data/network_500kv/generators_manualpypsa.csv` — asignaciones manuales de generadores pendientes. Versionado en Git.

`data/network_500kv/conflictos_psse_cammesa.csv` — resolución manual de discrepancias entre nombres PSS/E y GRUPOs CAMMESA. Versionado en Git.

### Estado

✅ 95 buses 500 kV + 249 buses secundarios en el network (344 totales tras fusión de acopladores)
✅ 103 líneas activas procesadas
✅ 300 transformadores procesados
✅ Topología validada (1 componente conexa, 0 buses aislados)
✅ Verificación visual en QGIS

---

## 2. Generación

### Fuente principal: CAMMESA — VALORES_2024.csv

Archivo de generación horaria del Mercado Eléctrico Mayorista para el año 2024.
Contiene ENERGIA (MWh), POT_DISP (MW), ENERG_OPERADA (MWh) y POT_DISP_GN (MW) por
GRUPO y hora, para todas las unidades del despacho.

Procesado por: `13_clean_valores_2024.py` → `valores_2024_clean.csv`

Transformaciones aplicadas:
- Filtro año 2024
- Normalización de formato datetime a DD/MM/YYYY HH:MM
- Exclusión de YACYHIPY (lado paraguayo de Yacyretá)
- Factor 0.5 a SGDE (Salto Grande — central binacional Argentina/Uruguay)
- Detección de outliers por GRUPO (flag_outlier)

Archivo resultante: `valores_2024_clean.csv` — externo a GitHub (~580 MB).

### Fuente complementaria: GeoSADI — centrales_electricas

Coordenadas y nemo de 436 centrales del SADI. Usado para asignar coordenadas
geográficas a las unidades generadoras del modelo.

### Estado

✅ 669 unidades generadoras en `generators_final.csv`
✅ 626 unidades en `generators_2024.csv` con p_nom real 2024 (p95 POT_DISP)
✅ 77 conflictos PSS/E vs CAMMESA detectados y resueltos manualmente
✅ p_nom total del sistema: ~40.084 MW
✅ Perfiles horarios p_max_pu 2024: `gen_profiles_2024.csv` (externo a GitHub, ~5.3M filas, ~577 unidades)
✅ Costos marginales: `costos_marginales_2024.csv` (~433 unidades con costo asignado, ~171 con costo=0 pendientes de completar)

---

## 3. Demanda

### Fuente: CAMMESA — Dda_horaria_x_trafo_2024.csv

Demanda horaria 2024 por transformador de distribución. Formato ancho: una fila por
transformador, 8784 columnas de valores horarios en MW. Incluye metadata de cada
transformador: bus 500 kV de conexión, región, provincia y participación en la
demanda provincial.

Procesado por: `15_build_loads_2024.py` → `loads_2024.csv`

Archivo resultante: `loads_2024.csv` — versionado en Git (72 buses × 8784 horas).

### Estado

✅ 72 buses con demanda asignada
✅ Pico de demanda del sistema: 27.439 MW (01/02/2024 14:00)
✅ Promedio anual: ~15.963 MW | Mínimo: ~9.365 MW (25/12/2024 07:00)

---

## 4. Validación DC — snapshot pico de demanda 2024

### Script: `16_snapshot_dc_pico2024.py`

Flujo DC linealizado sobre el snapshot de máximo pico de demanda del año 2024.

Resultados (01/02/2024 14:00):
- Generación despachada: 26.374 MW
- Inyección del slack (ATUCHA 2): 1.013 MW
- Demanda total: 27.439 MW
- Brecha explicada por importaciones de Brasil (~2.267 MW, no modeladas)
- Línea más cargada: C.COSTA-P.BAND.-1 al 133% de su rating PSS/E (rating identificado en 866 MVA, conservador para las condiciones reales de la línea)

### Estado

✅ Flujo DC converge
✅ Balance generación/demanda consistente con datos CAMMESA
✅ Congestión en corredor C.COSTA-P.BAND. coherente con la limitación de modelar solo red 500 kV sin los paralelos de niveles inferiores

---

## 5. Costos marginales

### Fuente: CAMMESA — CVP_Termica.csv + CVP_renovar.csv

Costos variables de producción por central, extraídos de los archivos posoperativos de CAMMESA.

Procesado por:
- `18_diagnostico_costos_marginales.py` → `18_costos_marginales_diagnostico.csv` (auditoría de cobertura)
- `18B_build_costos_marginales_2024.py` → `costos_marginales_2024.csv` (tabla final)

Lógica de asignación:
- Térmica/nuclear: match por clave reducida (nemo4 + número de unidad) contra CVP_Termica
- Renovables: match por nombre de central normalizado contra CVP_renovar (promedio anual Jan-24 a Dec-24)
- Hidro y pendientes: columna `CVP_manual` completada manualmente en el diagnóstico

Archivos CVP fuente: externos a GitHub.
Archivo resultante: `costos_marginales_2024.csv` — versionado en Git.

### Estado

✅ ~433 unidades con costo marginal asignado
⚠️ ~171 unidades con costo=0 (hidros pendientes de completar por equipo de trabajo)

---

## 6. Optimización y clustering

### Script 19: `19_run_optimization.py`

Despacho económico lineal DC (OPF) sobre la red 500 kV para el período configurado.
Usa `n.optimize()` con solver HiGHS. Parámetros configurables: período temporal,
chunking por días para manejo de memoria, tratamiento de generadores sin costo.

Archivo resultante: `results_2024_YYYYMMDD_YYYYMMDD.nc` en `networks/` — externo a GitHub.

### Script 21: `21_network_clustering.py`

Clustering espacial k-means nativo de PyPSA para simplificación de la red.
Genera redes clusterizadas funcionales para análisis de largo plazo.
Parámetro configurable: `CLUSTER_SIZES` (lista de niveles de agregación) y
criterio de pesos (`BUS_WEIGHTING`).

Archivos resultantes en `data/network_500kv/clusters/`:
- `clusters.gpkg` — visualización QGIS con layers por nivel de agregación
- `cluster_summary_k{N}.csv` — capacidad instalada por tecnología por cluster
- `cluster_k{N}.nc` — network clusterizado funcional para `n.optimize()`

### Estado

✅ Script 19 construido y listo para correr
✅ Script 21 corrido exitosamente para K=10, K=20, K=50
✅ Clusters visualizados en QGIS (`data/network_500kv/clusters/clusters.qgz`)
🔲 Script 20 (análisis de resultados de optimización): pendiente

---

## 7. Renovables (VRE) — para etapas futuras

### Viento y solar

- ERA5 (velocidades de viento, irradiancia)
- Atlas Solar Argentina
- Procesamiento con atlite para factores de capacidad horarios

En la versión actual, los perfiles de solar y eólica se construyen desde ENERGIA
real de CAMMESA 2024 (script 17). Los perfiles meteorológicos de ERA5/atlite se
incorporarán en etapas futuras para escenarios prospectivos.

Estado: 🔲 no iniciado.

---

## 8. Precios de combustibles y emisiones — para etapas futuras

### Fuentes

- ENARGAS (gas natural)
- CAMMESA (precios de referencia)
- IRENA / NREL ATB (referencias internacionales)
- Factores de emisión por tecnología (tCO2/MWh)

Estado: 🔲 a estructurar en fase de calibración.

---

## Principios de gestión de datos

- Toda fuente debe tener referencia y fecha de extracción.
- Archivos crudos pesados (.raw, .geojson, .nc, .csv >50 MB) se almacenan fuera de Git.
- Solo se versionan: scripts, CSVs procesados livianos, diccionarios de matching y documentación.
- Todas las transformaciones son reproducibles desde los archivos fuente.
