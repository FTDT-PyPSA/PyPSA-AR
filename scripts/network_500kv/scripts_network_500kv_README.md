# scripts/network_500kv

Pipeline de construcción de la red 500 kV para PyPSA.
Correr en orden desde WSL con el entorno `pypsa-earth-lock`.

---

## Índice de scripts

| Script | Descripción breve | Input | Output |
|--------|-------------------|-------|--------|
| `01_parse_raw_buses.py` | Extrae buses 500 kV del PSS/E | `ver2526pid.raw` | `buses_500kv_raw.csv` |
| `02_parse_raw_lines.py` | Extrae líneas y compensadores del PSS/E | `ver2526pid.raw` + `buses_500kv_raw.csv` | `lines_500kv_raw.csv` |
| `03_parse_raw_transformers.py` | Extrae transformadores con lado en 500 kV | `ver2526pid.raw` + `buses_500kv_raw.csv` | `trafos_500kv_raw.csv` |
| `04_parse_raw_buses_sec.py` | Extrae buses secundarios de los transformadores | `ver2526pid.raw` + `trafos_500kv_raw.csv` | `buses_sec_raw.csv` |
| `05_match_geosadi_coords.py` | Asigna coordenadas y consolida todos los buses | `buses_500kv_raw.csv` + `buses_sec_raw.csv` + `buses_PSSE_vs_geosadi.xlsx` | `buses_final.csv` |
| `06_match_geosadi_geometry.py` | Asigna geometría WKT a las líneas | `lines_500kv_raw.csv` + `buses_final.csv` + GeoSADI | `lines_500kv_final.csv` |
| `07_validate_topology.py` | Valida topología de la red | `buses_final.csv` + `lines_500kv_final.csv` + `trafos_500kv_raw.csv` | `topology_report.csv` |
| `07b_export_qgis.py` | Exporta la red a GeoPackage para QGIS | `buses_final.csv` + `lines_500kv_final.csv` + `trafos_500kv_raw.csv` | `red_500kv_qgis.gpkg` |
| `08_build_pypsa_network.py` | Construye el objeto PyPSA Network | `buses_final.csv` + `lines_500kv_final.csv` + `trafos_500kv_raw.csv` | `network_500kv.nc` |
| `09_map_generators.py` | Mapea generadores PSS/E → nodos del modelo vía BFS | `ver2526pid.raw` + `buses_final.csv` | `generators_mapped.csv` |
| `10_map_loads.py` | Mapea cargas PSS/E → nodos del modelo vía BFS | `ver2526pid.raw` + `buses_final.csv` | `loads_mapped.csv` |
| `10b_visualize_qgis.py` | Exporta balance generación/carga por nodo a GeoPackage | `generators_mapped.csv` + `loads_mapped.csv` + `buses_final.csv` | `balance_gen_carga.gpkg` |
| `11_add_geo_to_generators.py` | Asigna coordenadas GeoSADI a los generadores | `generators_mapped.csv` + `buses_final.csv` + GeoSADI | `generators_readypypsa.csv` + `generators_pendingmanualpypsa.csv` |
| `12_build_generators_final.py` | Join automático + manual → tabla definitiva para PyPSA | `generators_readypypsa.csv` + `generators_manualpypsa.csv` | `generators_final.csv` |
| `12b_export_qgis_generators.py` | Agrega layer de centrales al GeoPackage de balance | `generators_final.csv` + `balance_gen_carga.gpkg` | Layer `centrales_electricas` en `balance_gen_carga.gpkg` |
| `12c_test_snapshot.py` | Carga snapshot PSS/E al network PyPSA y corre power flow de validación | `network_500kv.nc` + `generators_final.csv` + `loads_mapped.csv` | (consola — sin archivo de salida) |
| `13_clean_valores_2024.py` | Limpieza y normalización de VALORES_2024.csv | `VALORES_2024.csv` (externo) | `valores_2024_clean.csv` (externo) |
| `14_detectar_conflictos_generadores.py` | Detecta discrepancias entre nombres de unidades PSS/E y GRUPOs CAMMESA | `generators_final.csv` + `valores_2024_clean.csv` (externo) | `conflictos_psse_cammesa.csv` |
| `14b_build_generators_2024.py` | Construye tabla de generadores con potencia real 2024 desde CAMMESA | `generators_final.csv` + `conflictos_psse_cammesa.csv` + `valores_2024_clean.csv` (externo) | `generators_2024.csv` |
| `15_build_loads_2024.py` | Construye demanda horaria 2024 por bus 500 kV en formato largo | `Dda_horaria_x_trafo_2024.csv` (externo) + `buses_final.csv` + `lines_500kv_final.csv` | `loads_2024.csv` |
| `16_snapshot_dc_pico2024.py` | Flujo DC linealizado en el snapshot de máximo pico de demanda 2024 | `network_500kv.nc` + `generators_2024.csv` + `loads_2024.csv` + `valores_2024_clean.csv` (externo) | (consola — sin archivo de salida) |
| `17_build_gen_profiles_2024.py` | Construye perfiles horarios de disponibilidad (p_max_pu) para todas las unidades generadoras | `generators_2024.csv` + `valores_2024_clean.csv` (externo) | `gen_profiles_2024.csv` (externo) |
| `18_diagnostico_costos_marginales.py` | Diagnóstico de cobertura de costos marginales por unidad generadora | `generators_2024.csv` + `CVP_Termica.csv` (externo) + `CVP_renovar.csv` (externo) | `18_costos_marginales_diagnostico.csv` |
| `18B_build_costos_marginales_2024.py` | Construye tabla de costos marginales fijos anuales por unidad generadora | `generators_2024.csv` + `costos_marginales_diagnostico_completado.csv` + `CVP_Termica.csv` (externo) + `CVP_renovar.csv` (externo) | `costos_marginales_2024.csv` |
| `19_run_optimization.py` | Despacho económico DC lineal (OPF) sobre la red 500 kV | `network_500kv.nc` + `generators_2024.csv` + `loads_2024.csv` + `costos_marginales_2024.csv` + `gen_profiles_2024.csv` (externo) | `results_2024_YYYYMMDD_YYYYMMDD.nc` |
| `20_analyze_results.py` | *(pendiente)* Análisis de resultados de la optimización vs datos reales CAMMESA | `results_2024_*.nc` | Por definir |
| `21_network_clustering.py` | Clustering espacial k-means de la red para análisis de largo plazo | `network_500kv.nc` + `generators_2024.csv` + `loads_2024.csv` + `costos_marginales_2024.csv` + `gen_profiles_2024.csv` (externo) | `clusters.gpkg` + `cluster_summary_k{N}.csv` + `cluster_k{N}.nc` |
| `aliases_500kv.py` | Diccionario de aliases para matching GeoSADI | — | (módulo auxiliar) |

