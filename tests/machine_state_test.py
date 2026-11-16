"""Tests for `htu_twin_apps.machine_state`."""

from __future__ import annotations

import json
import pathlib

import pytest


def test_a_setting_is_the_median_of_its_logged_values():
    from htu_twin_apps import machine_state

    rows = [
        {"U_S1H Current": "0.1", "U_ChicaneInner Current": "2.0"},
        {"U_S1H Current": "0.3", "U_ChicaneInner Current": "nan"},
        {"U_S1H Current": "0.2", "U_ChicaneInner Current": ""},
    ]

    state = machine_state.from_geecs(rows)

    assert state["S1H"] == pytest.approx(0.2)
    # an unreadable or non-finite value is left out, not taken as 0
    assert state["chicane_current"] == 2.0
    # a setting that is not logged at all is not in the state
    assert "S1V" not in state


def test_an_unlogged_emq_takes_its_nominal_value_and_a_logged_one_its_own():
    from htu_twin_apps import machine_state

    state = machine_state.from_geecs([{"U_EMQTripletBipolar Current_Limit.Ch2": "0.0"}])

    assert state["EMQ1H"] == 1.5
    assert state["EMQ2V"] == 0.0  # logged at 0: not the nominal -0.82
    assert state["EMQ3H"] == 0.0


def test_a_settings_epics_name_follows_the_geecs_gateway():
    from htu_twin_apps import machine_state

    # the examples of htu-pv-translation-draft.md
    assert machine_state.pv_name("S1H") == "undulator:u_s1h:current"
    assert (
        machine_state.pv_name("EMQ1H")
        == "undulator:u_emqtripletbipolar:current_limit_ch1"
    )
    with pytest.raises(ValueError, match="not a logged setting"):
        machine_state.pv_name("emq1_scale")


def test_the_twin_takes_settings_and_corrections_together():
    from htu_twin_apps import machine_state

    state = machine_state.to_twin({"EMQ1H": 1.2}, {"emq1_scale": 1.07})

    assert state == {"EMQ1H": 1.2, "emq1_scale": 1.07}
    with pytest.raises(ValueError, match=r"not setting keys: \['emq1_scale'\]"):
        machine_state.to_twin({"emq1_scale": 1.0}, {})
    with pytest.raises(ValueError, match=r"not correction keys: \['no_such_key'\]"):
        machine_state.to_twin({}, {"no_such_key": 1.0})


def test_the_fitted_corrections_are_correction_keys():
    from htu_twin_apps import machine_state
    from htu_twin_apps.lpa_source import aline

    fits = sorted(
        (pathlib.Path(machine_state.__file__).parent / "twin_viewer" / "fits").glob(
            "*.json"
        )
    )
    assert fits
    for f in fits:
        fitted = json.loads(f.read_text())["machine_state"]
        # the A-line camera's pixel size is fitted with them, but calibrates a camera, not the line
        fitted.pop(aline.PIXEL_KEY)
        assert machine_state.to_twin({}, fitted) == fitted, f.name


def test_every_setting_is_an_input_of_the_twin():
    htu_model = pytest.importorskip("htu.model")
    from htu_twin_apps import machine_state

    settings = {
        k for k, v in machine_state.KEYS.items() if v.kind == machine_state.SETTING
    }

    assert settings <= set(htu_model.DEFAULT_MACHINE_STATE)
