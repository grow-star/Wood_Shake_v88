#!/usr/bin/env python3
# CHANGELOG 2026-07-04: notch valley_ids threaded from UI; fallback preserves anchor 3691.
"""Layer 3 Piece A: headless Workbench UI -> frozen engine seam.

This module intentionally contains no UI, browser, diagram, geometry math, or
scope math.  It only translates a Workbench-style selection payload into the
existing engine confirmation payload, then delegates all calculation to the
frozen Module 2 assembly engine.
"""

from __future__ import annotations

from typing import Any, Mapping, MutableMapping

from candidate_display import confirmed_candidates_from_selection
from confirmation_builder import build_confirmation_from_selections
from eagleview_geometry_parser import EagleViewGeometry, parse_eagleview_geometry
from module2_assembly import RoofAssemblyResult, assemble_full_roof_scope


XML_TEXT_KEYS = ("xml_text", "_xml_text", "eagleview_xml", "source_xml")


def build_scope_from_ui_selection(geom: EagleViewGeometry | str, ui_selection: Mapping[str, Any] | None) -> RoofAssemblyResult:
    """Return the frozen engine's assembled scope for a UI selection.

    Parameters
    ----------
    geom:
        Either parsed EagleView geometry or the EagleView XML text.  The seam
        needs parsed geometry for candidate translation and XML text for the
        existing assembly function, so a parsed geometry call must include the
        source XML under one of XML_TEXT_KEYS in ``ui_selection``.
    ui_selection:
        Additive per-intersection Workbench selection. Empty/None means nothing
        selected and is valid.

    The function computes no scope or geometry quantities. All confirmed routing
    is delegated to candidate_display.py and confirmation_builder.py; all scope
    quantities are delegated to module2_assembly.py.
    """
    selection: Mapping[str, Any] = ui_selection or {}
    parsed_geom, xml_text = _resolve_geometry_and_xml(geom, selection)

    engine_selection = _selection_for_candidate_display(selection)
    confirmed_candidates = confirmed_candidates_from_selection(parsed_geom, engine_selection)
    confirmed_selection = build_confirmation_from_selections(confirmed_candidates, geom=parsed_geom)
    # User-defined appurtenances carve directly in the assembly engine (no candidate translation),
    # so they are carried onto the confirmed selection rather than through candidate_display.
    user_rows = list(engine_selection.get("user_appurtenance_repairs", ()))
    if user_rows:
        confirmed_selection = {**dict(confirmed_selection), "user_appurtenance_repairs": user_rows}
    # PATH B: user-confirmed pitch-transition repair events ride onto the confirmed selection the
    # same way. Each row is {edge_id, exposed, damaged}; the engine (transition_events) requires
    # BOTH assertions to be explicitly True, so the gate cannot be bypassed by the payload.
    transition_rows = [dict(r) for r in (selection.get("transition_repairs", ()) or ())]
    if transition_rows:
        confirmed_selection = {**dict(confirmed_selection), "transition_repairs": transition_rows}
    # Facets the user asserted are 2-story. STEEP is derived from geometry and needs no payload;
    # HIGH-SLOPE is a HEIGHT charge that the roof geometry cannot possibly tell us.
    high_slope_rows = [dict(r) if isinstance(r, dict) else {"face_id": str(r), "high": True}
                       for r in (selection.get("high_slope_facets", ()) or ())]
    if high_slope_rows:
        confirmed_selection = {**dict(confirmed_selection), "high_slope_facets": high_slope_rows}
    # Ridge vents: a MATERIAL item on an already-in-scope ridge run, never a repair event.
    ridge_vent_rows = [dict(r) for r in (selection.get("ridge_vents", ()) or ()) if isinstance(r, dict)]
    if ridge_vent_rows:
        confirmed_selection = {**dict(confirmed_selection), "ridge_vents": ridge_vent_rows}
    # v61 full slope replacement: a neutral stored fact "this facet is a replacement" (comparison vs
    # repair-scope wording is decided in the report on page 3, so page 2 stays mode-neutral). Carried
    # onto the confirmed selection exactly like ridge_vents / high_slope_facets.
    replaced_rows = [dict(r) if isinstance(r, dict) else {"face_id": str(r)}
                     for r in (selection.get("replaced_facets", ()) or ())]
    if replaced_rows:
        confirmed_selection = {**dict(confirmed_selection), "replaced_facets": replaced_rows}
    # v71 DEFECT 3: eave ICE & WATER assertion (page 2 checkboxes) and the measured soffit depth
    # (page 1). Neutral stored facts carried onto the confirmed selection exactly like the rows above;
    # the engine fires eave IWS only when code and/or existing is asserted on exposed eaves.
    _eave_iws = selection.get("eave_iws")
    if isinstance(_eave_iws, Mapping) and (_eave_iws.get("code") or _eave_iws.get("existing")):
        confirmed_selection = {**dict(confirmed_selection),
                               "eave_iws": {"code": bool(_eave_iws.get("code")),
                                            "existing": bool(_eave_iws.get("existing"))}}
    if selection.get("soffit_depth_in") not in (None, ""):
        confirmed_selection = {**dict(confirmed_selection),
                               "soffit_depth_in": float(selection["soffit_depth_in"])}
    shake_measurements = selection.get("shake_measurements") or selection.get("shakeMeasurements") or selection.get("shake_profile")
    if shake_measurements:
        confirmed_selection = {**dict(confirmed_selection), "shake_measurements": shake_measurements}
    return assemble_full_roof_scope(xml_text, confirmed_selection)


