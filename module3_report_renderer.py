#!/usr/bin/env python3
"""
MODULE 3 — REPORT PROTOTYPE RENDERER  (first template)
======================================================
Turns the §3.1 section projection into a professional, standardized HTML report.
This is PRESENTATION ONLY — it adds no logic, no calculation, no state assignment.
It consumes the already-projected section data from the proven, contract-obeying
reference renderer (`render()` in module3_render_engine), so it
cannot drift from the §3.1 read-map. Sample data is the existing seed oracle.

Scope guards honored: no fancy visual design, no new logic/calc, no F9, no
Authority Library / code automation, no policy interpretation. Module 1/2, the
parser, and the comparison builder are imported/frozen — not modified.

Outputs: module3_report_sample_comparison.html
         module3_report_sample_required_scope_only.html
"""

import html
from module3_render_engine import render
from module2_scope_expansion import CSSB_INTERLAYMENT_STRIP_IN   # ONE authority for the 18" strip width
from operation_dimension import OP_LABEL, delta_phrase

# v72 DEFECT 3: platform-specific activity vocabulary. Xactimate and Symbility name the same operation
# differently; the argument must cite the platform the carrier actually used. UNKNOWN/MANUAL -> not in
# this map, so _operation_note falls back to the neutral OP_LABEL (nothing platform-specific).
_PLATFORM_ACTIVITY = {
    "XACTIMATE": {
        "R_AND_R": "R&R", "REPLACE": "Replace (+)", "REMOVE": "Remove (-)",
        "DETACH_RESET": "Detach & Reset (R)", "MATERIAL_ONLY": "material only (M)",
        "INSTALL_ONLY": "Install (I)", "TEAR_OFF": "Tear-off",
    },
    "SYMBILITY": {
        "R_AND_R": "Replace (w/ removal)", "REPLACE": "Replace", "REMOVE": "Remove",
        "DETACH_RESET": "Detach & reset", "MATERIAL_ONLY": "Material only",
        "INSTALL_ONLY": "Install", "TEAR_OFF": "Tear off",
    },
}
from repair_logic_library import lookup_entry
from category_display_names import category_display_name as cname
# ITEM 4 — the legend swatches are derived from the SVG's OWN colour constants. They used to be
# hardcoded twice and had drifted: the SVG drew affected zones RED while the legend showed BLUE-GREY
# (the old stub's palette), and transitions were drawn but had no legend entry at all.
from report_diagram_svg import (AFFECTED_FILL, AFFECTED_STROKE, FACET_FILL, FACET_STROKE,
                                REPLACED_FILL, REPLACED_STROKE,
                                TRANSITION_STROKE, VALLEY_STROKE)

SHAKE_EXPLANATION = ("The affected repair area represents the roof area impacted by the repair "
                     "process. Because wood shake repairs require individual shake removal, "
                     "replacement, and integration, the affected area is converted into an "
                     "estimated shake quantity to represent the repair scope.")

DIAGRAM_DISCLAIMER = "Shading is representative; the percentage / square-foot value is authoritative."

# Quoted verbatim from the CSSB FAQ (cssbureau.com). The strip-width sentence is the AUTHORITY for
# the interlayment quantity; the second sentence is CSSB's own deferral to the local Building
# Official — the burden-shift framing this report is built on. The placement sentence ("bottom edge
# ... twice the weather exposure") is deliberately omitted: it is a PLACEMENT rule, not the quantity
# ratio, and this report never states it as the multiplier.
CSSB_INTERLAYMENT_QUOTE = ('The CSSB recommends using an 18" wide strip of No.30 ASTM D226 Type II '
                           'or ASTM D4869 Type IV roofing felt laid over the top portion of the '
                           'shakes and extending on to the sheathing. Check with your local '
                           'Building Official for exact specifications in your area.')

PRECONDITION_NOTE = ("This comparison presumes both scopes describe the same physical repair area. "
                     "Uploading the carrier loss statement asserts that the carrier estimate covers "
                     "the same repair area analyzed here.")

STATE_LABEL = {
    "QUANTITY_DIFFERENCE": "Quantity difference",
    "OPERATION_SPLIT": "Carrier funded more than one operation",
    "MISSING_FROM_CARRIER": "Not included in carrier estimate",
    "MISSING_FROM_CARRIER_EXCLUDED": "Carrier estimate marks excluded",
    "OPERATION_DIFFERENCE": "Repair Operation Difference",
    "UNMAPPED_REVIEW": "Unit mismatch — review",
}


def _operation_note(required_op, carrier_op, delta, platform=None):
    """Neutral scope sentence for an operation divergence (guard-clean; no coverage terms).
    v72 DEFECT 3: when the platform the carrier used is KNOWN, the activities are named in THAT
    platform's own vocabulary (Xactimate vs Symbility) so the argument cannot be dismissed for citing
    the wrong code. An UNKNOWN/absent platform falls back to the neutral labels — nothing
    platform-specific is asserted."""
    vocab = _PLATFORM_ACTIVITY.get(platform, {})
    req = vocab.get(required_op) or OP_LABEL.get(required_op, required_op)
    car = vocab.get(carrier_op) or OP_LABEL.get(carrier_op, carrier_op)
    phrase = delta_phrase(delta)
    base = f"required operation {req} vs carrier operation {car}"
    if phrase:
        return base + f"; the carrier operation does not account for {phrase}"
    return base


def _operation_explanation(category_id, required_op, carrier_op):
    """Additive lookup into the Repair Logic Library. When an authored entry matches the
    (category, required op, carrier op) triple, return its explanation as a neutral sub-note
    beneath the operation fact. CONDITION-class entries are already phrased conditionally and
    are rendered verbatim — the condition is never asserted as established. Returns "" when no
    entry matches (unchanged behavior — only the neutral operation fact renders)."""
    entry = lookup_entry(category_id, required_op, carrier_op)
    if not entry:
        return ""
    return f"<div class='opnote'>{e(entry['explanation'])}</div>"

def e(x):
    return html.escape(str(x)) if x is not None else ""

def _as_float(x):
    """Coerce a quantity to float for arithmetic; non-numeric/None -> 0.0 (never raises)."""
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0

# ---------------------------------------------------------------------------
def _kv_table(rows):
    body = "".join(f"<tr><th>{e(k)}</th><td>{e(v)}</td></tr>" for k, v in rows if v not in (None, ""))
    return f"<table class='kv'>{body}</table>"

