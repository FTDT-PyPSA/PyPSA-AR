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
| `09_map_generators.py` | Mapea generadores PSS/E → nodos del modelo vía BFS | `ver2526pid.raw` + `buses_final.csv` | `generators_mapped.csv` + `generators_manual_assignment_template.csv` |
| `10_map_loads.py` | Mapea cargas PSS/E → nodos del modelo vía BFS | `ver2526pid.raw` + `buses_final.csv` | `loads_mapped.csv` |
| `10b_visualize_qgis.py` | Exporta balance generación/carga por nodo a GeoPackage | `generators_mapped.csv` + `loads_mapped.csv` + `buses_final.csv` | `balance_gen_carga.gpkg` |
| `11_add_geo_to_generators.py` | Asigna coordenadas GeoSADI y resuelve conexiones manuales | `generators_mapped.csv` + `generators_manual_assignment_completed.csv` + `buses_final.csv` + GeoSADI | `generators_final.csv` + `generators_pending.csv` |
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
- Impedancias del PSS/E pasadas directamente en pu (Sbase=100 MVA)
- Compensadores serie modelados como `Line` con x negativo
- Transformadores de 3 devanados ya descompuestos en 2W desde el script 03
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
Si el carrier resuelto no corresponde a generación (DEMANDA, SS.AA., TRANSPORTE,
etc.), se intenta inferir desde las posiciones [4:6] del bus_name:
- TG → ocgt, TV → steam, HI → hydro, DI → diesel, CC → ccgt
- FV → solar, EO → wind, BG → biogas, BM → biomass, HB → pumped_hydro
- Posiciones [4:8] = NUCL → nuclear

Si tampoco puede resolverse por nombre, el generador se descarta. Esto elimina
equivalentes de red y nodos de demanda que aparecen incorrectamente como generadores
en el PSS/E.

**Categorías de resultado en `match_type`:**
- `directo` — el generador ya está en un bus del modelo
- `bfs` — alcanzó un nodo del modelo en N saltos (típico: 1–3)
- `sin_conexion` — la subred del PSS/E no tiene continuidad con el backbone

**Grupos `sin_conexion` identificados:**
- Ignorar: ALUAR (red industrial aislada), AEG y equivalentes Thévenin del PSS/E
- Asignación manual: centrales del área metropolitana GBA y NOA sin continuidad
  topológica hacia el backbone — ver `generators_manual_assignment_template.csv`

Parámetros configurables:
- `EXCLUIR_BUS_NOMBRES` — buses a excluir del template de asignación manual
- `PT_MIN_MW` — umbral mínimo de potencia instalada para incluir en el template

Outputs:
- `generators_mapped.csv` — tabla completa (770 generadores argentinos)
- `generators_manual_assignment_template.csv` — plantilla para completar manualmente

---

### `10_map_loads.py`
Parsea la sección `LOAD DATA` del PSS/E y mapea cada carga al nodo del modelo
usando la misma lógica BFS que `09_map_generators.py`.

Se usa únicamente el campo `PL` (potencia activa constante). Los campos `IP` e `YP`
son cero en todo el raw de CAMMESA, por lo que PL = carga total del nodo.

Categorías de resultado en campo `match_type`:
- `directo` — la carga está directamente en un nodo del modelo
- `bfs` — alcanzó un nodo del modelo en N saltos
- `sin_conexion` — subred sin continuidad con el backbone

Nota sobre el área metropolitana GBA: ~3.720 MW de carga aparecen como `sin_conexion`
porque la red de 132 kV de CABA/conurbano (AZCUENAG, BARRACAS, ESCALADA, etc.)
no tiene los ramales de conexión hacia las subestaciones de frontera (ABASTO, EZEIZA,
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

### `11_add_geo_to_generators.py`
Extiende `generators_mapped.csv` con coordenadas geográficas de GeoSADI y resuelve
el `bus_conexion500kv` para las centrales con asignación manual completada.

**Matching geográfico:**
Se comparan los primeros 4 caracteres del `bus_name_origen` (PSS/E) contra los
primeros 4 caracteres del campo `Nemo` de `centrales_electricas.csv` (GeoSADI).
Si hay múltiples candidatos, se desambigua por tipo tecnológico. Para Salto Grande
(representación argentina vs. uruguaya) se usa un diccionario de asignación
explícita por bus_name.

Resultados posibles en `geo_match`:
- `exacto` — central GeoSADI identificada sin ambigüedad
- `sin_match` — ningún candidato en GeoSADI
- `a_revisar` — múltiples candidatos no resolubles automáticamente

**Overrides de carrier aplicados en este script:**
- Tipo GeoSADI `HB` → carrier = `pumped_hydro` (único caso: Río Grande, 750 MW)
- Tipo GeoSADI `VG` → se acepta si carrier PSS/E ∈ {ocgt, steam, ccgt}; si no → `VG_revisar`

**Resolución manual de `bus_conexion500kv`:**
Para generadores `sin_conexion`, se hace join por `central_prefix` (primeros 6
caracteres del bus_name) contra `generators_manual_assignment_completed.csv`.
Si la entrada tiene `bus_conexion500kv_manual` completo, el `match_type` se actualiza
de `sin_conexion` a `manual`.

**Criterio de separación de outputs:**
- `generators_final.csv` — todos los generadores con `geo_match='exacto'`. Incluye
  generadores sin `bus_conexion500kv` resuelto; la conexión puede forzarse en etapas
  posteriores si se dispone de datos adicionales.
- `generators_pending.csv` — generadores con `geo_match='sin_match'` o `'a_revisar'`.
  Requieren revisión manual para completar coordenadas antes de incorporarlos al modelo.

Parámetros configurables:
- `NEMO_PREFERIDO` — diccionario bus_name_origen → Nemo GeoSADI para casos especiales
- `VG_CARRIERS_VALIDOS` — carriers aceptables para centrales de tipo VG en GeoSADI

---

### `aliases_500kv.py`
Módulo auxiliar usado por `06_match_geosadi_geometry.py`.
Contiene el diccionario de aliases para resolver abreviaturas y variantes de nombres
de estaciones en los nombres de líneas GeoSADI.
No se corre directamente.
