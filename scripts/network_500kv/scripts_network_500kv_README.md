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

Output:
- `generators_mapped.csv` — tabla completa (una fila por generador)

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
porque la red de 132 kV de CABA/conurbano no tiene los ramales de conexión hacia las
subestaciones de frontera (ABASTO, EZEIZA, RODRIGUEZ) modelados en el PSS/E.
Esta carga queda agregada en esas tres subestaciones de frontera.

Output:
- `loads_mapped.csv` — tabla completa de lookup topológica (1.215 cargas)

---

### `10b_visualize_qgis.py`
Calcula el balance generación/carga por nodo del modelo y exporta a GeoPackage
para visualización en QGIS como mapa de burbujas.

Lee la columna `bus_conexion500kv` de `generators_mapped.csv` para agregar generación
por nodo. Las cargas usan la columna `bus_destino` de `loads_mapped.csv`.

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
Extiende `generators_mapped.csv` con coordenadas geográficas de GeoSADI.

**Matching geográfico:**
Se comparan los primeros 4 caracteres del `bus_name_origen` (PSS/E) contra los
primeros 4 caracteres del campo `Nemo` de `centrales_electricas.csv` (GeoSADI).
Si hay múltiples candidatos, se desambigua por tipo tecnológico. Para casos con
ambigüedad no resoluble automáticamente se usa el diccionario `NEMO_PREFERIDO`
(ej: Salto Grande, representación argentina vs. uruguaya).

Resultados posibles en `geo_match`:
- `exacto` — central GeoSADI identificada sin ambigüedad
- `sin_match` — ningún candidato en GeoSADI
- `a_revisar` — múltiples candidatos no resolubles automáticamente

**Overrides de carrier:**
- Tipo GeoSADI `HB` → carrier = `pumped_hydro` (único caso: Río Grande, 750 MW)
- Tipo GeoSADI `VG` → se acepta si carrier PSS/E ∈ {ocgt, steam, ccgt}; si no → `VG_revisar`

**Criterio de separación de outputs:**
- `generators_readypypsa.csv` — tiene `geo_match='exacto'`, `bus_conexion500kv` resuelto
  y carrier válido. Son los candidatos directos a entrar a PyPSA una vez se incorpore
  la generación real 2024. El join con esa data se hace por `nombre_geosadi` → `bus_conexion500kv`.
- `generators_pendingmanualpypsa.csv` — le falta `nombre_geosadi`, `bus_conexion500kv`,
  o ambos. Una fila por generador. Columna `falta` indica qué falta (`geo`/`bus`/`ambos`).
  Columna `COMENTARIOS` vacía para registrar la decisión tomada (ej: `red interna ALUAR,
  no va a PyPSA`). **No se versiona en git** — se regenera en cada corrida.

Una vez completado el pending manualmente se guarda como `generators_manualpypsa.csv`
(ese sí se versiona). El script 12 hace el join final.

Parámetros configurables:
- `NEMO_PREFERIDO` — diccionario bus_name_origen → Nemo GeoSADI para casos especiales
- `VG_CARRIERS_VALIDOS` — carriers aceptables para centrales de tipo VG en GeoSADI

---

### `12_build_generators_final.py`
Une `generators_readypypsa.csv` con las filas de `generators_manualpypsa.csv` que
tienen ambos campos completos (`nombre_geosadi` y `bus_conexion500kv`) para producir
`generators_final.csv` — la tabla definitiva de generadores que entra a PyPSA.

El join con la data real de generación 2024 (CAMMESA) se hace por `nombre_geosadi`
→ `bus_conexion500kv`. Los MW del PSS/E (`pg_mw`, `pt_mw`) son solo referencia y
no se cargan al modelo.

---

### `12b_export_qgis_generators.py`
Agrega un layer de centrales eléctricas al GeoPackage `balance_gen_carga.gpkg` generado
por el script `10b`. Requiere que ese `.gpkg` ya exista.

Layer exportado: `centrales_electricas` en `data/GIS_psse_geosadi_pypsaearth/balance_gen_carga.gpkg`

Atributos del layer:
- `gen_key` — clave única PSS/E
- `bus_name_origen` — nombre del bus origen en PSS/E
- `nombre_geosadi` — nombre de la central en GeoSADI
- `bus_conexion500kv_name` — nodo del modelo al que conecta
- `carrier` — tipo tecnológico
- `pg_mw` — despacho en snapshot PSS/E (MW)
- `pt_mw` — potencia instalada (MW)
- `stat` — estado en snapshot PSS/E (1=en servicio)
- `match_type` — cómo se resolvió la conexión al modelo

Se excluyen generadores con `pt_mw >= 9000` (equivalentes ficticios del PSS/E)
y generadores sin coordenadas geográficas.

---

### `12c_test_snapshot.py`
Carga los generadores y cargas del snapshot PSS/E al objeto PyPSA Network y corre
un power flow Newton-Raphson para validar la topología y el balance de la red.

Antes del power flow detecta y elimina subredes aisladas (buses desconectados de la
red principal, típicamente remanentes de `match_status='pendiente_bus'`).

Slack bus: `ATUCHA 2_21kV` (bus 2620, central nuclear, 21 kV).

Pasos de ejecución:
1. Detección y eliminación de subredes aisladas
2. Carga de generadores activos (`stat=1`, `pt_mw < 9000`) con sus despachos del snapshot
3. Carga de cargas activas (`stat=1`, `pl_mw > 0`)
4. Power flow Newton-Raphson

Resultados reportados en consola:
- Tensiones nodales (mín / máx / buses fuera de [0.90, 1.10] pu)
- Buses con tensión crítica (si los hay)
- Carga de líneas con rating definido y líneas sobrecargadas (>100%)

No produce archivo de salida — es un script de validación. Si el power flow converge,
la topología y el balance generación/carga del snapshot están consistentes.

---

### `aliases_500kv.py`
Módulo auxiliar usado por `06_match_geosadi_geometry.py`.
Contiene el diccionario de aliases para resolver abreviaturas y variantes de nombres
de estaciones en los nombres de líneas GeoSADI.
No se corre directamente.