def _header_text(v):
    """Claim-header values arrive from the UI and may be str / int / float / None. A report
    renderer must NEVER die on claim metadata, so every header value is coerced to a display
    string and nothing here can raise. Empty/None -> None (row omitted, as before)."""
    if v is None:
        return None
    if isinstance(v, str):
        v = v.strip()
        return v or None
    return str(v)


def _money_text(v):
    """Deductible: accept 14362.0, "14362.00", "$14,362.00", "", None — never raise.
    Parses as a number -> currency format; not numeric -> render the raw string as given;
    empty/None -> None (row omitted). The deductible IS a required header field and IS shown;
    it is claim metadata, not scope pricing."""
    if v is None:
        return None
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        try:
            return f"${float(v):,.2f}"
        except (ValueError, OverflowError):
            return str(v)
    text = str(v).strip()
    if not text:
        return None
    cleaned = text.replace("$", "").replace(",", "").replace("\u00a0", " ").strip()
    try:
        return f"${float(cleaned):,.2f}"
    except (TypeError, ValueError):
        return text            # not a number (e.g. "TBD") -> show exactly what was given


def sec1_claim(s, mode):
    rows = [("Insured", _header_text(s.get("insured"))),
            ("Loss location", _header_text(s.get("loss_address"))),
            ("Claim number", _header_text(s.get("claim_number"))),
            ("Policy number", _header_text(s.get("policy_number"))),
            ("Type of loss", _header_text(s.get("type_of_loss"))),
            ("Date of loss", _header_text(s.get("date_of_loss"))),
            ("Deductible", _money_text(s.get("deductible"))),
            ("Carrier", _header_text(s.get("carrier"))),
            ("Jurisdiction / code", _header_text(s.get("jurisdiction_code")))]
    return ("Claim information", _kv_table(rows))

def sec2_carrier_summary(s):
    """What the carrier's own estimate already accepts, in plain words.

    NO DOLLAR FIGURES. This tool is dollar-free by design: pricing lives ONLY in the external
    attachments (§7). The carrier's reference totals may still be present in the data — they are
    simply NOT RENDERED. Printing them here broke the quarantine and told the reader nothing they
    could not read on the estimate itself.

    Also plain English, not engine jargon: raw category ids and words like "acknowledges" and
    "matched / acknowledged" were never readable by the person this report is for. It states SCOPE
    facts only — never a coverage conclusion — and still passes the §10.5 language guard.
    """
    if not s:
        return None                                  # required-scope-only: omit entirely (no stub)

    ack = s.get("acknowledged", {}) or {}
    yes = [k for k, v in ack.items() if v]
    no = [k for k, v in ack.items() if not v]

    def phrase(keys):
        return ", ".join(e(str(k).replace("_", " ").strip().lower()) for k in keys)

    bits = []
    if yes:
        bits.append(f"<p>The carrier's estimate already records {phrase(yes)}.</p>")
    if no:
        bits.append(f"<p>It does not record {phrase(no)}.</p>")
    if not bits:
        bits.append("<p>The carrier's estimate does not record any of the roof conditions listed here.</p>")

    agreed = [cname(c) for c in (s.get("agreed_lines") or [])]
    if agreed:
        items = "".join(f"<li>{e(a)}</li>" for a in agreed)
        agreed_html = (f"<p>We already agree on the following, and they are not in dispute:</p>"
                       f"<ul>{items}</ul>")
    else:
        agreed_html = ("<p>There are no line items yet where the estimate and this scope already "
                       "agree.</p>")

    source = e(s.get("estimate_name") or "the carrier estimate")
    return ("What the carrier's estimate already says",
            f"<p class='note'>Read from {source}. This section reports what that estimate contains; "
            f"it draws no conclusions and states no amounts.</p>"
            + "".join(bits) + agreed_html)

def _felt_interlayment_callout(s):
    """Show WHY interlayment felt exceeds the affected area — the first thing an adjuster challenges.

    Everything is derived from data already in this section: the felt required line (felt SQ) and
    shake_comparison_SQ (the affected repair area in squares, present in BOTH report modes). The 18"
    strip is the single sourced constant from the engine. The measured exposure is recovered from the
    interlayment ratio (strip / ratio) rather than plumbed across the Module-2 firewall — the section
    projection does not carry exposure. Renders in §3, so both the comparison and the required-scope-
    only report carry it.
    """
    felt = next((x for x in s.get("required_lines", [])
                 if "felt" in str(x.get("item", "")).lower() and x.get("unit") == "SQ"), None)
    affected_sq = s.get("shake_comparison_SQ")
    if not felt or affected_sq in (None, ""):
        return ""
    try:
        felt_sq = float(felt["qty"])
        asq = float(affected_sq)
        if asq <= 0 or felt_sq <= 0:
            return ""
        ratio = felt_sq / asq
        exposure = CSSB_INTERLAYMENT_STRIP_IN / ratio
    except (TypeError, ValueError, ZeroDivisionError):
        return ""
    affected_sf = asq * 100.0
    felt_sf = felt_sq * 100.0
    return ("<div class='callout'>"
            "<p><strong>Felt interlayment &mdash; why it exceeds the affected area.</strong> "
            f"One {CSSB_INTERLAYMENT_STRIP_IN:.0f}&Prime; CSSB felt strip is laid over the top of "
            f"every shake course, and courses repeat every {exposure:.1f}&Prime; of measured "
            f"exposure, so the interlayment overlaps itself up the slope: "
            f"{CSSB_INTERLAYMENT_STRIP_IN:.0f}&Prime; &divide; {exposure:.1f}&Prime; = "
            f"{ratio:.2f} SF of felt per SF of roof. Therefore {affected_sf:,.1f} SF affected "
            f"&times; {ratio:.2f} = {felt_sf:,.1f} SF = {felt_sq:,.2f} SQ &mdash; the felt quantity "
            "is larger than the affected area for this reason, not by error.</p>"
            f"<p class='note'>CSSB: &ldquo;{e(CSSB_INTERLAYMENT_QUOTE)}&rdquo;</p>"
            "</div>")


