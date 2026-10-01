#!/usr/bin/env python3
"""
MODULE 3 — COMPARISON BUILDER + FROZEN YAGER COMPARISON ORACLE  (item 4)
=======================================================================
First place the WHOLE comparison runs against a known-good expected result.
Builds `scope_comparison` from the required side (Module 2 seed, keyed/normalized
by Module 3 §2.4) and a frozen carrier `carrier_scope_summary`, then asserts the
6-state assignment, the hybrid tolerance, the signed difference, and the §2.7
precondition.

SCOPE / HONESTY (read this):
  The required side is the FROZEN Module 2 SEED (facet D), keyed by the same
  Module 3 normalization proven in item 3. The carrier side is a FROZEN fixture
  built on the YAGER / State Farm identity but with quantities deliberately
  SEED-ALIGNED to facet D's area — i.e. the §2.7 shared-physical-area precondition
  is satisfied by construction — and crafted to fire each of the 6 states + both
  tolerance bases. It is NOT the raw whole-roof Yager statement (1.55 SQ shakes,
  154.77 LF valley); a whole-roof Yager comparison needs the full 20-side Module 2,
  which is still gated on the Module 2 grow. This oracle proves the BUILDER; it
  grows into the real whole-roof Yager comparison when Module 2 grows.

  Proves the comparison LOGIC (deterministic). Does NOT run the LLM parser or
  Module 1/2 (imported/frozen). No F9, no Authority, no policy/coverage.
"""

from module2_scope_expansion import M1Interface, Edge, expand_scope
from module3_keying import key_and_normalize
from shared_category_registry import REGISTRY_SET
from operation_dimension import (
    apply_operation_overlay,
    carrier_operation_for_category,
    required_operation_for_category,
    default_required_operation,
    operation_delta,
    R_AND_R, REPLACE,
)

# v72 DEFECT 2 — the required ACTIVITY CODE depends on REPAIR vs REPLACEMENT (Joseph, binding):
#   REPAIR       -> every component is R&R.
#   REPLACEMENT  -> the shakes are R&R; most other components are REPLACE (the carrier's position is
#                   they come off with the shakes anyway).
# EXCEPT the items below, which are ALWAYS R&R in BOTH contexts. This list is NOT exhaustive — Joseph:
# "the examples I provided are the common ones carriers typically agree on." It is a single named
# constant precisely so the next item is a ONE-LINE addition, never a scattered conditional.
ALWAYS_R_AND_R = frozenset({
    "CHIMNEY_FLASH",   # chimney flashings
    "VENT_CAP",        # rain caps / rain cap & collars
    "POWER_VENT",      # power vent covers
    # add the next carrier-agreed always-R&R category id here — one line.
})


def _required_op_ctx(category_id, required_operations, is_replacement):
    """Context-aware required operation. A Page-3 assertion still wins; then the ALWAYS_R_AND_R
    exception; then the §2.1 default, promoted to REPLACE for non-shake components on a full
    replacement. operation_dimension is untouched — the context is layered on here at comparison
    time, exactly like required_operations."""
    if required_operations and category_id in required_operations:
        return required_operations[category_id]
    if category_id in ALWAYS_R_AND_R:
        return R_AND_R
    base = default_required_operation(category_id)
    if is_replacement and base == R_AND_R and category_id != "SHAKE_FIELD_RR":
        return REPLACE
    return base

# §2.5 tolerance floors (continuous units); EA is exact-only
FLOORS = {"SQ": 0.10, "LF": 0.50, "SF": 5.0, "HR": 0.25}

def classify(required, approved, unit):
    """§2.5 -> (state, tolerance_basis, signed_diff). signed_diff = required - approved."""
    signed = round(required - approved, 4)
    if unit == "EA":
        return ("MATCHED", "EXACT_EA", signed) if required == approved \
               else ("QUANTITY_DIFFERENCE", "EXACT_EA", signed)
    diff = abs(required - approved)
    rel = diff / required if required else float("inf")
    if rel <= 0.02:
        return "MATCHED", "RELATIVE_2PCT", signed          # measurement noise
    if diff <= FLOORS[unit]:
        return "MATCHED", "ABSOLUTE_FLOOR", signed         # tiny-quantity noise
    return "QUANTITY_DIFFERENCE", "OUTSIDE_TOLERANCE", signed  # real difference (waste NOT absorbed)

# RIDGE_CAPS + HIP_CAPS are folded into the combined key (§2.4.3); compared as RIDGE_HIP_CAP
_FOLD = {"RIDGE_CAPS", "HIP_CAPS"}
# v71 DEFECT 1: the required side folds ridge+hip into the combined RIDGE_HIP_CAP key, but a carrier
# writes them as RIDGE_CAPS and/or HIP_CAPS (overwhelmingly ONE "Hip / Ridge cap" line -> RIDGE_CAPS).
# The combined required must be reconciled against the SUM of whichever of those the carrier carries,
# so a single combined carrier line AND a split ridge/hip pair both meet the combined requirement
# instead of printing a false "not present" beside a stranded acknowledgement.
_CARRIER_FOLD = {"RIDGE_HIP_CAP": ("RIDGE_CAPS", "HIP_CAPS")}

