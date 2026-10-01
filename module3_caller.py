#!/usr/bin/env python3
"""Module 3 render-prep caller.

Projection only: turns real upstream outputs into the Module 3 renderer read-map
contract. It performs no geometry, scope, comparison, or prose authoring.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Optional, Sequence

from module3_render_engine import render

DIAGRAM_PENDING = "DIAGRAM_PENDING_PAGE2"


def build_module3_inputs(
    module1_result: Any,
    module2_result: Any,
    comparison_result: Optional[Mapping[str, Any]],
    argument_pack: Mapping[str, Any],
    verified_claim_info: Mapping[str, Any],
    carrier_summary: Optional[Mapping[str, Any]],
    photos: Optional[Sequence[Any]] = None,
    attachments: Optional[Sequence[Mapping[str, Any]]] = None,
    reference_tags: Optional[Sequence[str]] = None,
    diagram_pct: Optional[float] = None,
    non_roof_summary: Optional[Mapping[str, Any]] = None,
) -> Mapping[str, Any]:
    """Project locked upstream outputs into the renderer read-map contract.

    diagram_pct: the authoritative percentage of the roof affected, from the SAME diagram data the
    page-2 totals come from. Optional — when absent the renderer OMITS the phrase rather than
    printing a placeholder token.
    """
    sc = _project_scope_comparison(comparison_result, module2_result)
    # v72 DEFECT 2 (no-haul-off): carry the carrier-derived stated gaps into the comparison section.
    if isinstance(carrier_summary, Mapping) and carrier_summary.get("stated_gaps"):
        sc = {**dict(sc), "stated_gaps": list(carrier_summary.get("stated_gaps"))}
    css = _project_css(comparison_result, carrier_summary)
    inputs = {
        "VCI": dict(verified_claim_info),
        "M1": _project_m1(module1_result, module2_result, diagram_pct),
        "M2": _project_m2(module2_result, argument_pack, reference_tags, verified_claim_info.get("roof_structure_id")),
        "CSS": css,
        "SC": sc,
        "P2": _project_p2(sc, css),
        "P3": _project_p3(argument_pack, photos, attachments, non_roof_summary),
    }
    return {"status": "MODULE3_INPUTS_READY", "inputs": inputs, "sc": sc, "diagram_status": DIAGRAM_PENDING}


def render_module3_report(module3_projection: Mapping[str, Any]) -> Mapping[str, Any]:
    """Run the production render engine on an already-built projection."""
    return render(module3_projection["inputs"], module3_projection["sc"])


def _project_scope_comparison(comparison_result: Optional[Mapping[str, Any]], module2_result: Any) -> Mapping[str, Any]:
    if comparison_result and comparison_result.get("status") == "CARRIER_NEEDS_ESTIMATE_SELECTION":
        return {"mode": "REQUIRED_SCOPE_ONLY", "comparison_precondition": "CARRIER_NEEDS_ESTIMATE_SELECTION",
                "lines": [], "required_scope": _required_scope_from_module2(module2_result),
                "shake_dual": _shake_dual_from_required(comparison_result.get("required")),
                "structure_alignments": []}
    # The carrier's building names do not line up with the scoped structures — the comparison is
    # withheld and the required scope is presented one-sided, the same graceful degradation the
    # multi-estimate gate uses. The renderer states WHY (the mapping is unset) rather than guessing.
    if comparison_result and comparison_result.get("status") == "CARRIER_NEEDS_STRUCTURE_MAPPING":
        return {"mode": "REQUIRED_SCOPE_ONLY", "comparison_precondition": "CARRIER_NEEDS_STRUCTURE_MAPPING",
                "lines": [], "required_scope": _required_scope_from_module2(module2_result),
                "shake_dual": _shake_dual_from_required(comparison_result.get("required")),
                "unmapped_carrier_structures": list(comparison_result.get("unmapped_carrier_structures") or ()),
                "scoped_structures_without_carrier": list(comparison_result.get("scoped_structures_without_carrier") or ()),
                "structure_alignments": []}

    comparison = None
    if comparison_result:
        comparison = comparison_result.get("scope_comparison", comparison_result)
    if not isinstance(comparison, Mapping):
        comparison = {"mode": "REQUIRED_SCOPE_ONLY", "comparison_precondition": "NO_RESOLVED_COMPARISON", "lines": []}

    sc = dict(comparison)
    sc.setdefault("mode", "REQUIRED_SCOPE_ONLY")
    sc.setdefault("lines", [])
    sc.setdefault("comparison_precondition", "NO_RESOLVED_COMPARISON")
    sc.setdefault("estimate_name", _estimate_name(comparison_result))
    sc.setdefault("structure_alignments", [{"program_structure_id": "DWELLING", "carrier_structure_id": "DWELLING", "confirmed": True}]
                  if sc.get("mode") == "COMPARISON" else [])
    sc["lines"] = [_line_with_render_defaults(line) for line in sc.get("lines", [])]
    sc.setdefault("shake_dual", _shake_dual_from_lines(sc["lines"], comparison_result))
    sc.setdefault("required_scope", _required_scope_from_comparison(comparison_result, module2_result))
    # PER-STRUCTURE §5: carry each scoped structure's own comparison lines through to the renderer. The
    # heading is resolved downstream from M2.structure_blocks (ONE heading authority for §3 and §5).
    # Absent for a single-structure roof, so §5 renders byte-identically.
    if comparison_result and comparison_result.get("structure_comparisons"):
        sc["structure_comparisons"] = [
            {"structure_id": b.get("structure_id"),
             "mode": (b.get("scope_comparison") or {}).get("mode", "COMPARISON"),
             "lines": [_line_with_render_defaults(line)
                       for line in ((b.get("scope_comparison") or {}).get("lines") or [])]}
            for b in comparison_result["structure_comparisons"]]
    return sc


def _project_css(comparison_result: Optional[Mapping[str, Any]], carrier_summary: Optional[Mapping[str, Any]]) -> Optional[Mapping[str, Any]]:
    if carrier_summary is None:
        return None
    if comparison_result and comparison_result.get("status") == "CARRIER_NEEDS_ESTIMATE_SELECTION":
        return {
            "present": True,
            "parser_status": "NEEDS_CONFIRMATION",
            "acknowledged": dict(carrier_summary.get("acknowledged", {})),
            "reference_totals": dict(carrier_summary.get("reference_totals", {})),
            "platform_identity": _platform_identity(carrier_summary),
        }
    if not comparison_result or comparison_result.get("status") not in ("COMPARISON_READY", "REQUIRED_SCOPE_ONLY"):
        return None
    if comparison_result.get("status") != "COMPARISON_READY":
        return None
    return {
        "present": True,
        "parser_status": carrier_summary.get("parser_status", "SUCCESS"),
        "input_state": carrier_summary.get("input_state"),
        "acknowledged": dict(carrier_summary.get("acknowledged", {})),
        "reference_totals": dict(carrier_summary.get("reference_totals", {})),
        "platform_identity": _platform_identity(carrier_summary),
    }


def _project_m1(module1_result: Any, module2_result: Any, diagram_pct: Optional[float] = None) -> Mapping[str, Any]:
    return {
        "affected_polygons": DIAGRAM_PENDING,
        "affected_SF": {"total": _affected_display(module2_result)},
        "facet_valley_assignments": DIAGRAM_PENDING,
        # The real number, from the SAME diagram data the totals come from. DIAGRAM_PENDING_PAGE2 was
        # a leftover from when the diagram was a stub and page-2 data did not exist. It does now.
        # If it is genuinely unavailable the renderer OMITS the phrase — it never prints a token.
        "authoritative_pct": ({"of roof": f"{float(diagram_pct):.2f}%"} if diagram_pct is not None else {}),
        # v63 DEFECT 4: §4 needs to know the roof is (partly) a replacement so it can draw it as
        # replaced and show the legend swatch. Designators from the SAME source §3 uses.
        "replacement_facets": (list(getattr(module2_result, "replacement_facets", ()) or ())
                               if not isinstance(module2_result, Mapping)
                               else list(module2_result.get("replacement_facets", ()) or ())),
    }


def _project_m2(module2_result: Any, argument_pack: Mapping[str, Any], reference_tags: Optional[Sequence[str]], roof_structure_id: Optional[str] = None) -> Mapping[str, Any]:
    def _facets(name):
        if isinstance(module2_result, Mapping):
            return list(module2_result.get(name, ()) or ())
        return list(getattr(module2_result, name, ()) or ())
    return {
        "required_lines": _m2_required_lines(module2_result),
        "required_lines_by_structure": _m2_required_lines_by_structure(module2_result),
        # v69: ordered per-structure blocks for §2's dual and §3's slope callouts (empty for a single
        # structure, so those sections render byte-identically).
        "structure_blocks": _structure_blocks(module2_result, roof_structure_id),
        "per_shake_reasoning": argument_pack.get("per_shake_labor_explanation") or argument_pack.get("wood_shake_method_explanation"),
        "citations": list(reference_tags or ()),
        "material_list_ref": "Material list (internal estimating support)",
        # v61 full slope replacement: which facets are replacement vs repair (designators).
        "replacement_facets": _facets("replacement_facets"),
        "repair_facets": _facets("repair_facets"),
        # v71 DEFECT 3: eave ICE & WATER metadata (basis, coverage, layer count) or None. The report
        # cites the basis and states the layer count as a consequence; it never narrates a defaulted
        # soffit (that warning lives on page 2).
        "eave_iws": (module2_result.get("eave_iws") if isinstance(module2_result, Mapping)
                     else getattr(module2_result, "eave_iws", None)),
    }


def _structure_blocks(module2_result: Any, roof_structure_id: Optional[str]) -> Sequence[Mapping[str, Any]]:
    """Ordered per-structure blocks for §2 (affected area + shake quantity) and §3 (slope callouts).
    EMPTY unless the roof has 2+ structures, so single-structure reports render byte-identically.

    ORDERING: the structure the roof measurements represent (the user-asserted roof_structure_id) comes
    FIRST — it is the dwelling; the subordinate structures follow, ordered by the trailing integer of
    their ROOF id (ROOF1, ROOF2, ...) as a deterministic tiebreak. When no structure was asserted, the
    one with the most facets leads (still the dwelling), then the same tiebreak."""
    def _get(name):
        return (module2_result.get(name, ()) if isinstance(module2_result, Mapping)
                else getattr(module2_result, name, ())) or ()
    by_lines = {s: ls for s, ls in _get("aggregated_scope_by_structure")}
    if len(by_lines) < 2:
        return ()
    counts = dict(_get("structure_facet_counts"))
    affected = dict(_get("structure_affected_SF"))
    repl_by = {s: list(v) for s, v in _get("replacement_facets_by_structure")}
    rep_by = {s: list(v) for s, v in _get("repair_facets_by_structure")}
    # HEADING tracks SIZE (the largest structure is the dwelling) — consistent with §3's material list.
    # ORDER tracks the ASSERTED structure the measurements represent (roof_structure_id), which comes
    # first; usually that IS the largest, so the two coincide. Subordinate structures follow by the
    # trailing integer of their ROOF id.
    dwelling_by_size = max(counts, key=lambda s: counts.get(s, 0)) if counts else None
    primary = roof_structure_id if roof_structure_id in by_lines else dwelling_by_size

    import re as _re
    def _tiebreak(s):
        m = _re.search(r"(\d+)$", str(s))
        return (0, int(m.group(1))) if m else (1, str(s))
    ordered = sorted(by_lines, key=lambda s: (0, ()) if s == primary else (1, _tiebreak(s)))

    detached_n = 0
    out = []
    for sid in ordered:
        n = counts.get(sid, 0)
        if sid == dwelling_by_size:
            heading = f"Dwelling — {n} facets" if n else "Dwelling"
        else:
            detached_n += 1
            suffix = f" {detached_n}" if (len(ordered) - 1) > 1 else ""
            heading = f"Detached structure{suffix} — {n} facets" if n else f"Detached structure{suffix}"
        lines = by_lines[sid]
        shake_sq = next((_field(l, "qty") for l in lines if _field(l, "category_id") == "SHAKE_FIELD_RR" and _field(l, "unit") == "SQ"), None)
        shake_ea = next((_field(l, "qty") for l in lines if _field(l, "category_id") == "SHAKE_FIELD_RR" and _field(l, "unit") == "EA"), None)
        out.append({
            "structure_id": sid,
            "heading": heading,
            "affected_SQ": round(float(affected.get(sid, 0.0)) / 100.0, 4),
            "shake_SQ": shake_sq,
            "shake_EA": shake_ea,
            "replacement_facets": list(repl_by.get(sid, [])),
            "repair_facets": list(rep_by.get(sid, [])),
        })
    return tuple(out)


def _project_p2(sc: Mapping[str, Any], css: Optional[Mapping[str, Any]]) -> Mapping[str, Any]:
    return {"confirmed_carrier": bool(css), "confirmed_loss_location": True, "selected_estimate": sc.get("estimate_name")}


def _project_p3(argument_pack: Mapping[str, Any], photos: Optional[Sequence[Any]], attachments: Optional[Sequence[Mapping[str, Any]]], non_roof_summary: Optional[Mapping[str, Any]] = None) -> Mapping[str, Any]:
    photo_list = list(photos or ())
    return {
        # A photo may now be a real image: {"src": <data URL>, "caption": ...}. The key used to be
        # id/filename and the dict was STRINGIFIED, so an actual image could never reach §6 — the
        # renderer received "{'src': ..., 'caption': ...}" and drew a placeholder box. Prefer the
        # src, so the report can embed the picture. A plain string still behaves exactly as before.
        "photos": [(p.get("src") or p.get("id") or p.get("filename") or str(p))
                   if isinstance(p, Mapping) else str(p) for p in photo_list],
        "captions": {(p.get("src") or p.get("id") or p.get("filename") or str(p)): p.get("caption", "")
                     for p in photo_list if isinstance(p, Mapping)},
        "summary_prose": argument_pack.get("lead_summary", ""),
        "argument_prose": argument_pack.get("lead_summary", ""),
        "attachments": _attachments(attachments),
        "adjuster_email_subject": argument_pack.get("adjuster_email_subject", ""),
        "adjuster_email_body": argument_pack.get("adjuster_email_body", ""),
        # v66: honest acknowledgment that the whole estimate was read. Names the non-roof trades and a
        # count; renders nothing when there are none. No pricing, no conclusions.
        "non_roof_ack": (dict(non_roof_summary) if (non_roof_summary and non_roof_summary.get("count")) else None),
    }


def _one_line(line: Any) -> Mapping[str, Any]:
    category_id = _field(line, "category_id")
    return {
        "item": _field(line, "item", category_id),
        "category_id": category_id,
        "xact_code": _field(line, "xact_code", None),
        "citation": _field(line, "citation", None),
        "qty": _field(line, "qty"),
        "unit": _field(line, "unit"),
        "gate": _field(line, "gate", "module2"),
    }


def _m2_required_lines_by_structure(module2_result: Any) -> Sequence[Mapping[str, Any]]:
    """Per-structure material lists for the report's §3. EMPTY unless the roof has 2+ structures, so a
    single-structure roof renders exactly as before (the renderer falls back to the flat required_lines
    and the output is byte-identical). Each entry carries a human heading and the structure's own lines.
    The largest structure (most facets) is the Dwelling; the rest are Detached structures."""
    by_structure = (module2_result.get("aggregated_scope_by_structure", ()) if isinstance(module2_result, Mapping)
                    else getattr(module2_result, "aggregated_scope_by_structure", ()))
    if len(by_structure) < 2:
        return ()
    counts = dict((module2_result.get("structure_facet_counts", ()) if isinstance(module2_result, Mapping)
                   else getattr(module2_result, "structure_facet_counts", ())) or ())
    # The structure with the most facets is the main dwelling; others are detached (garage/shop/etc.).
    dwelling_sid = max(counts, key=lambda s: counts.get(s, 0)) if counts else None
    detached_n = 0
    out = []
    for sid, lines in by_structure:
        n = counts.get(sid, 0)
        if sid == dwelling_sid:
            heading = f"Dwelling — {n} facets" if n else "Dwelling"
        else:
            detached_n += 1
            suffix = f" {detached_n}" if len(by_structure) > 2 else ""
            heading = f"Detached structure{suffix} — {n} facets" if n else f"Detached structure{suffix}"
        out.append({"structure_id": sid, "facet_count": n, "heading": heading,
                    "lines": [_one_line(l) for l in lines]})
    return tuple(out)


def _m2_required_lines(module2_result: Any) -> Sequence[Mapping[str, Any]]:
    out = []
    for line in _aggregated_scope(module2_result):
        category_id = _field(line, "category_id")
        out.append({
            "item": _field(line, "item", category_id),
            "category_id": category_id,
            "xact_code": _field(line, "xact_code", None),
            # The AUTHORITY for this item — what puts it in a proper repair. §5 shows it instead of
            # the tool's bare assertion that something is "required".
            "citation": _field(line, "citation", None),
            "qty": _field(line, "qty"),
            "unit": _field(line, "unit"),
            "gate": _field(line, "gate", "module2"),
            # (There used to be a SECOND "citation" key here assigning the GATE — a duplicate dict
            # key that silently overwrote the real citation with "AUTO"/"CONFIRM". It is why the
            # authority column could only ever have shown the gate. Removed.)
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


def _affected_display(module2_result: Any) -> Any:
    for name in ("affected_SF_display_total", "affected_sf_display_total", "affected_SF", "affected_sf"):
        if hasattr(module2_result, name):
            return getattr(module2_result, name)
        if isinstance(module2_result, Mapping) and name in module2_result:
            return module2_result[name]
    return None


def _required_scope_from_comparison(comparison_result: Optional[Mapping[str, Any]], module2_result: Any) -> Sequence[Mapping[str, Any]]:
    if comparison_result and comparison_result.get("required"):
        return _required_scope_from_required_map(comparison_result["required"], module2_result)
    return _required_scope_from_module2(module2_result)


def _scope_citation_map(module2_result: Any) -> Mapping[str, Any]:
    """{category_id -> Module-2 citation}, plus the folded RIDGE_HIP_CAP (§ v73 DEFECT 4). The same
    authority §5 uses, so the NON-comparison report's 'why' column is populated too — the blank
    ridge/hip cell appeared in both modes because required_scope carried no citation at all."""
    m = {}
    for line in _aggregated_scope(module2_result):
        m[_field(line, "category_id")] = _field(line, "citation", None)
    seen = []
    for c in ("RIDGE_CAPS", "HIP_CAPS"):
        if m.get(c) and m[c] not in seen:
            seen.append(m[c])
    if seen:
        m["RIDGE_HIP_CAP"] = "; ".join(seen)
    return m


def _required_scope_from_required_map(required: Mapping[str, Mapping[str, Any]], module2_result: Any = None) -> Sequence[Mapping[str, Any]]:
    cites = _scope_citation_map(module2_result) if module2_result is not None else {}
    # v85 DEFECT — the required-material-scope table (§4) must list each required item ONCE. A combined
    # key (today only RIDGE_HIP_CAP__combined) carries the SUMMED quantity and names its components in
    # `combined_from`; module3_keying leaves those component keys (RIDGE_CAPS / HIP_CAPS) in the required
    # map beside the combined entry. §5 already folds the components out (module3_comparison_oracle._FOLD);
    # §4 did not, so it printed the ridge/hip quantity twice — once as each component, once as the combined
    # line wearing a second name. Fold the components out here too, taking the set to drop from the combined
    # entry's OWN `combined_from`, so what is folded is exactly what was combined — and only when the
    # combined key is present (a lone component, which module3_keying never emits, would be left untouched).
    # This removes duplicate ROWS only: no quantity is read, summed, or altered — the combined line already
    # carries the correct total that §5 renders.
    folded = {comp for val in required.values() for comp in (val.get("combined_from") or ())}
    return tuple({"category_id": (cat := ("RIDGE_HIP_CAP" if key == "RIDGE_HIP_CAP__combined" else key)),
                  "quantity": val.get("comparison_quantity"), "unit": val.get("comparison_unit"),
                  "citation": cites.get(cat)}
                 for key, val in required.items() if key not in folded)


def _required_scope_from_module2(module2_result: Any) -> Sequence[Mapping[str, Any]]:
    cites = _scope_citation_map(module2_result)
    return tuple({"category_id": _field(line, "category_id"), "quantity": _field(line, "qty"),
                  "unit": _field(line, "unit"), "citation": cites.get(_field(line, "category_id"))}
                 for line in _aggregated_scope(module2_result))


def _shake_dual_from_lines(lines: Sequence[Mapping[str, Any]], comparison_result: Optional[Mapping[str, Any]]) -> Optional[Mapping[str, Any]]:
    for line in lines:
        if line.get("category_id") == "SHAKE_FIELD_RR":
            return {"comparison_quantity": line.get("required_quantity"), "comparison_unit": line.get("required_unit", "SQ"),
                    "supporting_quantity": line.get("supporting_quantity"), "supporting_unit": line.get("supporting_unit")}
    if comparison_result:
        return _shake_dual_from_required(comparison_result.get("required"))
    return None


def _shake_dual_from_required(required: Optional[Mapping[str, Mapping[str, Any]]]) -> Optional[Mapping[str, Any]]:
    if not required or "SHAKE_FIELD_RR" not in required:
        return None
    shake = required["SHAKE_FIELD_RR"]
    return {"comparison_quantity": shake.get("comparison_quantity"), "comparison_unit": shake.get("comparison_unit"),
            "supporting_quantity": shake.get("supporting_quantity"), "supporting_unit": shake.get("supporting_unit")}


def _line_with_render_defaults(line: Mapping[str, Any]) -> Mapping[str, Any]:
    out = dict(line)
    out.setdefault("citation", "Module 2")
    out.setdefault("carrier_source_lines", [])
    return out


def _estimate_name(comparison_result: Optional[Mapping[str, Any]]) -> Optional[str]:
    if not comparison_result:
        return None
    return comparison_result.get("estimate_name") or comparison_result.get("selected_estimate") or "Estimate"


def _platform_identity(carrier_summary: Mapping[str, Any]) -> Mapping[str, Any]:
    advisory = carrier_summary.get("advisory", {}) if isinstance(carrier_summary.get("advisory"), Mapping) else {}
    return {"platform": carrier_summary.get("platform"),
            "inferred_platform": advisory.get("inferred_platform"),
            "inferred_confidence": advisory.get("inferred_confidence"),
            "inferred_basis": advisory.get("inferred_basis")}


def _attachments(attachments: Optional[Sequence[Mapping[str, Any]]]) -> Sequence[Mapping[str, Any]]:
    if attachments is not None:
        return tuple(dict(a) for a in attachments)
    return (
        {"label": "EagleView Report", "source": "system", "included": True},
        {"label": "Carrier Loss Statement", "source": "system", "included": True},
        {"label": "Repair Estimate", "source": "user_upload", "included": True},
        {"label": "Full Replacement Estimate", "source": "user_upload", "included": True},
        {"label": "Photographs", "source": "system", "included": True},
    )
