#!/usr/bin/env python3
"""Scope Argument Builder caller.

Pure assembly seam: collects locked upstream facts into the input dictionary
consumed by the frozen Scope Argument Builder. This module authors no prose and
mutates no upstream output.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Optional, Sequence

from scope_argument_builder import ARGUMENT_PACK_FIELDS, build_argument_pack


def build_scope_argument(
    module1_result: Any,
    module2_result: Any,
    comparison_result: Optional[Mapping[str, Any]],
    carrier_summary: Optional[Mapping[str, Any]],
    verified_claim_info: Mapping[str, Any],
    photos: Optional[Sequence[Mapping[str, Any]]] = None,
    attachments: Optional[Sequence[Mapping[str, Any]]] = None,
    reference_tags: Optional[Sequence[str]] = None,
) -> Mapping[str, Any]:
    """Build the frozen argument_pack from real upstream outputs.

    Multi-estimate/unresolved comparison guard: when the comparison is absent or
    blocked by carrier estimate selection, no comparison or carrier summary is
    passed to the argument builder. That forces REQUIRED_SCOPE_ONLY mode and
    prevents any unresolved carrier acknowledgment/comparison claim.
    """
    resolved_comparison = _resolved_scope_comparison(comparison_result)
    resolved_carrier_summary = carrier_summary if resolved_comparison is not None else None

    inputs = {
        "verified_claim_info": dict(verified_claim_info),
        "m1_affected": _m1_affected_payload(module1_result, module2_result),
        "m2_scope": _m2_scope_payload(module2_result),
        "scope_comparison": resolved_comparison,
        "carrier_scope_summary": resolved_carrier_summary,
        "photos": list(photos or ()),
        "attachments": list(attachments or ()),
        "reference_tags": list(reference_tags or ()),
    }
    pack = build_argument_pack(inputs)
    _validate_argument_pack(pack)
    return {"status": "ARGUMENT_READY", "inputs": inputs, "argument_pack": pack}


def _resolved_scope_comparison(comparison_result: Optional[Mapping[str, Any]]) -> Optional[Mapping[str, Any]]:
    if not comparison_result:
        return None
    if comparison_result.get("status") == "CARRIER_NEEDS_ESTIMATE_SELECTION":
        return None
    comparison = comparison_result.get("scope_comparison", comparison_result)
    if not isinstance(comparison, Mapping):
        return None
    if comparison.get("mode") == "COMPARISON":
        return comparison
    if comparison_result.get("status") == "COMPARISON_READY":
        return comparison
    return None


def _m1_affected_payload(module1_result: Any, module2_result: Any) -> Mapping[str, Any]:
    if isinstance(module1_result, Mapping):
        return dict(module1_result)
    payload = {}
    for source, names in (
        (module1_result, ("affected_SF", "affected_sf", "affected_SF_raw_total", "affected_sf_raw_total")),
        (module2_result, ("affected_SF_raw_total", "affected_sf_raw_total", "affected_SF", "affected_sf")),
    ):
        for name in names:
            if hasattr(source, name):
                payload["affected_SF"] = float(getattr(source, name))
                return payload
    return payload


def _m2_scope_payload(module2_result: Any) -> Sequence[Mapping[str, Any]]:
    lines = _aggregated_scope(module2_result)
    out = []
    for line in lines:
        category_id = _field(line, "category_id")
        out.append({
            "category_id": category_id,
            "quantity": _field(line, "qty"),
            "qty": _field(line, "qty"),
            "unit": _field(line, "unit"),
            "item": _field(line, "item", category_id),
            "citation": _field(line, "gate", "module2"),
        })
    return tuple(out)


def _aggregated_scope(module2_result: Any) -> Iterable[Any]:
    if isinstance(module2_result, Mapping):
        return module2_result.get("aggregated_scope", ())
    return getattr(module2_result, "aggregated_scope", ())


def _field(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, Mapping):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _validate_argument_pack(pack: Mapping[str, Any]) -> None:
    expected = set(ARGUMENT_PACK_FIELDS)
    actual = set(pack)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise ValueError(f"argument_pack field mismatch; missing={missing}, extra={extra}")
