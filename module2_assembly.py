#!/usr/bin/env python3
# CHANGELOG 2026-07-04: notch valley set now selection-driven (override_valley_ids); fallback preserves anchor 3691.
# CHANGELOG 2026-06-29 (Phase-2 re-baseline 3709->3691 EA / 1645.6->1638.0 SF):
#   Consistent clipped penetration exclusion across single/multi/notch paths,
#   dimensional-only (footprint >= 0.5 SF carves; point < 0.5 SF lays over).
#   - multi path: no longer include_child_penetrations flag-gated; always passes
#     dimensional penetrations to affected_area's existing clipped exclusion.
#   - notch path: now carves member-facet dimensional penetrations (frame-transformed).
#   - dedup-as-subsumed-event: in-field appurtenance (host is a confirmed repair facet)
#     contributes flashing/IWS only, 0 double-counted field shakes.
#   Prior multi/notch skipped the exclusion the single path already ran; only F70
#   (in-zone chimney on F4) moves the total. See module1_yager_proof.py.
"""Full-roof Module 2 assembly with physical shared-edge deduplication.

Assembly/translation only. Frozen expand_scope remains the material-rule engine;
this layer prevents physical edges shared by two in-scope facets from being
scoped twice by unioning contact by XML line id before one final edge-only
expand_scope call.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Tuple

import numpy as np

from candidate_model import Candidate
from eagleview_geometry_parser import EagleViewGeometry, parse_eagleview_geometry
from module1_m2interface import affected_area, build_m1_interface_for_face, edge_contacts, _quiet_import_regression_symbol
from module1_selected_valley_handoff import selected_valley_handoff
from module2_scope_expansion import Edge, M1Interface, ScopeLine, Transition, expand_scope, eave_iws_coverage, _eave_iws_citation
from transition_events import (
    active_transitions as _active_transitions,
    engine_bands,
    selected_transition_repairs,
    transition_bands_by_face,
    transition_contact_lf,
)
from notch_candidate_emitter import emit_notch_candidates, encoding_b_candidate as _emit_encoding_b_candidate
# ONE AUTHORITY for "does this appurtenance disturb the shake field?". module1_service imports
# the SAME function for the diagram, so the picture cannot disagree with the scope.
from shared_category_registry import appurtenance_carves, is_power_vent


@dataclass(frozen=True)
class EdgeContribution:
    line_id: str
    edge_type: str
    contact_LF: float
    edge_total_LF: float
    component: str


@dataclass(frozen=True)
class ComponentAssembly:
    label: str
    face_id: str
    component_type: str
    geometry_status: str
    surface_status: str
    reason: str
    iface: M1Interface
    scope_lines: Tuple[ScopeLine, ...]
    edge_contributions: Tuple[EdgeContribution, ...]


@dataclass(frozen=True)
class AggregatedScopeLine:
    item: str
    category_id: str
    qty: float
    unit: str
    gate: str
    # The Xactimate code the line will actually be billed under. Additive: defaults to None, so every
    # existing construction is unchanged. It was previously DROPPED at aggregation, so the size the
    # user set on page 2 never reached the report at all.
    xact_code: Optional[str] = None
    # THE AUTHORITY that puts this item in a proper repair — "IRC drip edge", "CSSB ridge detail",
    # "mfr / IRC flashing". Every ScopeLine has carried one all along; _aggregate_lines DROPPED it,
    # exactly as it dropped xact_code (fixed in v48). The consequence was severe: §5 could only print
    # the bare word "required", which is the TOOL drawing the conclusion — the very thing an adjuster
    # pushes back on. The report is supposed to DEMONSTRATE and let the reader conclude; it could not,
    # because the reason was destroyed before it reached the renderer.
    citation: Optional[str] = None


@dataclass(frozen=True)
class RoofAssemblyResult:
    components: Tuple[ComponentAssembly, ...]
    aggregated_scope: Tuple[AggregatedScopeLine, ...]
    affected_SF_raw_total: float
    affected_SF_display_total: float
    selected_valley_LF_total: float
    derivation_breakdown: Tuple[Mapping[str, str], ...]
    deduped_edges: Tuple[EdgeContribution, ...]
    edge_scope_lines: Tuple[ScopeLine, ...]
    # v61 full slope replacement: facet designators by kind, so the report can label the two shake
    # lines ("Slope replacement (facets M, O)" vs "Slope repair (facets J, K, N)"). Empty when a
    # roof has no replacement (repair-only) or no repair (full replacement) — additive, default ().
    replacement_facets: Tuple[str, ...] = ()
    repair_facets: Tuple[str, ...] = ()
    # v65 structure separation: {structure_id: (AggregatedScopeLine, ...)} keyed by the <ROOF id="…">
    # each facet belongs to. Additive and default-empty. For a single-structure roof the ONE entry is
    # byte-identical to aggregated_scope (a lone structure shares no edge across a boundary, so its
    # per-structure dedup equals the global dedup). The report shows structure headings only when this
    # has 2+ entries; otherwise it renders exactly as before.
    aggregated_scope_by_structure: Tuple[Tuple[str, Tuple[AggregatedScopeLine, ...]], ...] = ()
    # v65: (structure_id, total ROOF facet count) for every structure in the geometry — the count the
    # report heading shows ("Dwelling — 14 facets"). From the parser, not from what was repaired, so it
    # reflects the structure's size. Empty/single-entry when the XML has no multi-ROOF nesting.
    structure_facet_counts: Tuple[Tuple[str, int], ...] = ()
    # v69: per-structure affected SF (for §2's per-structure dual) and the replacement/repair facet
    # labels grouped by structure (for §3's per-structure slope callouts). Additive; empty/one-entry
    # for a single-structure roof, where the report renders byte-identically to before.
    structure_affected_SF: Tuple[Tuple[str, float], ...] = ()
    replacement_facets_by_structure: Tuple[Tuple[str, Tuple[str, ...]], ...] = ()
    repair_facets_by_structure: Tuple[Tuple[str, Tuple[str, ...]], ...] = ()
    # v71 DEFECT 3: eave ICE & WATER metadata for the report — basis (code/existing), computed
    # coverage, exposed eave LF, layer count, and the soffit depth used (None when defaulted). None
    # when the user did not assert eave IWS. The report cites the basis and states the layer count;
    # the "defaulted" fact never reaches the report (the page-2 warning carries that).
    eave_iws: Optional[Mapping[str, object]] = None


mkframe_pts = _quiet_import_regression_symbol("mkframe_pts")
resolve_shake_measurements = _quiet_import_regression_symbol("resolve_shake_measurements")

_EDGE_DRIVEN_CATEGORIES = {
    "RIDGE_CAPS",
    "HIP_CAPS",
    "STARTER",
    "DRIP_EDGE",
    "STEP_FLASH",
    "ENDWALL_FLASH",
}


def _shake_measurements_from_selection(confirmed_selection: Mapping[str, object]) -> Mapping[str, object]:
    raw = confirmed_selection.get("shake_measurements") or confirmed_selection.get("shake_profile") or {}
    return resolve_shake_measurements(raw)

def assemble_full_roof_scope(xml_text: str, confirmed_selection: Mapping[str, object]) -> RoofAssemblyResult:
    """Build full roof scope from confirmed selections using surfaced M1 interfaces."""
    geom = parse_eagleview_geometry(xml_text)
    notch_candidates = {tuple(c.source_ids): c for c in emit_notch_candidates(geom)}
    shake_measurements = _shake_measurements_from_selection(confirmed_selection)
    # v71 DEFECT 3: eave ICE & WATER. The assertion (page 2) fires it only when code and/or existing
    # is marked; the measured soffit depth (page 1) sets the coverage width and layer count. Both are
    # roof-level and are threaded onto the FACET interfaces only (eaves are per-facet perimeter edges,
    # never shared across facets, so no double count) — not the appurtenance host interfaces.
    _eave_iws = confirmed_selection.get("eave_iws")
    _eave_iws_basis = (_eave_iws if isinstance(_eave_iws, Mapping)
                       and (_eave_iws.get("code") or _eave_iws.get("existing")) else None)
    _soffit_depth = confirmed_selection.get("soffit_depth_in")
    if _soffit_depth in (None, "") and isinstance(shake_measurements, Mapping):
        _soffit_depth = shake_measurements.get("soffit_depth_in")
    selected_valley_ids = tuple(str(v) for v in confirmed_selection.get("selected_valley_ids", ()))
    selected_meta = selected_valley_handoff(xml_text, selected_valley_ids) if selected_valley_ids else {"selected_valley_LF_total": 0.0}
    selected_valley_lf = float(selected_meta["selected_valley_LF_total"])
    valley_lf_claimed: set[str] = set()

    # --- PATH B: user-confirmed transition repair events (spec amendment v0.1) ---------------
    # The gate (exposed AND damaged) is enforced in transition_events at the DATA layer, so a
    # hand-crafted payload cannot bypass it. Only DETECTED transitions can be selected — the
    # three-condition detector is untouched and edge_total_LF is never user-edited.
    # Bands are precomputed per facet and handed to the SAME affected_area call as that facet's
    # valley events, so the zones UNION (never sum). No transition selected -> empty dict ->
    # every existing call is bit-for-bit unchanged and the anchor holds by construction.
    # BUILD 2b — PATH A IS NOW LIVE. This line used to be `transitions=[]`, hardcoded, so the >=95%
    # passive rule NEVER RAN on a real roof: Yager's L33 is swept 100% by the standard repair and was
    # being silently dropped. Both paths are evaluated now, each transition appearing exactly ONCE.
    # Facets the USER asserted are high (2-story). EagleView cannot tell us this — it gives roof
    # geometry, not wall heights — so it is an explicit assertion, and page 2 forces the decision.
    _high_slope = _high_slope_faces(confirmed_selection)

    active_transitions = _active_transitions(geom, confirmed_selection)
    bands_by_face = transition_bands_by_face(geom, confirmed_selection, shake_measurements) if active_transitions else {}
    if bands_by_face:
        confirmed_selection = {**dict(confirmed_selection), "_transition_bands_by_face": bands_by_face}

    components: List[ComponentAssembly] = []
    breakdown: List[Mapping[str, str]] = []

    for item in confirmed_selection.get("single_valley_repairs", ()):  # type: ignore[union-attr]
        row = _as_mapping(item)
        face_id = str(row["face_id"])
        valley_id = str(row["valley_id"])
        _require_valley_borders_face(geom, valley_id, face_id)
        valley_lf = _claim_valley_lf_once(geom, valley_id, selected_valley_ids, valley_lf_claimed)
        affected = _single_valley_area(geom, face_id, valley_id, confirmed_selection)
        iface = build_m1_interface_for_face(
            geom,
            face_id,
            confirmed_valley_line_ids=(valley_id,),
            affected_SF=affected,
            valley_LF_in_scope=valley_lf,
            confirmed_appurtenance_candidates=(),
            shake_measurements=shake_measurements,
            facet_pitch_tier=_facet_pitch_tier(geom, face_id),
            high_slope_user_flag=(str(face_id) in _high_slope),
        )
        edge_contribs = _face_edge_contributions(geom, face_id, (valley_id,), str(row.get("label", face_id)), shake_measurements)
        components.append(_component(row, face_id, "single_valley", "derived", "fully_surfaced", "face, valley event, edges, and valley LF derived from parser/candidates", iface, edge_contribs))
        breakdown.append(_breakdown(components[-1]))

    for item in confirmed_selection.get("multi_valley_facets", ()):  # type: ignore[union-attr]
        row = _as_mapping(item)
        face_id = str(row["face_id"])
        valley_ids = tuple(str(v) for v in row.get("valley_ids", ()))
        for valley_id in valley_ids:
            _require_valley_borders_face(geom, valley_id, face_id)
        valley_lf = sum(_claim_valley_lf_once(geom, valley_id, selected_valley_ids, valley_lf_claimed) for valley_id in valley_ids)
        affected = _multi_valley_union_area(geom, face_id, valley_ids, confirmed_selection, include_child_penetrations=bool(row.get("include_child_penetrations", True)))
        iface = build_m1_interface_for_face(
            geom,
            face_id,
            confirmed_valley_line_ids=valley_ids,
            affected_SF=affected,
            valley_LF_in_scope=valley_lf,
            confirmed_appurtenance_candidates=(),
            shake_measurements=shake_measurements,
            facet_pitch_tier=_facet_pitch_tier(geom, face_id),
            high_slope_user_flag=(str(face_id) in _high_slope),
        )
        edge_contribs = _face_edge_contributions(geom, face_id, valley_ids, str(row.get("label", face_id)), shake_measurements)
        components.append(_component(row, face_id, "multi_valley", "derived", "fully_surfaced", "multi-valley union, edges, and non-duplicated selected valley LF derived from parser/candidates", iface, edge_contribs))
        breakdown.append(_breakdown(components[-1]))

    # --- PATH C: FULL SLOPE REPLACEMENT (v61) -------------------------------------------------
    # A facet marked for full replacement: the WHOLE facet (net of penetrations) comes off, billed in
    # SQUARES (a stripped slope is conventional square-based work; billing EA would claim the repair
    # labor premium a full slope does not involve). The perimeter falls out of the EXISTING edge rules
    # at 100% contact, deduped against an adjoining facet. VALLEY_METAL/IWS bill ONLY from
    # valley_LF_in_scope, so every valley on the facet's perimeter is claimed here (the whole valley
    # comes out — you cannot replace half a W-metal), deduped against any facet that also claims it.
    # Steep/high-slope and felt are area-driven and fire automatically on the full area. No facet
    # marked -> this loop is empty and every existing selection is bit-for-bit unchanged.
    _replaced_ids = {str(_as_mapping(_it)["face_id"]) for _it in confirmed_selection.get("replaced_facets", ())}
    if _replaced_ids:
        # MUTUAL EXCLUSION (rule 2): a facet cannot be replaced AND repaired. The UI clears the repair
        # selection; enforce it at the DATA layer so a hand-built payload cannot double-count a slope.
        for _it in (*confirmed_selection.get("single_valley_repairs", ()), *confirmed_selection.get("multi_valley_facets", ())):
            if str(_as_mapping(_it)["face_id"]) in _replaced_ids:
                raise ValueError(f"facet {_as_mapping(_it)['face_id']} is marked for BOTH replacement and repair")
    for item in confirmed_selection.get("replaced_facets", ()):
        row = _as_mapping(item)
        face_id = str(row["face_id"])
        if face_id not in geom.roof_faces:
            raise ValueError(f"replaced facet {face_id} is not a roof facet")
        label = str(row.get("label", face_id))
        affected = _replacement_facet_area(geom, face_id)
        valley_lf = sum(_claim_replacement_valley_lf(geom, vid, valley_lf_claimed)
                        for vid in _facet_valley_ids(geom, face_id))
        iface = build_m1_interface_for_face(
            geom,
            face_id,
            confirmed_valley_line_ids=(),
            affected_SF=affected,
            valley_LF_in_scope=valley_lf,
            confirmed_appurtenance_candidates=(),
            shake_measurements=shake_measurements,
            facet_pitch_tier=_facet_pitch_tier(geom, face_id),
            high_slope_user_flag=(face_id in _high_slope),
            is_replacement=True,
        )
        edge_contribs = _replacement_edge_contributions(geom, face_id, label)
        components.append(_component(row, face_id, "replacement", "derived", "fully_surfaced",
            "full slope replacement: whole facet net of penetrations, 100% perimeter contact, all valleys fully in scope", iface, edge_contribs))
        breakdown.append(_breakdown(components[-1]))

    for item in confirmed_selection.get("penetration_appurtenance_repairs", ()):  # type: ignore[union-attr]
        row = _as_mapping(item)
        penetration_id = str(row["penetration_face_id"])
        host_face_id = str(row.get("host_face_id") or _host_face_for_penetration(geom, penetration_id))
        candidate = _penetration_candidate_from_geom(geom, host_face_id, penetration_id)
        _rfacets = set()
        for _it in confirmed_selection.get("single_valley_repairs", ()): _rfacets.add(str(_as_mapping(_it)["face_id"]))
        for _it in confirmed_selection.get("multi_valley_facets", ()): _rfacets.add(str(_as_mapping(_it)["face_id"]))
        for _it in confirmed_selection.get("notch_repairs", ()):
            for _m in _as_mapping(_it).get("member_face_ids", ()): _rfacets.add(str(_m))
        # In-field appurtenance dedup is union-not-sum: only the overlap with
        # already-scoped repair zones is subsumed. Any portion of the 21in
        # disturbance zone outside the host/merged-plane repair union still counts.
        # THE FAN CARVES. THE COVER DOES NOT. One authority for the question, imported from
        # shared_category_registry so the SCOPE and the DIAGRAM (module1_service) can never drift.
        # A cover-only power vent contributes ZERO affected area — the carve is the ONLY thing that
        # differs between the two operations; the material line below is identical for both.
        _carves = appurtenance_carves(row)
        _replaced_ids = {str(_as_mapping(_it)["face_id"]) for _it in confirmed_selection.get("replaced_facets", ())}
        affected = _appurtenance_union_affected_area(geom, host_face_id, candidate, confirmed_selection, _carves, _replaced_ids, _rfacets)
        appurt_candidate = _with_appurtenance_label(candidate, str(row.get("kind_label", "CHIMNEY")), str(row.get("group", penetration_id)), row.get("contacted"), row.get("size_class"), carves=_carves, other_label=row.get("other_label"), other_category=row.get("other_category"))
        iface = build_m1_interface_for_face(
            geom,
            host_face_id,
            confirmed_valley_line_ids=(),
            affected_SF=affected,
            valley_LF_in_scope=0.0,
            confirmed_appurtenance_candidates=(appurt_candidate,),
            shake_measurements=shake_measurements,
            # THE FACET IS host_face_id here, not the loop's `face_id` — reading the wrong variable
            # made a 7-9 appurtenance emit a ">12" steep charge and a high-slope charge nobody asserted.
            facet_pitch_tier=_facet_pitch_tier(geom, host_face_id),
            high_slope_user_flag=(str(host_face_id) in _high_slope),
        )
        edge_contribs = _face_edge_contributions(geom, host_face_id, (), str(row.get("label", host_face_id)), shake_measurements)
        components.append(_component(row, host_face_id, "penetration_appurtenance", "derived", "fully_surfaced", "host facet, appurtenance footprint, edges, and Appurt payload derived from parser/candidates", iface, edge_contribs))
        breakdown.append(_breakdown(components[-1]))

    for item in confirmed_selection.get("user_appurtenance_repairs", ()):  # type: ignore[union-attr]
        row = _as_mapping(item)
        if not bool(row.get("repair_event", True)):
            continue
        host_face_id = str(row["host_facet_id"])
        candidate = _user_appurtenance_candidate_from_row(row)
        _rfacets = set()
        for _it in confirmed_selection.get("single_valley_repairs", ()): _rfacets.add(str(_as_mapping(_it)["face_id"]))
        for _it in confirmed_selection.get("multi_valley_facets", ()): _rfacets.add(str(_as_mapping(_it)["face_id"]))
        for _it in confirmed_selection.get("notch_repairs", ()):
            for _m in _as_mapping(_it).get("member_face_ids", ()): _rfacets.add(str(_m))
        # THE FAN CARVES. THE COVER DOES NOT — same single authority as the XML-detected path above.
        # A user-placed power vent behaves identically to a detected one; nothing about the rule
        # depends on where the marker came from.
        _carves = appurtenance_carves(row)
        _replaced_ids = {str(_as_mapping(_it)["face_id"]) for _it in confirmed_selection.get("replaced_facets", ())}
        affected = _appurtenance_union_affected_area(geom, host_face_id, candidate, confirmed_selection, _carves, _replaced_ids, _rfacets)
        appurt_candidate = _with_appurtenance_label(candidate, str(row.get("kind_label", "OTHER")), str(row.get("designator") or row.get("label") or "user"), row.get("contacted"), row.get("size_class"), carves=_carves, other_label=row.get("other_label"), other_category=row.get("other_category"))
        iface = build_m1_interface_for_face(
            geom,
            host_face_id,
            confirmed_valley_line_ids=(),
            affected_SF=affected,
            valley_LF_in_scope=0.0,
            confirmed_appurtenance_candidates=(appurt_candidate,),
            shake_measurements=shake_measurements,
            # THE FACET IS host_face_id here, not the loop's `face_id` — reading the wrong variable
            # made a 7-9 appurtenance emit a ">12" steep charge and a high-slope charge nobody asserted.
            facet_pitch_tier=_facet_pitch_tier(geom, host_face_id),
            high_slope_user_flag=(str(host_face_id) in _high_slope),
        )
        edge_contribs = _face_edge_contributions(geom, host_face_id, (), str(row.get("label", row.get("designator", host_face_id))), shake_measurements)
        components.append(_component(row, host_face_id, "user_appurtenance", "derived", "fully_surfaced", "host facet and user-entered appurtenance footprint supplied by confirmed selection", iface, edge_contribs))
        breakdown.append(_breakdown(components[-1]))

    for item in confirmed_selection.get("notch_repairs", ()):  # type: ignore[union-attr]
        row = _as_mapping(item)
        member_face_ids = tuple(str(v) for v in row["member_face_ids"])
        candidate = _require_notch_candidate(notch_candidates, member_face_ids)
        iface, edge_contribs = _build_m1_interface_for_notch(geom, candidate, selected_valley_ids, valley_lf_claimed, str(row.get("label", "+".join(member_face_ids))), confirmed_selection=confirmed_selection, override_valley_ids=row.get("valley_ids"), shake_measurements=shake_measurements)
        components.append(_component(row, "+".join(member_face_ids), "notch", "derived", "fully_surfaced", "merged facet, notch polygon, RIDGE anchor, VALLEY events, and edges derived from notch candidate", iface, edge_contribs))
        breakdown.append(_breakdown(components[-1]))

    # --- PATH B: carve the band on every facet the transition touches --------------------------
    # UNION, NEVER SUM. A facet that carries a VALLEY component already had its band unioned INTO
    # that component's affected_area call (the bands were threaded through the valley area helpers),
    # so it needs nothing more. Any OTHER facet the transition touches (e.g. Yager's P, which carries
    # only a chimney appurtenance) gets a transition component whose area is the band's INCREMENTAL
    # contribution: the facet's area WITH the band minus the same facet's area WITHOUT it, computed
    # over the identical set of that facet's other events. Overlap with an appurtenance (or anything
    # else already counted on that facet) therefore cancels out exactly — no double count.
    valley_threaded_faces = set()
    for item in confirmed_selection.get("single_valley_repairs", ()):  # type: ignore[union-attr]
        valley_threaded_faces.add(str(_as_mapping(item)["face_id"]))
    for item in confirmed_selection.get("multi_valley_facets", ()):    # type: ignore[union-attr]
        valley_threaded_faces.add(str(_as_mapping(item)["face_id"]))

    # v72 DEFECT 4: a transition band on a FULLY REPLACED facet lies inside a facet already 100%
    # scoped — exactly the appurtenance double-count fixed in v63, applied here to the transition path.
    # The band is UNIONED: it contributes NO incremental area and NO shakes (or the roof bills 186 EA
    # of shakes on a SQ replacement and gains +90.1632 SF). TRANSITION_FLASH and its underlayment still
    # fire — they are emitted at the ROOF level below, untouched by this skip.
    _replaced_band_ids = {str(_as_mapping(_it)["face_id"])
                          for _it in confirmed_selection.get("replaced_facets", ())}

    for face_id, bands in sorted(bands_by_face.items()):
        if face_id in valley_threaded_faces:
            continue                                   # band already unioned into the valley zone
        if str(face_id) in _replaced_band_ids:
            continue                                   # v72: band inside a fully-replaced facet -> unioned
        engine_face = geom.engine_facet(face_id)
        pens = _penetrations_with_user_footprints(geom, confirmed_selection, face_id)
        apps = _confirmed_appurtenance_geometries_for_face(geom, confirmed_selection, face_id)
        _p0, area_without = affected_area(
            engine_face.facet, [], appurtenances=apps, penetrations=pens,
            shake_measurements=shake_measurements)
        _p1, area_with = affected_area(
            engine_face.facet, [], appurtenances=apps, penetrations=pens,
            shake_measurements=shake_measurements, transition_bands=engine_bands(bands))
        net_area = max(0.0, float(area_with) - float(area_without))   # incremental, union-correct

        iface = build_m1_interface_for_face(
            geom,
            face_id,
            confirmed_valley_line_ids=(),
            affected_SF=net_area,
            valley_LF_in_scope=0.0,
            confirmed_appurtenance_candidates=(),
            shake_measurements=shake_measurements,
            facet_pitch_tier=_facet_pitch_tier(geom, face_id),
            high_slope_user_flag=(str(face_id) in _high_slope),
        )
        edge_ids = ", ".join(sorted({str(b["edge_id"]) for b in bands}))
        row = {"label": f"Transition {edge_ids} on {geom.faces[face_id].designator}", "face_id": face_id}
        components.append(_component(
            row, face_id, "transition_repair", "derived", "fully_surfaced",
            "user-confirmed transition repair event (exposed + damaged); band carved on both facets",
            iface, ()))
        breakdown.append(_breakdown(components[-1]))

    # ONE TRANSITION_FLASH per transition, emitted at the ROOF level (never per facet), exactly as
    # edge_scope_lines are. This is the structural de-dupe: the transition has TWO facets but only
    # ONE flashing line, at edge_total_LF — the true geometric length.
    # Each active transition is handed to expand_scope with its REAL contact_LF and its selected
    # flag, so the frozen rule there decides: Path A (contact >= 95%) OR Path B (user-confirmed).
    # De-dupe is structural at both levels — one entry per transition here, one `if` there.
    transition_scope_lines: tuple = ()
    if active_transitions:
        selected_ids = set(selected_transition_repairs(confirmed_selection))
        valley_ids = [str(v) for v in (confirmed_selection.get("selected_valley_ids", ()) or ())]
        transitions_for_scope = [
            Transition(
                contact_LF=transition_contact_lf(geom, t, valley_ids),
                edge_total_LF=float(t.edge_total_LF),
                selected=t.edge_id in selected_ids,
            )
            for t in active_transitions
        ]
        transition_scope_lines = tuple(
            expand_scope(M1Interface(transitions=transitions_for_scope), repair_factor=1.0))

    # ONE PHYSICAL OBJECT -> ONE MATERIAL LINE.
    # EagleView splits one physical chimney into one marker per facet it crosses. expand_scope
    # already dedupes appurtenances by `group` — but only WITHIN one M1Interface, and the assembly
    # gives every marker its OWN component/M1Interface, so that dedupe is never asked the question.
    # (That is why regression test 28 passed while two grouped markers still billed 2 flashings.)
    # The user links the markers of one physical object; the duplicate MATERIAL line is dropped here.
    #
    # CRITICAL — THE MATERIAL LINE ONLY:
    #   * the carved affected AREA stays per marker (the chimney really does penetrate both planes), and
    #   * APPURT_IWS stays per marker (both planes need ice & water).
    # Deduping either would silently UNDER-SCOPE the claim — invisible, and therefore worse than no
    # feature at all. An over-scope is visible and correctable; an under-scope is not.
    _APPURT_MATERIAL = {"CHIMNEY_FLASH", "SKYLIGHT_FLASH", "PIPE_JACK_FLASH", "BOX_VENT",
                        "TURBINE_VENT", "VENT_CAP", "CHIMNEY_CHASE_COVER", "RIDGE_VENT", "UNMAPPED"}
    _seen_appurt_groups: set = set()
    non_edge_lines: List[ScopeLine] = []
    all_edge_contribs: List[EdgeContribution] = []
    for comp in components:
        gid = next((a.group for a in comp.iface.appurts if a.group is not None), None)
        for line in comp.scope_lines:
            if line.category_id in _EDGE_DRIVEN_CATEGORIES:
                continue
            if gid is not None and line.category_id in _APPURT_MATERIAL:
                key = (gid, line.category_id)
                if key in _seen_appurt_groups:
                    continue                # same physical object -> its material line is already billed
                _seen_appurt_groups.add(key)
            non_edge_lines.append(line)
        all_edge_contribs.extend(comp.edge_contributions)

    deduped_edge_contribs = _dedupe_edge_contributions(all_edge_contribs)
    deduped_edges = [Edge(c.edge_type, c.contact_LF, c.edge_total_LF) for c in deduped_edge_contribs]
    # Ridge vents adjust the CAPS on their own ridge (aluminum) or ride alongside them (shingle-over).
    # With no ridge marked, this is bit-for-bit the old single expand_scope call.
    edge_scope_lines = _edge_lines_with_ridge_vents(deduped_edge_contribs,
                                                    _ridge_vents(confirmed_selection))
    # v71 DEFECT 3: eave ICE & WATER at the ROOF level, from the DEDUPED eave contributions (the same
    # authority that bills STARTER, so it can never disagree and never double-counts). Fires only when
    # the user asserted code and/or existing AND there is exposed eave. Reuses the IWS id (registry
    # stays 29) so it folds into the IWS comparison total — exactly the Devore 537.16-vs-119.85 gap.
    eave_iws_lines: List[ScopeLine] = []
    eave_iws_meta = None
    if _eave_iws_basis:
        _eave_lf = round(sum(c.contact_LF for c in deduped_edge_contribs
                             if c.edge_type == "EAVE" and c.contact_LF > 0), 2)
        if _eave_lf > 0:
            _cov, _layers, _defaulted = eave_iws_coverage(_eave_lf, _soffit_depth)
            eave_iws_lines.append(ScopeLine("Ice & water barrier (eaves)", "IWS", _cov, "SF",
                                            "CONFIRM", _eave_iws_citation(_eave_iws_basis)))
            eave_iws_meta = {
                "eave_LF": _eave_lf, "coverage_SF": _cov, "layers": _layers,
                "code": bool(_eave_iws_basis.get("code")),
                "existing": bool(_eave_iws_basis.get("existing")),
                "soffit_depth_in": (None if _defaulted else float(_soffit_depth)),
                "citation": _eave_iws_citation(_eave_iws_basis),
            }
    aggregated = _aggregate_lines([*non_edge_lines, *edge_scope_lines, *transition_scope_lines, *eave_iws_lines])
    aggregated_by_structure = _aggregate_by_structure(geom, components, confirmed_selection, active_transitions)
    _facet_counts: MutableMapping[str, int] = {}
    for _f in geom.roof_faces.values():
        _facet_counts[(getattr(_f, "structure_id", "") or "")] = _facet_counts.get((getattr(_f, "structure_id", "") or ""), 0) + 1
    structure_facet_counts = tuple(sorted(_facet_counts.items(), key=lambda kv: _struct_sort_key(kv[0])))
    raw_total = sum(comp.iface.affected_SF for comp in components)
    display_total = round(sum(round(comp.iface.affected_SF, 1) for comp in components), 1)
    _repl = tuple(c.label for c in components if c.component_type == "replacement")
    _rep = tuple(c.label for c in components if c.component_type in ("single_valley", "multi_valley"))
    # v69: per-structure exposure for the report's §2 dual and slope callouts. Purely additive — summed
    # from the SAME components already built; no scope number changes. Grouped by the structure each
    # facet belongs to (_structure_of_face), ordered by the ROOF id's trailing integer.
    _aff_by_struct: MutableMapping[str, float] = {}
    _repl_by_struct: MutableMapping[str, List[str]] = {}
    _rep_by_struct: MutableMapping[str, List[str]] = {}
    for c in components:
        sid = _structure_of_face(geom, c.face_id)
        _aff_by_struct[sid] = _aff_by_struct.get(sid, 0.0) + float(c.iface.affected_SF)
        if c.component_type == "replacement":
            _repl_by_struct.setdefault(sid, []).append(c.label)
        elif c.component_type in ("single_valley", "multi_valley"):
            _rep_by_struct.setdefault(sid, []).append(c.label)
    structure_affected_SF = tuple(sorted(_aff_by_struct.items(), key=lambda kv: _struct_sort_key(kv[0])))
    replacement_facets_by_structure = tuple((sid, tuple(v)) for sid, v in sorted(_repl_by_struct.items(), key=lambda kv: _struct_sort_key(kv[0])))
    repair_facets_by_structure = tuple((sid, tuple(v)) for sid, v in sorted(_rep_by_struct.items(), key=lambda kv: _struct_sort_key(kv[0])))
    # v63 DEFECT 3: the valley-LF total the header reports must be the SAME authority that bills the
    # metal. VALLEY_METAL is billed from valley_LF_in_scope, which a replaced facet claims for every
    # valley on it; the user-selected LF (selected_valley_lf) ignores replacement, so a full
    # replacement showed 0.00 in the page-2 header while the report billed 39.95. Report the billed
    # VALLEY_METAL quantity instead — identical to the selected LF on a repair-only roof (anchor: both
    # 134.03), correct on a replacement, and it can never disagree with the report line it comes from.
    _valley_lf_billed = round(float(sum(l.qty for l in aggregated if l.category_id == "VALLEY_METAL")), 2)
    return RoofAssemblyResult(
        components=tuple(components),
        aggregated_scope=tuple(aggregated),
        affected_SF_raw_total=float(raw_total),
        affected_SF_display_total=float(display_total),
        selected_valley_LF_total=_valley_lf_billed,
        derivation_breakdown=tuple(breakdown),
        deduped_edges=tuple(deduped_edge_contribs),
        edge_scope_lines=edge_scope_lines,
        replacement_facets=_repl,
        repair_facets=_rep,
        aggregated_scope_by_structure=aggregated_by_structure,
        structure_facet_counts=structure_facet_counts,
        structure_affected_SF=structure_affected_SF,
        replacement_facets_by_structure=replacement_facets_by_structure,
        repair_facets_by_structure=repair_facets_by_structure,
        eave_iws=eave_iws_meta,
    )


def _component(row: Mapping[str, object], face_id: str, component_type: str, geometry_status: str, surface_status: str, reason: str, iface: M1Interface, edge_contribs: Sequence[EdgeContribution]) -> ComponentAssembly:
    lines = tuple(expand_scope(iface, repair_factor=1.0))
    # The steep line leaves expand_scope with no tier on it, so three tiers would merge into one.
    # Stamp the component's own tier here — the single place every component's lines are produced.
    lines = _stamp_steep_tier(lines, iface.facet_pitch_tier)
    return ComponentAssembly(
        label=str(row.get("label", face_id)),
        face_id=face_id,
        component_type=component_type,
        geometry_status=geometry_status,
        surface_status=surface_status,
        reason=reason,
        iface=iface,
        scope_lines=lines,
        edge_contributions=tuple(edge_contribs),
    )


def _breakdown(component: ComponentAssembly) -> Mapping[str, str]:
    return {
        "component": component.label,
        "geometry_status": component.geometry_status,
        "surface_status": component.surface_status,
        "reason": component.reason,
    }


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

def _confirmed_appurtenance_geometries_for_face(geom: EagleViewGeometry, confirmed_selection: Mapping[str, object], face_id: str):
    """Appurtenance rectangles already confirmed on this facet. Used ONLY to cancel overlap when
    measuring a transition band's incremental area, so nothing is ever counted twice."""
    out = []
    for item in confirmed_selection.get("penetration_appurtenance_repairs", ()) or ():
        row = _as_mapping(item)
        # A NON-CARVING appurtenance (cover-only power vent) disturbs nothing, so it must not cancel
        # any of a transition band's incremental area. Overlap is only subtracted for area that is
        # genuinely already counted elsewhere; a cover-only vent counts none. Same single authority
        # as the carve itself — if it does not carve, it does not cancel.
        if not appurtenance_carves(row):
            continue
        pen_id = str(row.get("penetration_face_id") or row.get("penetration_id") or "")
        if not pen_id:
            continue
        try:
            host = _host_face_for_penetration(geom, pen_id)
        except Exception:
            continue
        if str(host) != str(face_id):
            continue
        try:
            candidate = _penetration_candidate_from_geom(geom, host, pen_id)
            out.append(dict(candidate.params["appurtenance_geometry"]))
        except Exception:
            continue
    for row in _user_footprints_for_face(confirmed_selection, face_id) or ():
        if isinstance(row, dict) and {"cx", "cy", "w", "h"} <= set(row):
            out.append(dict(row))
    return out