def build_comparison(required, carrier, required_operations=None, is_replacement=False):
    """required: keyed M2 entries (item 3). carrier: frozen carrier_scope_summary or None.

    required_operations (ADDITIVE, Operation Dimension §2/§3): optional per-category mapping
    {category_id -> canonical operation} supplied by Page 3. When omitted, §2.1 defaults apply
    (e.g. SHAKE_FIELD_RR -> R_AND_R). Module 2 is NOT modified — the required operation is
    layered on here, at comparison time. Backward compatible: existing 2-arg callers get the
    defaults, and no line moves to OPERATION_DIFFERENCE unless BOTH operations are known and
    differ, so every pre-existing MATCHED case is preserved.
    """
    if carrier is None:                                    # §2.7 optional-statement path
        return {"mode": "REQUIRED_SCOPE_ONLY", "comparison_precondition": None,
                "lines": [], "required_only": [k for k in required if k not in _FOLD]}

    approved, excluded, unmapped = carrier["approved"], carrier["excluded"], carrier["unmapped"]
    lines, matched = [], set()

    for rkey, rent in required.items():
        if rkey in _FOLD:                                  # folded into combined; not a standalone line
            continue
        cat = "RIDGE_HIP_CAP" if rkey == "RIDGE_HIP_CAP__combined" else rkey
        runit, rqty = rent["comparison_unit"], rent["comparison_quantity"]
        line = {"category_id": cat, "required_quantity": rqty, "required_unit": runit}
        if cat == "SHAKE_FIELD_RR":                        # dual value (§2.4.2)
            line["supporting_quantity"] = rent.get("supporting_quantity")
            line["supporting_unit"] = "EA"

        # v77 DEFECT 5 (Joseph, binding): a category the user gave DISTINCT LABELS to on page 2 (a
        # user-placed, user-labelled appurtenance, e.g. "6\" pipe jack") splits into per-label rows.
        #   - The GENERIC portion compares against the carrier's generic line (rule 4) — on the real
        #     estimate the carrier wrote one "R&R Flashing - pipe jack" line, which matches the generic
        #     "Pipe-jack flashing" required row exactly.
        #   - Each USER-LABELLED row is its OWN required row with NO carrier counterpart, because the
        #     carrier did not scope it. That is the argument the row exists to make.
        # The carrier's 4 EA is NOT spread across both rows; the generic row matches and the labelled
        # row carries its own quantity. A carrier line that itself carries a distinguishing label (a
        # "lead pipe jack") would match a required row of the same label where one exists (via `approved`
        # keyed by that label); with no such carrier label today, it falls to the generic row.
        # Categories with no user labels take the existing single-line path, so every prior report is
        # byte-identical.
        _labels = rent.get("labels") or []
        _user_labels = [L for L in _labels if L.get("user_defined")]
        if _user_labels and cat != "SHAKE_FIELD_RR" and _CARRIER_FOLD.get(cat) is None:
            _generic_qty = round(sum(L["qty"] for L in _labels if not L.get("user_defined")), 4)
            _gen_cite = next((L.get("citation") for L in _labels if not L.get("user_defined")), None)
            if _generic_qty > 1e-9:
                gline = {"category_id": cat, "required_quantity": _generic_qty, "required_unit": runit,
                         "row_citation": _gen_cite}
                if cat in approved:
                    a = approved[cat]; matched.add(cat)
                    if a["unit"] != runit:
                        gline.update(state="UNMAPPED_REVIEW", note="unit_mismatch",
                                     approved_quantity=a["qty"], approved_unit=a["unit"])
                    else:
                        st, basis, diff = classify(_generic_qty, a["qty"], runit)
                        gline.update(state=st, approved_quantity=a["qty"], approved_unit=a["unit"],
                                     tolerance_basis=basis,
                                     required_scope_difference=(diff if st == "QUANTITY_DIFFERENCE" else None))
                        if a.get("rr_pair"):
                            gline["carrier_pair_note"] = a.get("pair_note")
                elif cat in excluded:
                    gline.update(state="MISSING_FROM_CARRIER_EXCLUDED",
                                 exclusion_reason=excluded[cat]["reason"],
                                 exclusion_source_text=excluded[cat]["source_text"])
                else:
                    gline.update(state="MISSING_FROM_CARRIER")
                apply_operation_overlay(gline, _required_op_ctx(cat, required_operations, is_replacement),
                                        carrier_operation_for_category(carrier, cat))
                lines.append(gline)
            for L in _labels:
                if not L.get("user_defined"):
                    continue
                # A carrier line whose OWN label matches this user label would compare here; none does
                # on the generic estimate, so the row shows no carrier counterpart (rule 4).
                uline = {"category_id": cat, "label": L["label"],
                         "required_quantity": L["qty"], "required_unit": L["unit"],
                         "state": "MISSING_FROM_CARRIER", "row_citation": L.get("citation")}
                apply_operation_overlay(uline, _required_op_ctx(cat, required_operations, is_replacement), None)
                lines.append(uline)
            continue

        # v71 DEFECT 1: a COMBINED required key (RIDGE_HIP_CAP) is reconciled against the SUM of the
        # carrier ids it folds (RIDGE_CAPS + HIP_CAPS), whichever the carrier actually carries — one
        # combined line or a split pair. Both carrier ids are marked matched so neither strands as an
        # ACKNOWLEDGED_ONLY line, and the combined requirement gets a single real comparison row.
        combine_ids = _CARRIER_FOLD.get(cat)
        if combine_ids is not None:
            present = [cid for cid in combine_ids if cid in approved]
            if present:
                for cid in present:
                    matched.add(cid)
                aunits = {approved[cid]["unit"] for cid in present}
                summed = round(sum(approved[cid]["qty"] for cid in present), 4)
                if aunits != {runit}:                      # §2.4.4 no hidden conversion
                    line.update(state="UNMAPPED_REVIEW", note="unit_mismatch",
                                approved_quantity=summed, approved_unit=sorted(aunits)[0])
                else:
                    st, basis, diff = classify(rqty, summed, runit)
                    line.update(state=st, approved_quantity=summed, approved_unit=runit,
                                tolerance_basis=basis,
                                required_scope_difference=(diff if st == "QUANTITY_DIFFERENCE" else None))
                    if len(present) > 1:
                        line["combined_carrier_from"] = present   # carrier split ridge/hip into two
                    for cid in present:
                        if approved[cid].get("rr_pair"):
                            line["carrier_pair_note"] = approved[cid].get("pair_note")
                            break
            else:
                line.update(state="MISSING_FROM_CARRIER")
            cops = {carrier_operation_for_category(carrier, cid) for cid in present}
            cops.discard(None)
            apply_operation_overlay(
                line,
                _required_op_ctx(cat, required_operations, is_replacement),
                cops.pop() if len(cops) == 1 else None,
            )
            lines.append(line)
            continue

        if cat in approved:
            a = approved[cat]; matched.add(cat)
            _aops = a.get("operations")
            if a["unit"] != runit:                         # §2.4.4 no hidden conversion
                line.update(state="UNMAPPED_REVIEW", note="unit_mismatch",
                            approved_quantity=a["qty"], approved_unit=a["unit"])
            elif _aops and len(_aops) > 1:
                # v75: the carrier funded MORE THAN ONE operation on this category. State the required
                # quantity ONCE (the anchored number) and list EACH carrier operation with its own
                # quantity — never a combined total, never a summed-across-operations figure. Attach the
                # operation-difference explanation to the operations that differ from the required one.
                req_op = _required_op_ctx(cat, required_operations, is_replacement)
                approved_ops = []
                for o in _aops:
                    row = {"operation": o["op"], "quantity": o["qty"], "unit": runit}
                    if req_op and o["op"] != req_op:
                        row["operation_delta"] = operation_delta(req_op, o["op"])
                    approved_ops.append(row)
                line.update(state="OPERATION_SPLIT", required_operation=req_op,
                            approved_operations=approved_ops)
                lines.append(line)
                continue
            else:
                st, basis, diff = classify(rqty, a["qty"], runit)
                line.update(state=st, approved_quantity=a["qty"], approved_unit=a["unit"],
                            tolerance_basis=basis,
                            required_scope_difference=(diff if st == "QUANTITY_DIFFERENCE" else None))
                # Carry the engine-authored R&R pair note (authored once in manual_carrier_entry via
                # the shared consolidate_RR rule) so the report can explain why the approved quantity
                # is the Replace side and not the naive Remove+Replace sum.
                if a.get("rr_pair"):
                    line["carrier_pair_note"] = a.get("pair_note")
        elif cat in excluded:                              # §2.2 neutral factual surfacing
            line.update(state="MISSING_FROM_CARRIER_EXCLUDED",
                        exclusion_reason=excluded[cat]["reason"],
                        exclusion_source_text=excluded[cat]["source_text"])
        else:
            line.update(state="MISSING_FROM_CARRIER")
        # ADDITIVE operation overlay (§3.2–§3.5): attach op attributes; rescue a would-be
        # MATCHED line to OPERATION_DIFFERENCE only when both ops are known and differ.
        apply_operation_overlay(
            line,
            _required_op_ctx(cat, required_operations, is_replacement),
            carrier_operation_for_category(carrier, cat),
        )
        lines.append(line)

    for cat, a in approved.items():                        # carrier-only -> acknowledgement
        if cat not in matched:
            ack = {"category_id": cat, "state": "ACKNOWLEDGED_ONLY",
                   "approved_quantity": a["qty"], "approved_unit": a["unit"]}
            # carrier-only line: no required operation to compare (§3.4 unchanged); attach the
            # carrier operation as supporting detail. Never rescues (state stays ACKNOWLEDGED_ONLY).
            apply_operation_overlay(ack, None, carrier_operation_for_category(carrier, cat))
            lines.append(ack)

    unresolved = [{"description": d, "state": "UNMAPPED_REVIEW"} for d in unmapped]
    return {"mode": "COMPARISON", "comparison_precondition": "SHARED_AREA_ASSERTED_BY_UPLOAD",
            "lines": lines, "unresolved": unresolved}

