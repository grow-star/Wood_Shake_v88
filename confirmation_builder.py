#!/usr/bin/env python3
# CHANGELOG 2026-07-04: notch valley_ids threaded from UI; fallback preserves anchor 3691.
"""Workbench confirmation bridge for Module 1.

Pure translation only: takes UI-shaped confirmed candidate selections and emits the
five-collection confirmation dict consumed by the Module 1/2 pipeline. It does
not detect geometry, compute affected areas, compute scope, or set confirmation.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, MutableMapping, Sequence


CONFIRMATION_KEYS = (
    "selected_valley_ids",
    "single_valley_repairs",
    "multi_valley_facets",
    "penetration_appurtenance_repairs",
    "notch_repairs",
)


class ConfirmationValidationError(ValueError):
    """Raised when a UI-confirmed candidate cannot be translated safely."""


def build_confirmation_from_selections(
    confirmed_candidates: Iterable[Mapping[str, Any] | Any],
    geom: Any | None = None,
    valid_ids: Mapping[str, Iterable[str]] | None = None,
) -> dict[str, list[Any]]:
    """Translate Workbench-confirmed candidates into the pipeline confirmation dict.

    The caller passes only user-confirmed selections. This function trusts that
    selection boundary and only routes/validates the already-confirmed candidate
    payloads. Geometry is optional and used only for ID existence validation.
    """
    validators = _validators_from(geom, valid_ids)
    out: dict[str, list[Any]] = {key: [] for key in CONFIRMATION_KEYS}

    for candidate_obj in confirmed_candidates:
        candidate = _candidate_mapping(candidate_obj)
        kind = str(candidate.get("kind", ""))
        params = _params(candidate)
        source_ids = tuple(str(v) for v in candidate.get("source_ids", ()) or ())

        if kind == "valley":
            valley_id = _first_text(params, "valley_line_id", "valley_id") or _source_id(source_ids, 0, "valley")
            _require_id(validators, "valley", valley_id)
            if valley_id not in out["selected_valley_ids"]:
                out["selected_valley_ids"].append(valley_id)

        elif kind == "face":
            face_id = _first_text(params, "face_id") or _source_id(source_ids, 0, "face")
            _require_id(validators, "face", face_id)
            valley_ids = _valley_ids_from(params)
            if not valley_ids:
                raise ConfirmationValidationError(f"confirmed face {face_id!r} has no valley association")
            for valley_id in valley_ids:
                _require_id(validators, "valley", valley_id)
            label = _label(params, _face_label(params, face_id, valley_ids))
            if len(valley_ids) == 1:
                out["single_valley_repairs"].append({
                    "label": label,
                    "face_id": face_id,
                    "valley_id": valley_ids[0],
                    "include_child_penetrations": bool(params.get("include_child_penetrations", True)),
                })
            else:
                out["multi_valley_facets"].append({
                    "label": label,
                    "face_id": face_id,
                    "valley_ids": list(valley_ids),
                    "include_child_penetrations": bool(params.get("include_child_penetrations", True)),
                })

        elif kind == "penetration":
            penetration_id = _first_text(params, "penetration_face_id") or _source_id(source_ids, 0, "penetration")
            host_face_id = _first_text(params, "host_face_id", "host_facet_id")
            if host_face_id is None:
                raise ConfirmationValidationError(f"confirmed penetration {penetration_id!r} has no host face")
            _require_id(validators, "penetration", penetration_id)
            _require_id(validators, "face", host_face_id)
            row = {
                "label": _label(params, f"{host_face_id} penetration {penetration_id}"),
                "host_face_id": host_face_id,
                "penetration_face_id": penetration_id,
            }
            if params.get("kind_label") not in (None, ""):
                row["kind_label"] = str(params["kind_label"])
            if params.get("group") not in (None, ""):
                row["group"] = str(params["group"])
            if params.get("contacted") is not None:
                row["contacted"] = bool(params["contacted"])
            if params.get("size_class") not in (None, ""):
                row["size_class"] = str(params["size_class"])
            # POWER ATTIC VENT operation — the THIRD and last allowlist before the engine. Dropping
            # it here would have left the user's "cover only" choice invisible to module2_assembly
            # and module1_service, which both default to carving.
            if params.get("operation") not in (None, ""):
                row["operation"] = str(params["operation"])
            # v71 DEFECT 2: the THIRD and last allowlist — carry the user-defined appurtenance name
            # (and optional category) so kind_label=OTHER reaches the engine as the user's own words
            # instead of the generic 'User-defined appurtenance'.
            if params.get("other_label") not in (None, ""):
                row["other_label"] = str(params["other_label"])
            if params.get("other_category") not in (None, ""):
                row["other_category"] = str(params["other_category"])
            out["penetration_appurtenance_repairs"].append(row)

        elif kind == "notch":
            member_face_ids = tuple(str(v) for v in params.get("member_face_ids", ()) or source_ids)
            if len(member_face_ids) < 2:
                raise ConfirmationValidationError("confirmed notch has fewer than two member faces")
            for face_id in member_face_ids:
                _require_id(validators, "face", face_id)
            _notch_vids = [str(v) for v in params.get("valley_ids", ())]
            out["notch_repairs"].append({
                "label": _label(params, "+".join(member_face_ids)),
                "member_face_ids": list(member_face_ids),
                **({"valley_ids": _notch_vids} if _notch_vids else {}),
            })

        elif kind in {"transition", "appurtenance"}:
            # These candidates are display/placement candidates today. They do not
            # map to one of the five confirmed-repair collections until a specific
            # repair-event contract is added for them.
            raise ConfirmationValidationError(f"confirmed {kind!r} candidate has no Module 1 confirmation route yet")

        else:
            raise ConfirmationValidationError(f"unknown confirmed candidate kind: {kind!r}")

    selected = set(out["selected_valley_ids"])
    for row in out["single_valley_repairs"]:
        if row["valley_id"] not in selected:
            raise ConfirmationValidationError(f"face {row['face_id']!r} references unconfirmed valley {row['valley_id']!r}")
    return out


def _candidate_mapping(candidate: Mapping[str, Any] | Any) -> Mapping[str, Any]:
    if isinstance(candidate, Mapping):
        return candidate
    return {
        "kind": getattr(candidate, "kind"),
        "source_ids": getattr(candidate, "source_ids"),
        "origin": getattr(candidate, "origin"),
        "params": getattr(candidate, "params"),
        "confirmed": getattr(candidate, "confirmed", None),
    }


def _params(candidate: Mapping[str, Any]) -> Mapping[str, Any]:
    params = candidate.get("params", {})
    if not isinstance(params, Mapping):
        raise ConfirmationValidationError("candidate params must be a mapping")
    return params


def _validators_from(geom: Any | None, valid_ids: Mapping[str, Iterable[str]] | None) -> dict[str, set[str]]:
    if valid_ids is not None:
        return {key: {str(v) for v in vals} for key, vals in valid_ids.items()}
    if geom is None:
        return {}
    return {
        "face": set(str(v) for v in geom.roof_faces.keys()),
        "valley": set(str(line_id) for line_id, line in geom.lines.items() if str(line.type).upper() == "VALLEY"),
        "penetration": set(str(v) for v in geom.penetration_faces.keys()),
    }


def _require_id(validators: Mapping[str, set[str]], id_type: str, value: str) -> None:
    allowed = validators.get(id_type)
    if allowed is not None and value not in allowed:
        raise ConfirmationValidationError(f"unknown {id_type} id: {value!r}")


def _source_id(source_ids: Sequence[str], index: int, label: str) -> str:
    try:
        return source_ids[index]
    except IndexError as exc:
        raise ConfirmationValidationError(f"confirmed {label} candidate has no source id") from exc


def _first_text(params: Mapping[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = params.get(key)
        if value not in (None, ""):
            return str(value)
    return None


def _valley_ids_from(params: Mapping[str, Any]) -> tuple[str, ...]:
    if "confirmed_valley_line_ids" in params:
        return tuple(str(v) for v in params.get("confirmed_valley_line_ids", ()) or ())
    if "valley_ids" in params:
        return tuple(str(v) for v in params.get("valley_ids", ()) or ())
    if "valley_line_ids" in params:
        return tuple(str(v) for v in params.get("valley_line_ids", ()) or ())
    if "valley_id" in params:
        return (str(params["valley_id"]),)
    if "valley_line_id" in params:
        return (str(params["valley_line_id"]),)
    return ()


def _label(params: Mapping[str, Any], fallback: str) -> str:
    value = params.get("label")
    return str(value) if value not in (None, "") else fallback


def _face_label(params: Mapping[str, Any], face_id: str, valley_ids: Sequence[str]) -> str:
    designator = params.get("designator") or face_id
    if len(valley_ids) == 1:
        side = params.get("repair_side") or params.get("side")
        return f"{designator} {side} {valley_ids[0]}" if side else f"{designator} {valley_ids[0]}"
    return f"{designator} multi-valley union"