---

## Detalle

### `01_parse_raw_buses.py`
Lee la sección `BUS DATA` del archivo PSS/E `.raw` y extrae todos los buses en el rango
490–530 kV. Excluye buses IDE=4 (aislados) e internacionales (por área CAMMESA).

Parámetros configurables:
- `KV_MIN` / `KV_MAX` — rango de tensión
- `EXCLUDE_INTERNATIONAL` — incluir o excluir buses de países vecinos
- `EXCLUDE_BUSES` — set de bus_name a excluir manualmente

---

### `02_parse_raw_lines.py`
Lee la sección `BRANCH DATA` del PSS/E y extrae todas las ramas cuyos dos extremos
sean buses 500 kV. Clasifica cada rama como `line` o `series_compensator` (x < 0).

Parámetros configurables:
- `FORCE_ALL_IN_SERVICE` — forzar todas las ramas como en servicio independientemente del ST del raw

---

### `03_parse_raw_transformers.py`
Lee la sección `TRANSFORMER DATA` del PSS/E y extrae transformadores con al menos
un devanado en 500 kV. Los transformadores de 3 devanados se descomponen en 2
transformadores de 2 devanados usando el devanado de 500 kV como referencia común,
evitando la necesidad de nodos estrella ficticios en PyPSA.

Parámetros configurables:
- `FORCE_ALL_IN_SERVICE` — forzar todos los transformadores como en servicio

---

### `04_parse_raw_buses_sec.py`
Extrae los buses secundarios (bus_j) de `trafos_500kv_raw.csv` y les asigna un nombre
descriptivo con el formato `PARENT_kVkV` o `PARENT_kVkV_N` cuando hay múltiples
buses del mismo nivel de tensión para el mismo bus 500 kV padre.
Incluye todos los niveles de tensión: barras de red (33–345 kV) y terminales de
generador (11–22 kV).

---

### `05_match_geosadi_coords.py`
Asigna coordenadas geográficas a todos los buses y consolida en `buses_final.csv`:
- Buses 500 kV: coordenadas desde el diccionario manual `buses_PSSE_vs_geosadi.xlsx`
- Buses secundarios: heredan coordenadas del bus 500 kV padre (misma estación física)