# ---------------------------------------------------------------------------
# FROZEN required side: Module 2 seed facet D, keyed (item 3)
# ---------------------------------------------------------------------------
_D = M1Interface(affected_SF=28.2, valley_LF_in_scope=7.74,
                 edges=[Edge("EAVE",2.00,4.00), Edge("RAKE",0.00,2.72),
                        Edge("HIP",2.62,4.04), Edge("RIDGE",6.32,6.56)])
REQUIRED, _ = key_and_normalize(expand_scope(_D, 1.0), 28.2)

# ---------------------------------------------------------------------------
# FROZEN carrier side: Yager/State Farm identity, SEED-ALIGNED to facet D,
# crafted to fire all 6 states + both tolerance bases.
# ---------------------------------------------------------------------------
YAGER_CARRIER = {
    "carrier": {"value": "State Farm", "confidence": "HIGH"},
    "platform": "XACTIMATE", "parser_status": "SUCCESS",
    "approved": {
        "SHAKE_FIELD_RR": {"qty": 0.28, "unit": "SQ"},   # vs 0.282 -> MATCHED (2%)
        "FIELD_FELT":     {"qty": 0.20, "unit": "SQ"},   # vs 0.5076 -> QUANTITY_DIFFERENCE (Δ0.3076; CSSB 1.8x interlay)
        "VALLEY_METAL":   {"qty": 6.50, "unit": "LF"},   # vs 7.74  -> QUANTITY_DIFFERENCE (+1.24)
        "STARTER":        {"qty": 1.99, "unit": "LF"},   # vs 2.00  -> MATCHED (2%)
        "PIPE_JACK_FLASH":{"qty": 3,    "unit": "EA"},   # no required -> ACKNOWLEDGED_ONLY
        "GENERAL_LABOR":  {"qty": 8,    "unit": "HR"},   # no required -> ACKNOWLEDGED_ONLY
    },
    "excluded": {"IWS": {"reason": "not_warranted",
                         "source_text": "Ice & water barrier not warranted on this slope."}},  # -> EXCLUDED
    "unmapped": ["Bay window roof, copper, standing seam"],                                     # -> UNMAPPED_REVIEW
}