def _replacement_callout(s):
    """v61 full slope replacement. Labels the two wood-shake lines BY FACET (replacement SQ vs repair
    EA) and states the replacement area is NET (no waste) with no repair factor applied. Renders only
    when at least one facet is a replacement; a repair-only roof is unchanged.

    Wording is mode-safe: it says the slopes ARE SCOPED for full replacement (true whether or not a
    carrier estimate exists). It does not claim the carrier scoped a slope — that attribution belongs
    to §5, where the carrier's own lines are shown, and is never asserted from the scope side.
    """
    repl = list(s.get("replacement_facets") or [])
    if not repl:
        return ""
    rep = list(s.get("repair_facets") or [])
    lines = s.get("required_lines", [])
    sq = next((x for x in lines if x.get("category_id") == "SHAKE_FIELD_RR" and x.get("unit") == "SQ"), None)
    ea = next((x for x in lines if x.get("category_id") == "SHAKE_FIELD_RR" and x.get("unit") == "EA"), None)
    fac = lambda names: ", ".join(e(str(n)) for n in names)
    parts = []
    if sq is not None:
        parts.append(f"<strong>Slope replacement</strong> (facets {fac(repl)}): {e(sq['qty'])} SQ")
    if ea is not None and rep:
        parts.append(f"<strong>Slope repair</strong> (facets {fac(rep)}): {e(ea['qty'])} EA")
    head = " &nbsp;|&nbsp; ".join(parts) if parts else f"Slope replacement (facets {fac(repl)})"
    return ("<div class='callout'>"
            f"<p>{head}</p>"
            "<p class='note'>The listed slope(s) are scoped for full replacement. The replacement "
            "quantity is the <strong>net facet area</strong> (penetrations removed) billed in "
            "<strong>squares (SQ)</strong> &mdash; a full slope is conventional square-based work, so "
            "billing it &ldquo;each&rdquo; would claim a per-shake repair labor premium the work does "
            "not involve. <strong>No waste factor</strong> and <strong>no repair or contingency "
            "multiplier</strong> have been applied to the replacement area.</p>"
            "</div>")


def _slope_replacement_note():
    return ("<p class='note'>The listed slope(s) are scoped for full replacement. The replacement "
            "quantity is the <strong>net facet area</strong> (penetrations removed) billed in "
            "<strong>squares (SQ)</strong> &mdash; a full slope is conventional square-based work, so "
            "billing it &ldquo;each&rdquo; would claim a per-shake repair labor premium the work does "
            "not involve. <strong>No waste factor</strong> and <strong>no repair or contingency "
            "multiplier</strong> have been applied to the replacement area.</p>")


def _replacement_callout_by_structure(s):
    """v69 DEFECT 3: group the slope replacement / repair callouts BY STRUCTURE, dwelling first (the
    structure the roof measurements represent, ordered in _structure_blocks), each carrying its OWN
    net-area / no-waste / no-multiplier note. Renders a block only for a structure that has a slope
    replacement, exactly as the single-structure callout does."""
    blocks = s.get("structure_blocks") or []
    fac = lambda names: ", ".join(e(str(n)) for n in names)
    out = []
    for b in blocks:
        repl = list(b.get("replacement_facets") or [])
        rep = list(b.get("repair_facets") or [])
        if not repl:
            continue
        parts = []
        if b.get("shake_SQ") is not None:
            parts.append(f"<strong>Slope replacement</strong> (facets {fac(repl)}): {e(b['shake_SQ'])} SQ")
        if b.get("shake_EA") is not None and rep:
            parts.append(f"<strong>Slope repair</strong> (facets {fac(rep)}): {e(b['shake_EA'])} EA")
        head = " &nbsp;|&nbsp; ".join(parts) if parts else f"Slope replacement (facets {fac(repl)})"
        out.append(f"<div class='callout'><p><strong>{e(b['heading'])}</strong></p><p>{head}</p>"
                   f"{_slope_replacement_note()}</div>")
    return "".join(out)


def _shake_count_callout(s, shake_measurements):
    """Show HOW the estimated shake count is reached — the per-shake exposed coverage and the
    shakes-per-square from the job's MEASURED width and exposure, then the rounding that IS the
    argument: each repair zone is counted separately and rounded up, because a partial shake is not a
    repair. The stated total is READ from the same SHAKE_FIELD_RR EA line(s) the required-items table
    prints, so it reconciles with the table exactly on every roof — it is never re-derived by a single
    area division (which would net the per-zone ceilings and contradict the table). Renders in the same
    register as the felt block, only when a repair EA line is in scope and the measured profile is
    present (never the defaults)."""
    by = s.get("required_lines_by_structure") or []
    if by:
        ea_lines = [x for g in by for x in g.get("lines", [])
                    if x.get("category_id") == "SHAKE_FIELD_RR" and x.get("unit") == "EA"]
    else:
        ea_lines = [x for x in s.get("required_lines", [])
                    if x.get("category_id") == "SHAKE_FIELD_RR" and x.get("unit") == "EA"]
    if not ea_lines:
        return ""
    sm = shake_measurements if isinstance(shake_measurements, dict) else {}
    try:
        width = float(sm.get("width_in"))
        exposure = float(sm.get("exposure_in"))
    except (TypeError, ValueError):
        return ""                       # no measured profile -> omit rather than print the defaults
    if width <= 0 or exposure <= 0:
        return ""
    try:
        total_ea = sum(int(round(float(x["qty"]))) for x in ea_lines)
    except (TypeError, ValueError, KeyError):
        return ""
    sq_in = width * exposure
    coverage_sf = sq_in / 144.0
    per_sq = 14400.0 / sq_in
    return ("<div class='callout'>"
            "<p><strong>Estimated shake count &mdash; how it is reached.</strong> "
            f"Each shake covers its exposed face: width &times; exposure = {width:g}&Prime; &times; "
            f"{exposure:g}&Prime; = {sq_in:g} sq in = {coverage_sf:.4f} SF of roof; at 14,400 sq in per "
            f"square that is 14,400 &divide; ({width:g} &times; {exposure:g}) = {per_sq:.1f} shakes per "
            "square. Each repair zone is then counted separately and <strong>rounded up</strong> "
            "&mdash; a partial shake is not a repair, so every zone takes whole shakes. That rounding "
            "is exactly why localized repair is more labour-intensive per square than a full "
            f"replacement, and the per-zone counts sum to {total_ea:,} EA.</p></div>")