---

### `06_match_geosadi_geometry.py`
Para cada línea PSS/E busca la geometría correspondiente en el GeoJSON de GeoSADI.
El matching sigue este orden de prioridad:
1. Diccionario manual `manual_line_mappings.csv`
2. Matching por tokens de nombre (vía `aliases_500kv.py`)
3. Desambiguación por número de circuito para paralelas

Resultados posibles en `match_status`:
- `directo` — match único encontrado
- `paralela` — desambiguado por número de circuito
- `manual_geo` — asignado desde diccionario manual
- `compensador` — compensador serie, sin geometría de línea en GeoSADI
- `pendiente_bus` — algún bus extremo sin coordenadas asignadas

---

### `07_validate_topology.py`
Valida la red completa (buses 500 kV + secundarios + trafos) antes de cargarla en PyPSA.
Detecta:
1. Líneas huérfanas (bus extremo ausente en buses_final.csv)
2. Trafos huérfanos (bus extremo ausente en buses_final.csv)
3. Buses 500 kV sin líneas — clasifica como barra central de compensador, nodo solo con trafos, o bus aislado real
4. Componentes conexas de la red 500 kV (islas desconectadas)
5. Líneas con r=0 y x=0 simultáneamente
6. Líneas sin rating definido
7. Ramas fuera de servicio (informativo)

---

### `07b_export_qgis.py`
Exporta toda la red a un GeoPackage con cuatro layers:
- `buses_500kv` — puntos con coordenadas GeoSADI
- `buses_sec` — puntos de buses secundarios (coordenadas heredadas del padre)
- `lines_500kv` — líneas con geometría GeoSADI
- `trafos_500kv` — transformadores como puntos en coordenadas del bus 500 kV padre

El `.gpkg` se guarda en `data/GIS_psse_geosadi_pypsaearth/red_500kv_qgis.gpkg`.

---

### `08_build_pypsa_network.py`
Construye el objeto `pypsa.Network` con la red 500 kV y lo exporta a `.nc`.

Decisiones de modelado:
- Impedancias del PSS/E en pu (Sbase=100 MVA confirmado en encabezado del raw)
- Conversión a unidades físicas usando Zbase dinámico por línea: Z_base = baskv² / S_base
- Compensadores serie modelados como `Line` con x negativo
- Transformadores de 3 devanados ya descompuestos en 2W desde el script 03
- Fusión de acopladores de barra (series_compensator con r=0 exacto): se detectan
  automáticamente y se fusionan sus buses al representante del grupo (menor bus_id)
  antes de agregar líneas y trafos. Los CSVs originales no se modifican.
- Perfil PSS/E (v_mag_pu, v_ang_deg) guardado como atributos en n.buses para warm start
- Interconexión Argentina-Brasil incluida: bus ficticio BRASIL, línea RINCON-GARABI-1
  (datos reales PSS/E), Link `importacion_brasil` (p_nom=2200 MW, marginal_cost=110 USD/MWh)
- Output en `networks/network_500kv.nc` (no versionado en git)

---

### `09_map_generators.py`
Parsea las secciones `GENERATOR DATA`, `OWNER DATA` y `AREA DATA` del PSS/E y mapea
cada unidad generadora al nodo del modelo (`buses_final.csv`) más cercano
topológicamente, usando BFS sobre `BRANCH DATA` + `TRANSFORMER DATA`.

**Resolución del carrier:**
Se extrae del campo Owner 1 (O1) de cada generador, cruzado contra `OWNER DATA`.
Los owner IDs conocidos se mapean a carriers PyPSA estándar (ocgt, steam, hydro,
diesel, ccgt, nuclear, wind, solar, biogas, biomass, battery).
Si el carrier resuelto no corresponde a generación, se intenta inferir desde las
posiciones [4:6] del bus_name:
- TG → ocgt, TV → steam, HI → hydro, DI → diesel, CC → ccgt
- FV → solar, EO → wind, BG → biogas, BM → biomass, HB → pumped_hydro
- Posiciones [4:8] = NUCL → nuclear

---

### `10_map_loads.py`
Misma lógica BFS que `09_map_generators.py` aplicada a las cargas del PSS/E.
Excluye cargas de áreas internacionales (Paraguay, Chile SING, Brasil, Bolivia, Uruguay).

---

### `10b_visualize_qgis.py`
Exporta el balance generación/carga por nodo del modelo a un GeoPackage para QGIS.

---

