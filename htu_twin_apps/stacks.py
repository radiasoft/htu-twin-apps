"""HTU device stacks matched to a scan's shots, shared by the apps.

A device stack (`<device>/<device>.h5`, dataset `entry/data/data`) holds one frame per saved shot,
with its acquisition time in `entry/instrument/NDAttributes/*frame_acq_timestamp` (Unix seconds).
The scan's scalar table has one row per shot, with the device's `<device> acq_timestamp` in
LabVIEW time (seconds since 1904). A frame belongs to the row whose time is within
TIMESTAMP_TOLERANCE_S of it.

:copyright: Copyright (c) 2026 RadiaSoft LLC.  All Rights Reserved.
:license: http://www.apache.org/licenses/LICENSE-2.0.html
"""

from __future__ import annotations

import math
import numpy

# Seconds from the LabVIEW epoch (1904-01-01) to the Unix epoch (1970-01-01).
LABVIEW_EPOCH_OFFSET_S = 2_082_844_800.0
# How far apart, in seconds, a frame's and a shot's timestamps may be and still match.
TIMESTAMP_TOLERANCE_S = 0.05


def match(frame_times, table_times) -> list[int]:
    """For each table row, the index of the frame taken within TIMESTAMP_TOLERANCE_S of it, or -1.

    Args:
        frame_times: the stack's frame acquisition times (Unix seconds).
        table_times: the rows' `<device> acq_timestamp` (LabVIEW seconds); None or NaN for a row
            without one.
    """
    f = numpy.asarray(frame_times, dtype=numpy.float64)
    o = numpy.argsort(f)
    s = f[o]

    def _frame(t):
        if t is None or not math.isfinite(t) or f.size == 0:
            return -1
        u = t - LABVIEW_EPOCH_OFFSET_S
        i = int(numpy.searchsorted(s, u))
        k = min((k for k in (i - 1, i) if 0 <= k < f.size), key=lambda k: abs(s[k] - u))
        return int(o[k]) if abs(s[k] - u) <= TIMESTAMP_TOLERANCE_S else -1

    return [_frame(t) for t in table_times]
