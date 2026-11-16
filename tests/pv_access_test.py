"""Tests for `htu_twin_apps.pv_access`: live, against the HTU twin's own PV server; recorded, against
a GEECS scan folder.

The live tests need the twin (`htu`) and `p4p`; they start `python -m htu.serve` and are skipped
without them. The recorded test needs HTU's data: set `HTU_DATA_ROOT` to the folder holding
`Y2026` (HTU's `Undulator`); it is skipped otherwise.
"""

from __future__ import annotations

import os
import statistics
import subprocess
import sys
import threading
import time

import pytest

# The twin's server builds the twin before serving (a few seconds), and the first read of a PV
# can wait for its first update.
_SERVER_START_S = 120.0


@pytest.fixture(scope="module")
def twin_server():
    pytest.importorskip("htu.serve")
    pytest.importorskip("p4p")
    from htu_twin_apps import pv_access

    process = subprocess.Popen(
        [sys.executable, "-m", "htu.serve"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        with pv_access.Live(timeout_s=2.0) as live:
            end = time.monotonic() + _SERVER_START_S
            while True:
                if process.poll() is not None:
                    pytest.fail(f"htu.serve exited with {process.returncode}")
                try:
                    # a PV reads 0 until the server's first update; the twin's EMQ1H is not 0
                    if live.get("EMQ1H") != 0.0:
                        break
                except TimeoutError:
                    pass
                if time.monotonic() > end:
                    pytest.fail("htu.serve did not serve its PVs in time")
                time.sleep(0.5)
        yield process
    finally:
        process.terminate()
        process.wait(timeout=30)


def test_every_setting_has_its_twin_variable():
    htu_model = pytest.importorskip("htu.model")
    from htu_twin_apps import machine_state, pv_access

    variables = htu_model.build_htu_model().supported_variables
    for key, value in machine_state.KEYS.items():
        if value.kind == machine_state.SETTING:
            name = pv_access.twin_name(key).removeprefix(pv_access.TWIN_PREFIX)
            assert variables[name].key == key, key


def test_a_live_setting_is_the_twins_value(twin_server):
    htu_model = pytest.importorskip("htu.model")
    from htu_twin_apps import pv_access

    with pv_access.Live() as live:
        value = live.get("EMQ1H")

    # the twin holds its values as float32
    assert value == pytest.approx(htu_model.DEFAULT_MACHINE_STATE["EMQ1H"], rel=1e-6)


def test_a_monitor_sees_a_put(twin_server):
    from p4p.client.thread import Context

    from htu_twin_apps import pv_access

    seen = []
    changed = threading.Event()

    def _seen(key, value):
        seen.append((key, value))
        if value == pytest.approx(0.25, rel=1e-6):
            changed.set()

    with pv_access.Live() as live, Context("pva") as writer:
        subscription = live.monitor("EMQ2V", _seen)
        try:
            writer.put(pv_access.twin_name("EMQ2V"), 0.25, timeout=60.0)
            assert changed.wait(30.0), seen
        finally:
            subscription.close()
            writer.put(
                pv_access.twin_name("EMQ2V"),
                pytest.importorskip("htu.model").DEFAULT_MACHINE_STATE["EMQ2V"],
                timeout=60.0,
            )

    assert seen[0][0] == "EMQ2V"


def test_only_a_setting_can_be_read_live(twin_server):
    from htu_twin_apps import pv_access

    with pv_access.Live() as live:
        with pytest.raises(ValueError, match="not a setting"):
            live.get("emq1_scale")


def test_a_recorded_scan_gives_each_shots_settings():
    root = os.environ.get("HTU_DATA_ROOT")
    if not root:
        pytest.skip("HTU_DATA_ROOT is not set")
    from htu_twin_apps import days, machine_state, pv_access
    from htu_twin_apps.lpa_source import scans

    folder = days.folder("26_0929", root)
    shots = pv_access.archive(folder, "Scan023")
    _, rows = scans.table(folder, "Scan023")

    assert len(shots) == len(rows)
    assert sorted({s["step"] for s in shots}) == list(range(1, 16))
    # the shots of a step agree with that step's machine state
    step = [r for r, s in zip(rows, shots) if s["step"] == 1]
    state = machine_state.from_geecs(step)
    assert state["EMQ1H"] == statistics.median(
        s["EMQ1H"] for s in shots if s["step"] == 1
    )
