"""Track an LPA source through the HTU twin (`geecs-lume-twin`) to the spectrometer entrance.

The twin is built only up to `PIPE_AP8`, the end of the beam pipe at the magnetic
spectrometer's entrance, with no active screens. The machine settings go through the twin's own
`htu.model._apply_machine_state`, so magnet currents mean what they mean in the twin. The beam is
tracked element by element with each element's own `track`: `Segment.track` merges elements into
transfer maps first, which is about ten times slower for these beams, and the simulator's
`track()` does not keep the outgoing beam.

Changes to the twin's line:

- The chicane slit can be a blade (`slit="blade"`): the twin's slit is two jaws that pass the
  beam between them (`slit="jaws"`, the default); a blade blocks the band between its edges and
  passes either side. The blade's edges are the twin's jaw keys, `chicane_jaw1_mm` its high-x
  edge and `chicane_jaw2_mm` its low-x edge, in the same lab frame (offset from the straight,
  R56 = 0 axis) and converted to the beam's frame by the twin as for the jaws. Or it can be the
  jaws with a blade as well (`slit="jaws_blade"`), the blade's edges given by BLADE_KEYS in the
  machine state (not twin keys; in the jaws' lab frame): a third obstruction, to test whether
  Scan019's narrow notch is one.
- Magnet strengths can be scaled (SCALES): a machine-state key such as `emq2_scale` multiplies
  its magnet's current (`EMQ2V`) before the twin sees it, to fit a calibration error. The scale
  keys are not twin keys and are removed.
- The EMQs can be offset (OFFSETS): `emq1_x_mm` and `emq1_y_mm` (and EMQ2's, EMQ3's) move the
  quadrupole's field off the beam pipe's axis (its `misalignment`), the pipe's apertures staying
  where they are. Not twin keys either.
- The PMQs get fringe fields (`pmq_fringe_mm`, PMQ_FRINGE_MM by default; None keeps the twin's
  hard-edged PMQs). The twin's PMQs are hard-edged, but they are only 16 to 29 mm long with a
  6 mm bore radius, so their fringe is a large part of them. Each PMQ's gradient is given a
  logistic step of width `pmq_fringe_mm` at each hard edge, `G(z) = G0 (s((z - z_in) / w) -
  s((z - z_out) / w))` with `s(u) = 1 / (1 + exp(-u))`, which keeps its integrated gradient, the
  twin's `G0 L`, exactly. The default width, half the bore radius, makes the field fall from 90%
  to 10% over about one bore diameter; it is assumed, as HTU has not given the PMQs' field
  profiles. The triplet's region, from PMQ1's entrance less PMQ_FRINGE_EXTENT widths to PMQ3's
  exit plus as many, is tracked as PMQ_SLICE_M slices whose gradient is the three profiles'
  sum (permanent magnets' fields add), offset with the triplet; the bore apertures stay at the
  magnets' ends.
- Each PMQ can be rolled and offset on its own (PMQ_ERROR_KEYS: `pmq2_roll_deg`, `pmq2_dx_mm`,
  `pmq2_dy_mm` and PMQ1's and PMQ3's), as Sam Barber's bench found (2026-10-08: PMQ2 0.27 / 0.07
  mm off the PMQ1-PMQ3 axis, PMQ2 and PMQ3 rolled 0.38 and 1.86 deg relative to PMQ1; signs in
  the twin's frame not known). The offsets are relative to the triplet's (`pmq_x_mm`,
  `pmq_y_mm`), and the PMQ's bore apertures move with it. Not twin keys. A slice's field is then a
  sum of quadrupoles with different rolls and centres; a sum of linear fields is linear, so each
  slice is one quadrupole of the sum's strength, roll and centre (`_slice`).
- The PMQ triplet's bore apertures move with the triplet. The twin offsets the three PMQs by
  `pmq_x_mm` and `pmq_y_mm` (their `misalignment`) but leaves the bore apertures at entrance and
  exit of each on the beam axis, so with an offset the clipping stays where the magnets were.
  Here each is replaced by `_ShiftedAperture`, centred on the offset triplet.
- The chicane dipoles get pole-face edges (`chicane_edges`, on by default). The twin's are sector
  bends, with no edges. Assumed here (HTU has not given the magnets' shape): rectangular magnets
  with every pole face perpendicular to the straight-through axis, so the beam enters BEND1 and
  BEND3 square and leaves at its bend angle (`dipole_e1` 0, `dipole_e2` the angle), and the
  reverse for BEND2 and BEND4. That cancels the bends' horizontal focusing and adds vertical
  focusing. The pole gap is not known either: `chicane_gap_m` 0 is a hard edge; with a gap, the
  fringe-field correction uses FRINGE_INTEGRAL. Cheetah's drift-kick-drift tracking applies both
  as linear edge kicks.

:copyright: Copyright (c) 2026 RadiaSoft LLC.  All Rights Reserved.
:license: http://www.apache.org/licenses/LICENSE-2.0.html
"""