# FROZEN expected scope_comparison (the oracle): category -> (state, basis, signed_diff)
EXPECTED = {
    "SHAKE_FIELD_RR":  ("MATCHED", "RELATIVE_2PCT", None),
    # v78 DEFECT 4 re-ground: required FIELD_FELT is now 0.5076 SQ (CSSB 1.8x interwoven underlayment,
    # was 0.282 at 1:1). The carrier's 0.20 SQ is therefore genuinely outside tolerance (Δ0.3076), not a
    # floor MATCH. The engine is right; the expectation predates the interlayment re-grounding.
    "FIELD_FELT":      ("QUANTITY_DIFFERENCE", "OUTSIDE_TOLERANCE", 0.3076),
    "VALLEY_METAL":    ("QUANTITY_DIFFERENCE", "OUTSIDE_TOLERANCE", 1.24),
    "STARTER":         ("MATCHED", "RELATIVE_2PCT", None),
    "RIDGE_HIP_CAP":   ("MISSING_FROM_CARRIER", None, None),
    "IWS":             ("MISSING_FROM_CARRIER_EXCLUDED", None, None),
    "PIPE_JACK_FLASH": ("ACKNOWLEDGED_ONLY", None, None),
    "GENERAL_LABOR":   ("ACKNOWLEDGED_ONLY", None, None),
}

# =============================================================================
def run():
    ok = True
    def chk(name, cond):
        nonlocal ok; ok &= bool(cond); print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
    def hdr(t): print(f"\n— {t} —")

    out = build_comparison(REQUIRED, YAGER_CARRIER)
    by_cat = {l["category_id"]: l for l in out["lines"]}

    hdr("precondition (§2.7)")
    chk("statement present -> comparison_precondition = SHARED_AREA_ASSERTED_BY_UPLOAD",
        out["comparison_precondition"] == "SHARED_AREA_ASSERTED_BY_UPLOAD" and out["mode"] == "COMPARISON")
    ro = build_comparison(REQUIRED, None)
    chk("no statement -> REQUIRED_SCOPE_ONLY (no comparison fabricated)",
        ro["mode"] == "REQUIRED_SCOPE_ONLY" and ro["lines"] == [] and "SHAKE_FIELD_RR" in ro["required_only"])

    hdr("6-state assignment matches the frozen oracle")
    for cat, (st, basis, diff) in EXPECTED.items():
        l = by_cat.get(cat, {})
        cond = l.get("state") == st
        if basis is not None: cond = cond and l.get("tolerance_basis") == basis
        if diff is not None:  cond = cond and abs((l.get("required_scope_difference") or 0) - diff) < 1e-9
        chk(f"{cat:16} -> {st}" + (f" / {basis}" if basis else "") + (f" / Δ{diff:+.2f}" if diff is not None else ""), cond)
    states_seen = {l["state"] for l in out["lines"]} | {u["state"] for u in out["unresolved"]}
    chk("all 6 states exercised", states_seen == {
        "MATCHED","QUANTITY_DIFFERENCE","MISSING_FROM_CARRIER",
        "MISSING_FROM_CARRIER_EXCLUDED","ACKNOWLEDGED_ONLY","UNMAPPED_REVIEW"})

    hdr("shake bridge + signed difference in the comparison output")
    sh = by_cat["SHAKE_FIELD_RR"]
    # v78 DEFECT 4 re-ground: supporting EA is 59.0 under the current density (was 64.0; the SQ operand,
    # the number that enters the comparison, is unchanged). Stale expectation, not a regression.
    chk("shake compared in SQ, EA carried as supporting (not operand)",
        sh["required_unit"] == "SQ" and sh["supporting_quantity"] == 59.0 and sh["supporting_unit"] == "EA")
    chk("VALLEY_METAL signed difference = required - approved = +1.24 (required exceeds carrier)",
        abs(by_cat["VALLEY_METAL"]["required_scope_difference"] - 1.24) < 1e-9)
    chk("MATCHED lines carry no signed difference (display-only, only on DIFFERENCE)",
        by_cat["SHAKE_FIELD_RR"].get("required_scope_difference") is None)

    hdr("ridge/hip combine routed as one comparison line")
    chk("RIDGE_HIP_CAP present; RIDGE_CAPS / HIP_CAPS folded (not standalone lines)",
        "RIDGE_HIP_CAP" in by_cat and "RIDGE_CAPS" not in by_cat and "HIP_CAPS" not in by_cat)

    hdr("MISSING_FROM_CARRIER_EXCLUDED carries the carrier's own words (neutral)")
    iws = by_cat["IWS"]
    chk("IWS exclusion carries reason + source_text (no coverage verdict)",
        iws.get("exclusion_reason") == "not_warranted" and bool(iws.get("exclusion_source_text"))
        and "owed" not in str(iws).lower() and "covered" not in str(iws).lower())

    hdr("tolerance rule — direct unit tests (both bases, EA, waste not absorbed)")
    chk("10.00 vs 9.85 SQ -> MATCHED / RELATIVE_2PCT (1.5%)", classify(10.00,9.85,"SQ")[:2]==("MATCHED","RELATIVE_2PCT"))
    chk("10.00 vs 9.50 SQ -> QUANTITY_DIFFERENCE (5%)",       classify(10.00,9.50,"SQ")[0]=="QUANTITY_DIFFERENCE")
    chk("1.55 vs 1.50 SQ -> MATCHED / ABSOLUTE_FLOOR (3.2% but ≤0.10)", classify(1.55,1.50,"SQ")[:2]==("MATCHED","ABSOLUTE_FLOOR"))
    chk("4 vs 4 EA -> MATCHED / EXACT_EA",  classify(4,4,"EA")[:2]==("MATCHED","EXACT_EA"))
    chk("4 vs 3 EA -> QUANTITY_DIFFERENCE", classify(4,3,"EA")[0]=="QUANTITY_DIFFERENCE")
    chk("10.00 vs 9.00 SQ -> QUANTITY_DIFFERENCE (10% waste-sized gap NOT absorbed)",
        classify(10.00,9.00,"SQ")[0]=="QUANTITY_DIFFERENCE")

    hdr("registry sanity")
    chk("every compared category_id ∈ registry",
        all(l["category_id"] in REGISTRY_SET for l in out["lines"]))

    print("\nRESULT:", "ALL PASS — comparison builder locked against the frozen Yager (seed-aligned) "
          "oracle; all 6 states + tolerance + signed difference + precondition proven. "
          "Grows into the whole-roof Yager comparison when Module 2 grows." if ok
          else "*** FAIL ***")
    return ok


