#!/usr/bin/env python3
"""
EAGLEVIEW GEOMETRY INTAKE PARSER
================================
Geometry intake only. Extracts EagleView POINT / LINE / FACE structure and emits
engine-ready facet, edge, point, and penetration structures. It performs no
affected-area math, no scope math, and no carrier parsing.

CHANGELOG 2026-07-03: unified centerline-extent seed flat-valley marker; anchor unchanged 3691.

Valley extraction authority remains the frozen Module 1 valley parser. This file
imports and reuses parse_valley_geometry for the valley geometry map; it does not
compute valley LF independently.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import contextlib
import importlib.util
import io
import math
import os
import re
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import numpy as np
from geometry_core import EXP as _EXP_COURSE

from module1_selected_valley_handoff import parse_valley_geometry


def _quiet_import_regression_symbol(name: str):
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
    return getattr(module, name)


mkframe_pts = _quiet_import_regression_symbol("mkframe_pts")

Point2 = Tuple[float, float]
Point3 = Tuple[float, float, float]
EdgeTuple = Tuple[Point2, Point2, str, float]
ValleyEvent = Tuple[Point2, Point2, int]


@dataclass(frozen=True)
class EagleViewLine:
    id: str
    path: Tuple[str, ...]
    type: str


@dataclass(frozen=True)
class EagleViewFace:
    id: str
    designator: str
    type: str
    children: Tuple[str, ...]
    polygon_id: str
    line_ids: Tuple[str, ...]
    pitch: Optional[float]
    size: Optional[float]
    unrounded_size: Optional[float]
    structure_id: str = ""  # v65: the <ROOF id="…"> the face belongs to; "" when the XML has no ROOF nesting


@dataclass(frozen=True)
class EngineFacetGeometry:
    face_id: str
    designator: str
    facet: List[Point2]
    edges: List[EdgeTuple]
    penetrations: List[List[Point2]] = field(default_factory=list)
    point_ids: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class EagleViewGeometry:
    points: Dict[str, Point3]
    lines: Dict[str, EagleViewLine]
    faces: Dict[str, EagleViewFace]
    valley_lengths: Dict[str, float]

    @property
    def roof_faces(self) -> Dict[str, EagleViewFace]:
        return {fid: f for fid, f in self.faces.items() if f.type == "ROOF"}

    @property
    def penetration_faces(self) -> Dict[str, EagleViewFace]:
        return {fid: f for fid, f in self.faces.items() if f.type == "ROOFPENETRATION"}

    def ordered_face_point_ids(self, face_id: str) -> List[str]:
        return _walk_lines([self.lines[lid].path for lid in self.faces[face_id].line_ids])

    def face_frame(self, face_id: str):
        face = self.faces[face_id]
        point_ids = self.ordered_face_point_ids(face_id)
        anchor_line = _frame_anchor_line(face.line_ids, self.lines)
        anchor_path = self.lines[anchor_line].path
        return mkframe_pts([self.points[pid] for pid in point_ids],
                           self.points[anchor_path[0]], self.points[anchor_path[-1]])

    def engine_facet(self, face_id: str, include_child_penetrations: bool = True) -> EngineFacetGeometry:
        face = self.faces[face_id]
        frame = self.face_frame(face_id)
        point_ids = self.ordered_face_point_ids(face_id)
        facet = [tuple(float(v) for v in frame(self.points[pid])) for pid in point_ids]
        edges: List[EdgeTuple] = []
        for lid in face.line_ids:
            line = self.lines[lid]
            a = tuple(float(v) for v in frame(self.points[line.path[0]]))
            b = tuple(float(v) for v in frame(self.points[line.path[-1]]))
            edges.append((a, b, line.type, _length_3d([self.points[p] for p in line.path])))

        penetrations: List[List[Point2]] = []
        if include_child_penetrations:
            for child_id in face.children:
                child = self.faces.get(child_id)
                if child and child.type == "ROOFPENETRATION":
                    child_loop = self.ordered_face_point_ids(child_id)
                    penetrations.append([tuple(float(v) for v in frame(self.points[pid])) for pid in child_loop])

        return EngineFacetGeometry(face_id=face.id, designator=face.designator,
                                   facet=facet, edges=edges,
                                   penetrations=penetrations, point_ids=point_ids)

    def valley_event_for_face(self, face_id: str, valley_id: str) -> ValleyEvent:
        frame = self.face_frame(face_id)
        line = self.lines[valley_id]
        a_id, b_id = line.path[0], line.path[-1]
        # Engine valley event is start-at-low/eave side to apex/high side.
        apex_id, start_id = (a_id, b_id) if self.points[a_id][2] >= self.points[b_id][2] else (b_id, a_id)
        start = np.array(frame(self.points[start_id]), dtype=float)
        apex = np.array(frame(self.points[apex_id]), dtype=float)
        _apex_edge = apex.copy()  # REAL valley endpoint for the fan edge (pre flat-collapse)
        # FLAT valley (global 15deg test, matches transition_detect): no true apex ->
        # collapse apex up-slope coord to start so stair_edges seeds the fan from the
        # valley's cross-slope EXTENT (both endpoints) instead of a single apex point.
        # FLAT = the valley rises less than one course in the fall-line frame, i.e. it
        # runs along a course rather than climbing the slope. Frame-rise-per-course is
        # the physical criterion (replaces the arbitrary 15-degree 3D angle, which
        # mis-classifies long-shallow and short-steep valleys on other roofs).
        _is_flat = abs(_apex_edge[1] - start[1]) < _EXP_COURSE
        if _is_flat:
            apex=np.array([apex[0], start[1]], dtype=float)
        poly = self.engine_facet(face_id).facet
        # Fan = inward normal of the valley EDGE read from polygon winding (robust on
        # non-convex facets; the old centroid rule fanned the wrong way when a valley's
        # local interior pointed away from the facet bulk, e.g. H/Q, D/R).
        _pn = np.asarray(poly, dtype=float); _n = len(_pn)
        fan = 1 if _pn.mean(axis=0)[0] > (start[0] + _apex_edge[0]) / 2 else -1  # fallback
        _sa = 0.0
        for _i in range(_n):
            _x1,_y1 = _pn[_i]; _x2,_y2 = _pn[(_i+1)%_n]; _sa += _x1*_y2 - _x2*_y1
        _ccw = _sa > 0
        _do_winding = not _is_flat
        def _cv(pt):
            return min(range(_n), key=lambda i: (_pn[i][0]-pt[0])**2 + (_pn[i][1]-pt[1])**2)
        _si = _cv(start); _ai = _cv(_apex_edge); _ed = None
        if _ai == (_si+1) % _n: _ed = _pn[_ai] - _pn[_si]
        elif _si == (_ai+1) % _n: _ed = _pn[_si] - _pn[_ai]
        if _do_winding and _ed is not None:
            _l = float(np.hypot(_ed[0], _ed[1]))
            if _l > 1e-9:
                _ed = _ed / _l; _nl2 = np.array([-_ed[1], _ed[0]])
                _inw = _nl2 if _ccw else -_nl2
                if abs(_inw[0]) > 1e-9: fan = 1 if _inw[0] > 0 else -1
        return (tuple(float(v) for v in start), tuple(float(v) for v in apex), int(fan))

    def penetration_appurtenance_for_face(self, face_id: str, penetration_face_id: str) -> Mapping[str, float | str]:
        frame = self.face_frame(face_id)
        pts = [np.array(frame(self.points[pid]), dtype=float) for pid in self.ordered_face_point_ids(penetration_face_id)]
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        return {
            "cx": float((min(xs) + max(xs)) / 2),
            "cy": float((min(ys) + max(ys)) / 2),
            "w": float(max(xs) - min(xs)),
            "h": float(max(ys) - min(ys)),
            "kind": "dimensioned",
        }


def parse_eagleview_geometry(xml_text: str) -> EagleViewGeometry:
    """Parse EagleView POINT / LINE / FACE structure. Geometry intake only."""
    points = _parse_points(xml_text)
    lines = _parse_lines(xml_text)
    faces = _parse_faces(xml_text)
    # Coherence at the PARSE BOUNDARY: a file that yields faces but no points is incoherent — a face
    # references vertices that were never read. Left alone this surfaces as a KeyError deep in the layout
    # code (naming a vertex like "C5"), which tells the user nothing. Fail here, naming the file, so no
    # consumer — workbench_roof_layout or otherwise — ever sees a half-parsed geometry. This lives in the
    # parser rather than in workbench_roof_layout precisely because the parser is the one boundary every
    # consumer passes through.
    if faces and not points:
        raise ValueError(
            "Could not read this EagleView file: it has faces but no points, so its geometry "
            "could not be parsed. The export may use an attribute layout this tool does not recognize."
        )
    valley_lengths = parse_valley_geometry(xml_text)
    return EagleViewGeometry(points=points, lines=lines, faces=faces, valley_lengths=valley_lengths)


def structural_counts(geom: EagleViewGeometry) -> Dict[str, int]:
    return {
        "points": len(geom.points),
        "lines": len(geom.lines),
        "faces": len(geom.faces),
        "valleys": len(geom.valley_lengths),
        "roofpenetration_faces": len(geom.penetration_faces),
    }


def _parse_points(xml_text: str) -> Dict[str, Point3]:
    # Read POINT attributes BY NAME, exactly as _parse_faces does — so the order of attributes and any
    # extra attributes (e.g. EagleView's `rawpixel`, which appears AFTER `data` on some exports) do not
    # matter. The old positional regex required `data` to be the last attribute and dropped every point
    # on a rawpixel-bearing export, silently, which then died 300 lines later as a KeyError on a vertex.
    # `<POINT\s+([^>]*)>` matches the same tags the old regex did (all POINT ids are C-numbers) while the
    # container `<POINTS>` tag is not matched — the required `\s+` after POINT cannot follow the "S".
    out: Dict[str, Point3] = {}
    for m in re.finditer(r'<POINT\s+([^>]*)>', xml_text):
        attrs = _attrs(m.group(1))
        pid = attrs.get("id")
        if not pid:
            raise ValueError("POINT tag is missing its id attribute")
        if "data" not in attrs:
            raise ValueError(f"POINT {pid} is missing its data attribute")   # required, not merely absent
        vals = tuple(float(v) for v in attrs["data"].split(","))
        if len(vals) != 3:
            raise ValueError(f"POINT {pid} does not contain x,y,z")
        out[pid] = vals  # type: ignore[assignment]
    return out


def _parse_lines(xml_text: str) -> Dict[str, EagleViewLine]:
    # Read LINE attributes BY NAME, like _parse_faces. The old positional regex required exactly
    # id, path, type in that order with type last, so a reordered tag (`type` before `path`) or an extra
    # trailing attribute dropped the line silently. `path` is required and its absence is a malformed file.
    out: Dict[str, EagleViewLine] = {}
    for m in re.finditer(r'<LINE\s+([^>]*)>', xml_text):
        attrs = _attrs(m.group(1))
        lid = attrs.get("id")
        if not lid:
            raise ValueError("LINE tag is missing its id attribute")
        if "path" not in attrs:
            raise ValueError(f"LINE {lid} is missing its path attribute")     # required, not merely absent
        path = tuple(p for p in attrs["path"].split(",") if p)
        out[lid] = EagleViewLine(id=lid, path=path, type=attrs.get("type", ""))
    return out


def _parse_faces(xml_text: str) -> Dict[str, EagleViewFace]:
    out: Dict[str, EagleViewFace] = {}
    # v65: map each <FACE> to the <ROOF id="…"> block that contains it, by character span. This is
    # purely additive — a roof with no ROOF nesting yields structure_id "" for every face, so
    # single-structure exports are unchanged. ROOF blocks do not nest, so a non-greedy match is exact.
    roof_spans = [(m.start(), m.end(), _attrs(m.group(1)).get("id", ""))
                  for m in re.finditer(r'<ROOF\s+([^>]*)>(.*?)</ROOF>', xml_text, re.S)]

    def _structure_for(pos: int) -> str:
        for start, end, rid in roof_spans:
            if start <= pos < end:
                return rid
        return ""

    face_re = re.compile(r'<FACE\s+([^>]*)>\s*<POLYGON\s+([^>]*)/>\s*</FACE>', re.S)
    for m in face_re.finditer(xml_text):
        face_attrs = _attrs(m.group(1))
        poly_attrs = _attrs(m.group(2))
        fid = face_attrs["id"]
        children = tuple(c for c in face_attrs.get("children", "").split(",") if c)
        line_ids = tuple(l for l in poly_attrs.get("path", "").split(",") if l)
        out[fid] = EagleViewFace(
            id=fid,
            designator=face_attrs.get("designator", ""),
            type=face_attrs.get("type", ""),
            children=children,
            polygon_id=poly_attrs.get("id", ""),
            line_ids=line_ids,
            pitch=_float_or_none(poly_attrs.get("pitch")),
            size=_float_or_none(poly_attrs.get("size")),
            unrounded_size=_float_or_none(poly_attrs.get("unroundedsize")),
            structure_id=_structure_for(m.start()),
        )
    return out


def _attrs(s: str) -> Dict[str, str]:
    return {m.group(1): m.group(2) for m in re.finditer(r'(\w+)="([^"]*)"', s)}


def _float_or_none(value: Optional[str]) -> Optional[float]:
    if value in (None, ""):
        return None
    return float(value)


def _walk_lines(paths: Sequence[Sequence[str]]) -> List[str]:
    # v64: BACKTRACKING walk. The old walk was greedy with no backtracking: it took segs[0] then
    # repeatedly grabbed the first unused segment touching the current endpoint, and RAISED if that
    # stranded it. A PINCHED (slit) facet — one whose boundary runs out along a line and back along the
    # SAME line, so a line_id appears twice and 3+ segments meet at the pinch point — could send the
    # greedy pick down the wrong branch (e.g. Pershing F4 at C35). The loop is still a legitimate closed
    # traversal; it simply is not a SIMPLE polygon.
    #
    # This is a depth-first search that UNDOES a dead-end branch and tries the next candidate. It scans
    # candidates in the SAME order the greedy walk did (segment index order, a forward endpoint match
    # preferred over a reversed one), and only ever backtracks where the greedy walk would have FAILED —
    # so on any face the greedy walk could already close, the FIRST candidate at every step is taken and
    # the raw output is IDENTICAL, not merely geometrically identical. A face that genuinely cannot form
    # a closed loop exhausts the search and raises the same ValueError as before (never a partial loop).
    # Iterative (an explicit stack), so recursion depth is not a concern on large faces.
    if not paths:
        return []
    segs = [list(p) for p in paths]
    n = len(segs)
    loop = list(segs[0])
    used = [False] * n
    used[0] = True
    tried: List[set] = [set()]        # tried[d]: candidate seg indices already exhausted at depth d
    undo: List[tuple] = []            # (seg_index, points_appended) for each committed step, for undo

    while sum(used) < n:
        last = loop[-1]
        pick = None
        for i in range(n):
            if used[i] or i in tried[-1]:
                continue
            seg = segs[i]
            if seg[0] == last:
                pick = (i, seg[1:])
                break
            if seg[-1] == last:
                pick = (i, list(reversed(seg[:-1])))
                break
        if pick is None:                              # dead end -> backtrack
            tried.pop()
            if not undo:                              # exhausted at the root: genuinely unclosable
                break
            seg_i, added = undo.pop()
            used[seg_i] = False
            del loop[len(loop) - added:]
            tried[-1].add(seg_i)                      # do not re-pick this failed branch at the parent
            continue
        i, ext = pick
        used[i] = True
        loop.extend(ext)
        undo.append((i, len(ext)))
        tried.append(set())

    if sum(used) != n:
        raise ValueError("face polygon path is not a closed connected loop")
    if not loop or loop[0] != loop[-1]:
        # Every segment was consumed but the traversal did not return to its start: an open chain,
        # not a loop. Raise loudly rather than silently returning a partial polygon.
        raise ValueError("face polygon path is not a closed connected loop")
    loop = loop[:-1]
    return loop


def _frame_anchor_line(line_ids: Sequence[str], lines: Mapping[str, EagleViewLine]) -> str:
    for wanted in ("EAVE", "RIDGE"):
        for lid in line_ids:
            if lines[lid].type == wanted:
                return lid
    return line_ids[0]


def _length_3d(points: Sequence[Point3]) -> float:
    total = 0.0
    for a, b in zip(points, points[1:]):
        total += math.dist(a, b)
    return total
