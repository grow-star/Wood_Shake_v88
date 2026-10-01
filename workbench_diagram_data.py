#!/usr/bin/env python3
"""Layer 3 Piece B: Workbench diagram drawing-data exporter.

This module is intentionally an exporter, not a calculator.  The UI selection is
translated through the same confirmation seam as Piece A, then the frozen Module
1 service and affected_area(return_zone=True) engine path are used to expose the
already-computed affected regions as JSON-safe drawing data.

Returned polygons are raster-zone outlines re-projected into the same shared
roof coordinate frame used by workbench_roof_layout.  They are for drawing red
affected regions and labeling the verified per-event shake count; they are not
per-shake footprints.
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from math import ceil
from typing import Any, Callable, Iterable, Mapping, Sequence

import numpy as np

from candidate_display import confirmed_candidates_from_selection
from confirmation_builder import build_confirmation_from_selections
from eagleview_geometry_parser import EagleViewGeometry, parse_eagleview_geometry, _frame_anchor_line
from module1_service import (
    _confirmed_mapping,
    _derived_notch_union_area,
    _dimensional_pens,
    _require_bordering_face,
    _require_candidate,
    _require_notch_candidate,
    _valley_event_for_notch,
    affected_area,
    run_module1_service,
)
from workbench_roof_layout import _xy, _facet_local_to_shared, _local_to_shared_transform
from module2_assembly import _replacement_facet_area, encoding_b_zone, _encoding_b_candidate   # v62/v69: ONE authority for replacement area and for
                                                       # diagram total can never disagree with the scope.
from module2_scope_expansion import _shake_count
from workbench_seam import XML_TEXT_KEYS, _selection_for_candidate_display


_REQUIRED_CONFIRMED_KEYS = {
    "selected_valley_ids",
    "single_valley_repairs",
    "multi_valley_facets",
    "penetration_appurtenance_repairs",
    "notch_repairs",
}


def build_diagram_data(geom_or_xml: EagleViewGeometry | str, ui_selection: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return JSON-safe affected-region drawing data for the Workbench UI.

    Parameters
    ----------
    geom_or_xml:
        Either EagleView XML text or a parsed EagleViewGeometry.  If parsed
        geometry is supplied, include the source XML text in ``ui_selection``
        under one of workbench_seam.XML_TEXT_KEYS.
    ui_selection:
        A Workbench display-shaped selection, or the five-collection confirmed
        selection shape. Empty/None is valid and returns no events.

    The function does not compute affected area. It asks the frozen engine for
    the zone mask using affected_area(..., return_zone=True), then traces the
    mask into a drawable outline. The verified affected_SF remains the value
    emitted by run_module1_service.
    """
    selection: Mapping[str, Any] = ui_selection or {}
    geom, xml_text = _resolve_geometry_and_xml(geom_or_xml, selection)
    confirmed_selection = _confirmed_selection_from_ui(geom, selection)

    service_result = run_module1_service(xml_text, confirmed_selection)

    # COMPUTE THE EVENTS, THEN DECIDE. Module 1 builds `components` from valleys / notches /
    # appurtenances only, so a TRANSITION-ONLY selection has ZERO components — yet it is a real
    # repair event whose bands are computed inside _event_regions(). Early-returning on empty
    # components skipped the band code entirely: no shading, and the Continue gate's in-zone
    # penetration check ran against an empty diagram. Emptiness is a property of the EVENTS,
    # not of Module-1's components.
    events = _event_regions(service_result.candidate_package.geom, service_result, confirmed_selection)
    if not events:
        return {
            "events": [],
            "summary": {
                "total_SF": 0.0,
                "total_EA": 0,
                "pct_of_roof": 0.0,
            },
        }
    # THE DIAGRAM READS FROM THE MATH. total_SF used to come from `service_result` — a Module-1 value
    # computed BEFORE the transition bands exist — while total_EA was summed from the events (which
    # DO include them). So EA moved and SF did not, and the header contradicted the picture beneath
    # it. Both totals are now summed from the same events, so the summary can never disagree with
    # what was actually drawn, and it matches the scope.
    #
    # This IS the scope's own convention: affected_SF_display_total rounds EACH COMPONENT to 1 dp and
    # sums those (Yager: 1639.4 — the raw component sum is 1639.60 and rounding once at the end would
    # print 1639.6, moving the anchor). So the diagram must likewise sum the per-event DISPLAY values.
    # The corollary matters when one scope component is drawn as TWO regions (a valley zone + the
    # incremental transition band on the same facet): the band region must carry the component's
    # ROUNDED REMAINDER, not its own independent rounding, or the split leaks 0.1 SF. That is done at
    # source, in _transition_regions — not papered over here.
    total_sf = round(float(sum(float(e["affected_SF"]) for e in events)), 1)
    total_ea = int(sum(int(e["shake_count"]) for e in events))
    # pct_of_roof (§4's most persuasive number). TWO fixes from v63:
    #   (2a) it must count REPLACEMENTS, not repair events only — the numerator is total_sf, summed from
    #        ALL events (repairs + replacements), so a full replacement is no longer 0%.
    #   (2b/2c) numerator and denominator must SHARE A BASIS. total_sf is NET of penetrations, so the
    #        denominator is the SHAKEABLE area (facet area minus penetrations), computed by the SAME
    #        per-facet function and per-facet rounding the replacement events use. That makes a
    #        fully-replaced roof read EXACTLY 100.0% by construction: when every facet is marked the
    #        numerator is the sum of _round_sf(_replacement_facet_area) over every facet, which is the
    #        denominator itself — no residual (the old ~1.21 SF gap was exactly the mismatch between the
    #        penetration-inclusive facet-area denominator and the penetration-net numerator).
    geom = service_result.candidate_package.geom
    shakeable_sf = round(float(sum(_round_sf(_replacement_facet_area(geom, f)) for f in geom.roof_faces)), 1)
    pct = round((total_sf / shakeable_sf) * 100.0, 2) if shakeable_sf else 0.0
    return {
        "events": events,
        "summary": {
            "total_SF": total_sf,
            "total_EA": total_ea,
            "pct_of_roof": pct,
        },
    }


