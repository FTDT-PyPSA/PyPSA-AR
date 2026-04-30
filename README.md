# PyPSA-AR

Reproducible model of the Argentine high-voltage power grid using PyPSA.

**Current status:** Scripts 01–22 complete. 500 kV network built, 2024 hourly generation and demand incorporated, marginal costs assigned with CAMMESA-derived efficiencies, DC economic dispatch validated, and future-year scenario pipeline (clustering + capacity expansion + dispatch) operational with first 2035 BAU scenario produced.
**Next phase:** PYPSA-AR — integration of 220 kV and 132 kV nodes over the existing 500 kV network.


---

## Objective

Build a calibrated model of the SADI (Argentine Interconnection System) that allows:
- Replicating the 2024 historical dispatch against CAMMESA data
- Analyzing transmission constraints
- Serving as a base for expansion and energy policy scenarios

Strategy: build level by level (500 kV → 220/330 kV → 132 kV), validating each level before moving on.

---

## Working environment

### Why WSL + Windows

The project uses **WSL (Ubuntu)** to run the scripts and **Windows (Cursor or VSCode)** to edit them.
This combination is intentional:

- PyPSA and its dependencies (especially linear solvers) run more stably on Linux
- The `pypsa-earth-lock` environment pins all library versions to guarantee reproducibility across team machines
- Cursor and VSCode on Windows integrate with WSL without friction

**Do not use Windows Python or a parallel venv** — the scripts assume the WSL conda environment.

### Environment setup

1. Have WSL installed with Ubuntu.

2. Install miniforge in WSL:
```bash
wget https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-x86_64.sh
bash Miniforge3-Linux-x86_64.sh
```

3. Clone the repository:
```bash
git clone https://github.com/FTDT-PyPSA/PyPSA-AR.git
cd PyPSA-AR
```

4. Create the environment from the repo file:
```bash
conda env create -f environment.yml
conda activate pypsa-earth-lock
```

5. Verify the correct Python:
```bash
which python
# should show: /home/<user>/miniforge3/envs/pypsa-earth-lock/bin/python
```

### Configure paths

Before running any script, edit **`config.yaml`** at the repo root:

```yaml
repo_dir:          /local/path/to/repo        # root of the cloned repo
external_data_dir: /path/to/external_data
```

External data files (CAMMESA, GeoSADI, PSS/E, CVP) are downloaded from:

> **https://github.com/FTDT-PyPSA/PyPSA-AR/releases/tag/v1.0-data**

Extract them maintaining the folder structure indicated in the release notes.
Once `config.yaml` is configured, no script requires path editing.

---

## 500 kV pipeline

All scripts are run from the repository root, in order:

```bash
# 500 kV network construction
python scripts/network_500kv/01_parse_raw_buses.py
python scripts/network_500kv/02_parse_raw_lines.py
python scripts/network_500kv/03_parse_raw_transformers.py
python scripts/network_500kv/04_parse_raw_buses_sec.py
python scripts/network_500kv/05_match_geosadi_coords.py
python scripts/network_500kv/06_match_geosadi_geometry.py
python scripts/network_500kv/07_validate_topology.py
python scripts/network_500kv/07b_export_qgis.py
python scripts/network_500kv/08_build_network.py

# Generation and demand mapping
python scripts/network_500kv/09_map_generators.py
python scripts/network_500kv/10_map_loads.py
python scripts/network_500kv/10b_visualize_qgis.py
python scripts/network_500kv/11_add_geo_to_generators.py
# → complete generators_pendingmanualpypsa.csv before continuing,
#   or use generators_manualpypsa.csv already versioned in data/network_500kv/
python scripts/network_500kv/12_build_generators_final.py
python scripts/network_500kv/12b_export_qgis_generators.py

# Real 2024 data — require external files (not versioned in git)
python scripts/network_500kv/13_clean_valores_2024.py
python scripts/network_500kv/14_detect_generator_conflicts.py
# → complete conflicts_psse_cammesa.csv before continuing
python scripts/network_500kv/14b_build_generators_2024.py
python scripts/network_500kv/15_build_loads_2024.py
python scripts/network_500kv/16_snapshot_dc_peak2024.py   # DC peak demand validation
python scripts/network_500kv/17_build_gen_profiles_2024.py

# Marginal costs — require external CVP files (not versioned in git)
python scripts/network_500kv/18_diagnose_marginal_costs.py
# → complete CVP_manual column in marginal_costs_diagnostic.csv before continuing
python scripts/network_500kv/18b_build_marginal_costs_2024.py

# Economic dispatch — configure START_DATE, END_DATE and CHUNK_DAYS in the script before running
python scripts/network_500kv/19_run_optimization.py

# Network simplification + clustering — required before scenarios
python scripts/network_500kv/20A_simplify_network.py
python scripts/network_500kv/20B_network_clustering.py

# Future-year scenarios — require external ATB cost file and fuel YAMLs (not versioned in git)
python scripts/network_500kv/21_build_scenario.py
python scripts/network_500kv/22_run_scenario.py
```

## Team

| Name | Role |
|------|------|
| Gustavo Barbaran | Project lead |
| Gustavo Ramirez | Data and network modeling |
| Juan Manuel Bregman | Programming and pipeline |

---

## Documentation

See the `docs/` folder for:
- `roadmap.md` — project status and phases
- `architecture.md` — model design
- `data_sources.md` — data sources and status
- `aprendizaje_pypsaearth_ar.md` — why PyPSA-Earth was abandoned
- `auditoria_macro_geosadi_vs_pypsa.md` — quantitative comparison GeoSADI vs OSM
- `auditoria_red_oficial_vs_pypsa.md` — audit process and decision to migrate to GeoSADI
