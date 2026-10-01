#!/usr/bin/env python3
"""Manual carrier-scope entry producer.

Converts user-confirmed Page-3 carrier rows into the same carrier_scope_summary
shape consumed by the Comparison Builder. No PDF parsing, no AI extraction, and
no deterministic Part-A/Part-B parsing happens here; this is a second producer
of the existing provider-neutral carrier-side contract.
"""

from __future__ import annotations

from collections import defaultdict
import re
from typing import Any, Iterable, Mapping, Optional

from shared_category_registry import REGISTRY_28, REGISTRY_SET, REGISTRY_HASH, registry_fingerprint
# ONE AUTHORITY for the Remove/Replace rule. consolidate_RR already encodes "keep the Replace/Install
# side, the Remove side is the same material coming off, Replace >= Remove is expected not a mismatch."
# The live path imports and USES it rather than re-implementing it — two copies drifting apart is how
# this project has shipped the same bug repeatedly. carrier_parser is NOT modified; it defines the rule.
from carrier_parser import consolidate_RR, detect_platform

# Display label carried into the rendered report so an adjuster comparing documents sees WHY one
# quantity replaces the carrier's two lines. This is a label, not the rule; the rule is consolidate_RR.
RR_PAIR_NOTE = "Remove + Install read as one carrier operation (Detach & Reset)."


_OP_CANON = {
    "R&R": "R_AND_R", "RR": "R_AND_R", "R_AND_R": "R_AND_R",
    "D&R": "DETACH_RESET", "DR": "DETACH_RESET", "DETACH_RESET": "DETACH_RESET",
    "REPLACE": "REPLACE", "REPLACEMENT": "REPLACE",
    "INSTALL": "INSTALL_ONLY", "INSTALL_ONLY": "INSTALL_ONLY", "LABOR_ONLY": "INSTALL_ONLY",
    "MATERIAL": "MATERIAL_ONLY", "MATERIAL_ONLY": "MATERIAL_ONLY",
    "REMOVE": "REMOVE", "REMOVAL": "REMOVE",
    "LABOR": "LABOR", "GENERAL_LABOR": "LABOR",
}


def _canon_op(op):
    return _OP_CANON.get(str(op or "").strip().upper(), str(op or "").strip().upper() or "R_AND_R")


def _partition_operations(lines):
    """v75/v76: a category+structure bucket can carry MORE THAN ONE carrier operation — e.g. a Detach &
    Reset (the existing shakes come off and go back on) PLUS a REPLACE for shakes broken during removal.
    Collapsing them to one number MUST lose a funded operation. This partitions by the ROW'S OPERATION
    (what page 3 now assigns after the folding fix) and NEVER sums across operations — quantities sum
    ONLY within the same operation. Separate Remove + Install lines (a carrier that did not pre-fold
    them) still reconcile to Detach & Reset here, so the engine is the ONE authority whether or not the
    pair arrived folded.

    Returns a list of {op, qty}. Length 1 = a single operation; the caller keeps the EXISTING
    single-number path unchanged so every existing report stays byte-identical. Length > 1 = a genuinely
    mixed category carried as separate operations.
    """
    by_op: dict[str, float] = defaultdict(float)
    removes = 0.0
    installs = 0.0
    for l in lines:
        op = _canon_op(l.get("op"))
        qty = float(l.get("qty") or 0)
        if op == "REMOVE":
            removes += qty
            continue
        if op == "INSTALL_ONLY":
            installs += qty
            continue
        by_op[op] += qty
    # separate Remove + Install lines reconcile to Detach & Reset (existing off and back on); leftovers
    # keep their own operation rather than being invented into something the carrier did not write.
    reset = min(removes, installs) if (removes > 0 and installs > 0) else 0.0
    if reset > 0:
        by_op["DETACH_RESET"] += reset
        removes -= reset
        installs -= reset
    if installs > 1e-9:
        by_op["INSTALL_ONLY"] += installs
    # v60 consolidation, preserved: a leftover explicit REMOVE beside a NEW-MATERIAL operation is the
    # SAME repair (remove + new material = R&R) — the removal is absorbed as evidence, never carried as
    # a separate quantity. A REPLACE whose removal is now explicitly funded becomes R&R. A REMOVE with
    # no new-material partner is a genuine remove-only line and stands on its own.
    if removes > 1e-9:
        if by_op.get("R_AND_R", 0) > 1e-9:
            pass  # removal absorbed into the existing R&R (qty is the replace side, waste-included)
        elif by_op.get("REPLACE", 0) > 1e-9:
            by_op["R_AND_R"] += by_op.pop("REPLACE")   # explicit remove + replace = R&R
        else:
            by_op["REMOVE"] += removes
    return [{"op": op, "qty": round(q, 4)} for op, q in by_op.items() if q > 1e-9]


