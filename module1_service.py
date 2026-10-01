#!/usr/bin/env python3
# CHANGELOG 2026-06-29 (Phase-2 re-baseline): M1 service affected-area invocations
#   made consistent with module2_assembly -- dimensional-only clipped exclusion across
#   single/multi/notch + in-field appurtenance dedup. Keeps M1 and M2 totals in
#   agreement at 3691 EA / 1638.0 SF. See module1_yager_proof.py.
"""
MODULE 1 PRODUCTION SERVICE — candidate-confirmation bridge
===========================================================
Parses EagleView XML, emits detection candidates, accepts a Workbench-style
confirmed-selection payload, derives frozen-engine inputs from the confirmed
candidates, and emits Module 1/2 totals. Detection is not confirmation.

This service performs no affected-area math and no scope math itself. It wraps
sealed engine functions and Module 2. Yager-specific selections belong in proof
harnesses, not this module.
"""

from __future__ import annotations

from dataclasses import dataclass
import contextlib
import importlib.util
import io
import os
from typing import List, Mapping, Sequence, Tuple

import numpy as np

# ONE AUTHORITY, shared with module2_assembly, for "does this appurtenance disturb the field?".
from shared_category_registry import appurtenance_carves
from candidate_emitters import (
    emit_face_candidates,
    emit_penetration_candidates,
    emit_transition_candidates,
    emit_valley_candidates,
)
from candidate_model import Candidate
from eagleview_geometry_parser import EagleViewGeometry, parse_eagleview_geometry
from module1_selected_valley_handoff import selected_valley_handoff
from module2_scope_expansion import M1Interface, expand_scope
from notch_candidate_emitter import emit_notch_candidates


def _quiet_import_regression_engine():
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
    return module


_engine = _quiet_import_regression_engine()
affected_area = _engine.affected_area
mkframe_pts = _engine.mkframe_pts


@dataclass(frozen=True)
class CandidatePackage:
    geom: EagleViewGeometry
    faces: List[Candidate]
    valleys: List[Candidate]
    penetrations: List[Candidate]
    transitions: List[Candidate]
    notches: List[Candidate]


@dataclass(frozen=True)
class Module1ComponentResult:
    label: str
    affected_SF_raw: float
    geometry_status: str
    source: str
    zone: object = None      # local affected-cell mask (the shape Module 1 computed)
    gx: object = None        # local grid x
    gy: object = None        # local grid y
    face_id: object = None   # for facet local->shared transform in the diagram


@dataclass(frozen=True)
class Module1ServiceResult:
    candidate_package: CandidatePackage
    components: List[Module1ComponentResult]
    selected_valley_LF_total: float
    scope_lines: list
    affected_SF_raw_total: float
    affected_SF_display: float
    affected_SQ_raw: float
    affected_SQ_display: float
    shake_EA: int
    derivation_report: List[Mapping[str, str]]


def build_candidate_package(xml_text: str) -> CandidatePackage:
    geom = parse_eagleview_geometry(xml_text)
    return CandidatePackage(
        geom=geom,
        faces=emit_face_candidates(geom),
        valleys=emit_valley_candidates(geom),
        penetrations=emit_penetration_candidates(geom),
        transitions=emit_transition_candidates(geom),
        notches=emit_notch_candidates(geom),
    )


_DIM_MIN_SF = 0.5  # footprint >= 0.5 SF => dimensional (carve); below => point (lay over)

def _polyarea_xy(poly) -> float:
    a = 0.0; n = len(poly)
    for i in range(n):
        x1, y1 = poly[i][0], poly[i][1]
        x2, y2 = poly[(i + 1) % n][0], poly[(i + 1) % n][1]
        a += x1 * y2 - x2 * y1
    return abs(a) / 2.0

def _dimensional_pens(polys):
    return [p for p in polys if _polyarea_xy(p) >= _DIM_MIN_SF]


_ONE_SHAKE_SF = 1.0 / 2.25

