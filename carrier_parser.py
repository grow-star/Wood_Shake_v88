#!/usr/bin/env python3
"""Carrier Parser Part B — deterministic rule/contract production home."""

from shared_category_registry import (
    REGISTRY_28, REGISTRY_SET, REGISTRY_HASH, registry_fingerprint,
)

# =============================================================================
# 1. DETERMINISTIC RULE FUNCTIONS (the parser's layer-B logic; §5.4, §7.2)
# =============================================================================
def detect_platform(pricing_ref, xact_price_list):
    """§5.4 deterministic, field-only. CoreLogic OR Cotality 'Data Driven' -> SYMBILITY."""
    if xact_price_list:
        return "XACTIMATE"
    if pricing_ref and "Data Driven" in pricing_ref and \
       ("CoreLogic" in pricing_ref or "Cotality" in pricing_ref):
        return "SYMBILITY"
    return "UNKNOWN"     # CARRIER_NATIVE / UNKNOWN — not guessed from layout (§5.4)

def consolidate_RR(source_lines):
    """§7.2: keep the Replace/Install side (waste-included). Returns (kept_qty, mismatch)."""
    rr   = [s for s in source_lines if s["side"] == "RR"]
    rep  = [s for s in source_lines if s["side"] in ("REPLACE", "INSTALL")]
    rem  = [s for s in source_lines if s["side"] == "REMOVE"]
    if rr:                                   # single combined R&R line
        return rr[0]["qty"], False
    if rep:
        kept = rep[0]["qty"]
        # waste differential (Replace >= Remove) is EXPECTED, never a mismatch
        mismatch = bool(rem) and rep[0]["qty"] < rem[0]["qty"]
        return kept, mismatch
    if rem:
        return rem[0]["qty"], True           # remove-only with no replace -> flag
    return None, True

# §5.4 ADVISORY inference (v0.6): set inferred_platform ONLY from >=2 independent
# grammar signals of one family AND <2 of the other (conflict guard); cap MEDIUM.
SYMBILITY_SIGNALS = {"remove_replace_prefix","per_column","mat_lab_equ_columns",
                     "roofplan_recap","ld_debris_unit"}
XACTIMATE_SIGNALS = {"numbered_line_grammar","rr_remove_install",
                     "xact_recap_by_category","partial_price_list_token"}

def infer_platform(signals):
    """Advisory only. Returns (inferred_platform|None, inferred_confidence)."""
    sym = len(set(signals) & SYMBILITY_SIGNALS)
    xac = len(set(signals) & XACTIMATE_SIGNALS)
    if sym >= 2 and xac >= 2:        # conflict guard -> do not coin-flip
        return None, "UNKNOWN"
    if sym >= 2 and xac < 2:
        return "SYMBILITY", "MEDIUM"
    if xac >= 2 and sym < 2:
        return "XACTIMATE", "MEDIUM"
    return None, "UNKNOWN"           # one weak signal is not enough


# =============================================================================
# 2. PROVIDER-NEUTRAL EXTRACTED-FIELDS CONTRACT + PART-B PRODUCTION CALLER
# =============================================================================
# Provider-neutral boundary: any Layer-A extractor (Claude, GPT, Gemini, OCR,
# manual form, or future parser) must hand Part B this structured contract. Part B
# does not read PDFs, call AI, or know who produced the fields. It validates the
# shape, applies deterministic platform/R&R rules, quarantines advisory inference,
# and emits the carrier-side category summary consumed by the Comparison Builder.

LINE_COLLECTIONS = ("approved", "excluded", "unmapped", "out_of_scope")
REQUIRED_TOP_LEVEL_KEYS = (
    "carrier", "platform", "pricing_ref", "xact_price_list", "input_state",
    "parser_status", "property_address", "mailing_trap", "structures",
    "estimates", "approved", "excluded", "unmapped", "out_of_scope",
    "flags", "acknowledged", "reference_totals",
)

EXTRACTED_FIELDS_CONTRACT = {
    "top_level": REQUIRED_TOP_LEVEL_KEYS,
    "line_collections": LINE_COLLECTIONS,
    "line_shape": {
        "required": ("category_id", "qty", "unit", "op", "structure_id", "estimate_id"),
        "optional": ("subtype", "source_lines"),
    },
    "boundary": "provider-neutral Layer-A extraction output; deterministic Part-B input",
}


