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
| `09_map_generators.py` | Mapea generadores PSS/E → nodos del modelo vía BFS | `ver2526pid.raw` + `buses_final.csv` | `generators_mapped.csv` + `generators_manual_assignment.csv` |
| `10_map_loads.py` | Mapea cargas PSS/E → nodos del modelo vía BFS | `ver2526pid.raw` + `buses_final.csv` | `loads_mapped.csv` |
| `10b_visualize_qgis.py` | Exporta balance generación/carga por nodo a GeoPackage | `generators_mapped.csv` + `loads_mapped.csv` + `buses_final.csv` | `balance_gen_carga.gpkg` |
| `aliases_500kv.py` | Diccionario de aliases para matching GeoSADI | — | (módulo auxiliar) |

> Scripts `11_add_to_pypsa.py` y `12_run_powerflow.py` están pendientes — esperan datos reales de generación y demanda 2024.

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
- Impedancias del PSS/E pasadas directamente en pu (Sbase=100 MVA)
- Compensadores serie modelados como `Line` con x negativo
- Transformadores de 3 devanados ya descompuestos en 2W desde el script 03
- Output en `networks/network_500kv.nc` (no versionado en git)

---

### `09_map_generators.py`
Parsea la sección `MACHINE DATA` del PSS/E y mapea cada unidad generadora al nodo
del modelo (`buses_final.csv`) más cercano topológicamente, usando BFS sobre
`BRANCH DATA` + `TRANSFORMER DATA`.

Categorías de resultado en campo `method`:
- `directo` — la máquina ya está en un bus del modelo
- `bfs` — alcanzó un nodo del modelo en N saltos (típico: 1–3)
- `sin_conexion` — la subbred del PSS/E no tiene continuidad con el backbone

Grupos de `sin_conexion` identificados:
- **Ignorar:** ALUAR (red industrial aislada) y equivalentes Thévenin del PSS/E (PG negativo, PT=9999)
- **Asignación manual:** ~8 centrales grandes (~3.200 MW) del área metropolitana GBA y NOA — ver `generators_manual_assignment.csv`

Parámetros configurables:
- `EXCLUIR_BUS_NOMBRES` — set de buses a excluir del output (ALUAR + equivalentes)
- `FORCE_STAT1` — incluir solo máquinas en servicio (STAT=1)

Outputs:
- `generators_mapped.csv` — tabla completa de lookup topológica (836 generadores)
- `generators_manual_assignment.csv` — plantilla para completar `bus_destino_manual` de centrales sin conexión relevantes

---

### `10_map_loads.py`
Parsea la sección `LOAD DATA` del PSS/E y mapea cada carga al nodo del modelo
usando la misma lógica BFS que `09_map_generators.py`.

Se usa únicamente el campo `PL` (potencia activa constante). Los campos `IP` e `YP`
son cero en todo el raw de CAMMESA, por lo que PL = carga total del nodo.

Categorías de resultado en campo `method`:
- `directo` — la carga está directamente en un nodo del modelo
- `bfs` — alcanzó un nodo del modelo en N saltos
- `sin_conexion` — subbred sin continuidad con el backbone

Nota sobre el área metropolitana GBA: ~3.720 MW de carga aparecen como `sin_conexion`
porque la red de 132 kV de CABA/conurbano (AZCUENAG, BARRACAS, ESCALADA, etc.)
no tiene los cables de conexión hacia las subestaciones de frontera (ABASTO, EZEIZA,
RODRIGUEZ) modelados en el PSS/E. Los trafos 500/220/132 kV en esas subestaciones
sí existen, pero los ramales de 132 kV hacia adentro del área no están en el raw.
Esta carga queda agregada en esas tres subestaciones de frontera.

Output:
- `loads_mapped.csv` — tabla completa de lookup topológica (1.215 cargas)

---

### `10b_visualize_qgis.py`
Calcula el balance generación/carga por nodo del modelo y exporta a GeoPackage
para visualización en QGIS como mapa de burbujas.

Layer exportado: `balance_por_bus` en `data/GIS_psse_geosadi_pypsaearth/balance_gen_carga.gpkg`

Atributos del layer:
- `pg_mw` — generación total mapeada al nodo (MW)
- `pl_mw` — carga total mapeada al nodo (MW)
- `balance_mw` — pg_mw − pl_mw (positivo = nodo generador, negativo = nodo consumidor)
- `n_generadores` / `n_cargas` — cantidad de unidades mapeadas

Simbología sugerida en QGIS (expresión para tamaño de burbuja):
```
sqrt(abs("balance_mw")) / 1.5
```
Verde = balance positivo (nodo generador). Rojo = balance negativo (nodo consumidor).

---

### `aliases_500kv.py`
Módulo auxiliar usado por `06_match_geosadi_geometry.py`.
Contiene el diccionario de aliases para resolver abreviaturas y variantes de nombres
de estaciones en los nombres de líneas GeoSADI.
No se corre directamente.
