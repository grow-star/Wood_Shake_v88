#!/usr/bin/env python3
"""Facet basis helpers for production geometry intake."""

from __future__ import annotations

from typing import Sequence, Tuple

import numpy as np

Point3 = Tuple[float, float, float]


def facet_fall_xy(points3d: Sequence[Point3]) -> Tuple[float, float]:
    """Return the world-XY downslope vector for an ordered facet vertex loop."""
    # Deliberately mirrors mkframe_pts' internal normal/fall basis so it can later be merged into the sealed engine.
    pp = [np.array(p, dtype=float) for p in points3d]
    nrm = np.zeros(3, dtype=float)
    for i in range(len(pp)):
        nrm += np.cross(pp[i], pp[(i + 1) % len(pp)])
    nrm /= np.linalg.norm(nrm)
    if nrm[2] < 0:
        nrm = -nrm
    g = np.array([0.0, 0.0, -1.0])
    fall = g - np.dot(g, nrm) * nrm
    return (float(fall[0]), float(fall[1]))
