#!/usr/bin/env python3
"""
TRANSITION REPAIR EVENTS (Path B) — additive
============================================
Authority: docs/Wood_Shake_Spec_Amendment_Transition_Repair_Events_v0_1.md

Path A (passive, ≥95% sweep) is UNCHANGED and lives in module2_scope_expansion.
This module adds only what Path B needs:

  1. THE GATE, ENFORCED AT THE DATA LAYER (§2). A transition becomes a repair event only when the
     user asserted BOTH `exposed` and `damaged`. The UI gate is not the enforcement point — this is.
     A payload with exposed=False (or damaged=False, or either missing) creates NO repair event,
     so the gate cannot be bypassed by hand-crafting a selection.

  2. THE BAND GEOMETRY (§3), per CSSB Figure 10:
       UPPER slope: 36 in (3 ft) up-slope from the shared edge — CSSB's 914 mm starter-felt strip
                    governs the tear-off (the metal alone is only 152 mm/6 in up).
       LOWER slope: ONE (1) COURSE down-slope — a course-lap requirement, specified in courses and
                    therefore read off the slope's own course grid (exposure), not in inches.
     The band runs the full edge_total_LF and is carved on BOTH facets sharing the edge.

The DETECTOR IS UNTOUCHED: this module never creates, moves, or re-lengths a transition. It only
consumes an already-detected one (transition_enumerator.confirmed_transitions) that the user SELECTED.
`edge_total_LF` is geometric truth and is never user-edited — which is what structurally kills any
double-count or length ambiguity.
"""

from __future__ import annotations

from typing import List, Mapping, Optional, Sequence

from geometry_core import resolve_shake_measurements
from transition_enumerator import confirmed_transitions, transition_contact_readings

UPPER_BAND_FT = 3.0        # 36 in — CSSB 914 mm starter-felt strip on the upper slope
LOWER_BAND_COURSES = 1     # one course down-slope (course-lap requirement)

UPPER = "UPPER"
LOWER = "LOWER"


# ---------------------------------------------------------------------------
# 1. The gate (data layer — the real enforcement point)
# ---------------------------------------------------------------------------
def selected_transition_repairs(confirmed_selection: Mapping[str, object]) -> tuple:
    """Edge ids the user confirmed as repair events.

    BOTH assertions are required (spec §2):
        exposed = True  -> the flashing is visible metal, not concealed under the courses
        damaged = True  -> that metal has storm damage

    Anything else — exposed False, damaged False, either absent, or a non-True value — yields NO
    repair event. This is deliberate: asserting damaged transition flashing is a CLAIM that goes
    into a document an adjuster and an appraiser will read, so it cannot be created by accident,
    and it cannot be smuggled in through the payload either.
    """
    rows = confirmed_selection.get("transition_repairs", ()) or ()
    out: List[str] = []
    for row in rows:
        data = dict(row) if not isinstance(row, dict) else row
        edge_id = data.get("edge_id")
        if not edge_id:
            continue
        if data.get("exposed") is True and data.get("damaged") is True:
            out.append(str(edge_id))
    return tuple(dict.fromkeys(out))            # de-duped, order preserved


def selected_transitions(geom, confirmed_selection) -> list:
    """The DETECTED transitions the user selected. A selection naming an edge the detector did not
    return is ignored — the user can only ever select something the three-condition test found."""
    wanted = set(selected_transition_repairs(confirmed_selection))
    if not wanted:
        return []
    return [t for t in confirmed_transitions(geom) if t.edge_id in wanted]


# ---------------------------------------------------------------------------
# 1b. PATH A — the passive >=95% rule, now actually LIVE (Build 2b)
# ---------------------------------------------------------------------------
CAP_THRESHOLD = 0.95        # same constant module2_scope_expansion uses; the rule is unchanged


def transition_contact_lf(geom, transition, selected_valley_ids) -> float:
    """Affected-area contact along this transition, from OTHER repairs (the selected valleys).

    Read on BOTH facets and the LARGER taken: the flashing is a single continuous piece spanning
    the edge, so if the repair sweeps its full length on either slope, that flashing is torn out.
    (On Yager's L33 this is 100% on V and 0% on P — the metal is still gone.)
    """
    readings = transition_contact_readings(
        geom, transition, selected_valley_ids=[str(v) for v in (selected_valley_ids or ())])
    return max([float(r["contact_LF"]) for r in readings] or [0.0])


def path_a_transitions(geom, confirmed_selection) -> list:
    """Detected transitions the selected repairs sweep to >=95% of edge_total_LF.

    THE BUG THIS FIXES (Build 2b): module2_assembly always built M1Interface(transitions=[]), so the
    >=95% rule — designed, specified and believed live — had NEVER ONCE RUN on a real roof. Yager's
    L33 is swept 100% by the standard confirmed repair and was being silently dropped.

    The rule itself is unchanged; it is simply evaluated now.
    """
    valley_ids = [str(v) for v in (confirmed_selection.get("selected_valley_ids", ()) or ())]
    if not valley_ids:
        return []
    fired = []
    for t in confirmed_transitions(geom):
        if t.edge_total_LF <= 0:
            continue
        if transition_contact_lf(geom, t, valley_ids) >= CAP_THRESHOLD * float(t.edge_total_LF):
            fired.append(t)
    return fired