### `11_add_geo_to_generators.py`
Asigna coordenadas GeoSADI y nombre de central a cada generador de `generators_mapped.csv`.

Matching geográfico: compara los primeros 4 caracteres del `bus_name_origen` contra el
campo `Nemo` de `centrales_electricas.csv`. Resuelve ambigüedades por tipo tecnológico
usando el índice carrier → tipo GeoSADI. Los casos irreducibles se resuelven vía el
diccionario `NEMO_PREFERIDO` hardcodeado en el script.

---

### `12_build_generators_final.py`
Une `generators_readypypsa.csv` con las filas de `generators_manualpypsa.csv` que tienen
`nombre_geosadi` y `bus_conexion500kv` completos.

El campo `nemo` se resuelve haciendo join `nombre_geosadi` → `Nombre` en
`centrales_electricas.csv` de GeoSADI.

Reasignación CAPE/ACAJ: las unidades TG01, TG06 y TV07 de Agua del Cajón se
reasignan a `nemo = CAPE` (CAPEX Autoprod.) directamente en este script.

---

### `12b_export_qgis_generators.py`
Agrega un layer de centrales eléctricas al GeoPackage `balance_gen_carga.gpkg`.

---

### `12c_test_snapshot.py`
Carga los generadores y cargas del snapshot PSS/E al objeto PyPSA Network y corre
un power flow Newton-Raphson para validar la topología y el balance de la red.

Slack bus: `ATUCHA 2_21kV` (bus 2620, central nuclear, 21 kV).

No produce archivo de salida — es un script de validación.

---

### `13_clean_valores_2024.py`
Limpieza y normalización de `VALORES_2024.csv` — archivo horario de generación
del Mercado Eléctrico Mayorista provisto por CAMMESA.

Transformaciones aplicadas:
- Lectura en chunks (500.000 filas) — el archivo supera los 8 millones de filas e incluye datos hasta 2025
- Normalización de formatos de fecha a `DD/MM/YYYY`
- Filtro: solo filas del año 2024
- Columna `datetime` construida como fecha + (HORA-1) horas (convencion CAMMESA: HORA=1 → 00:00)
- Exclusión de `YACYHIPY` (lado paraguayo de Yacyretá — fuera del modelo argentino)
- Factor 0.5 aplicado a SGDE (Salto Grande — central binacional Argentina/Uruguay)
- Detección de outliers por GRUPO: flag_outlier=True si ENERGIA<0, POT_DISP<0, o
  si supera el percentil 99.9 anual del GRUPO

Output: `valores_2024_clean.csv` — externo a GitHub por tamaño (~580 MB).

---

### `14_detectar_conflictos_generadores.py`
Detecta discrepancias entre los nombres de unidades del modelo (PSS/E) y los GRUPOs
de CAMMESA en `valores_2024_clean.csv`.

Un conflicto existe cuando una unidad no tiene match directo en CAMMESA
(`bus_name_origen` no es un GRUPO válido) Y la central a la que pertenece tiene más
de un GRUPO en CAMMESA — en ese caso no es posible determinar automáticamente qué
GRUPO corresponde a esa unidad.

Genera `conflictos_psse_cammesa.csv` para completar manualmente. Si el archivo ya
existe, preserva las resoluciones completadas y solo actualiza las filas nuevas.

Columnas a completar manualmente:
- `bus_name_origen_correcto` — GRUPO de CAMMESA que corresponde a esta unidad según el unifilar
- `revisado` — `si` si la fila fue revisada y no tiene match posible (va al nemo4)
- `excluir` — `si` si la unidad debe excluirse del modelo (no entra ni por nemo4)
- `comentario` — observaciones del unifilar

Una vez completado el CSV, correr el script 14b.

---

### `14b_build_generators_2024.py`
Construye `generators_2024.csv` con `p_nom` calculado desde datos reales de CAMMESA 2024.
Requiere que `conflictos_psse_cammesa.csv` esté completado (generado por script 14).

Si hay conflictos pendientes (sin `excluir`, `revisado` ni `bus_name_origen_correcto`),
el script avisa y termina sin generar el output.

**Lógica de p_nom:**
Para cada central (nemo4), `p_nom` = percentil 95 de `POT_DISP` anual en
`valores_2024_clean.csv`. El valor se distribuye proporcionalmente al `pt_mw` del
PSS/E entre las unidades de la central.

**Resolución de conflictos:**
- `excluir = si` → unidad excluida del modelo
- `bus_name_origen_correcto` completado → reemplaza `bus_name_origen` para el match con CAMMESA
- `revisado = si` sin match → va al nemo4 normalmente