def sec3_shake_analysis(s, shake_measurements=None):
    def _row(x):
        # v48 splits chimney flashings by size (Small / Average / Large are three different
        # Xactimate items). Show the code beside the item so the reader can see WHICH is billed.
        code = x.get("xact_code")
        suffix = f" <span class='code'>{e(code)}</span>" if code else ""
        return (f"<tr><td>{e(x['item'])}{suffix}</td><td class='num'>{e(x['qty'])}</td>"
                f"<td>{e(x['unit'])}</td></tr>")
    by_struct = s.get("required_lines_by_structure", []) or []
    if by_struct:
        # v65 structure separation: two or more <ROOF> structures each get their OWN material list with
        # a heading and its own quantities — never a merged total. A single-structure roof never reaches
        # this branch (the projection leaves required_lines_by_structure empty), so its table is unchanged.
        _parts = []
        for _grp in by_struct:
            _parts.append(f"<tr class='structure-head'><td colspan='3'><strong>{e(_grp['heading'])}</strong></td></tr>")
            _parts.append("".join(_row(x) for x in _grp.get("lines", [])))
        lines = "".join(_parts)
    else:
        lines = "".join(_row(x) for x in s.get("required_lines", []))
    # v62 DEFECT 4: the §3 framing follows the SCOPE. The EA labor argument (and the repair-area /
    # shake-quantity dual) is the case FOR the EA line and AGAINST the SQ line — printing it on a full
    # replacement is the exact credibility problem the SQ/EA split exists to avoid. Show it only when a
    # repair EA line is actually in scope: repair-only and mixed keep it (attached to the EA line and
    # its facet set), replacement-only omits it entirely and leads with the replacement callout.
    _lines = s.get("required_lines", [])
    has_repair_ea = any(x.get("category_id") == "SHAKE_FIELD_RR" and x.get("unit") == "EA" for x in _lines)
    blocks = s.get("structure_blocks") or []
    if blocks:
        # v69 DEFECT 2: with more than one structure, the affected-area / shake-quantity callout is
        # stated PER STRUCTURE (a report that separates §3's material list but merges here is incoherent).
        rows = []
        for b in blocks:
            if b.get("shake_EA") is not None:   # a structure with a repair EA line
                rows.append(f"<p><strong>{e(b['heading'])}</strong> &mdash; "
                            f"<strong>Affected repair area:</strong> {e(b['affected_SQ'])} SQ &nbsp;|&nbsp; "
                            f"<strong>Estimated shake quantity:</strong> {e(b['shake_EA'])} EA</p>")
        dual = (f"<div class='callout'>{''.join(rows)}<p class='note'>{e(SHAKE_EXPLANATION)}</p></div>") if rows else ""
        replacement_html = _replacement_callout_by_structure(s)
    else:
        dual = ""
        if s.get("shake_comparison_SQ") is not None and has_repair_ea:
            dual = (f"<div class='callout'><p><strong>Affected repair area:</strong> "
                    f"{e(s['shake_comparison_SQ'])} SQ &nbsp;|&nbsp; "
                    f"<strong>Estimated shake quantity:</strong> {e(s['shake_supporting_EA'])} EA</p>"
                    f"<p class='note'>{e(SHAKE_EXPLANATION)}</p></div>")
        replacement_html = _replacement_callout(s)
    reasoning_html = f"<p>{e(s.get('reasoning'))}</p>" if (has_repair_ea and s.get("reasoning")) else ""
    return ("Wood shake repair analysis",
            f"{reasoning_html}{dual}{_shake_count_callout(s, shake_measurements)}"
            f"{replacement_html}{_felt_interlayment_callout(s)}{_eave_iws_callout(s)}"
            f"<table class='data'><thead><tr><th>Required item</th><th>Qty</th><th>Unit</th></tr></thead>"
            f"<tbody>{lines}</tbody></table>"
            f"<p class='note'>Authorities: {', '.join(e(c) for c in s.get('citations', []))}</p>")


def _eave_iws_callout(s):
    """v71 DEFECT 3: state the eave ice & water coverage, cite the basis, and state the layer count as
    a CONSEQUENCE of the run geometry. This report is carrier-facing: it never narrates the tool's own
    uncertainty (a defaulted soffit reads like any other derived figure; the warning is on page 2)."""
    m = s.get("eave_iws")
    if not m:
        return ""
    layers = m.get("layers") or 1
    layer_txt = f"{layers} layer" + ("s" if layers != 1 else "")
    return (f"<div class='callout'><p><strong>Eave ice &amp; water barrier:</strong> "
            f"{e(m.get('coverage_SF'))} SF &mdash; {e(m.get('citation'))}.</p>"
            f"<p class='note'>Coverage runs from the eave edge to 24&quot; inside the exterior wall; "
            f"that run takes {e(layer_txt)} of 36&quot; membrane.</p></div>")

def sec4_diagram(s):
    """The roof picture. When a diagram SVG is supplied it is embedded as-is; otherwise the original
    stub renders, so every existing caller and test still works.

    The SVG is generated (report_diagram_svg) from the SAME diagram data the totals come from — the
    picture is never re-derived or re-scaled independently of the math it illustrates. The caption
    (affected SF, authoritative percentage, disclaimer) is unchanged.
    """
    pct_map = s.get("authoritative_pct") or {}
    pct = ", ".join(f"{e(k)}: {e(v)}" for k, v in pct_map.items())
    sf = ", ".join(f"{e(k)}: {e(v)} SF" for k, v in (s.get("affected_SF") or {}).items())
    legend = ("<div class='legend'>"
              + ("<span><i class='sw sw-replaced'></i> Full slope replacement</span>" if s.get("has_replacement") else "")
              + "<span><i class='sw sw-affected'></i> Affected repair area</span>"
              "<span><i class='sw sw-valley'></i> Valley / repair feature</span>"
              "<span><i class='sw sw-transition'></i> Pitch transition</span>"
              "<span><i class='sw sw-field'></i> Unaffected field</span></div>")
    svg = s.get("diagram_svg")
    body = (f"<div class='diagram-full has-svg'>{svg}</div>" if svg
            else "<div class='diagram-full'>[ Full-page roof diagram &mdash; static view ]</div>")
    return ("Affected area diagram",
            f"{body}{legend}"
            # No placeholder token may reach a live report: when the percentage is unavailable the
            # phrase is OMITTED entirely rather than printing something like DIAGRAM_PENDING_PAGE2.
            + (f"<p><strong>Affected area:</strong> {sf} &nbsp;|&nbsp; "
               f"<strong>Authoritative percentage:</strong> {pct}</p>" if pct
               else f"<p><strong>Affected area:</strong> {sf}</p>")
            + f"<p class='note'>{e(DIAGRAM_DISCLAIMER)}</p>")

def _cite(r):
    """The authority cell — what puts this item in a proper repair."""
    c = r.get("citation")
    return e(c) if c else "&mdash;"


def _qty(value, unit):
    """A quantity, never the word 'required'. The number IS the argument."""
    if value is None or value == "":
        return "&mdash;"
    try:
        return f"{float(value):,.2f} {e(unit or '')}".strip()
    except (TypeError, ValueError):
        return f"{e(value)} {e(unit or '')}".strip()


