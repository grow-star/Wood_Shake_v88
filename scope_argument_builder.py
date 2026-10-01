#!/usr/bin/env python3
"""
SCOPE ARGUMENT BUILDER — support service (NOT a module)
======================================================
Consumes already-locked facts and emits a single `argument_pack` consumed by
Module 3 (renderer) and by the adjuster email. It AUTHORS argument prose so
Module 3 can stay dumb (render/order/print). It performs NO geometry, NO
material quantity, NO pricing, NO coverage interpretation, NO approval/denial
language, and it creates/suppresses/alters NO scope item, comparison state, or
upstream output. It is strictly READ-ONLY over its inputs.

Spec: Wood_Shake_Scope_Argument_Builder_Spec_v0_1.md (§0–§6). This is the
reference implementation that makes the v0.1 regression runnable; it does not
modify Module 1/2, the Carrier Parser, the Comparison Builder, or the renderer.
"""

# --- canonical phrasing (spec §0.2) ----------------------------------------
SURFACE_PHRASE = "repair activity on a wood shake roof surface"
COMPONENTS_PHRASE = "components necessary to complete a proper repair"

# Terms this service must never author into emitted prose (spec §0.2 / §5).
# (The Module 3 §10.5 guard is the authority at export; we avoid them at source.)
_AUTHORING_AVOID = ["owed", "underpaid", "carrier failed", "coverage applies"]


def _mode(inputs):
    """report_mode mirrors SC.mode; never decided here, only read/derived."""
    sc = inputs.get("scope_comparison")
    if isinstance(sc, dict) and sc.get("mode"):
        return sc["mode"]
    has_carrier = bool(inputs.get("carrier_scope_summary"))
    return "COMPARISON" if (sc and has_carrier) else "REQUIRED_SCOPE_ONLY"


def _carrier_acknowledged(inputs):
    css = inputs.get("carrier_scope_summary") or {}
    # In the live path "acknowledged" is a DICT ({"wood_shake_repair": <bool>, ...}), so bool(css.get(
    # "acknowledged")) is True for ANY non-empty dict — including {"wood_shake_repair": False}. That printed
    # the acknowledging wording on every comparison, even when the carrier scoped no shake. Read the actual
    # flag; a bare bool (simplified/legacy callers) is honoured as given.
    ack = css.get("acknowledged")
    if isinstance(ack, dict):
        return bool(ack.get("wood_shake_repair"))
    return bool(ack)


