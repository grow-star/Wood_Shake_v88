#!/usr/bin/env python3
# CHANGELOG 2026-07-04: notch valley_ids threaded from UI; fallback preserves anchor 3691.
"""Build 1.5: whole-roof layout export for the Workbench UI.

This module surfaces the raw EagleView geometry already parsed by
``eagleview_geometry_parser``. It performs no scope, affected-area, repair-zone,
or Module 2 quantity calculations. The output is a blank/clickable roof layout:
all roof facets, all valley lines, all penetration faces, and drawing bounds in
one shared roof coordinate frame.
"""

from __future__ import annotations

import json
import os
from typing import Any, Callable, Iterable, Mapping, Sequence

import numpy as np

import math
from transition_enumerator import confirmed_transitions, enumerate_transition_candidates
from eagleview_geometry_parser import EagleViewGeometry, parse_eagleview_geometry, _frame_anchor_line

Point2List = list[float]


def build_roof_layout(geom_or_xml: EagleViewGeometry | str) -> dict[str, Any]:
    """Return the whole roof inventory/layout in a shared drawing frame.

    ``geom_or_xml`` may be a parsed ``EagleViewGeometry`` object, EagleView XML
    text, or a filesystem path to an EagleView XML text file. All coordinates are
    read from the parser's global POINT coordinates and therefore share one roof
    frame; per-facet local engine frames are not used here.
    """

    geom = _resolve_geometry(geom_or_xml)

    facets = [_facet_payload(geom, fid) for fid in sorted(geom.roof_faces, key=_id_sort_key)]
    valleys = [_valley_payload(geom, lid) for lid in sorted(geom.valley_lengths, key=_id_sort_key)]
    transitions = [_transition_payload(geom, t) for t in confirmed_transitions(geom)]
    ridges = [_ridge_payload(geom, lid) for lid, ln in sorted(geom.lines.items(), key=lambda kv: _id_sort_key(kv[0]))
              if getattr(ln, "type", None) == "RIDGE"]
    facet_adjacency = _facet_adjacency(geom)
    penetrations = [
        _penetration_payload(geom, pid)
        for pid in sorted(geom.penetration_faces, key=_id_sort_key)
    ]

    roof_bounds = _bounds_for_points(
        point for facet in facets for point in facet["polygon"]
    )

    # Parser-sourced area receipts. The 22 roof-face sizes are kept separate
    # from penetration-face sizes so this endpoint does not hide what the XML
    # actually supplied.
    facet_area_sum = round(sum(float(f["area_SF"] or 0.0) for f in facets), 3)
    penetration_area_sum = round(
        sum(float(p.get("area_SF") or 0.0) for p in penetrations), 3
    )

    # Merged-slope facets: face groups Module 1 flags as one physical slope split by a
    # HIDDEN line. Surfaced so page2 can route member-facet picks into a per-valley notch
    # (union across the hidden line) instead of separate singles.
    from notch_candidate_emitter import emit_notch_candidates as _emit_notch
    merged_slopes = []
    for _c in _emit_notch(geom):
        _members = [str(f) for f in _c.params["member_face_ids"]]
        _vs = []
        for _fid in _members:
            for _lid in geom.roof_faces[_fid].line_ids:
                if getattr(geom.lines[_lid], "type", "") == "VALLEY" and _lid not in _vs:
                    _vs.append(_lid)
        merged_slopes.append({
            "member_face_ids": _members,
            "valley_line_ids": sorted(_vs, key=_id_sort_key),
        })

    return {
        "facets": facets,
        "valleys": valleys,
        "transitions": transitions,
        "ridges": ridges,                     # ridge runs — the user may mark one VENTED (not a repair event)
        "facet_adjacency": facet_adjacency,   # {face_id: [face_id, ...]} — facets sharing an edge
        "merged_slopes": merged_slopes,
        "penetrations": penetrations,
        "roof_bounds": roof_bounds,
        "area_summary": {
            "facet_area_SF_sum": facet_area_sum,
            "penetration_area_SF_sum": penetration_area_sum,
            "facet_plus_penetration_area_SF_sum": round(facet_area_sum + penetration_area_sum, 3),
        },
    }