def _line_is_remove(line: Mapping[str, Any]) -> bool:
    """A carrier line is the REMOVE side when any of its source_lines is marked REMOVE.

    Detection is by the REMOVE marker only (page 3 sets it from the 'Remove ' prefix, which QA
    confirmed correct on every real Devore line). It does NOT depend on an 'install' keyword: the
    real Xactimate partner is simply the same description with 'Remove ' stripped and carries no verb.
    """
    for s in line.get("source_lines", []) or []:
        if str(s.get("side", "")).upper() == "REMOVE":
            return True
    return False

_STATUS_TO_COLLECTION = {
    "Approved": "approved_lines",
    "Excluded": "excluded_lines",
    "Unmapped": "unmapped_lines",
    "Out of Scope": "out_of_scope_lines",
}

_COLLECTION_TO_KEYED = {
    "approved_lines": "approved",
    "excluded_lines": "excluded",
    "unmapped_lines": "unmapped",
    "out_of_scope_lines": "out_of_scope",
}

_REQUIRED_ROW_KEYS = ("category_id", "qty", "unit", "status")


def _header_value(verified_claim_info: Optional[Mapping[str, Any]], key: str, default: Any = None) -> Any:
    if not verified_claim_info:
        return default
    return verified_claim_info.get(key, default)


def _numeric_qty(value: Any, row_index: int) -> float:
    if isinstance(value, bool):
        raise ValueError(f"manual_rows[{row_index}].qty must be numeric >= 0")
    try:
        qty = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"manual_rows[{row_index}].qty must be numeric >= 0") from None
    if qty < 0:
        raise ValueError(f"manual_rows[{row_index}].qty must be numeric >= 0")
    return qty


def _source_lines_for_row(row: Mapping[str, Any], qty: float) -> list[dict[str, Any]]:
    source_lines = row.get("source_lines")
    if source_lines is not None:
        if not isinstance(source_lines, list):
            raise ValueError("source_lines must be a list when supplied")
        return [dict(item) for item in source_lines]
    note = row.get("note") or row.get("source_note") or row.get("source") or "manual carrier entry"
    return [{"side": "MANUAL", "qty": qty, "note": note}]


def _line_from_row(row: Mapping[str, Any], row_index: int) -> dict[str, Any]:
    for key in _REQUIRED_ROW_KEYS:
        if key not in row:
            raise ValueError(f"manual_rows[{row_index}] missing {key}")

    category_id = row["category_id"]
    if category_id not in REGISTRY_SET:
        raise ValueError(f"manual_rows[{row_index}].category_id unknown: {category_id}")

    qty = _numeric_qty(row["qty"], row_index)
    unit = row.get("unit")
    if not isinstance(unit, str) or not unit.strip():
        raise ValueError(f"manual_rows[{row_index}].unit must be non-empty")

    status = row.get("status")
    if status not in _STATUS_TO_COLLECTION:
        allowed = ", ".join(_STATUS_TO_COLLECTION)
        raise ValueError(f"manual_rows[{row_index}].status must be one of: {allowed}")

    line = {
        "category_id": category_id,
        "qty": qty,
        "unit": unit.strip(),
        "op": row.get("op") or "R&R",
        "structure_id": row.get("structure_id") or "roof",
        "estimate_id": row.get("estimate_id") or "manual_1",
        "source_lines": _source_lines_for_row(row, qty),
    }
    if row.get("subtype"):
        line["subtype"] = row["subtype"]
    if row.get("note"):
        line["note"] = row["note"]
    return line