def _sec5_gap_body(s, gap, total_required, include_footer=True):
    """Render ONE comparison table (the whole roof, or a single scoped structure) from its gap rows.
    The identical builder drives the single-structure §5 and each per-structure block, so a lone
    structure and one block of a multi-structure roof are rendered the same way. include_footer carries
    the roof-level stated-gaps + closing note; on a multi-structure report those render once, after all
    blocks, so per-block calls pass include_footer=False."""
    missing = [r for r in gap if r["state"] in ("MISSING_FROM_CARRIER", "MISSING_FROM_CARRIER_EXCLUDED")]
    headline = ""
    if total_required and missing:
        headline = (f"<p class='headline'>{len(missing)} of the {total_required} items in this "
                    f"repair scope are not present in the carrier estimate.</p>")
    elif missing:
        headline = (f"<p class='headline'>{len(missing)} item(s) in this repair scope are not "
                    f"present in the carrier estimate.</p>")

    rows = ""
    for r in gap:
        st = r["state"]
        item = e(r.get("label") or cname(r["category_id"]))
        cite = _cite(r)
        note = ""

        if st == "QUANTITY_DIFFERENCE":
            diff = r.get("required_scope_difference")
            required = _qty(r.get("required"), r.get("required_unit"))
            approved = _qty(r.get("approved"), r.get("required_unit"))
            detail = e(STATE_LABEL[st])
            oc = r.get("operation_context")
            if oc:
                detail += (" &mdash; also: "
                           + e(_operation_note(oc.get("required_operation"),
                                               oc.get("carrier_operation"),
                                               oc.get("operation_delta"), s.get("platform"))))
                detail += _operation_explanation(r["category_id"],
                                                 oc.get("required_operation"),
                                                 oc.get("carrier_operation"))
            rows += (f"<tr class='fact'><td>{item}</td><td class='num'>{required}</td>"
                     f"<td>{cite}</td>"
                     f"<td class='num'>{approved}</td>"
                     f"<td class='num'>{diff:+.2f}</td></tr>")
            note = detail

        elif st == "OPERATION_DIFFERENCE":
            required = _qty(r.get("required"), r.get("required_unit"))
            approved = _qty(r.get("approved"), r.get("required_unit"))
            detail = (e(STATE_LABEL[st]) + " &mdash; "
                      + e(_operation_note(r.get("required_operation"), r.get("carrier_operation"),
                                          r.get("operation_delta"), s.get("platform")))
                      + _operation_explanation(r["category_id"], r.get("required_operation"),
                                               r.get("carrier_operation")))
            rows += (f"<tr class='fact'><td>{item}</td><td class='num'>{required}</td>"
                     f"<td>{cite}</td>"
                     f"<td class='num'>{approved}</td>"
                     f"<td class='num'>&mdash;</td></tr>")
            note = detail

        elif st == "OPERATION_SPLIT":
            req_op = r.get("required_operation")
            req_val = r.get("required")
            unit = r.get("required_unit")
            required = _qty(req_val, unit)
            if req_op:
                required += f" ({e(OP_LABEL.get(req_op, req_op))})"
            ops = list(r.get("approved_operations") or [])
            ops.sort(key=lambda o: (0 if o.get("operation") == req_op else 1, -_as_float(o.get("quantity"))))
            parts, delta_notes, explanations = [], [], []
            funded_total = 0.0
            funded_at_diff = 0.0
            for o in ops:
                q = _as_float(o.get("quantity"))
                funded_total += q
                opq = _qty(o.get("quantity"), o.get("unit"))
                oplabel = OP_LABEL.get(o.get("operation"), o.get("operation"))
                parts.append(f"{opq} {e(oplabel)}")
                if o.get("operation") != req_op:
                    funded_at_diff += q
                if o.get("operation_delta"):
                    delta_notes.append(f"The {e(str(oplabel).lower())} quantity does not account for "
                                       f"{e(delta_phrase(o['operation_delta']))}.")
                expl = _operation_explanation(r["category_id"], req_op, o.get("operation"))
                if expl:
                    explanations.append(expl)
            not_addressed = round(_as_float(req_val) - funded_total, 2) if req_val is not None else None
            diff_cell = (f"{not_addressed:.2f} {e(unit)} not addressed"
                         if not_addressed is not None else "&mdash;")
            rows += (f"<tr class='fact'><td>{item}</td><td class='num'>{required}</td>"
                     f"<td>{cite}</td>"
                     f"<td>{' &middot; '.join(parts)}</td>"
                     f"<td class='num'>{diff_cell}</td></tr>")
            qnote = (e(STATE_LABEL[st]) + " &mdash; each operation is listed with its own quantity; the "
                     "carrier total is not combined.")
            if not_addressed is not None:
                qnote += (f" {not_addressed:.2f} {e(unit)} of the required {_qty(req_val, unit)} is not "
                          f"addressed by any operation")
                if funded_at_diff > 1e-9:
                    qnote += (f"; a further {funded_at_diff:.2f} {e(unit)} is addressed at a different "
                              f"operation &mdash; work that lacks the removal labour a Remove &amp; "
                              f"Replace includes, so it does not offset the gap.")
                else:
                    qnote += "."
            if delta_notes:
                qnote += " " + " ".join(delta_notes)
            note = qnote + "".join(explanations)

        elif st == "UNMAPPED_REVIEW":
            required = _qty(r.get("required_quantity"), r.get("required_unit"))
            carrier = _qty(r.get("carrier_quantity"), r.get("carrier_unit"))
            rows += (f"<tr class='fact'><td>{item}</td><td class='num'>{required}</td>"
                     f"<td>{cite}</td>"
                     f"<td class='num'>{carrier}</td>"
                     f"<td class='num'>&mdash;</td></tr>")
            note = (e(STATE_LABEL[st]) + f" &mdash; required {required}; carrier estimate wrote "
                    f"{carrier}; the two are in different units and are not directly comparable.")

        elif st == "MATCHED":
            required = _qty(r.get("required"), r.get("required_unit"))
            approved = _qty(r.get("approved"), r.get("required_unit"))
            rows += (f"<tr class='fact'><td>{item}</td><td class='num'>{required}</td>"
                     f"<td>{cite}</td>"
                     f"<td class='num'>{approved}</td>"
                     f"<td class='num'>in agreement</td></tr>")

        else:
            required = _qty(r.get("required_quantity"), r.get("required_unit"))
            rows += (f"<tr class='fact'><td>{item}</td><td class='num'>{required}</td>"
                     f"<td>{cite}</td>"
                     f"<td class='absent' colspan='2'>not present in the carrier estimate</td></tr>")
            if st == "MISSING_FROM_CARRIER_EXCLUDED":
                note = (e(STATE_LABEL[st]) + " &mdash; carrier language: &ldquo;"
                        + e(r.get("exclusion_source_text")) + "&rdquo;")

        if r.get("carrier_pair_note"):
            pn = e(r["carrier_pair_note"])
            note = (note + " &mdash; " + pn) if note else pn

        if note:
            rows += f"<tr class='detail'><td colspan='5'>{note}</td></tr>"

    body = (f"{headline}<p class='note'>{e(PRECONDITION_NOTE)}</p>"
            "<table class='data cmp'><thead><tr><th>Item</th><th>Required</th>"
            "<th>Why it is in a proper repair</th><th>Carrier estimate</th>"
            "<th>Difference</th></tr></thead>"
            f"<tbody>{rows}</tbody></table>")
    if include_footer:
        gaps_html = ""
        for g in (s.get("stated_gaps") or []):
            gaps_html += f"<p class='note gap'>{e(g)}</p>"
        body += (gaps_html
                 + "<p class='note'>Items in agreement appear in the carrier estimate summary. "
                   "Unmapped items are held for review and are not stated as conclusions.</p>")
    return body