def _resolve_geometry(geom_or_xml: EagleViewGeometry | str) -> EagleViewGeometry:
    if isinstance(geom_or_xml, EagleViewGeometry):
        return geom_or_xml
    if not isinstance(geom_or_xml, str):
        raise TypeError("build_roof_layout expects EagleViewGeometry, XML text, or XML path")

    text = geom_or_xml
    if "<" not in text[:200] and os.path.exists(text):
        with open(text, "r", encoding="utf-8") as fh:
            text = fh.read()
    return parse_eagleview_geometry(text)


def _steep_tier_for_pitch(pitch):
    """Same rule the engine applies (module2_assembly._steep_tier_for_pitch) — read-only, for display."""
    try:
        p = float(pitch)
    except (TypeError, ValueError):
        return None
    if p >= 13:
        return ">12"
    if p >= 10:
        return "10-12"
    if p >= 7:
        return "7-9"
    return None


def _facet_payload(geom: EagleViewGeometry, face_id: str) -> dict[str, Any]:
    face = geom.roof_faces[face_id]
    point_ids = geom.ordered_face_point_ids(face_id)
    polygon = [_xy(geom.points[pid]) for pid in point_ids]
    bounds = _bounds_for_points(polygon)
    local_to_shared = _facet_affine_payload(geom, face_id)
    return {
        "facet_id": face.id,
        "designator": face.designator,
        # v65 structure separation: which <ROOF> this facet belongs to, so page 2 can label facets by
        # structure when a roof has more than one. Additive; "" when the XML has no ROOF nesting.
        "structure_id": getattr(face, "structure_id", "") or "",
        # STEEP is geometry — the engine derives the tier from the pitch, and the user confirms
        # nothing. Both are surfaced so the user can SEE what the engine derived: the lesson from the
        # transitions build was that hidden engine work makes users invent workarounds.
        "pitch": float(getattr(face, "pitch", 0.0) or 0.0),
        "steep_tier": _steep_tier_for_pitch(getattr(face, "pitch", None)),
        "polygon": polygon,
        "area_SF": _round_area(face.size),
        "unrounded_area_SF": _round_area(face.unrounded_size),
        "point_ids": point_ids,
        "bounds": bounds,
        "local_to_shared": local_to_shared,
    }



def _facet_affine_payload(geom: EagleViewGeometry, face_id: str) -> dict[str, Point2List]:
    """Expose the exact local->shared affine used by diagram mask drawing."""
    to_shared = _facet_local_to_shared(geom, face_id)
    origin = to_shared((0.0, 0.0))
    one_u = to_shared((1.0, 0.0))
    one_v = to_shared((0.0, 1.0))
    return {
        "origin": origin,
        "du": [round(float(one_u[0]) - float(origin[0]), 6), round(float(one_u[1]) - float(origin[1]), 6)],
        "dv": [round(float(one_v[0]) - float(origin[0]), 6), round(float(one_v[1]) - float(origin[1]), 6)],
    }


def _facet_local_to_shared(geom: EagleViewGeometry, face_id: str) -> Callable[[Sequence[float]], Point2List]:
    face = geom.faces[str(face_id)]
    point_ids = geom.ordered_face_point_ids(str(face_id))
    anchor_line_id = _frame_anchor_line(face.line_ids, geom.lines)
    anchor_path = geom.lines[anchor_line_id].path
    return _local_to_shared_transform(
        [geom.points[pid] for pid in point_ids],
        geom.points[anchor_path[0]],
        geom.points[anchor_path[-1]],
    )


def _local_to_shared_transform(
    points3d_order: Sequence[Sequence[float]],
    eave_a: Sequence[float],
    eave_b: Sequence[float],
) -> Callable[[Sequence[float]], Point2List]:
    """Return the bridge from engine facet-local coordinates to shared roof x/y."""
    pp = [np.asarray(p, dtype=float) for p in points3d_order]
    nrm = np.zeros(3, dtype=float)
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
    er = np.asarray(eave_b, dtype=float) - np.asarray(eave_a, dtype=float)
    if np.dot(x_axis, er) < 0:
        x_axis = -x_axis
    origin = pp[0]

    def to_shared(local_point: Sequence[float]) -> Point2List:
        u = float(local_point[0])
        v = float(local_point[1])
        p3d = origin + (u * x_axis) + (v * up)
        return _xy(p3d)

    return to_shared

