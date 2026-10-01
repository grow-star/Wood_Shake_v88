#!/usr/bin/env python3
"""Production caller for Module 3 scope comparison.

Confluence only: required scope is normalized by the production keying function;
carrier scope is the deterministic Carrier Parser Part-B summary; the frozen
comparison oracle assigns the 6-state result. No comparison logic is reimplemented here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Optional, Sequence

from module3_keying import key_and_normalize
from module3_comparison_oracle import build_comparison
# The ONE authority for narrowing a carrier keyed view to a single structure — the same function
# manual_carrier_entry itself uses when it restricts to one structure, so a per-structure carrier side
# built here is byte-identical in shape and semantics to the single-structure path.
from manual_carrier_entry import _restrict_to_structure


@dataclass(frozen=True)
class RequiredLineForComparison:
    item: str
    category_id: str
    qty: float
    unit: str
    # v77 DEFECT 5: the label authority ("user-defined" for a user-placed, user-labelled appurtenance).
    # key_and_normalize reads this to tell a user's own label apart from the generic category item so it
    # can group by label. Additive with a default, so every existing caller is unchanged.
    citation: Optional[str] = None


def _required_lines_with_item(lines: Iterable[Any]) -> Sequence[RequiredLineForComparison]:
    """Adapt Module 2 aggregate lines to the keying contract by surfacing .item."""
    out = []
    for line in lines:
        category_id = getattr(line, "category_id")
        out.append(RequiredLineForComparison(
            item=getattr(line, "item", None) or category_id,
            category_id=category_id,
            qty=float(getattr(line, "qty")),
            unit=getattr(line, "unit"),
            citation=getattr(line, "citation", None),
        ))
    return tuple(out)


def _affected_sf(module2_result: Any) -> float:
    for name in ("affected_SF_raw_total", "affected_sf_raw_total", "affected_SF", "affected_sf"):
        if hasattr(module2_result, name):
            return float(getattr(module2_result, name))
    raise ValueError("module2_result missing affected SF total")


def _aggregated_scope(module2_result: Any) -> Iterable[Any]:
    if hasattr(module2_result, "aggregated_scope"):
        return getattr(module2_result, "aggregated_scope")
    if isinstance(module2_result, Mapping) and "aggregated_scope" in module2_result:
        return module2_result["aggregated_scope"]
    raise ValueError("module2_result missing aggregated_scope")


def _aggregated_scope_by_structure(module2_result: Any) -> Sequence[Any]:
    """The per-structure required scope Module 2 already produces: ((structure_id, lines), ...), one
    entry per structure the USER SCOPED (built only from the user's confirmed events, grouped by each
    component's facet). Empty or single-entry for a single-structure roof, so the single-structure path
    below is unchanged."""
    if isinstance(module2_result, Mapping):
        return tuple(module2_result.get("aggregated_scope_by_structure", ()) or ())
    return tuple(getattr(module2_result, "aggregated_scope_by_structure", ()) or ())


def _structure_affected_sf(module2_result: Any) -> Mapping[str, float]:
    raw = (module2_result.get("structure_affected_SF", ()) if isinstance(module2_result, Mapping)
           else getattr(module2_result, "structure_affected_SF", ())) or ()
    return {str(sid): float(sf) for sid, sf in raw}


def _structure_facet_counts(module2_result: Any) -> Mapping[str, int]:
    raw = (module2_result.get("structure_facet_counts", ()) if isinstance(module2_result, Mapping)
           else getattr(module2_result, "structure_facet_counts", ())) or ()
    return {str(sid): int(n) for sid, n in raw}


def _carrier_view_for_structure(carrier_summary: Mapping[str, Any], structure_id: str) -> Mapping[str, Any]:
    """The carrier approved/excluded/unmapped views narrowed to ONE structure, via the same authority
    the single-structure restrict uses. A structure the carrier never wrote a line for comes back
    empty — every required item then renders MISSING_FROM_CARRIER, which is the argument, not an error."""
    ps = carrier_summary.get("per_structure") or {}
    return {
        "approved": _restrict_to_structure(ps.get("approved") or {}, structure_id, with_audit=False),
        "excluded": _restrict_to_structure(ps.get("excluded") or {}, structure_id, with_audit=True),
        "unmapped": _restrict_to_structure(ps.get("unmapped") or {}, structure_id, with_audit=True),
    }


def build_scope_comparison(module2_result: Any, carrier_summary: Optional[Mapping[str, Any]]) -> Mapping[str, Any]:
    """Build scope comparison from resolved Module 2 and Carrier Parser outputs."""
    if carrier_summary is None:
        required, required_totals = key_and_normalize(
            _required_lines_with_item(_aggregated_scope(module2_result)),
            _affected_sf(module2_result),
        )
        comparison = build_comparison(required, None)
        return {"status": "REQUIRED_SCOPE_ONLY", "required": required,
                "required_totals": required_totals, "scope_comparison": comparison}

    if carrier_summary.get("parser_status") == "NEEDS_CONFIRMATION":
        return {"status": "CARRIER_NEEDS_ESTIMATE_SELECTION",
                "reason": "carrier parser status requires resolved single estimate before comparison",
                "carrier_flags": tuple(carrier_summary.get("flags", ())),
                "duplicate_comparison_categories": tuple(carrier_summary.get("duplicate_comparison_categories", ())),
                "scope_comparison": None}

    required, required_totals = key_and_normalize(
        _required_lines_with_item(_aggregated_scope(module2_result)),
        _affected_sf(module2_result),
    )
    # v72 DEFECT 2: a FULL replacement (every scoped facet replaced, none repaired) flips the required
    # activity code for the non-shake components to REPLACE — they come off with the shakes anyway. A
    # repair or a mixed roof stays R&R for everything (conservative: only a clean full replacement
    # promotes to REPLACE). The always-R&R exceptions are enforced inside build_comparison.
    _repl = list(getattr(module2_result, "replacement_facets", ()) or ()) if not isinstance(module2_result, Mapping) else list(module2_result.get("replacement_facets", ()) or ())
    _rep = list(getattr(module2_result, "repair_facets", ()) or ()) if not isinstance(module2_result, Mapping) else list(module2_result.get("repair_facets", ()) or ())
    is_replacement = bool(_repl) and not _rep

    # PER-STRUCTURE COMPARISON (§5 covers what the USER scoped, not what the carrier scoped).
    # The scoped set is EXACTLY the structures Module 2 built components on (aggregated_scope_by_structure
    # is grouped by each component's facet, and components come only from the user's confirmed events).
    # Fires only with 2+ scoped structures; a single-structure roof (one entry, or an anonymous "")
    # falls straight through to the unchanged single path below and renders byte-identically.
    by_structure = [(str(sid), lines) for sid, lines in _aggregated_scope_by_structure(module2_result) if lines]
    if len(by_structure) >= 2:
        scoped_sids = [sid for sid, _ in by_structure]
        ps = carrier_summary.get("per_structure") or {}
        carrier_structs: set = set()
        for bucket in ("approved", "excluded", "unmapped"):
            carrier_structs |= set((ps.get(bucket) or {}).keys())
        matched = carrier_structs & set(scoped_sids)
        unmatched_carrier = sorted(s for s in carrier_structs if s not in set(scoped_sids))
        scoped_without_carrier = [sid for sid in scoped_sids if sid not in matched]
        # ASK, DO NOT GUESS: carrier lines name buildings that are not among the scoped structures WHILE
        # some scoped structures have no carrier lines at all — the two label sets do not line up (e.g.
        # carrier "Dwelling/Garage" vs geometry "ROOF1/ROOF2"). Comparing across that gap would pit one
        # building's required side against another building's approved side. Withhold and ask instead.
        if unmatched_carrier and scoped_without_carrier:
            return {"status": "CARRIER_NEEDS_STRUCTURE_MAPPING",
                    "reason": "carrier lines name structures that are not among the scoped buildings; "
                              "the structure mapping must be set before a comparison can be built",
                    "unmapped_carrier_structures": unmatched_carrier,
                    "scoped_structures_without_carrier": list(scoped_without_carrier),
                    "required": required, "required_totals": required_totals,
                    "scope_comparison": None}

        aff = _structure_affected_sf(module2_result)
        _fallback_sf = _affected_sf(module2_result)
        structure_comparisons = []
        for sid, lines in by_structure:
            req_sid, tot_sid = key_and_normalize(_required_lines_with_item(lines), aff.get(sid, _fallback_sf))
            carrier_sid = _carrier_view_for_structure(carrier_summary, sid)
            comp_sid = build_comparison(req_sid, carrier_sid, is_replacement=is_replacement)
            structure_comparisons.append({"structure_id": sid, "scope_comparison": comp_sid,
                                          "required": req_sid, "required_totals": tot_sid})
        # The top-level scope_comparison stays the POOLED comparison so any single-block consumer
        # (shake_dual, required_scope fallbacks) is unchanged; the renderer prefers structure_comparisons.
        pooled = build_comparison(required, carrier_summary, is_replacement=is_replacement)
        return {"status": "COMPARISON_READY", "required": required, "required_totals": required_totals,
                "scope_comparison": pooled, "structure_comparisons": structure_comparisons,
                "scoped_structures": scoped_sids, "multi_structure": True}

    comparison = build_comparison(required, carrier_summary, is_replacement=is_replacement)
    return {"status": "COMPARISON_READY", "required": required,
            "required_totals": required_totals, "scope_comparison": comparison}