# =============================================================================================
# DUPLICATES ARE A STRUCTURE QUESTION (Joseph's rule, binding)
# =============================================================================================
#   SAME STRUCTURE + SAME MATERIAL     -> COMBINE. One comparison line, quantities SUMMED.
#   SEPARATE STRUCTURES                -> KEEP SEPARATE. Carriers break line items out by structure
#                                         (dwelling vs detached garage); merging them is wrong.
#   GENUINELY AMBIGUOUS MULTI-ESTIMATE -> the hard gate stays. You cannot compare when you do not
#                                         know WHICH estimate.
#
# WHAT THIS REPLACED, AND WHY IT WAS A FIELD BUG
# ----------------------------------------------
# Both keying helpers used to do this:
#
#     key = (estimate_id, category_id)          # structure_id NOT in the key
#     if seen_by_estimate[key] > 1:
#         duplicates.add(category_id)
#         continue                              # <-- AND THE LINE WAS DISCARDED, NOT SUMMED
#
# Two consequences, one visible and one not:
#   VISIBLE  — `duplicates` set parser_status to NEEDS_CONFIRMATION, which module3_render_engine
#              treated as a hard gate and returned {"gated": True, "sections": {}}. A blank report.
#              Joseph hit this on a real claim: "Nothing showed up. Not even the material list."
#   INVISIBLE — the `continue` SILENTLY THREW AWAY the second line's quantity. Two ridge runs of
#              104.0 + 71.5 LF keyed as 104.0 LF. That is an under-scope hiding behind the visible
#              bug, and it would have survived a fix that only touched the render gate.
#
# It is not a corner case. Xactimate writes Remove/Additional as TWO lines for the same charge, so a
# full replacement triggers it BY CONSTRUCTION — Devore's real Travelers estimate does it four times
# over (hip/ridge runs; steep 10-12 R+A; steep >12 R+A; high roof R+A).
#
# ONE AUTHORITY. `_combine_by_structure` below is the ONLY place duplicate/merge policy is decided.
# Both `_keyed_quantity` and `_keyed_audit` delegate to it, because they had two copies of the same
# broken rule and that is exactly how this project has shipped the same bug repeatedly.
_MERGE_KEY_DOC = "(estimate_id, structure_id, category_id)"


def _line_key(line: Mapping[str, Any]) -> tuple[str, str, str]:
    """The identity of a carrier line for merge purposes. STRUCTURE IS PART OF IT."""
    return (str(line.get("estimate_id") or "manual_1"),
            str(line.get("structure_id") or "roof"),
            str(line["category_id"]))