def _resolve_geometry_and_xml(geom_or_xml: EagleViewGeometry | str, selection: Mapping[str, Any]) -> tuple[EagleViewGeometry, str]:
    if isinstance(geom_or_xml, str):
        return parse_eagleview_geometry(geom_or_xml), geom_or_xml
    for key in XML_TEXT_KEYS:
        value = selection.get(key)
        if isinstance(value, str) and value.strip():
            return geom_or_xml, value
    raise ValueError(
        "build_diagram_data needs XML text for the Module 1 service. "
        "Pass XML text as geom_or_xml, or include it in ui_selection under one of: "
        + ", ".join(XML_TEXT_KEYS)
    )


def _confirmed_selection_from_ui(geom: EagleViewGeometry, selection: Mapping[str, Any]) -> Mapping[str, Any]:
    if _REQUIRED_CONFIRMED_KEYS.issubset(selection.keys()):
        return selection
    engine_selection = _selection_for_candidate_display(selection)
    confirmed_candidates = confirmed_candidates_from_selection(geom, engine_selection)
    confirmed = build_confirmation_from_selections(confirmed_candidates, geom=geom)
    # User-defined appurtenances carve directly in the engine (no candidate translation),
    # so carry them onto the confirmed selection rather than through candidate_display.
    user_rows = list(engine_selection.get("user_appurtenance_repairs", ()))
    if user_rows:
        confirmed = {**dict(confirmed), "user_appurtenance_repairs": user_rows}
    # BUG FIX: user-confirmed pitch-transition repair events were being SILENTLY DROPPED here.
    # `workbench_seam` carries them (which is why the REPORT was right) but this conversion did not
    # (which is why the DIAGRAM was wrong): the band never became an event, so it neither shaded nor
    # contributed EA/SF. Carried now by exactly the same pattern, from the same source dict.
    # The exposed+damaged gate is NOT duplicated here — it stays enforced downstream in
    # transition_events.selected_transition_repairs(), which requires BOTH to be explicitly True.
    transition_rows = [dict(r) for r in (selection.get("transition_repairs", ()) or ())]
    if transition_rows:
        confirmed = {**dict(confirmed), "transition_repairs": transition_rows}
    # v62 DEFECT 1: replaced facets were dropped here (like transitions once were), so the diagram
    # produced no replacement events and reported ~0 SF for a full roof. Carried now, same pattern.
    replaced_rows = [dict(r) if isinstance(r, dict) else {"face_id": str(r)}
                     for r in (selection.get("replaced_facets", ()) or ())]
    if replaced_rows:
        confirmed = {**dict(confirmed), "replaced_facets": replaced_rows}
    return confirmed


