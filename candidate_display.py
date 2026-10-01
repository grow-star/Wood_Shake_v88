#!/usr/bin/env python3
# CHANGELOG 2026-07-04: notch valley_ids threaded from UI; fallback preserves anchor 3691.
"""Layer 2 candidate-display and selection-surfacing helpers.

This module is input surfacing only. It does not compute affected area, scope,
comparison states, or report prose. It packages detected Module 1 candidates into
JSON-native display rows and converts user-confirmed display selections into the
confirmed-candidate payloads consumed by build_confirmation_from_selections.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Sequence, Tuple

from candidate_emitters import emit_face_candidates, emit_penetration_candidates, emit_valley_candidates
from notch_candidate_emitter import emit_notch_candidates


TYPE_OPTIONS = ("PIPE", "CHIMNEY", "SKYLIGHT")
SIZE_OPTIONS = ("S", "A", "L")


def build_display_model(geom: Any) -> dict[str, Any]:
    """Return JSON-native display rows for the Workbench candidate layer."""
    face_candidates = emit_face_candidates(geom)
    valley_candidates = emit_valley_candidates(geom)
    penetration_candidates = emit_penetration_candidates(geom)
    notch_candidates = emit_notch_candidates(geom)
    face_by_id = {str(candidate.source_ids[0]): candidate for candidate in face_candidates}

    valley_rows: List[dict[str, Any]] = []
    for valley in valley_candidates:
        valley_id = str(valley.params["valley_line_id"])
        bordering = [str(face_id) for face_id in valley.params.get("bordering_roof_face_ids", ())]
        pair_label = _valley_pair_label(geom, bordering, valley_id)
        for face_id in bordering:
            face = face_by_id.get(face_id)
            designator = _face_designator(geom, face_id)
            valley_rows.append({
                "id": f"valley_intersection:{face_id}:{valley_id}",
                "kind": "valley_intersection",
                "confirmed_default": False,
                "face_id": face_id,
                "facet_designator": designator,
                "valley_id": valley_id,
                "valley_source_ids": _json_list(valley.source_ids),
                "face_source_ids": _json_list(face.source_ids) if face is not None else [face_id],
                "bordering_roof_face_ids": bordering,
                "endpoint_ids": _json_list(valley.params.get("endpoint_ids", ())),
                "label": f"Facet {designator} - Valley {valley_id}",
                "combined_label_if_both_facets_confirmed": pair_label,
            })

    appurtenance_rows: List[dict[str, Any]] = []
    for candidate in penetration_candidates:
        params = candidate.params
        pen_id = str(params.get("penetration_face_id") or candidate.source_ids[0])
        host_id = str(params.get("host_facet_id") or "")
        designator = _face_designator(geom, host_id) if host_id else host_id
        default_type = _default_appurtenance_type(params)
        appurtenance_rows.append({
            "id": f"appurtenance:{host_id}:{pen_id}",
            "kind": "appurtenance",
            "confirmed_default": False,
            "host_face_id": host_id,
            "host_designator": designator,
            "penetration_face_id": pen_id,
            "source_ids": _json_list(candidate.source_ids),
            "label": f"Facet {designator} - {_title(default_type)}",
            "type_options": list(TYPE_OPTIONS),
            "default_type": default_type,
            "contacted_default": False,
            "size_class_options": list(SIZE_OPTIONS),
            "requires_size_class_for": ["CHIMNEY"],
            "appurtenance_geometry": _json_value(params.get("appurtenance_geometry")),
            "place_new_status": "DETECTED_ONLY_LAYER3_PLACE_NEW_PENDING",
        })

    notch_rows: List[dict[str, Any]] = []
    for candidate in notch_candidates:
        member_ids = [str(face_id) for face_id in candidate.params.get("member_face_ids", candidate.source_ids)]
        label = _notch_label(geom, member_ids)
        notch_rows.append({
            "id": "notch:" + "+".join(member_ids),
            "kind": "notch",
            "confirmed_default": False,
            "source_ids": _json_list(candidate.source_ids),
            "member_face_ids": member_ids,
            "member_designators": [_face_designator(geom, face_id) for face_id in member_ids],
            "label": label,
            "route": "notch_repairs",
            "diagram_interaction_status": "LAYER3_OPEN",
        })

    return {
        "valley_intersections": valley_rows,
        "appurtenances": appurtenance_rows,
        "notches": notch_rows,
        "place_new_appurtenances": {
            "status": "LAYER3_PENDING",
            "message": "Off-XML user placement is not built in Layer 2.",
        },
    }


def confirmed_candidates_from_selection(geom: Any, selection_dict: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Convert confirmed UI/workbench selections into confirmed candidate payloads.

    This accepts either the five-collection confirmation selection used by the
    existing proof gates, or the Layer-2 display-selection shape.
    """
    if _is_pipeline_confirmation_shape(selection_dict):
        return _confirmed_candidates_from_pipeline_selection(geom, selection_dict)
    return _confirmed_candidates_from_display_selection(geom, selection_dict)