def _filter_subshake_components(mask, gx, gy, threshold_sf: float = _ONE_SHAKE_SF):
    """Drop 4-connected mask components smaller than one replaceable shake."""
    src = np.asarray(mask, dtype=bool)
    out = np.zeros_like(src, dtype=bool)
    if src.size == 0 or len(gx) < 2 or len(gy) < 2:
        return out
    cell = float((gx[1] - gx[0]) * (gy[1] - gy[0]))
    visited = np.zeros_like(src, dtype=bool)
    rows, cols = src.shape
    for r in range(rows):
        for c in range(cols):
            if not src[r, c] or visited[r, c]:
                continue
            stack = [(r, c)]
            visited[r, c] = True
            cells = []
            while stack:
                cr, cc = stack.pop()
                cells.append((cr, cc))
                for nr, nc in ((cr - 1, cc), (cr + 1, cc), (cr, cc - 1), (cr, cc + 1)):
                    if 0 <= nr < rows and 0 <= nc < cols and src[nr, nc] and not visited[nr, nc]:
                        visited[nr, nc] = True
                        stack.append((nr, nc))
            if len(cells) * cell >= threshold_sf:
                for cr, cc in cells:
                    out[cr, cc] = True
    return out

def run_module1_service(xml_text: str, confirmed_selection: Mapping[str, object]) -> Module1ServiceResult:
    package = build_candidate_package(xml_text)
    geom = package.geom
    valley_candidates = {c.source_ids[0]: c for c in package.valleys}
    penetration_candidates = {c.source_ids[0]: c for c in package.penetrations}
    notch_candidates = {tuple(c.source_ids): c for c in package.notches}
    components: List[Module1ComponentResult] = []
    derivation_report: List[Mapping[str, str]] = []
    _repair_facet_ids = set()
    for _it in confirmed_selection.get("single_valley_repairs", []): _repair_facet_ids.add(str(_confirmed_mapping(_it)["face_id"]))
    for _it in confirmed_selection.get("multi_valley_facets", []): _repair_facet_ids.add(str(_confirmed_mapping(_it)["face_id"]))
    for _it in confirmed_selection.get("notch_repairs", []):
        for _m in _confirmed_mapping(_it).get("member_face_ids", []): _repair_facet_ids.add(str(_m))

    for item in confirmed_selection.get("single_valley_repairs", []):
        row = _confirmed_mapping(item)
        valley_id = str(row["valley_id"])
        face_id = str(row["face_id"])
        cand = _require_candidate(valley_candidates, valley_id, "valley")
        _require_bordering_face(cand, face_id)
        facet_geom = geom.engine_facet(face_id)
        penetrations = _penetrations_with_user_footprints(geom, confirmed_selection, face_id)  # XML + confirmed user dimensioned footprint holes
        per_event, _area, _zone, _gx, _gy = affected_area(
            facet_geom.facet,
            [geom.valley_event_for_face(face_id, valley_id)],
            penetrations=penetrations,
            return_zone=True,
        )
        components.append(Module1ComponentResult(
            label=str(row.get("label", f"{face_id}:{valley_id}")),
            affected_SF_raw=float(per_event[0]),
            geometry_status="derived",
            source="confirmed valley candidate + parser face geometry",
            zone=_zone, gx=_gx, gy=_gy, face_id=face_id,
        ))
        derivation_report.append({
            "component": str(row.get("label", f"{face_id}:{valley_id}")),
            "status": "derived",
            "source": "valley candidate bordering_roof_face_ids validated the confirmed face; parser built the facet and valley event",
        })

    for item in confirmed_selection.get("multi_valley_facets", []):
        row = _confirmed_mapping(item)
        face_id = str(row["face_id"])
        valley_ids = tuple(str(v) for v in row.get("valley_ids", ()))
        for valley_id in valley_ids:
            cand = _require_candidate(valley_candidates, valley_id, "valley")
            _require_bordering_face(cand, face_id)
        facet_geom = geom.engine_facet(face_id)
        _per_event, area, _zone, _gx, _gy = affected_area(
            facet_geom.facet,
            [geom.valley_event_for_face(face_id, valley_id) for valley_id in valley_ids],
            penetrations=_penetrations_with_user_footprints(geom, confirmed_selection, face_id),  # XML + confirmed user dimensioned footprint holes
            return_zone=True,
        )
        components.append(Module1ComponentResult(
            label=str(row.get("label", f"{face_id}:multi-valley")),
            affected_SF_raw=float(area),
            geometry_status="derived",
            source="confirmed multi-valley candidate set + parser face geometry",
            zone=_zone, gx=_gx, gy=_gy, face_id=face_id,
        ))
        derivation_report.append({
            "component": str(row.get("label", f"{face_id}:multi-valley")),
            "status": "derived",
            "source": "all valley ids validated against emitted valley candidates bordering the confirmed face; area comes from frozen affected_area",
        })

    for item in confirmed_selection.get("penetration_appurtenance_repairs", []):
        row = _confirmed_mapping(item)
        penetration_id = str(row["penetration_face_id"])
        cand = _require_candidate(penetration_candidates, penetration_id, "penetration")
        host_face_id = str(row.get("host_face_id") or cand.params["host_facet_id"])
        if host_face_id != cand.params["host_facet_id"]:
            raise ValueError(f"penetration {penetration_id} is not hosted by {host_face_id}")
        # THE FAN CARVES. THE COVER DOES NOT. Module 1 feeds the DIAGRAM; module2_assembly feeds the
        # SCOPE. Both import the SAME predicate from shared_category_registry, because this project
        # has shipped "the engine computed it correctly and a downstream path disagreed" five times
        # and the v56 transition-band bug was exactly two zone derivations drifting apart. A
        # cover-only power vent produces an EMPTY zone here, so the diagram shades nothing and its
        # totals stay equal to the scope's by construction.
        if not appurtenance_carves(row):
            area, _zone, _gx, _gy, _zone_face_id = 0.0, None, None, None, host_face_id
        elif host_face_id in _repair_facet_ids:
            area, _zone, _gx, _gy, _zone_face_id = _appurtenance_net_affected_area(geom, host_face_id, cand, confirmed_selection)
        else:
            area, _zone, _gx, _gy, _zone_face_id = _appurtenance_affected_area(geom, host_face_id, cand, confirmed_selection)
        components.append(Module1ComponentResult(
            label=str(row.get("label", f"{host_face_id}:{penetration_id}:appurtenance")),
            affected_SF_raw=float(area),
            geometry_status="derived",
            source="confirmed penetration candidate + parser appurtenance footprint",
            zone=_zone, gx=_gx, gy=_gy, face_id=_zone_face_id,
        ))
        derivation_report.append({
            "component": str(row.get("label", f"{host_face_id}:{penetration_id}:appurtenance")),
            "status": "derived",
            "source": "host facet and appurtenance footprint come from the penetration candidate emitted from parser children",
        })

    for item in confirmed_selection.get("user_appurtenance_repairs", []):
        row = _confirmed_mapping(item)
        if not bool(row.get("repair_event", True)):
            continue
        host_face_id = str(row["host_facet_id"])
        cand = _user_appurtenance_candidate_from_row(row)
        if host_face_id in _repair_facet_ids:
            area, _zone, _gx, _gy, _zone_face_id = _appurtenance_net_affected_area(geom, host_face_id, cand, confirmed_selection)
        else:
            area, _zone, _gx, _gy, _zone_face_id = _appurtenance_affected_area(geom, host_face_id, cand, confirmed_selection)
        label = str(row.get("designator") or row.get("label") or f"{host_face_id}:user-appurtenance")
        components.append(Module1ComponentResult(
            label=label,
            affected_SF_raw=float(area),
            geometry_status="derived",
            source="confirmed user-defined appurtenance footprint",
            zone=_zone, gx=_gx, gy=_gy, face_id=_zone_face_id,
        ))
        derivation_report.append({
            "component": label,
            "status": "derived",
            "source": "host facet and user-entered appurtenance footprint supplied by confirmed selection",
        })

    for item in confirmed_selection.get("notch_repairs", []):
        row = _confirmed_mapping(item)
        member_face_ids = tuple(str(v) for v in row["member_face_ids"])
        cand = _require_notch_candidate(notch_candidates, member_face_ids)
        area, _zone, _gx, _gy = _derived_notch_union_area(geom, cand, confirmed_selection, override_valley_ids=row.get("valley_ids"))
        components.append(Module1ComponentResult(
            label=str(row.get("label", ":".join(member_face_ids) + ":notch")),
            affected_SF_raw=float(area),
            geometry_status="derived",
            source="confirmed notch candidate + derived RIDGE anchor and bordering VALLEY events",
            zone=_zone, gx=_gx, gy=_gy, face_id="+".join(member_face_ids),
        ))
        derivation_report.append({
            "component": str(row.get("label", ":".join(member_face_ids) + ":notch")),
            "status": "derived",
            "source": "notch candidate supplies member faces, merged facet, notch polygon, RIDGE anchor, and VALLEY event ids; frozen affected_area computes the area",
        })

    selected_valley_ids = [str(v) for v in confirmed_selection.get("selected_valley_ids", [])]
    selected_meta = selected_valley_handoff(xml_text, selected_valley_ids) if selected_valley_ids else {"selected_valley_LF_total": 0.0}
    selected_lf = float(selected_meta["selected_valley_LF_total"])

    scope_lines = []
    for component in components:
        scope_lines.extend(expand_scope(M1Interface(affected_SF=component.affected_SF_raw), repair_factor=1.0))
    if selected_lf > 0:
        scope_lines.extend(expand_scope(M1Interface(affected_SF=0.0, valley_LF_in_scope=selected_lf), repair_factor=1.0))

    raw_total = sum(component.affected_SF_raw for component in components)
    display_total = round(sum(round(component.affected_SF_raw, 1) for component in components), 1)
    shake_ea = sum(line.qty for line in scope_lines if line.category_id == "SHAKE_FIELD_RR")

    return Module1ServiceResult(
        candidate_package=package,
        components=components,
        selected_valley_LF_total=selected_lf,
        scope_lines=scope_lines,
        affected_SF_raw_total=float(raw_total),
        affected_SF_display=float(display_total),
        affected_SQ_raw=float(raw_total / 100.0),
        affected_SQ_display=float(round(display_total / 100.0, 3)),
        shake_EA=int(shake_ea),
        derivation_report=derivation_report,
    )



