"""HTU's transport-line machine state: one representation, independent of the simulator.

A machine state is a dict of named values (`KEYS`), of two kinds:

- **settings**, logged by GEECS for each shot: magnet currents. `from_geecs()` reads them from a
  scan step's rows, and `pv_name()` gives each one's EPICS name.
- **corrections**, fitted to the recorded scans and not logged: magnet scales, EMQ and PMQ offsets,
  the slit's effective jaws and blade (`htu_twin_apps/twin_viewer/fits/`).

`to_twin()` joins a step's settings and the corrections into the state a simulator takes. The keys
are the HTU twin's own (`htu.model.DEFAULT_MACHINE_STATE`) where the twin has them; how a
correction acts on a simulator is that simulator's business (for the twin,
`htu_twin_apps.lpa_source.twin.to_spectrometer`). The representation covers the transport line
only: the LPA's inputs (laser, gas) are not logged as PVs.

:copyright: Copyright (c) 2026 RadiaSoft LLC.  All Rights Reserved.
:license: http://www.apache.org/licenses/LICENSE-2.0.html
"""

from __future__ import annotations

import math
import re
import statistics
import typing

# A correction: fitted, not logged.
CORRECTION = "correction"
# The EMQ triplet's channels, in beam order.
EMQ = ("EMQ1H", "EMQ2V", "EMQ3H")
# The GEECS experiment the transport line's devices are in: the first part of their EPICS names.
EXPERIMENT = "undulator"
# A setting: logged by GEECS for each shot.
SETTING = "setting"


class Key(typing.NamedTuple):
    """One value of the machine state."""

    # SETTING or CORRECTION
    kind: str
    # the unit of the value (1 for a ratio)
    unit: str
    # what it is
    description: str
    # the scan-table column it is logged as (`Device Variable`), for a setting
    geecs: str | None = None
    # the value when a scan does not log it, if there is one
    nominal: float | None = None


def _settings() -> dict[str, Key]:
    rv = {
        "chicane_current": Key(
            SETTING, "A", "chicane dipoles' current", "U_ChicaneInner Current"
        ),
    }
    # POSIT: HTU's nominal EMQ setpoints on 2026-09-29, as logged in Scan022 and given in the
    # data's README; an EMQ scan logs only the channel it scans, and a scan that logs a channel
    # (Scan019 logs all three, at 0) uses its own value
    for i, (k, n) in enumerate(zip(EMQ, (1.5, -0.82, 0.0)), 1):
        rv[k] = Key(
            SETTING,
            "A",
            f"EMQ triplet channel {i}'s current limit",
            f"U_EMQTripletBipolar Current_Limit.Ch{i}",
            n,
        )
    for i in range(1, 5):
        for p in "HV":
            rv[f"S{i}{p}"] = Key(
                SETTING, "A", f"steerer S{i}{p}'s current", f"U_S{i}{p} Current"
            )
    for i in range(1, 9):
        for p in "HV":
            rv[f"VS{i}{p}"] = Key(
                SETTING, "A", f"steerer VS{i}{p}'s current", f"U_VS{i}{p} Current"
            )
    return rv


def _corrections() -> dict[str, Key]:
    rv = {}
    for i, m in enumerate(EMQ, 1):
        rv[f"emq{i}_scale"] = Key(CORRECTION, "1", f"{m}'s strength over the twin's")
        for a in "xy":
            rv[f"emq{i}_{a}_mm"] = Key(CORRECTION, "mm", f"{m}'s {a} offset")
    rv["s1h_scale"] = Key(CORRECTION, "1", "S1H's strength over the twin's")
    for a in "xyz":
        rv[f"pmq_{a}_mm"] = Key(CORRECTION, "mm", f"PMQ triplet's {a} offset")
    rv["pmq_scale"] = Key(CORRECTION, "1", "every PMQ's gradient over the twin's")
    for i in (1, 2, 3):
        rv[f"pmq{i}_roll_deg"] = Key(CORRECTION, "deg", f"PMQ {i}'s roll")
        for a in "xy":
            rv[f"pmq{i}_d{a}_mm"] = Key(
                CORRECTION, "mm", f"PMQ {i}'s {a} offset in the triplet"
            )
    for i in (1, 2):
        rv[f"chicane_jaw{i}_mm"] = Key(CORRECTION, "mm", f"chicane slit jaw {i}'s edge")
    for e in ("low", "high"):
        rv[f"slit_blade_{e}_mm"] = Key(
            CORRECTION, "mm", f"chicane slit blade's {e} edge"
        )
    return rv


# Every key of the machine state, by name.
KEYS = {**_settings(), **_corrections()}


def from_geecs(rows: typing.Iterable[dict]) -> dict[str, float]:
    """The settings of one scan step, from its rows of the scan table (`Device Variable` columns):
    each logged setting's median over the step's shots, and the nominal value of a setting with
    one that the step does not log."""
    rows = list(rows)
    rv = {k: v.nominal for k, v in KEYS.items() if v.nominal is not None}
    for k, v in KEYS.items():
        if v.geecs is None:
            continue
        x = [y for y in (_number(r.get(v.geecs)) for r in rows) if y is not None]
        if x:
            rv[k] = statistics.median(x)
    return rv


def pv_name(key: str) -> str:
    """The EPICS name of setting `key`, as GEECS's gateway builds it: `experiment:device:variable`,
    each part lowercased and every character but letters, digits and `_` replaced by `_`.

    Raises:
        ValueError: If `key` is not a setting.
    """
    k = KEYS.get(key)
    if k is None or k.geecs is None:
        raise ValueError(f"{key!r} is not a logged setting")
    return ":".join(
        re.sub(r"[^a-z0-9_]", "_", p.lower())
        for p in (EXPERIMENT, *k.geecs.split(" ", 1))
    )


def to_twin(settings: dict, corrections: dict) -> dict[str, float]:
    """The machine state a simulator takes: `settings` (`from_geecs()`) with `corrections`.

    Raises:
        ValueError: If a key is unknown, or of the other kind.
    """
    for given, kind in ((settings, SETTING), (corrections, CORRECTION)):
        u = sorted(k for k in given if k not in KEYS or KEYS[k].kind != kind)
        if u:
            raise ValueError(f"not {kind} keys: {u}")
    return {**settings, **corrections}


def _number(text: typing.Any) -> float | None:
    """`text` as a finite float, or None."""
    try:
        rv = float(text)
    except (TypeError, ValueError):
        return None
    return rv if math.isfinite(rv) else None