**Central binacional:**
Salto Grande (SGDE): `p_nom` × 0.5 antes de distribuir (Argentina/Uruguay).

Parámetros configurables:
- `P_NOM_PERCENTILE` — percentil usado para p_nom (default: 95)
- `BINACIONAL_FACTOR` — diccionario nemo4 → factor para centrales binacionales

---

### `15_build_loads_2024.py`
Construye la tabla de demanda horaria 2024 por bus 500 kV en formato largo.

Input principal: `Dda_horaria_x_trafo_2024.csv` — archivo de demanda horaria por
transformador confeccionado por equipo de trabajo. Formato ancho: una fila por trafo, 8784 columnas
de valores horarios en MW. Encabezado multi-nivel de 4 filas.

Fusión de acopladores de barra: replica la lógica Union-Find del script 08 usando
`lines_500kv_final.csv` para redirigir la demanda de buses fusionados al bus
representante que existe en el network. Garantiza que los `bus_name` del output
coincidan con el índice de buses de `network_500kv.nc`.

Output: `loads_2024.csv` — formato largo con columnas `bus_id`, `bus_name`,
`datetime` (DD/MM/YYYY HH:MM), `p_mw`. 72 buses × 8784 horas.

---

### `16_snapshot_dc_pico2024.py`
Flujo DC linealizado sobre el snapshot de máximo pico de demanda 2024.
Snapshot: 01/02/2024 14:00 — 27.439 MW de demanda, 28.590 MW de generación CAMMESA.

Genera demanda desde `loads_2024.csv` y generación desde `valores_2024_clean.csv`,
aplicando el mismo matching que el script 14b: match directo por `bus_name_origen` o
distribución proporcional a `p_nom` por nemo4.

Slack bus: `ATUCHA 2_21kV` (bus 2620, central nuclear, 21 kV).

Reporte en consola:
- Balance: generación despachada, inyección del slack, demanda total
- Mix de generación por tecnología (térmica agrupada: steam + ocgt + ccgt + diesel)
- 10 líneas más cargadas (flujo / capacidad %)
- Ángulos nodales extremos (indicador de estrés de red)
- Top 3 fuentes no representadas en el modelo (solo si slack > 0)

No produce archivo de salida — es un script de validación.

---

### `17_build_gen_profiles_2024.py`
Construye los perfiles horarios de disponibilidad (`p_max_pu`) para todas las unidades
generadoras del modelo, para las 8784 horas de 2024.

**Lógica de p_max_pu:**
- Solar, eólica, biogas, biomass: `p_max_pu = ENERGIA / p_nom`
  Se usa ENERGIA porque se asume que en 2024 se tomaba el máximo disponible del recurso.
- Resto de tecnologías (térmica, hidro, nuclear, pumped_hydro, diesel):
  `p_max_pu = POT_DISP / p_nom`
  POT_DISP refleja la capacidad disponible real hora a hora, incorporando paradas
  programadas, mantenimientos e indisponibilidades.
- En ambos casos el resultado se clipea entre 0 y 1.
- Unidades sin match en CAMMESA (autoproductores, fuera del MEM): excluidas del output.
  El script 19 y 21 eliminan del network cualquier generador sin perfil en este archivo.

**Matching GRUPO → unidad del modelo:**
Mismo criterio que el script 14b: match directo por `bus_name_origen`, o distribución
proporcional a `p_nom` por nemo4 cuando el GRUPO de CAMMESA representa la central entera.
La distribución se vectoriza con merge de pandas — no itera fila a fila.

Procesamiento en chunks (500.000 filas) para no exceder RAM.

Output: `gen_profiles_2024.csv` — externo a GitHub por tamaño (~5.3M filas).
Columnas: `gen_key`, `bus_conexion500kv_name`, `carrier`, `datetime`, `p_max_pu`.

---

### `18_diagnostico_costos_marginales.py`
Diagnóstico de cobertura de costos marginales para las 626 unidades de `generators_2024.csv`.
No construye el archivo final — es un paso de auditoría previo al 18B.

Grupos de análisis:
- **Térmica y nuclear**: match contra `CVP_Termica.csv` por clave reducida (primeras 4 siglas + últimos 2 dígitos). Prioridad de combustible: GN > combustible único > FO sobre GO.
- **Renovables**: match por `nombre_geosadi` normalizado vs campo `Proyecto` de `CVP_renovar.csv`.
- **Hidro**: datos pendientes de completar manualmente en la columna `CVP_manual`.