def _appurtenance_net_affected_area(geom: EagleViewGeometry, host_face_id: str, candidate: Candidate, confirmed_selection: Mapping[str, object]):
    merged_candidate = _merged_candidate_for_member_face(geom, host_face_id)
    if merged_candidate is not None:
        return _merged_appurtenance_net_affected_area(geom, merged_candidate, candidate, confirmed_selection)

    engine_face = geom.engine_facet(host_face_id)
    repair_events = []
    for item in confirmed_selection.get("single_valley_repairs", ()):
        row = _confirmed_mapping(item)
        if str(row["face_id"]) == host_face_id:
            repair_events.append(geom.valley_event_for_face(host_face_id, str(row["valley_id"])))
    for item in confirmed_selection.get("multi_valley_facets", ()):
        row = _confirmed_mapping(item)
        if str(row["face_id"]) == host_face_id:
            repair_events.extend(geom.valley_event_for_face(host_face_id, str(v)) for v in row.get("valley_ids", ()))

    _per_app, _app_area, app_zone, gx, gy = affected_area(
        engine_face.facet,
        [],
        appurtenances=[dict(candidate.params["appurtenance_geometry"])],
        penetrations=_penetrations_with_user_footprints(geom, confirmed_selection, host_face_id),
        return_zone=True,
    )
    if not repair_events:
        return float(_app_area), app_zone, gx, gy, host_face_id
    _per_repair, _repair_area, repair_zone, _gx, _gy = affected_area(
        engine_face.facet,
        repair_events,
        penetrations=_penetrations_with_user_footprints(geom, confirmed_selection, host_face_id),
        return_zone=True,
    )
    cell = float((gx[1] - gx[0]) * (gy[1] - gy[0]))
    net_zone = (np.asarray(app_zone, bool) & ~np.asarray(repair_zone, bool))
    net_zone = _filter_subshake_components(net_zone, gx, gy)
    return float(net_zone.sum() * cell), net_zone, gx, gy, host_face_id


