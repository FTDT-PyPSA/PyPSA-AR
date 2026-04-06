# data/network_500kv

Archivos procesados del pipeline de construcción de la red 500 kV.
Generados corriendo los scripts de `scripts/network_500kv/` en orden.

---

## Índice de archivos

| Archivo | Generado por | Descripción breve |
|---------|-------------|-------------------|
| `buses_500kv_raw.csv` | `01_parse_raw_buses.py` | Buses 500 kV extraídos del PSS/E |
| `lines_500kv_raw.csv` | `02_parse_raw_lines.py` | Líneas y compensadores 500 kV extraídos del PSS/E |
| `trafos_500kv_raw.csv` | `03_parse_raw_transformers.py` | Transformadores con al menos un lado en 500 kV |
| `buses_sec_raw.csv` | `04_parse_raw_buses_sec.py` | Buses secundarios (lado bajo de los transformadores) |
| `buses_final.csv` | `05_match_geosadi_coords.py` | Todos los buses con coordenadas geográficas |
| `lines_500kv_final.csv` | `06_match_geosadi_geometry.py` | Líneas con geometría WKT de GeoSADI |
| `buses_PSSE_vs_geosadi.xlsx` | Manual | Diccionario de matching bus PSS/E → coordenadas GeoSADI |
| `manual_line_mappings.csv` | Manual | Diccionario de mapping line_key → geosadi_line_id |
| `topology_report.csv` | `07_validate_topology.py` | Reporte de problemas topológicos |
| `generators_mapped.csv` | `09_map_generators.py` | Tabla de lookup topológica generadores PSS/E → nodos modelo |
| `generators_readypypsa.csv` | `11_add_geo_to_generators.py` | Generadores con geo + bus resueltos — candidatos directos a PyPSA |
| `generators_manualpypsa.csv` | Manual | Pending completado manualmente con decisiones y asignaciones |
| `generators_final.csv` | `12_build_generators_final.py` | Tabla definitiva de generadores para PyPSA |
| `conflictos_psse_cammesa.csv` | `14_detectar_conflictos_generadores.py` | Discrepancias entre nombres PSS/E y GRUPOs CAMMESA — completar manualmente |
| `generators_2024.csv` | `14b_build_generators_2024.py` | Generadores con potencia real 2024 (p_nom desde CAMMESA) |
| `loads_mapped.csv` | `10_map_loads.py` | Tabla de lookup topológica cargas PSS/E → nodos modelo |
| `loads_2024.csv` | `15_build_loads_2024.py` | Demanda horaria 2024 por bus 500 kV en formato largo |
| `18_costos_marginales_diagnostico.csv` | `18_diagnostico_costos_marginales.py` | Auditoría de cobertura de costos marginales — completar columna `CVP_manual` antes de correr 18B |
| `costos_marginales_2024.csv` | `18B_build_costos_marginales_2024.py` | Costo marginal fijo anual por unidad generadora (USD/MWh) |
| `conexiones_internacionales.md` | Manual | Interconexiones con países vecinos en el PSS/E |

**Archivos externos a GitHub** (tamaño o datos sensibles):

| Archivo | Generado por | Descripción breve |
|---------|-------------|-------------------|
| `valores_2024_clean.csv` | `13_clean_valores_2024.py` | Generación horaria 2024 limpia y normalizada (CAMMESA) |
| `gen_profiles_2024.csv` | `17_build_gen_profiles_2024.py` | Perfiles horarios de disponibilidad (p_max_pu) por unidad generadora |

> Los archivos GeoPackage de la red base (`.gpkg`) se guardan en `data/GIS_psse_geosadi_pypsaearth/`.

> Los archivos de clustering se guardan en `data/network_500kv/clusters/` — ver sección correspondiente.

> `generators_pendingmanualpypsa.csv` se genera en cada corrida del script 11 pero
> **no se versiona en git** — es un archivo de trabajo que se regenera automáticamente.

> `network_500kv.nc` y `results_2024_*.nc` se guardan en `networks/` y **no se versionan en git**.

---

## Detalle

### `buses_500kv_raw.csv`
**Fuente:** PSS/E `ver2526pid.raw` (CAMMESA)