def _event_regions(geom: EagleViewGeometry, service_result: Any, confirmed_selection: Mapping[str, Any]) -> list[dict[str, Any]]:
    valley_candidates = {c.source_ids[0]: c for c in service_result.candidate_package.valleys}
    penetration_candidates = {c.source_ids[0]: c for c in service_result.candidate_package.penetrations}
    notch_candidates = {tuple(c.source_ids): c for c in service_result.candidate_package.notches}
    components = iter(service_result.components)
    repair_facet_ids = _repair_facet_ids(confirmed_selection)
    replaced_facet_ids = {str(_confirmed_mapping(_it)["face_id"]) for _it in confirmed_selection.get("replaced_facets", [])}
    out: list[dict[str, Any]] = []
    shake_measurements = confirmed_selection.get("shake_measurements") or confirmed_selection.get("shake_profile") or {"width_in": 7.0, "exposure_in": 10.0}

    for item in confirmed_selection.get("single_valley_repairs", []):
        row = _confirmed_mapping(item)
        component = next(components)
        face_id = str(row["face_id"])
        valley_id = str(row["valley_id"])
        cand = _require_candidate(valley_candidates, valley_id, "valley")
        _require_bordering_face(cand, face_id)
        # v69 NINTH DIVERGENCE FIX: an Encoding-B face (self-bounding HIDDEN slit) is reframed in the
        # SCOPE (module2). The diagram must draw the SAME zone, from the SAME authority — never a second
        # reframing here. encoding_b_zone returns the reframed mask+area (or None for a plain facet).
        ebz = encoding_b_zone(geom, face_id, [valley_id], confirmed_selection, shake_measurements)
        if ebz is not None:
            area, zone, gx, gy, _facet = ebz
            _f, _v, _n, _p, to_shared = _notch_zone_inputs(geom, _encoding_b_candidate(geom, face_id))
            out.append(_event_dict(row.get("label", f"{face_id}:{valley_id}"), face_id, area, zone, gx, gy, to_shared, shake_measurements))
            continue
        to_shared = _facet_local_to_shared(geom, face_id)  # Module 1's mask, drawn directly (no re-derivation)
        out.append(_event_dict(row.get("label", f"{face_id}:{valley_id}"), face_id, component.affected_SF_raw, component.zone, component.gx, component.gy, to_shared, shake_measurements))

    for item in confirmed_selection.get("multi_valley_facets", []):
        row = _confirmed_mapping(item)
        component = next(components)
        face_id = str(row["face_id"])
        valley_ids = tuple(str(v) for v in row.get("valley_ids", ()))
        for valley_id in valley_ids:
            cand = _require_candidate(valley_candidates, valley_id, "valley")
            _require_bordering_face(cand, face_id)
        ebz = encoding_b_zone(geom, face_id, list(valley_ids), confirmed_selection, shake_measurements)
        if ebz is not None:
            area, zone, gx, gy, _facet = ebz
            _f, _v, _n, _p, to_shared = _notch_zone_inputs(geom, _encoding_b_candidate(geom, face_id))
            out.append(_event_dict(row.get("label", f"{face_id}:multi-valley"), face_id, area, zone, gx, gy, to_shared, shake_measurements))
            continue
        to_shared = _facet_local_to_shared(geom, face_id)  # Module 1's mask, drawn directly
        out.append(_event_dict(row.get("label", f"{face_id}:multi-valley"), face_id, component.affected_SF_raw, component.zone, component.gx, component.gy, to_shared, shake_measurements))

    # v62 DEFECT 1: a REPLACED facet must emit a diagram event, or page 2 reports ~0 for a full roof
    # while the scope reports the whole roof. It is NOT a run_module1_service component (that builder
    # skips replacement, exactly like this iterator did), so it does not consume `next(components)` —
    # the iterator stays aligned. The whole facet comes off: the polygon is the facet itself, the area
    # is the SAME authority the scope bills (`_replacement_facet_area`, net of penetrations), and the
    # count is 0 because a replacement bills SQ, not EA. Diagram total == scope total by construction.
    for item in confirmed_selection.get("replaced_facets", []):
        row = _confirmed_mapping(item)
        face_id = str(row["face_id"])
        polygon = [_xy(geom.points[pid]) for pid in geom.ordered_face_point_ids(face_id)]
        out.append({
            "event_label": str(row.get("label", f"{face_id}:replacement")),
            "facet_id": face_id,
            "affected_polygon": [polygon],       # list-of-rings, like every other event
            "affected_SF": _round_sf(_replacement_facet_area(geom, face_id)),
            "shake_count": 0,
            "kind": "replacement",              # v63: drawn as REPLACED in §4, not as a red repair zone
        })

    for item in confirmed_selection.get("penetration_appurtenance_repairs", []):
        row = _confirmed_mapping(item)
        component = next(components)
        penetration_id = str(row["penetration_face_id"])
        cand = _require_candidate(penetration_candidates, penetration_id, "penetration")
        host_face_id = str(row.get("host_face_id") or cand.params["host_facet_id"])
        if host_face_id != cand.params["host_facet_id"]:
            raise ValueError(f"penetration {penetration_id} is not hosted by {host_face_id}")
        zone_face_id = str(component.face_id or host_face_id)
        if "+" in zone_face_id:
            member_face_ids = tuple(zone_face_id.split("+"))
            notch_cand = _require_notch_candidate(notch_candidates, member_face_ids)
            _f, _v, _n, _p, to_shared = _notch_zone_inputs(geom, notch_cand)
        else:
            to_shared = _facet_local_to_shared(geom, zone_face_id)
        # v62 DEFECT 2: appurtenance on a REPLACED facet is unioned into the replacement — its area and
        # count are 0 in the diagram too, so the diagram total stays equal to the scope total. (The
        # material line and IWS are scope-only concerns; the diagram only reports affected area/count.)
        _union = host_face_id in replaced_facet_ids
        out.append(_event_dict(
            row.get("label", f"{host_face_id}:{penetration_id}:appurtenance"),
            host_face_id,
            component.affected_SF_raw,
            component.zone,
            component.gx,
            component.gy,
            to_shared,
            shake_measurements,
            affected_SF=0.0 if _union else None,
            shake_count=0 if _union else None,
        ))
        if _union:
            out[-1]["kind"] = "subsumed"     # v63: inside a full replacement — not a separate §4 box

    for item in confirmed_selection.get("user_appurtenance_repairs", []):
        row = _confirmed_mapping(item)
        if not bool(row.get("repair_event", True)):
            continue
        component = next(components)
        host_face_id = str(row["host_facet_id"])
        zone_face_id = str(component.face_id or host_face_id)
        if "+" in zone_face_id:
            member_face_ids = tuple(zone_face_id.split("+"))
            notch_cand = _require_notch_candidate(notch_candidates, member_face_ids)
            _f, _v, _n, _p, to_shared = _notch_zone_inputs(geom, notch_cand)
        else:
            to_shared = _facet_local_to_shared(geom, zone_face_id)
        label = row.get("designator") or row.get("label") or f"{host_face_id}:user-appurtenance"
        _union = host_face_id in replaced_facet_ids   # v62: unioned into the full replacement
        out.append(_event_dict(
            label,
            host_face_id,
            component.affected_SF_raw,
            component.zone,
            component.gx,
            component.gy,
            to_shared,
            shake_measurements,
            affected_SF=0.0 if _union else None,
            shake_count=0 if _union else None,
        ))
        if _union:
            out[-1]["kind"] = "subsumed"     # v63: inside a full replacement — not a separate §4 box

    for item in confirmed_selection.get("notch_repairs", []):
        row = _confirmed_mapping(item)
        component = next(components)
        member_face_ids = tuple(str(v) for v in row["member_face_ids"])
        cand = _require_notch_candidate(notch_candidates, member_face_ids)
        _f, _v, _n, _p, to_shared = _notch_zone_inputs(geom, cand)  # transform only; mask is Module 1's
        out.append(_event_dict(row.get("label", ":".join(member_face_ids) + ":notch"), "/".join(member_face_ids), component.affected_SF_raw, component.zone, component.gx, component.gy, to_shared, shake_measurements))

    out.extend(_transition_regions(geom, confirmed_selection, shake_measurements))
    return out