def _confirmed_candidates_from_pipeline_selection(geom: Any, selection_dict: Mapping[str, Any]) -> list[dict[str, Any]]:
    face_candidates = emit_face_candidates(geom)
    valley_candidates = emit_valley_candidates(geom)
    penetration_candidates = emit_penetration_candidates(geom)
    notch_candidates = emit_notch_candidates(geom)

    confirmed: list[dict[str, Any]] = []
    for valley_id in selection_dict["selected_valley_ids"]:
        confirmed.append(_ui_confirm(_valley_by_id(valley_candidates, str(valley_id))))

    for row_obj in selection_dict["single_valley_repairs"]:
        row = _mapping(row_obj)
        confirmed.append(_ui_confirm(
            _face_by_id(face_candidates, str(row["face_id"])),
            label=row["label"],
            confirmed_valley_line_ids=(row["valley_id"],),
        ))

    for row_obj in selection_dict["multi_valley_facets"]:
        row = _mapping(row_obj)
        confirmed.append(_ui_confirm(
            _face_by_id(face_candidates, str(row["face_id"])),
            label=row["label"],
            confirmed_valley_line_ids=tuple(row["valley_ids"]),
            include_child_penetrations=row.get("include_child_penetrations", True),
        ))

    for row_obj in selection_dict["penetration_appurtenance_repairs"]:
        row = _mapping(row_obj)
        updates = {
            "label": row["label"],
            "host_face_id": row["host_face_id"],
            "kind_label": row.get("kind_label"),
            "group": row.get("group"),
        }
        if row.get("contacted") is not None:
            updates["contacted"] = bool(row["contacted"])
        if row.get("size_class") not in (None, ""):
            updates["size_class"] = str(row["size_class"])
        # POWER ATTIC VENT operation (cover-only vs fan). This is the SECOND of three sequential
        # allowlists between page 2 and the engine (workbench_seam -> here -> confirmation_builder);
        # a field must be threaded through ALL THREE or it is silently dropped and the engine quietly
        # falls back to its default — which for a cover-only vent means carving area that is not
        # disturbed. Guarded by `not in (None, "")` so nothing changes for any other appurtenance.
        if row.get("operation") not in (None, ""):
            updates["operation"] = str(row["operation"])
        # v71 DEFECT 2: the user-defined appurtenance name (kind_label=OTHER) — SECOND allowlist.
        if row.get("other_label") not in (None, ""):
            updates["other_label"] = str(row["other_label"])
        if row.get("other_category") not in (None, ""):
            updates["other_category"] = str(row["other_category"])
        confirmed.append(_ui_confirm(_penetration_by_id(penetration_candidates, str(row["penetration_face_id"])), **updates))

    for row_obj in selection_dict["notch_repairs"]:
        row = _mapping(row_obj)
        confirmed.append(_ui_confirm(
            _notch_by_members(notch_candidates, row["member_face_ids"]),
            label=row["label"],
            **({"valley_ids": [str(v) for v in row["valley_ids"]]} if row.get("valley_ids") else {}),
        ))

    return confirmed


def _confirmed_candidates_from_display_selection(geom: Any, selection_dict: Mapping[str, Any]) -> list[dict[str, Any]]:
    face_candidates = emit_face_candidates(geom)
    valley_candidates = emit_valley_candidates(geom)
    penetration_candidates = emit_penetration_candidates(geom)
    notch_candidates = emit_notch_candidates(geom)

    selected_valleys: set[str] = set()
    face_to_valleys: MutableMapping[str, list[str]] = {}
    face_options: dict[str, dict[str, Any]] = {}

    for row_obj in selection_dict.get("valley_intersections", ()):  # type: ignore[union-attr]
        row = _mapping(row_obj)
        face_id = str(row["face_id"])
        valley_id = str(row["valley_id"])
        selected_valleys.add(valley_id)
        face_to_valleys.setdefault(face_id, [])
        if valley_id not in face_to_valleys[face_id]:
            face_to_valleys[face_id].append(valley_id)
        face_options.setdefault(face_id, {})
        if row.get("include_child_penetrations") is not None:
            face_options[face_id]["include_child_penetrations"] = row.get("include_child_penetrations")

    confirmed: list[dict[str, Any]] = []
    for valley_id in sorted(selected_valleys, key=_id_sort_key):
        confirmed.append(_ui_confirm(_valley_by_id(valley_candidates, valley_id)))

    for face_id in sorted(face_to_valleys, key=_id_sort_key):
        valley_ids = tuple(sorted(face_to_valleys[face_id], key=_id_sort_key))
        updates: dict[str, Any] = {
            "label": _selected_face_label(geom, face_id, valley_ids),
            "confirmed_valley_line_ids": valley_ids,
            "include_child_penetrations": bool(face_options.get(face_id, {}).get("include_child_penetrations", True)),
        }
        confirmed.append(_ui_confirm(_face_by_id(face_candidates, face_id), **updates))

    for row_obj in selection_dict.get("appurtenances", ()):  # type: ignore[union-attr]
        row = _mapping(row_obj)
        pen_id = str(row["penetration_face_id"])
        host_id = str(row.get("host_face_id") or row.get("host_facet_id") or "")
        type_value = str(row.get("type") or row.get("kind_label") or "CHIMNEY").upper()
        if type_value.endswith("_FLASH"):
            type_value = type_value.replace("_FLASH", "")
        if type_value == "PIPE_JACK":
            type_value = "PIPE"
        updates = {
            "label": row.get("label") or f"Facet {_face_designator(geom, host_id)} - {_title(type_value)}",
            "host_face_id": host_id,
            "kind_label": type_value,
            "group": row.get("group") or pen_id,
            "contacted": bool(row.get("contacted", True)),
        }
        if row.get("size_class") not in (None, ""):
            updates["size_class"] = str(row["size_class"])
        # v71 DEFECT 2: carry the user-defined name from the display-shaped appurtenances payload.
        if row.get("other_label") not in (None, ""):
            updates["other_label"] = str(row["other_label"])
        if row.get("other_category") not in (None, ""):
            updates["other_category"] = str(row["other_category"])
        confirmed.append(_ui_confirm(_penetration_by_id(penetration_candidates, pen_id), **updates))

    for row_obj in selection_dict.get("notches", ()):  # type: ignore[union-attr]
        row = _mapping(row_obj)
        members = tuple(str(v) for v in row.get("member_face_ids", row.get("source_ids", ())))
        confirmed.append(_ui_confirm(_notch_by_members(notch_candidates, members), label=row.get("label") or _notch_label(geom, members)))

    return confirmed