def _resolve_geometry_and_xml(geom: EagleViewGeometry | str, selection: Mapping[str, Any]) -> tuple[EagleViewGeometry, str]:
    if isinstance(geom, str):
        return parse_eagleview_geometry(geom), geom

    for key in XML_TEXT_KEYS:
        value = selection.get(key)
        if isinstance(value, str) and value.strip():
            return geom, value

    raise ValueError(
        "build_scope_from_ui_selection needs XML text for the frozen assembly engine. "
        "Pass XML text as geom, or include it in ui_selection under one of: "
        + ", ".join(XML_TEXT_KEYS)
    )


def _selection_for_candidate_display(selection: Mapping[str, Any]) -> Mapping[str, Any]:
    """Normalize display-shaped UI clicks into the engine confirmation shape.

    The candidate-display helper already accepts the five-collection pipeline
    shape, so that shape is passed through unchanged. Display-shaped valley
    intersections are grouped by facet here to preserve the required
    one-facet/one-candidate behavior. Valley LF selection is explicit:
    rows may set claim_valley_lf/include_valley_lf/select_valley_lf true, or
    callers may pass selected_valley_ids directly. This avoids treating
    multi-valley boundary lines as automatically claimed valley-LF scope.
    """
    required = {
        "selected_valley_ids",
        "single_valley_repairs",
        "multi_valley_facets",
        "penetration_appurtenance_repairs",
        "notch_repairs",
    }
    if required.issubset(selection.keys()):
        # A pre-built confirmed selection passes through as-is; transition_repairs (if any) ride
        # along untouched. The exposed+damaged gate is enforced downstream in transition_events.
        return selection

    face_to_valleys: dict[str, list[str]] = {}
    face_options: dict[str, dict[str, Any]] = {}
    selected_valley_ids: list[str] = [str(v) for v in selection.get("selected_valley_ids", ())]

    for row_obj in selection.get("valley_intersections", ()):  # type: ignore[union-attr]
        if not isinstance(row_obj, Mapping):
            raise TypeError("valley_intersections rows must be mappings")
        face_id = str(row_obj["face_id"])
        valley_id = str(row_obj["valley_id"])
        face_to_valleys.setdefault(face_id, [])
        if valley_id not in face_to_valleys[face_id]:
            face_to_valleys[face_id].append(valley_id)
        if _truthy_any(row_obj, ("claim_valley_lf", "include_valley_lf", "select_valley_lf")) and valley_id not in selected_valley_ids:
            selected_valley_ids.append(valley_id)
        if row_obj.get("include_child_penetrations") is not None:
            face_options.setdefault(face_id, {})["include_child_penetrations"] = row_obj.get("include_child_penetrations")

    single_valley_repairs: list[dict[str, Any]] = []
    multi_valley_facets: list[dict[str, Any]] = []
    for face_id in sorted(face_to_valleys, key=_id_sort_key):
        valley_ids = sorted(face_to_valleys[face_id], key=_id_sort_key)
        include_children = bool(face_options.get(face_id, {}).get("include_child_penetrations", True))
        if len(valley_ids) == 1:
            single_valley_repairs.append({
                "label": f"Facet {face_id} - Valley {valley_ids[0]}",
                "face_id": face_id,
                "valley_id": valley_ids[0],
                "include_child_penetrations": include_children,
            })
        else:
            multi_valley_facets.append({
                "label": f"Facet {face_id} multi-valley union",
                "face_id": face_id,
                "valley_ids": valley_ids,
                "include_child_penetrations": include_children,
            })

    penetration_rows = []
    for row_obj in selection.get("appurtenances", ()):  # type: ignore[union-attr]
        if not isinstance(row_obj, Mapping):
            raise TypeError("appurtenances rows must be mappings")
        penetration_rows.append({
            "label": row_obj.get("label") or str(row_obj.get("penetration_face_id")),
            "host_face_id": str(row_obj.get("host_face_id") or row_obj.get("host_facet_id") or ""),
            "penetration_face_id": str(row_obj["penetration_face_id"]),
            "kind_label": row_obj.get("kind_label") or row_obj.get("type") or "CHIMNEY",
            "group": row_obj.get("group") or str(row_obj["penetration_face_id"]),
            "contacted": row_obj.get("contacted", True),
            "size_class": row_obj.get("size_class"),
            # POWER ATTIC VENT: cover-only vs fan/full unit. THIS DICT IS A WHITELIST — a key that is
            # not listed here is SILENTLY DROPPED, and an operation dropped here would have left the
            # engine defaulting to "carve" while page 2 showed the user "cover only". That is exactly
            # the failure mode this project has hit repeatedly: a feature specified, implemented,
            # believed live, and never once firing because the payload never reached the engine.
            # Carried explicitly, and locked by power_vent_regression's end-to-end page-2 payload test.
            "operation": row_obj.get("operation") or row_obj.get("power_vent_operation"),
            # v71 DEFECT 2: a user-defined appurtenance (kind_label=OTHER) names itself with
            # other_label ('6" pipe jack'). This is the THIRD key the fixed-key rebuild has eaten
            # (after operation, structure). Carried through all three allowlists, exactly like
            # operation, so the material list and comparison use the user's own words.
            **({"other_label": row_obj["other_label"]} if row_obj.get("other_label") not in (None, "") else {}),
            **({"other_category": row_obj["other_category"]} if row_obj.get("other_category") not in (None, "") else {}),
        })

    notch_rows = []
    for row_obj in selection.get("notches", ()):  # type: ignore[union-attr]
        if not isinstance(row_obj, Mapping):
            raise TypeError("notches rows must be mappings")
        _notch_vids = [str(v) for v in row_obj.get("valley_ids", ())]
        notch_rows.append({
            "label": row_obj.get("label") or "+".join(str(v) for v in row_obj.get("member_face_ids", row_obj.get("source_ids", ()))),
            "member_face_ids": [str(v) for v in row_obj.get("member_face_ids", row_obj.get("source_ids", ()))],
            **({"valley_ids": _notch_vids} if _notch_vids else {}),
        })

    return {
        "selected_valley_ids": selected_valley_ids,
        "single_valley_repairs": single_valley_repairs,
        "multi_valley_facets": multi_valley_facets,
        "penetration_appurtenance_repairs": penetration_rows,
        "notch_repairs": notch_rows,
        "user_appurtenance_repairs": list(selection.get("user_appurtenance_repairs", ())),
        # PATH B: user-confirmed pitch-transition repair events. Each row is
        # {edge_id, exposed, damaged}. The engine (transition_events) enforces that BOTH
        # assertions are explicitly True — the UI gate is not the enforcement point, so a
        # payload cannot smuggle in an unasserted transition.
        "transition_repairs": [dict(r) for r in (selection.get("transition_repairs", ()) or ())],
    }