def _valley_payload(geom: EagleViewGeometry, line_id: str) -> dict[str, Any]:
    line = geom.lines[line_id]
    path = list(line.path)
    if len(path) < 2:
        raise ValueError(f"valley {line_id} has fewer than two points")
    endpoints = [_xy(geom.points[path[0]]), _xy(geom.points[path[-1]])]
    return {
        "valley_id": line_id,
        "line": endpoints,
        "length_LF": round(float(geom.valley_lengths[line_id]), 2),
        "bordering_facet_ids": _bordering_roof_faces(geom, line_id),
    }


def _facet_adjacency(geom: EagleViewGeometry) -> dict[str, list[str]]:
    """{face_id: [adjacent face_id, ...]} — two facets are adjacent iff they SHARE AN EDGE.

    Reuses the SAME shared-edge enumeration the transition detector walks
    (`enumerate_transition_candidates`), rather than inventing a second notion of adjacency that
    could drift from it. This is what constrains appurtenance grouping: EagleView splits one physical
    chimney into one marker per facet it crosses, and those facets necessarily share an edge — so a
    marker may only ever be linked to a marker on an ADJACENT facet, never one across the roof.
    """
    adjacency: dict[str, set[str]] = {}
    for candidate in enumerate_transition_candidates(geom):
        a, b = str(candidate.face_a_id), str(candidate.face_b_id)
        adjacency.setdefault(a, set()).add(b)
        adjacency.setdefault(b, set()).add(a)
    return {face: sorted(neighbours, key=_id_sort_key) for face, neighbours in sorted(adjacency.items(), key=lambda kv: _id_sort_key(kv[0]))}


def _ridge_payload(geom: EagleViewGeometry, line_id: str) -> dict[str, Any]:
    """A RIDGE, surfaced so the UI can draw it and the user can mark it VENTED.

    A ridge vent is NOT a repair event: it creates no affected area and carves nothing. It is a
    material item on a ridge run that is ALREADY in scope — so the UI needs the ridge only to draw
    it and identify it; the CONTACTED length (which bounds the vent) comes from the engine's compute,
    because contact depends on the user's repair selections, not on the geometry alone.
    """
    line = geom.lines[line_id]
    path = list(line.path)
    return {
        "edge_id": line_id,
        "line": [_xy(geom.points[path[0]]), _xy(geom.points[path[-1]])],
        "length_LF": round(float(_polyline_length(geom, path)), 2),
    }


def _polyline_length(geom: EagleViewGeometry, path) -> float:
    total = 0.0
    for a, b in zip(path, path[1:]):
        pa, pb = geom.points[a], geom.points[b]
        total += math.dist((pa[0], pa[1], pa[2]), (pb[0], pb[1], pb[2]))
    return total


def _transition_payload(geom: EagleViewGeometry, transition) -> dict[str, Any]:
    """A DETECTED pitch transition, surfaced to the UI so it can be drawn (dotted) and selected.
    Read-only: the UI can never create, move, or re-length one — edge_total_LF is geometric truth."""
    line = geom.lines[transition.edge_id]
    path = list(line.path)
    return {
        "edge_id": transition.edge_id,
        "line": [_xy(geom.points[path[0]]), _xy(geom.points[path[-1]])],
        "length_LF": round(float(transition.edge_total_LF), 2),
        "face_a_id": transition.face_a_id,
        "face_b_id": transition.face_b_id,
        "face_a_designator": transition.face_a_designator,
        "face_b_designator": transition.face_b_designator,
        "pitch_a": float(transition.pA),
        "pitch_b": float(transition.pB),
    }


def _penetration_payload(geom: EagleViewGeometry, penetration_id: str) -> dict[str, Any]:
    face = geom.penetration_faces[penetration_id]
    point_ids = geom.ordered_face_point_ids(penetration_id)
    polygon = [_xy(geom.points[pid]) for pid in point_ids]
    payload: dict[str, Any] = {
        "penetration_id": penetration_id,
        "host_facet_id": _host_facet_id(geom, penetration_id),
        "type_if_known": face.designator or None,
        "polygon": polygon,
        "point": _centroid(polygon),
        "area_SF": _round_area(face.size),
        "detected": True,
        "point_ids": point_ids,
        "bounds": _bounds_for_points(polygon),
    }
    return payload