def _combine_by_structure(lines: Iterable[Mapping[str, Any]], *, with_audit: bool):
    """Merge carrier lines on (estimate_id, structure_id, category_id). NOTHING IS DISCARDED.

    Returns (keyed, duplicate_categories, unit_conflicts, per_structure).

    THE DISCRIMINATOR IS THE REMOVE SIDE, NOT THE LINE COUNT (Joseph's rule, binding):
    * SAME key, SAME unit, NO Remove side -> genuine duplicate. Quantities SUMMED, source_lines
      UNIONED, NO flag. Two ridge runs 104.0 + 71.5 LF -> 175.5. This is v59 behaviour, unchanged.
    * SAME key, SAME unit, ONE Remove side + its partner -> ONE R&R operation, NOT two quantities.
      They are NEVER added. The shared consolidate_RR keeps the Replace/Install side (waste-included);
      the Remove side is retained as evidence in source_lines. REMOVE 4.32 + partner 5.00 -> 5.00.
    * SAME key, DIFFERENT unit -> a REAL conflict. Not summed: 104 LF + 3 EA has no meaning. Surfaced
      as a unit conflict for review, consistent with module3_keying.key_and_normalize, which raises
      on the same condition. Both lines are retained in *_lines so nothing is lost.
    * DIFFERENT structure -> NOT a duplicate. Kept separate and never flagged.

    Pair detection is CATEGORY-AGNOSTIC (applies to STEEP_CHARGE, HIGH_SLOPE_CHARGE, shakes, any
    category) and does NOT depend on an 'install' verb — see `_line_is_remove`.

    `keyed` stays keyed by category_id, because that is the shape the comparison consumes and this
    build does not change that contract. When one category appears under SEVERAL structures, the
    keyed entry carries the structure the XML represents — resolved by the caller, which knows which
    structure is in scope; see `_select_in_scope_structure`. `per_structure` preserves the full
    breakdown so nothing is invisible.
    """
    # PASS 1 — bucket lines by key, preserving first-seen order. The pair-vs-duplicate decision needs
    # the WHOLE group at once (is there a Remove side?), so it cannot be made line-by-line.
    buckets: dict[tuple[str, str, str], list[Mapping[str, Any]]] = {}
    order: list[tuple[str, str, str]] = []
    for line in lines:
        key = _line_key(line)
        if key not in buckets:
            buckets[key] = []
            order.append(key)
        buckets[key].append(line)

    merged: dict[tuple[str, str, str], dict[str, Any]] = {}
    unit_conflicts: list[dict[str, Any]] = []

    # PASS 2 — resolve each bucket.
    for key in order:
        grp = buckets[key]
        entry_unit = grp[0]["unit"]
        same_unit = [l for l in grp if l["unit"] == entry_unit]
        for l in grp:
            if l["unit"] != entry_unit:
                # DO NOT SUM ACROSS UNITS. Surface it; never invent a combined quantity.
                unit_conflicts.append({
                    "category_id": key[2], "structure_id": key[1], "estimate_id": key[0],
                    "units": sorted({str(entry_unit), str(l["unit"])}),
                })

        removes = [l for l in same_unit if _line_is_remove(l)]
        others = [l for l in same_unit if not _line_is_remove(l)]

        entry: dict[str, Any] = {
            "unit": entry_unit, "structure_id": key[1], "estimate_id": key[0],
            "merged_line_count": len(same_unit),
        }
        if with_audit:
            entry["op"] = grp[0]["op"]
            entry["source_lines"] = [s for l in same_unit for s in list(l.get("source_lines", []))]

        # v75: does this category carry MORE THAN ONE carrier operation (e.g. Detach & Reset PLUS new
        # material)? If so, keep each operation separate — collapsing them to one number is the field
        # bug. A single operation falls through to the EXISTING path below, unchanged, so every existing
        # single-operation report stays byte-identical.
        operations = _partition_operations(same_unit)
        if len(operations) > 1:
            entry["operations"] = operations
            entry["qty"] = operations[0]["qty"]          # legacy fallback; multi-op readers use operations
            entry["rr_ambiguous"] = True                 # mixed operations -> surface on page 3 for review
            merged[key] = entry
            continue

        if not removes:
            # GENUINE duplicate (or a single line): SUM. v59 behaviour, must not regress.
            entry["qty"] = round(sum(float(l["qty"]) for l in same_unit), 4)
        else:
            # R&R PAIR: delegate the keep-which-quantity decision to the ONE shared authority. The
            # non-Remove partner IS the Replace side (structural, not verb-based); consolidate_RR then
            # keeps it and flags only when a Remove exceeds its Replace (a real anomaly, surfaced).
            sides = ([{"side": "REMOVE", "qty": float(l["qty"])} for l in removes]
                     + [{"side": "REPLACE", "qty": float(l["qty"])} for l in others])
            kept, mismatch = consolidate_RR(sides)
            entry["qty"] = round(float(kept), 4) if kept is not None else 0.0
            entry["rr_pair"] = True
            entry["pair_note"] = RR_PAIR_NOTE
            entry["removed_qty"] = round(sum(float(l["qty"]) for l in removes), 4)
            if not (len(removes) == 1 and len(others) == 1):
                # Not the clean 1-Remove + 1-partner shape. consolidate_RR still keeps a Replace side
                # deterministically and never sums a Remove, but the shape is unusual — surface it.
                entry["rr_ambiguous"] = True
            if mismatch:
                # Remove exceeded Replace (or Remove-only). Do NOT silently pick the larger — flag it.
                entry["rr_anomaly"] = True

        merged[key] = entry

    per_structure: dict[str, list[dict[str, Any]]] = {}
    for key in order:
        entry = merged[key]
        per_structure.setdefault(entry["structure_id"], []).append({"category_id": key[2], **entry})

    # A category is only a genuine "duplicate" worth surfacing when the SAME category appears under
    # MORE THAN ONE STRUCTURE. Within one structure it was merged, which is the correct answer and
    # needs no flag. Across structures it is not a duplicate either — it is two structures — so this
    # is reported for transparency and NEVER used to gate.
    by_category: dict[str, set[str]] = {}
    for key in order:
        by_category.setdefault(key[2], set()).add(key[1])
    multi_structure = sorted(c for c, s in by_category.items() if len(s) > 1)

    keyed: dict[str, dict[str, Any]] = {}
    for key in order:
        keyed.setdefault(key[2], {k: v for k, v in merged[key].items()})
    return keyed, multi_structure, unit_conflicts, per_structure


