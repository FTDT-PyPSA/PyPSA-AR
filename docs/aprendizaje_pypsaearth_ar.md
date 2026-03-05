# Aprendizaje PyPSA-Earth para Argentina

Estudio realizado para entender qué tiene modelado PyPSA-Earth cuando se configura `config.yaml [AR]`.
Este documento justifica la decisión de reemplazar los datos de OSM por GeoSADI + PSS/E.

---

## Conclusiones del pipeline PyPSA-Earth

| | |
|---|---|
| ✅ | Pipeline funciona correctamente y es reproducible |
| ✅ | Se conservan los niveles reales de tensión (incluido 500 kV) |
| ✅ | La topología física no cambia entre `base_network` y `add_electricity` |
| ❌ | Las líneas no tienen impedancias activas (r = 0, x = 0) |
| ❌ | No se modelan pérdidas eléctricas |
| ⚠️ | La red proviene de OpenStreetMap y fragmenta corredores troncales |
| ⚠️ | Las líneas 500 kV usan tipo de conductor europeo (380 kV) |

---

## Estado final del modelo AR (hasta el step `add_electricity`)

```
976  buses
1091 líneas
125  transformadores
851  cargas
80   generadores
```

Niveles de tensión presentes: 35, 66, 132, 220, 330, 345, 500 kV

### Observación sobre líneas 500 kV

Las líneas 500 kV usan tipo: `Al/St 240/40 4-bundle 380.0`

- ✅ Voltaje nominal correcto
- ⚠️ Parámetros eléctricos aproximados
- ⚠️ Conductores europeos como referencia

**No existe reparto por reactancia.**
Es un modelo de transporte con capacidad, no un modelo AC físico del SADI.

---

## Pipeline de PyPSA-Earth paso a paso

### 1. `download_osm_data`
Descarga datos crudos desde OpenStreetMap: líneas, subestaciones, generadores, cables.
- ✅ Materia prima geográfica
- ❌ No es todavía una red eléctrica estructurada

### 2. `clean_osm_data`
Limpia y filtra datos OSM. Elimina inconsistencias y normaliza tags.
- ✅ Dataset usable
- ❌ Aún no hay parámetros eléctricos

### 3. `build_shapes`
Construye límites geográficos del país. Define qué entra dentro de Argentina.
- ✅ Recorte espacial
- ❌ No afecta parámetros eléctricos

### 4. `build_osm_network`
Convierte datos OSM limpios en tablas estructuradas:
- `all_buses_build_network.csv`
- `all_lines_build_network.csv`
- `all_transformers_build_network.csv`

Aparece: voltage, bus0/bus1, geometría.
- ✅ Se define topología
- ✅ Se conserva voltaje original
- ❌ No hay impedancias

### 5. `base_network`
Construye `base.nc`.
- ✅ Crea red estructural (buses, líneas, transformadores)
- ✅ Asigna tipo de línea según voltaje
- ✅ Calcula capacidad térmica (s_nom)

> Aquí podrían incorporarse impedancias reales (`r = r_por_km × length`, `x = x_por_km × length`),
> lo que permitiría modelo DC con física realista, pérdidas aproximadas y reparto por reactancia.
> No rompe el pipeline.

### 6. `retrieve_cost_data`
Descarga parámetros económicos y tecnológicos.
- ✅ Necesario para generación
- ❌ No afecta física de red

### 7. `build_powerplants`
Construye inventario de generación existente.
- ✅ Agrega plantas reales
- ❌ No modifica líneas

### 8. `build_demand_profiles`
Genera perfiles horarios de demanda.
- ✅ Se agregan cargas
- ❌ No modifica topología

Flujo interno de la demanda:
1. Descarga datos de https://unstats.un.org/unsd/energy/balance/
2. Crea totales por país
3. Genera perfil horario según cantidad de snapshots configurados
4. Construye regiones alrededor de cada bus
5. Reparte la demanda por raster de densidad poblacional

### 9. `add_electricity`
Genera `elec.nc`.
- ✅ Agrega loads, generadores, storage
- ❌ No modifica red física
- ❌ No activa impedancias