Buses 500 kV del caso PSS/E con sus parámetros eléctricos del caso base.
Un registro por bus. Excluye buses IDE=4 (aislados) e internacionales.

| Campo | Descripción |
|-------|-------------|
| `bus_id` | ID numérico en PSS/E |
| `bus_name` | Nombre del bus |
| `baskv_kv` | Tensión base (kV) |
| `ide` | Tipo: 1=PQ, 2=PV, 3=slack |
| `ide_desc` | Descripción del tipo de bus |
| `area` | Área eléctrica CAMMESA |
| `vm_pu` | Módulo de tensión del caso base (pu) |
| `va_deg` | Ángulo de tensión del caso base (grados) |

---

### `lines_500kv_raw.csv`
**Fuente:** PSS/E `ver2526pid.raw` (CAMMESA)

Líneas y compensadores serie 500 kV con impedancias y ratings del caso PSS/E.

| Campo | Descripción |
|-------|-------------|
| `line_key` | Identificador legible: `BUS_I-BUS_J-CKT` |
| `bus_i` / `bus_j` | IDs de buses extremos |
| `ckt` | Número de circuito (1, 2, 3...) |
| `r_pu` / `x_pu` / `b_pu` | Impedancias en pu (Sbase=100 MVA) |
| `ratea_mva` | Capacidad térmica en MVA (NaN si no definida) |
| `len_km` | Longitud en km |
| `element_type` | `line` o `series_compensator` |
| `in_service` | True si la rama está en servicio |

---

### `trafos_500kv_raw.csv`
**Fuente:** PSS/E `ver2526pid.raw` (CAMMESA)

Transformadores con al menos un devanado en 500 kV. Los transformadores de 3 devanados
se descomponen en 2 transformadores de 2 devanados usando el devanado de 500 kV como
referencia común.

| Campo | Descripción |
|-------|-------------|
| `trafo_key` | Identificador legible: `BUS_I-BUS_J-CKT` |
| `bus_i` | Bus 500 kV (siempre el lado de alta tensión) |
| `bus_j` | Bus secundario (lado de baja tensión) |
| `ckt` | Número de circuito |
| `origin` | `2W` (original) o `3W_decomp` (descompuesto de 3 devanados) |
| `r_pu` / `x_pu` | Impedancias en pu (Sbase=100 MVA) |
| `sbase_mva` | Potencia base del transformador en MVA |
| `in_service` | True si el transformador está en servicio |

---

### `buses_sec_raw.csv`
**Fuente:** PSS/E `ver2526pid.raw` (CAMMESA)

Buses secundarios: todos los buses que aparecen como `bus_j` en `trafos_500kv_raw.csv`.

| Campo | Descripción |
|-------|-------------|
| `bus_id` | ID numérico en PSS/E |
| `bus_name` | Nombre generado: `PARENT_kVkV` o `PARENT_kVkV_N` |
| `bus_name_psse` | Nombre original del bus en el PSS/E |
| `baskv_kv` | Tensión base (kV) |
| `ide` | Tipo de bus PSS/E |
| `vm_pu` / `va_deg` | Tensión del caso base |
| `parent_bus_id` | `bus_id` del bus 500 kV al que conecta vía transformador |

---

### `buses_final.csv`
**Fuente:** `buses_500kv_raw.csv` + `buses_sec_raw.csv` + `buses_PSSE_vs_geosadi.xlsx`

Consolidación de todos los buses del modelo con coordenadas geográficas.

| Campo | Descripción |
|-------|-------------|
| `bus_id` | ID numérico en PSS/E |
| `bus_name` | Nombre del bus en el modelo |
| `bus_type` | `500kV` o `secundario` |
| `baskv_kv` | Tensión base (kV) |
| `vm_pu` / `va_deg` | Tensión del caso base PSS/E |
| `lat` / `lon` | Coordenadas geográficas (WGS84) |
| `parent_bus_id` | Bus 500 kV padre (NaN para buses 500 kV) |
| `name_geosadi` | Nombre GeoSADI asignado (solo buses 500 kV) |

---

### `lines_500kv_final.csv`
**Fuente:** `lines_500kv_raw.csv` + GeoSADI `lineas_alta_tension.geojson`

Líneas con geometría WKT asignada. Extiende `lines_500kv_raw.csv` con:

| Campo | Descripción |
|-------|-------------|
| `geo_nombre` | Nombre de la línea GeoSADI asignada |
| `match_status` | `directo` / `paralela` / `manual_geo` / `compensador` / `pendiente_bus` |
| `geometry` | Geometría WKT (LINESTRING, WGS84) |

---

### `buses_PSSE_vs_geosadi.xlsx`
**Fuente:** revisión manual

Diccionario de coordenadas para los 95 buses 500 kV del PSS/E.

---

### `manual_line_mappings.csv`
**Fuente:** revisión manual

23 entradas de mapping manual `line_key → geosadi_line_id` para líneas que no pueden
resolverse automáticamente.

---

### `topology_report.csv`
**Fuente:** `07_validate_topology.py`

Reporte de problemas topológicos. Si la red está limpia el archivo está vacío.

---

### `generators_mapped.csv`
**Fuente:** `09_map_generators.py`

Tabla de lookup topológica que mapea cada unidad generadora del PSS/E al nodo del
modelo más cercano.

| Campo | Descripción |
|-------|-------------|
| `gen_key` | Clave única PSS/E: `bus_id_origen-gen_id` |
| `bus_name_origen` | Nombre del bus origen en PSS/E |
| `carrier` | Tipo tecnológico PyPSA |
| `pg_mw` | Despacho activo en el snapshot PSS/E (MW) |
| `pt_mw` | Potencia máxima instalada (MW) |
| `stat` | Estado en el snapshot (1=en servicio, 0=fuera) |
| `match_type` | `directo` / `bfs` / `sin_conexion` |
| `bus_conexion500kv` | bus_id del nodo del modelo asignado |
| `bus_conexion500kv_name` | Nombre del nodo destino en el modelo |
| `n_saltos` | Saltos BFS hasta el nodo destino |
| `camino` | Ruta de buses PSS/E desde origen hasta destino |

---

### `generators_final.csv`
**Fuente:** `12_build_generators_final.py`

Tabla definitiva de generadores para PyPSA. Une `generators_readypypsa.csv` con las
filas de `generators_manualpypsa.csv` que tienen `nombre_geosadi` y `bus_conexion500kv`
completos.

El campo `nemo` se resuelve haciendo join `nombre_geosadi` → `Nombre` en
`centrales_electricas.csv` de GeoSADI. Las unidades TG01, TG06 y TV07 de Agua del
Cajón figuran con `nemo = CAPE` (CAPEX Autoprod.) por reasignación aplicada en este script.

---

### `conflictos_psse_cammesa.csv`
**Fuente:** `14_detectar_conflictos_generadores.py` + completado manualmente

Discrepancias entre los nombres de unidades del modelo (PSS/E) y los GRUPOs de CAMMESA.

| Campo | Descripción |
|-------|-------------|
| `gen_key` | Clave única de la unidad |
| `bus_name_origen` | Nombre PSS/E actual |
| `nombre_geosadi` | Nombre de la central en GeoSADI |
| `bus_conexion500kv_name` | Nodo del modelo al que conecta |
| `nemo4` | Primeros 4 caracteres del nemo |
| `carrier` | Tipo tecnológico |
| `grupos_cammesa` | GRUPOs CAMMESA de la central separados por `\|` |
| `n_grupos_cammesa` | Cantidad de GRUPOs en CAMMESA |
| `bus_name_origen_correcto` | **Completar:** GRUPO de CAMMESA que corresponde a esta unidad |
| `revisado` | **Completar:** `si` si fue revisado y no tiene match posible (va al nemo4) |
| `excluir` | **Completar:** `si` si la unidad debe excluirse del modelo |
| `comentario` | **Completar:** observaciones del unifilar |

---

### `generators_2024.csv`
**Fuente:** `14b_build_generators_2024.py`

Tabla de generadores con potencia instalada real 2024 desde CAMMESA. Es el input
de generación del modelo a partir del script 14b en adelante.