# ================================ RIDGE VENTS ================================
# A RIDGE VENT IS NOT A REPAIR EVENT. Marking a ridge vented creates NO affected area, NO carve, NO
# shading and NO new repair event. It changes NOTHING about EA, SF, the shake count or the diagram's
# affected zones. It is a MATERIAL ITEM on a ridge run that is ALREADY IN SCOPE: ridge caps only bill
# where the affected area from the user's EXISTING repairs contacts the ridge (contact_LF > 0), and a
# vent only changes WHAT MATERIAL goes on that already-contacted run.
#
# THE TWO TYPES BEHAVE DIFFERENTLY (Joseph — binding):
#   SHINGLE-OVER = an ACCESSORY. The cap shakes lay OVER the vent, so the ridge STILL GETS ITS FULL
#                  CAPS. It ADDS a line and takes nothing away:   RIDGE_VENT = V, RIDGE_CAPS = C.
#   ALUMINUM     = a SUBSTITUTION. It is self-capping, so it REPLACES the caps on its own run:
#                                                                 RIDGE_VENT = V, RIDGE_CAPS = C - V.
# Modelling shingle-over as a substitution would silently DELETE caps the job actually needs.
#
# THE VENTED LF IS A USER INPUT. A vent may cover only part of a ridge, and we do not know WHERE on
# the ridge it sits, so V is defined as "the vent LF being replaced WITHIN THIS REPAIR". That
# sidesteps the positional problem and puts the judgement with the person looking at the roof.
VENT_SHINGLE_OVER = "SHINGLE_OVER"
VENT_ALUMINUM = "ALUMINUM"


