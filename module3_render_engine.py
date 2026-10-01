#!/usr/bin/env python3
"""Production Module 3 render engine.

Relocated read-map renderer contract machinery from the contract regression.
This module renders/projections only; it performs no scope math, comparison math,
or prose authoring.
"""

# §3.1 per-section read allow-list (path prefixes)
ALLOW = {
 0: {"P3.argument_prose"},                                # lead repair-logic narrative (editable, guarded)
 1: {"VCI"},                                              # §1 reads verified_claim_info ONLY (Change 1)
 2: {"CSS.acknowledged", "SC.estimate_id", "SC.estimate_name", "SC.lines",
     "CSS.reference_totals", "CSS.platform_identity.platform"},
 3: {"M2.required_lines", "M2.required_lines_by_structure", "M2.structure_blocks", "M2.per_shake_reasoning", "M2.citations", "SC.shake_dual",
     "M2.replacement_facets", "M2.repair_facets", "M2.eave_iws"},
 4: {"M1.affected_polygons", "M1.affected_SF", "M1.facet_valley_assignments", "M1.authoritative_pct", "M1.replacement_facets"},
 5: {"SC.lines", "SC.structure_alignments", "SC.structure_comparisons", "SC.comparison_precondition", "SC.shake_dual",
     "SC.required_scope", "M2.citations", "CSS.platform_identity.platform", "SC.stated_gaps"},  # v72: platform + no-haul-off gaps; v84: per-structure §5
 6: {"P3.photos", "P3.captions", "SC.lines", "M2.citations"},
 7: {"P3.attachments", "P3.non_roof_ack"},
}
FORBIDDEN_EVERYWHERE = "CSS.platform_identity.inferred_platform"   # never authoritative

# =============================================================================
# Instrumented reader + reference renderer (data projection only)
# =============================================================================
class Reader:
    def __init__(self, inputs): self.inputs = inputs; self.log = []
    def __call__(self, section, path):
        self.log.append((section, path))
        cur = self.inputs
        for p in path.split("."):
            cur = (cur or {}).get(p) if isinstance(cur, dict) else None
        return cur

def _allowed(path, prefixes):
    return any(path == a or path.startswith(a + ".") for a in prefixes)

# states partitioned across sections (the contract's implied routing — encoded here)
S2_STATES = {"MATCHED", "ACKNOWLEDGED_ONLY"}
# OPERATION_DIFFERENCE (Operation Dimension §3.3/§5) is a divergence -> rendered in §5.
# v76 DEFECT 4: every REQUIRED item in §3 must also appear in §5, even when it is in agreement.
# MATCHED required items previously reached §2 only, so a required item the carrier funded correctly
# (e.g. chimney flashing) was absent from the comparison table — invisible where the reader looks for
# the required-vs-approved picture. MATCHED now renders in §5 as an explicit "in agreement" row.
# AUDIT: MATCHED was the only required-item state routed away from §5; every required category is built
# into SC.lines, so nothing is dropped from the comparison. ACKNOWLEDGED_ONLY is a CARRIER-only line
# (no required side) and correctly stays out of the required-item table.
S5_STATES = {"QUANTITY_DIFFERENCE", "MISSING_FROM_CARRIER", "MISSING_FROM_CARRIER_EXCLUDED",
             "OPERATION_DIFFERENCE", "UNMAPPED_REVIEW", "OPERATION_SPLIT", "MATCHED"}

def _citation_for(inputs, category_id):
    """The standard Module 2 bound to this category. None when it has none — never invented.
    v73 DEFECT 4: the synthesised RIDGE_HIP_CAP key has no Module-2 line of its own — the fold drops
    the citations the engine DID produce for RIDGE_CAPS and HIP_CAPS. Recombine those (never invent
    one), so the ridge/hip row is no longer the only blank 'why' cell in the table."""
    lines = (inputs.get("M2") or {}).get("required_lines") or []
    by_cat = {ln.get("category_id"): ln.get("citation") for ln in lines}
    if category_id == "RIDGE_HIP_CAP":
        seen = []
        for c in ("RIDGE_CAPS", "HIP_CAPS"):
            cit = by_cat.get(c)
            if cit and cit not in seen:
                seen.append(cit)
        return "; ".join(seen) or None
    return by_cat.get(category_id)