def _truthy_any(row: Mapping[str, Any], keys: tuple[str, ...]) -> bool:
    return any(bool(row.get(key)) for key in keys)


def _id_sort_key(value: str) -> tuple[str, int, str]:
    prefix = "".join(ch for ch in str(value) if not ch.isdigit())
    digits = "".join(ch for ch in str(value) if ch.isdigit())
    return (prefix, int(digits or "0"), str(value))


# ------------------------- verification helpers -------------------------
# These helpers are deliberately outside the production seam. They exist so this
# file can be run directly and produce the Piece-A receipts.


def _ui_selection_from_confirmed_selection(confirmed: Mapping[str, Any], *, xml_text: str | None = None) -> dict[str, Any]:
    """Reconstruct the additive display-selection shape from a pipeline selection."""
    out: dict[str, Any] = {
        "valley_intersections": [],
        "appurtenances": [],
        "notches": [],
    }
    if xml_text is not None:
        out["xml_text"] = xml_text

    selected = {str(v) for v in confirmed.get("selected_valley_ids", ())}

    for row in confirmed.get("single_valley_repairs", ()):  # type: ignore[union-attr]
        r = dict(row)
        valley_id = str(r["valley_id"])
        selected.add(valley_id)
        out["valley_intersections"].append({
            "face_id": str(r["face_id"]),
            "valley_id": valley_id,
            "claim_valley_lf": valley_id in selected,
        })

    for row in confirmed.get("multi_valley_facets", ()):  # type: ignore[union-attr]
        r = dict(row)
        face_id = str(r["face_id"])
        include = bool(r.get("include_child_penetrations", True))
        for valley_id_obj in r.get("valley_ids", ()):  # type: ignore[union-attr]
            valley_id = str(valley_id_obj)
            out["valley_intersections"].append({
                "face_id": face_id,
                "valley_id": valley_id,
                "include_child_penetrations": include,
                "claim_valley_lf": valley_id in selected,
            })

    # UI-selected standalone valley lines with no repair facet are valid, too.
    already_rows = {(r["face_id"], r["valley_id"]) for r in out["valley_intersections"]}
    # There is no facet-free display row; selected_valley_ids are represented by
    # the facet rows above in the Yager round trip. Any leftover selected valley
    # would be ignored rather than guessed to a facet.
    _ = selected, already_rows

    for row in confirmed.get("penetration_appurtenance_repairs", ()):  # type: ignore[union-attr]
        r = dict(row)
        out["appurtenances"].append({
            "label": r.get("label"),
            "host_face_id": str(r.get("host_face_id", "")),
            "penetration_face_id": str(r["penetration_face_id"]),
            "type": r.get("kind_label") or "CHIMNEY",
            "kind_label": r.get("kind_label") or "CHIMNEY",
            "group": r.get("group") or str(r["penetration_face_id"]),
            "contacted": r.get("contacted", True),
            "size_class": r.get("size_class"),
            # Power-vent operation must survive the round trip too, or a test that reconstructs the
            # display payload from a confirmed selection would silently lose the user's choice.
            "operation": r.get("operation") or r.get("power_vent_operation"),
            # v71 DEFECT 2: the user-defined name survives the round trip too.
            **({"other_label": r["other_label"]} if r.get("other_label") not in (None, "") else {}),
            **({"other_category": r["other_category"]} if r.get("other_category") not in (None, "") else {}),
        })

    for row in confirmed.get("notch_repairs", ()):  # type: ignore[union-attr]
        r = dict(row)
        out["notches"].append({
            "label": r.get("label"),
            "member_face_ids": [str(v) for v in r.get("member_face_ids", ())],
        })

    return out