def _ridge_vents(confirmed_selection: Mapping[str, object]) -> dict:
    """{edge_id: {"vent_type": ..., "vented_LF": float}} for ridges the user marked vented."""
    out: dict = {}
    for row in (confirmed_selection.get("ridge_vents", ()) or ()):
        if not isinstance(row, Mapping):
            continue
        edge_id = row.get("edge_id")
        vent_type = str(row.get("vent_type") or "").upper()
        try:
            vented = float(row.get("vented_LF") or 0.0)
        except (TypeError, ValueError):
            vented = 0.0
        if not edge_id or vent_type not in (VENT_SHINGLE_OVER, VENT_ALUMINUM) or vented <= 0:
            continue                       # never guess: an incomplete assertion creates nothing
        out[str(edge_id)] = {"vent_type": vent_type, "vented_LF": vented}
    return out


def _edge_lines_with_ridge_vents(contribs, ridge_vents: Mapping[str, Mapping[str, object]]):
    """Edge-driven scope lines, with any user-marked ridge vent applied.

    Expanded PER EDGE (the expander's edge loop already treats every edge independently, so this is
    identical to expanding them together) — which is what lets the caps be adjusted for ONE ridge
    without touching module2_scope_expansion.py at all. Same trick as v51's steep tier.
    """
    out = []
    for contrib in contribs:
        edge = Edge(contrib.edge_type, contrib.contact_LF, contrib.edge_total_LF)
        lines = list(expand_scope(M1Interface(edges=[edge]), repair_factor=1.0))
        vent = ridge_vents.get(str(contrib.line_id)) if contrib.edge_type == "RIDGE" else None
        if not vent:
            out.extend(lines)
            continue

        # C = the CONTACTED cap run the engine already computed for THIS ridge.
        cap_line = next((l for l in lines if l.category_id == "RIDGE_CAPS"), None)
        contacted_caps = float(cap_line.qty) if cap_line else 0.0
        if contacted_caps <= 0:
            # No contact -> no caps -> this ridge is not in the repair at all, so it cannot be vented.
            out.extend(lines)
            continue

        # You cannot replace more vent than the ridge you are actually working on.
        vented = min(float(vent["vented_LF"]), contacted_caps)

        for line in lines:
            if line.category_id != "RIDGE_CAPS":
                out.append(line)
                continue
            if vent["vent_type"] == VENT_ALUMINUM:
                remaining = round(max(0.0, contacted_caps - vented), 2)
                if remaining > 0:
                    out.append(replace(line, qty=remaining))
                # V >= C -> the vent covers the whole contacted run: NO caps, and NO zero-qty line.
            else:
                out.append(line)          # SHINGLE-OVER: the caps lay over the vent — unchanged

        label = "Ridge vent (aluminum)" if vent["vent_type"] == VENT_ALUMINUM else "Ridge vent (shingle-over)"
        out.append(ScopeLine(label, "RIDGE_VENT", round(vented, 2), "LF", "CONFIRM",
                             "ventilation; mfr ridge vent"))
    return tuple(out)