def _transition_regions(geom: EagleViewGeometry, confirmed_selection: Mapping[str, Any], shake_measurements) -> list[dict[str, Any]]:
    """Shade the tear-off band of every ACTIVE transition (Path A or Path B), on EVERY facet it
    carves — including facets that also carry a valley repair.

    THE DIAGRAM READS FROM THE MATH, NEVER THE REVERSE. The scope counts this band, so the diagram
    must draw it — otherwise the picture and the numbers disagree, which is exactly the failure the
    regression's diagram==count check exists to catch.

    BUG FIX (v56): this loop used to SKIP any facet that carried a valley component, on the false
    assumption that the valley zone it had already drawn contained the band. It does not.
    module2_assembly threads the bands into the SAME affected_area call as that facet's valley
    events, so the SCOPE's valley component is the UNION of valley zone + band. The DIAGRAM's valley
    zone, however, comes from module1_service — which NEVER receives the bands. So the band was in
    the scope and absent from the picture: on Yager (L79 confirmed + the Q side of L83/L84 repaired)
    the diagram was 11.3 SF short; on Devore (L24 confirmed + a valley on O) it was missing the whole
    70.4 SF upper band. It also punched a hole in the page-2 Continue gate, which reads the DIAGRAM
    events to decide whether a penetration sits in an affected zone.

    ONE ZONE AUTHORITY. The fix is NOT to thread bands into module1_service as well — that would
    leave two zone derivations to keep in step by hand, which IS the bug. The band's region is
    derived here, once, as the INCREMENTAL area it contributes beyond everything else already drawn
    on that facet:

        net_zone = zone(that facet's other events + band) MINUS zone(that facet's other events)

    Union-correct by construction: the region added is exactly what the band opens up beyond the rest
    of that facet, so diagram total == scope total and no pixel is counted twice. Where a valley zone
    already sweeps the band (Yager's V under the default selection), net_zone is empty and the band
    adds ZERO — the anchor cannot move.

    "That facet's other events" is whatever the SCOPE nets the band against on that facet, mirrored
    exactly:
      * VALLEY facet — module2_assembly's `_single_valley_area` / `_multi_valley_union_area` pass the
        bands into affected_area alongside the valley events and the penetrations, and NOT the
        appurtenances (an appurtenance is its own component, already netted against the valley zone).
        So the "other events" here are the valley events + penetrations.
      * NON-VALLEY facet — module2_assembly emits a standalone transition component whose area is
        netted against that facet's appurtenances + penetrations. Unchanged from v55.

    The SHAKE COUNT follows the same mirror, because EA is ceil()ed once PER SCOPE COMPONENT:
      * VALLEY facet — the band lives INSIDE the valley component, which ceils the union once. The
        band region therefore carries the INCREMENTAL count, count(union) - count(valley alone), so
        that valley_region_EA + band_region_EA == the component's single ceil. Counting ceil(net_SF)
        instead would over-count by up to one shake per band.
      * NON-VALLEY facet — the band IS its own scope component, so it carries ceil(net_SF), exactly
        as the scope does. Unchanged from v55.
    """
    import numpy as _np
    from module2_assembly import _confirmed_appurtenance_geometries_for_face, _penetrations_with_user_footprints
    from transition_events import engine_bands, transition_bands_by_face

    bands_by_face = transition_bands_by_face(geom, confirmed_selection, shake_measurements)
    if not bands_by_face:
        return []

    # The valley events the SCOPE unions the band into, per facet. Notch members are deliberately
    # absent: module2_assembly does not thread bands into a notch component either, so a banded notch
    # member is a NON-VALLEY facet on both sides of the seam and stays byte-for-byte as it was.
    valley_events_by_face: dict[str, list[Any]] = {}
    for item in confirmed_selection.get("single_valley_repairs", []):
        row = _confirmed_mapping(item)
        face_id = str(row["face_id"])
        valley_events_by_face.setdefault(face_id, []).append(
            geom.valley_event_for_face(face_id, str(row["valley_id"])))
    for item in confirmed_selection.get("multi_valley_facets", []):
        row = _confirmed_mapping(item)
        face_id = str(row["face_id"])
        for valley_id in row.get("valley_ids", ()):
            valley_events_by_face.setdefault(face_id, []).append(
                geom.valley_event_for_face(face_id, str(valley_id)))

    width_in = float((shake_measurements or {}).get("width_in", 7.0))
    exposure_in = float((shake_measurements or {}).get("exposure_in", 10.0))

    out: list[dict[str, Any]] = []
    for face_id, bands in sorted(bands_by_face.items()):
        engine_face = geom.engine_facet(face_id)
        pens = _penetrations_with_user_footprints(geom, confirmed_selection, face_id)
        valley_events = valley_events_by_face.get(face_id, [])
        apps = [] if valley_events else _confirmed_appurtenance_geometries_for_face(geom, confirmed_selection, face_id)
        _p0, area_without, zone_without, gx, gy = affected_area(
            engine_face.facet, valley_events, appurtenances=apps, penetrations=pens,
            return_zone=True, shake_measurements=shake_measurements)
        _p1, area_with, zone_with, _gx, _gy = affected_area(
            engine_face.facet, valley_events, appurtenances=apps, penetrations=pens,
            return_zone=True, shake_measurements=shake_measurements,
            transition_bands=engine_bands(bands))
        net_zone = _np.asarray(zone_with, bool) & ~_np.asarray(zone_without, bool)
        cell = float((gx[1] - gx[0]) * (gy[1] - gy[0]))
        net_sf = float(net_zone.sum() * cell)
        if net_sf <= 0:
            continue                          # the facet's own zone already sweeps the band: ZERO new area
        if valley_events:
            # The band is INSIDE the valley component. Carry that component's REMAINDER so the two
            # regions sum to exactly the one component the scope billed (Devore: 161.7 - 91.2 = 70.5,
            # not round(70.44) = 70.4, which would leak 0.1 SF; 349 - 204 = 145 EA, not ceil(70.44)).
            sf_receipt: float | None = round(_round_sf(area_with) - _round_sf(area_without), 1)
            count: int | None = int(_shake_count(float(area_with), 1.0, width_in, exposure_in)
                                    - _shake_count(float(area_without), 1.0, width_in, exposure_in))
        else:
            # The band IS its own scope component. Its own area, its own rounding. Unchanged from v55.
            sf_receipt, count = None, None
        edge_ids = ", ".join(sorted({str(b["edge_id"]) for b in bands}))
        to_shared = _facet_local_to_shared(geom, face_id)
        out.append(_event_dict(f"Transition {edge_ids}", face_id, net_sf, net_zone, gx, gy,
                               to_shared, shake_measurements,
                               affected_SF=sf_receipt, shake_count=count))
    return out


