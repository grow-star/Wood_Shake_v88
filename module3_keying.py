#!/usr/bin/env python3
"""Production home for Module 3 keying / normalization.

Extracted verbatim from module3_keying_regression.py so production code no
longer imports from a regression suite.
"""

def key_and_normalize(m2_lines, affected_SF):
    totals, units, detail = {}, {}, {}
    # v77 DEFECT 5: per-label breakdown within a category. GROUP BY THE USER'S LABEL — a user-placed,
    # user-labelled item (citation 'user-defined', e.g. '6" pipe jack') is a distinct row from the
    # generic category item, and identical labels combine. Matched on label text with case and
    # surrounding whitespace ignored, and nothing else (no fuzzy matching).
    labels = {}   # cid -> { casefold(label) : {"label": str, "qty": float, "unit": str, "user_defined": bool} }
    shake_ea = 0.0
    for l in m2_lines:
        if l.category_id != "SHAKE_FIELD_RR":
            _lab = str(getattr(l, "item", l.category_id) or l.category_id)
            _ud = (getattr(l, "citation", None) == "user-defined")
            _lm = labels.setdefault(l.category_id, {})
            _e = _lm.setdefault(_lab.strip().casefold(),
                                {"label": _lab, "qty": 0.0, "unit": l.unit, "user_defined": False,
                                 "citation": getattr(l, "citation", None)})
            _e["qty"] = round(_e["qty"] + l.qty, 4)
            _e["user_defined"] = _e["user_defined"] or _ud
        if l.category_id == "SHAKE_FIELD_RR":
            # SHAKE compares in SQ (affected_SF/100, the §2.4.2 dual value); the EA count is SUPPORTING
            # only. A mixed roof (v61) carries BOTH a replacement SQ line and a repair EA line under
            # this one id — legitimately two units — so SHAKE is exempt from the single-unit total and
            # guard below. The SQ replacement area is already inside affected_SF; only the EA repair
            # count is summed here, as the supporting figure.
            if str(l.unit) == "EA":
                shake_ea = round(shake_ea + l.qty, 4)
            totals.setdefault("SHAKE_FIELD_RR", 0.0)
            detail.setdefault("SHAKE_FIELD_RR", []).append((l.item, l.qty, l.unit))
            continue
        totals[l.category_id] = round(totals.get(l.category_id, 0.0) + l.qty, 4)
        units.setdefault(l.category_id, l.unit)
        if units[l.category_id] != l.unit:
            raise ValueError(f"unit conflict within {l.category_id}")   # would be unit_mismatch
        detail.setdefault(l.category_id, []).append((l.item, l.qty, l.unit))

    entries = {}
    for cid, tot in totals.items():
        if cid == "SHAKE_FIELD_RR":
            entries[cid] = {                       # dual value (§2.4.2)
                "comparison_quantity": round(affected_SF / 100.0, 4), "comparison_unit": "SQ",
                "supporting_quantity": shake_ea, "supporting_unit": "EA",
                "source_detail": detail[cid]}
        else:
            entries[cid] = {"comparison_quantity": tot, "comparison_unit": units[cid],
                            "source_detail": detail[cid],
                            "labels": list(labels.get(cid, {}).values())}

    # ridge/hip combine (§2.4.3): required RIDGE_CAPS + HIP_CAPS -> combined key
    if "RIDGE_CAPS" in totals or "HIP_CAPS" in totals:
        entries["RIDGE_HIP_CAP__combined"] = {
            "comparison_quantity": round(totals.get("RIDGE_CAPS",0.0) + totals.get("HIP_CAPS",0.0), 2),
            "comparison_unit": "LF", "combined_from": ["RIDGE_CAPS","HIP_CAPS"],
            "source_detail": [("RIDGE_CAPS", totals.get("RIDGE_CAPS",0.0)),
                              ("HIP_CAPS",  totals.get("HIP_CAPS",0.0))]}
    return entries, totals

