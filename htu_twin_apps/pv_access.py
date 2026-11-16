"""HTU's transport-line settings, by machine-state key, live over EPICS or from recorded scans.

The same keys (`htu_twin_apps.machine_state.KEYS`, the settings) name a value wherever it is read:

- **live**, over EPICS PV Access: `Live(names)` with `get()` and `monitor()`. `names` maps a key to
  a PV name: `twin_name` for the HTU twin's server (`HTU:SIM:EMQ1H_Current`), or
  `machine_state.pv_name` for HTU's own IOCs through the GEECS gateway
  (`undulator:u_emqtripletbipolar:current_limit_ch1`), which is a matter of configuration;
- **recorded**, from a GEECS scan folder: `archive()`, each shot's logged settings.

PV Access only (`p4p`, installed with the HTU twin); Channel Access is not supported.

:copyright: Copyright (c) 2026 RadiaSoft LLC.  All Rights Reserved.
:license: http://www.apache.org/licenses/LICENSE-2.0.html
"""

from __future__ import annotations

import os
import typing

from htu_twin_apps import machine_state as htu_machine_state
from htu_twin_apps.lpa_source import scans as htu_scans

# How long a `get()` waits for a PV [s].
TIMEOUT_S = 5.0
# The prefix of the HTU twin's PVs (`htu.config_tool.DEFAULT_PREFIX`).
TWIN_PREFIX = "HTU:SIM:"
# The twin's variable for a setting, where it is not `<key>_Current`.
_TWIN_VARIABLES = {"chicane_current": "ChicaneDipole_Current"}


class Live:
    """Settings read live over EPICS PV Access, by machine-state key.

    Args:
        names: the PV name of a key (`twin_name`, or `machine_state.pv_name` for HTU's IOCs).
        timeout_s: how long a `get()` waits for its PV.
    """

    def __init__(
        self,
        names: typing.Callable[[str], str] | None = None,
        timeout_s: float = TIMEOUT_S,
    ):
        from p4p.client.thread import Context

        self._context = Context("pva")
        self._names = twin_name if names is None else names
        self._timeout_s = timeout_s

    def __enter__(self) -> Live:
        return self

    def __exit__(self, *args) -> None:
        self.close()

    def close(self) -> None:
        """Close the EPICS connections, and with them every monitor."""
        self._context.close()

    def get(self, key: str) -> float:
        """The current value of setting `key`.

        Raises:
            TimeoutError: If its PV does not answer within the timeout.
        """
        return float(self._context.get(self._name(key), timeout=self._timeout_s))

    def monitor(self, key: str, callback: typing.Callable[[str, float], None]):
        """Call `callback(key, value)` with the value of setting `key` now and on each change,
        until the returned subscription's `close()` (or this object's)."""

        def _update(value):
            if not isinstance(value, Exception):
                callback(key, float(value))

        return self._context.monitor(self._name(key), _update)

    def _name(self, key: str) -> str:
        k = htu_machine_state.KEYS.get(key)
        if k is None or k.kind != htu_machine_state.SETTING:
            raise ValueError(f"{key!r} is not a setting")
        return self._names(key)


def archive(day_folder: str | os.PathLike, scan: str) -> list[dict[str, float]]:
    """Each shot's logged settings in `scan` (such as `Scan025`) of the day folder `day_folder`
    (`htu_twin_apps.days.folder()`), with its step as `step`: the values an archiver would hold.
    A setting the scan does not log is absent. (`machine_state.from_geecs()` makes one state of
    a step's shots: their medians, and the nominal value of an unlogged EMQ.)"""
    _, rows = htu_scans.table(day_folder, scan)
    rv = []
    for row, step in zip(rows, htu_scans.step_numbers(rows)):
        s = {"step": step}
        for k, v in htu_machine_state.KEYS.items():
            if v.geecs is not None:
                x = htu_scans.number(row.get(v.geecs))
                if x is not None:
                    s[k] = x
        rv.append(s)
    return rv


def twin_name(key: str) -> str:
    """The HTU twin's PV for setting `key` (`htu.model`'s variable for it, under TWIN_PREFIX)."""
    return TWIN_PREFIX + _TWIN_VARIABLES.get(key, f"{key}_Current")