def _merged_appurtenance_net_affected_area(geom: EagleViewGeometry, notch_candidate: Candidate, appurtenance_candidate: Candidate, confirmed_selection: Mapping[str, object]):
    anchor_line = geom.lines[str(notch_candidate.params["anchor_line_id"])]
    frame_ids = tuple(str(pid) for pid in notch_candidate.params["frame_point_ids"])
    frame = mkframe_pts(
        [geom.points[pid] for pid in frame_ids],
        geom.points[anchor_line.path[0]],
        geom.points[anchor_line.path[-1]],
    )
    facet = [tuple(float(v) for v in frame(geom.points[str(pid)])) for pid in notch_candidate.params["merged_facet_point_ids"]]
    notches = [
        [tuple(float(v) for v in frame(geom.points[str(pid)])) for pid in notch_ids]
        for notch_ids in notch_candidate.params["notch_polygon_point_ids"]
    ]
    pens = []
    for member_face_id in notch_candidate.params["member_face_ids"]:
        member_face = geom.faces.get(str(member_face_id))
        for child_id in (member_face.children if member_face else []):
            pen_face = geom.penetration_faces.get(child_id)
            if pen_face is not None and getattr(pen_face, "size", 0) > 0:
                pens.append([tuple(float(v) for v in frame(geom.points[pid])) for pid in geom.ordered_face_point_ids(child_id)])
    pens.extend(_user_footprints_for_merged_members(geom, confirmed_selection, notch_candidate.params["member_face_ids"], frame))
    holes = _dimensional_pens(pens)
    app = _candidate_appurtenance_geometry_in_frame(geom, appurtenance_candidate, frame)
    _per_app, _app_area, app_zone, gx, gy = affected_area(
        facet, [], notches=notches, appurtenances=[app], penetrations=holes, return_zone=True
    )

    member_set = {str(v) for v in notch_candidate.params.get("member_face_ids", ())}
    repair_masks = []
    for item in confirmed_selection.get("notch_repairs", ()):
        row = _confirmed_mapping(item)
        if {str(v) for v in row.get("member_face_ids", ())} == member_set:
            valley_ids = tuple(str(v) for v in row.get("valley_ids", notch_candidate.params["bordering_valley_line_ids"]))
            valley_events = [_valley_event_for_notch(geom, notch_candidate, frame, facet, valley_id) for valley_id in valley_ids]
            _per_r, _area_r, z_r, _gx, _gy = affected_area(
                facet, valley_events, notches=notches, penetrations=holes, return_zone=True
            )
            repair_masks.append(np.asarray(z_r, bool))
    if not repair_masks:
        return float(_app_area), app_zone, gx, gy, "+".join(str(v) for v in notch_candidate.params["member_face_ids"])
    repair_union = np.logical_or.reduce(repair_masks)
    cell = float((gx[1] - gx[0]) * (gy[1] - gy[0]))
    net_zone = (np.asarray(app_zone, bool) & ~repair_union)
    net_zone = _filter_subshake_components(net_zone, gx, gy)
    return float(net_zone.sum() * cell), net_zone, gx, gy, "+".join(str(v) for v in notch_candidate.params["member_face_ids"])