def _repair_facet_ids(confirmed_selection: Mapping[str, Any]) -> set[str]:
    out: set[str] = set()
    for item in confirmed_selection.get("single_valley_repairs", []):
        out.add(str(_confirmed_mapping(item)["face_id"]))
    for item in confirmed_selection.get("multi_valley_facets", []):
        out.add(str(_confirmed_mapping(item)["face_id"]))
    for item in confirmed_selection.get("notch_repairs", []):
        for member in _confirmed_mapping(item).get("member_face_ids", []):
            out.add(str(member))
    return out


def _notch_zone_inputs(geom: EagleViewGeometry, candidate: Any):
    anchor_line_id = str(candidate.params["anchor_line_id"])
    anchor_line = geom.lines[anchor_line_id]
    frame_ids = tuple(str(pid) for pid in candidate.params["frame_point_ids"])
    from module1_service import mkframe_pts
    frame = mkframe_pts(
        [geom.points[pid] for pid in frame_ids],
        geom.points[anchor_line.path[0]],
        geom.points[anchor_line.path[-1]],
    )
    to_shared = _local_to_shared_transform(
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
        for line_id in candidate.params["bordering_valley_line_ids"]
    ]
    pens = []
    for member_face_id in candidate.params["member_face_ids"]:
        member_face = geom.faces.get(str(member_face_id))
        for child_id in (member_face.children if member_face else []):
            pen_face = geom.penetration_faces.get(child_id)
            if pen_face is not None and getattr(pen_face, "size", 0) > 0:
                pens.append([tuple(frame(geom.points[pid])) for pid in geom.ordered_face_point_ids(child_id)])
    return facet, valleys, notches, pens, to_shared


def _event_dict(
    label: object,
    facet_id: str,
    affected_sf_raw: float,
    zone: Any,
    gx: Sequence[float],
    gy: Sequence[float],
    to_shared: Callable[[Sequence[float]], list[float]],
    shake_measurements: Mapping[str, Any] | None = None,
    affected_SF: float | None = None,
    shake_count: int | None = None,
) -> dict[str, Any]:
    # `affected_SF` / `shake_count` are explicit REMAINDER values, supplied ONLY by an incremental
    # transition-band region drawn on a facet whose band the scope counts INSIDE another component
    # (see _transition_regions). Both SF and EA are rounded/ceil()ed ONCE PER SCOPE COMPONENT, so a
    # region that is only PART of a component must carry that component's remainder rather than its
    # own independent rounding — otherwise the two regions sum to 0.1 SF (and up to one shake) less
    # than the single component they are drawing. The POLYGON is always the region's true traced
    # zone; only the receipt it is labelled with is the remainder. Every other event is a component in
    # its own right and derives both values from its own area, exactly as before.
    return {
        "event_label": str(label),
        "facet_id": str(facet_id),
        "affected_polygon": _zone_to_polygon(zone, gx, gy, to_shared, affected_sf_raw),
        "affected_SF": _round_sf(affected_sf_raw) if affected_SF is None else _round_sf(affected_SF),
        "shake_count": int(_shake_count(float(affected_sf_raw), 1.0, (shake_measurements or {}).get("width_in", 7.0), (shake_measurements or {}).get("exposure_in", 10.0))) if shake_count is None else int(shake_count),
    }


