#!/usr/bin/env python3
"""Notch candidate emitter for Module 1 intake. Detection only; no repair decisions."""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Dict, List, Sequence, Set, Tuple

from candidate_model import Candidate
from eagleview_geometry_parser import EagleViewGeometry
from facet_basis import facet_fall_xy

Point2 = Tuple[float, float]


def emit_notch_candidates(geom: EagleViewGeometry, pitch_tol: float = 1e-6, fall_cos_tol: float = 0.999) -> List[Candidate]:
    """Detect same-plane roof-face groups joined by HIDDEN edges and emit notch candidates.

    ENCODING A only: two roof faces SHARE a HIDDEN line (Yager F21/F22). These are the user-selectable
    notch candidates surfaced on page 2. UNCHANGED — the anchor's notch candidate comes from here and is
    byte-identical.

    ENCODING B (one face whose boundary traverses a HIDDEN line twice — a slit) is NOT surfaced here as a
    selectable notch: such a face is a single continuous surface that the user already repairs through its
    ordinary valley intersections, not a two-face merge to pick. Its reframing candidate is built ON
    DEMAND by `encoding_b_candidate` and consumed inside the assembly's valley sweep, so page 2's
    candidate list is unchanged and Yager cannot be affected."""
    hidden_pairs = _hidden_same_plane_pairs(geom, pitch_tol=pitch_tol, fall_cos_tol=fall_cos_tol)
    groups = _connected_face_groups(hidden_pairs)
    out: List[Candidate] = []
    for group in groups:
        candidate = _candidate_for_group(geom, group)
        if candidate is not None:
            out.append(candidate)
    return out


def encoding_b_candidate(geom: EagleViewGeometry, face_id: str) -> Candidate | None:
    """Build the Encoding-B reframing candidate for ONE face on demand, via the SAME builder Encoding A
    uses (one authority). Returns None unless the face has a self-bounding HIDDEN line (a line appearing
    twice in its own line_ids). Because Yager has no such line, this is None for every Yager face — the
    anchor cannot enter the reframing branch by construction, not merely by a guard."""
    if not _self_bounding_hidden_line_ids(geom, str(face_id)):
        return None
    return _candidate_for_group(geom, (str(face_id),))


def _self_bounding_hidden_line_ids(geom: EagleViewGeometry, face_id: str) -> List[str]:
    """HIDDEN lines that appear TWICE (or more) in ONE face's own line_ids — the Encoding-B slit."""
    face = geom.faces[face_id]
    out: List[str] = []
    for line_id in dict.fromkeys(face.line_ids):
        if face.line_ids.count(line_id) >= 2 and geom.lines[line_id].type.upper() == "HIDDEN":
            out.append(line_id)
    return sorted(out, key=_id_sort_key)


def _self_bounding_faces(geom: EagleViewGeometry) -> List[str]:
    return [fid for fid in geom.roof_faces if _self_bounding_hidden_line_ids(geom, fid)]


def _group_has_self_bounding_hidden(geom: EagleViewGeometry, group: Tuple[str, ...]) -> bool:
    return any(_self_bounding_hidden_line_ids(geom, fid) for fid in group)


def _hidden_same_plane_pairs(geom: EagleViewGeometry, pitch_tol: float, fall_cos_tol: float) -> List[Tuple[str, str, str]]:
    line_to_roof_faces: Dict[str, List[str]] = defaultdict(list)
    for face_id, face in geom.roof_faces.items():
        for line_id in face.line_ids:
            line_to_roof_faces[line_id].append(face_id)

    pairs: List[Tuple[str, str, str]] = []
    for line_id, face_ids in line_to_roof_faces.items():
        line = geom.lines[line_id]
        if line.type.upper() != "HIDDEN" or len(face_ids) != 2:
            continue
        a, b = sorted(face_ids, key=_id_sort_key)
        if a == b:
            # Same face on both ends: this is a self-bounding HIDDEN line (Encoding B), not a two-face
            # Encoding-A merge. It is handled on demand by `encoding_b_candidate`, never surfaced here as
            # a selectable page-2 notch. Skipping it keeps `emit_notch_candidates` byte-identical.
            continue
        fa, fb = geom.faces[a], geom.faces[b]
        if fa.pitch is None or fb.pitch is None:
            continue
        if abs(float(fa.pitch) - float(fb.pitch)) > pitch_tol:
            continue
        fall_a = facet_fall_xy([geom.points[pid] for pid in geom.ordered_face_point_ids(a)])
        fall_b = facet_fall_xy([geom.points[pid] for pid in geom.ordered_face_point_ids(b)])
        if _cosine(fall_a, fall_b) < fall_cos_tol:
            continue
        pairs.append((a, b, line_id))
    return pairs