from __future__ import annotations

import cheetah
import dataclasses
import functools
import htu.model
import numpy
import re
import torch
import types

# With `slit="jaws_blade"`, the machine-state keys of the blade's low-x and high-x edges [mm, lab
# frame, as the jaws'].
BLADE_KEYS = ("slit_blade_low_mm", "slit_blade_high_mm")
# The chicane dipoles the beam enters square (pole face perpendicular to it) and leaves at its
# bend angle; the others it enters at the angle and leaves square (`htu.lattice` names).
CHICANE_ENTERED_SQUARE = ("BEND1", "BEND3")
CHICANE_LEFT_SQUARE = ("BEND2", "BEND4")
# The element the line is cut after: the end of the beam pipe, at the spectrometer's entrance.
END_ELEMENT = "PIPE_AP8"
# The chicane dipoles' fringe-field integral, used only with a pole gap: 0.5 is typical of an
# unclamped fringe field (not measured).
FRINGE_INTEGRAL = 0.5
# Machine-state keys [mm] that offset an EMQ's field in x and y, by the EMQ's element.
OFFSETS = {
    "EMQ1H": ("emq1_x_mm", "emq1_y_mm"),
    "EMQ2V": ("emq2_x_mm", "emq2_y_mm"),
    "EMQ3H": ("emq3_x_mm", "emq3_y_mm"),
}
# The PMQ triplet's bore apertures, at entrance (i) and exit (o) of each PMQ (`htu.lattice`).
PMQ_APERTURE = re.compile(r"^PMQ\d[HV]_AP[io]$")
# Machine-state keys that roll [deg] and offset [mm, relative to the triplet] each PMQ, by its
# number (1 to 3): (roll, x, y).
PMQ_ERROR_KEYS = {
    i: (f"pmq{i}_roll_deg", f"pmq{i}_dx_mm", f"pmq{i}_dy_mm") for i in (1, 2, 3)
}
# How many fringe widths the sliced region extends beyond the triplet's outer hard edges
# (the gradient there is exp(-8), 3e-4, of the peak).
PMQ_FRINGE_EXTENT = 8
# The PMQs' default fringe width [mm]: half their 6 mm bore radius (assumed, not measured).
PMQ_FRINGE_MM = 3.0
# The PMQs (`htu.lattice`), and the drifts the sliced region begins and ends in.
PMQ_MAGNET = re.compile(r"^PMQ\d[HV]$")
PMQ_REGION = ("SrcToPMQ1", "PMQTripToTCPhos")
# A machine-state key (not a twin key) that scales every PMQ's gradient: the PMQs' field values
# are lattice constants with no stated source.
PMQ_SCALE_KEY = "pmq_scale"
# The length [m] of a slice of the PMQ triplet's region.
PMQ_SLICE_M = 0.002
# Machine-state keys that scale a magnet's current, by the twin key they scale.
SCALES = {
    "EMQ1H": "emq1_scale",
    "EMQ2V": "emq2_scale",
    "EMQ3H": "emq3_scale",
    "S1H": "s1h_scale",
}
# Scan016 (HTU, 2026-09-29): chicane, EMQs and steerers off except S1H, magspec dipole not in the
# line here. The S1H sign convention against the twin's is not validated.
SCAN016_STATE = {
    "EMQ1H": 0.0,
    "EMQ2V": 0.0,
    "EMQ3H": 0.0,
    "S1H": -2.7,
    "chicane_current": 0.0,
}
# The most lines `_segment` keeps: each is reused within an evaluation (every step's state), and a
# fit's next evaluation changes the state, so an unbounded cache only grows (13 GB per worker).
SEGMENT_CACHE = 64
# The chicane slit's shapes (see the module's docstring).
SLITS = ("jaws", "blade", "jaws_blade")
# The chicane slit's element (`htu.lattice`).
SLIT_ELEMENT = "ChicaneSlitJaws"