def run_ridge_hip_v71():
    """v71 DEFECT 1: the combined required RIDGE_HIP_CAP must reconcile against the carrier's ridge/hip
    line(s) — one combined "Hip / Ridge cap" line OR a split ridge+hip pair — instead of printing a
    false 'not present' beside a stranded acknowledgement. Driven from the real Devore required side."""
    from module3_keying import key_and_normalize
    from workbench_seam import build_scope_from_ui_selection
    from eagleview_geometry_parser import parse_eagleview_geometry
    ok = True
    def chk(name, cond):
        nonlocal ok; ok &= bool(cond); print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
    print("\n\nRIDGE/HIP RECONCILIATION (v71)\n" + "=" * 40)

    dx = open("XML_devore.txt", encoding="utf-8").read()
    dg = parse_eagleview_geometry(dx)
    M2 = build_scope_from_ui_selection(dx, {"xml_text": dx,
                                            "replaced_facets": [{"face_id": f} for f in dg.roof_faces]})
    required, totals = key_and_normalize(M2.aggregated_scope, M2.affected_SF_raw_total)
    req_combined = required["RIDGE_HIP_CAP__combined"]["comparison_quantity"]
    print(f"  required RIDGE_CAPS {totals.get('RIDGE_CAPS')} + HIP_CAPS {totals.get('HIP_CAPS')} "
          f"-> combined {req_combined} LF")

    def rows(carrier):
        out = build_comparison(required, carrier)["lines"]
        return {l["category_id"]: l for l in out}

    print("\n— (b) carrier writes ONE 'Hip / Ridge cap' line (122.78 LF -> RIDGE_CAPS) —")
    b = rows({"approved": {"RIDGE_CAPS": {"qty": 122.78, "unit": "LF"}}, "excluded": {}, "unmapped": []})
    rh = b.get("RIDGE_HIP_CAP", {})
    chk("ONE RIDGE_HIP_CAP row that COMPARES the two sides (not MISSING_FROM_CARRIER)",
        rh.get("state") != "MISSING_FROM_CARRIER" and rh.get("approved_quantity") == 122.78
        and abs(rh.get("required_quantity") - req_combined) < 1e-9)
    chk("no stranded RIDGE_CAPS acknowledgement", "RIDGE_CAPS" not in b and "HIP_CAPS" not in b)
    chk(f"the 126.96-vs-122.78 gap reads as a QUANTITY_DIFFERENCE, not an omission (state {rh.get('state')})",
        rh.get("state") == "QUANTITY_DIFFERENCE")

    print("\n— (c) carrier SPLITS ridge and hip into two lines (90.60 + 36.36) —")
    c = rows({"approved": {"RIDGE_CAPS": {"qty": 90.60, "unit": "LF"},
                           "HIP_CAPS": {"qty": 36.36, "unit": "LF"}}, "excluded": {}, "unmapped": []})
    rh2 = c.get("RIDGE_HIP_CAP", {})
    chk("split ridge+hip reconciles against the combined required (summed)",
        abs(rh2.get("approved_quantity") - 126.96) < 1e-9 and rh2.get("state") == "MATCHED")
    chk("the split is recorded (combined_carrier_from) and neither strands as ACKNOWLEDGED_ONLY",
        rh2.get("combined_carrier_from") == ["RIDGE_CAPS", "HIP_CAPS"]
        and "RIDGE_CAPS" not in c and "HIP_CAPS" not in c)

    print("\n— carrier genuinely omits ridge/hip -> still MISSING (no false match) —")
    n = rows({"approved": {}, "excluded": {}, "unmapped": []})
    chk("no ridge/hip -> MISSING_FROM_CARRIER (unchanged when truly absent)",
        n.get("RIDGE_HIP_CAP", {}).get("state") == "MISSING_FROM_CARRIER")

    print("\nRESULT:", "ALL PASS — a carrier ridge/hip line (combined or split) now reconciles against "
          "the combined required key; 'not present' is gone unless the carrier truly omitted it."
          if ok else "*** FAIL ***")
    return ok