def _zone_to_polygon(
    zone: Any,
    gx: Sequence[float],
    gy: Sequence[float],
    to_shared: Callable[[Sequence[float]], list[float]] | None = None,
    target_area: float | None = None,
) -> list[list[float]]:
    """Trace the engine zone mask into a JSON-safe polygon ring.

    The affected area is not derived here. The frozen engine returns the zone
    mask and Module 1 returns the verified SF; this exporter only converts the
    occupied mask cells into a drawable rectilinear outline. When ``to_shared``
    is supplied, each traced local point is re-projected into the same shared
    roof frame used by workbench_roof_layout. ``target_area`` is retained for
    call compatibility and intentionally not used for centroid rescaling.
    """
    arr = np.asarray(zone, dtype=bool)
    if arr.size == 0 or not arr.any():
        return []

    res_x = _grid_res(gx)
    res_y = _grid_res(gy)
    rings = _mask_boundary_rings(arr)
    if not rings:
        return []

    x0 = float(gx[0]) - res_x / 2.0
    y0 = float(gy[0]) - res_y / 2.0

    def to_points(ring: Sequence[tuple[int, int]]) -> list[list[float]]:
        return _round_and_clean_ring([(x0 + col * res_x, y0 + row * res_y) for col, row in ring])

    # Preserve the single-ring UI contract. When the mask contains holes or rare
    # disconnected islands, concatenate the rings with zero-area bridge segments.
    # The shoelace area remains the signed sum of the engine mask boundaries, and
    # SVG still receives one closed [x, y] path.  # TODO multi-component
    cleaned_rings = [to_points(ring) for ring in sorted(rings, key=lambda r: abs(_signed_shoelace_area(r)), reverse=True)]
    cleaned_rings = [ring for ring in cleaned_rings if len(ring) >= 4]
    if not cleaned_rings:
        return []

    # Multi-ring: return each connected mask boundary (and hole) as its OWN ring,
    # drawn with fill-rule=evenodd on the client. No zero-area bridge segments, so
    # no stray connector lines. Largest ring first (used for the label centroid).
    if to_shared is None:
        return cleaned_rings
    return [[to_shared(pt) for pt in ring] for ring in cleaned_rings]


def _mask_boundary_rings(arr: Any) -> list[list[tuple[int, int]]]:
    """Return directed boundary rings of a boolean cell mask.

    Nodes are integer grid-corner coordinates (col, row). The directed edges are
    emitted clockwise around True cells, which makes holes naturally carry the
    opposite signed area.
    """
    import numpy as np
    from collections import defaultdict

    mask = np.asarray(arr, dtype=bool)
    if mask.size == 0 or not mask.any():
        return []

    nrows, ncols = mask.shape
    ys, xs = np.nonzero(mask)
    outgoing: dict[tuple[int, int], list[tuple[int, int]]] = defaultdict(list)
    directed_edges: set[tuple[tuple[int, int], tuple[int, int]]] = set()

    def add(a: tuple[int, int], b: tuple[int, int]) -> None:
        edge = (a, b)
        if edge not in directed_edges:
            directed_edges.add(edge)
            outgoing[a].append(b)

    for i, j in zip(ys.tolist(), xs.tolist()):
        below_empty = i == 0 or not mask[i - 1, j]
        above_empty = i == nrows - 1 or not mask[i + 1, j]
        left_empty = j == 0 or not mask[i, j - 1]
        right_empty = j == ncols - 1 or not mask[i, j + 1]

        if below_empty:
            add((j + 1, i), (j, i))
        if above_empty:
            add((j, i + 1), (j + 1, i + 1))
        if left_empty:
            add((j, i), (j, i + 1))
        if right_empty:
            add((j + 1, i + 1), (j + 1, i))

    visited: set[tuple[tuple[int, int], tuple[int, int]]] = set()
    rings: list[list[tuple[int, int]]] = []

    for edge in list(directed_edges):
        if edge in visited:
            continue
        start, nxt = edge
        ring = [start]
        current = start
        next_node = nxt
        while True:
            step = (current, next_node)
            if step in visited:
                break
            visited.add(step)
            ring.append(next_node)
            current = next_node
            if current == start:
                rings.append(ring)
                break
            candidates = outgoing.get(current, [])
            unvisited = [cand for cand in candidates if (current, cand) not in visited]
            if not unvisited:
                break
            next_node = _choose_boundary_successor(ring[-2], current, unvisited)

    return rings


def _choose_boundary_successor(prev: tuple[int, int], current: tuple[int, int], candidates: Sequence[tuple[int, int]]) -> tuple[int, int]:
    """Choose a deterministic continuation at a boundary corner."""
    if len(candidates) == 1:
        return candidates[0]

    dx = current[0] - prev[0]
    dy = current[1] - prev[1]
    # Prefer right turn, then straight, then left, then reverse for clockwise
    # cell boundaries with the occupied mask on the right-hand side.
    ranked: list[tuple[int, tuple[int, int]]] = []
    for cand in candidates:
        ndx = cand[0] - current[0]
        ndy = cand[1] - current[1]
        cross = dx * ndy - dy * ndx
        dot = dx * ndx + dy * ndy
        if cross < 0:
            rank = 0
        elif cross == 0 and dot > 0:
            rank = 1
        elif cross > 0:
            rank = 2
        else:
            rank = 3
        ranked.append((rank, cand))
    ranked.sort(key=lambda item: (item[0], item[1]))
    return ranked[0][1]