def validate_extracted_fields(extracted_fields):
    """Validate the neutral extracted-fields contract shape. Returns (ok, errors)."""
    errors = []
    if not isinstance(extracted_fields, dict):
        return False, ["extracted_fields must be a dict"]

    for key in REQUIRED_TOP_LEVEL_KEYS:
        if key not in extracted_fields:
            errors.append(f"missing required key: {key}")

    for coll in LINE_COLLECTIONS:
        value = extracted_fields.get(coll)
        if not isinstance(value, list):
            errors.append(f"{coll} must be a list")
            continue
        if coll == "approved":
            for i, line in enumerate(value):
                if not isinstance(line, dict):
                    errors.append(f"approved[{i}] must be a dict")
                    continue
                for req in EXTRACTED_FIELDS_CONTRACT["line_shape"]["required"]:
                    if req not in line:
                        errors.append(f"approved[{i}] missing {req}")
                if "source_lines" in line and not isinstance(line["source_lines"], list):
                    errors.append(f"approved[{i}].source_lines must be a list")

    if not isinstance(extracted_fields.get("carrier"), dict):
        errors.append("carrier must be a dict")
    if not isinstance(extracted_fields.get("structures", []), list):
        errors.append("structures must be a list")
    if not isinstance(extracted_fields.get("estimates", []), list):
        errors.append("estimates must be a list")
    if not isinstance(extracted_fields.get("flags", []), list):
        errors.append("flags must be a list")
    if not isinstance(extracted_fields.get("acknowledged", {}), dict):
        errors.append("acknowledged must be a dict")
    if not isinstance(extracted_fields.get("reference_totals", {}), dict):
        errors.append("reference_totals must be a dict")

    return not errors, errors


def _copy_line(line):
    return dict(line)


def _approved_dict(approved_lines):
    out = {}
    duplicates = []
    for line in approved_lines:
        cid = line["category_id"]
        entry = {"qty": line["qty"], "unit": line["unit"]}
        if cid in out:
            duplicates.append(cid)
            # Comparison Builder accepts one category entry. Preserve the first
            # deterministic entry and flag duplicates in caller metadata; estimate
            # selection belongs upstream/user confirmation, not this dict collapse.
            continue
        out[cid] = entry
    return out, sorted(set(duplicates))


def _excluded_dict(excluded_lines):
    out = {}
    for item in excluded_lines:
        if "category_id" in item:
            out[item["category_id"]] = {
                "reason": item.get("reason", "excluded"),
                "source_text": item.get("source_text", ""),
            }
    return out


def _unmapped_list(unmapped_lines):
    out = []
    for item in unmapped_lines:
        if isinstance(item, str):
            out.append(item)
        elif isinstance(item, dict):
            out.append(item.get("desc") or item.get("description") or str(item))
        else:
            out.append(str(item))
    return out


def build_carrier_scope_summary(extracted_fields):
    """Run deterministic Carrier Parser Part B over provider-neutral fields."""
    ok, errors = validate_extracted_fields(extracted_fields)
    if not ok:
        return {
            "parser_status": "MALFORMED_INPUT",
            "status": "MALFORMED_INPUT",
            "errors": errors,
            "approved": {},
            "excluded": {},
            "unmapped": [],
            "advisory": {},
        }

    fx = extracted_fields
    deterministic_platform = detect_platform(fx.get("pricing_ref"), fx.get("xact_price_list"))
    advisory_platform, advisory_confidence = infer_platform(fx.get("inferred_signals", []))

    approved_lines = []
    rr_mismatches = []
    for line in fx["approved"]:
        out_line = _copy_line(line)
        if out_line.get("source_lines"):
            kept, mismatch = consolidate_RR(out_line["source_lines"])
            if kept is not None and out_line.get("op") == "R&R":
                out_line["qty"] = kept
            if mismatch:
                rr_mismatches.append({
                    "category_id": out_line.get("category_id"),
                    "structure_id": out_line.get("structure_id"),
                    "estimate_id": out_line.get("estimate_id"),
                })
        approved_lines.append(out_line)

    approved, duplicate_categories = _approved_dict(approved_lines)
    flags = list(fx.get("flags") or [])
    if duplicate_categories and "comparison_duplicate_categories" not in flags:
        flags.append("comparison_duplicate_categories")
    if rr_mismatches and "rr_mismatch" not in flags:
        flags.append("rr_mismatch")

    summary = {
        "carrier": fx["carrier"],
        "platform": deterministic_platform,
        "parser_status": fx["parser_status"],
        "input_state": fx["input_state"],
        "property_address": fx["property_address"],
        "mailing_trap": fx["mailing_trap"],
        "structures": fx["structures"],
        "estimates": fx["estimates"],
        "approved": approved,
        "excluded": _excluded_dict(fx["excluded"]),
        "unmapped": _unmapped_list(fx["unmapped"]),
        "approved_lines": approved_lines,
        "excluded_lines": list(fx["excluded"]),
        "unmapped_lines": list(fx["unmapped"]),
        "out_of_scope_lines": list(fx["out_of_scope"]),
        "flags": flags,
        "acknowledged": fx["acknowledged"],
        "reference_totals": fx["reference_totals"],
        "registry_hash": registry_fingerprint(REGISTRY_28),
        "duplicate_comparison_categories": duplicate_categories,
        "rr_mismatches": rr_mismatches,
        "advisory": {
            "inferred_platform": advisory_platform,
            "inferred_confidence": advisory_confidence,
            "quarantined": True,
        },
    }
    if "inferred_platform" in fx:
        summary["advisory"]["fixture_inferred_platform"] = fx.get("inferred_platform")
        summary["advisory"]["fixture_inferred_confidence"] = fx.get("inferred_confidence")
        summary["advisory"]["fixture_inferred_basis"] = fx.get("inferred_basis")
    return summary