@dataclasses.dataclass
class Transported:
    """Particles at the spectrometer entrance: energy [MeV], positions [mm], angles [mrad],
    charge [pC].

    `charge_pc` is each particle's charge times its survival (0 for lost particles).
    """

    charge_pc: numpy.ndarray
    energy_mev: numpy.ndarray
    source_charge_pc: float
    x_mm: numpy.ndarray
    xp_mrad: numpy.ndarray
    y_mm: numpy.ndarray
    yp_mrad: numpy.ndarray

    def transmission(self) -> float:
        """The fraction of the source charge that reaches the spectrometer entrance."""
        return float(self.charge_pc.sum() / self.source_charge_pc)


def to_spectrometer(
    particles,
    machine_state: dict | None = None,
    reference_mev: float | None = None,
    chicane_edges: bool = True,
    chicane_gap_m: float = 0.0,
    pmq_fringe_mm: float | None = PMQ_FRINGE_MM,
    slit: str = "jaws",
) -> Transported:
    """Track `particles` (a `ParticleGroup` at the plasma exit) to the spectrometer entrance.

    Args:
        particles: the source, every particle at the plasma exit (`z` equal, `t` per particle).
        machine_state: twin machine-state keys to set over its defaults (see
            `htu.model.DEFAULT_MACHINE_STATE`), such as `SCAN016_STATE` or `pmq_z_mm`, and
            SCALES', OFFSETS', PMQ_ERROR_KEYS', PMQ_SCALE_KEY and (for "jaws_blade")
            BLADE_KEYS' keys.
        reference_mev: the reference energy the beam is tracked at; the particles' mean energy
            if None. Each particle is tracked at its own energy either way (drift-kick-drift),
            but a fixed reference lets repeated calls reuse one built line.
        chicane_edges: give the chicane dipoles rectangular pole-face edges (see the module's
            docstring); False keeps the twin's sector bends.
        chicane_gap_m: the chicane dipoles' full pole gap [m], for the edges' fringe-field
            correction; 0 is a hard edge.
        pmq_fringe_mm: the PMQs' fringe width [mm] (see the module's docstring); None keeps the
            twin's hard-edged PMQs.
        slit: the chicane slit's shape, one of SLITS (see the module's docstring).
    """
    if slit not in SLITS:
        raise ValueError(f"slit {slit!r} not one of {SLITS}")
    m = dict(machine_state or {})
    k = tuple(m.pop(x) for x in BLADE_KEYS) if slit == "jaws_blade" else None
    for x, v in SCALES.items():
        if v in m:
            # POSIT: htu.model.DEFAULT_MACHINE_STATE has every key in SCALES
            m[x] = m.pop(v) * m.get(x, htu.model.DEFAULT_MACHINE_STATE[x])
    o = tuple(
        (x, m.pop(v[0], 0.0), m.pop(v[1], 0.0))
        for x, v in OFFSETS.items()
        if v[0] in m or v[1] in m
    )
    q = float(m.pop(PMQ_SCALE_KEY, 1.0))
    r = tuple(
        (i, *(float(m.pop(x, 0.0)) for x in v))
        for i, v in PMQ_ERROR_KEYS.items()
        if any(x in m for x in v)
    )
    # POSIT: the twin's lattice is float32 (htu.lattice builds its tensors with torch defaults)
    e = torch.tensor(
        (
            float(particles["mean_energy"])
            if reference_mev is None
            else reference_mev * 1e6
        ),
        dtype=torch.float32,
    )
    b = cheetah.ParticleBeam.from_openpmd_particlegroup(
        particles, energy=e, dtype=torch.float32
    )
    for x in _segment(
        float(e),
        tuple(sorted(m.items())),
        chicane_edges,
        float(chicane_gap_m),
        None if pmq_fringe_mm is None else float(pmq_fringe_mm),
        slit,
        k,
        o,
        q,
        r,
    ).elements:
        b = x.track(b)
    return _transported(b, float(particles.charge * 1e12))


def without_slit(machine_state: dict) -> dict:
    """`machine_state` with the slit out: its jaw keys and BLADE_KEYS dropped (the twin's
    defaults retract the jaws)."""
    return {
        k: v
        for k, v in machine_state.items()
        if not k.startswith("chicane_jaw") and k not in BLADE_KEYS
    }