def _keyed_quantity(lines: Iterable[Mapping[str, Any]]):
    return _combine_by_structure(lines, with_audit=False)


def _keyed_audit(lines: Iterable[Mapping[str, Any]]):
    return _combine_by_structure(lines, with_audit=True)


def _estimate_entries(collections: Mapping[str, list[dict[str, Any]]]) -> list[dict[str, str]]:
    seen: dict[str, dict[str, str]] = {}
    for lines in collections.values():
        for line in lines:
            estimate_id = line.get("estimate_id") or "manual_1"
            seen.setdefault(estimate_id, {"estimate_id": estimate_id, "estimate_name": estimate_id})
    return [seen[key] for key in sorted(seen)]


def _select_in_scope_structure(structures: list[str],
                               verified_claim_info: Optional[Mapping[str, Any]]) -> str:
    """WHICH structure the EagleView XML represents — i.e. the one with a required side.

    NEVER GUESSED WHEN IT MATTERS. With one structure there is nothing to decide and the common case
    stays frictionless. With several, page 3 REQUIRES the human to assert which one the roof scope
    represents, and passes it here as verified_claim_info['roof_structure_id'] — the tool proposes,
    the human asserts, exactly as with the exposed/damaged transition gate.

    The fallback below only runs if a caller supplies several structures without an assertion (a
    hand-built payload; the UI cannot do it). It prefers a conventional dwelling name and otherwise
    takes the first sorted id, so behaviour stays deterministic rather than arbitrary."""
    if len(structures) == 1:
        return structures[0]
    asserted = _header_value(verified_claim_info, "roof_structure_id")
    if asserted and str(asserted) in structures:
        return str(asserted)
    for preferred in ("roof", "dwelling", "DWELLING", "main", "Roof1"):
        if preferred in structures:
            return preferred
    return structures[0]


def _restrict_to_structure(per_structure: Mapping[str, list[Mapping[str, Any]]],
                           structure_id: str, *, with_audit: bool) -> dict[str, dict[str, Any]]:
    """The keyed view narrowed to the one structure that has a required side."""
    keyed: dict[str, dict[str, Any]] = {}
    for entry in per_structure.get(structure_id, ()):  # type: ignore[union-attr]
        item = {"qty": entry["qty"], "unit": entry["unit"],
                "structure_id": entry["structure_id"], "estimate_id": entry["estimate_id"],
                "merged_line_count": entry["merged_line_count"]}
        # Carry R&R-pair metadata AND the v75 multi-operation split so both stay intact after narrowing
        # to one structure. v76 DEFECT 6: `operations` was omitted here, so any estimate with a second
        # structure silently collapsed a category's operation split back to one number — the same bug
        # v75 fixed, reappearing on the multi-structure path. ONE AUTHORITY: this narrowing must preserve
        # exactly what _combine_by_structure (via _partition_operations) produced.
        for opt in ("rr_pair", "pair_note", "removed_qty", "rr_ambiguous", "rr_anomaly", "operations"):
            if opt in entry:
                item[opt] = list(entry[opt]) if opt == "operations" else entry[opt]
        if with_audit:
            item["op"] = entry.get("op")
            item["source_lines"] = list(entry.get("source_lines", []))
        keyed.setdefault(str(entry["category_id"]), item)
    return keyed


