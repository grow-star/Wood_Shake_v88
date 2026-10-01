#!/usr/bin/env python3
"""
CARRIER LAYER A — raw estimate text -> structured fields
========================================================
ADDITIVE. Layer A is the missing half of the carrier pipeline:

    uploaded file --[pdf.js / raw text]--> LAYER A (this module) --> structured fields
                                                                  --> page 3 (user confirms)
                                                                  --> manual_carrier_entry (Layer B)

Layer B (`carrier_parser.build_carrier_scope_summary`) already takes PRE-EXTRACTED structured
fields and is proven against 7 fixtures — it is NOT touched here. This module only produces the
raw -> structured step that previously did not exist (page 3 used a hardcoded fixture).

HARD RULES:
  * NEVER fabricate. A header field that is not found stays BLANK. A line whose category cannot
    be determined with confidence gets category=None and is FLAGGED "needs mapping" — it is never
    guessed into a category.
  * NEVER raise on bad input. Empty / whitespace / a scan with no text layer returns
    TEXT_LAYER_ABSENT with an empty header and zero lines, so the UI can degrade to manual entry.
  * The RCV (dollar) column is captured for completeness but the UI must not display it. No
    pricing surfaces in the tool; the deductible in the claim header is claim metadata, not scope
    pricing.
"""

from __future__ import annotations

import re

from shared_category_registry import REGISTRY_28

# ---------------------------------------------------------------------------
# status
PARSED = "PARSED"                      # header + line items found
PARSED_PARTIAL = "PARSED_PARTIAL"      # text present, but header or lines incomplete
TEXT_LAYER_ABSENT = "TEXT_LAYER_ABSENT"  # scan/photo/garbage: no usable text (NOT an error)

# A statement needs at least this much real text before we'll claim we read it.
_MIN_MEANINGFUL_CHARS = 40
_MIN_MEANINGFUL_WORDS = 8


# ---------------------------------------------------------------------------
# Sample / specimen pages
# ---------------------------------------------------------------------------
# State Farm statements embed a "Building Estimate Summary Guide" page built from a SAMPLE
# estimate ("Insured: Smith, Joe & Jane", "Claim number: 00-0000-000", "Deductible: $1,000.00").
# Those are decoys. We excise any page that announces itself as a sample before parsing, and we
# additionally reject placeholder-shaped values, so a sample value can never reach the claim header.
_SAMPLE_MARKERS = (
    "based on a sample estimate",
    "building estimate summary guide",
    "provided for reference only",
    # v70 DEFECT 1: Travelers appends a "Guide to Understanding Your Property Estimate" insert whose
    # sample estimate (named GUIDE_EXAMPLE: drywall/paint/carpet/cash/TV) carries its OWN numbered
    # line items. Left in, its items 1-6 precede and shadow the real estimate's items 1,2,5,6 (the
    # biggest roofing lines) under de-dupe. It is boilerplate — excise the whole page here, the same
    # way State Farm's specimen guide is excised, so neither its decoy header nor its sample lines
    # ever reach extraction.
    "guide to understanding your property estimate",
    "guide_example",
)
_PAGE_SPLIT = re.compile(r"Page:\s*\d+", re.I)
_PLACEHOLDER = re.compile(r"^[0\-\s]*$|^0{2}-0{4}-0{3}$|smith,\s*joe", re.I)


def _strip_sample_pages(text):
    """Drop pages that identify themselves as the sample/specimen guide."""
    chunks = _PAGE_SPLIT.split(text)
    kept = [c for c in chunks if not any(m in c.lower() for m in _SAMPLE_MARKERS)]
    return "\n".join(kept) if kept else text


def _is_placeholder(value):
    v = (value or "").strip()
    if not v:
        return True
    if _PLACEHOLDER.match(v):
        return True
    return v.replace("-", "").replace("0", "").strip() == ""      # e.g. 00-0000-000


# ---------------------------------------------------------------------------
# Claim header
# ---------------------------------------------------------------------------
# Label -> canonical field. Matching is case/whitespace tolerant and requires the value on the
# SAME line as the label (a label with an empty value is simply not found -> stays blank).
_HEADER_LABELS = [
    ("claim_number", (r"claim\s*(?:number|no\.?|#)", )),
    ("policy_number", (r"policy\s*(?:number|no\.?|#)", )),
    ("price_list", (r"price\s*list", )),
    ("type_of_loss", (r"type\s*of\s*loss", )),
    ("date_of_loss", (r"date\s*of\s*loss", )),
    ("deductible", (r"deductible", )),
    ("insured", (r"insured", )),
    ("loss_address", (r"property", )),
]