Output: `18_costos_marginales_diagnostico.csv` — tabla con cobertura de costos por unidad.
La columna `CVP_manual` debe completarse manualmente antes de correr el script 18B.

---

### `18B_build_costos_marginales_2024.py`
Construye `costos_marginales_2024.csv` con costo marginal fijo anual por unidad generadora.
Requiere que `costos_marginales_diagnostico_completado.csv` esté completado (generado por 18).

**Fuentes de costo por tecnología:**
- Térmica/nuclear: costo único desde `CVP_Termica.csv` (filtro año 2026, semana 1)
- Renovables: promedio anual de columnas Jan-24 a Dec-24 de `CVP_renovar.csv`
- Hidro y pendientes: desde columna `CVP_manual` del diagnóstico completado

**Lógica de CVP_manual:**
- Si es numérico: se usa directamente como costo marginal
- Si es texto: se busca ese nombre en el CVP correspondiente según tecnología

Parámetros configurables:
- `EXCLUIR_SIN_COSTO` — False (default): asigna costo=0 a unidades sin datos. True: las excluye del output.

---

### `19_run_optimization.py`
Despacho económico lineal DC (OPF) sobre la red 500 kV para el período configurado.
Usa `n.optimize()` de PyPSA con solver HiGHS.

El script carga dinámicamente generadores, perfiles y demanda sobre `network_500kv.nc`
sin modificar ese archivo base. Los resultados se guardan en un `.nc` separado.

**Decisiones de modelado:**
- DC OPF lineal: sin pérdidas, sin tensiones, solo flujos activos
- Sin restricciones adicionales: no hay mínimos técnicos ni rampas
- Slack bus: `ATUCHA 2_21kV`
- Link Brasil: solo importación (`p_min_pu=0`), libre para el solver
- Load shedding virtual en cada bus (costo=10.000 USD/MWh) para garantizar factibilidad
- Generadores sin costo marginal en `costos_marginales_2024.csv`: costo=0 por default
- Generadores sin perfil en `gen_profiles_2024.csv`: excluidos del network

**Parámetros configurables:**
- `FECHA_INICIO` / `FECHA_FIN` — período de simulación
- `CHUNK_DIAS` — None (problema único) o número de días por bloque (reduce RAM)
- `EXCLUIR_SIN_COSTO` — False (costo=0) o True (excluir del modelo)

Output: `results_2024_YYYYMMDD_YYYYMMDD.nc` en `networks/` (no versionado en git).
El sufijo de fechas evita pisar corridas anteriores de distintos períodos.

---

### `20_analyze_results.py` *(pendiente)*
Análisis de resultados de la optimización vs datos reales CAMMESA.
Levanta `results_2024_*.nc` sin necesidad de recorrer la optimización.

Análisis previstos:
- Mix de generación por tecnología y por período
- Comparación despacho simulado vs real CAMMESA
- Líneas congestionadas por período
- Importación acumulada desde Brasil

---

### `21_network_clustering.py`
Genera versiones simplificadas de la red mediante clustering espacial k-means nativo
de PyPSA (`kmeans_clustering`). Para cada nivel de agregación en `CLUSTER_SIZES`
produce un network clusterizado funcional para optimización y archivos de visualización.

El network base se carga con generadores, perfiles horarios completos, demanda y costos
antes de clusterizar, de forma que cada network clusterizado resultante quede listo
para `n.optimize()` sin pasos adicionales.

**Parámetros configurables:**
- `CLUSTER_SIZES` — lista de niveles de agregación deseados (ej: [10, 20, 50])
- `BUS_WEIGHTING` — criterio de pesos: `"uniforme"` (geográfico puro), `"p_nom"` (pondera por generación instalada), `"demanda"` (pondera por demanda)
- `EXCLUIR_SIN_COSTO` — False (costo=0) o True (excluir del modelo)

**Outputs** en `data/network_500kv/clusters/`:
- `clusters.gpkg` — layers `k{N}_buses`, `k{N}_centroids`, `k{N}_lines` para cada N
- `cluster_summary_k{N}.csv` — capacidad instalada por tecnología por cluster
- `cluster_k{N}.nc` — network clusterizado exportado (no versionado en git)

---

### `aliases_500kv.py`
Módulo auxiliar usado por `06_match_geosadi_geometry.py`.
Contiene el diccionario de aliases para resolver abreviaturas y variantes de nombres
de estaciones en los nombres de líneas GeoSADI.
No se corre directamente.
