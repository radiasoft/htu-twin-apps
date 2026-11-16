"""The documentation's tables of the machine state agree with the code."""

from __future__ import annotations

import pathlib
import re


def test_the_pv_translations_machine_state_tables_are_the_codes():
    from htu_twin_apps import machine_state, pv_access

    text = (
        pathlib.Path(__file__).parents[1] / "docs" / "htu-pv-translation.md"
    ).read_text()
    rows = {}
    for line in text.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        m = re.fullmatch(r"`([^`]+)`", cells[0]) if line.startswith("|") else None
        if m and m.group(1) in machine_state.KEYS:
            rows[m.group(1)] = cells[1:]

    expected = {}
    for k, v in machine_state.KEYS.items():
        if v.kind == machine_state.SETTING:
            expected[k] = [
                f"`{v.geecs}`",
                f"`{machine_state.pv_name(k)}`",
                f"`{pv_access.twin_name(k)}`",
                v.unit,
                "" if v.nominal is None else f"{v.nominal:g}",
            ]
        else:
            expected[k] = [v.unit, v.description]
    assert rows == expected
