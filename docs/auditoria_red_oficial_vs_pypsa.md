# Auditoría Red Oficial vs PyPSA-Earth

Documento que registra el proceso de comparación entre la red oficial argentina y el modelo PyPSA-Earth,
y la decisión de migrar a GeoSADI + PSS/E como fuente de verdad.

---

## Objetivo

Construir un proceso reproducible para:
- Auditar la red oficial argentina
- Mapear líneas a un maestro curado de estaciones eléctricas
- Separar interconexiones internacionales
- Comparar estructuralmente contra PyPSA-Earth (OSM)

---

## Etapa 1 — Auditoría con datos de Secretaría de Energía (deprecado)

> **Nota:** Esta etapa trabajó con datos de la Secretaría de Energía.
> Fue reemplazada por GeoSADI a partir del 26/02/2026.
> Los scripts `scripts/qa_network/` están deprecados.

### Datos utilizados

**SHP oficial líneas AT:** `transporte-electrico-at-lineas-shp.shp`
- Total registros: 1.299 (1.247 LineString + 50 MultiLineString)

**Biblia de estaciones:** `official_stations_master.csv`
- 310 estaciones curadas
- Campos: `station_uid`, `station_name`, `source_id`, `lon`, `lat`, `tension_levels`, `status`

### Diagnóstico de matching por tensión

| Tensión | Mediana distancia endpoint → estación | Calidad |
|---------|---------------------------------------|---------|
| 500 kV | ~0.2 km | ✅ Muy bueno |
| 330 kV | ~0.1 km | ✅ Muy bueno |
| 132 kV | ~7 km | ⚠️ Necesita refinamiento |
| 220 kV | ~15–20 km | ❌ Problemático |
| 66/33 kV | muy altas | ❌ No representado |

### Problema identificado

El SHP oficial fragmenta corredores en múltiples tramos.
Ejemplo: Güemes – Formosa – Clorinda dividido en 3 segmentos.
Si falta una estación intermedia (ej: ESPINILLO), los tramos intermedios generan errores grandes.
No es error del algoritmo — es segmentación + cobertura incompleta del maestro.

---

## Etapa 2 — Migración a GeoSADI (26/02/2026)

Se obtuvo acceso completo al GeoSADI (CAMMESA):
https://www.arcgis.com/apps/instant/sidebar/index.html?appid=4b0ffba2055745a3afdbe1444d2db6d7

Layers disponibles en `.csv` y `.geojson`:
- `lineas_alta_tension`
- `estaciones_transformadoras`
- `centrales_electricas`

Se cargó un `.gpkg` de PyPSA-Earth AR junto al GeoSADI en QGIS para comparación visual.

---

## Comparación macro GeoSADI vs PyPSA-Earth (28/02/2026)

### Líneas

| | GeoSADI | PyPSA-Earth | Diferencia |
|---|---|---|---|
| Cantidad de líneas | 1.332 | 1.091 | PyPSA tiene 82% |
| Kilómetros totales | 53.129 km | 65.018 km | PyPSA sobrestima +22% |

- 33 kV y 150 kV no representados en PyPSA
- 500 kV es el nivel mejor representado (88% de circuitos)

### Transformadores — hallazgo crítico

| | GeoSADI | PyPSA-Earth | Cobertura |
|---|---|---|---|
| Total | 1.132 | 125 | **11%** |
| 132 kV | 895 | 31 | **3%** |

> Este hallazgo valida definitivamente la decisión de reemplazar OSM por GeoSADI.

### Generación

| | GeoSADI | PyPSA-Earth | Cobertura |
|---|---|---|---|
| Centrales | 436 | 80 | 18% |
| MW instalados | 48.099 MW | 21.732 MW | 45% |

- Nuclear: bien representado (3 reales vs 4 en PyPSA ≈ OK)
- Hidro: 12.153 MW ausentes en PyPSA
- Eólica: 4.390 MW ausentes en PyPSA
- Solar: 2.404 MW ausentes en PyPSA

> Nota: hidro/eólica/solar estaban ausentes también por decisión propia — no se corrió el step `elec.nc` con renovables.

---

## Decisión estratégica — Arrancar con red 500 kV

Se decide construir primero la red 500 kV completa antes de incorporar niveles menores.

Razones:
- Solo ~112 líneas y ~70 estaciones — escala manejable
- Nombres de líneas limpios, pocas abreviaturas problemáticas
- Es el backbone del SADI
- Problemas de snap geoespacial menores que en 132 kV

A partir de aquí: fuente PSS/E (topología + impedancias) + GeoSADI (coordenadas + geometría).