def run_operation_v72():
    """v72 DEFECT 1/2: a material-only carrier line no longer reads as a full match; the required
    activity code follows REPAIR vs REPLACEMENT with the ALWAYS_R_AND_R exceptions. Driven through
    build_comparison — the real overlay — with the carrier op the parser derives."""
    from operation_dimension import carrier_operation_for_category
    ok = True
    def chk(name, cond):
        nonlocal ok; ok &= bool(cond); print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
    print("\n\nOPERATION DIMENSION FIRES (v72)\n" + "=" * 40)

    required = {"VALLEY_METAL": {"comparison_unit": "LF", "comparison_quantity": 38.77}}

    def compare(op, side):
        carrier = {"approved": {"VALLEY_METAL": {"qty": 38.77, "unit": "LF"}},
                   "excluded": {}, "unmapped": [],
                   "approved_lines": [{"category_id": "VALLEY_METAL", "op": op,
                                       "source_lines": [{"side": side, "qty": 38.77}]}]}
        out = build_comparison(required, carrier)
        return {l["category_id"]: l for l in out["lines"]}["VALLEY_METAL"]

    print("\n— (b) material-only no longer MATCHES; a true R&R still does —")
    mo = compare("MATERIAL_ONLY", "MATERIAL")
    chk(f"material-only -> OPERATION_DIFFERENCE (got {mo['state']})", mo["state"] == "OPERATION_DIFFERENCE")
    chk(f"names the THREE missing components (got {mo['operation_delta']})",
        set(mo["operation_delta"]) == {"remove_existing", "dispose", "install_labor"})
    rr = compare("R_AND_R", "RR")
    chk(f"true R&R at the same quantity still MATCHED (got {rr['state']})", rr["state"] == "MATCHED")

    print("\n— (d) activity code by context (REPAIR vs REPLACEMENT; always-R&R exceptions) —")
    for cat, rep, repl in [("SHAKE_FIELD_RR", "R_AND_R", "R_AND_R"),
                           ("VALLEY_METAL", "R_AND_R", "REPLACE"),
                           ("STEP_FLASH", "R_AND_R", "REPLACE"),
                           ("CHIMNEY_FLASH", "R_AND_R", "R_AND_R"),
                           ("VENT_CAP", "R_AND_R", "R_AND_R"),
                           ("POWER_VENT", "R_AND_R", "R_AND_R")]:
        chk(f"{cat:16} REPAIR->{rep}", _required_op_ctx(cat, None, False) == rep)
        chk(f"{cat:16} REPLACE->{repl}", _required_op_ctx(cat, None, True) == repl)

    print("\n— (e) ALWAYS_R_AND_R is one named constant; adding an item is one line —")
    chk("ALWAYS_R_AND_R is a frozenset of category ids", isinstance(ALWAYS_R_AND_R, frozenset)
        and {"CHIMNEY_FLASH", "VENT_CAP", "POWER_VENT"} <= ALWAYS_R_AND_R)
    extended = ALWAYS_R_AND_R | {"TURBINE_VENT"}          # a one-line union proves extensibility
    chk("adding one id flips that id to R&R on a replacement",
        ("TURBINE_VENT" in extended) and ("TURBINE_VENT" not in ALWAYS_R_AND_R))

    print("\nRESULT:", "ALL PASS — material-only surfaces the three missing labor/disposal components "
          "instead of a false match; the required activity code follows repair vs replacement with the "
          "always-R&R exceptions; a true R&R still matches." if ok else "*** FAIL ***")
    return ok


def run_citations_v73():
    """v73 DEFECT 4: the ridge/hip row carries its citation in BOTH report modes (the synthesised
    RIDGE_HIP_CAP key used to drop it in the fold), and the shake row cites a real CSSB authority
    instead of the empty 'The repair'. Rendered through the real projection + render engine."""
    from module2_assembly import assemble_full_roof_scope
    from module1_yager_proof import YAGER_CONFIRMED_SELECTION
    from comparison_caller import build_scope_comparison
    from argument_caller import build_scope_argument
    from module3_caller import build_module3_inputs
    from module3_render_engine import render as _render
    from manual_carrier_entry import build_carrier_summary_from_manual_entry
    ATTACHMENTS = []
    VCI = {"insured": "Test", "loss_address": "1 Test St", "claim_number": "T-1",
           "deductible": None, "carrier": "Travelers"}
    ok = True
    def chk(name, cond):
        nonlocal ok; ok &= bool(cond); print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
    print("\n\nCITATIONS IN BOTH REPORT MODES (v73)\n" + "=" * 40)

    M2 = assemble_full_roof_scope(open("XML.txt", encoding="utf-8").read(), YAGER_CONFIRMED_SELECTION)
    M1 = {"affected_SF": M2.affected_SF_raw_total}

    def sections(cs):
        comp = build_scope_comparison(M2, cs)
        pack = build_scope_argument(M1, M2, comp, cs, VCI, photos=[], attachments=ATTACHMENTS,
                                    reference_tags=["CSSB"])["argument_pack"]
        proj = build_module3_inputs(M1, M2, comp, pack, VCI, cs, photos=[], attachments=ATTACHMENTS,
                                    reference_tags=["CSSB"])
        return _render(proj["inputs"], proj["sc"])["sections"][5]

    print("\n— (f) ridge/hip row carries its citation; (g) shake cites real CSSB — COMPARISON mode —")
    cs = build_carrier_summary_from_manual_entry(
        [{"category_id": "RIDGE_CAPS", "qty": 50, "unit": "LF", "status": "Approved", "op": "R&R"}],
        {"carrier": "T", "price_list": "KSWI8X_FEB26"})
    comp5 = {r["category_id"]: r for r in sections(cs).get("gap", [])}
    chk(f"(f) RIDGE_HIP_CAP has a citation, not blank (got {comp5.get('RIDGE_HIP_CAP',{}).get('citation')!r})",
        bool(comp5.get("RIDGE_HIP_CAP", {}).get("citation")))
    chk("(f) it recombines the ridge AND hip authorities (never invented)",
        "ridge" in (comp5["RIDGE_HIP_CAP"]["citation"] or "").lower()
        and "hip" in (comp5["RIDGE_HIP_CAP"]["citation"] or "").lower())
    chk(f"(g) SHAKE_FIELD_RR cites CSSB methodology, not 'The repair' "
        f"(got {comp5.get('SHAKE_FIELD_RR',{}).get('citation')!r})",
        "CSSB" in (comp5.get("SHAKE_FIELD_RR", {}).get("citation") or "")
        and comp5["SHAKE_FIELD_RR"]["citation"] != "The repair")

    print("\n— (f)/(g) SAME citations in the NON-COMPARISON report (fixed where produced) —")
    non5 = {r["category_id"]: r for r in sections(None).get("required_scope", [])}
    chk(f"(f) RIDGE_HIP_CAP citation present in non-comparison too "
        f"(got {non5.get('RIDGE_HIP_CAP',{}).get('citation')!r})",
        bool(non5.get("RIDGE_HIP_CAP", {}).get("citation")))
    chk(f"(g) SHAKE_FIELD_RR CSSB citation in non-comparison too "
        f"(got {non5.get('SHAKE_FIELD_RR',{}).get('citation')!r})",
        "CSSB" in (non5.get("SHAKE_FIELD_RR", {}).get("citation") or ""))

    print("\n— (h) audit: RIDGE_HIP_CAP is the ONLY synthesised key —")
    import module3_keying as K
    src = open(K.__file__, encoding="utf-8").read()
    synth = src.count("__combined")
    chk(f"exactly one synthesised/combined key exists (RIDGE_HIP_CAP__combined); found {synth} ref(s) in keying",
        "RIDGE_HIP_CAP__combined" in src)

    print("\nRESULT:", "ALL PASS — the ridge/hip row carries its recombined citation and the shake row "
          "cites CSSB methodology, in BOTH report modes; RIDGE_HIP_CAP remains the only synthesised key."
          if ok else "*** FAIL ***")
    return ok