def _no_haul_off_gap(descriptions):
    """v74 PART 1/3 — the ONE conditional debris rule, driven by the TEAR-OFF LINE'S OWN WORDING
    (Joseph, binding). The roof debris gap is claimed ONLY when the tear-off line EXPLICITLY says it
    excludes haul-off (a literal "(no haul off)") AND there is no debris line to cover the estimate:

        tear-off INCLUDES haul-off (or says nothing)  -> the roof debris is inside the tear-off (or the
                                                         "-" activity code / RFG ARMV>). NO roof gap,
                                                         whether or not a debris line exists.
        tear-off says "(no haul off)" + debris line   -> the debris line covers the whole estimate. NO gap.
        tear-off says "(no haul off)" + NO debris line -> REAL GAP: the roof debris is unfunded.

    SILENCE IS NEVER EVIDENCE OF A GAP: if the tear-off line says nothing about haul-off, the tool says
    nothing. Claiming a gap the carrier funded inside the line item is the failure class this project has
    spent the most builds eliminating. `descriptions` is every carrier line (all dispositions), since a
    dumpster line is often out of scope."""
    tearoff_excludes_haul = debris_present = False
    for d in (descriptions or []):
        low = str(d or "").lower()
        if _ROOF_TEAROFF_LINE.search(low) and _EXPLICIT_NO_HAUL.search(low):
            tearoff_excludes_haul = True
        if _DEBRIS_LINE.search(low):
            debris_present = True
    if tearoff_excludes_haul and not debris_present:
        return ("The roof tear-off line is written without haul-off (\u201cno haul off\u201d) and the "
                "estimate contains no debris disposal line (DEBRIS_DISPOSAL). The removed roof covering "
                "produces debris that must be hauled and disposed; on this estimate that disposal is "
                "unfunded.")
    return None


# The roof-covering removal line: a tear-off / removal of shakes, shingles, wood or the roof itself
# (or Xactimate's tear-off code RFG ARMV). Its own wording is what decides haul-off status.
_ROOF_TEAROFF_LINE = re.compile(
    r"(?:tear[\s-]*off|\bremov(?:e|al)\b).{0,60}(?:shake|shingle|wood|roof|comp)"
    r"|(?:shake|shingle|wood|comp).{0,40}(?:tear[\s-]*off)"
    r"|\brfg\s*armv", re.I)
# EXPLICIT exclusion only — a literal "(no haul off)" / "without haul" / "less haul". Nothing implicit.
_EXPLICIT_NO_HAUL = re.compile(r"\bno\s*haul|without\s*haul|w/?o\s*haul|less\s*haul|excl\w*\s*haul", re.I)
# A standalone debris / disposal line (NOT the tear-off's own "(no haul off)" wording, which carries no
# "debris"/"dumpster"/"dump fee").
_DEBRIS_LINE = re.compile(r"dumpster|debris|dump\s*fee|debris\s*disposal", re.I)


def mixed_operation_categories(rows):
    """v75: which categories the user's carrier rows resolve to MORE THAN ONE operation on — i.e. the
    engine cannot read them as a single pair and will split them (Detach & Reset vs new material). The
    page-3 confirmation surfaces these so the user sees the ambiguity BEFORE the report is delivered,
    instead of discovering a lost operation afterward. One authority: the same _partition_operations
    the approved side uses. Returns a list of {category_id, structure_id, operations:[{op,qty}]}."""
    from collections import defaultdict
    buckets: dict = defaultdict(list)
    for r in (rows or []):
        cat = (r.get("category_id") if isinstance(r, dict) else None)
        if not cat:
            continue
        struct = r.get("structure_id") or "roof"
        buckets[(struct, cat)].append(r)
    out = []
    for (struct, cat), lines in buckets.items():
        ops = _partition_operations(lines)
        if len(ops) > 1:
            out.append({"category_id": cat, "structure_id": struct, "operations": ops})
    return out