def _appurtenance_affected_area(geom: EagleViewGeometry, host_face_id: str, candidate: Candidate, confirmed_selection: Mapping[str, object] | None = None):
    merged_candidate = _merged_candidate_for_member_face(geom, host_face_id)
    if merged_candidate is not None:
        return _merged_appurtenance_affected_area(geom, merged_candidate, candidate, confirmed_selection or {})

    facet_geom = geom.engine_facet(host_face_id)
    _per_event, area, zone, gx, gy = affected_area(
        facet_geom.facet,
        [],
        appurtenances=[dict(candidate.params["appurtenance_geometry"])],
        penetrations=_penetrations_with_user_footprints(geom, confirmed_selection or {}, host_face_id),
        return_zone=True,
    )
    return float(area), zone, gx, gy, host_face_id


def _merged_candidate_for_member_face(geom: EagleViewGeometry, face_id: str) -> Candidate | None:
    for candidate in emit_notch_candidates(geom):
        if str(face_id) in {str(v) for v in candidate.params.get("member_face_ids", ())}:
            return candidate
    return None


def _merged_appurtenance_affected_area(geom: EagleViewGeometry, notch_candidate: Candidate, appurtenance_candidate: Candidate, confirmed_selection: Mapping[str, object] | None = None):
    anchor_line_id = str(notch_candidate.params["anchor_line_id"])
    anchor_line = geom.lines[anchor_line_id]
    frame_ids = tuple(str(pid) for pid in notch_candidate.params["frame_point_ids"])
    frame = mkframe_pts(
        [geom.points[pid] for pid in frame_ids],
        geom.points[anchor_line.path[0]],
        geom.points[anchor_line.path[-1]],
    )
    facet = [tuple(float(v) for v in frame(geom.points[str(pid)])) for pid in notch_candidate.params["merged_facet_point_ids"]]
    notches = [
        [tuple(float(v) for v in frame(geom.points[str(pid)])) for pid in notch_ids]
        for notch_ids in notch_candidate.params["notch_polygon_point_ids"]
    ]
    pens = []
    for member_face_id in notch_candidate.params["member_face_ids"]:
        member_face = geom.faces.get(str(member_face_id))
        for child_id in (member_face.children if member_face else []):
            pen_face = geom.penetration_faces.get(child_id)
            if pen_face is not None and getattr(pen_face, "size", 0) > 0:
                pens.append([tuple(float(v) for v in frame(geom.points[pid])) for pid in geom.ordered_face_point_ids(child_id)])
    pens.extend(_user_footprints_for_merged_members(geom, confirmed_selection or {}, notch_candidate.params["member_face_ids"], frame))
    app = _candidate_appurtenance_geometry_in_frame(geom, appurtenance_candidate, frame)
    _per_event, area, zone, gx, gy = affected_area(
        facet,
        [],
        notches=notches,
        appurtenances=[app],
        penetrations=_dimensional_pens(pens),
        return_zone=True,
    )
    return float(area), zone, gx, gy, "+".join(str(v) for v in notch_candidate.params["member_face_ids"])