def _connected_face_groups(pairs: Sequence[Tuple[str, str, str]]) -> List[Tuple[str, ...]]:
    graph: Dict[str, Set[str]] = defaultdict(set)
    for a, b, _line_id in pairs:
        graph[a].add(b)
        graph[b].add(a)
    groups: List[Tuple[str, ...]] = []
    seen: Set[str] = set()
    for start in sorted(graph, key=_id_sort_key):
        if start in seen:
            continue
        q = deque([start])
        seen.add(start)
        group: List[str] = []
        while q:
            cur = q.popleft()
            group.append(cur)
            for nxt in sorted(graph[cur], key=_id_sort_key):
                if nxt not in seen:
                    seen.add(nxt)
                    q.append(nxt)
        groups.append(tuple(sorted(group, key=_id_sort_key)))
    return groups


def _candidate_for_group(geom: EagleViewGeometry, group: Tuple[str, ...]) -> Candidate | None:
    # A two-face group is Encoding A. A single-face group is admitted ONLY when it carries a
    # self-bounding HIDDEN line (Encoding B). Everything below is shared — one authority.
    if len(group) < 2 and not _group_has_self_bounding_hidden(geom, group):
        return None
    hidden_edges: List[str] = []
    boundary_edges: List[Tuple[str, str, str]] = []

    for line_id, line in geom.lines.items():
        faces_with = [fid for fid in group if line_id in geom.faces[fid].line_ids]
        if not faces_with:
            continue
        # A HIDDEN line is the shared/self-bounding edge when it is traversed twice across the group:
        # once by each of two faces (Encoding A) OR twice by one face (Encoding B). Using multiplicity
        # makes both encodings land on the same branch; for a two-face group it is identical to the old
        # `len(face_ids) >= 2` test, so Encoding A (the anchor) is unchanged.
        multiplicity = sum(geom.faces[fid].line_ids.count(line_id) for fid in group)
        if line.type.upper() == "HIDDEN" and multiplicity >= 2:
            hidden_edges.append(line_id)
            continue
        if len(faces_with) == 1:
            boundary_edges.append((line_id, line.path[0], line.path[-1]))

    cycles = _boundary_cycles(boundary_edges)
    if len(cycles) < 2:
        return None

    frame = geom.face_frame(group[0])
    ranked = sorted(cycles, key=lambda cyc: abs(_signed_area([tuple(float(v) for v in frame(geom.points[pid])) for pid in cyc])), reverse=True)
    oriented = [_clockwise_cycle(frame, geom, cyc) for cyc in ranked]
    merged_facet_point_ids = _rotate_to_smallest(oriented[0])
    notch_polygon_point_ids = [_rotate_to_smallest(cyc) for cyc in oriented[1:]]
    anchor_line_id = _ridge_anchor_line_id(geom, group, merged_facet_point_ids)
    anchor_face_id = _anchor_face_id(geom, group, anchor_line_id)
    bordering_valley_line_ids = _bordering_valley_line_ids(geom, (anchor_face_id,), anchor_line_id)

    return Candidate(
        kind="notch",
        source_ids=group,
        origin="xml",
        params={
            "member_face_ids": group,
            "shared_hidden_edge_ids": tuple(sorted(hidden_edges, key=_id_sort_key)),
            "merged_facet_point_ids": tuple(merged_facet_point_ids),
            "notch_polygon_point_ids": tuple(tuple(cyc) for cyc in notch_polygon_point_ids),
            "anchor_line_id": anchor_line_id,
            "anchor_face_id": anchor_face_id,
            "frame_point_ids": tuple(geom.ordered_face_point_ids(anchor_face_id)),
            "bordering_valley_line_ids": tuple(bordering_valley_line_ids),
        },
        confirmed=False,
    )