def _scope_qty(result: RoofAssemblyResult, category_id: str) -> float:
    for line in result.aggregated_scope:
        if line.category_id == category_id:
            return line.qty
    return 0.0


def _receipt_totals(result: RoofAssemblyResult) -> dict[str, float]:
    return {
        "EA": _scope_qty(result, "SHAKE_FIELD_RR"),
        "SF": result.affected_SF_display_total,
        "LF": round(float(result.selected_valley_LF_total), 2),
    }


def _run_piece_a_receipts() -> int:
    # Test-only import allowed by the Piece-A prompt. Production function does not
    # import any proof/regression/gate module.
    from module1_yager_proof import YAGER_CONFIRMED_SELECTION

    xml = open("XML.txt", encoding="utf-8").read()

    yager_ui = _ui_selection_from_confirmed_selection(YAGER_CONFIRMED_SELECTION, xml_text=xml)
    yager = build_scope_from_ui_selection(xml, yager_ui)
    yager_totals = _receipt_totals(yager)

    empty = build_scope_from_ui_selection(xml, {})
    empty_totals = _receipt_totals(empty)

    f4_ui = {
        "valley_intersections": [
            {"face_id": "F4", "valley_id": valley_id, "include_child_penetrations": False}
            for valley_id in ("L28", "L29", "L30", "L36", "L37", "L38")
        ]
    }
    f4 = build_scope_from_ui_selection(xml, f4_ui)
    f4_totals = _receipt_totals(f4)
    f4_multi_count = sum(1 for c in f4.components if c.face_id == "F4" and c.component_type == "multi_valley")
    f4_single_count = sum(1 for c in f4.components if c.face_id == "F4" and c.component_type == "single_valley")

    checks = [
        ("round-trip EA", yager_totals["EA"] == 3691),
        ("round-trip SF", yager_totals["SF"] == 1638.0),
        ("round-trip LF", yager_totals["LF"] == 134.03),
        ("empty EA", empty_totals["EA"] == 0.0),
        ("empty SF", empty_totals["SF"] == 0.0),
        ("empty LF", empty_totals["LF"] == 0.0),
        ("F4 one multi", f4_multi_count == 1 and f4_single_count == 0),
        ("F4 SF", round(float(f4.affected_SF_raw_total), 3) == 507.064),
        ("F4 EA", f4_totals["EA"] == 1141),
    ]

    print("PIECE A WORKBENCH SEAM RECEIPTS")
    print(f"  round-trip: EA={yager_totals['EA']} SF={yager_totals['SF']} LF={yager_totals['LF']}")
    print(f"  empty:      EA={empty_totals['EA']} SF={empty_totals['SF']} LF={empty_totals['LF']}")
    print(
        "  F4:         "
        f"raw_SF={round(float(f4.affected_SF_raw_total), 3)} EA={f4_totals['EA']} "
        f"multi_count={f4_multi_count} single_count={f4_single_count}"
    )
    for name, ok in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    return 0 if all(ok for _, ok in checks) else 1