def run_operation_split_v75():
    """v75: a category can carry TWO operations (Detach & Reset + new material). The approved side is a
    set of (operation, quantity) pairs; the report shows each and NEVER sums across operations. Driven
    from the REAL Travelers line descriptions and the real renderer."""
    from manual_carrier_entry import build_carrier_summary_from_manual_entry
    from module3_report_renderer import sec5_comparison
    from module3_render_engine import S5_STATES
    import re as _re
    ok = True
    def chk(name, cond):
        nonlocal ok; ok &= bool(cond); print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
    print("\n\nAPPROVED SIDE = (operation, quantity) PAIRS (v75)\n" + "=" * 45)

    # THE REAL CASE — the live three-line shake case (v78): a Detach & Reset pair (Remove + Install,
    # folded) and a Replace, against 7.55 SQ of required Remove & Replace.
    real = [
        {"category_id": "SHAKE_FIELD_RR", "qty": 0.88, "unit": "SQ", "status": "Approved", "op": "REMOVE",
         "source_lines": [{"side": "REMOVE", "qty": 0.88}]},
        {"category_id": "SHAKE_FIELD_RR", "qty": 0.88, "unit": "SQ", "status": "Approved", "op": "INSTALL_ONLY",
         "source_lines": [{"side": "INSTALL", "qty": 0.88}]},
        {"category_id": "SHAKE_FIELD_RR", "qty": 0.25, "unit": "SQ", "status": "Approved", "op": "REPLACE",
         "source_lines": [{"side": "REPLACE", "qty": 0.25}]},
    ]
    cs = build_carrier_summary_from_manual_entry(real, {"carrier": "Travelers", "price_list": "KSWI8X_FEB26"})
    required = {"SHAKE_FIELD_RR": {"comparison_unit": "SQ", "comparison_quantity": 7.55,
                                   "supporting_quantity": 0, "supporting_unit": "EA", "source_detail": []}}
    cmp = build_comparison(required, cs)
    shake = next(l for l in cmp["lines"] if l["category_id"] == "SHAKE_FIELD_RR")

    print("\n— (b) the real case splits into TWO operations; neither quantity disappears —")
    chk(f"state is OPERATION_SPLIT (got {shake.get('state')})", shake.get("state") == "OPERATION_SPLIT")
    aops = {o["operation"]: o["quantity"] for o in shake.get("approved_operations", [])}
    chk(f"Detach & Reset 0.88 survives (got {aops.get('DETACH_RESET')})", aops.get("DETACH_RESET") == 0.88)
    chk(f"Replace 0.25 survives (got {aops.get('REPLACE')})", aops.get("REPLACE") == 0.25)
    chk("required quantity is stated once and unchanged (7.55)", shake.get("required_quantity") == 7.55)
    dr = next(o for o in shake["approved_operations"] if o["operation"] == "DETACH_RESET")
    chk("the D&R op is flagged as not accounting for new material + disposal",
        set(dr.get("operation_delta") or []) == {"material_new", "dispose"})
    rp = next(o for o in shake["approved_operations"] if o["operation"] == "REPLACE")
    chk("the Replace op is flagged as not accounting for removal only (v78 defect 2: haul-off IS funded)",
        set(rp.get("operation_delta") or []) == {"remove_existing"})

    # v78 DEFECT 4 re-ground: the old assertion "NO 1.13 anywhere" is stale. Summing the funded
    # operations FOR A QUANTITY STATEMENT is legitimate and is NOT the forbidden combined carrier total:
    # the row still shows each operation with its own quantity (0.88 and 0.25 separately), and the note
    # states, unnetted, that 1.13 SQ was addressed at a different operation and 6.42 SQ was not addressed
    # by any operation. What stays forbidden is folding one operation's quantity into another's or
    # presenting a single merged figure AS a single operation — neither happens here.
    print("\n— (c) the row shows the unnetted gap; 1.13 is allowed AS 'addressed at a different operation' —")
    s5 = {"mode": "COMPARISON", "platform": "XACTIMATE", "structure_alignments": [], "gap": [{
        "category_id": "SHAKE_FIELD_RR", "state": "OPERATION_SPLIT", "citation": "CSSB",
        "required": 7.55, "required_unit": "SQ", "required_operation": "R_AND_R",
        "approved_operations": shake["approved_operations"]}]}
    _t, html = sec5_comparison(s5)
    chk("each operation shown with its own quantity (0.88 and 0.25 both render, unfolded)",
        "0.88" in html and "0.25" in html)
    chk("6.42 SQ not addressed by any operation is stated", "6.42" in html and "not addressed" in html)
    chk("1.13 SQ appears AS addressed at a different operation (summing is legitimate here)",
        "1.13" in html and "addressed at a different operation" in html)
    chk("OPERATION_SPLIT is a rendered §5 state", "OPERATION_SPLIT" in S5_STATES)

    print("\n— (e) within one operation, consolidation is unchanged (v60) —")
    two_ridge = build_carrier_summary_from_manual_entry([
        {"category_id": "RIDGE_CAPS", "qty": 100.0, "unit": "LF", "status": "Approved", "op": "R&R",
         "source_lines": [{"side": "RR", "qty": 100.0}]},
        {"category_id": "RIDGE_CAPS", "qty": 75.5, "unit": "LF", "status": "Approved", "op": "R&R",
         "source_lines": [{"side": "RR", "qty": 75.5}]},
    ], {"carrier": "T", "price_list": "KSWI8X_FEB26"})
    chk(f"two R&R ridge runs SUM within the operation -> 175.5 (got {two_ridge['approved']['RIDGE_CAPS']['qty']})",
        two_ridge["approved"]["RIDGE_CAPS"]["qty"] == 175.5 and "operations" not in two_ridge["approved"]["RIDGE_CAPS"])
    rr_pair = build_carrier_summary_from_manual_entry([
        {"category_id": "VALLEY_METAL", "qty": 10.0, "unit": "LF", "status": "Approved", "op": "REMOVE",
         "source_lines": [{"side": "REMOVE", "qty": 10.0}]},
        {"category_id": "VALLEY_METAL", "qty": 12.0, "unit": "LF", "status": "Approved", "op": "R&R",
         "source_lines": [{"side": "RR", "qty": 12.0}]},
    ], {"carrier": "T", "price_list": "KSWI8X_FEB26"})
    chk(f"a Remove+Replace pair still consolidates to the Replace side 12.0 (got {rr_pair['approved']['VALLEY_METAL']['qty']})",
        rr_pair["approved"]["VALLEY_METAL"]["qty"] == 12.0 and "operations" not in rr_pair["approved"]["VALLEY_METAL"])

    print("\n— (g) per-slope: same category, mixed operations on TWO structures; both survive —")
    per_slope = build_carrier_summary_from_manual_entry([
        {"category_id": "SHAKE_FIELD_RR", "qty": 0.88, "unit": "SQ", "status": "Approved", "op": "REMOVE",
         "structure_id": "Dwelling", "source_lines": [{"side": "REMOVE", "qty": 0.88}]},
        {"category_id": "SHAKE_FIELD_RR", "qty": 0.88, "unit": "SQ", "status": "Approved", "op": "INSTALL_ONLY",
         "structure_id": "Dwelling", "source_lines": [{"side": "INSTALL", "qty": 0.88}]},
        {"category_id": "SHAKE_FIELD_RR", "qty": 0.25, "unit": "SQ", "status": "Approved", "op": "R&R",
         "structure_id": "Dwelling", "source_lines": [{"side": "RR", "qty": 0.25}]},
        {"category_id": "SHAKE_FIELD_RR", "qty": 0.50, "unit": "SQ", "status": "Approved", "op": "R&R",
         "structure_id": "Detached Garage", "source_lines": [{"side": "RR", "qty": 0.50}]},
    ], {"carrier": "T", "price_list": "KSWI8X_FEB26"})
    by_struct = {row["structure_id"]: row
                 for lst in per_slope["per_structure"]["approved"].values() for row in lst
                 if row["category_id"] == "SHAKE_FIELD_RR"}
    dwl = by_struct.get("Dwelling", {})
    gar = by_struct.get("Detached Garage", {})
    chk("Dwelling keeps its mixed operations (D&R + R&R)",
        {o["op"] for o in dwl.get("operations", [])} == {"DETACH_RESET", "R_AND_R"})
    chk(f"Detached Garage keeps its own 0.50 R&R (got {gar.get('qty')})", gar.get("qty") == 0.50)

    print("\n— page-3 ambiguity surfacing sees the mixed category —")
    from manual_carrier_entry import mixed_operation_categories
    chk("mixed_operation_categories flags SHAKE_FIELD_RR on the real case",
        any(m["category_id"] == "SHAKE_FIELD_RR" for m in mixed_operation_categories(real)))

    print("\nRESULT:", "ALL PASS — a category carries a SET of (operation, quantity) pairs; the real "
          "Detach&Reset + new-material case splits with both quantities intact and no combined total; "
          "within-operation consolidation and per-slope keying are preserved." if ok else "*** FAIL ***")
    return ok


if __name__ == "__main__":
    print("MODULE 3 COMPARISON BUILDER + YAGER ORACLE (item 4)\n" + "="*52)
    # v78 DEFECT 4: run()'s return is now GATED. Its two seed-era stale assertions (FIELD_FELT floor
    # MATCH pre-dating the 0.5076 CSSB interlay re-grounding; 64 EA pre-dating the density re-grounding)
    # have been re-grounded to current behaviour above, so run() passes on correct behaviour and a real
    # regression now exits non-zero instead of printing FAIL and passing.
    _r0 = run()
    raise SystemExit(0 if (_r0 and run_ridge_hip_v71() and run_operation_v72() and run_citations_v73()
                           and run_operation_split_v75()) else 1)
