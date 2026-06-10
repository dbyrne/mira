"""mtf -- PixInsight midtones transfer function. x=m -> 0.5; smaller m lifts faints harder."""
import numpy as np

DEFAULTS = {"m": 0.12}
SWEEP = [{"m": 0.05}, {"m": 0.08}, {"m": 0.12}, {"m": 0.2}]


def apply(x, m=0.12):
    return ((m - 1.0) * x) / ((2.0 * m - 1.0) * x - m)
