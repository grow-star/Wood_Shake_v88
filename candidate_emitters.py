#!/usr/bin/env python3
"""Candidate emitters for Module 1 intake. Detection only; no repair decisions."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Dict, List, Mapping, Tuple

from candidate_model import Candidate
from eagleview_geometry_parser import EagleViewGeometry
from transition_enumerator import enumerate_transition_candidates
from notch_candidate_emitter import emit_notch_candidates


def emit_face_candidates(geom: EagleViewGeometry) -> List[Candidate]:
    """One detected candidate per XML roof facet."""
    out: List[Candidate] = []
    for face_id, face in sorted(geom.roof_faces.items(), key=lambda kv: _id_sort_key(kv[0])):
        out.append(Candidate(
            kind="face",
            source_ids=(face_id,),
            origin="xml",
            confirmed=False,
            params={
                "face_id": face_id,
                "designator": face.designator,
                "pitch": face.pitch,
                "ordered_vertex_ids": tuple(geom.ordered_face_point_ids(face_id)),
            },
        ))
    return out


def emit_valley_candidates(geom: EagleViewGeometry) -> List[Candidate]:
    """One detected candidate per XML VALLEY line, with bordering roof faces."""
    line_to_roof_faces = _line_to_roof_faces(geom)
    out: List[Candidate] = []
    for line_id, line in sorted(geom.lines.items(), key=lambda kv: _id_sort_key(kv[0])):
        if line.type != "VALLEY":
            continue
        endpoint_ids = (line.path[0], line.path[-1])
        out.append(Candidate(
            kind="valley",
            source_ids=(line_id,),
            origin="xml",
            confirmed=False,
            params={
                "valley_line_id": line_id,
                "endpoint_ids": endpoint_ids,
                "endpoints_3d": (geom.points[endpoint_ids[0]], geom.points[endpoint_ids[1]]),
                "bordering_roof_face_ids": tuple(sorted(line_to_roof_faces.get(line_id, ()), key=_id_sort_key)),
            },
        ))
    return out


def emit_penetration_candidates(geom: EagleViewGeometry) -> List[Candidate]:
    """One detected candidate per XML ROOFPENETRATION face with host roof facet footprint."""
    host_by_penetration: Dict[str, str] = {}
    for face_id, face in geom.roof_faces.items():
        for child_id in face.children:
            child = geom.faces.get(child_id)
            if child is not None and child.type == "ROOFPENETRATION":
                host_by_penetration[child_id] = face_id

    out: List[Candidate] = []
    for pen_id, pen in sorted(geom.penetration_faces.items(), key=lambda kv: _id_sort_key(kv[0])):
        host_id = host_by_penetration.get(pen_id)
        footprint: Mapping[str, Any] | None = None
        if host_id is not None:
            footprint = geom.penetration_appurtenance_for_face(host_id, pen_id)
        out.append(Candidate(
            kind="penetration",
            source_ids=(pen_id,),
            origin="xml",
            confirmed=False,
            params={
                "penetration_face_id": pen_id,
                "host_facet_id": host_id,
                "appurtenance_geometry": dict(footprint) if footprint is not None else None,
            },
        ))
    return out


def emit_transition_candidates(geom: EagleViewGeometry) -> List[Candidate]:
    """Wrap existing TransitionCandidate fields into the common candidate envelope."""
    out: List[Candidate] = []
    for transition in enumerate_transition_candidates(geom):
        if geom.lines[transition.edge_id].type == "VALLEY":
            continue
        out.append(Candidate(
            kind="transition",
            source_ids=(transition.edge_id, transition.face_a_id, transition.face_b_id),
            origin="xml",
            confirmed=False,
            params=asdict(transition),
        ))
    return out


def build_user_point_appurtenance_candidate(
    host_facet_id: str,
    x: float,
    y: float,
    kind_label: str,
) -> Candidate:
    """Create a user-origin point appurtenance candidate. No detection or confirmation."""
    return Candidate(
        kind="appurtenance",
        source_ids=("user",),
        origin="user",
        confirmed=False,
        params={
            "host_facet_id": host_facet_id,
            "position": {"x": float(x), "y": float(y)},
            "appurtenance_shape": "point",
            "appurtenance_geometry": {"cx": float(x), "cy": float(y), "kind": "point"},
            "kind_label": kind_label,
        },
    )


def build_user_dimensioned_appurtenance_candidate(
    host_facet_id: str,
    x: float,
    y: float,
    width: float,
    height: float,
    kind_label: str,
) -> Candidate:
    """Create a user-origin dimensioned appurtenance candidate. No detection or confirmation."""
    return Candidate(
        kind="appurtenance",
        source_ids=("user",),
        origin="user",
        confirmed=False,
        params={
            "host_facet_id": host_facet_id,
            "position": {"x": float(x), "y": float(y)},
            "width": float(width),
            "height": float(height),
            "appurtenance_shape": "dimensioned",
            "appurtenance_geometry": {"cx": float(x), "cy": float(y), "w": float(width), "h": float(height), "kind": "dimensioned"},
            "kind_label": kind_label,
        },
    )


def _line_to_roof_faces(geom: EagleViewGeometry) -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {}
    for face_id, face in geom.roof_faces.items():
        for line_id in face.line_ids:
            out.setdefault(line_id, []).append(face_id)
    return out


def _id_sort_key(value: str) -> Tuple[str, int, str]:
    prefix = "".join(ch for ch in value if not ch.isdigit())
    digits = "".join(ch for ch in value if ch.isdigit())
    return (prefix, int(digits or "0"), value)