def _s5_build_gap(lines, inputs):
    """Build the §5 gap rows for ONE comparison — the whole roof, or a single scoped structure. The
    identical projection drives the single-structure table and each per-structure block, so a lone
    structure and one block of a multi-structure roof render the same way. Pure; no reads logged."""
    gap = []
    for l in lines:
        if l["state"] not in S5_STATES:
            continue
        row = {"category_id": l["category_id"], "state": l["state"],
               "citation": l.get("row_citation") or _citation_for(inputs, l["category_id"]),
               "required_quantity": l.get("required_quantity"),
               "required_unit": l.get("required_unit"),
               "label": l.get("label")}
        if l["state"] == "QUANTITY_DIFFERENCE":
            row.update(required=l["required_quantity"], approved=l["approved_quantity"],
                       required_scope_difference=l["required_scope_difference"],
                       tolerance_basis=l["tolerance_basis"])
            if l.get("operation_match") is False:
                row["operation_context"] = {
                    "required_operation": l.get("required_operation"),
                    "carrier_operation": l.get("carrier_operation"),
                    "operation_delta": list(l.get("operation_delta") or []),
                }
        if l["state"] == "OPERATION_DIFFERENCE":
            row.update(required=l.get("required_quantity"), approved=l.get("approved_quantity"),
                       required_operation=l.get("required_operation"),
                       carrier_operation=l.get("carrier_operation"),
                       operation_delta=list(l.get("operation_delta") or []))
        if l["state"] == "OPERATION_SPLIT":
            row.update(required=l.get("required_quantity"),
                       required_operation=l.get("required_operation"),
                       approved_operations=[dict(o) for o in (l.get("approved_operations") or [])])
        if l["state"] == "MATCHED":
            row.update(required=l.get("required_quantity"), approved=l.get("approved_quantity"))
        if l["state"] == "MISSING_FROM_CARRIER_EXCLUDED":
            row.update(exclusion_reason=l["exclusion_reason"],
                       exclusion_source_text=l["exclusion_source_text"])
        if l["state"] == "UNMAPPED_REVIEW":
            row.update(carrier_quantity=l.get("approved_quantity"),
                       carrier_unit=l.get("approved_unit"), note=l.get("note"))
        if l.get("carrier_pair_note"):
            row["carrier_pair_note"] = l.get("carrier_pair_note")
        gap.append(row)
    _req_order = {ln.get("category_id"): i
                  for i, ln in enumerate((inputs.get("M2") or {}).get("required_lines") or [])}
    _END = len(_req_order) + 1
    def _s5_rank(cat):
        if cat in _req_order:
            return _req_order[cat]
        if cat == "RIDGE_HIP_CAP":                       # combined key -> its components' position
            return min(_req_order.get("RIDGE_CAPS", _END), _req_order.get("HIP_CAPS", _END))
        return _END
    return sorted(gap, key=lambda r: (_s5_rank(r["category_id"]), str(r["category_id"])))