# ============================ STEEP & HIGH-SLOPE (labor modifiers) ============================
# BOTH charges were DEAD CODE. module2_scope_expansion could emit them all along, but:
#   * facet_pitch_tier was NEVER computed -> STEEP CHARGE HAS NEVER FIRED, on a roof that is mostly
#     13/12-18/12. Yager has been silently under-scoped.
#   * high_slope_user_flag had NO UI -> HIGH-SLOPE CHARGE HAS NEVER FIRED.
#
# STEEP is pitch: derivable from the XML alone, so it is AUTO — the user confirms nothing.
# HIGH-SLOPE is a HEIGHT charge ("high roof, 2 story" — parser spec §category table). EagleView gives
# roof geometry, NOT wall heights or storey counts; it cannot be derived. It is a per-facet USER
# assertion, and page 2 now forces an explicit decision rather than letting it default to nothing.
STEEP_TIER_79 = "7-9"
STEEP_TIER_1012 = "10-12"
STEEP_TIER_GT12 = ">12"


def _steep_tier_for_pitch(pitch) -> Optional[str]:
    """The steep tier a facet's pitch falls in — read from the geometry, never re-measured.
    Below 7/12 there is no steep charge at all."""
    try:
        p = float(pitch)
    except (TypeError, ValueError):
        return None
    if p >= 13:
        return STEEP_TIER_GT12
    if p >= 10:
        return STEEP_TIER_1012
    if p >= 7:
        return STEEP_TIER_79
    return None