if __name__ == "__main__":
    raise SystemExit(_run_piece_a_receipts())


def transition_states(geom, ui_selection):
    """Which detected transitions are ACTIVE for this selection, and by which path.

    UI-facing only — the engine decides; the browser just draws what it is told.
      PATH_A : swept >=95% by the repair -> AUTOMATICALLY included. No assertion is being made, so
               the UI must NOT show the exposed/damaged gate, and the user must NOT be able to
               remove it (removing it would mean billing a repair that tears the flashing out and
               then not replacing it). Deselect the triggering valley and it stops firing naturally.
      PATH_B : user-asserted exposed + damaged.
      BOTH   : swept AND asserted (still ONE flashing line).
    """
    from transition_events import path_a_transitions, selected_transition_repairs
    parsed_geom, xml_text = _resolve_geometry_and_xml(geom, ui_selection or {})
    engine_selection = _selection_for_candidate_display(ui_selection or {})
    confirmed_candidates = confirmed_candidates_from_selection(parsed_geom, engine_selection)
    confirmed = dict(build_confirmation_from_selections(confirmed_candidates, geom=parsed_geom))
    confirmed["transition_repairs"] = [dict(r) for r in ((ui_selection or {}).get("transition_repairs", ()) or ())]

    auto = {t.edge_id for t in path_a_transitions(parsed_geom, confirmed)}
    asserted = set(selected_transition_repairs(confirmed))
    out = {}
    for edge_id in sorted(auto | asserted):
        if edge_id in auto and edge_id in asserted:
            out[edge_id] = "BOTH"
        elif edge_id in auto:
            out[edge_id] = "PATH_A"
        else:
            out[edge_id] = "PATH_B"
    return out