def _ui_confirm(candidate: Any, **updates: Any) -> dict[str, Any]:
    payload = {
        "kind": candidate.kind,
        "source_ids": tuple(candidate.source_ids),
        "origin": candidate.origin,
        "params": deepcopy(candidate.params),
        "confirmed": True,
    }
    payload["params"].update(updates)
    return payload


def _face_by_id(candidates: Sequence[Any], face_id: str) -> Any:
    return next(candidate for candidate in candidates if candidate.source_ids == (face_id,))


def _valley_by_id(candidates: Sequence[Any], valley_id: str) -> Any:
    return next(candidate for candidate in candidates if candidate.source_ids == (valley_id,))


def _penetration_by_id(candidates: Sequence[Any], penetration_id: str) -> Any:
    return next(candidate for candidate in candidates if candidate.source_ids == (penetration_id,))


def _notch_by_members(candidates: Sequence[Any], members: Iterable[str]) -> Any:
    key = tuple(sorted((str(value) for value in members), key=_id_sort_key))
    return next(candidate for candidate in candidates if tuple(candidate.source_ids) == key)


def _is_pipeline_confirmation_shape(selection_dict: Mapping[str, Any]) -> bool:
    return all(key in selection_dict for key in (
        "selected_valley_ids",
        "single_valley_repairs",
        "multi_valley_facets",
        "penetration_appurtenance_repairs",
        "notch_repairs",
    ))


def _valley_pair_label(geom: Any, bordering_face_ids: Sequence[str], valley_id: str) -> str:
    names = [_face_designator(geom, face_id) for face_id in bordering_face_ids]
    if len(names) >= 2:
        return f"Facets {' + '.join(names)} - Valley {valley_id}"
    if len(names) == 1:
        return f"Facet {names[0]} - Valley {valley_id}"
    return f"Valley {valley_id}"


def _selected_face_label(geom: Any, face_id: str, valley_ids: Sequence[str]) -> str:
    designator = _face_designator(geom, face_id)
    if len(valley_ids) == 1:
        return f"Facet {designator} - Valley {valley_ids[0]}"
    return f"Facet {designator} multi-valley union"


def _notch_label(geom: Any, member_face_ids: Iterable[str]) -> str:
    names = [_face_designator(geom, str(face_id)) for face_id in member_face_ids]
    return "Facets " + "/".join(names)


def _face_designator(geom: Any, face_id: str) -> str:
    face = getattr(geom, "faces", {}).get(face_id)
    return str(getattr(face, "designator", "") or face_id)


def _default_appurtenance_type(params: Mapping[str, Any]) -> str:
    geom = params.get("appurtenance_geometry")
    if isinstance(geom, Mapping) and str(geom.get("kind", "")).lower() == "dimensioned":
        return "CHIMNEY"
    return "PIPE"


def _title(value: str) -> str:
    return str(value).replace("_", " ").title()


def _json_list(value: Any) -> list[Any]:
    return list(_json_value(value) or [])


def _json_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(k): _json_value(v) for k, v in value.items()}
    if isinstance(value, tuple):
        return [_json_value(v) for v in value]
    if isinstance(value, list):
        return [_json_value(v) for v in value]
    return value


def _mapping(value: Any) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError("selection rows must be mappings")
    return value


def _id_sort_key(value: str) -> Tuple[str, int, str]:
    prefix = "".join(ch for ch in str(value) if not ch.isdigit())
    digits = "".join(ch for ch in str(value) if ch.isdigit())
    return (prefix, int(digits or "0"), str(value))
