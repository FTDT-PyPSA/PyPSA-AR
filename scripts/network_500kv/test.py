
"""
python scripts/network_500kv/test.py
"""
import pypsa
import pandas as pd

n = pypsa.Network('networks/scenarios/results_2035_BAU_k10/results_2035_BAU_k10.nc')

print("="*60)
print("DIAGNOSTIC: where do the 1,549 TWh come from?")
print("="*60)

print(f"\nNumber of snapshots          : {len(n.snapshots)}")
print(f"Sum of weightings (objective): {n.snapshot_weightings.objective.sum():.1f}  (should be 8760-8784)")
print(f"Mean weighting               : {n.snapshot_weightings.objective.mean():.2f}")

print(f"\n--- Demand check ---")
load_p = n.loads_t.p_set
print(f"loads_t.p_set shape          : {load_p.shape}")
print(f"Mean demand across snapshots : {load_p.sum(axis=1).mean():,.0f} MW")
print(f"Peak demand                  : {load_p.sum(axis=1).max():,.0f} MW")
print(f"Min demand                   : {load_p.sum(axis=1).min():,.0f} MW")

print(f"\n--- Integration ---")
raw_sum = float(load_p.sum().sum())
weighted_sum = float(load_p.multiply(n.snapshot_weightings.objective, axis=0).sum().sum())
print(f"Raw sum (no weights)         : {raw_sum:>15,.0f} MWh")
print(f"Weighted sum                 : {weighted_sum:>15,.0f} MWh")
print(f"Expected ~180 TWh            : {180_000_000:>15,.0f} MWh")

print(f"\n--- Weighting distribution ---")
print(n.snapshot_weightings.objective.describe())