def _row_runs(arr: Any) -> list[tuple[int, int, int]]:
    """Return one occupied [start,end] column run per occupied row."""
    import numpy as np

    mask = np.asarray(arr, dtype=bool)
    rows = np.flatnonzero(mask.any(axis=1))
    out: list[tuple[int, int, int]] = []
    for row in rows.tolist():
        cols = np.flatnonzero(mask[row])
        if cols.size:
            out.append((int(row), int(cols.min()), int(cols.max())))
    return out


def _largest_mask_component(arr: Any) -> Any:
    """Keep the largest 4-connected mask component without new dependencies."""
    import numpy as np
    from collections import deque

    mask = np.asarray(arr, dtype=bool)
    ys, xs = np.nonzero(mask)
    if ys.size == 0:
        return mask

    occupied = set(zip(ys.tolist(), xs.tolist()))
    best: set[tuple[int, int]] = set()
    while occupied:
        start = occupied.pop()
        component = {start}
        q: deque[tuple[int, int]] = deque([start])
        while q:
            y, x = q.popleft()
            for nb in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
                if nb in occupied:
                    occupied.remove(nb)
                    component.add(nb)
                    q.append(nb)
        if len(component) > len(best):
            best = component

    out = np.zeros_like(mask, dtype=bool)
    if best:
        by, bx = zip(*best)
        out[list(by), list(bx)] = True
    return out


def _round_and_clean_ring(points: Sequence[Sequence[float]]) -> list[list[float]]:
    cleaned: list[tuple[float, float]] = []
    for x, y in points:
        pt = (round(float(x), 4), round(float(y), 4))
        if not cleaned or cleaned[-1] != pt:
            cleaned.append(pt)

    if len(cleaned) > 1 and cleaned[0] == cleaned[-1]:
        open_pts = cleaned[:-1]
    else:
        open_pts = cleaned

    changed = True
    while changed and len(open_pts) >= 3:
        changed = False
        next_pts: list[tuple[float, float]] = []
        n = len(open_pts)
        for idx, pt in enumerate(open_pts):
            prev_pt = open_pts[(idx - 1) % n]
            next_pt = open_pts[(idx + 1) % n]
            collinear_vertical = prev_pt[0] == pt[0] == next_pt[0]
            collinear_horizontal = prev_pt[1] == pt[1] == next_pt[1]
            if collinear_vertical or collinear_horizontal:
                changed = True
                continue
            next_pts.append(pt)
        open_pts = next_pts

    if not open_pts:
        return []
    if open_pts[0] != open_pts[-1]:
        open_pts.append(open_pts[0])
    return [[float(x), float(y)] for x, y in open_pts]


def _scale_polygon_to_area(poly: Sequence[Sequence[float]], target_area: float) -> list[list[float]]:
    """Preserve the engine's surface-area receipt after shared-frame placement.

    The shared roof frame is the parser POINT x/y drawing frame.  For pitched
    facets, a 3D -> x/y projection naturally has smaller shoelace area than the
    surface-area returned by affected_area.  The UI still needs the verified SF
    receipt to reconcile, so after landing the polygon in the shared frame we
    scale about its centroid to keep the polygon's drawable area equal to the
    frozen engine affected area.  This changes only drawing coordinates.
    """
    current = _shoelace_area(poly)
    if current <= 0 or target_area <= 0:
        return [[round(float(p[0]), 6), round(float(p[1]), 6)] for p in poly]
    factor = (target_area / current) ** 0.5
    closed = len(poly) > 1 and list(poly[0]) == list(poly[-1])
    pts = list(poly[:-1] if closed else poly)
    cx = sum(float(p[0]) for p in pts) / len(pts)
    cy = sum(float(p[1]) for p in pts) / len(pts)
    scaled = [
        [round(cx + (float(p[0]) - cx) * factor, 6), round(cy + (float(p[1]) - cy) * factor, 6)]
        for p in pts
    ]
    if closed:
        scaled.append(list(scaled[0]))
    return scaled


# local/shared affine helpers are imported from workbench_roof_layout so layout export
# and diagram drawing share one coordinate transform implementation.

def _grid_res(values: Sequence[float]) -> float:
    return abs(float(values[1]) - float(values[0])) if len(values) > 1 else 0.04


def _round_sf(value: float) -> float:
    return round(float(value), 1)


def _roof_area_sf(geom: EagleViewGeometry) -> float:
    total = 0.0
    for face in geom.roof_faces.values():
        if face.unrounded_size is not None:
            total += float(face.unrounded_size)
        elif face.size is not None:
            total += float(face.size)
    return total


def _signed_shoelace_area(poly: Sequence[Sequence[float]]) -> float:
    if len(poly) < 3:
        return 0.0
    pts = list(poly)
    if pts[0] == pts[-1]:
        pts = pts[:-1]
    area = 0.0
    for i in range(len(pts)):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % len(pts)]
        area += float(x1) * float(y2) - float(x2) * float(y1)
    return area / 2.0

