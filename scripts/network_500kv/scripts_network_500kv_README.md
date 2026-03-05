# scripts/network_500kv

Pipeline de construcción de la red 500 kV para PyPSA.
Correr en orden desde WSL con el entorno `pypsa-earth-lock`.

---

## Índice de scripts

| Script | Descripción breve | Input | Output |
|--------|-------------------|-------|--------|
| `01_parse_raw_buses.py` | Extrae buses 500 kV del PSS/E | `ver2526pid.raw` | `buses_500kv_raw.csv` |
| `02_parse_raw_lines.py` | Extrae líneas y compensadores del PSS/E | `ver2526pid.raw` | `lines_500kv_raw.csv` |
| `03_match_geosadi_coords.py` | Asigna coordenadas GeoSADI a los buses | `buses_500kv_raw.csv` + GeoSADI | `buses_500kv_final.csv` |
| `04_match_geosadi_geometry.py` | Asigna geometría WKT a las líneas | `lines_500kv_raw.csv` + GeoSADI | `lines_500kv_final.csv` |
| `05_validate_topology.py` | Valida topología de la red | `*_final.csv` | `topology_report.csv` |
| `05b_export_qgis.py` | Exporta la red a GeoPackage para QGIS | `*_final.csv` | `red_500kv_qgis.gpkg` |
| `06_build_pypsa_network.py` | Construye el objeto PyPSA Network | `*_final.csv` | `network_500kv.nc` |
| `aliases_500kv.py` | Diccionario de aliases para matching GeoSADI | — | (módulo, no se corre directamente) |

---

## Detalle

### `01_parse_raw_buses.py`
Lee la sección `BUS DATA` del archivo PSS/E `.raw` y extrae todos los buses en el rango
490–530 kV. Excluye buses IDE=4 (aislados) e internacionales (por área CAMMESA).

Parámetros configurables:
- `KV_MIN` / `KV_MAX` — rango de tensión
- `EXCLUDE_INTERNATIONAL` — incluir o excluir buses de países vecinos

---

### `02_parse_raw_lines.py`
Lee la sección `BRANCH DATA` del PSS/E y extrae todas las ramas cuyos dos extremos
sean buses 500 kV. Clasifica cada rama como `line` o `series_compensator` (x < 0).
Normaliza el identificador de circuito: A→1, B→2, C→3.

Parámetros configurables:
- `INCLUDE_OUT_OF_SERVICE` — incluir ramas ST=0 (fuera de servicio)

---

### `03_match_geosadi_coords.py`
Asigna coordenadas geográficas a cada bus usando el diccionario manual
`buses_PSSE_vs_geosadi.xlsx` como fuente de verdad. Los buses sin entrada manual
quedan con `match_status = consultar`.

---

### `04_match_geosadi_geometry.py`
Para cada línea PSS/E busca la geometría correspondiente en el GeoJSON de GeoSADI.
El matching sigue este orden de prioridad:
1. Diccionario manual `manual_line_mappings.csv`
2. Matching por tokens de nombre (vía `aliases_500kv.py`)
3. Desambiguación por número de circuito para paralelas

Resultados posibles en `match_status`:
- `directo` — match único encontrado
- `paralela` — desambiguado por número de circuito
- `manual_geo` — asignado desde diccionario manual
- `compensador` — compensador serie, sin geometría de línea
- `pendiente_bus` — algún bus extremo no tiene name_geosadi

---

### `05_validate_topology.py`
Valida la red antes de cargarla en PyPSA. Detecta:
1. Líneas huérfanas (bus extremo ausente)
2. Buses sin líneas 500 kV — clasifica como barra central, nodo de transformador o bus aislado real
3. Componentes conexas (islas desconectadas)
4. Líneas con r=0 y x=0 simultáneamente
5. Líneas sin rating definido
6. Ramas fuera de servicio (ST=0, informativo)

Opera en dos modos: `COMPLETO` (usa `*_final.csv`) o `TOPOLOGIA` (usa `*_raw.csv`).

---

### `05b_export_qgis.py`
Exporta buses y líneas a un GeoPackage con dos layers (`buses_500kv`, `lines_500kv`).
Útil para verificación visual antes de cargar en PyPSA.
El `.gpkg` se guarda en `data/GIS_psse_geosadi_pypsaearth/`.

---

### `06_build_pypsa_network.py`
Construye el objeto `pypsa.Network` con la red 500 kV y lo exporta a `.nc`.
Decisiones de modelado:
- Impedancias del PSS/E pasadas directamente en pu (Sbase=100 MVA)
- Compensadores serie modelados como `Line` con x negativo
- Ramas ST=0 incluidas con `active=False`
- Output en `networks/network_500kv.nc` (no versionado en git)

---

### `aliases_500kv.py`
Módulo auxiliar usado por `04_match_geosadi_geometry.py`.
Contiene el diccionario de aliases para resolver abreviaturas y variantes de nombres
de estaciones en los nombres de líneas GeoSADI.
No se corre directamente.