def _facet_pitch_tier(geom: EagleViewGeometry, face_id: str) -> Optional[str]:
    face = geom.faces.get(str(face_id))
    return _steep_tier_for_pitch(getattr(face, "pitch", None)) if face else None


def _high_slope_faces(confirmed_selection: Mapping[str, object]) -> set:
    """Facets the USER asserted are high (2-story). Only the user can know the storey count."""
    out = set()
    for item in (confirmed_selection.get("high_slope_facets", ()) or ()):
        if isinstance(item, Mapping):
            fid = item.get("face_id")
            if fid and item.get("high") is not False:
                out.add(str(fid))
        elif item:
            out.add(str(item))
    return out


def _stamp_steep_tier(lines, tier: Optional[str]):
    """Carry the TIER on the steep line itself, so the three tiers become three lines — exactly as
    carriers write them (spec fixture: STEEP_CHARGE SQ 6.45 (7-9), 55.27 (10-12), 1.40 (>12)).

    Done HERE rather than in module2_scope_expansion so that file stays BYTE-IDENTICAL: the tier is
    stamped onto the existing `xact_code` discriminator, which _aggregate_lines already keys on
    (the v48 chimney-size precedent). Same-tier components therefore MERGE; different tiers SPLIT.
    """
    if not tier:
        return lines
    out = []
    for line in lines:
        if line.category_id == "STEEP_CHARGE":
            out.append(replace(line, item=f"Steep charge ({tier})", xact_code=f"STEEP_{tier}"))
        else:
            out.append(line)
    return tuple(out)


def _transition_bands_for(confirmed_selection: Mapping[str, object], face_id: str):
    """Bands a user-confirmed transition carves on this facet. Empty when none is selected, so
    every existing call is bit-for-bit unchanged. Passing them INTO the same affected_area call as
    the valley events is what makes the zones UNION rather than sum."""
    cache = confirmed_selection.get("_transition_bands_by_face") if isinstance(confirmed_selection, dict) else None
    if not cache:
        return []
    return engine_bands(cache.get(face_id) or [])


def _encoding_b_candidate(geom: EagleViewGeometry, face_id: str) -> Optional[Candidate]:
    """The Encoding-B reframing candidate for a face with a self-bounding HIDDEN line, or None.

    Built on demand via the emitter's single authority. It is NOT one of the page-2 selectable notch
    candidates (those are Encoding A, two-face merges); it exists only to reframe this face's own valley
    sweep so the slit stops acting as a barrier. Yager has no self-bounding hidden line, so this is None
    for every Yager face — the anchor can never take the reframing branch."""
    return _emit_encoding_b_candidate(geom, str(face_id))


def _encoding_b_reframed_area(geom: EagleViewGeometry, b_cand: Candidate, valley_ids: Sequence[str], confirmed_selection: Mapping[str, object], shake_measurements) -> float:
    """Reframed affected area for an Encoding-B face's valleys, through the SAME ridge-anchored notch
    machinery Encoding A uses (one authority). Only the AREA is taken from the notch builder; the
    component's interface (pitch tier, edges, transitions) is still built by the plain path, so nothing
    face-level is lost. A throwaway `claimed` set and empty selected_valley_ids mean this call never
    claims valley LF — that is claimed once on the plain path."""
    iface, _edge_contribs = _build_m1_interface_for_notch(
        geom, b_cand, [], set(), "encoding_b_area",
        confirmed_selection=confirmed_selection, override_valley_ids=list(valley_ids),
        shake_measurements=shake_measurements)
    return float(iface.affected_SF)


def _single_valley_area(geom: EagleViewGeometry, face_id: str, valley_id: str, confirmed_selection: Mapping[str, object]) -> float:
    shake_measurements = _shake_measurements_from_selection(confirmed_selection)
    b_cand = _encoding_b_candidate(geom, face_id)
    if b_cand is not None and not _transition_bands_for(confirmed_selection, face_id):
        # ENCODING B (v65): self-bounding HIDDEN line (slit around a lobe). Reframe the valley sweep so
        # the slit stops barriering the lobe-side zones. A face with a user-confirmed transition keeps
        # the plain path (its band is unioned in the face's own frame there, and the slit barely moves
        # the sweep on such a face).
        return _encoding_b_reframed_area(geom, b_cand, [valley_id], confirmed_selection, shake_measurements)
    engine_face = geom.engine_facet(face_id)
    valley_event = geom.valley_event_for_face(face_id, valley_id)
    _per_event, area = affected_area(engine_face.facet, [valley_event], penetrations=_penetrations_with_user_footprints(geom, confirmed_selection, face_id), shake_measurements=shake_measurements, transition_bands=_transition_bands_for(confirmed_selection, face_id))
    return float(area)


def _multi_valley_union_area(geom: EagleViewGeometry, face_id: str, valley_ids: Sequence[str], confirmed_selection: Mapping[str, object], include_child_penetrations: bool = True) -> float:
    shake_measurements = _shake_measurements_from_selection(confirmed_selection)
    b_cand = _encoding_b_candidate(geom, face_id)
    if b_cand is not None and not _transition_bands_for(confirmed_selection, face_id):
        return _encoding_b_reframed_area(geom, b_cand, list(valley_ids), confirmed_selection, shake_measurements)
    engine_face = geom.engine_facet(face_id)
    valley_events = [geom.valley_event_for_face(face_id, valley_id) for valley_id in valley_ids]
    # uniform clipped exclusion: dimensional XML penetrations plus confirmed user dimensioned footprint holes
    _per_event, area = affected_area(engine_face.facet, valley_events, penetrations=_penetrations_with_user_footprints(geom, confirmed_selection, face_id), shake_measurements=shake_measurements, transition_bands=_transition_bands_for(confirmed_selection, face_id))
    return float(area)


def _notch_reframe_geometry(geom: EagleViewGeometry, candidate: Candidate, confirmed_selection: Mapping[str, object] | None, override_valley_ids=None):
    """The merged-facet reframing geometry for a notch/Encoding-B candidate: the ridge-anchored frame,
    the merged facet, the lobe notches, the reframed valley events, and the dimensional penetrations.
    ONE authority — `_build_m1_interface_for_notch` (which the SCOPE bills) and `encoding_b_zone` (which
    the DIAGRAM draws) both build their geometry here, so the picture can never disagree with the math."""
    anchor_line = geom.lines[str(candidate.params["anchor_line_id"])]
    frame_ids = tuple(str(pid) for pid in candidate.params["frame_point_ids"])
    frame = mkframe_pts(
        [geom.points[pid] for pid in frame_ids],
        geom.points[anchor_line.path[0]],
        geom.points[anchor_line.path[-1]],
    )
    facet = [tuple(float(v) for v in frame(geom.points[str(pid)])) for pid in candidate.params["merged_facet_point_ids"]]
    notches = [
        [tuple(float(v) for v in frame(geom.points[str(pid)])) for pid in notch_ids]
        for notch_ids in candidate.params["notch_polygon_point_ids"]
    ]
    valley_ids = tuple(str(v) for v in (override_valley_ids if override_valley_ids else candidate.params["bordering_valley_line_ids"]))
    valley_events = [_valley_event_for_notch(geom, candidate, frame, facet, valley_id) for valley_id in valley_ids]
    _notch_pens = []
    for _mfid in candidate.params["member_face_ids"]:
        for _pf in geom.penetration_faces.values():
            if getattr(_pf, "size", 0) > 0 and _host_face_for_penetration(geom, _pf.id) == str(_mfid):
                _poly = []
                for _lid in _pf.line_ids:
                    for _pid in geom.lines[_lid].path:
                        if _pid not in _poly: _poly.append(_pid)
                _notch_pens.append([tuple(float(v) for v in frame(geom.points[str(_pid)])) for _pid in _poly])
    _notch_pens.extend(_user_footprints_for_merged_members(geom, confirmed_selection or {}, candidate.params["member_face_ids"], frame))
    return frame, facet, notches, valley_ids, valley_events, _dimensional_pens(_notch_pens)