def _penetrations_with_user_footprints(geom: EagleViewGeometry, confirmed_selection: Mapping[str, object], face_id: str):
    """Return XML dimensional penetrations plus confirmed user dimensioned footprint holes in facet-local frame."""
    engine_face = geom.engine_facet(str(face_id))
    pens = list(_dimensional_pens(engine_face.penetrations))
    pens.extend(_user_footprints_for_face(confirmed_selection, str(face_id)))
    return _dimensional_pens(pens)


def _user_footprints_for_face(confirmed_selection: Mapping[str, object], face_id: str):
    out = []
    for item in confirmed_selection.get("user_appurtenance_repairs", ()):  # type: ignore[union-attr]
        row = _confirmed_mapping(item)
        if str(row.get("host_facet_id")) != str(face_id):
            continue
        poly = _user_footprint_polygon_local(row)
        if poly is not None:
            out.append(poly)
    return out


def _user_footprints_for_merged_members(geom: EagleViewGeometry, confirmed_selection: Mapping[str, object], member_face_ids, frame):
    member_set = {str(v) for v in member_face_ids}
    out = []
    for item in confirmed_selection.get("user_appurtenance_repairs", ()):  # type: ignore[union-attr]
        row = _confirmed_mapping(item)
        host_face_id = str(row.get("host_facet_id"))
        if host_face_id not in member_set:
            continue
        poly = _user_footprint_polygon_local(row)
        if poly is None:
            continue
        transformed = []
        for x, y in poly:
            pt3 = _face_local_point_to_3d(geom, host_face_id, float(x), float(y))
            transformed.append(tuple(float(v) for v in frame(pt3)))
        out.append(transformed)
    return out


def _user_footprint_polygon_local(row: Mapping[str, object]):
    """Raw dimensioned user footprint (not the 21in band) as a facet-local hole polygon."""
    shape = str(row.get("shape") or row.get("appurtenance_shape") or "point").lower()
    if shape != "dimensioned":
        return None
    position = row.get("position")
    if not isinstance(position, Mapping):
        return None
    try:
        cx = float(position["x"]); cy = float(position["y"])
        w = float(row.get("width", 0.0)); h = float(row.get("height", 0.0))
    except (TypeError, ValueError, KeyError):
        return None
    if not (w > 0 and h > 0 and w * h >= _DIM_MIN_SF):
        return None
    hw = w / 2.0; hh = h / 2.0
    return [(cx - hw, cy - hh), (cx + hw, cy - hh), (cx + hw, cy + hh), (cx - hw, cy + hh)]


def _user_appurtenance_candidate_from_row(row: Mapping[str, object]) -> Candidate:
    host_face_id = str(row["host_facet_id"])
    position = row.get("position")
    if not isinstance(position, Mapping):
        raise ValueError("user appurtenance requires position {x, y}")
    x = float(position["x"])
    y = float(position["y"])
    shape = str(row.get("shape") or row.get("appurtenance_shape") or "point").lower()
    if shape == "dimensioned":
        w = float(row.get("width", 0.0))
        h = float(row.get("height", 0.0))
        if not (w > 0 and h > 0):
            raise ValueError("dimensioned user appurtenance requires positive width and height")
        app_geom = {"cx": x, "cy": y, "w": w, "h": h, "kind": "dimensioned"}
    elif shape == "point":
        app_geom = {"cx": x, "cy": y, "kind": "point"}
    else:
        raise ValueError(f"unknown user appurtenance shape {shape!r}")
    return Candidate(
        kind="appurtenance",
        source_ids=(str(row.get("designator") or row.get("label") or "user"),),
        origin="user",
        confirmed=False,
        params={
            "host_facet_id": host_face_id,
            "position": {"x": x, "y": y},
            "width": app_geom.get("w"),
            "height": app_geom.get("h"),
            "appurtenance_shape": shape,
            "appurtenance_geometry": app_geom,
            "kind_label": str(row.get("kind_label") or "OTHER"),
            "designator": str(row.get("designator") or row.get("label") or "user"),
        },
    )