def active_transitions(geom, confirmed_selection) -> list:
    """Every transition that fires, by EITHER path, each appearing exactly ONCE.

    Path A (passive): the repair swept >=95% of it — the flashing was torn out (consequential).
    Path B (active):  the user asserted exposed + damaged — the flashing IS the damage (trigger).

    De-duplication is preserved here as well as in expand_scope: a transition satisfying BOTH paths
    appears once in this list, so it can only ever produce ONE flashing line at edge_total_LF.
    """
    by_id = {}
    for t in path_a_transitions(geom, confirmed_selection):
        by_id[t.edge_id] = t
    for t in selected_transitions(geom, confirmed_selection):
        by_id[t.edge_id] = t
    return [by_id[k] for k in sorted(by_id)]


def transition_trigger(geom, confirmed_selection, edge_id) -> str:
    """"PATH_A" | "PATH_B" | "BOTH" — which path put this transition in scope. UI-facing only."""
    a = {t.edge_id for t in path_a_transitions(geom, confirmed_selection)}
    b = set(selected_transition_repairs(confirmed_selection))
    eid = str(edge_id)
    if eid in a and eid in b:
        return "BOTH"
    if eid in a:
        return "PATH_A"
    return "PATH_B" if eid in b else ""


# ---------------------------------------------------------------------------
# 2. The band (§3)
# ---------------------------------------------------------------------------
def transition_band_for_face(geom, transition, face_id: str,
                             shake_measurements: Optional[Mapping[str, object]] = None) -> Mapping[str, object]:
    """The tear-off band this transition carves on ONE of its two facets, in that facet's frame.

    Which facet is the UPPER slope is read from 3-D ELEVATION, never assumed: the facet that rises
    ABOVE the shared edge is the upper slope; the one that only descends from it is the lower slope.

    (A tempting shortcut — "the edge sits at the facet's min-y, so the facet is above it" — is WRONG
    here and was caught in testing: these facets are not rectangles. On Yager's L33, facet V is
    stepped, so the shared edge lies partway up V's frame with most of V's vertices BELOW it, yet V
    genuinely rises above the edge (to z=0.00 vs the edge's z=-1.625) and IS the upper slope.
    Elevation is the only honest test.)

    The band is then aimed INTO the facet from the edge: up-slope (+y) 36 in on the upper facet,
    down-slope (-y) one course on the lower one. It is clipped to the facet by affected_area, so a
    short upper slope simply yields a shorter band rather than spilling off the roof.
    """
    frame = geom.face_frame(face_id)
    line = geom.lines[transition.edge_id]
    a = frame(geom.points[line.path[0]])
    b = frame(geom.points[line.path[-1]])

    edge_y = (float(a[1]) + float(b[1])) / 2.0
    x_lo, x_hi = sorted((float(a[0]), float(b[0])))

    edge_z = float(geom.points[line.path[0]][2])
    face = geom.faces[face_id]
    zs = [float(geom.points[pid][2]) for lid in face.line_ids for pid in geom.lines[lid].path]
    rises_above_edge = (max(zs) - edge_z) > 1e-6

    prof = resolve_shake_measurements(shake_measurements)
    course_ft = float(prof["exposure_in"]) / 12.0

    if rises_above_edge:
        # UPPER slope — 36 in (CSSB 914 mm starter-felt strip) measured UP-slope from the edge.
        band = {"x0": x_lo, "x1": x_hi, "y0": edge_y, "y1": edge_y + UPPER_BAND_FT, "side": UPPER}
    else:
        # LOWER slope — ONE course measured DOWN-slope from the edge (course-lap requirement).
        band = {"x0": x_lo, "x1": x_hi, "y0": edge_y - LOWER_BAND_COURSES * course_ft,
                "y1": edge_y, "side": LOWER}
    band["edge_id"] = transition.edge_id
    band["face_id"] = face_id
    band["edge_total_LF"] = float(transition.edge_total_LF)
    band["course_ft"] = course_ft
    return band


def transition_bands_by_face(geom, confirmed_selection,
                             shake_measurements: Optional[Mapping[str, object]] = None) -> dict:
    """{face_id: [band, ...]} for every facet touched by an ACTIVE transition — by EITHER path.

    Build 2b: Path A carves the band too, and this is required, not cosmetic. On Yager's L33 the
    valley repair sweeps facet V 100% but facet P 0%: the LOWER slope is never opened. Without the
    carve the tool would bill transition flashing that cannot physically be installed — CSSB needs
    the 914 mm felt strip above the edge and the 6 in metal lapped over the lower courses, and you
    cannot do either through shakes that are still nailed down. Standard union rules apply, so the
    band adds ~0 SF on V (already swept) and real area on P."""
    bands: dict = {}
    for transition in active_transitions(geom, confirmed_selection):
        for face_id in (transition.face_a_id, transition.face_b_id):
            band = transition_band_for_face(geom, transition, face_id, shake_measurements)
            bands.setdefault(face_id, []).append(band)
    return bands


def engine_bands(bands: Sequence[Mapping[str, object]]) -> List[Mapping[str, float]]:
    """Strip to the four numbers geometry_core.affected_area consumes."""
    return [{"x0": float(b["x0"]), "x1": float(b["x1"]), "y0": float(b["y0"]), "y1": float(b["y1"])}
            for b in (bands or [])]