def sec5_comparison(s):
    """The comparison must DEMONSTRATE the divergence and let the reader conclude.

    It used to print the bare word "required" for every item the carrier omitted — 11 of 13 lines on
    a real claim. That is the TOOL drawing the conclusion, which is exactly what an adjuster pushes
    back on. It now states three facts and stops: HOW MUCH, the STANDARD that puts it in a proper
    repair, and that the carrier's estimate does not contain it. No "owed", no "should pay", no
    coverage language. THE ADJUSTER DRAWS THE CONCLUSION.
    """
    if s.get("mode") != "COMPARISON":
        rows = "".join(f"<tr><td>{e(cname(r['category_id']))}</td>"
                       f"<td class='num'>{_qty(r.get('quantity'), r.get('unit'))}</td>"
                       f"<td>{_cite(r)}</td></tr>" for r in s.get("required_scope", []))
        dual = ""
        if (s.get("shake_dual") or {}).get("comparison_quantity") is not None:
            d = s["shake_dual"]
            dual = (f"<p class='note'>Wood shake field is expressed as affected repair area "
                    f"{e(d['comparison_quantity'])} SQ (supporting estimate {e(d['supporting_quantity'])} EA).</p>")
        return ("Required material scope",
                "<table class='data cmp'><thead><tr><th>Item</th><th>Quantity</th>"
                "<th>Why it is in a proper repair</th></tr></thead>"
                f"<tbody>{rows}</tbody></table>{dual}")

    gap = s.get("gap", []) or []
    # ITEM 6 — the scale of the divergence, computed (never hardcoded).
    total_required = s.get("scope_line_count") or (len(s.get("required_scope") or []) or None)

    # PER-STRUCTURE §5: one comparison block per scoped structure, each rendered by the SAME builder as
    # the single-structure table (see _sec5_gap_body). The heading is the one §3 already uses, so the two
    # sections name the buildings identically. Present only for 2+ scoped structures; a single-structure
    # roof takes the else-branch and renders byte-identically.
    structure_gaps = s.get("structure_gaps") or []
    if len(structure_gaps) >= 2:
        parts = []
        for b in structure_gaps:
            parts.append(f"<h3 class='struct-heading'>{e(b.get('heading') or b.get('structure_id') or '')}</h3>")
            parts.append(_sec5_gap_body(s, b.get("gap") or [], b.get("scope_line_count"), include_footer=False))
        # The roof-level stated gaps + closing note render ONCE, after all blocks.
        gaps_html = ""
        for g in (s.get("stated_gaps") or []):
            gaps_html += f"<p class='note gap'>{e(g)}</p>"
        parts.append(gaps_html
                     + "<p class='note'>Items in agreement appear in the carrier estimate summary. "
                       "Unmapped items are held for review and are not stated as conclusions.</p>")
        return ("Required vs approved scope comparison", "".join(parts))

    return ("Required vs approved scope comparison",
            _sec5_gap_body(s, gap, total_required, include_footer=True))


def sec6_evidence(s):
    """Photos are what make the field-measured shake dimensions defensible — not decoration.

    A photo may be supplied as a data URL / URL string, or as {"src": ..., "caption": ...}. Anything
    that is not an image source still renders as the old placeholder box, so existing callers and
    tests are unaffected.
    """
    captions = s.get("captions") or {}
    cards = []
    for p in (s.get("photos") or []):
        if isinstance(p, dict):
            src = str(p.get("src") or "")
            caption = str(p.get("caption") or captions.get(src, "") or "")
        else:
            src = str(p)
            caption = str(captions.get(p, "") or "")
        is_image = src.startswith("data:image") or src.startswith("http") or src.startswith("./")
        box = (f"<img class='photo-img' src='{e(src)}' alt='{e(caption or "Supporting photo")}' />"
               if is_image else f"<div class='photo-box'>[ photo: {e(src)} ]</div>")
        cards.append(f"<div class='photo'>{box}"
                     f"<div class='caption'>{e(caption) if caption else '&nbsp;'}</div></div>")
    photos = "".join(cards)
    return ("Supporting photos / evidence",
            f"<div class='photo-row'>{photos}</div>"
            f"<p class='note'>Authorities bound to scope lines: {', '.join(e(c) for c in s.get('citations', []))}</p>")

def sec7_attachments(s):
    lis = "".join(f"<li>{e(label)}</li>" for label in s.get("included", []))
    # v66: honest acknowledgment that the WHOLE estimate was read. One line naming the non-roof trades
    # and the count; renders nothing when there are none. No pricing, no conclusions about them.
    ack = ""
    nr = s.get("non_roof_ack")
    if nr and (nr.get("exterior") or nr.get("interior")):
        # v67: the COUNTS the user actually asserted on page 3, split by side. No pricing, no
        # conclusions — a plain statement that the whole estimate was read.
        ext, inte = int(nr.get("exterior", 0)), int(nr.get("interior", 0))
        parts = []
        if ext:
            parts.append(f"{ext} exterior")
        if inte:
            parts.append(f"{inte} interior")
        joined = " and ".join(parts)
        total = ext + inte
        ack = (f"<p class='note'>The estimate also contains {joined} line item{'' if total == 1 else 's'}; "
               f"they are outside the roof scope and are not analyzed here.</p>")
    return ("Attachments",
            f"<ul>{lis}</ul>"
            "<p class='note'>The repair and full replacement estimates are attached for the adjuster's "
            "review; this report does not contain or interpret their pricing.</p>"
            f"{ack}")