def _candidate_appurtenance_geometry_in_frame(geom: EagleViewGeometry, candidate: Candidate, frame) -> Mapping[str, float | str]:
    params = candidate.params
    if params.get("penetration_face_id"):
        return _appurtenance_geometry_in_frame(geom, str(params["penetration_face_id"]), frame)
    app = params.get("appurtenance_geometry")
    if not isinstance(app, Mapping):
        raise ValueError("appurtenance candidate missing appurtenance_geometry")
    host_face_id = str(params["host_facet_id"])
    center = _face_local_point_to_3d(geom, host_face_id, float(app["cx"]), float(app["cy"]))
    cx, cy = (float(v) for v in frame(center))
    if app.get("kind") == "point":
        return {"cx": cx, "cy": cy, "kind": "point"}
    return {"cx": cx, "cy": cy, "w": float(app["w"]), "h": float(app["h"]), "kind": "dimensioned"}


def _face_local_point_to_3d(geom: EagleViewGeometry, face_id: str, x_local: float, y_local: float):
    face = geom.faces[str(face_id)]
    point_ids = geom.ordered_face_point_ids(str(face_id))
    anchor_line_id = next((lid for lid in face.line_ids if geom.lines[lid].type == "EAVE"), face.line_ids[0])
    anchor_path = geom.lines[anchor_line_id].path
    pp = [np.array(geom.points[pid], dtype=float) for pid in point_ids]
    nrm = np.zeros(3)
    for i in range(len(pp)):
        nrm += np.cross(pp[i], pp[(i + 1) % len(pp)])
    nrm /= np.linalg.norm(nrm)
    if nrm[2] < 0:
        nrm = -nrm
    g = np.array([0.0, 0.0, -1.0])
    fall = g - np.dot(g, nrm) * nrm
    fall /= np.linalg.norm(fall)
    up = -fall
    x_axis = np.cross(up, nrm)
    x_axis /= np.linalg.norm(x_axis)
    er = np.array(geom.points[anchor_path[-1]], dtype=float) - np.array(geom.points[anchor_path[0]], dtype=float)
    if np.dot(x_axis, er) < 0:
        x_axis = -x_axis
    origin = pp[0]
    return origin + float(x_local) * x_axis + float(y_local) * up


def _appurtenance_geometry_in_frame(geom: EagleViewGeometry, penetration_id: str, frame) -> Mapping[str, float | str]:
    pts = [np.array(frame(geom.points[pid]), dtype=float) for pid in geom.ordered_face_point_ids(penetration_id)]
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return {
        "cx": float((min(xs) + max(xs)) / 2.0),
        "cy": float((min(ys) + max(ys)) / 2.0),
        "w": float(max(xs) - min(xs)),
        "h": float(max(ys) - min(ys)),
        "kind": "dimensioned",
    }


def _derived_notch_union_area(geom: EagleViewGeometry, candidate: Candidate, confirmed_selection: Mapping[str, object] | None = None, override_valley_ids=None):
    anchor_line_id = str(candidate.params["anchor_line_id"])
    anchor_line = geom.lines[anchor_line_id]
    frame_ids = tuple(str(pid) for pid in candidate.params["frame_point_ids"])
    frame = mkframe_pts(
        [geom.points[pid] for pid in frame_ids],
        geom.points[anchor_line.path[0]],
        geom.points[anchor_line.path[-1]],
    )
    facet = [tuple(frame(geom.points[pid])) for pid in candidate.params["merged_facet_point_ids"]]
    notches = [
        [tuple(frame(geom.points[pid])) for pid in notch_ids]
        for notch_ids in candidate.params["notch_polygon_point_ids"]
    ]
    valleys = [
        _valley_event_for_notch(geom, candidate, frame, facet, str(line_id))
        for line_id in (override_valley_ids if override_valley_ids else candidate.params["bordering_valley_line_ids"])
    ]
    _notch_pens = []
    for _mfid in candidate.params["member_face_ids"]:
        _mface = geom.faces.get(str(_mfid))
        for _cid in (_mface.children if _mface else []):
            _pf = geom.penetration_faces.get(_cid)
            if _pf is not None and getattr(_pf, "size", 0) > 0:
                _notch_pens.append([tuple(frame(geom.points[pid])) for pid in geom.ordered_face_point_ids(_cid)])
    _notch_pens.extend(_user_footprints_for_merged_members(geom, confirmed_selection or {}, candidate.params["member_face_ids"], frame))
    _per_event, area, _zone, _gx, _gy = affected_area(facet, valleys, notches=notches, penetrations=_dimensional_pens(_notch_pens), return_zone=True)
    return float(area), _zone, _gx, _gy


