# PyPSA-AR — Auditoría Macro

GeoSADI (Red Real) vs PyPSA-Earth (OSM) — Febrero 2026

---

## 1. Líneas de Alta Tensión

Comparación de cantidad de circuitos y kilómetros totales por nivel de tensión.
Se excluyen los layers de Edenor y Edesur (distribución urbana AMBA, ~7.000 líneas adicionales)
por no ser comparables con el modelo de transporte nacional.

| Tensión (kV) | GeoSADI # Líneas | GeoSADI Km | PyPSA # Líneas | PyPSA Km | Cobertura # | Cobertura Km |
|---|---|---|---|---|---|---|
| 33 | 15 | 88 | 0 | 0 | 0% | 0% |
| 66 | 127 | 1.989 | 33 | 866 | 26% | 44% |
| 132 | 1.025 | 32.325 | 913 | 41.171 | 89% | 127% |
| 150 | 2 | 51 | 0 | 0 | 0% | 0% |
| 220 | 39 | 2.117 | 43 | 3.125 | 110% | 148% |
| 330 | 6 | 1.116 | 2 | 1.506 | 33% | 135% |
| 345 | 6 | 269 | 1 | 21 | 17% | 8% |
| 500 | 112 | 15.174 | 99 | 18.327 | 88% | 121% |
| **TOTAL** | **1.332** | **53.129** | **1.091** | **65.016** | **82%** | **122%** |

Referencia: ≥ 80% buena cobertura · 50–79% cobertura parcial · < 50% cobertura insuficiente

### Observaciones

- A nivel de conteo de circuitos PyPSA-Earth tiene 82% del total GeoSADI, lo cual parece razonable. Sin embargo en kilómetros sube al 122% — PyPSA sobrestima distancias en 500 kV y 132 kV, posiblemente por fragmentación OSM o ruteo diferente.
- Las tensiones 33 kV y 150 kV no están representadas en PyPSA-Earth.
- El nivel 330 kV tiene solo 2 circuitos en PyPSA vs 6 reales.
- El nivel 500 kV muestra la mejor cobertura relativa (88% de circuitos).

---

## 2. Transformadores

Los transformadores en GeoSADI representan posiciones de transformación en cada estación (una fila por transformador, con el nivel de tensión de alta). PyPSA-Earth modela transformadores como conexión entre buses de distinta tensión.

| Tensión Alta (kV) | GeoSADI # Trafos | PyPSA # Trafos | Cobertura | Brecha |
|---|---|---|---|---|
| 132 | 895 | 31 | 3% | 864 faltantes |
| 220 | 41 | 35 | 85% | 6 faltantes |
| 330 | 3 | 2 | 67% | 1 faltante |
| 345 | 5 | 2 | 40% | 3 faltantes |
| 500 | 70 | 55 | 79% | 15 faltantes |
| **TOTAL** | **1.014** | **125** | **12%** | **889 faltantes** |

### Observaciones

- La brecha es crítica: PyPSA-Earth tiene solo 125 transformadores vs 1.132 registros en GeoSADI (11% de cobertura). Es el hallazgo más significativo del análisis.
- En 132 kV PyPSA tiene 31 vs 895 reales — 3% de cobertura.
- Esta diferencia se explica porque PyPSA-Earth colapsa subestaciones complejas a 1–2 buses, eliminando toda la topología interna.
- El 500 kV es el mejor representado con 55 de 70 (79%).

---

## 3. Generación

> Nota: la corrida de PyPSA-Earth utilizada no incluyó generación renovable (hidro, eólica, solar)
> de forma intencional para simplificar el análisis topológico.
> Los datos de GeoSADI provienen del layer de centrales eléctricas (436 centrales, 48.099 MW instalados).

| Tecnología | GeoSADI Unidades | GeoSADI MW | PyPSA Unidades | PyPSA MW | Cob. MW | Estado |
|---|---|---|---|---|---|---|
| Hidro (HI/HB/HR) | 72 | 12.153 | — | — | — | Falta |
| CCGT / Vapor Gas (VG) | 24 | 10.281 | 65 | 16.838 | 164% | Agrupado |
| Turbina Gas (TG) | 68 | 9.260 | — | — | — | Agrupado |
| Vapor carbón/fuel (TV) | 26 | 6.170 | 1 | 240 | 4% | Parcial |
| Eólica (EO) | 71 | 4.390 | — | — | — | Falta |
| Solar FV (FV) | 69 | 2.404 | — | — | — | Falta |
| Nuclear (NU) | 3 | 1.755 | 4 | 1.792 | 102% | OK |
| Diesel/Oil (DI) | 102 | 1.685 | 10 | 2.861 | 170% | Agrupado |
| **TOTAL** | **435** | **48.098** | **80** | **21.731** | **45%** | |

### Observaciones

- PyPSA cubre solo el 45% de la potencia instalada real. La brecha se explica principalmente por la ausencia de hidro (12.153 MW), eólica (4.390 MW) y solar (2.404 MW).
- La térmica a gas (VG + TG) está parcialmente representada: PyPSA agrupa ambas en CCGT con 16.838 MW vs 19.541 MW reales — diferencia del 14%.
- Nuclear: 3 centrales reales (1.755 MW) vs 4 en PyPSA (1.792 MW). Diferencia menor, posiblemente por inclusión de CAREM o potencia nominal distinta.
- Vapor (TV): PyPSA tiene 240 MW (1 central) vs 6.170 MW reales — 4% de cobertura, muy subrepresentado.
- Diesel/Oil: PyPSA tiene 2.861 MW vs 1.685 MW reales — sobrestima 70%, posiblemente por unidades fuera de servicio incluidas en OSM.

---

## 4. Resumen ejecutivo

| Elemento | GeoSADI | PyPSA-Earth (OSM) | Cobertura |
|---|---|---|---|
| Líneas AT (circuitos) | 1.332 | 1.091 | 82% |
| Líneas AT (km) | 53.129 km | 65.018 km | +22% sobrest. |
| Transformadores | 1.132 | 125 | 11% |
| Generación (MW) | 48.099 MW (436 centrales) | 21.732 MW (80 unidades) | 45% (sin renov. ni hidro) |

### Conclusión

La topología de líneas de PyPSA-Earth (OSM) es razonablemente completa para los niveles ≥ 220 kV. Sin embargo el modelo de transformadores es gravemente insuficiente (11% de cobertura). Esto valida la decisión de reemplazar la fuente de datos por GeoSADI como input del pipeline PyPSA-AR.

### Próximos pasos (al momento del documento — Febrero 2026)

1. Limpiar y procesar los layers GeoSADI en formato compatible con PyPSA (buses, líneas, transformadores)
2. Inferir topología de transformadores a partir de estaciones con múltiples niveles de tensión
3. Resolver el problema de snap geoespacial
4. Incorporar generación hidro, eólica y solar desde fuentes oficiales CAMMESA/MINEM