# ITEM 4 — the legend swatches are DERIVED from the SVG's own colour constants, so the picture and
# its key can never drift apart again. (They had: the SVG drew affected zones red while the legend
# showed the old stub's blue-grey, and transitions were drawn with no legend entry at all.)
SWATCH_CSS = (
    f".sw-affected{{background:{AFFECTED_FILL};border:1px solid {AFFECTED_STROKE}}}"
    f".sw-replaced{{background:{REPLACED_FILL};border:1px solid {REPLACED_STROKE}}}"
    f".sw-valley{{background:{VALLEY_STROKE}}}"
    f".sw-transition{{background:repeating-linear-gradient(90deg,{TRANSITION_STROKE},"
    f"{TRANSITION_STROKE} 3px,transparent 3px,transparent 6px)}}"
    f".sw-field{{background:{FACET_FILL};border:1px solid {FACET_STROKE}}}"
)


# ITEM 8 — §6 photo grid. TWO ACROSS, legible but compact: this document gets printed and PDF'd for
# an adjuster, and length works against it. No fixed pixel widths (they assume a screen and break on
# paper) — percentages and max-width only, so it scales to the page.
PHOTO_CSS = (
    # §6 evidence grid (v74.3). TWO PHOTOS PER ROW, each box filling HALF the usable page width, so an
    # adjuster / appraiser / attorney can read a caption and confirm it against a large, clear photo.
    # This is the sole authority for the photo grid — it overrides the base-CSS photo rules that
    # pinned each image to a tiny fixed width inside its half-page column.
    ".photo-row{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px;"
    "margin:10px 0 6px;align-items:start}"
    # each photo + its caption is ONE unbreakable block: an image must never split across a page
    ".photo{width:auto;page-break-inside:avoid;break-inside:avoid;margin:0}"
    # THE BOX fills its half-page column (width:100%). THE IMAGE sits inside at its TRUE proportions and
    # is NEVER stretched: object-fit:contain fits the whole photo (no crop) without distortion, so a
    # portrait and a landscape shot both render honestly in equal side-by-side boxes. max-height caps a
    # tall portrait so it stays large-but-page-friendly; a wide landscape simply fills the column width.
    # Source photos are CompanyCam 1440x1920, so this size stays crisp — nothing is upscaled past source.
    ".photo-img{width:100%;height:auto;max-height:3.7in;object-fit:contain;display:block;"
    "background:var(--soft);border:1px solid var(--line);border-radius:4px}"
    ".photo .caption{font-size:12px;color:var(--ink);margin-top:7px;line-height:1.4;text-align:center}"
    # collapse to one column on a narrow SCREEN, without touching print
    "@media screen and (max-width:560px){.photo-row{grid-template-columns:minmax(0,1fr)}}"
    # PRINT/PDF is the real deliverable: keep the two-up grid and the unbreakable photo+caption blocks.
    "@media print{.photo-img{max-height:3.7in}.photo{break-inside:avoid;page-break-inside:avoid}}"
)

CSS = """
:root{--ink:#1f2733;--muted:#5b6573;--line:#d9dee5;--bg:#fff;--accent:#33485e;--soft:#f4f6f8;}
*{box-sizing:border-box}
body{font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;color:var(--ink);
     line-height:1.5;margin:0;background:#eef1f4}
.page{max-width:820px;margin:24px auto;background:var(--bg);padding:40px 48px;
      box-shadow:0 1px 3px rgba(0,0,0,.08)}
.banner{background:#fff7e6;border:1px solid #f0d48a;color:#7a5b12;padding:8px 12px;
        border-radius:4px;font-size:13px;margin-bottom:24px}
h1{font-size:22px;margin:0 0 2px}
.sub{color:var(--muted);font-size:13px;margin:0 0 28px}
/* Layout A — the sender's logo sits upper-left, inline with the header; title + subtitle to its
   right. Rendered only when a logo was uploaded (page 1, stored in localStorage); with no logo the
   header degrades to the plain h1 + subtitle it has always been. The logo is a transparent PNG shown
   at a 72px height (a floor: the "ROOFING LLC" band stops being legible below ~56px) with the width
   following the aspect ratio, and sits on the page background — never in a white box. */
.rpt-header{display:flex;align-items:center;gap:18px;margin:0 0 28px;min-height:72px}
.rpt-logo{height:72px;width:auto;max-width:360px;display:block;flex:0 0 auto;background:transparent}
.rpt-headings{min-width:0}
.rpt-headings h1{margin:0 0 2px}
.rpt-headings .sub{margin:0}
h2{font-size:15px;letter-spacing:.02em;text-transform:uppercase;color:var(--accent);
   border-bottom:2px solid var(--accent);padding-bottom:6px;margin:32px 0 14px}
table{border-collapse:collapse;width:100%;font-size:14px;margin:8px 0}
table.kv th{text-align:left;width:38%;color:var(--muted);font-weight:600;vertical-align:top;
            padding:5px 10px 5px 0}
table.kv td{padding:5px 0}
table.data th{background:var(--soft);text-align:left;padding:8px 10px;border-bottom:1px solid var(--line);font-size:13px}
table.data td{padding:8px 10px;border-bottom:1px solid var(--line)}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
.note{color:var(--muted);font-size:13px}
.opnote{color:var(--muted);font-size:13px;margin-top:6px;line-height:1.45}
.callout{background:var(--soft);border-left:3px solid var(--accent);padding:10px 14px;margin:12px 0}
.diagram-full.has-svg{background:#fff;border:1px solid var(--line);padding:8px;min-height:0}
.roof-svg{width:100%;height:auto;display:block;-webkit-print-color-adjust:exact;print-color-adjust:exact}
.photo-img{width:100%;height:auto;display:block;border:1px solid var(--line);border-radius:4px}
.code{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:11px;color:var(--muted);
      background:var(--soft);border:1px solid var(--line);border-radius:3px;padding:1px 5px;margin-left:6px}
.diagram-full{background:repeating-linear-gradient(45deg,#f4f6f8,#f4f6f8 10px,#eef1f4 10px,#eef1f4 20px);
   border:1px solid #c2cad4;border-radius:6px;height:420px;display:flex;align-items:center;
   justify-content:center;color:#8a94a3;font-size:14px;margin:8px 0}
.legend{display:flex;gap:18px;flex-wrap:wrap;font-size:12px;color:var(--muted);margin:6px 0 10px}
.legend i.sw{display:inline-block;width:12px;height:12px;border-radius:2px;margin-right:5px;vertical-align:middle;-webkit-print-color-adjust:exact;print-color-adjust:exact}

/* the photo grid lives entirely in PHOTO_CSS (loaded last) — v74.3. Only the non-image fallback box
   and a generic caption remain here; .photo-row / .photo sizing must NOT be redefined here or it will
   fight the grid (a hard fixed pixel width on the photo card is what shrank every evidence photo). */
.photo-box{background:var(--soft);border:1px dashed #c2cad4;border-radius:4px;height:110px;
   display:flex;align-items:center;justify-content:center;color:#8a94a3;font-size:12px}
.caption{font-size:12px;color:var(--muted);margin-top:4px}
ul{margin:8px 0;padding-left:20px}
.foot{margin-top:36px;border-top:1px solid var(--line);padding-top:12px;color:var(--muted);font-size:12px}
.lead{background:var(--soft);border:1px solid var(--line);border-radius:6px;padding:14px 18px;margin:0 0 12px}
.lead h2{margin-top:0;border:none}
/* PRINT/PDF is the real deliverable. Browsers drop background colours when printing to save ink,
   which silently ate the pure-background legend swatches (valley, transition) and lightened the §4
   affected-area SVG fills. print-color-adjust:exact forces every coloured surface to print as drawn. */
@media print{
  .legend i.sw,.sw-affected,.sw-replaced,.sw-valley,.sw-transition,.sw-field,
  .roof-svg,.roof-svg *,.diagram-full,.diagram-full.has-svg{
    -webkit-print-color-adjust:exact;print-color-adjust:exact}
}
"""