class _BladeSlit(cheetah.Aperture):
    """A blade across the beam: blocks `jaw_minus_m` < x < `jaw_plus_m` [m, beam frame]."""

    def __init__(self, jaws):
        super().__init__(name=jaws.name)
        self.jaw_minus_m = jaws.jaw_minus_m
        self.jaw_plus_m = jaws.jaw_plus_m

    def track(self, incoming):
        if not isinstance(incoming, cheetah.ParticleBeam):
            return super().track(incoming)
        return cheetah.ParticleBeam(
            particles=incoming.particles,
            energy=incoming.energy,
            particle_charges=incoming.particle_charges,
            survival_probabilities=incoming.survival_probabilities
            * ((incoming.x <= self.jaw_minus_m) | (incoming.x >= self.jaw_plus_m)),
            s=incoming.s,
            species=incoming.species.clone(),
        )


class _ShiftedAperture(cheetah.Aperture):
    """An `Aperture` centred at (x_offset, y_offset) [m] instead of on the beam axis."""

    def __init__(self, aperture: cheetah.Aperture, x_offset: float, y_offset: float):
        super().__init__(
            x_max=aperture.x_max,
            y_max=aperture.y_max,
            shape=aperture.shape,
            is_active=aperture.is_active,
            name=aperture.name,
        )
        self.x_offset = x_offset
        self.y_offset = y_offset

    def track(self, incoming):
        """`Aperture.track` on the particles relative to the centre; the coordinates are kept."""
        if not isinstance(incoming, cheetah.ParticleBeam):
            return super().track(incoming)
        b = incoming.clone()
        b.x = b.x - self.x_offset
        b.y = b.y - self.y_offset
        return cheetah.ParticleBeam(
            particles=incoming.particles,
            energy=incoming.energy,
            particle_charges=incoming.particle_charges,
            survival_probabilities=super().track(b).survival_probabilities,
            s=incoming.s,
            species=incoming.species.clone(),
        )


def _chicane_edges(segment, gap_m: float) -> None:
    """Give the chicane dipoles rectangular pole-face edges at their current bend angles."""
    for n in CHICANE_ENTERED_SQUARE + CHICANE_LEFT_SQUARE:
        d = getattr(segment, n)
        z = torch.zeros_like(d.angle)
        d.dipole_e1 = z if n in CHICANE_ENTERED_SQUARE else d.angle.clone()
        d.dipole_e2 = d.angle.clone() if n in CHICANE_ENTERED_SQUARE else z.clone()
        # the exit's gap and fringe integral default to the entrance's at construction only
        for a in ("gap", "gap_exit"):
            setattr(d, a, torch.full_like(d.angle, gap_m))
        for a in ("fringe_integral", "fringe_integral_exit"):
            setattr(d, a, torch.full_like(d.angle, FRINGE_INTEGRAL))


def _drift(name: str, length: float):
    return cheetah.Drift(
        length=torch.tensor(float(length)),
        tracking_method="drift_kick_drift",
        name=name,
    )


def _pmq_fringe(elements: list, width_m: float) -> list:
    """`elements` with the PMQ triplet's region (PMQ_REGION) replaced by fringe-field slices."""
    n = [x.name for x in elements]
    i, j = n.index(PMQ_REGION[0]), n.index(PMQ_REGION[1])
    m, a, z = [], [], 0.0
    for x in elements[i : j + 1]:
        if PMQ_MAGNET.match(x.name):
            m.append(
                (
                    z,
                    z + float(x.length),
                    float(x.k1),
                    float(x.tilt),
                    x.misalignment.detach().numpy().astype(float),
                )
            )
        elif isinstance(x, cheetah.Aperture):
            a.append((z, x))
        z += float(x.length)
    lo, hi = (
        m[0][0] - PMQ_FRINGE_EXTENT * width_m,
        m[-1][1] + PMQ_FRINGE_EXTENT * width_m,
    )
    if lo < 0 or hi > z:
        raise ValueError(f"fringe width {width_m} m reaches beyond {PMQ_REGION}")
    # the apertures' positions and the region's end exactly, then the regular slice boundaries
    # not within a micron of one (a slice boundary may land on an aperture up to rounding)
    f = numpy.array([p for p, _ in a] + [hi])
    g = numpy.sort(
        numpy.concatenate(
            [
                f,
                [
                    x
                    for x in numpy.arange(lo, hi, PMQ_SLICE_M)
                    if numpy.abs(f - x).min() > 1e-6
                ],
            ]
        )
    )
    rv = [_drift("PMQFringeIn", lo)]
    for k, (u, v) in enumerate(zip(g[:-1], g[1:])):
        rv.extend(x for p, x in a if abs(p - u) < 1e-9)
        c = (u + v) / 2
        q, t, d = _slice(
            [
                (q * (_step((c - s) / width_m) - _step((c - e) / width_m)), t, d)
                for s, e, q, t, d in m
            ],
            m[0][4],
        )
        rv.append(
            cheetah.Quadrupole(
                length=torch.tensor(float(v - u)),
                k1=torch.tensor(float(q), dtype=torch.float32),
                misalignment=torch.tensor(d, dtype=torch.float32),
                tilt=torch.tensor(float(t), dtype=torch.float32),
                num_steps=1,
                tracking_method="drift_kick_drift",
                name=f"PMQFringe{k:03d}",
            )
        )
    rv.extend(x for p, x in a if abs(p - g[-1]) < 1e-9)
    return elements[:i] + rv + [_drift("PMQFringeOut", z - hi)] + elements[j + 1 :]