def encoding_b_zone(geom: EagleViewGeometry, face_id: str, valley_ids, confirmed_selection: Mapping[str, object] | None = None, shake_measurements=None):
    """Reframed ZONE for an Encoding-B face, from the SAME authority the scope bills. Returns
    (affected_SF, zone_mask, gx, gy, merged_facet) so the diagram can draw exactly what the scope
    counted. Returns None when the face is not Encoding-B (no self-bounding hidden line). Do NOT
    reimplement the reframing anywhere else — call this."""
    b_cand = _encoding_b_candidate(geom, str(face_id))
    if b_cand is None or _transition_bands_for(confirmed_selection or {}, str(face_id)):
        # Not Encoding-B, or a face carrying a transition (which the SCOPE keeps on the plain path) —
        # the same gate _single_valley_area/_multi_valley_union_area use, so the diagram never reframes
        # a facet the scope did not.
        return None
    vids = [str(v) for v in valley_ids] if valley_ids else None
    _frame, facet, notches, _vidt, valley_events, pens = _notch_reframe_geometry(geom, b_cand, confirmed_selection, override_valley_ids=vids)
    _per, affected, zone, gx, gy = affected_area(facet, valley_events, notches=notches, penetrations=pens, shake_measurements=shake_measurements, return_zone=True)
    return float(affected), zone, gx, gy, facet


def _build_m1_interface_for_notch(geom: EagleViewGeometry, candidate: Candidate, selected_valley_ids: Sequence[str], claimed: set[str], label: str, confirmed_selection: Mapping[str, object] | None = None, override_valley_ids=None, shake_measurements=None) -> Tuple[M1Interface, Tuple[EdgeContribution, ...]]:
    frame, facet, notches, valley_ids, valley_events, pens = _notch_reframe_geometry(geom, candidate, confirmed_selection, override_valley_ids=override_valley_ids)
    _per_event, affected = affected_area(facet, valley_events, notches=notches, penetrations=pens, shake_measurements=shake_measurements)
    edge_tuples_with_ids = _notch_outer_edge_tuples_with_ids(geom, candidate, frame)
    edge_tuples = [(a, b, edge_type, total_lf) for _line_id, a, b, edge_type, total_lf in edge_tuples_with_ids]
    edges, edge_contribs = _surface_physical_edges(facet, valley_events, edge_tuples_with_ids, label, shake_measurements)
    valley_lf = sum(_claim_valley_lf_once(geom, valley_id, selected_valley_ids, claimed) for valley_id in valley_ids)
    return M1Interface(affected_SF=float(affected), valley_LF_in_scope=float(valley_lf), edges=edges, appurts=[], transitions=[], shake_width_in=float((shake_measurements or {}).get("width_in", 7.0)), exposure_in=float((shake_measurements or {}).get("exposure_in", 10.0))), tuple(edge_contribs)


def _notch_outer_edge_tuples_with_ids(geom: EagleViewGeometry, candidate: Candidate, frame) -> List[Tuple[str, Tuple[float, float], Tuple[float, float], str, float]]:
    line_by_edge = {_edge_key(line.path[0], line.path[-1]): (line_id, line) for line_id, line in geom.lines.items()}
    ids = tuple(str(pid) for pid in candidate.params["merged_facet_point_ids"])
    out = []
    for a_id, b_id in zip(ids, list(ids[1:]) + [ids[0]]):
        line_id, line = line_by_edge[_edge_key(a_id, b_id)]
        out.append((
            line_id,
            tuple(float(v) for v in frame(geom.points[a_id])),
            tuple(float(v) for v in frame(geom.points[b_id])),
            line.type,
            _length_3d([geom.points[p] for p in line.path]),
        ))
    return out


def _valley_event_for_notch(geom: EagleViewGeometry, candidate: Candidate, frame, facet, line_id: str):
    line = geom.lines[line_id]
    a_id, b_id = line.path[0], line.path[-1]
    apex_id, start_id = (a_id, b_id) if geom.points[a_id][2] >= geom.points[b_id][2] else (b_id, a_id)
    start = np.array(frame(geom.points[start_id]), dtype=float)
    apex = np.array(frame(geom.points[apex_id]), dtype=float)
    fan = _notch_valley_fan(geom, candidate, frame, facet, line_id)
    return (tuple(float(v) for v in start), tuple(float(v) for v in apex), int(fan))


def _notch_valley_fan(geom: EagleViewGeometry, candidate: Candidate, frame, facet, line_id: str) -> int:
    from geometry_core import excluded_region_aware_notch_fan
    line = geom.lines[line_id]
    seg_a = tuple(float(v) for v in frame(geom.points[line.path[0]])[:2])
    seg_b = tuple(float(v) for v in frame(geom.points[line.path[-1]])[:2])
    holes = [[tuple(float(v) for v in frame(geom.points[pid])[:2]) for pid in poly]
             for poly in candidate.params["notch_polygon_point_ids"]]
    return excluded_region_aware_notch_fan(facet, holes, seg_a, seg_b)


def _face_edge_contributions(geom: EagleViewGeometry, face_id: str, valley_ids: Sequence[str], label: str, shake_measurements=None) -> Tuple[EdgeContribution, ...]:
    engine_face = geom.engine_facet(face_id)
    valley_events = [geom.valley_event_for_face(face_id, valley_id) for valley_id in valley_ids]
    tuples_with_ids = []
    for line_id, edge in zip(geom.faces[face_id].line_ids, engine_face.edges):
        a, b, edge_type, total_lf = edge
        tuples_with_ids.append((line_id, a, b, edge_type, total_lf))
    _edges, contribs = _surface_physical_edges(engine_face.facet, valley_events, tuples_with_ids, label, shake_measurements)
    return tuple(contribs)


def _surface_physical_edges(facet, valley_events, edge_tuples_with_ids, label: str, shake_measurements=None) -> Tuple[List[Edge], List[EdgeContribution]]:
    edges: List[Edge] = []
    contribs: List[EdgeContribution] = []
    for line_id, a, b, edge_type, total_lf in edge_tuples_with_ids:
        if edge_type == "VALLEY":
            continue
        single_edge = [(a, b, edge_type, total_lf)]
        contacts = edge_contacts(facet, valley_events, single_edge, res=0.04, shake_measurements=shake_measurements) if valley_events else {}
        contact_lf = float(contacts.get(edge_type, (0.0, total_lf))[0])
        total = float(contacts.get(edge_type, (contact_lf, total_lf))[1])
        edges.append(Edge(edge_type, contact_lf, total))
        contribs.append(EdgeContribution(str(line_id), str(edge_type), contact_lf, total, label))
    return edges, contribs


def _facet_valley_ids(geom: EagleViewGeometry, face_id: str) -> Tuple[str, ...]:
    """Every VALLEY line bordering this facet (line ids) — for full-slope replacement."""
    return tuple(lid for lid in geom.faces[face_id].line_ids
                 if lid in geom.lines and geom.lines[lid].type.upper() == "VALLEY")


def _claim_replacement_valley_lf(geom: EagleViewGeometry, valley_id: str, claimed: set) -> float:
    """The WHOLE valley on a replaced facet's perimeter is in scope (you cannot replace half a
    W-metal), independent of the user's selected_valley_ids — but claimed ONCE, deduped against any
    adjoining facet (repair or replacement) that also claims it, exactly like _claim_valley_lf_once."""
    if valley_id in claimed or valley_id not in geom.valley_lengths:
        return 0.0
    claimed.add(valley_id)
    return float(geom.valley_lengths[valley_id])


def _replacement_facet_area(geom: EagleViewGeometry, face_id: str) -> float:
    """Whole facet, net of penetrations >= 0.5 SF. The facet's surface area is EagleView's own
    unrounded_size (equal to the facet polygon area); penetrations are the same holes every carved
    zone excludes, subtracted here so a stripped slope is NET area — consistent with every other zone
    and with the roof-area convention the diagram uses. NO waste factor is added (rule 8)."""
    face = geom.roof_faces[face_id]
    gross = float(face.unrounded_size if face.unrounded_size is not None else (face.size or 0.0))
    engine_face = geom.engine_facet(face_id)

    def _poly_area(q):
        n = len(q)
        return abs(sum(q[i][0] * q[(i + 1) % n][1] - q[(i + 1) % n][0] * q[i][1] for i in range(n))) / 2.0

    pen = sum(_poly_area(p) for p in engine_face.penetrations if _poly_area(p) >= 0.5)
    return max(gross - pen, 0.0)


def _replacement_edge_contributions(geom: EagleViewGeometry, face_id: str, label: str) -> Tuple[EdgeContribution, ...]:
    """A stripped facet contacts its WHOLE perimeter, so every non-valley edge bills at 100% contact
    through the SAME edge machinery (ridge/hip/starter/step/drip + the §6 95% run + shared-run
    dedupe). Valley edges are excluded here — VALLEY_METAL/IWS bill from valley_LF_in_scope, never
    from edge contact. This writes no new perimeter rule; it feeds the existing one the physical
    truth for a full replacement (100% contact)."""
    engine_face = geom.engine_facet(face_id)
    contribs: List[EdgeContribution] = []
    for line_id, edge in zip(geom.faces[face_id].line_ids, engine_face.edges):
        _a, _b, edge_type, total_lf = edge
        if str(edge_type).upper() == "VALLEY":
            continue
        contribs.append(EdgeContribution(str(line_id), str(edge_type), float(total_lf), float(total_lf), label))
    return tuple(contribs)


