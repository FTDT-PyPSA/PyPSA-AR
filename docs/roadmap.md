# PyPSA-AR Roadmap

Objetivo: modelo calibrado y reproducible de la red eléctrica argentina usando PyPSA.

Estrategia de construcción: arrancar con la red 500 kV completa y cerrarla antes de
incorporar niveles de tensión inferiores. Cada nivel se valida antes de avanzar al siguiente.

---

## Fase 0 — Repositorio y estructura ✅ COMPLETADA

- Repositorio GitHub inicializado
- Estructura de carpetas definida
- Documentación base creada
- Entorno reproducible configurado (pypsa-earth-lock en WSL)

---

## Fase 1 — Auditoría PyPSA-Earth para Argentina ✅ COMPLETADA

Objetivo: entender qué modelaba PyPSA-Earth para AR y decidir si reutilizar o reemplazar.

Resultado: se decidió reemplazar toda la data de OSM por GeoSADI + PSS/E.
Razones documentadas en `Aprendizaje_pypsaearth_ar.txt`.

Hallazgos clave:
- PyPSA-Earth tiene 125 transformadores vs 1.132 reales (11% cobertura)
- Líneas 500 kV con tipo de conductor europeo (380 kV)
- Sin impedancias activas (r=0, x=0)

---

## Fase 2 — Construcción red 500 kV ✅ EN CURSO

Fuentes: GeoSADI (geometría) + PSS/E ver2526pid.raw (topología e impedancias)

Scripts desarrollados:

| Script | Descripción | Estado |
|--------|-------------|--------|
| 01_parse_raw_buses.py | Extrae buses 500 kV del PSS/E | ✅ |
| 02_parse_raw_lines.py | Extrae líneas 500 kV del PSS/E | ✅ |
| 03_match_geosadi_coords.py | Asigna coordenadas GeoSADI a buses | ✅ |
| 04_match_geosadi_geometry.py | Asigna geometría WKT a líneas | ✅ |
| 05_validate_topology.py | Valida topología de la red | ✅ |
| 05b_export_qgis.py | Exporta a GeoPackage para QGIS | ✅ |
| 06_build_pypsa_network.py | Construye objeto PyPSA Network | 🔲 |

Estado actual de la red 500 kV:
- 96 buses (94 OK, 2 CONSULTAR: T PEPE y R9B5RS)
- 122 líneas (114 en servicio, 8 fuera de servicio en este snapshot)
- 15 compensadores serie
- sin_match = 0 en geometría
- Red principal: 92 buses en una componente conexa

Pendientes antes de cerrar la fase:
- Check visual en QGIS
- Script 06: construir objeto PyPSA con impedancias reales

---

## Fase 3 — Generación y demanda 500 kV 🔲 PENDIENTE

Objetivo: incorporar generación y demanda únicamente para la red 500 kV y que cierre.


Tareas:
- Mapear centrales eléctricas a buses 500 kV
- Asignar perfiles de demanda por nodo
- Correr simulación y verificar que la red converge

---

## Fase 4 — Incorporar niveles 220, 330, 132 kV 🔲 PENDIENTE

Mismo pipeline que 500 kV, nivel por nivel.
Scripts 01-05 son reutilizables con distintos filtros de tensión.
Incorporar transformadores inter-nivel.

---

## Fase 5 — Generación y demanda completas 🔲 PENDIENTE

- 436 centrales del GeoSADI (hidro, eólica, solar incluidas)
- Perfiles horarios 8760h año base 2024
- Datos CAMMESA

---

## Fase 6 — Calibración año base 2024 🔲 PENDIENTE

- Simulación completa 8760h
- Comparar despacho simulado vs CAMMESA por tecnología
- Ajustar costos variables hasta match ±5%
- Validar límites de transmisión

Fecha límite del proyecto: 30/04/2026