# Report identity is DATA, not a hardcoded assumption. The banner is driven by
# report_context["kind"]; nothing in the renderer presumes a specific fixture.
#   SEED_VALIDATION  — the all-six-state seed oracle (facet D) coverage report
#   YAGER_VALIDATION — the full Yager integration fixture
#   PRODUCTION       — a real claim (no validation/prototype banner)
#   None / unknown   — neutral validation/sample banner (no fixture assumption)
def _report_banner(report_context):
    rc = report_context or {}
    kind = rc.get("kind", "VALIDATION_GENERIC")
    detail = rc.get("detail", "")
    if kind == "PRODUCTION":
        return ""  # real claim: no validation banner at all
    if kind == "SEED_VALIDATION":
        text = ("VALIDATION — Module&nbsp;2/3 seed oracle (facet&nbsp;D). Not a real claim; "
                "this fixture deliberately exercises all six comparison states for "
                "renderer/state coverage.")
    elif kind == "YAGER_VALIDATION":
        ref = f" ({e(detail)})" if detail else ""
        text = (f"VALIDATION — full Yager integration fixture{ref}. Not a real claim; "
                "quantities are engine-derived validation values from the selected "
                "repair events.")
    else:  # VALIDATION_GENERIC — safe default, makes NO fixture/facet assumption
        text = ("VALIDATION / sample output — not a real claim. Layout is a standardized "
                "template; quantities are validation data.")
    return f'<div class="banner">{text}</div>'


def _report_header(mode, logo_data_uri=None, prepared_by=None):
    """Layout A header. The subtitle is the mode label plus the typed attribution — the developer
    string 'standardized report template (Module 3 v0.1)' is gone. With no 'Prepared by' entered the
    mode label prints alone (never a placeholder). A logo renders only when a real image data URI was
    provided; with none, the header is the plain h1 + subtitle it has always been (clean degradation,
    no empty box). Any too-small warning lives on screen (page 1) — never in the report."""
    mode_label = "Comparison report" if mode == "COMPARISON" else "Required-scope-only report"
    prep = (prepared_by or "").strip()
    sub = f"{e(mode_label)} &middot; Prepared by {e(prep)}" if prep else e(mode_label)
    title_line = '<h1>Wood Shake Repair &mdash; Scope Justification</h1>'
    sub_line = f'<p class="sub">{sub}</p>'
    has_logo = isinstance(logo_data_uri, str) and logo_data_uri.startswith("data:image/")
    if has_logo:
        alt = f"{prep} logo" if prep else "Report logo"
        return (f'<header class="rpt-header">'
                f'<img class="rpt-logo" src="{e(logo_data_uri)}" alt="{e(alt)}">'
                f'<div class="rpt-headings">{title_line}{sub_line}</div></header>')
    return f'{title_line}{sub_line}'


def to_html(rendered, mode, title, report_context=None,
            logo_data_uri=None, prepared_by=None, shake_measurements=None):
    sec = rendered["sections"]
    argument = (sec.get(0) or {}).get("argument")
    lead = (f"<div class='lead'><h2>Summary of repair requirements</h2><p>{e(argument)}</p></div>"
            if argument else "")
    ordered = [sec1_claim(sec.get(1, {}), mode),
               sec2_carrier_summary(sec.get(2)),          # None in required-scope-only -> dropped
               sec3_shake_analysis(sec.get(3, {}), shake_measurements),
               sec4_diagram(sec.get(4, {})),
               sec5_comparison(sec.get(5, {})),
               sec6_evidence(sec.get(6, {})),
               sec7_attachments(sec.get(7, {}))]
    body = lead + "\n".join(f"<h2>{i} &middot; {e(t)}</h2>{inner}"
                            for i, (t, inner) in enumerate((p for p in ordered if p), start=1))
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{e(title)}</title>
<style>{CSS}{SWATCH_CSS}{PHOTO_CSS}</style></head><body><div class="page">
{_report_banner(report_context)}
{_report_header(mode, logo_data_uri, prepared_by)}
{body}
<div class="foot">This report presents repair scope, quantities, existing materials, and repair
impacts. It does not interpret coverage, state what is owed, or decide approval or denial.</div>
</div></body></html>"""

def build_samples():
    """Sample generation moved out of production renderer.

Production callers pass already-projected inputs to render()/to_html(); validation
fixtures live in the regression suite, not in this production renderer.
"""
    raise RuntimeError("build_samples requires a validation fixture harness; production rendering uses module3_caller.build_module3_inputs")


if __name__ == "__main__":
    print("MODULE 3 REPORT PROTOTYPE RENDERER\n" + "="*40)
    build_samples()
