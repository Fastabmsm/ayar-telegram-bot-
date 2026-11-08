"""
Indicator V4.1 FINAL - Continuous Dynamic Emergency, No Overfit, No Future Look
Version: 4.1 FINAL
- Exposes atr_ratio for dynamic engine
- Same core as V3.6, version bump only
"""
import Indicator_V3_6 as base

VERSION = "4.1 FINAL"

def build(paths):
    return base.build(paths)

def dynamic_threshold_continuous(atr_ratio, regime):
    """Helper for documentation: linear 1.0->4% to 1.25->2%"""
    if regime == 2:  # DOWN
        return 0.0111454445420979
    atr = max(1.0, min(1.25, float(atr_ratio))) if not __import__('math').isnan(atr_ratio) else 1.0
    loss_pct = 0.04 - (atr - 1.0) / 0.25 * 0.02  # 4% at 1.0 down to 2% at 1.25
    return loss_pct
