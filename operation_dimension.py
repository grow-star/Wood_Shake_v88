#!/usr/bin/env python3
"""
OPERATION DIMENSION (CORE) — additive layer
===========================================
Authority: Wood_Shake_Operation_Dimension_Spec_v0_1.md (§1 normalization + cost model,
§2 required-operation defaults, §3 comparison overlay). This module is ADDITIVE:

  * It contains NO Module 1 / Module 2 math, NO geometry, NO quantity/area.
  * It contains NO pricing and NO coverage/owed/underpaid language. `operation_delta`
    is a descriptive list of cost COMPONENTS (what a proper operation includes), never
    a dollar figure and never a coverage statement (spec §3.2, §5).
  * It only tells the Comparison Builder how to normalize a carrier operation, what the
    required operation defaults to, and — for a line that would otherwise be MATCHED —
    whether an operation mismatch should re-route it to OPERATION_DIFFERENCE (§3.3–§3.5).

Design guarantee (additivity): a line is only ever "rescued" MATCHED -> OPERATION_DIFFERENCE
when BOTH the required and carrier operations are KNOWN (non-null, non-UNKNOWN_OP) AND they
differ. When either side is absent or UNKNOWN_OP the operation is treated as non-divergent
and HELD (the §1.3 "never guessed / never auto-stated" discipline). This is exactly what
keeps every existing MATCHED case (implicit R&R / no operation asserted) MATCHED.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# §1.1 Canonical operation set
# ---------------------------------------------------------------------------
R_AND_R = "R_AND_R"
REPLACE = "REPLACE"
REMOVE = "REMOVE"
TEAR_OFF = "TEAR_OFF"
INSTALL_ONLY = "INSTALL_ONLY"
DETACH_RESET = "DETACH_RESET"
MATERIAL_ONLY = "MATERIAL_ONLY"
UNKNOWN_OP = "UNKNOWN_OP"           # held for user confirmation; never guessed, never auto-stated

CANONICAL_OPS = frozenset({
    R_AND_R, REPLACE, REMOVE, TEAR_OFF, INSTALL_ONLY, DETACH_RESET, MATERIAL_ONLY,
})

# neutral display labels (scope language only — no coverage terms)
OP_LABEL = {
    R_AND_R: "Remove & Replace",
    REPLACE: "Replace",
    REMOVE: "Remove",
    TEAR_OFF: "Tear-off",
    INSTALL_ONLY: "Install only",
    DETACH_RESET: "Detach & Reset",
    MATERIAL_ONLY: "Material only",
    UNKNOWN_OP: "Unspecified",
}

# ---------------------------------------------------------------------------
# §1.2 Cost-component decomposition  (the machine-usable form of §1.1)
# operation_delta reads the difference of these sets. NOT pricing.
# ---------------------------------------------------------------------------
COST_COMPONENTS = {
    R_AND_R:       frozenset({"remove_existing", "dispose", "material_new", "install_labor"}),
    REPLACE:       frozenset({"material_new", "install_labor", "dispose"}),
    REMOVE:        frozenset({"remove_existing", "dispose"}),
    TEAR_OFF:      frozenset({"remove_existing", "dispose"}),
    INSTALL_ONLY:  frozenset({"install_labor"}),
    DETACH_RESET:  frozenset({"remove_existing", "careful_handling_store", "install_labor"}),
    MATERIAL_ONLY: frozenset({"material_new"}),
}

# per-operation flags exactly per §1.2 table
OP_FLAGS = {
    R_AND_R:       (),
    REPLACE:       ("material_new",),
    REMOVE:        ("salvage_intent",),
    TEAR_OFF:      ("destructive_removal",),
    INSTALL_ONLY:  ("material_assumed_present", "no_careful_handling"),
    DETACH_RESET:  ("reuse_material", "salvage_intent"),
    MATERIAL_ONLY: ("material_only",),
}

# Deterministic emit order for operation_delta. The flagship divergence the spec exists
# to surface is the MISSING MATERIAL (§0), so material_new leads, then disposal, then the
# removal/handling/labor components. This yields the spec's thrice-stated flagship literal
# R_AND_R vs DETACH_RESET -> ["material_new","dispose"] exactly. For other pairs the SET is
# authoritative (spec §7.3 writes "or per §1.2" for the non-flagship examples).
_COMPONENT_EMIT_ORDER = (
    "material_new", "dispose", "remove_existing", "careful_handling_store", "install_labor",
)

COMPONENT_LABEL = {
    "remove_existing": "removal of existing material",
    "careful_handling_store": "careful handling and storage",
    "dispose": "disposal",
    "material_new": "new material",
    "install_labor": "installation labor",
}


# ---------------------------------------------------------------------------
# §1.3 Normalization — dialect -> canonical (deterministic; never guessed)
# ---------------------------------------------------------------------------
# Xactimate activity codes. Note "R&R" (combined) vs single "R" (Detach & Reset) are
# distinct exact keys — matched by exact string, never by prefix.
_XACT_CODE = {
    "R&R": R_AND_R,
    "+": REPLACE,
    "-": REMOVE, "\u2212": REMOVE,        # ASCII hyphen and Unicode minus both map to REMOVE
    "I": INSTALL_ONLY,
    "R": DETACH_RESET,
    "M": MATERIAL_ONLY,
}

# Symbility words (case/space-insensitive on lookup)
_SYMBILITY_WORD = {
    "replace (w/ removal)": R_AND_R,
    "replace w/ removal": R_AND_R,
    "remove & replace": R_AND_R,
    "remove and replace": R_AND_R,
    "r&r": R_AND_R,
    "replace": REPLACE,
    "remove": REMOVE,
    "tear off": TEAR_OFF,
    "tear-off": TEAR_OFF,
    "tearoff": TEAR_OFF,
    "install only": INSTALL_ONLY,
    "install": INSTALL_ONLY,
    "detach & reset": DETACH_RESET,
    "detach and reset": DETACH_RESET,
    "detach/reset": DETACH_RESET,
    "material only": MATERIAL_ONLY,
    "material": MATERIAL_ONLY,
}


def normalize_operation(op_label):
    """Map a single carrier activity code / word to the canonical set. Unknown/ambiguous
    -> UNKNOWN_OP (never guessed). Returns UNKNOWN_OP for None/empty."""
    if op_label is None:
        return UNKNOWN_OP
    raw = str(op_label).strip()
    if not raw:
        return UNKNOWN_OP
    if raw in CANONICAL_OPS:                       # already canonical
        return raw
    if raw in _XACT_CODE:                          # exact Xactimate code (case-sensitive: I vs i etc.)
        return _XACT_CODE[raw]
    key = raw.lower()
    if key in _SYMBILITY_WORD:
        return _SYMBILITY_WORD[key]
    # a bare "r&r"/"rr" spelled in mixed case
    if key in ("r&r", "rr"):
        return R_AND_R
    return UNKNOWN_OP


# ---------------------------------------------------------------------------
# §1.3 Remove + Install pairing (Option A)
# ---------------------------------------------------------------------------
# When a carrier's line composition (source_lines) is REMOVE + INSTALL/REPLACE with matching
# quantity and NO material line, the EFFECTIVE operation is Detach & Reset (labor-only reuse),
# regardless of the stated op label — this is the "silent divergence" the spec targets. If a
# Material line is also present, the effective operation is R&R. The raw lines are preserved by
# the caller (source_detail); this function never silently collapses to R&R.
_SIDE_ALIASES = {
    "remove": "REMOVE",
    "install": "INSTALL",
    "replace": "REPLACE",
    "rr": "RR",
    "r&r": "RR",
    "material": "MATERIAL",
    "mat": "MATERIAL",
    "labor": "LABOR",
    "dispose": "DISPOSE",
    "disposal": "DISPOSE",
}


def _side(name):
    if name is None:
        return None
    return _SIDE_ALIASES.get(str(name).strip().lower(), str(name).strip().upper())


def _qty_match(a, b, rel=0.02, floor=0.01):
    try:
        a = float(a); b = float(b)
    except (TypeError, ValueError):
        return False
    if a == b:
        return True
    diff = abs(a - b)
    base = max(abs(a), abs(b), 1e-9)
    return diff <= floor or (diff / base) <= rel


def infer_effective_operation(op_label, source_lines):
    """Derive the effective canonical carrier operation for ONE category from its op label
    and its source_lines (list of {"side","qty"}), applying §1.3 Option A.

    Returns (effective_op, basis) where basis is a short machine tag describing how it was
    determined ("label" | "pairing_detach_reset" | "pairing_r_and_r" | "combined_rr" | ...).
    """
    sides = {}
    for s in (source_lines or []):
        side = _side(s.get("side") if isinstance(s, dict) else s)
        if side is None:
            continue
        sides.setdefault(side, []).append(s.get("qty") if isinstance(s, dict) else None)

    has_remove = "REMOVE" in sides
    has_install = ("INSTALL" in sides) or ("REPLACE" in sides)
    has_material = "MATERIAL" in sides
    has_rr = "RR" in sides

    if has_remove and has_install and not has_material:
        rq = sides["REMOVE"][0]
        iq = (sides.get("INSTALL") or sides.get("REPLACE") or [None])[0]
        if rq is None or iq is None or _qty_match(rq, iq):
            return DETACH_RESET, "pairing_detach_reset"          # Option A: labor-only reuse
        return UNKNOWN_OP, "pairing_qty_mismatch_held"           # ambiguous -> held, not guessed
    if has_remove and has_install and has_material:
        return R_AND_R, "pairing_r_and_r"                        # Option A: +material -> R&R
    if has_rr:
        return R_AND_R, "combined_rr"
    if has_material and not (has_remove or has_install):
        return MATERIAL_ONLY, "material_only_line"
    if has_remove and not (has_install or has_material):
        return REMOVE, "remove_only_line"
    if has_install and not (has_remove or has_material):
        return INSTALL_ONLY, "install_only_line"
    # no decisive composition -> trust the normalized label
    return normalize_operation(op_label), "label"


def carrier_operation_for_category(carrier_summary, category_id):
    """Effective carrier operation for a category, read from the carrier summary's raw
    approved_lines (which carry op + source_lines). Returns None when the carrier summary
    exposes no line-level operation data (e.g. the seed oracle's approved-dict-only fixture)
    — in which case no operation divergence can be asserted and the line stays as-is."""
    if not isinstance(carrier_summary, dict):
        return None
    lines = carrier_summary.get("approved_lines")
    if not lines:
        return None
    matched = [l for l in lines if isinstance(l, dict) and l.get("category_id") == category_id]
    if not matched:
        return None
    # aggregate source_lines across the category's approved lines (handles the two-line split too)
    src = []
    labels = []
    for l in matched:
        labels.append(l.get("op"))
        src.extend(l.get("source_lines") or [])
    # if lines split remove/install across separate approved entries with no source_lines,
    # synthesize sides from the op labels
    if not src and len(matched) > 1:
        for lbl in labels:
            n = normalize_operation(lbl)
            if n == REMOVE:
                src.append({"side": "REMOVE", "qty": None})
            elif n in (INSTALL_ONLY, REPLACE):
                src.append({"side": "INSTALL", "qty": None})
            elif n == MATERIAL_ONLY:
                src.append({"side": "MATERIAL", "qty": None})
    op, _basis = infer_effective_operation(labels[0] if labels else None, src)
    return op


# ---------------------------------------------------------------------------
# §2.1 Default required operation (prefill; user-confirmed value is authoritative)
# ---------------------------------------------------------------------------
_FLASHING_DEFAULT_RR = frozenset({
    "CHIMNEY_FLASH", "ENDWALL_FLASH", "STEP_FLASH", "TRANSITION_FLASH",
    "SKYLIGHT_FLASH", "VALLEY_METAL",
})


def default_required_operation(category_id):
    """§2.1 sensible prefill. SHAKE_FIELD_RR -> R_AND_R; flashing categories -> R_AND_R on a
    shake roof (interlaced/bonded). Everything else -> None (no operation asserted by default,
    so it never manufactures a divergence). Page 3 supplies/overrides per category."""
    if category_id == "SHAKE_FIELD_RR":
        return R_AND_R
    if category_id in _FLASHING_DEFAULT_RR:
        return R_AND_R
    return None


def required_operation_for_category(category_id, required_operations):
    """Explicit Page-3 assertion wins; otherwise the §2.1 default."""
    if required_operations and category_id in required_operations:
        return required_operations[category_id]
    return default_required_operation(category_id)


# ---------------------------------------------------------------------------
# §3.2 operation_match + operation_delta
# ---------------------------------------------------------------------------
def _known(op):
    return op is not None and op != UNKNOWN_OP and op in CANONICAL_OPS


def operations_comparable(required_op, carrier_op):
    """Both sides carry a KNOWN canonical operation -> a real comparison is possible."""
    return _known(required_op) and _known(carrier_op)


def operation_match(required_op, carrier_op):
    """§3.2 match boolean, with the additivity guarantee: when either side is absent/unknown
    the operation is treated as non-divergent (held, not asserted) -> True, so a would-be
    MATCHED line stays MATCHED. False ONLY when both are known and differ."""
    if not operations_comparable(required_op, carrier_op):
        return True
    return required_op == carrier_op


def operation_delta(required_op, carrier_op):
    """§3.2/§1.2: cost components present in the REQUIRED operation but ABSENT in the carrier
    operation, in the deterministic emit order. Empty when not comparable or when equal."""
    if not operations_comparable(required_op, carrier_op):
        return []
    missing = COST_COMPONENTS[required_op] - COST_COMPONENTS[carrier_op]
    return [c for c in _COMPONENT_EMIT_ORDER if c in missing]


def delta_phrase(delta):
    """Neutral human phrase for a delta list (scope language; guard-clean; no coverage terms)."""
    labels = [COMPONENT_LABEL.get(c, c) for c in delta]
    if not labels:
        return ""
    if len(labels) == 1:
        return labels[0]
    return ", ".join(labels[:-1]) + " and " + labels[-1]


# ---------------------------------------------------------------------------
# §3.3–§3.5 overlay: attach the four attributes and rescue MATCHED -> OPERATION_DIFFERENCE
# ---------------------------------------------------------------------------
OPERATION_DIFFERENCE = "OPERATION_DIFFERENCE"


def apply_operation_overlay(line, required_op, carrier_op):
    """Mutates `line` in place: attaches §3.2 attributes to EVERY line, and — per §3.4/§3.5 —
    re-routes a would-be MATCHED line to OPERATION_DIFFERENCE when (and only when) the
    operations are comparable and differ. QUANTITY_DIFFERENCE keeps its state; the operation
    rides as supplementary detail. All other states are untouched."""
    match = operation_match(required_op, carrier_op)
    line["required_operation"] = required_op
    line["carrier_operation"] = carrier_op
    line["operation_match"] = match
    line["operation_delta"] = operation_delta(required_op, carrier_op)

    if line.get("state") == "MATCHED" and operations_comparable(required_op, carrier_op) and not match:
        line["state"] = OPERATION_DIFFERENCE
        # OPERATION_DIFFERENCE is an equal-quantity line; it carries NO required_scope_difference.
        line["required_scope_difference"] = None
    return line