| Campo | Descripción |
|-------|-------------|
| `gen_key` | Clave única PSS/E |
| `bus_name_origen` | Nombre del bus origen (con overrides de conflictos aplicados) |
| `nombre_geosadi` | Nombre de la central en GeoSADI |
| `nemo` | Código CAMMESA de la central |
| `bus_conexion500kv` / `bus_conexion500kv_name` | Nodo del modelo al que conecta |
| `carrier` | Tipo tecnológico PyPSA |
| `p_nom` | Potencia instalada real (MW) — percentil 95 de POT_DISP anual en CAMMESA |
| `lat` / `lon` | Coordenadas geográficas (WGS84) |

Notas:
- Salto Grande (SGDE): `p_nom` × 0.5 (central binacional Argentina/Uruguay)
- 18 unidades excluidas por conflicto de nombre con CAMMESA
- 25 unidades sin match en CAMMESA (autoproductores y centrales fuera del MEM)
- `p_nom` total del sistema: ~40.084 MW

---

### `loads_mapped.csv`
**Fuente:** `10_map_loads.py`

Tabla de lookup topológica que mapea cada carga del PSS/E al nodo del modelo más
cercano. Misma lógica BFS que `generators_mapped.csv`.

---

### `loads_2024.csv`
**Fuente:** `15_build_loads_2024.py`

Demanda horaria 2024 por bus 500 kV en formato largo. Una fila por bus por hora.

Los `bus_name` del output coinciden con el índice de buses de `network_500kv.nc`
gracias a la fusión de acopladores de barra aplicada durante el procesamiento.

| Campo | Descripción |
|-------|-------------|
| `bus_id` | ID del bus 500 kV |
| `bus_name` | Nombre del bus en el network |
| `datetime` | Timestamp en formato DD/MM/YYYY HH:MM |
| `p_mw` | Demanda en MW |

Cobertura: 72 buses × 8784 horas. 6 buses del network sin demanda en el archivo
fuente (compensadores y barras de paso sin carga de distribución asociada).

Pico de demanda del sistema: 27.439 MW el 01/02/2024 a las 14:00.

---

### `18_costos_marginales_diagnostico.csv`
**Fuente:** `18_diagnostico_costos_marginales.py` + completado manualmente

Auditoría de cobertura de costos marginales para las 626 unidades de `generators_2024.csv`.
La columna `CVP_manual` debe completarse antes de correr el script 18B.

| Campo | Descripción |
|-------|-------------|
| `bus_name_origen` | Nombre del bus origen en PSS/E |
| `nombre_geosadi` | Nombre de la central en GeoSADI |
| `nemo` | Código CAMMESA |
| `carrier` | Tipo tecnológico |
| `p_nom` | Potencia instalada (MW) |
| `costo_marginal_match` | Costo encontrado automáticamente (USD/MWh) |
| `fuente_costo` | `CVP_Termica` / `CVP_renovar` / `rescate` / NaN |
| `CVP_manual` | **Completar:** valor numérico o nombre de lookup para unidades sin costo automático |

---

### `costos_marginales_2024.csv`
**Fuente:** `18B_build_costos_marginales_2024.py`

Costo marginal fijo anual por unidad generadora. Input directo para la optimización
(scripts 19 y 21).

| Campo | Descripción |
|-------|-------------|
| `gen_key` | Clave única PSS/E |
| `bus_name_origen` | Nombre del bus origen |
| `nombre_geosadi` | Nombre de la central en GeoSADI |
| `nemo` | Código CAMMESA |
| `bus_conexion500kv` / `bus_conexion500kv_name` | Nodo del modelo al que conecta |
| `carrier` | Tipo tecnológico PyPSA |
| `p_nom` | Potencia instalada (MW) |
| `lat` / `lon` | Coordenadas geográficas (WGS84) |
| `costo_marginal(USD/mwh)` | Costo marginal fijo anual (USD/MWh) |

Estado actual: ~433 unidades con costo asignado, ~171 con costo=0 (pendientes de completar).

---

### `valores_2024_clean.csv` *(externo a GitHub)*
**Fuente:** `13_clean_valores_2024.py`
**Ruta local:** `Official data/valores_2024_clean.csv`

Archivo limpio y normalizado de generación horaria 2024 del MEM. Base para los
scripts 14b, 16 y 17.