def _bordering_roof_faces(geom: EagleViewGeometry, line_id: str) -> list[str]:
    return [
        fid
        for fid, face in sorted(geom.roof_faces.items(), key=lambda item: _id_sort_key(item[0]))
        if line_id in face.line_ids
    ]


def _host_facet_id(geom: EagleViewGeometry, penetration_id: str) -> str | None:
    for fid, face in sorted(geom.roof_faces.items(), key=lambda item: _id_sort_key(item[0])):
        if penetration_id in face.children:
            return fid
    # Fallback for XMLs that do not list penetration children on the host face:
    # choose the roof face whose bounding box contains the penetration centroid.
    pen_face = geom.penetration_faces[penetration_id]
    pen_poly = [_xy(geom.points[pid]) for pid in geom.ordered_face_point_ids(penetration_id)]
    cx, cy = _centroid(pen_poly)
    for fid, face in sorted(geom.roof_faces.items(), key=lambda item: _id_sort_key(item[0])):
        poly = [_xy(geom.points[pid]) for pid in geom.ordered_face_point_ids(fid)]
        b = _bounds_for_points(poly)
        if b["minx"] <= cx <= b["maxx"] and b["miny"] <= cy <= b["maxy"]:
            return fid
    return None


def _xy(point3: Sequence[float]) -> list[float]:
    return [round(float(point3[0]), 6), round(float(point3[1]), 6)]


def _round_area(value: float | None) -> float | None:
    return None if value is None else round(float(value), 3)


def _centroid(points: Sequence[Sequence[float]]) -> list[float]:
    if not points:
        return [0.0, 0.0]
    return [
        round(sum(float(p[0]) for p in points) / len(points), 6),
        round(sum(float(p[1]) for p in points) / len(points), 6),
    ]


def _bounds_for_points(points: Iterable[Sequence[float]]) -> dict[str, float]:
    pts = list(points)
    if not pts:
        return {"minx": 0.0, "miny": 0.0, "maxx": 0.0, "maxy": 0.0}
    xs = [float(p[0]) for p in pts]
    ys = [float(p[1]) for p in pts]
    return {
        "minx": round(min(xs), 6),
        "miny": round(min(ys), 6),
        "maxx": round(max(xs), 6),
        "maxy": round(max(ys), 6),
    }


def _id_sort_key(value: str) -> tuple[str, int, str]:
    prefix = "".join(ch for ch in str(value) if not ch.isdigit())
    digits = "".join(ch for ch in str(value) if ch.isdigit())
    return (prefix, int(digits or "0"), str(value))


# ----------------------------- receipt helper -----------------------------

def _run_receipts(path: str = "XML.txt") -> int:
    result = build_roof_layout(path)
    print("BUILD 1.5 ROOF LAYOUT RECEIPTS")
    print(f"  facets: {len(result['facets'])}")
    print(f"  valleys: {len(result['valleys'])}")
    print(f"  penetrations: {len(result['penetrations'])}")
    print(f"  facet_area_SF_sum: {result['area_summary']['facet_area_SF_sum']}")
    print(f"  facet_plus_penetration_area_SF_sum: {result['area_summary']['facet_plus_penetration_area_SF_sum']}")
    examples = {v["valley_id"]: v["length_LF"] for v in result["valleys"] if v["valley_id"] in {"L4", "L5", "L9"}}
    print(f"  valley examples: {examples}")
    print(f"  roof_bounds: {result['roof_bounds']}")
    for facet in result["facets"][:6]:
        print(f"  {facet['facet_id']} {facet['designator']} bounds: {facet['bounds']}")
    json.dumps(result, separators=(",", ":"))
    checks = [
        len(result["facets"]) == 22,
        len(result["valleys"]) == 14,
        len(result["penetrations"]) == 7,
        examples.get("L4") == 7.74,
        examples.get("L5") == 7.74,
        examples.get("L9") == 25.5,
    ]
    print("  json.dumps: PASS")
    print("RESULT:", "PASS" if all(checks) else "FAIL")
    return 0 if all(checks) else 1


if __name__ == "__main__":
    import sys
    raise SystemExit(_run_receipts(sys.argv[1] if len(sys.argv) > 1 else "XML.txt"))
