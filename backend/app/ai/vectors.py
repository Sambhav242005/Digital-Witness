"""Finite normalized vectors shared by retrieval adapters."""
import math


def normalize(vector, dimension=768):
    values = [float(x) for x in vector]
    if len(values) != dimension or not all(math.isfinite(x) for x in values):
        raise ValueError("Embedding has invalid dimensions or non-finite values")
    norm = math.hypot(*values)
    if not math.isfinite(norm) or norm <= 0:
        raise ValueError("Embedding has invalid norm")
    return [x / norm for x in values]