def _ridge_anchor_line_id(geom: EagleViewGeometry, group: Tuple[str, ...], merged_facet_point_ids: Sequence[str]) -> str:
    outer_edges = _cycle_edges(merged_facet_point_ids)
    ridge_lines: List[str] = []
    for line_id, line in geom.lines.items():
        if line.type.upper() != "RIDGE":
            continue
        if _edge_key(line.path[0], line.path[-1]) not in outer_edges:
            continue
        if not any(line_id in geom.faces[face_id].line_ids for face_id in group):
            continue
        ridge_lines.append(line_id)
    if not ridge_lines:
        raise ValueError("notch group has no RIDGE line on the merged facet boundary")
    return sorted(ridge_lines, key=_id_sort_key)[0]


def _anchor_face_id(geom: EagleViewGeometry, group: Tuple[str, ...], anchor_line_id: str) -> str:
    anchor_faces = [face_id for face_id in group if anchor_line_id in geom.faces[face_id].line_ids]
    if not anchor_faces:
        raise ValueError("notch anchor line is not attached to a member roof face")
    return sorted(anchor_faces, key=_id_sort_key)[0]


def _bordering_valley_line_ids(geom: EagleViewGeometry, face_ids: Tuple[str, ...], anchor_line_id: str) -> List[str]:
    valley_ids: Set[str] = set()
    for face_id in face_ids:
        for line_id in geom.faces[face_id].line_ids:
            if geom.lines[line_id].type.upper() == "VALLEY":
                valley_ids.add(line_id)
    return sorted(valley_ids, key=_id_sort_key)


def _boundary_cycles(edges: Sequence[Tuple[str, str, str]]) -> List[List[str]]:
    adj: Dict[str, List[str]] = defaultdict(list)
    edge_keys: Set[Tuple[str, str]] = set()
    for _line_id, a, b in edges:
        adj[a].append(b)
        adj[b].append(a)
        edge_keys.add(_edge_key(a, b))

    cycles: List[List[str]] = []
    remaining = set(edge_keys)
    while remaining:
        a, b = min(remaining, key=lambda e: (_id_sort_key(e[0]), _id_sort_key(e[1])))
        cycle = [a, b]
        remaining.remove(_edge_key(a, b))
        prev, cur = a, b
        while cur != a:
            nxts = [n for n in adj[cur] if n != prev and _edge_key(cur, n) in remaining]
            if not nxts:
                if cur == a:
                    break
                raise ValueError("notch boundary graph is not a closed cycle")
            nxt = sorted(nxts, key=_id_sort_key)[0]
            remaining.remove(_edge_key(cur, nxt))
            if nxt != a:
                cycle.append(nxt)
            prev, cur = cur, nxt
        cycles.append(cycle)
    return cycles


def _clockwise_cycle(frame, geom: EagleViewGeometry, ids: Sequence[str]) -> List[str]:
    vals = list(ids)
    area = _signed_area([tuple(float(v) for v in frame(geom.points[pid])) for pid in vals])
    return list(reversed(vals)) if area > 0 else vals


def _signed_area(poly: Sequence[Point2]) -> float:
    area = 0.0
    for (x1, y1), (x2, y2) in zip(poly, list(poly[1:]) + [poly[0]]):
        area += x1 * y2 - x2 * y1
    return area / 2.0


def _rotate_to_smallest(ids: Sequence[str]) -> List[str]:
    vals = list(ids)
    if not vals:
        return []
    best_i = min(range(len(vals)), key=lambda i: _id_sort_key(vals[i]))
    return vals[best_i:] + vals[:best_i]


def _cycle_edges(ids: Sequence[str]) -> Set[Tuple[str, str]]:
    return {_edge_key(a, b) for a, b in zip(ids, list(ids[1:]) + [ids[0]])}


def _cosine(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    ax, ay = a
    bx, by = b
    denom = (ax * ax + ay * ay) ** 0.5 * (bx * bx + by * by) ** 0.5
    if denom == 0:
        return -1.0
    return (ax * bx + ay * by) / denom


def _edge_key(a: str, b: str) -> Tuple[str, str]:
    return tuple(sorted((a, b), key=_id_sort_key))  # type: ignore[return-value]


def _id_sort_key(value: str) -> Tuple[str, int]:
    prefix = "".join(ch for ch in value if not ch.isdigit())
    number = int("".join(ch for ch in value if ch.isdigit()) or "0")
    return (prefix, number)