@functools.lru_cache(maxsize=SEGMENT_CACHE)
def _segment(
    energy_ev: float,
    machine_state: tuple,
    chicane_edges: bool,
    chicane_gap_m: float,
    pmq_fringe_mm: float | None,
    slit: str,
    blade: tuple | None,
    offsets: tuple,
    pmq_scale: float = 1.0,
    pmq_errors: tuple = (),
):
    """The twin's line to END_ELEMENT with `machine_state` (key, value pairs) applied at
    reference `energy_ev`, the PMQ bore apertures moved with the triplet, with `pmq_fringe_mm`
    fringe fields on the PMQs, with `chicane_edges` edges on the chicane dipoles, and the slit
    shaped as `slit` (with `blade`'s edges [mm, lab frame] for "jaws_blade"), and the EMQs in
    `offsets` ((element, x [mm], y [mm]) triples) offset from the pipe's axis, and the PMQs in
    `pmq_errors` ((number, roll [deg], x [mm], y [mm])) rolled and offset from the triplet;
    tracking does not change a line's elements, so a line is reused."""
    import htu.lattice
    import htu.model

    m = dict(machine_state)
    u = set(m) - set(htu.model.DEFAULT_MACHINE_STATE)
    if u:
        raise KeyError(f"not twin machine-state keys: {sorted(u)}")
    s = htu.lattice.build_htu_segment(active_screens=(), to_element=END_ELEMENT)
    m = {**htu.model.DEFAULT_MACHINE_STATE, **m}
    # POSIT: htu.model._apply_machine_state reads only `segment`, `energies` (element name to
    # reference energy [eV]) and `machine_state` of the simulator it is given, and nothing in
    # this part of the line changes the beam energy, so every element's energy is the source's.
    htu.model._apply_machine_state(
        types.SimpleNamespace(
            segment=s, energies={x.name: energy_ev for x in s.elements}, machine_state=m
        )
    )
    g = {i: (a, b, c) for i, a, b, c in pmq_errors}
    for x in s.elements:
        if PMQ_MAGNET.match(x.name):
            # POSIT: _apply_machine_state has set the PMQs' k1 and the triplet's misalignment;
            # _pmq_fringe reads them, and the tilt, below
            x.k1 = x.k1 * pmq_scale
            if int(x.name[3]) in g:
                a, b, c = g[int(x.name[3])]
                x.tilt = torch.tensor(numpy.radians(a), dtype=torch.float32)
                x.misalignment = x.misalignment + torch.tensor(
                    [b * 1e-3, c * 1e-3], dtype=torch.float32
                )
    if chicane_edges:
        # POSIT: _apply_machine_state has set the chicane dipoles' angles from chicane_current
        _chicane_edges(s, chicane_gap_m)
    # POSIT: _apply_machine_state offsets the PMQs by (pmq_x_mm, pmq_y_mm) mm (their
    # misalignment), so their bore apertures are centred there
    d = (m["pmq_x_mm"] * 1e-3, m["pmq_y_mm"] * 1e-3)
    e = list(s.elements)
    if slit == "blade":
        # POSIT: _apply_machine_state has set the jaws' jaw_plus_m and jaw_minus_m (beam frame)
        e = [_BladeSlit(x) if x.name == SLIT_ELEMENT else x for x in e]
    if slit == "jaws_blade":
        e = _slit_blade(e, m["chicane_jaw1_mm"], blade)
    for n, x, y in offsets:
        # POSIT: htu.lattice's EMQs are single Quadrupole elements named as OFFSETS' keys
        q = next(z for z in e if z.name == n)
        q.misalignment = torch.tensor([x * 1e-3, y * 1e-3], dtype=torch.float32)
    if pmq_fringe_mm is not None:
        # POSIT: _apply_machine_state has set the PMQs' k1 at energy_ev and the triplet's offset
        e = _pmq_fringe(e, pmq_fringe_mm * 1e-3)
    return cheetah.Segment(
        elements=[
            (
                _ShiftedAperture(
                    x,
                    # POSIT: PMQ_APERTURE's names start with their PMQ's ("PMQ2V_APi")
                    d[0] + g.get(int(x.name[3]), (0, 0, 0))[1] * 1e-3,
                    d[1] + g.get(int(x.name[3]), (0, 0, 0))[2] * 1e-3,
                )
                if PMQ_APERTURE.match(x.name)
                else x
            )
            for x in e
        ],
        name=s.name,
    )