_CARRIERS = [
    ("State Farm", r"state\s*farm"),
    ("Allstate", r"allstate"),
    ("Liberty Mutual", r"liberty\s*mutual"),
    ("Safeco", r"safeco"),
    ("Farmers", r"farmers\s+insurance"),
    ("USAA", r"\busaa\b"),
    ("Travelers", r"travelers"),
    ("Nationwide", r"nationwide"),
    ("American Family", r"american\s*family"),
    ("Chubb", r"\bchubb\b"),
    ("Shelter", r"shelter\s*insurance"),
    ("Auto-Owners", r"auto[-\s]?owners"),
    ("Farm Bureau", r"farm\s*bureau"),
]

_ADDRESS_TAIL = re.compile(r"^[A-Za-z .'-]+,\s*[A-Z]{2}\s*\d{5}(?:-\d{4})?\s*$")
_STOP_LABELS = re.compile(
    r"^\s*(home|cellular|phone|work|email|e-mail|estimate|claim|policy|price|type|date|deductible|insured)\b",
    re.I)


def _find_header(lines):
    """Label-based extraction. Emits only what it actually finds; unfound fields stay blank."""
    header = {}
    for idx, raw in enumerate(lines):
        line = raw.strip()
        if not line:
            continue
        for field, patterns in _HEADER_LABELS:
            if field in header:
                continue
            for pat in patterns:
                m = re.match(rf"^\*?\s*{pat}\s*[:\-]\s*(.+)$", line, re.I)
                if not m:
                    continue
                value = m.group(1).strip()
                if not value or _is_placeholder(value):
                    continue                                   # empty label or sample decoy
                if field == "loss_address":
                    # the address usually wraps: "1 Sample St" / "Anytown, ST 00000-0000"
                    parts = [value]
                    for nxt in lines[idx + 1: idx + 3]:
                        nxt = nxt.strip()
                        if not nxt or _STOP_LABELS.match(nxt):
                            break
                        if _ADDRESS_TAIL.match(nxt):
                            parts.append(nxt)
                            break
                    header[field] = ", ".join(parts)
                else:
                    header[field] = value
                break
    return header


def _find_carrier(text):
    low = text.lower()
    for name, pat in _CARRIERS:
        if re.search(pat, low):
            return name
    return ""


def parse_deductible(value):
    """'$14,362.00' -> 14362.0. Returns None when absent/unparseable (never raises)."""
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    cleaned = str(value).replace("$", "").replace(",", "").strip()
    try:
        return float(cleaned)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Line items
# ---------------------------------------------------------------------------
# Numbered item, optionally flagged with a leading '*':
#     "1.  Remove Wood shakes - medium (1/2\") hand split"
#     "* 7.  R&R Gutter - aluminum - 6\""
_ITEM_HEAD = re.compile(r"^\s*\*?\s*(\d{1,3})\.\s+(\S.*?)\s*$")

# Quantity + unit, on the item's line OR (State Farm/Xactimate PDFs) the next line. The extractor
# often glues them together: "1.55SQ 68.31 0.00 105.88" — so the space is optional.
_UNITS = r"SQ|LF|SF|EA|HR|DA|WK|MO|CY|GL|RL|BF|BX|PR"
# v73 DEFECT 2: the page-3 unit dropdown is DERIVED from this ONE list (via the bridge), so the two
# can never drift again. _UNITS is the single source of truth for both reading and hand-entry; adding
# a unit here makes it selectable with no second edit.
UNIT_LIST = tuple(_UNITS.split("|"))
_QTY_UNIT_LEAD = re.compile(rf"^\s*([\d,]+(?:\.\d+)?)\s*({_UNITS})\b(.*)$", re.I)
_QTY_UNIT_TAIL = re.compile(rf"([\d,]+(?:\.\d+)?)\s*({_UNITS})\b", re.I)
_MONEY = re.compile(r"([\d,]+\.\d{2})")

# Lines that are totals/headers, never items.
_NOT_AN_ITEM = re.compile(
    r"^\s*(totals?:|line item totals?:|grand total|area totals?:|recap of|quantity\s+unit|"
    r"continued\b|page:|date:)", re.I)