def build_argument_pack(inputs):
    """Assemble the argument_pack from locked facts. Pure read; mutates nothing."""
    mode = _mode(inputs)
    vci = inputs.get("verified_claim_info") or {}
    insured = vci.get("insured", "[insured]")
    loss_address = vci.get("loss_address", "[loss_address]")
    claim_number = vci.get("claim_number", "[claim_number]")
    acknowledged = _carrier_acknowledged(inputs)
    photos = inputs.get("photos") or []
    attachments = inputs.get("attachments") or []
    ref_tags = inputs.get("reference_tags") or []
    m2_lines = inputs.get("m2_scope") or []

    # --- lead_summary (precedes Section 1) ---------------------------------
    if mode == "COMPARISON" and acknowledged:
        lead_summary = (
            f"Summary of repair requirements for {insured} ({loss_address}). "
            f"The carrier estimate acknowledges {SURFACE_PHRASE}. Because of how wood shake roof "
            f"systems are constructed, the repair process affects more than the initially identified "
            f"damaged component. This analysis identifies the {COMPONENTS_PHRASE} using wood shake "
            f"repair practices."
        )
    else:
        lead_summary = (
            f"Summary of repair requirements for {insured} ({loss_address}). "
            f"This analysis identifies the {COMPONENTS_PHRASE} for the affected area of the wood "
            f"shake roof. Because of how wood shake roof systems are constructed, completing the "
            f"repair affects the surrounding assembly, not only the initially identified component."
        )

    # --- repair_surface_context (Section 2 intro) --------------------------
    if acknowledged:
        repair_surface_context = (
            f"The carrier estimate acknowledges {SURFACE_PHRASE}. The analysis below identifies the "
            f"roof components affected by completing that repair using proper wood shake repair practices."
        )
    else:
        repair_surface_context = (
            f"The analysis below identifies the {COMPONENTS_PHRASE} for the affected area of the wood "
            f"shake roof. No carrier acknowledgment is asserted in this report."
        )

    # --- wood_shake_method_explanation (Section 3; educational points 1-4) -
    wood_shake_method_explanation = (
        "Wood shake repairs differ from laminate shingle repairs. Wood shakes are individual shake "
        "components installed in overlapping courses, and the felt interlayment is integrated between "
        "the shake courses rather than sitting as one continuous layer beneath the roof covering. "
        "Because the components interlock course over course, a localized repair requires opening and "
        "rebuilding the affected assembly piece-by-piece; the repair affects the surrounding assembly, "
        "not just the single damaged component."
    )
    if ref_tags:
        wood_shake_method_explanation += (
            " Supporting manufacturer and industry references for these practices are included for review."
        )

    # --- per_shake_labor_explanation (Section 3; points 6-7, revised) ------
    # EA is a VALID estimate / repair-operation quantity — not dismissed as only a material count.
    # (SQ remains the §2.4 SHAKE_FIELD_RR comparison operand; EA is supporting. This block does not
    #  change that — it explains EA's role as repair operations and labor evidence.)
    per_shake_labor_explanation = (
        "The individual shake quantity is not simply a material count; it represents the individual "
        "repair operations necessary within the affected area and illustrates why localized wood shake "
        "repairs are more labor intensive than square-based replacement."
    )

    # --- repair_vs_replacement_explanation (Section 3; new block) ----------
    repair_vs_replacement_explanation = (
        "Full roof replacement allows continuous removal and installation across a roof area. Localized "
        "wood shake repair requires opening the affected assembly and replacing individual components "
        "within that repair area. The individual shake quantity reflects the labor-intensive repair "
        "process."
    )

    # --- component_summary_intro (Section 3; point 5) ----------------------
    component_summary_intro = (
        "The components below are the "
        f"{COMPONENTS_PHRASE}. The Affected SQ describes the physical repair area; the individual "
        "shake quantity describes the repair operations performed within that area."
    )

    # --- comparison_intro (Section 5; COMPARISON only) ---------------------
    if mode == "COMPARISON":
        comparison_intro = (
            "The comparison below aligns the "
            f"{COMPONENTS_PHRASE} with the scope the carrier has acknowledged, by aligned structure. "
            "It identifies, neutrally, the components affected by completing the repair."
        )
    else:
        comparison_intro = ""  # omitted in REQUIRED_SCOPE_ONLY

    # --- photo_evidence_intro (Section 6) ----------------------------------
    photo_evidence_intro = (
        "The photographs below document field conditions supporting the repair analysis."
        if photos else ""
    )

    # --- attachment_intro (Section 7; labels only) -------------------------
    labels = [a.get("label", "") for a in attachments if a.get("included")]
    attachment_intro = (
        "The following documentation is included for review: " + ", ".join(labels) + "."
        if labels else ""
    )

    # --- adjuster email (spec §6) ------------------------------------------
    adjuster_email_subject = f"Wood Shake Roof Repair Review — {insured}, Claim {claim_number}"
    closing = (
        "Supporting manufacturer documentation and applicable requirements have been included for "
        "review, along with the estimate comparison identifying the remaining scope items necessary "
        "to complete the repair."
        if mode == "COMPARISON" else
        "Supporting manufacturer documentation and applicable requirements have been included for "
        "review, identifying the scope items necessary to complete the repair."
    )
    email_scope_context = (
        f"The carrier estimate acknowledges {SURFACE_PHRASE}. The attached documentation identifies "
        "the roof components impacted by the required repair process and the additional scope necessary "
        "to complete the repair using proper wood shake repair practices."
        if mode == "COMPARISON" and acknowledged else
        f"The attached documentation identifies the {COMPONENTS_PHRASE} for the affected area of the "
        "wood shake roof and the scope necessary to complete the repair using proper wood shake repair "
        "practices. No carrier repair-surface confirmation is asserted."
    )
    adjuster_email_body = (
        f"Re: {insured} — Claim {claim_number} — {loss_address}\n\n"
        "Please see the attached wood shake roof repair review package.\n\n"
        f"{email_scope_context}\n\n"
        "Due to the installation method of cedar shakes, completing the identified repair requires "
        "removal and integration of the surrounding assembly, including affected shake courses, felt "
        "interlayment, flashings, valley assemblies, ridge/hip components, or related roof accessories "
        "depending on the repair location.\n\n"
        f"{closing}"
    )

    # --- missing_support_warnings (user-facing, NOT report prose) ----------
    warnings = []
    if not ref_tags:
        warnings.append("No code/manufacturer reference tags present; method explanation references "
                        "supporting standards that are not attached.")
    if mode == "COMPARISON" and not acknowledged:
        warnings.append("COMPARISON mode but no carrier acknowledgment present in carrier_scope_summary.")
    if any(not (ln.get("citation")) for ln in m2_lines):
        warnings.append("One or more Module 2 scope lines carry no citation passthrough.")

    return {
        "report_mode": mode,
        "lead_summary": lead_summary,
        "repair_surface_context": repair_surface_context,
        "wood_shake_method_explanation": wood_shake_method_explanation,
        "per_shake_labor_explanation": per_shake_labor_explanation,
        "repair_vs_replacement_explanation": repair_vs_replacement_explanation,
        "component_summary_intro": component_summary_intro,
        "comparison_intro": comparison_intro,
        "photo_evidence_intro": photo_evidence_intro,
        "attachment_intro": attachment_intro,
        "adjuster_email_subject": adjuster_email_subject,
        "adjuster_email_body": adjuster_email_body,
        "missing_support_warnings": warnings,
    }


# Canonical field list (spec §2) — the contract Module 3 consumes.
ARGUMENT_PACK_FIELDS = [
    "report_mode", "lead_summary", "repair_surface_context",
    "wood_shake_method_explanation", "per_shake_labor_explanation",
    "repair_vs_replacement_explanation", "component_summary_intro",
    "comparison_intro", "photo_evidence_intro", "attachment_intro",
    "adjuster_email_subject", "adjuster_email_body", "missing_support_warnings",
]