def render(inputs, sc):
    # A CARRIER-SIDE CONDITION MAY NEVER PRODUCE AN EMPTY REPORT.
    # =========================================================================================
    # This used to be:
    #     if inputs["CSS"].get("parser_status") == "NEEDS_CONFIRMATION":
    #         return {"gated": True, "sections": {}, "review_queue": []}
    #
    # Two things were wrong with it, and together they cost Joseph a real claim — "Nothing showed up
    # in the report. Not even the material list."
    #
    #   1. IT SUPPRESSED SECTIONS THAT HAVE NOTHING TO DO WITH THE CARRIER. The material list (§3),
    #      the shake analysis and the diagram (§4) are computed from the PAGE 2 ROOF SELECTION. No
    #      carrier estimate is involved in producing them. If a carrier-side condition can suppress
    #      them, the design is wrong. Verified on v58: bypassing this line rendered ALL EIGHT
    #      sections with 15 material lines already sitting in M2.required_lines, unused.
    #   2. IT FIRED FOR THE WRONG CONDITION. manual_carrier_entry reused NEEDS_CONFIRMATION for
    #      "the same category appears twice in one estimate" — a normal Xactimate Remove/Additional
    #      pair. Fixed at source; that status is now raised ONLY for the true multi-ESTIMATE case.
    #
    # WHAT REPLACES IT. The multi-estimate gate is CORRECT and STAYS: you genuinely cannot compare
    # when you do not know which of several estimates to compare against. But "cannot COMPARE" is not
    # "cannot REPORT". So the comparison is withheld and everything else renders, in the mode the
    # projection ALREADY produces for exactly this case — module3_caller._project_scope_comparison
    # returns mode REQUIRED_SCOPE_ONLY with comparison_precondition CARRIER_NEEDS_ESTIMATE_SELECTION.
    # Nothing new was invented here; the renderer simply stopped discarding it.
    #
    # `gated` is still reported so callers that branch on it keep working, and the reason is stated
    # in plain words the reader can act on rather than as a status token.
    gate_reason = None
    if inputs.get("CSS") and inputs["CSS"].get("parser_status") == "NEEDS_CONFIRMATION":
        gate_reason = ("This estimate document contains more than one named estimate, so the "
                       "carrier comparison is withheld until one is selected. The required scope, "
                       "material list, shake analysis and diagram below are computed from the roof "
                       "measurements and are unaffected.")
        sc = dict(sc or {})
        sc["mode"] = "REQUIRED_SCOPE_ONLY"
        sc["comparison_precondition"] = "CARRIER_NEEDS_ESTIMATE_SELECTION"
        sc["lines"] = []
    R = Reader(inputs)
    sec = {}

    # 0 — Repair argument (lead narrative; editable prepared prose, guarded before export — renderer is dumb)
    sec[0] = {"argument": R(0, "P3.argument_prose")}
    # 1 — Claim information (reads verified_claim_info ONLY — Change 1; identical in both modes)
    v = R(1, "VCI") or {}
    sec[1] = {"insured": v.get("insured"), "loss_address": v.get("loss_address"),
              "claim_number": v.get("claim_number"), "policy_number": v.get("policy_number"),
              "type_of_loss": v.get("type_of_loss"), "date_of_loss": v.get("date_of_loss"),
              "deductible": v.get("deductible"), "carrier": v.get("carrier"),
              "jurisdiction_code": v.get("jurisdiction_code")}

    # 2 — Carrier estimate summary (only if a statement is present)
    if inputs.get("CSS"):
        ack = R(2, "CSS.acknowledged") or {}
        lines = R(2, "SC.lines") or []
        rt = R(2, "CSS.reference_totals") or {}
        sec[2] = {"acknowledged": ack, "estimate_name": R(2, "SC.estimate_name"),
                  "agreed_lines": [l["category_id"] for l in lines if l["state"] in S2_STATES],
                  "reference_totals": rt, "platform": R(2, "CSS.platform_identity.platform")}

    # 3 — Wood shake repair analysis (program required scope; no carrier qty)
    dual = R(3, "SC.shake_dual")
    sec[3] = {"required_lines": [{"item": x["item"], "qty": x["qty"], "unit": x["unit"],
                                  "category_id": x.get("category_id"),
                                  # v48 split chimney flashings by size; carry the Xactimate code
                                  # so the reader can see WHICH item is being billed.
                                  "xact_code": x.get("xact_code")}
                                 for x in (R(3, "M2.required_lines") or [])],
              "reasoning": R(3, "M2.per_shake_reasoning"), "citations": R(3, "M2.citations"),
              "shake_comparison_SQ": (dual or {}).get("comparison_quantity"),
              "shake_supporting_EA": (dual or {}).get("supporting_quantity"),
              # v61 full slope replacement: designators so §3 labels the two shake lines by facet and
              # states the replacement area is NET (no waste) with no repair factor applied.
              "replacement_facets": R(3, "M2.replacement_facets") or [],
              "repair_facets": R(3, "M2.repair_facets") or [],
              # v65 structure separation: per-structure material lists (empty for single-structure roofs,
              # so the flat required_lines above renders unchanged). Each entry: heading + its own lines.
              "required_lines_by_structure": [
                  {"structure_id": g.get("structure_id"), "facet_count": g.get("facet_count"),
                   "heading": g.get("heading"),
                   "lines": [{"item": x["item"], "qty": x["qty"], "unit": x["unit"],
                              "category_id": x.get("category_id"), "xact_code": x.get("xact_code")}
                             for x in (g.get("lines") or [])]}
                  for g in (R(3, "M2.required_lines_by_structure") or [])],
              # v69: ordered per-structure blocks for §2's dual and §3's slope callouts.
              "structure_blocks": [dict(b) for b in (R(3, "M2.structure_blocks") or [])],
              # v71 DEFECT 3: eave ice & water metadata (basis, coverage, layer count) or None.
              "eave_iws": R(3, "M2.eave_iws")}

    # 4 — Affected area diagram
    sec[4] = {"polygons": R(4, "M1.affected_polygons"), "affected_SF": R(4, "M1.affected_SF"),
              "valley_assignments": R(4, "M1.facet_valley_assignments"),
              "authoritative_pct": R(4, "M1.authoritative_pct"),
              # The roof picture, generated from the SAME diagram data as the totals. Optional:
              # absent -> the renderer falls back to its stub, so every existing caller still works.
              "diagram_svg": (inputs.get("P3") or {}).get("diagram_svg"),
              "has_replacement": bool(R(4, "M1.replacement_facets"))}   # v63: legend shows a replaced swatch

    # 5 — Required vs approved comparison (gap; mode-aware)
    review_queue = []
    if sc["mode"] == "COMPARISON":
        lines = R(5, "SC.lines") or []
        # §5 gap for the whole roof (single-structure) — one authority, one builder (see _s5_build_gap).
        # §5 ORDERING: the same category order the material list (§3) uses (that helper sorts on it).
        gap = _s5_build_gap(lines, inputs)
        sec[5] = {"mode": "COMPARISON", "precondition": R(5, "SC.comparison_precondition"),
                  "structure_alignments": R(5, "SC.structure_alignments"), "gap": gap,
                  # How many items are in this repair scope at all — the denominator for the headline
                  # count ("11 of the 13 items ... are not present in the carrier estimate").
                  # Computed, never hardcoded.
                  "scope_line_count": len((inputs.get("M2") or {}).get("required_lines") or []),
                  "shake_dual": R(5, "SC.shake_dual"),
                  # v72 DEFECT 3: the platform the carrier actually used, so the operation argument
                  # cites the right activity vocabulary (UNKNOWN -> nothing platform-specific).
                  "platform": R(5, "CSS.platform_identity.platform"),
                  "stated_gaps": R(5, "SC.stated_gaps") or []}
        # PER-STRUCTURE §5: one gap block per scoped structure, each built by the SAME helper as the
        # single table above. The heading comes from M2.structure_blocks — the ONE heading authority
        # §3 already uses, so §3 and §5 name the buildings identically. Present only for 2+ scoped
        # structures; absent for a single-structure roof, which renders byte-identically.
        struct_cmps = R(5, "SC.structure_comparisons") or []
        if len(struct_cmps) >= 2:
            heading_by_sid = {b.get("structure_id"): b.get("heading")
                              for b in ((inputs.get("M2") or {}).get("structure_blocks") or [])}
            structure_gaps = []
            for b in struct_cmps:
                sid = b.get("structure_id")
                g = _s5_build_gap(b.get("lines") or [], inputs)
                structure_gaps.append({"structure_id": sid,
                                       "heading": heading_by_sid.get(sid) or sid,
                                       "gap": g, "scope_line_count": len(g)})
            sec[5]["structure_gaps"] = structure_gaps
        review_queue = [u["description"] for u in sc.get("unresolved", [])]   # held, NOT in gap
    else:   # REQUIRED_SCOPE_ONLY — a valid mode: present the required material scope (one-sided), no comparison
        sec[5] = {"mode": "REQUIRED_SCOPE_ONLY",
                  "required_scope": R(5, "SC.required_scope") or [],
                  "shake_dual": R(5, "SC.shake_dual")}

    # 6 — Evidence
    lines = R(6, "SC.lines") or []
    sec[6] = {"photos": R(6, "P3.photos"), "captions": R(6, "P3.captions"),
              "carrier_source_lines": [l.get("carrier_source_lines") for l in lines],
              "citations": R(6, "M2.citations")}

    # 7 — Attachments (renders the confirmed Page 3 manifest; fixed labels only, NO pricing, no material list)
    atts = R(7, "P3.attachments") or []
    sec[7] = {"included": [a["label"] for a in atts if a.get("included")],
              "non_roof_ack": R(7, "P3.non_roof_ack")}

    return {"gated": gate_reason is not None, "gate_reason": gate_reason,
            "sections": sec, "reads": R.log, "review_queue": review_queue}

# dollar keys that must never leak outside §2
DOLLAR_KEYS = {"reference_totals", "roof_section_total_RCV", "estimate_total", "rcv", "acv",
               "price", "total", "deductible", "$"}

def section_violations(reads, section):
    return [p for (s, p) in reads if s == section and not _allowed(p, ALLOW[section])]

