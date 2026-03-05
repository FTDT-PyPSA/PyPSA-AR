# Data Directory – PyPSA-AR

This folder does NOT contain raw datasets.

The purpose of this directory is to:

- Store lightweight sample files (for testing)
- Document dataset structure
- Maintain metadata and data inventories
- Define expected schemas

---

## What DOES NOT go here

- Large CSV files
- NetCDF files
- Shapefiles
- ERA5 datasets
- Full PyPSA-Earth exports
- Model results

All heavy datasets are stored in shared Drive storage.

---

## Data Architecture

Drive (Data Lake) contains:

- data_raw/
- data_processed/
- results/

GitHub repository contains:

- Documentation
- Scripts
- Metadata


---

## Reproducibility Principle

Raw datasets are never modified manually.

---

This structure ensures:

- Transparency
- Version control of transformations
- Lightweight repository
- Reproducibility