def _valley_event_for_notch(geom: EagleViewGeometry, candidate: Candidate, frame, facet, line_id: str):
    line = geom.lines[line_id]
    a_id, b_id = line.path[0], line.path[-1]
    apex_id, start_id = (a_id, b_id) if geom.points[a_id][2] >= geom.points[b_id][2] else (b_id, a_id)
    start = np.array(frame(geom.points[start_id]), dtype=float)
    apex = np.array(frame(geom.points[apex_id]), dtype=float)
    fan = _notch_valley_fan(geom, candidate, frame, facet, line_id)
    return (tuple(float(v) for v in start), tuple(float(v) for v in apex), int(fan))


def _winding_fan(poly, p0, p1):
    _pn = np.asarray(poly, dtype=float)[:, :2]; _n = len(_pn)
    _sa = 0.0
    for _i in range(_n):
        _x1,_y1=_pn[_i]; _x2,_y2=_pn[(_i+1)%_n]; _sa += _x1*_y2 - _x2*_y1
    _ccw = _sa > 0
    def _cv(pt): return min(range(_n), key=lambda i:(_pn[i][0]-pt[0])**2+(_pn[i][1]-pt[1])**2)
    _si=_cv(p0); _ai=_cv(p1); _ed=None
    if _ai==(_si+1)%_n: _ed=_pn[_ai]-_pn[_si]
    elif _si==(_ai+1)%_n: _ed=_pn[_si]-_pn[_ai]
    if _ed is None: return None
    _l=float(np.hypot(_ed[0],_ed[1]))
    if _l<1e-9: return None
    _ed=_ed/_l; _nl=np.array([-_ed[1],_ed[0]]); _inw=_nl if _ccw else -_nl
    if abs(_inw[0])<1e-9: return None
    return 1 if _inw[0]>0 else -1


def _notch_valley_fan(geom: EagleViewGeometry, candidate: Candidate, frame, facet, line_id: str) -> int:
    from geometry_core import excluded_region_aware_notch_fan
    line = geom.lines[line_id]
    seg_a = tuple(float(v) for v in frame(geom.points[line.path[0]])[:2])
    seg_b = tuple(float(v) for v in frame(geom.points[line.path[-1]])[:2])
    holes = [[tuple(float(v) for v in frame(geom.points[pid])[:2]) for pid in poly]
             for poly in candidate.params["notch_polygon_point_ids"]]
    return excluded_region_aware_notch_fan(facet, holes, seg_a, seg_b)


def _face_centroid_x(frame, geom: EagleViewGeometry, face_id: str) -> float:
    pts = [np.array(frame(geom.points[pid]), dtype=float) for pid in geom.ordered_face_point_ids(face_id)]
    return float(np.mean(pts, axis=0)[0])


def _cycle_edges(ids: Sequence[str]):
    return {_edge_key(a, b) for a, b in zip(ids, list(ids[1:]) + [ids[0]])}


def _edge_key(a: str, b: str) -> Tuple[str, str]:
    return tuple(sorted((a, b), key=_id_sort_key))  # type: ignore[return-value]


def _id_sort_key(value: str) -> Tuple[str, int]:
    prefix = "".join(ch for ch in value if not ch.isdigit())
    number = int("".join(ch for ch in value if ch.isdigit()) or "0")
    return (prefix, number)


def _require_candidate(candidates: Mapping[str, Candidate], source_id: str, kind: str) -> Candidate:
    try:
        cand = candidates[source_id]
    except KeyError as exc:
        raise ValueError(f"confirmed {kind} source id {source_id!r} was not emitted as a candidate") from exc
    return cand


def _require_notch_candidate(candidates: Mapping[Tuple[str, ...], Candidate], member_face_ids: Tuple[str, ...]) -> Candidate:
    key = tuple(sorted(member_face_ids, key=_id_sort_key))
    try:
        return candidates[key]
    except KeyError as exc:
        raise ValueError(f"confirmed notch member face ids {member_face_ids!r} were not emitted as a notch candidate") from exc


def _require_bordering_face(candidate: Candidate, face_id: str) -> None:
    bordering = tuple(candidate.params.get("bordering_roof_face_ids", ()))
    if face_id not in bordering:
        raise ValueError(f"face {face_id!r} does not border candidate {candidate.source_ids}")


def _confirmed_mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError("confirmed selection entries must be mappings")
    return value