| Campo | Descripción |
|-------|-------------|
| `FECHA` | Fecha normalizada (DD/MM/YYYY) |
| `HORA` | Hora CAMMESA (1-24, donde HORA=1 → 00:00) |
| `datetime` | Timestamp construido como fecha + (HORA-1) horas (DD/MM/YYYY HH:MM) |
| `GRUPO` | Identificador de la unidad generadora en CAMMESA |
| `TIPO` | Tipo tecnológico CAMMESA |
| `Central` | Nemo de la central (4 caracteres) |
| `Region` | Región CAMMESA |
| `ENERGIA` | Energía generada en la hora (MWh ≡ MW promedio de la hora) |
| `POT_DISP` | Potencia disponible declarada (MW) |
| `ENERG_OPERADA` | Energía operada (MWh) |
| `POT_DISP_GN` | Potencia disponible de gas natural (MW) |
| `PIND` | Potencia independiente (MW) |
| `flag_outlier` | True si el valor supera el percentil 99.9 del GRUPO o es negativo |

---

### `gen_profiles_2024.csv` *(externo a GitHub)*
**Fuente:** `17_build_gen_profiles_2024.py`
**Ruta local:** `Official data/gen_profiles_2024.csv`

Perfiles horarios de disponibilidad para todas las unidades generadoras del modelo.
Input para la optimización (scripts 19 y 21). Las unidades sin match en CAMMESA
(autoproductores, fuera del MEM) no aparecen en este archivo y son excluidas del
network por los scripts 19 y 21 al momento de carga.

| Campo | Descripción |
|-------|-------------|
| `gen_key` | Clave única de la unidad |
| `bus_conexion500kv_name` | Nodo del modelo al que conecta |
| `carrier` | Tipo tecnológico PyPSA |
| `datetime` | Timestamp (DD/MM/YYYY HH:MM) |
| `p_max_pu` | Factor de disponibilidad [0,1]. Para solar/eólica/biogas/biomass: ENERGIA/p_nom. Para el resto: POT_DISP/p_nom |

Cobertura: ~577 unidades × 8784 horas ≈ 5.3M filas.

---

## Subcarpeta `clusters/`

Archivos generados por `21_network_clustering.py`. Contiene versiones simplificadas
de la red para análisis de largo plazo.

| Archivo | Descripción |
|---------|-------------|
| `clusters.gpkg` | GeoPackage con layers de buses, centroides y líneas equivalentes para cada nivel de agregación |
| `cluster_summary_k{N}.csv` | Capacidad instalada por tecnología por cluster para K=N |
| `cluster_k{N}.nc` | Network PyPSA clusterizado a K=N super-buses — listo para `n.optimize()` (no versionado en git) |

### `clusters.gpkg`
Layers incluidos para cada N en `CLUSTER_SIZES`:
- `k{N}_buses` — los 346 buses originales con `cluster_id` asignado. Visualizar con simbología categorizada por `cluster_id`.
- `k{N}_centroids` — los N super-buses con `p_nom_total_mw` y `n_buses`. Visualizar con tamaño proporcional a `sqrt(p_nom_total_mw) / 5`.
- `k{N}_lines` — líneas equivalentes entre clusters con `s_nom_mw`. Visualizar con ancho proporcional a `s_nom_mw / 1000`.

### `cluster_summary_k{N}.csv`

| Campo | Descripción |
|-------|-------------|
| `cluster_id` | ID del cluster (0 a N-1) |
| `centroid_lat` / `centroid_lon` | Coordenadas del super-bus |
| `n_buses` | Buses originales contenidos en el cluster |
| `p_nom_hydro_mw` | Capacidad hidro + pumped_hydro (MW) |
| `p_nom_nuclear_mw` | Capacidad nuclear (MW) |
| `p_nom_termica_mw` | Capacidad térmica: ccgt + ocgt + steam + diesel (MW) |
| `p_nom_wind_mw` | Capacidad eólica (MW) |
| `p_nom_solar_mw` | Capacidad solar (MW) |
| `p_nom_bioenergia_mw` | Capacidad biomass + biogas (MW) |
| `p_nom_total_mw` | Capacidad total instalada (MW) |

---

### `conexiones_internacionales.md`
Tabla de interconexiones de Argentina con Bolivia, Brasil, Chile, Paraguay y Uruguay
presentes en el PSS/E. Referencia para cuando se incorporen esos flujos al modelo.