def build_carrier_summary_from_manual_entry(
    manual_rows: Iterable[Mapping[str, Any]],
    verified_claim_info: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """Build a confirmed carrier_scope_summary from user-confirmed rows.

    The rows are the confirmed output of the Page-3 carrier-scope review table.
    They may have been typed manually or prefilled by another detector/parser and
    then confirmed by the user. This function performs validation and contract
    shaping only; it does not parse documents or infer scope.
    """
    if manual_rows is None:
        raise ValueError("manual_rows must be an iterable of row dictionaries")

    collections = {name: [] for name in _COLLECTION_TO_KEYED}
    for i, row in enumerate(manual_rows):
        if not isinstance(row, Mapping):
            raise ValueError(f"manual_rows[{i}] must be a mapping")
        line = _line_from_row(row, i)
        collections[_STATUS_TO_COLLECTION[row["status"]]].append(line)

    approved, dup_approved, uc_approved, ps_approved = _keyed_quantity(collections["approved_lines"])
    excluded, dup_excluded, uc_excluded, ps_excluded = _keyed_audit(collections["excluded_lines"])
    unmapped, dup_unmapped, uc_unmapped, ps_unmapped = _keyed_audit(collections["unmapped_lines"])
    out_of_scope, dup_out, uc_out, ps_out = _keyed_audit(collections["out_of_scope_lines"])
    multi_structure_categories = sorted(set(dup_approved + dup_excluded + dup_unmapped + dup_out))
    unit_conflicts = uc_approved + uc_excluded + uc_unmapped + uc_out

    all_lines = [line for lines in collections.values() for line in lines]
    structures = sorted({str(line.get("structure_id") or "roof") for line in all_lines}) or ["roof"]
    in_scope_structure = _select_in_scope_structure(structures, verified_claim_info)

    # THIS TOOL COMPUTES ONE ROOF FROM ONE EagleView XML. If the estimate also covers a detached
    # garage, those lines have an APPROVED side and NO REQUIRED side. Comparing them would have the
    # tool asserting a gap it cannot justify — the exact failure avoided everywhere else in this
    # project (see: non-roof items stay out of the registry permanently). So they are ACKNOWLEDGED,
    # OUT OF SCOPE: named, counted, and never given a fabricated required side.
    out_of_scope_structures = [
        {"structure_id": s,
         "line_count": sum(1 for line in all_lines if str(line.get("structure_id") or "roof") == s),
         "reason": "ACKNOWLEDGED_OUT_OF_SCOPE_STRUCTURE",
         "detail": "the roof scope is computed from one EagleView XML, which represents "
                   f"{in_scope_structure!r}; this structure has no required side and is not compared"}
        for s in structures if s != in_scope_structure
    ]
    if out_of_scope_structures:
        # Keep only the in-scope structure in the KEYED views the comparison consumes. The raw
        # *_lines below are untouched, so nothing is hidden — only the comparison is narrowed.
        approved = _restrict_to_structure(ps_approved, in_scope_structure, with_audit=False)
        excluded = _restrict_to_structure(ps_excluded, in_scope_structure, with_audit=True)
        unmapped = _restrict_to_structure(ps_unmapped, in_scope_structure, with_audit=True)
        out_of_scope = _restrict_to_structure(ps_out, in_scope_structure, with_audit=True)

    flags = []
    parser_status = "MANUAL_CONFIRMED"

    # NEEDS_CONFIRMATION MEANS MULTI-**ESTIMATE** SELECTION AND NOTHING ELSE.
    # Per the parser spec it is the one legitimate hard gate: a PDF carrying several NAMED ESTIMATES
    # where the parser must not pick which to compare against. It used to be reused for "the same
    # category appears twice in one estimate", which is an entirely normal Xactimate Remove/Additional
    # pair — a completely different condition, and the reason a routine estimate blanked the report.
    # That reuse is gone. The true multi-estimate gate is UNCHANGED and must stay.
    estimates = _estimate_entries(collections) or [{"estimate_id": "manual_1", "estimate_name": "manual_1"}]
    if len(estimates) > 1:
        flags.append("multi_estimate_selection_required")
        parser_status = "NEEDS_CONFIRMATION"

    if unit_conflicts:
        # A real conflict: same structure, same category, different units. NOT summed, NOT gated —
        # surfaced for review. Gating here would re-create the bug this build exists to fix.
        flags.append("comparison_unit_conflict")
    if out_of_scope_structures:
        flags.append("structures_out_of_scope_acknowledged")
    if multi_structure_categories:
        # Transparency only. A category appearing under two structures is NOT a duplicate, and this
        # flag NEVER gates.
        flags.append("category_present_in_multiple_structures")

    # R&R PAIR TRANSPARENCY. When a Remove line and its partner were read as one operation, the
    # carrier wrote two lines and we show one. Surface it so an adjuster comparing documents can see
    # WHY the quantities differ from a naive sum. Never gates. Read from the compared (approved) view.
    rr_consolidations = [
        {"category_id": cat, "kept_qty": e["qty"], "removed_qty": e.get("removed_qty"),
         "pair_note": e.get("pair_note"), "anomaly": bool(e.get("rr_anomaly"))}
        for cat, e in approved.items() if e.get("rr_pair")
    ]
    if rr_consolidations:
        flags.append("rr_pair_consolidated")
    if any(c["anomaly"] for c in rr_consolidations):
        # A Remove side exceeded its Replace side — surfaced, not silently resolved.
        flags.append("rr_remove_exceeds_replace")

    carrier_value = _header_value(verified_claim_info, "carrier", "MANUAL")
    property_address = _header_value(verified_claim_info, "loss_address",
                                     _header_value(verified_claim_info, "property_address", ""))
    # v72 DEFECT 3: platform detection has been built, tested, and never fired in production — the live
    # path hardcoded "MANUAL". Wire the deterministic §5.4 detector here so the activity-code argument
    # uses the RIGHT platform vocabulary: a price list -> XACTIMATE; CoreLogic/Cotality "Data Driven"
    # -> SYMBILITY; otherwise UNKNOWN (never guessed from layout — the report then says nothing
    # platform-specific rather than defaulting to Xactimate).
    platform = detect_platform(
        _header_value(verified_claim_info, "pricing_ref", ""),
        _header_value(verified_claim_info, "price_list",
                      _header_value(verified_claim_info, "xact_price_list", "")),
    )

    return {
        "carrier": {"value": carrier_value, "family": carrier_value, "confidence": "USER_CONFIRMED"},
        "platform": platform,
        "parser_status": parser_status,
        "input_state": "MANUAL_ENTRY",
        "property_address": property_address,
        "mailing_trap": None,
        "structures": structures,
        "in_scope_structure": in_scope_structure,
        "out_of_scope_structures": out_of_scope_structures,
        "estimates": estimates,
        "approved": approved,
        "excluded": excluded,
        "unmapped": unmapped,
        "out_of_scope": out_of_scope,
        "approved_lines": collections["approved_lines"],
        "excluded_lines": collections["excluded_lines"],
        "unmapped_lines": collections["unmapped_lines"],
        "out_of_scope_lines": collections["out_of_scope_lines"],
        "flags": flags,
        "acknowledged": {"wood_shake_repair": "SHAKE_FIELD_RR" in approved},
        # v72 DEFECT 2 (no-haul-off): stated §5 gaps derived from the carrier's own lines (not required
        # lines). Empty when none apply, so existing reports are unchanged.
        "stated_gaps": [g for g in (_no_haul_off_gap(
            (verified_claim_info or {}).get("carrier_line_descriptions")),) if g],
        "reference_totals": {},
        "registry_hash": registry_fingerprint(REGISTRY_28),
        # Retained key, corrected meaning. It NO LONGER means "this category appeared twice and was
        # discarded" — same-structure repeats are now SUMMED. It lists categories present under MORE
        # THAN ONE STRUCTURE, and it never gates.
        "duplicate_comparison_categories": multi_structure_categories,
        "unit_conflicts": unit_conflicts,
        "rr_consolidations": rr_consolidations,
        "per_structure": {"approved": ps_approved, "excluded": ps_excluded,
                          "unmapped": ps_unmapped, "out_of_scope": ps_out},
        "advisory": {
            "inferred_platform": None,
            "inferred_confidence": "UNKNOWN",
            "quarantined": True,
        },
    }
