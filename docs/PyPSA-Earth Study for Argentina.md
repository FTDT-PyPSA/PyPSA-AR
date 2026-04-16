# PyPSA-Earth Study for Argentina

Study conducted to understand what PyPSA-Earth models when configured for Argentina (`config.yaml [AR]`).
This document justifies the decision to replace OSM data with GeoSADI + PSS/E.

---

## PyPSA-Earth pipeline conclusions

| | |
|---|---|
| ✅ | Pipeline works correctly and is reproducible |
| ✅ | Real voltage levels are preserved (including 500 kV) |
| ✅ | Physical topology does not change between `base_network` and `add_electricity` |
| ❌ | Lines have no active impedances (r = 0, x = 0) |
| ❌ | Electrical losses are not modeled |
| ⚠️ | The network comes from OpenStreetMap and fragments trunk corridors |
| ⚠️ | 500 kV lines use a European conductor type (380 kV) |

---

## Final state of the AR model (up to the `add_electricity` step)

```
976  buses
1091 lines
125  transformers
851  loads
80   generators
```

Voltage levels present: 35, 66, 132, 220, 330, 345, 500 kV

### Note on 500 kV lines

500 kV lines use type: `Al/St 240/40 4-bundle 380.0`

- ✅ Correct nominal voltage
- ⚠️ Approximate electrical parameters
- ⚠️ European conductors used as reference

**No power flow dispatch by reactance.**
This is a transport model with capacity limits, not a physical AC model of the SADI.

---

## PyPSA-Earth pipeline step by step

### 1. `download_osm_data`
Downloads raw data from OpenStreetMap: lines, substations, generators, cables.
- ✅ Geographic raw material
- ❌ Not yet a structured power network

### 2. `clean_osm_data`
Cleans and filters OSM data. Removes inconsistencies and normalizes tags.
- ✅ Usable dataset
- ❌ No electrical parameters yet

### 3. `build_shapes`
Builds the country's geographic boundaries. Defines what falls within Argentina.
- ✅ Spatial clipping
- ❌ Does not affect electrical parameters

### 4. `build_osm_network`
Converts clean OSM data into structured tables:
- `all_buses_build_network.csv`
- `all_lines_build_network.csv`
- `all_transformers_build_network.csv`

Voltage, bus0/bus1, and geometry appear here.
- ✅ Topology defined
- ✅ Original voltage preserved
- ❌ No impedances

### 5. `base_network`
Builds `base.nc`.
- ✅ Creates structural network (buses, lines, transformers)
- ✅ Assigns line type by voltage level
- ✅ Calculates thermal capacity (s_nom)

> Real impedances could be incorporated here (`r = r_per_km × length`, `x = x_per_km × length`),
> which would enable a DC model with realistic physics, approximate losses, and reactance-based dispatch.
> This would not break the pipeline.

### 6. `retrieve_cost_data`
Downloads economic and technological parameters.
- ✅ Required for generation
- ❌ Does not affect network physics

### 7. `build_powerplants`
Builds the existing generation inventory.
- ✅ Adds real power plants
- ❌ Does not modify lines

### 8. `build_demand_profiles`
Generates hourly demand profiles.
- ✅ Loads are added
- ❌ Does not modify topology

Internal demand flow:
1. Downloads data from https://unstats.un.org/unsd/energy/balance/
2. Creates country-level totals
3. Generates hourly profile based on the number of configured snapshots
4. Builds regions around each bus
5. Allocates demand proportionally using a population density raster

### 9. `add_electricity`
Generates `elec.nc`.
- ✅ Adds loads, generators, storage
- ❌ Does not modify the physical network
- ❌ Does not activate impedances