def _dedupe_edge_contributions(contribs: Sequence[EdgeContribution]) -> Tuple[EdgeContribution, ...]:
    by_line: Dict[str, EdgeContribution] = {}
    for contrib in contribs:
        prior = by_line.get(contrib.line_id)
        if prior is None:
            by_line[contrib.line_id] = contrib
            continue
        by_line[contrib.line_id] = EdgeContribution(
            line_id=contrib.line_id,
            edge_type=prior.edge_type,
            contact_LF=max(prior.contact_LF, contrib.contact_LF),
            edge_total_LF=max(prior.edge_total_LF, contrib.edge_total_LF),
            component=";".join(sorted(set(prior.component.split(";") + contrib.component.split(";")))),
        )
    return tuple(sorted(by_line.values(), key=lambda c: _id_sort_key(c.line_id)))



def _appurtenance_union_affected_area(geom, host_face_id, candidate, confirmed_selection, carves, replaced_ids, repair_facet_ids):
    """The appurtenance's affected AREA under the union-not-sum rule (v56 transitions, v62 replacement).

    A cover that does not carve contributes 0. On a REPLACED facet the whole facet is already 100%
    scoped, so the footprint is UNIONED in and adds NO area (0) and NO shakes — exactly like a
    transition band unioned into a valley zone. Crucially this zeros only `iface.affected_SF` (the
    shake/felt driver); the Appurt's OWN affected_SF (built from the candidate) still drives APPURT_IWS
    and the material line, so a box vent on a stripped slope still bills its vent and its deck-level
    IWS. On a repair facet only the increment beyond the repair zone counts; otherwise the full
    footprint counts."""
    if not carves:
        return 0.0
    if host_face_id in replaced_ids:
        return 0.0
    if host_face_id in repair_facet_ids:
        return _appurtenance_net_affected_area(geom, host_face_id, candidate, confirmed_selection)[0]
    return _appurtenance_affected_area(geom, host_face_id, candidate, confirmed_selection)[0]


def _appurtenance_net_affected_area(geom: EagleViewGeometry, host_face_id: str, candidate: Candidate, confirmed_selection: Mapping[str, object]):
    shake_measurements = _shake_measurements_from_selection(confirmed_selection)
    merged_candidate = _merged_candidate_for_member_face(geom, host_face_id)
    if merged_candidate is not None:
        return _merged_appurtenance_net_affected_area(geom, merged_candidate, candidate, confirmed_selection)

    engine_face = geom.engine_facet(host_face_id)
    repair_events = []
    for item in confirmed_selection.get("single_valley_repairs", ()):
        row = _as_mapping(item)
        if str(row["face_id"]) == host_face_id:
            repair_events.append(geom.valley_event_for_face(host_face_id, str(row["valley_id"])))
    for item in confirmed_selection.get("multi_valley_facets", ()):
        row = _as_mapping(item)
        if str(row["face_id"]) == host_face_id:
            repair_events.extend(geom.valley_event_for_face(host_face_id, str(v)) for v in row.get("valley_ids", ()))

    _per_app, _app_area, app_zone, gx, gy = affected_area(
        engine_face.facet,
        [],
        appurtenances=[dict(candidate.params["appurtenance_geometry"])],
        penetrations=_penetrations_with_user_footprints(geom, confirmed_selection, host_face_id),
        return_zone=True,
        shake_measurements=shake_measurements,
    )
    if not repair_events:
        return float(_app_area), app_zone, gx, gy, host_face_id
    _per_repair, _repair_area, repair_zone, _gx, _gy = affected_area(
        engine_face.facet,
        repair_events,
        penetrations=_penetrations_with_user_footprints(geom, confirmed_selection, host_face_id),
        return_zone=True,
        shake_measurements=shake_measurements,
    )
    cell = float((gx[1] - gx[0]) * (gy[1] - gy[0]))
    net_zone = (np.asarray(app_zone, bool) & ~np.asarray(repair_zone, bool))
    net_zone = _filter_subshake_components(net_zone, gx, gy)
    return float(net_zone.sum() * cell), net_zone, gx, gy, host_face_id


def _merged_appurtenance_net_affected_area(geom: EagleViewGeometry, notch_candidate: Candidate, appurtenance_candidate: Candidate, confirmed_selection: Mapping[str, object]):
    shake_measurements = _shake_measurements_from_selection(confirmed_selection)
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
        facet, [], notches=notches, appurtenances=[app], penetrations=holes, return_zone=True,
        shake_measurements=shake_measurements
    )

    member_set = {str(v) for v in notch_candidate.params.get("member_face_ids", ())}
    repair_masks = []
    for item in confirmed_selection.get("notch_repairs", ()):
        row = _as_mapping(item)
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
    shake_measurements = _shake_measurements_from_selection(confirmed_selection or {})
    merged_candidate = _merged_candidate_for_member_face(geom, host_face_id)
    if merged_candidate is not None:
        return _merged_appurtenance_affected_area(geom, merged_candidate, candidate, confirmed_selection or {})

    engine_face = geom.engine_facet(host_face_id)
    _per_event, area, zone, gx, gy = affected_area(
        engine_face.facet,
        [],
        appurtenances=[dict(candidate.params["appurtenance_geometry"])],
        penetrations=_penetrations_with_user_footprints(geom, confirmed_selection or {}, host_face_id),
        return_zone=True,
        shake_measurements=shake_measurements,
    )
    return float(area), zone, gx, gy, host_face_id


def _merged_candidate_for_member_face(geom: EagleViewGeometry, face_id: str) -> Candidate | None:
    for candidate in emit_notch_candidates(geom):
        if str(face_id) in {str(v) for v in candidate.params.get("member_face_ids", ())}:
            return candidate
    return None


