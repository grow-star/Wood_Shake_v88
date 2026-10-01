#!/usr/bin/env python3
# CHANGELOG 2026-06-29 (Phase-2 re-baseline): single-path penetration exclusion
#   now dimensional-only (footprint >= 0.5 SF) for consistency with multi/notch.
#   No-op for Yager (F72 is dimensional and out-of-zone) but makes the rule uniform.
"""Surface Module 1 geometry results into the Module 2 M1Interface shape."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import os
from typing import Iterable, List, Mapping, Optional, Sequence

from eagleview_geometry_parser import EagleViewGeometry
from module2_scope_expansion import Appurt, Edge, M1Interface, Transition

_REGRESSION_ENGINE = None


def _quiet_import_regression_engine():
    global _REGRESSION_ENGINE
    if _REGRESSION_ENGINE is not None:
        return _REGRESSION_ENGINE
    spec = importlib.util.find_spec("geometry_core")
    if spec is None or spec.loader is None:
        raise ImportError("geometry_core")
    module = importlib.util.module_from_spec(spec)
    cwd = os.getcwd()
    try:
        os.chdir(os.path.dirname(os.path.abspath(__file__)))
        with contextlib.redirect_stdout(io.StringIO()):
            try:
                spec.loader.exec_module(module)
            except SystemExit as exc:
                if exc.code not in (0, None):
                    raise
    finally:
        os.chdir(cwd)
    _REGRESSION_ENGINE = module
    return module


def _quiet_import_regression_symbol(name: str):
    return getattr(_quiet_import_regression_engine(), name)


edge_contacts = _quiet_import_regression_symbol("edge_contacts")
affected_area = _quiet_import_regression_symbol("affected_area")


def build_m1_interface_for_face(
    geom: EagleViewGeometry,
    face_id: str,
    confirmed_valley_line_ids: Iterable[str] = (),
    confirmed_transition_line_ids: Iterable[str] = (),
    confirmed_appurtenance_candidates: Iterable[Mapping[str, object]] = (),
    affected_SF: Optional[float] = None,
    valley_LF_in_scope: Optional[float] = None,
    repair_factor: float = 1.0,
    facet_pitch_tier: Optional[str] = None,
    high_slope_user_flag: bool = False,
    shake_measurements: Optional[Mapping[str, object]] = None,
    is_replacement: bool = False,
) -> M1Interface:
    """Translate one confirmed facet stream into Module 2's M1Interface.

    This is packaging only: it wraps frozen Module 1 results and creates the
    dataclass objects Module 2 already consumes. It does not do scope math.
    """
    engine_face = geom.engine_facet(face_id)
    face = geom.faces[face_id]
    confirmed_valleys = tuple(v for v in confirmed_valley_line_ids if v in face.line_ids)
    valley_events = [geom.valley_event_for_face(face_id, valley_id) for valley_id in confirmed_valleys]

    if affected_SF is None:
        per_areas, _ = affected_area(engine_face.facet, valley_events, penetrations=[_p for _p in engine_face.penetrations if (lambda q: abs(sum(q[i][0]*q[(i+1)%len(q)][1]-q[(i+1)%len(q)][0]*q[i][1] for i in range(len(q))))/2.0)(_p) >= 0.5], shake_measurements=shake_measurements)
        affected = float(sum(per_areas))
    else:
        affected = float(affected_SF)

    if valley_LF_in_scope is None:
        valley_lf = float(sum(geom.valley_lengths[v] for v in confirmed_valleys if v in geom.valley_lengths))
    else:
        valley_lf = float(valley_LF_in_scope)

    surfaced_edges = _surface_edges(engine_face.facet, valley_events, engine_face.edges, shake_measurements=shake_measurements)
    surfaced_transitions = _surface_transitions(geom, face_id, confirmed_transition_line_ids, valley_events)
    surfaced_appurts = _surface_appurts(confirmed_appurtenance_candidates)

    return M1Interface(
        affected_SF=affected,
        valley_LF_in_scope=valley_lf,
        edges=surfaced_edges,
        appurts=surfaced_appurts,
        transitions=surfaced_transitions,
        facet_pitch_tier=facet_pitch_tier,
        high_slope_user_flag=high_slope_user_flag,
        shake_width_in=float((shake_measurements or {}).get("width_in", 7.0)),
        exposure_in=float((shake_measurements or {}).get("exposure_in", 10.0)),
        is_replacement=is_replacement,
    )


def _surface_edges(facet, valley_events, edges, shake_measurements=None) -> List[Edge]:
    contacts = edge_contacts(facet, valley_events, edges, res=0.04, shake_measurements=shake_measurements) if valley_events else {}
    out: List[Edge] = []
    for _a, _b, edge_type, edge_total_lf in edges:
        if edge_type == "VALLEY":
            continue
        contact_lf = float(contacts.get(edge_type, (0.0, edge_total_lf))[0])
        total_lf = float(contacts.get(edge_type, (contact_lf, edge_total_lf))[1])
        out.append(Edge(edge_type, contact_lf, total_lf))
    return out


def _surface_transitions(
    geom: EagleViewGeometry,
    face_id: str,
    confirmed_transition_line_ids: Iterable[str],
    valley_events,
) -> List[Transition]:
    selected_transitions = set(confirmed_transition_line_ids)
    if not selected_transitions:
        return []
    engine_face = geom.engine_facet(face_id)
    frame = geom.face_frame(face_id)
    out: List[Transition] = []
    from transition_enumerator import enumerate_transition_candidates
    for transition in enumerate_transition_candidates(geom):
        if not transition.true_transition or transition.edge_id not in selected_transitions:
            continue
        if face_id not in (transition.face_a_id, transition.face_b_id):
            continue
        line = geom.lines[transition.edge_id]
        edge = [(
            tuple(float(v) for v in frame(geom.points[line.path[0]])),
            tuple(float(v) for v in frame(geom.points[line.path[-1]])),
            "TRANSITION",
            transition.edge_total_LF,
        )]
        contacts = edge_contacts(engine_face.facet, valley_events, edge, res=0.04) if valley_events else {}
        contact_lf = float(contacts.get("TRANSITION", (0.0, transition.edge_total_LF))[0])
        total_lf = float(contacts.get("TRANSITION", (contact_lf, transition.edge_total_LF))[1])
        out.append(Transition(contact_lf, total_lf))
    return out


def _surface_appurts(candidates: Iterable[Mapping[str, object]]) -> List[Appurt]:
    out: List[Appurt] = []
    for candidate in candidates:
        params = candidate.get("params", {}) if isinstance(candidate, Mapping) else {}
        geom = params.get("appurtenance_geometry") if isinstance(params, Mapping) else None
        affected = 0.0
        if isinstance(geom, Mapping):
            affected = float(geom.get("w", 0.0)) * float(geom.get("h", 0.0))
        label = str(params.get("kind_label") or params.get("type") or "OTHER") if isinstance(params, Mapping) else "OTHER"
        # contacted/size_class are user classify-and-attribute inputs; default preserves prior behavior
        contacted = bool(params.get("contacted", True)) if isinstance(params, Mapping) else True
        size_class = params.get("size_class") if isinstance(params, Mapping) else None
        out.append(Appurt(label.upper(), affected_SF=affected, contacted=contacted, size_class=size_class,
                          other_label=(params.get("other_label") if isinstance(params, Mapping) else None),
                          other_category=(params.get("other_category") if isinstance(params, Mapping) else None),
                          # EagleView splits ONE physical chimney into one marker per facet it crosses.
                          # module2_scope_expansion has always deduped the MATERIAL line by `group`
                          # (one assembly per physical object) — but nothing ever passed a group in, so
                          # every marker was its own group and 6 markers billed 6 flashings. Strictly
                          # additive: Appurt.group already exists and defaults to None, so a selection
                          # that sets no groups (e.g. Yager's default) is unchanged BY CONSTRUCTION.
                          # NOTE: this dedupes the material line ONLY. The affected AREA stays per
                          # marker — the chimney really does penetrate both planes.
                          group=(params.get("group") if isinstance(params, Mapping) else None)))
    return out