def _shoelace_area(poly: Sequence[Sequence[float]]) -> float:
    if len(poly) < 3:
        return 0.0
    pts = list(poly)
    if pts[0] == pts[-1]:
        pts = pts[:-1]
    area = 0.0
    for i in range(len(pts)):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % len(pts)]
        area += float(x1) * float(y2) - float(x2) * float(y1)
    return abs(area) / 2.0


def _run_receipts() -> int:
    """SELF-RECEIPT — asserts THE INVARIANT, not a magic number.

    RE-GROUNDED v57 (2026-07-22). This used to read:

        total_ok = result["summary"]["total_SF"] == 1638.0 and result["summary"]["total_EA"] == 3691

    Two hard-coded totals from before Path A was activated, so this receipt printed FAIL on a healthy
    build for eleven versions. Re-baselining them to 1639.4 / 3382 would have bought about one
    re-grounding of silence and then gone stale again in exactly the same way — the failure mode is
    the MAGIC NUMBER, not the value in it.

    So it asserts what the diagram actually OWES instead:

        diagram total_SF == scope affected_SF_display_total   AND   diagram total_EA == scope shake EA

    computed from the SAME selection in the SAME run. That is the rule the whole v56 fix exists to
    protect — THE DIAGRAM READS FROM THE MATH; it may never report a total that disagrees with the
    scope — it is self-maintaining across any future re-grounding, and it is a strictly STRONGER check
    than the pair of constants it replaces: a hard-coded 1639.4 only fails if the diagram breaks, but
    this fails if the diagram and the scope ever diverge FOR ANY REASON, on any of the selections
    below. Fed the v55 diagram code it fails on the overlap selection, which is the bug v56 fixed.

    The selections are chosen so at least one of them can actually fail: the DEFAULT Yager selection
    is structurally blind to the transition-band overlap bug (facet V is 100% swept, so its band adds
    0 SF), which is precisely how that bug survived. The empty-selection check is kept as it was.
    """
    import json
    from module1_yager_proof import YAGER_CONFIRMED_SELECTION
    from workbench_seam import build_scope_from_ui_selection, _ui_selection_from_confirmed_selection

    xml = open("XML.txt", encoding="utf-8").read()
    ui = _ui_selection_from_confirmed_selection(YAGER_CONFIRMED_SELECTION, xml_text=xml)
    l79 = [{"edge_id": "L79", "exposed": True, "damaged": True}]

    selections = [
        ("Yager default (Path A, L33 auto)", ui),
        ("Yager default + L79 confirmed", {**ui, "transition_repairs": l79}),
        # THE ONE THAT CAN FAIL: F17 carries BOTH a valley repair and a band that adds real area.
        ("OVERLAP — L79 + the Q side (F17) of L83/L84",
         {"xml_text": xml,
          "valley_intersections": [{"face_id": "F17", "valley_id": "L83", "claim_valley_lf": True},
                                   {"face_id": "F17", "valley_id": "L84", "claim_valley_lf": True}],
          "appurtenances": [], "notches": [], "transition_repairs": l79}),
    ]

    print("ROOF-FRAME TRACER RECEIPTS")
    result = build_diagram_data(xml, ui)
    print("json_serializable:", bool(json.dumps(result)))
    print("events:", len(result["events"]))
    print("summary:", result["summary"])
    print("label | affected_SF | shake_count | shared_vertices | shared_polygon_area")
    for event in result["events"]:
        print(
            f"{event['event_label']} | {float(event['affected_SF']):.1f} | "
            f"{event['shake_count']} | {len(event['affected_polygon'])} | "
            f"{_shoelace_area(event['affected_polygon']):.1f}"
        )

    print("\nTHE INVARIANT — diagram == scope, both totals, same selection, same run:")
    total_ok = True
    for label, selection in selections:
        diagram = build_diagram_data(xml, selection)
        scope = build_scope_from_ui_selection(xml, selection)
        d_sf = round(float(diagram["summary"]["total_SF"]), 1)
        d_ea = int(diagram["summary"]["total_EA"])
        s_sf = round(float(scope.affected_SF_display_total), 1)
        s_ea = int(next(float(l.qty) for l in scope.aggregated_scope
                        if l.category_id == "SHAKE_FIELD_RR"))
        # Summed from the events actually DRAWN, so the header can never disagree with the picture.
        drawn_sf = round(sum(float(e["affected_SF"]) for e in diagram["events"]), 1)
        drawn_ea = sum(int(e["shake_count"]) for e in diagram["events"])
        ok = (d_sf, d_ea) == (s_sf, s_ea) == (drawn_sf, drawn_ea)
        total_ok &= ok
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}: diagram {d_ea} EA / {d_sf} SF == "
              f"drawn {drawn_ea} / {drawn_sf} == scope {s_ea} / {s_sf}")

    empty = build_diagram_data(xml, {"selected_valley_ids": [], "single_valley_repairs": [], "multi_valley_facets": [], "penetration_appurtenance_repairs": [], "notch_repairs": []})
    empty_ok = empty["events"] == [] and empty["summary"]["total_SF"] == 0.0 and empty["summary"]["total_EA"] == 0
    print("invariant_check:", "PASS" if total_ok else "FAIL")
    print("empty_selection:", "PASS" if empty_ok else "FAIL", empty)
    print("RESULT:", "PASS" if total_ok and empty_ok else "FAIL")
    return 0 if total_ok and empty_ok else 1


if __name__ == "__main__":
    import sys as _sys
    _sys.exit(_run_receipts())