def _merged_appurtenance_affected_area(geom: EagleViewGeometry, notch_candidate: Candidate, appurtenance_candidate: Candidate, confirmed_selection: Mapping[str, object] | None = None):
    shake_measurements = _shake_measurements_from_selection(confirmed_selection or {})
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
    pens.extend(_user_footprints_for_merged_members(geom, confirmed_selection or {}, notch_candidate.params["member_face_ids"], frame))
    app = _candidate_appurtenance_geometry_in_frame(geom, appurtenance_candidate, frame)
    _per_event, area, zone, gx, gy = affected_area(
        facet,
        [],
        notches=notches,
        appurtenances=[app],
        penetrations=_dimensional_pens(pens),
        return_zone=True,
        shake_measurements=shake_measurements,
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
        row = _as_mapping(item)
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
        row = _as_mapping(item)
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


def _with_appurtenance_label(candidate: Candidate, kind_label: str, group: Optional[str], contacted=None, size_class=None, carves: bool = True, other_label=None, other_category=None) -> Mapping[str, object]:
    params = dict(candidate.params)
    params["kind_label"] = kind_label
    if group is not None:
        params["group"] = group
    if contacted is not None:
        params["contacted"] = bool(contacted)
    if size_class not in (None, ""):
        params["size_class"] = str(size_class)
    # v71 DEFECT 2: a user-defined appurtenance (kind_label=OTHER) names itself with other_label; carry
    # it (and any explicit other_category) into the params module1_m2interface._surface_appurts reads,
    # so the engine bills the user's own words instead of the generic 'User-defined appurtenance'.
    if other_label not in (None, ""):
        params["other_label"] = str(other_label)
    if other_category not in (None, ""):
        params["other_category"] = str(other_category)
    if not carves:
        # A NON-CARVING appurtenance (today: a cover-only power attic vent) has NO disturbance
        # footprint at all, so it is handed to Module 2 with no appurtenance_geometry.
        # module1_m2interface._surface_appurts derives Appurt.affected_SF from exactly this key, so
        # dropping it yields affected_SF == 0 and APPURT_IWS — which fires only on affected_SF > 0 —
        # never triggers. THAT IS THE WHOLE MECHANISM: the geometry is absent because there is no
        # disturbance, and the ice & water falls out of the zero. No IWS special case exists, and
        # none may be added. module1_m2interface stays byte-identical.
        params.pop("appurtenance_geometry", None)
    return {"kind": candidate.kind, "source_ids": candidate.source_ids, "origin": candidate.origin, "confirmed": candidate.confirmed, "params": params}


# RFG FLCH< / RFG FLCH / RFG FLCH> are THREE DIFFERENT XACTIMATE LINE ITEMS AT THREE DIFFERENT PRICES.
# They cannot be billed as one line of qty 3. Derived here (from the code) so that
# module2_scope_expansion.py — which already stamps the code correctly — stays BYTE-IDENTICAL.
_XACT_SIZE_LABEL = {
    "RFG FLCH<": "Chimney flashing — Small (24x24)",
    "RFG FLCH":  "Chimney flashing — Average (32x36)",
    "RFG FLCH>": "Chimney flashing — Large (60x24)",
}


# Module-level copy of the appurtenance-material categories, so per-structure aggregation dedupes one
# physical object exactly the way the global loop does. Kept in sync with the local set in the assembly.
_APPURT_MATERIAL_CATEGORIES = {"CHIMNEY_FLASH", "SKYLIGHT_FLASH", "PIPE_JACK_FLASH", "BOX_VENT",
                               "TURBINE_VENT", "VENT_CAP", "CHIMNEY_CHASE_COVER", "RIDGE_VENT", "UNMAPPED"}


def _structure_of_face(geom: EagleViewGeometry, face_id: str) -> str:
    """The <ROOF id="…"> a component sits in. A notch label like 'F21+F22' takes its first member; an
    empty structure_id (no ROOF nesting in the XML) collapses to '' so a lone structure stays anonymous."""
    first = str(face_id).split("+")[0]
    face = geom.faces.get(first)
    return (getattr(face, "structure_id", "") or "") if face is not None else ""


def _aggregate_by_structure(geom: EagleViewGeometry, components, confirmed_selection, active_transitions) -> Tuple[Tuple[str, Tuple[AggregatedScopeLine, ...]], ...]:
    """Per-structure material lists, one aggregation per <ROOF id>. Reuses the SAME steps the global
    aggregation uses (appurtenance dedup, edge dedup + ridge vents, transition expansion, trade-order
    aggregation), scoped to each structure's own components. Physically separate structures share no
    edge, so per-structure edge dedup equals the global dedup — which is why the single-structure entry
    comes out byte-identical to aggregated_scope."""
    comps_by_structure: "MutableMapping[str, List]" = {}
    for comp in components:
        comps_by_structure.setdefault(_structure_of_face(geom, comp.face_id), []).append(comp)

    trans_by_structure: "MutableMapping[str, List]" = {}
    if active_transitions:
        selected_ids = set(selected_transition_repairs(confirmed_selection))
        valley_ids = [str(v) for v in (confirmed_selection.get("selected_valley_ids", ()) or ())]
        for t in active_transitions:
            sid = _structure_of_face(geom, t.face_a_id)
            trans_by_structure.setdefault(sid, []).append(Transition(
                contact_LF=transition_contact_lf(geom, t, valley_ids),
                edge_total_LF=float(t.edge_total_LF),
                selected=t.edge_id in selected_ids))

    out: List[Tuple[str, Tuple[AggregatedScopeLine, ...]]] = []
    for sid in sorted(comps_by_structure, key=_struct_sort_key):
        seen_appurt: set = set()
        non_edge: List[ScopeLine] = []
        edge_contribs: List[EdgeContribution] = []
        for comp in comps_by_structure[sid]:
            gid = next((a.group for a in comp.iface.appurts if a.group is not None), None)
            for line in comp.scope_lines:
                if line.category_id in _EDGE_DRIVEN_CATEGORIES:
                    continue
                if gid is not None and line.category_id in _APPURT_MATERIAL_CATEGORIES:
                    key = (gid, line.category_id)
                    if key in seen_appurt:
                        continue
                    seen_appurt.add(key)
                non_edge.append(line)
            edge_contribs.extend(comp.edge_contributions)
        deduped = _dedupe_edge_contributions(edge_contribs)
        edge_lines = _edge_lines_with_ridge_vents(deduped, _ridge_vents(confirmed_selection))
        trans_lines = (tuple(expand_scope(M1Interface(transitions=trans_by_structure[sid]), repair_factor=1.0))
                       if trans_by_structure.get(sid) else ())
        out.append((sid, tuple(_aggregate_lines([*non_edge, *edge_lines, *trans_lines]))))
    return tuple(out)


def _struct_sort_key(sid: str):
    """Order structures by the trailing integer of the ROOF id when present (ROOF1, ROOF2, …), else name."""
    import re as _re
    m = _re.search(r"(\d+)$", str(sid))
    return (0, int(m.group(1))) if m else (1, str(sid))


def _aggregate_lines(lines: Iterable[ScopeLine]) -> List[AggregatedScopeLine]:
    """Merge scope lines into the material list.

    The key now includes `xact_code`, so lines that will be BILLED DIFFERENTLY are never merged.
    Same-code lines still merge exactly as before. Verified: CHIMNEY_FLASH is the ONLY category whose
    code varies (S/A/L); every other category emits a single code, so nothing else can split.
    """
    totals: MutableMapping[Tuple[str, str, str, Optional[str], str], float] = {}
    items: MutableMapping[Tuple[str, str, str, Optional[str], str], str] = {}
    cites: MutableMapping[Tuple[str, str, str, Optional[str], str], Optional[str]] = {}
    for line in lines:
        code = getattr(line, "xact_code", None)
        # v77 DEFECT 5 (Joseph, binding): GROUP BY THE USER'S LABEL. The item text (the user's own
        # label for a user-placed appurtenance, e.g. '6" pipe jack') now participates in the merge key,
        # matched on case and surrounding whitespace only — so two DIFFERENT labels never merge and two
        # IDENTICAL labels do. Standard categories emit a single stable item per (category, code), so
        # this is a no-op for them and every existing report stays byte-identical.
        item_key = str(getattr(line, "item", line.category_id) or line.category_id).strip().casefold()
        key = (line.category_id, line.unit, line.gate, code, item_key)
        totals[key] = totals.get(key, 0.0) + float(line.qty)
        # The citation is ADDITIVE METADATA, deliberately NOT part of the key — it must never split a
        # line. Lines that merge share the same authority; if two somehow differed we keep the first
        # and never fabricate a blend.
        cites.setdefault(key, getattr(line, "citation", None))
        # A split chimney line names its size, so a human reading the material list can tell the three
        # apart. A category with no code keeps its existing item text, unchanged.
        default_item = getattr(line, "item", line.category_id) or line.category_id
        items.setdefault(key, _XACT_SIZE_LABEL.get(code, default_item) if code else default_item)
    out = [AggregatedScopeLine(item=items[k], category_id=k[0], unit=k[1], gate=k[2],
                               qty=round(v, 4), xact_code=k[3], citation=cites.get(k))
           for k, v in totals.items()]  # k = (category_id, unit, gate, xact_code, item_key)
    return sorted(out, key=_trade_order_key)


# THE ORDER AN ESTIMATE IS WRITTEN IN — not alphabetical, which buried the shakes in the middle and
# meant nothing to a roofer or an estimator. Defined ONCE, here. An unknown category falls to the end
# (never crashes, never drops a line); UNMAPPED is last of all, so anything unclassified is conspicuous.
_TRADE_ORDER = (
    # 1. the shakes
    "SHAKE_FIELD_RR",
    # 2. roof covering / underlayment / trim
    "FIELD_TEAROFF", "FIELD_COVERING", "FIELD_FELT", "IWS", "APPURT_IWS",
    "STARTER", "DRIP_EDGE", "RIDGE_CAPS", "HIP_CAPS", "RIDGE_HIP_CAP", "GABLE_CORNICE",
    # 3. flashings
    "VALLEY_METAL", "STEP_FLASH", "TRANSITION_FLASH", "ENDWALL_FLASH",
    "CHIMNEY_FLASH", "SKYLIGHT_FLASH", "PIPE_JACK_FLASH",
    # 4. vents & other appurtenances
    "BOX_VENT", "TURBINE_VENT", "RIDGE_VENT", "VENT_CAP", "CHIMNEY_CHASE_COVER",
    # 5. labor & charges
    "GENERAL_LABOR", "STEEP_CHARGE", "HIGH_SLOPE_CHARGE",
    # 6. anything unclassified, last and conspicuous
    "UNMAPPED",
)
_TRADE_RANK = {cat: i for i, cat in enumerate(_TRADE_ORDER)}
_UNKNOWN_RANK = len(_TRADE_ORDER)          # an unknown category falls to the end, never crashes

# within STEEP_CHARGE the tiers read in slope order, the way a carrier writes them
_STEEP_TIER_RANK = {"STEEP_7-9": 0, "STEEP_10-12": 1, "STEEP_>12": 2}


def _trade_order_key(line: AggregatedScopeLine):
    rank = _TRADE_RANK.get(line.category_id, _UNKNOWN_RANK)
    tier = _STEEP_TIER_RANK.get(line.xact_code or "", 0)
    return (rank, line.category_id, tier, line.unit, line.gate, line.xact_code or "")


def _claim_valley_lf_once(geom: EagleViewGeometry, valley_id: str, selected_valley_ids: Sequence[str], claimed: set[str]) -> float:
    if valley_id not in selected_valley_ids or valley_id in claimed:
        return 0.0
    claimed.add(valley_id)
    return float(geom.valley_lengths[valley_id])


def _require_valley_borders_face(geom: EagleViewGeometry, valley_id: str, face_id: str) -> None:
    if valley_id not in geom.lines or geom.lines[valley_id].type.upper() != "VALLEY":
        raise ValueError(f"missing valley candidate {valley_id}")
    if valley_id not in geom.faces[face_id].line_ids:
        raise ValueError(f"{valley_id} does not border {face_id}")


def _host_face_for_penetration(geom: EagleViewGeometry, penetration_id: str) -> str:
    for face_id, face in geom.roof_faces.items():
        if penetration_id in face.children:
            return face_id
    raise ValueError(f"missing penetration host for {penetration_id}")


def _penetration_candidate_from_geom(geom: EagleViewGeometry, host_face_id: str, penetration_id: str) -> Candidate:
    if penetration_id not in geom.penetration_faces:
        raise ValueError(f"missing penetration candidate {penetration_id}")
    if penetration_id not in geom.faces[host_face_id].children:
        raise ValueError(f"penetration {penetration_id} is not hosted by {host_face_id}")
    return Candidate(
        kind="penetration",
        source_ids=(penetration_id,),
        origin="xml",
        params={
            "penetration_face_id": penetration_id,
            "host_facet_id": host_face_id,
            "appurtenance_geometry": dict(geom.penetration_appurtenance_for_face(host_face_id, penetration_id)),
        },
        confirmed=False,
    )


def _require_notch_candidate(candidates: Mapping[Tuple[str, ...], Candidate], member_face_ids: Tuple[str, ...]) -> Candidate:
    key = tuple(sorted(member_face_ids, key=_id_sort_key))
    candidate = candidates.get(key)
    if candidate is None:
        raise ValueError(f"missing notch candidate {key}")
    return candidate


def _as_mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError("confirmed selection entries must be mappings")
    return value


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


def _length_3d(points: Sequence[Tuple[float, float, float]]) -> float:
    total = 0.0
    for a, b in zip(points, points[1:]):
        total += float(np.linalg.norm(np.array(b, dtype=float) - np.array(a, dtype=float)))
    return total