def _to_float(s):
    try:
        return float(str(s).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# STRUCTURE PROPOSAL — the tool PROPOSES, the human ASSERTS (page 3)
# ---------------------------------------------------------------------------
# Xactimate groups line items under AREA HEADERS naming the structure the lines belong to:
# "Roof1", "Ext_Surfaces", "CHRIS_DEVORE___7", "Detached Garage". They sit on their own line, carry
# no item number, and are followed by the items they own.
#
# WHY THIS MATTERS: a carrier estimate covering a dwelling AND a detached garage has TWO ridge-cap
# lines that are NOT duplicates. Without a structure per line, manual_carrier_entry cannot tell
# "one structure, two ridge runs — SUM them" from "two structures — KEEP THEM SEPARATE". They are
# opposite answers, and page 3 hard-coded every row to 'roof', so the distinction has never been
# expressible from the UI at all.
#
# THIS IS A PROPOSAL, NOT AN ASSERTION. The header text is a heuristic on a carrier's own naming
# convention. `structure_confidence` is reported honestly and page 3 REQUIRES the human to confirm
# whenever more than one structure is detected — same discipline as the exposed/damaged transition
# gate. When only one structure is found there is nothing to decide and NO interaction is required.
_AREA_HEADER = re.compile(r"^\s*([A-Za-z][A-Za-z0-9 _\-/&']{1,48})\s*$")
# Never treat these as a structure name: they are section labels, not areas.
_NOT_A_STRUCTURE = re.compile(
    r"^\s*(description|quantity|unit|price|tax|rcv|acv|depreciation|total|totals|subtotal|"
    r"grand total|recap|summary|continued|page|date|notes?|remarks?|coverage|deductible|"
    r"line item totals?|area totals?|material|labor|overhead|profit|estimate|claim|insured|"
    r"policy|adjuster|contact|phone|email|address)\b", re.I)
DEFAULT_STRUCTURE_ID = "roof"


# A TRADE SECTION IS NOT A STRUCTURE. Estimates also group items under trade headings — the real
# Yager State Farm text has "Valley Metal Replacement" and "Flashing/ Appurtenances" sitting on their
# own lines, textually identical in shape to an area header. Treating those as structures would be
# WORSE THAN DOING NOTHING: it would split one roof into several, and two ridge-cap lines that ought
# to SUM would be kept apart as "different structures". Verified against the real fixture — this
# blocklist exists because the naive rule got it wrong there.
_TRADE_WORDS = re.compile(
    r"\b(valley|ridge|hip|cap|flash|flashing|appurtenance|shingles?|shakes?|felt|underlay|starter|"
    r"drip|edge|vent|ventilat|pipe|jack|chimney|skylight|gutter|downspout|siding|paint|fascia|"
    r"soffit|decking|sheath|ice|water|barrier|tear[- ]?off|removal|replacement|repair|labor|"
    r"material|dumpster|permit|steep|charge|slope|roofing|restoration|service|remodel|"
    r"contents|cleaning|general|conditions|demolition|framing|drywall|insulation)\b", re.I)

# v70 DEFECT 2 — a NON-ROOF surface AREA is not a STRUCTURE. Xactimate groups a building's exterior
# wall/soffit/siding work under "Ext_Surfaces" (and elevations/exterior/interior labels). These are
# AREAS WITHIN a structure, not separate buildings, and they carry no roof — so they must never open
# a new roof-structure boundary. A single-building estimate legitimately shows Roof1 AND Ext_Surfaces
# (one structure, two areas); only genuine roof areas ("Roof1"/"Roof2") and separate buildings
# ("Detached Garage") define a structure the roof measurements could belong to.
_NON_ROOF_AREA = re.compile(
    r"^(ext[_ ]?surfaces?|exterior(\s+surfaces?)?|elevations?|interior)$", re.I)

# v76 DEFECT 3 — a heading opens a STRUCTURE only if it names a BUILDING. Xactimate also groups items
# under EXTERIOR ELEVATIONS ("Front Elevation", "Rear Elevation", …) and INTERIOR ROOMS / LEVELS
# ("Bathroom", "Living room", "Main Level", …). Those are areas WITHIN a building, never a separate
# building, so they must never open a new structure boundary — same class as the v70/v71 trade-heading
# bug. A real detached building (Shed, Detached Garage, Roof1/Roof2) does NOT match this and still opens
# a structure, so genuine multi-building estimates (Pershing's Dwelling + Detached Garage) are unaffected.
_ROOM_OR_ELEVATION = re.compile(
    r"\b(elevation|bath(room)?|bedroom|kitchen|living(\s*room)?|dining(\s*room)?|family\s*room|"
    r"great\s*room|bonus\s*room|rec\s*room|hall(way)?|closet|laundry|utility|mud\s*room|office|den|"
    r"study|foyer|entry(way)?|stair(s|way|well)?|pantry|nook|loft|basement|attic|crawl\s*space|"
    r"master|main\s*level|upper\s*level|lower\s*level|(first|second|third|ground|top)\s*floor)\b", re.I)


def _looks_like_area_header(raw):
    """A bare line naming an AREA/STRUCTURE, e.g. 'Roof1', 'Detached Garage', 'CHRIS_DEVORE___7'.

    CONSERVATIVE BY DESIGN, and deliberately asymmetric. A false NEGATIVE means every line lands in
    one structure — exactly today's behaviour, and the common single-structure case is correct
    anyway. A false POSITIVE invents a structure boundary that stops legitimate duplicates from
    summing, which silently under-scopes. So when in doubt, this returns None."""
    if _ITEM_HEAD.match(raw) or _NOT_AN_ITEM.match(raw) or _NOT_A_STRUCTURE.match(raw):
        return None
    if _MONEY.search(raw) or _QTY_UNIT_TAIL.search(raw):
        return None                                  # a data row, not a header
    m = _AREA_HEADER.match(raw)
    if not m:
        return None
    name = m.group(1).strip()
    if not re.search(r"[A-Za-z]", name) or len(name.split()) > 5:
        return None
    if _TRADE_WORDS.search(name):
        return None                                  # a TRADE section, not a structure
    if _NON_ROOF_AREA.match(name):
        return None                                  # a non-roof AREA of the structure, not a new one
    if _ROOM_OR_ELEVATION.search(name):
        return None                                  # an elevation or interior room, not a building
    if propose_category(name)[0] is not None:
        return None                                  # it names a material -> a trade section
    return name


def _extract_lines(lines):
    """Find numbered line items with description + qty + unit. RCV captured but never displayed."""
    items = []
    i = 0
    n = len(lines)
    current_structure = None          # None until an area header is actually seen
    while i < n:
        raw = lines[i]
        if _NOT_AN_ITEM.match(raw):
            i += 1
            continue
        head = _ITEM_HEAD.match(raw)
        if not head:
            # Not an item — it may be the AREA HEADER that names the structure owning what follows.
            area = _looks_like_area_header(raw)
            if area:
                current_structure = area
            i += 1
            continue
        number = int(head.group(1))
        desc = head.group(2).strip()

        qty = unit = None
        rcv = None

        # (a) qty+unit already on the description line (many carriers)
        tail = _QTY_UNIT_TAIL.search(desc)
        if tail and not re.match(r"^\d", desc):
            # only treat as qty if it sits at the END of the description
            if desc.rstrip().endswith(tail.group(0).strip()) or tail.end() > len(desc) - 12:
                qty = _to_float(tail.group(1))
                unit = tail.group(2).upper()
                desc = desc[:tail.start()].strip(" -\u2013\t")

        # (b) otherwise qty+unit lead the NEXT non-empty line ("1.55SQ 68.31 0.00 105.88")
        j = i + 1
        if qty is None:
            while j < n and not lines[j].strip():
                j += 1
            if j < n:
                lead = _QTY_UNIT_LEAD.match(lines[j])
                if lead:
                    qty = _to_float(lead.group(1))
                    unit = lead.group(2).upper()
                    monies = _MONEY.findall(lead.group(3) or "")
                    if len(monies) >= 3:
                        rcv = _to_float(monies[2])          # QTY UNIT | price | tax | RCV ...
                    i = j                                    # consume the qty line

        if qty is None or not unit:
            i += 1
            continue                                         # a numbered thing that isn't an item

        desc = re.sub(r"\s{2,}", " ", desc).strip()
        cat, in_scope, confidence, needs_mapping, reason = propose_category(desc)
        disposition, _dcat = propose_disposition(desc)
        items.append({
            "n": number,
            "description": desc,
            "qty": qty,
            "unit": unit,
            "rcv": rcv,                                      # captured; UI must not display it
            "suggested_category": cat,
            "suggested_in_scope": in_scope,
            "suggested_disposition": disposition,           # v67: proposal only — visible & overridable
            "suggested_operation": propose_operation(desc), # v72: carrier ACTIVITY from its own wording (None = unstated)
            "confidence": confidence,
            "needs_mapping": needs_mapping,
            "reason": reason,
            # PROPOSED structure. `None` means no area header was seen above this line, which page 3
            # renders as the single default structure — the common case, requiring no interaction.
            "suggested_structure_id": current_structure,
            "structure_confidence": "medium" if current_structure else "default",
        })
        i += 1
    # de-dupe TRUE repeats only: a continued-page header can reprint an item (same number AND same
    # description) — those collapse. Two DISTINCT items that happen to share a number (a boilerplate
    # sample, a second sequence) must NOT let one silently drop the other; keying on number alone is
    # exactly what dropped the real wood-shake lines. Key on (number, normalized description).
    seen, out = set(), []
    for it in items:
        key = (it["n"], re.sub(r"\s+", " ", str(it["description"]).lower()).strip())
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return sorted(out, key=lambda x: x["n"])


# ---------------------------------------------------------------------------
# Category proposal (deterministic rules -> REGISTRY_28). Never guesses.
# ---------------------------------------------------------------------------
# (pattern, category, in_scope, confidence). Order matters: first match wins.
_RULES = [
    (r"valley\s*metal|valley\s*flashing",              "VALLEY_METAL",     True,  "high"),
    (r"wood\s*shake|shakes?\b|cedar\s*shake",          "SHAKE_FIELD_RR",   True,  "high"),
    (r"pipe\s*jack|jack\s*flash|vent\s*pipe\s*flash",  "PIPE_JACK_FLASH",  True,  "high"),
    (r"chimney\s*flash|counter\s*flash",               "CHIMNEY_FLASH",    True,  "high"),
    (r"step\s*flash",                                  "STEP_FLASH",       True,  "high"),
    (r"endwall|headwall",                              "ENDWALL_FLASH",    True,  "high"),
    (r"transition\s*flash",                            "TRANSITION_FLASH", True,  "high"),
    (r"skylight\s*flash|skylight",                     "SKYLIGHT_FLASH",   True,  "medium"),
    (r"ridge\s*cap|hip\s*(?:and|&|/)\s*ridge",         "RIDGE_CAPS",       True,  "high"),
    (r"hip\s*cap",                                     "HIP_CAPS",         True,  "high"),
    (r"ridge\s*vent",                                  "RIDGE_VENT",       True,  "high"),
    (r"drip\s*edge",                                   "DRIP_EDGE",        True,  "high"),
    (r"starter",                                       "STARTER",          True,  "high"),
    (r"ice\s*(?:and|&)?\s*water|ice\s*&\s*water|\biws\b", "IWS",           True,  "high"),
    (r"felt|underlayment",                             "FIELD_FELT",       True,  "high"),
    (r"tear\s*-?\s*off|remove\s*roof",                 "FIELD_TEAROFF",    True,  "medium"),
    (r"box\s*vent|turtle\s*vent",                      "BOX_VENT",         True,  "high"),
    (r"turbine",                                       "TURBINE_VENT",     True,  "high"),
    # POWER ATTIC VENT — its own category, NEVER VENT_CAP. Devore's Travelers estimate lists
    # "12. R&R Roof mount power attic vent  1.00 EA" SEPARATELY from
    # '11. Exhaust cap - through roof - up to 4"  4.00 EA'. Conflating them would compare a powered
    # ventilator against a passive cap and mis-state the difference. Placed ABOVE the VENT_CAP rule
    # so ordering can never let a generic cap pattern claim it first; the two patterns are disjoint
    # in any case ("power attic vent" has no "cap", "exhaust cap" has no "power").
    (r"power\s*attic\s*vent|power\s*vent|roof\s*mount\s*power", "POWER_VENT", True, "high"),
    # VENT_CAP HAD NO RULE AT ALL. The id has been in the registry since v1, but nothing ever mapped
    # to it, so EVERY "exhaust cap" line on EVERY carrier estimate has been falling through to
    # UNMAPPED_REVIEW — including the 4.00 EA on Devore's Travelers estimate. Found while proving the
    # power vent does not swallow it; you cannot demonstrate "these two stay separate" when one of
    # them was never mapped in the first place.
    (r"exhaust\s*cap|vent\s*cap|\bcap\b\s*-?\s*through\s*roof", "VENT_CAP", True, "high"),
    # v74 — FLUE_CAP had no rule; Devore's Travelers estimate wrote "R&R Flue cap 3.00 EA" and it fell
    # to UNMAPPED. A flue cap is its own item, distinct from an exhaust/vent cap. Placed here (disjoint
    # from the cap patterns above: none of them contain "flue").
    (r"flue\s*cap",                                    "FLUE_CAP",         True,  "high"),
    (r"steep\s*charge|steep\s*roof",                   "STEEP_CHARGE",     True,  "medium"),
    (r"high\s*slope",                                  "HIGH_SLOPE_CHARGE", True, "medium"),
    (r"chimney\s*chase",                               "CHIMNEY_CHASE_COVER", True, "medium"),
    (r"gable|cornice",                                 "GABLE_CORNICE",    True,  "medium"),
    # v74 — ROOFER_LABOR is DISTINCT from GENERAL_LABOR (Joseph): on the live Travelers claim
    # "Roofer - per hour, 16.00 HR" was the ENTIRE labor allowance against three material-only lines,
    # so it gets its own id and §5 can speak to it precisely. RECEIVE-ONLY: recognised, never a
    # required side.
    (r"roofer\s*-?\s*per\s*hour|\broofer\b|roofing\s*labor", "ROOFER_LABOR", True, "medium"),
    (r"general\s*labor|labor\s*-?\s*general",          "GENERAL_LABOR",    True,  "medium"),
    # v74 — DEBRIS_DISPOSAL: haul-off / dumpster / dump fees. It USED to be classed non-roof and clear
    # the gate silently (v67). It is now RECOGNISED and ACKNOWLEDGED (receive-only, no required side).
    # Whether it counts as roof scope is decided by the tear-off wording downstream (see the debris
    # attribution / no-haul-off gap rule), never by this classification.
    (r"haul\s*debris|debris\s*removal|dump\s*fee|dumpster|haul\s*-?\s*off|haul\s*away", "DEBRIS_DISPOSAL", True, "high"),
    # v74 — EQUIPMENT: ladders with jacks and plank, staging, scaffold, lifts. RECEIVE-ONLY.
    (r"ladder.{0,20}(?:jack|plank)|jacks?\s*(?:and|&)\s*plank|\bstaging\b|scaffold|\blift\b\s*-?\s*(?:rent|per)|equipment\s*(?:rent|-)", "EQUIPMENT", True, "medium"),
]

# Confidently NOT part of the roof repair -> out of scope by default (NOT "needs mapping":
# we know exactly what these are, they simply aren't roof scope).
_NOT_ROOF = [
    (r"gutter",            "gutters are not part of the roof covering scope"),
    (r"downspout",         "downspouts are not part of the roof covering scope"),
    # v74: debris / dumpster / haul-off is NO LONGER classed non-roof here — it maps to DEBRIS_DISPOSAL
    # (recognised & acknowledged). Whether it is a ROOF gap is decided by the tear-off wording, not by
    # a fixed classification of the word "debris" (v67 removed).
    (r"fireplace",         "fireplace line is not roof scope"),
    (r"labor\s*minimum",   "labor minimum is not a roof scope line"),
    (r"siding|window|fence|screen", "not a roof scope line"),
    # v67: `deck` used to be bare, so every ROOF DECKING / sheathing line was silently classed non-roof
    # (MABCD R905.2.1 territory) and never surfaced. Match only a standalone (patio/exterior) deck: not
    # "roof deck", not "decking", not "deck sheathing". The disposition model is the real protection —
    # nothing is silently dismissed — but a tighter proposal is still better.
    (r"(?<!roof )\bdeck\b(?!ing)(?!\s*sheath)", "a deck is exterior carpentry, not roof covering scope"),
    # v66: positive non-roof trade classification. These are KNOWN — another trade — not "unknown
    # roof", so they are out of scope by default and do NOT flag. Each is tight enough to avoid a
    # roof-adjacent collision (soffit vent, fascia flashing and chimney brick still FLAG — the v54
    # under-scope protection is untouched). The test is "do we positively recognise another trade",
    # never "did we fail to find a roof category".
    (r"\bsoffit\b(?!\s*vent)(?!\s*return)",   "soffit is exterior carpentry, not roof covering scope"),
    (r"\bfascia\b(?!\s*flash)",  "fascia is exterior carpentry, not roof covering scope"),
    (r"house\s*wrap|housewrap|building\s*wrap", "house wrap is a wall weather barrier, not roof scope"),
    (r"\bstucco\b",              "stucco is an exterior wall finish, not roof scope"),
    (r"drywall|sheetrock|gypsum\s*board", "drywall is interior finish, not roof scope"),
    (r"\bcarpet\b|\bflooring\b|hardwood\s*floor|vinyl\s*plank|laminate\s*floor", "flooring is not roof scope"),
    (r"content\s*manipulation|\bcontents\b", "contents handling is not roof scope"),
    # Painting / priming / sealing of a NON-ROOF surface. Requires an explicit non-roof subject, so
    # "paint drip edge" or "paint chimney flashing" is NOT caught here and still reaches the roof rules.
    (r"(?:prime|paint|repaint|seal|stain)\w*\s+.{0,30}?(?:soffit|fascia|siding|brick|masonry|stucco|exterior|interior|trim|drywall|deck|fence|door|window)",
                           "painting of a non-roof surface is not roof scope"),
]


# SHAKE_FIELD_RR is the roof-covering FIELD material — the LEAST specific rule. A line that ALSO names a
# specific component (starter, ridge/hip cap, valley metal, a flashing, a vent, tear-off, ...) is that
# component, not the field. This is the only generic rule in the set; everything else names a specific
# part or operation. See the audit in layer_a_regression.py.
_GENERIC_FIELD = {"SHAKE_FIELD_RR"}


# v72 DEFECT 1: derive the carrier's ACTIVITY (operation) from its own wording. Until now Layer A
# emitted no operation, so every parsed line reached the comparison operation-less and defaulted to a
# full R&R MATCH — a carrier who funded the material and NONE of the labor read as being in agreement.
# The op the reader draws the conclusion from is the carrier's own; we only classify it, never guess:
# an unrecognised description returns None (no operation asserted, the comparison then HOLDS exactly as
# before rather than manufacturing a divergence). Values are the canonical operation_dimension codes
# (kept as literals so Layer A stays decoupled from the comparison layer); they must stay in step with
# operation_dimension.CANONICAL_OPS. Phrases are scanned MOST-SPECIFIC-FIRST (a compound phrase before
# any substring it contains) so "detach & reset" never reads as "reset"/"remove", etc.
_OPERATION_PHRASES = (
    (r"detach\s*(?:&|and|/)\s*reset|\bd\s*&\s*r\b", "DETACH_RESET"),
    (r"material[\s-]*only|\bmat\.?\s*only", "MATERIAL_ONLY"),
    (r"labor[\s-]*only", "INSTALL_ONLY"),                       # labor only = installation labor, no material
    (r"\br\s*&\s*r\b|remove\s*(?:&|and)\s*replace|replace\s*\(?\s*w/?\s*removal\)?", "R_AND_R"),
    (r"\btear[\s-]*off\b", "TEAR_OFF"),
    (r"\bremov(?:e|al)\b", "REMOVE"),
    (r"\binstall\b", "INSTALL_ONLY"),
    (r"\breplace\b", "REPLACE"),
)


def propose_operation(description):
    """Layer A's PROPOSED canonical operation for a carrier line, read from the description's own
    wording. None when nothing decisive is present — never guessed. The comparison treats None as
    'no operation asserted' and holds the line (the §1.3 discipline), so this only ever ADDS a
    divergence the carrier's words actually support (material-only, labor-only, detach & reset, …)."""
    low = str(description or "").lower()
    for pat, op in _OPERATION_PHRASES:
        if re.search(pat, low):
            return op
    # v76 DEFECT 2 (Joseph, binding): a bare line that NAMES A MATERIAL but carries no operation verb
    # is a REPLACE — "the material and the labor to install a new item", NOT the removal. It is not R&R
    # (which would overstate the removal the carrier did not write and weaken the argument, since R&R
    # already contains the removal we argue for), and it is not "install only" (the carrier did not write
    # install-only). Only a recognised material line qualifies; an unrecognised line still returns None.
    if propose_category(description)[0] is not None:
        return "REPLACE"
    return None


def propose_category(description):
    """(category, in_scope, confidence, needs_mapping, reason).

    A description we cannot map with confidence returns category=None, needs_mapping=True — it is
    NEVER guessed into a category. A description we recognize as non-roof returns category=None,
    needs_mapping=False, in_scope=False (known, just not roof scope).

    SPECIFICITY BEATS ORDER (v63): when a description matches more than one rule, the MOST SPECIFIC
    wins, not the first in the list. The greedy "wood shake" field pattern used to match before the
    more specific "starter" and "hip / ridge cap" rules, so "Wood shake/shingle starter" and "Hip /
    Ridge cap - wood shake shingles" both fell to SHAKE_FIELD_RR — making the report claim the carrier
    omitted a starter course and ridge/hip caps they had actually paid for. Same failure class as
    VENT_CAP (v58): a category silently never receives its lines. A component rule (anything not in
    _GENERIC_FIELD) beats the field-material rule; ties within a tier are broken by list order."""
    d = (description or "").lower()
    if not d.strip():
        return None, False, "low", True, "empty description"

    for pat, reason in _NOT_ROOF:
        if re.search(pat, d):
            return None, False, "high", False, reason

    matches = [(cat, in_scope, conf) for pat, cat, in_scope, conf in _RULES
               if re.search(pat, d) and cat in REGISTRY_28]        # registry is the authority
    if not matches:
        return None, False, "low", True, "could not map this description to a category"
    specific = [m for m in matches if m[0] not in _GENERIC_FIELD]
    cat, in_scope, conf = specific[0] if specific else matches[0]
    return cat, in_scope, conf, False, ""


# v67: interior vs exterior side for a recognised non-roof trade. This only decides which disposition
# to PRE-SELECT on page 3 — the user sees it and can change it, so a wrong guess is visible and
# harmless, never a silent dismissal. Default is exterior (most non-roof lines on a roofing estimate).
_INTERIOR = (r"drywall|sheetrock|gypsum|\bcarpet\b|\bflooring\b|hardwood|vinyl\s*plank|laminate|"
             r"\bcontents?\b|content\s*manipulation|ceiling|\binsulation\b|(?:prime|paint|repaint|seal|stain)"
             r"\w*\s+.{0,30}?(?:interior|drywall|ceiling)")


def propose_disposition(description):
    """Layer A's PROPOSED disposition for a carrier line — never a decision, only a pre-selection the
    user can see and override on page 3:

        'in_scope'  a high-confidence roof match (page 3 also pre-selects its category)
        'interior'  a recognised interior non-roof trade
        'exterior'  a recognised exterior non-roof trade
        'undecided' we could not identify it — the user MUST decide (nothing is silently dismissed)

    Returns (disposition, category). category is set only for 'in_scope'."""
    cat, in_scope, _conf, needs_mapping, _reason = propose_category(description)
    if needs_mapping:
        return "undecided", None
    if cat is not None:
        return "in_scope", cat
    d = (description or "").lower()
    return ("interior" if re.search(_INTERIOR, d) else "exterior"), None


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
# v66: name the non-roof TRADE for the report's honest acknowledgment. Descriptions are already known
# to be non-roof (propose_category returned needs_mapping=False, category=None); this only groups them
# into trade names for one honest line. Order = specificity; the first match wins.
_NON_ROOF_TRADE = [
    (r"gutter\s*guard|gutter|downspout",            "gutters"),
    (r"house\s*wrap|housewrap|building\s*wrap",      "house wrap"),
    (r"\bsoffit\b|\bfascia\b",                        "soffit & fascia"),
    (r"siding",                                       "siding"),
    (r"\bstucco\b",                                   "stucco"),
    (r"drywall|sheetrock|gypsum",                     "drywall"),
    (r"\bcarpet\b|\bflooring\b|hardwood\s*floor|vinyl\s*plank|laminate", "flooring"),
    (r"prime|paint|repaint|\bseal\b|stain",           "paint"),
    (r"\bfence\b",                                     "fencing"),
    (r"\bdeck\b",                                      "decking"),
    (r"\bscreen\b|\bwindow\b",                         "windows"),
    (r"fireplace",                                     "fireplace"),
    (r"content",                                       "contents"),
    (r"debris|dumpster|haul|dump\s*fee",              "debris removal"),
]


def _non_roof_trade(description):
    d = (description or "").lower()
    for pat, trade in _NON_ROOF_TRADE:
        if re.search(pat, d):
            return trade
    return "other non-roof work"


def summarize_non_roof(lines):
    """Count the carrier lines the USER dispositioned as out-of-roof-scope, split by side, for the
    report's §7 acknowledgment. Returns {'exterior': int, 'interior': int, 'count': int}. v67: this
    now reports the user's ASSERTED dispositions, not Layer A's guesses. NO pricing, no conclusions —
    counts only. {'exterior':0,'interior':0,'count':0} when there are none."""
    exterior = interior = 0
    for l in (lines or []):
        disp = l.get("disposition")
        if disp == "exterior":
            exterior += 1
        elif disp == "interior":
            interior += 1
    return {"exterior": exterior, "interior": interior, "count": exterior + interior}


def parse_carrier_estimate_text(text):
    """Raw estimate text -> provider-neutral structured result. Never raises.

    { status, claim_header{...}, lines[...], notes[] }
    """
    notes = []
    raw = text if isinstance(text, str) else ""

    # --- no usable text (a scan / photo has no text layer) -> degrade to manual entry ---
    stripped = raw.strip()
    words = re.findall(r"[A-Za-z]{2,}", stripped)
    if (len(stripped) < _MIN_MEANINGFUL_CHARS) or (len(words) < _MIN_MEANINGFUL_WORDS):
        return {
            "status": TEXT_LAYER_ABSENT,
            "claim_header": _blank_header(),
            "lines": [],
            "notes": ["No readable text layer was found in this file (it looks like a scan or "
                      "photo). Enter the line items manually."],
        }

    body = _strip_sample_pages(raw)
    lines = body.splitlines()

    header = _find_header(lines)
    # Carrier is detected from the RAW text, not the sample-stripped body: the brand is a
    # document-wide signal (the summary-guide page is the carrier's own), unlike the sample's
    # decoy VALUES (insured/claim number/deductible), which must never be read.
    carrier = _find_carrier(raw)
    if carrier:
        header["carrier"] = carrier

    items = _extract_lines(lines)

    claim_header = _blank_header()
    claim_header.update({k: v for k, v in header.items() if v})
    ded = parse_deductible(claim_header.get("deductible"))
    if ded is not None:
        claim_header["deductible"] = ded                      # numeric; renderer also tolerates str

    missing = [k for k, v in claim_header.items() if v in (None, "")]
    if missing:
        notes.append("Not found in the file (left blank for you to fill): " + ", ".join(missing) + ".")
    flagged = [i["n"] for i in items if i["needs_mapping"]]
    if flagged:
        notes.append("Could not map line(s) " + ", ".join(str(n) for n in flagged)
                     + " to a category — please choose one or mark them out of scope.")
    if not items:
        notes.append("No line items could be read from this file. Add them manually below.")

    status = PARSED if (items and not missing) else PARSED_PARTIAL
    return {"status": status, "claim_header": claim_header, "lines": items, "notes": notes}


def _blank_header():
    return {"insured": "", "loss_address": "", "claim_number": "", "policy_number": "",
            "carrier": "", "price_list": "", "type_of_loss": "", "date_of_loss": "",
            "deductible": ""}


if __name__ == "__main__":
    import sys, json
    src = sys.argv[1] if len(sys.argv) > 1 else "-"
    data = sys.stdin.read() if src == "-" else open(src, encoding="utf-8", errors="replace").read()
    print(json.dumps(parse_carrier_estimate_text(data), indent=1))
