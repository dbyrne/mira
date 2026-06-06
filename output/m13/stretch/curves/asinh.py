"""asinh -- baseline. M57 (bright planetary) wants HIGH a (gentle, highlight-protecting)
to hold the bright ring back from white so its OIII-teal / H-alpha-red color survives.
My hand-tuned M57 final used a~0.17."""
import numpy as np

DEFAULTS = {"a": 0.17}
SWEEP = [{"a": 0.08}, {"a": 0.15}, {"a": 0.25}, {"a": 0.4}]


def apply(x, a=0.17):
    return np.arcsinh(x / a) / np.arcsinh(1.0 / a)