def _slice(fields: list, centre: numpy.ndarray) -> tuple:
    """(k1, tilt [rad], centre [m]) of the one quadrupole equal to the sum of `fields`, each
    (k1, tilt [rad], centre [m]); `centre` for a slice with no field.

    In Cheetah's frame (the particle shifted by the centre, then rotated by the tilt) a
    quadrupole kicks by `-k1 K(tilt) (r - centre)` with `K(t) = [[cos 2t, sin 2t], [sin 2t,
    -cos 2t]]`. The sum's matrix has the same form: `a = sum k1 cos 2t`, `b = sum k1 sin 2t` give
    its k1 `sqrt(a^2 + b^2)` and tilt `atan2(b, a) / 2`, and its centre solves `M c = sum k1 K
    c_i`, where `M^-1 = M / k1^2`. As `K(t - pi/2) = -K(t)`, the tilt is kept within +-pi/4 and
    k1 takes the sign: untilted PMQs give untilted slices of the summed k1, as without rolls.
    """
    a = sum(q * numpy.cos(2 * t) for q, t, _ in fields)
    b = sum(q * numpy.sin(2 * t) for q, t, _ in fields)
    k = float(numpy.hypot(a, b))
    if k < 1e-12:
        return 0.0, 0.0, centre
    m = numpy.array([[a, b], [b, -a]])
    v = sum(
        q
        * numpy.array(
            [
                [numpy.cos(2 * t), numpy.sin(2 * t)],
                [numpy.sin(2 * t), -numpy.cos(2 * t)],
            ]
        )
        @ d
        for q, t, d in fields
    )
    t = float(numpy.arctan2(b, a) / 2)
    if abs(t) > numpy.pi / 4:
        return -k, t - numpy.copysign(numpy.pi / 2, t), (m @ v) / k**2
    return k, t, (m @ v) / k**2


def _slit_blade(elements: list, jaw1_mm: float, blade: tuple) -> list:
    """`elements` with a blade after the slit's jaws, its edges `blade` [mm, lab frame]."""
    i = next(i for i, x in enumerate(elements) if x.name == SLIT_ELEMENT)
    # POSIT: _apply_machine_state has set jaw_plus_m to chicane_jaw1_mm less the slit's
    # reference offset (the lab-to-beam frame shift)
    o = jaw1_mm * 1e-3 - float(elements[i].jaw_plus_m)
    return (
        elements[: i + 1]
        + [
            _BladeSlit(
                types.SimpleNamespace(
                    name=SLIT_ELEMENT + "Blade",
                    jaw_minus_m=blade[0] * 1e-3 - o,
                    jaw_plus_m=blade[1] * 1e-3 - o,
                )
            )
        ]
        + elements[i + 1 :]
    )


def _step(u):
    """The logistic step, 0 for u far below 0 and 1 far above (as tanh, which cannot overflow)."""
    return 0.5 * (1.0 + numpy.tanh(0.5 * u))


def _transported(beam, source_charge_pc: float) -> Transported:
    """The outgoing beam as arrays; angles are px/pz, using each particle's own momentum."""
    p = (beam.momenta / beam.p0c).detach().numpy()
    return Transported(
        charge_pc=(beam.particle_charges * beam.survival_probabilities).detach().numpy()
        * 1e12,
        energy_mev=beam.energies.detach().numpy() / 1e6,
        source_charge_pc=source_charge_pc,
        x_mm=beam.x.detach().numpy() * 1e3,
        xp_mrad=beam.px.detach().numpy() / p * 1e3,
        y_mm=beam.y.detach().numpy() * 1e3,
        yp_mrad=beam.py.detach().numpy() / p * 1e3,
    )
