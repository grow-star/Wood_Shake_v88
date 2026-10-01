#!/usr/bin/env python3
"""
MODULE 2 — SCOPE EXPANSION ENGINE  +  SEED REGRESSION
=====================================================
The missing Module 2 implementation. Module 1 (regression_test.py, v3.3, GREEN)
computes geometry; THIS turns that frozen geometry into the quantified material/
labor line list. Built to Module 2 Scope Expansion Spec v1.2 (§2 rule table).

BOUNDARY (Architecture v1.5 / Module 2 §0):
  - Reads the Module 1 interface; NEVER measures geometry.
  - Does all quantity math; no pricing, no replacement escalation, no report.
  - Source-agnostic: same rules whether a value came from EagleView or a user-
    placed event — Module 2 only sees the interface numbers.

REGRESSION INTEGRITY:
  Every expected number in the seed suite traces to a value the GREEN Module 1
  suite already asserts, or to a locked study-sheet area. No invented inputs.
  Facet D is a COMPLETE single-facet fixture (every line traceable):
    area 28.2 SF (GREEN test 3) ; eave 2.00 ; ridge 6.32/6.56=96% ; hip
    2.62/4.04=65% ; rake 0.00 ; valley L4 edge 7.74 ft (XML).
  Plus the green Yager facets (N/R, dormer-outside L4/L5, L, M, V-J, V-E, V full,
  P chimney), each asserted ONCE from green-traceable totals, and the synthetic
  rule guards (94/96 boundary, transition fire/no-fire, grouping, informational,
  repair_factor) per Module 2 §12.

  This is a SEED suite (Module 2 §12 discipline: seed then grow). Growing to all
  20 valley-sides = feeding each remaining facet's GREEN-frozen interface in as
  another snapshot; the engine logic does not change.
"""

import math
from dataclasses import dataclass, field
from typing import Mapping, Optional

from shared_category_registry import REGISTRY_28   # authority for a user-supplied OTHER category

# ---- locked parameters (Module 1 engine constants / Module 2 §1) -------------
EXPOSURE_IN      = 10.0     # default 24" shake exposure
SHAKE_WIDTH_IN   = 7.0      # default measured average width
SHAKES_PER_SQ    = 14400.0 / (SHAKE_WIDTH_IN * EXPOSURE_IN)
# CSSB interlayment strip width — a SOURCED CONSTANT, never a bare literal. CSSB FAQ (cssbureau.com):
#   "The CSSB recommends using an 18" wide strip of No.30 ASTM D226 Type II or ASTM D4869 Type IV
#    roofing felt laid over the top portion of the shakes and extending on to the sheathing... The
#    bottom edge of the felt should be positioned above the butt of the shake at a distance equal to
#    twice the weather exposure."
# GEOMETRY: one 18" strip is laid PER COURSE; courses repeat every `exposure_in`, so every
# exposure_in of roof rise consumes 18" of felt width -> felt ratio = 18 / exposure_in (SF felt per
# SF of roof). The strip width does NOT vary by shake length (the source states it flat); the formula
# is dynamic in the MEASURED per-job exposure. The source's "twice the weather exposure" is a
# PLACEMENT rule (where the strip's bottom edge sits), NOT the quantity multiplier — do not use it so.
CSSB_INTERLAYMENT_STRIP_IN = 18.0
CAP_THRESHOLD    = 0.95     # §6 continuous-metal round-to-full-run rule
IWS_BAND_FT      = 3.0      # valley/transition underlayment band = LF * 3 ft

STEEP_TIERS = ("7-9", "10-12", ">12")   # §7

# ---- Module 1 interface (read-only inputs; Module 2 §0) ----------------------
@dataclass
class Edge:
    edge_type: str          # EAVE RAKE RIDGE HIP VALLEY FLASHING STEPFLASH
    contact_LF: float
    edge_total_LF: float

@dataclass
class Appurt:
    type: str               # CHIMNEY SKYLIGHT PIPE TURTLE TURBINE OTHER
    affected_SF: float = 0.0
    contacted: bool = True          # informational events do not enter the stream
    group: Optional[str] = None     # cross-facet grouping link (§4.1)
    size_class: Optional[str] = None  # chimney S/A/L -> Xactimate code
    # --- user-defined ("OTHER") appurtenances -------------------------------
    # Both default to None, so every existing construction is unchanged.
    other_label: Optional[str] = None     # the user's free-text name for the feature
    other_category: Optional[str] = None  # optional REGISTRY_28 id; None -> UNMAPPED (human review)

@dataclass
class Transition:
    contact_LF: float
    edge_total_LF: float
    # PATH B (spec amendment: Transition Repair Events v0.1). A DETECTED transition the user
    # confirmed — via the exposed+damaged gate — as a repair event in its own right. Defaults to
    # False, so every existing construction and every existing test is unchanged.
    selected: bool = False

@dataclass
class M1Interface:
    """One confirmed valley-side or per-slope union from Module 1."""
    affected_SF: float = 0.0
    valley_LF_in_scope: float = 0.0
    edges: list = field(default_factory=list)            # list[Edge]
    appurts: list = field(default_factory=list)          # list[Appurt] (confirmed only)
    transitions: list = field(default_factory=list)      # list[Transition]
    facet_pitch_tier: Optional[str] = None               # one of STEEP_TIERS or None
    high_slope_user_flag: bool = False                   # §7 user confirm
    shake_width_in: float = SHAKE_WIDTH_IN
    exposure_in: float = EXPOSURE_IN
    is_replacement: bool = False                          # v61 §facet-replacement: bill SQ, not EA

# ---- output line -------------------------------------------------------------
@dataclass
class ScopeLine:
    item: str
    category_id: str
    qty: float
    unit: str
    gate: str               # AUTO | CONFIRM
    citation: str
    xact_code: Optional[str] = None

    def key(self):
        return (self.category_id, round(self.qty, 2), self.unit, self.gate)


# ---- helpers -----------------------------------------------------------------
def _shakes_per_sq(width_in=SHAKE_WIDTH_IN, exposure_in=EXPOSURE_IN):
    width = float(width_in)
    exposure = float(exposure_in)
    if width <= 0 or exposure <= 0:
        raise ValueError("shake width and exposure must be greater than 0")
    return 14400.0 / (width * exposure)

def _shake_count(affected_SF, repair_factor, width_in=SHAKE_WIDTH_IN, exposure_in=EXPOSURE_IN):
    # §2: ceil ONCE, after repair_factor; repair_factor on COUNT only, never area
    return math.ceil(affected_SF / 100.0 * _shakes_per_sq(width_in, exposure_in) * repair_factor)

def _felt_interlayment_ratio(exposure_in):
    """SF of interlayment felt per SF of roof.

    One 18" CSSB strip is laid per course; courses repeat every `exposure_in`, so the felt overlaps
    with itself up the slope and one square of roof consumes (18 / exposure_in) squares of felt.
    This is why interlayment felt EXCEEDS the affected area.

    FAIL LOUDLY. A missing, zero or non-positive exposure must RAISE — never silently fall back to a
    1:1 area conversion, which is exactly the ~44% under-scope this build exists to remove.
    resolve_shake_measurements validates exposure upstream, so this should be unreachable; guard anyway.
    """
    if exposure_in is None or float(exposure_in) <= 0:
        raise ValueError(
            f"exposure_in must be positive to scope felt interlayment (18\"/exposure); got {exposure_in!r}")
    return CSSB_INTERLAYMENT_STRIP_IN / float(exposure_in)

def _felt_sq(affected_SF, exposure_in):
    """FIELD_FELT in squares = affected_SF x (18 / exposure_in) / 100."""
    return affected_SF * _felt_interlayment_ratio(exposure_in) / 100.0

def _continuous_run(contact, total):
    """§6 all-or-nothing: >=95% -> full run (total); else contacted LF."""
    if total > 0 and contact >= CAP_THRESHOLD * total:
        return total, True
    return contact, False

_CHIMNEY_CODE = {"S": "RFG FLCH<", "A": "RFG FLCH", "L": "RFG FLCH>"}

# v71 DEFECT 3 — eave ICE & WATER (CSSB/IRC geometry Joseph specified).
IWS_ROLL_WIDTH_IN = 36.0          # one membrane course
EAVE_IWS_INSIDE_WALL_IN = 24.0    # coverage runs 24" inside the exterior wall (code geometry)
_EAVE_IWS_DEFAULT_SOFFIT_IN = 12.0  # unknown soffit -> the one-layer case (a 12" soffit / 36" run)


def eave_iws_coverage(eave_LF, soffit_depth_in):
    """Code/existing eave ice & water. Coverage runs from the eave edge to 24" inside the exterior
    wall, so the run width = (soffit_depth + 24). Carriers pay the computed COVERAGE AREA, not whole
    rolls: coverage = eave_LF * (soffit + 24)/12 (SF). A 36" membrane covers a 12" soffit in ONE
    layer; a deeper soffit needs TWO overlapping courses — the layer count is a consequence, stated,
    never a multiplier on the area. Soffit unknown -> the one-layer default (page 2 warns on screen;
    the report must never narrate the default). Returns (coverage_SF, layers, defaulted)."""
    defaulted = soffit_depth_in in (None, "")
    soffit = _EAVE_IWS_DEFAULT_SOFFIT_IN if defaulted else float(soffit_depth_in)
    run_in = soffit + EAVE_IWS_INSIDE_WALL_IN
    coverage = round(float(eave_LF) * run_in / 12.0, 2)
    layers = 1 if run_in <= IWS_ROLL_WIDTH_IN else 2
    return coverage, layers, defaulted


def _eave_iws_citation(basis):
    """Citation follows the basis (§ eave IWS): code cites code/MABCD; existing cites match-existing;
    both cites both (the strongest position). basis is {"code":bool,"existing":bool}."""
    code, existing = bool(basis.get("code")), bool(basis.get("existing"))
    if code and existing:
        return "IRC R905.1.2 / CSSB code minimum AND match-existing eave protection"
    if code:
        return "IRC R905.1.2 / CSSB / MABCD code-required eave protection"
    return "Match-existing eave protection"


# ---- the engine --------------------------------------------------------------
def expand_scope(iface: M1Interface, repair_factor: float = 1.0):
    """Module 1 interface -> quantified Module 2 scope lines (Spec v1.2 §2).

    repair_factor is DELIBERATELY FIXED AT 1.0 in production (Module 2 §12): the scope asserts the
    CSSB standard, not a negotiated multiplier. It is implemented and tested at 1.5, but exposing a
    dial that produces 1.5x/2x the count would turn a sourced number into a positioning number. Do
    not wire it up thinking it was an oversight.
    """
    out = []
    sf = iface.affected_SF

    # --- SF-driven (§1) ---
    if sf > 0:
        if iface.is_replacement:
            # v61 §facet-replacement: a stripped slope is conventional square-based work, so it bills
            # in SQUARES of NET facet area (no waste factor — waste varies by cut complexity and no
            # defensible published figure exists; an invented multiplier is the one place an adjuster
            # would most easily attack). It does NOT bill EA: the report's own §3 argument for EA is a
            # labor premium for localized repair, which is FALSE for a full slope. repair_factor never
            # applies to a replacement. Same SHAKE_FIELD_RR id, unit "SQ" -> a separate aggregated line.
            out.append(ScopeLine("Wood shakes, hand split (full slope replacement)", "SHAKE_FIELD_RR",
                                 round(sf / 100.0, 4), "SQ", "AUTO", "Full slope replacement"))
        else:
            out.append(ScopeLine("Wood shakes, hand split", "SHAKE_FIELD_RR",
                                 _shake_count(sf, repair_factor, iface.shake_width_in, iface.exposure_in),
                                 "EA", "AUTO", "CSSB wood-shake repair methodology"))  # v73 DEFECT 4: was "The repair" (said nothing); the same CSSB authority §3's reasoning invokes
        out.append(ScopeLine("30# felt", "FIELD_FELT",
                             round(_felt_sq(sf, iface.exposure_in), 4), "SQ", "AUTO",
                             "CSSB interwoven underlayment"))

    # --- valley-LF-driven (§2/§4) ---
    if iface.valley_LF_in_scope > 0:
        vlf = iface.valley_LF_in_scope
        out.append(ScopeLine("Valley metal (W or open)", "VALLEY_METAL",
                             round(vlf, 2), "LF", "AUTO", "CSSB valley metal; IRC flashing"))
        out.append(ScopeLine("Valley underlayment (IWS)", "IWS",
                             round(vlf * IWS_BAND_FT, 2), "SF", "AUTO",
                             "Code roll-roofing equivalent; IWS standard"))  # subtype VALLEY_IWS

    # --- edge-contact-driven (§1/§6) ---
    by_type = {}
    for e in iface.edges:
        by_type.setdefault(e.edge_type, []).append(e)

    for e in iface.edges:
        t = e.edge_type
        if t == "RIDGE" and e.contact_LF > 0:
            q, full = _continuous_run(e.contact_LF, e.edge_total_LF)
            out.append(ScopeLine("Ridge caps", "RIDGE_CAPS", round(q, 2), "LF", "AUTO",
                                 "CSSB ridge detail"))
        elif t == "HIP" and e.contact_LF > 0:
            q, full = _continuous_run(e.contact_LF, e.edge_total_LF)
            out.append(ScopeLine("Hip caps", "HIP_CAPS", round(q, 2), "LF", "AUTO",
                                 "CSSB hip detail"))
        elif t == "EAVE" and e.contact_LF > 0:
            out.append(ScopeLine("Wood shake starter", "STARTER", round(e.contact_LF, 2),
                                 "LF", "AUTO", "CSSB / mfr starter"))
        elif t == "STEPFLASH" and e.contact_LF > 0:
            out.append(ScopeLine("Step flashing", "STEP_FLASH", round(e.contact_LF, 2),
                                 "LF", "AUTO", "IRC flashing; mfr"))
        elif t == "FLASHING" and e.contact_LF > 0:
            out.append(ScopeLine("End-wall flashing", "ENDWALL_FLASH", round(e.contact_LF, 2),
                                 "LF", "AUTO", "IRC flashing; mfr"))
        elif t in ("EAVE_DRIP", "RAKE"):
            pass  # drip handled below per the 95% confirm rule

    # drip edge: EAVE or RAKE, 95% confirm-flag (§2/§6). Below 95% -> no auto line.
    for e in iface.edges:
        if e.edge_type in ("EAVE", "RAKE") and e.edge_total_LF > 0:
            if e.contact_LF >= CAP_THRESHOLD * e.edge_total_LF:
                out.append(ScopeLine("Drip edge", "DRIP_EDGE", round(e.edge_total_LF, 2),
                                     "LF", "CONFIRM", "IRC drip edge"))

    # --- pitch transitions (§3) — TWO independent paths to TRANSITION_FLASH ---
    #   Path A (passive, UNCHANGED): affected area from OTHER repairs sweeps >=95% of the edge ->
    #                                the flashing was torn out; it is CONSEQUENTIAL damage.
    #   Path B (active, NEW):        the user confirmed the transition as a repair event (exposed +
    #                                damaged) -> the flashing IS the damage; it is the TRIGGER.
    # DE-DUPLICATION IS STRUCTURAL: one `if`, one emission. A transition satisfying BOTH paths
    # cannot emit twice. Quantity is edge_total_LF (geometric truth) either way.
    for tr in iface.transitions:
        path_a = tr.edge_total_LF > 0 and tr.contact_LF >= CAP_THRESHOLD * tr.edge_total_LF
        path_b = bool(getattr(tr, "selected", False)) and tr.edge_total_LF > 0
        if path_a or path_b:
            tlf = tr.edge_total_LF
            out.append(ScopeLine("Transition flashing", "TRANSITION_FLASH", round(tlf, 2),
                                 "LF", "CONFIRM", "mfr pitch-transition detail"))
            out.append(ScopeLine("Transition underlayment", "IWS", round(tlf * IWS_BAND_FT, 2),
                                 "SF", "CONFIRM", "CSSB felt interlay; IWS company option"))  # subtype TRANSITION_IWS

    # --- appurtenance-driven (§5), grouped (§4.1) ---
    seen_groups = set()
    for a in iface.appurts:
        if not a.contacted:
            continue
        gid = a.group if a.group is not None else id(a)
        if gid in seen_groups:
            continue            # consolidate: one assembly per physical object
        seen_groups.add(gid)

        if a.affected_SF > 0:
            out.append(ScopeLine("Appurtenance IWS", "APPURT_IWS", round(a.affected_SF, 2),
                                 "SF", "AUTO", "IWS standard around appurtenance"))
        ty = a.type.upper()
        if ty == "CHIMNEY":
            out.append(ScopeLine("Chimney flashing", "CHIMNEY_FLASH", 1, "EA", "CONFIRM",
                                 "mfr / IRC flashing", _CHIMNEY_CODE.get(a.size_class, "RFG FLCH")))
        elif ty == "SKYLIGHT":
            out.append(ScopeLine("Skylight flashing", "SKYLIGHT_FLASH", 1, "EA", "CONFIRM",
                                 "mfr flashing kit"))
        elif ty == "PIPE":
            out.append(ScopeLine("Pipe-jack flashing", "PIPE_JACK_FLASH", 1, "EA", "AUTO",
                                 "mfr / IRC flashing"))
        elif ty == "TURTLE":
            out.append(ScopeLine("Turtle / box vent", "BOX_VENT", 1, "EA", "AUTO", "mfr"))
        elif ty == "TURBINE":
            out.append(ScopeLine("Turbine vent", "TURBINE_VENT", 1, "EA", "AUTO", "mfr"))
        elif ty == "POWER_VENT":
            # ONE TYPE, TWO OPERATIONS — and BOTH emit this same line. Whether the shake field is
            # disturbed is decided in the ASSEMBLY (see shared_category_registry.appurtenance_carves),
            # because that is where affected area is computed; it is NOT decided here. A cover-only
            # vent reaches this branch with affected_SF == 0, so the APPURT_IWS block above simply
            # does not fire — no if-statement suppresses it, and none may ever be added.
            # CONFIRM, not AUTO: unlike a turbine or box vent, a power vent needs a SECOND human
            # assertion (cover vs fan) that materially changes the scope, so it is never automatic.
            out.append(ScopeLine("Power attic vent", "POWER_VENT", 1, "EA", "CONFIRM",
                                 "mfr; roof-mount powered attic ventilator"))
        else:
            # USER-DEFINED ("OTHER") — previously there was NO else branch, so a user-defined
            # appurtenance silently emitted NOTHING and contributed nothing to the material list.
            # It now always emits a line:
            #   * description = the user's own label (never the raw word "OTHER"),
            #   * category    = the user's registry category IF they supplied a valid one,
            #                   otherwise UNMAPPED — which the comparison already routes to
            #                   UNMAPPED_REVIEW, so the feature is surfaced for human review
            #                   rather than dropped or wrongly matched,
            #   * CONFIRM tier: the user must confirm a feature the tool did not classify.
            label = str(a.other_label).strip() if a.other_label else ""
            category = str(a.other_category).strip() if a.other_category else ""
            out.append(ScopeLine(
                label or "User-defined appurtenance",
                category if category in REGISTRY_28 else "UNMAPPED",
                1, "EA", "CONFIRM", "user-defined"))

    # --- labor modifiers (§7) ---
    if sf > 0 and iface.facet_pitch_tier in STEEP_TIERS:
        out.append(ScopeLine("Steep charge", "STEEP_CHARGE", round(sf / 100.0, 4), "SQ",
                             "AUTO", "labor standard"))
    if sf > 0 and iface.high_slope_user_flag:
        out.append(ScopeLine("High-slope charge", "HIGH_SLOPE_CHARGE", round(sf / 100.0, 4),
                             "SQ", "CONFIRM", "labor standard"))

    return out


# =============================================================================
# SEED REGRESSION  (every expected value traces to a GREEN Module 1 assertion
# or a locked study-sheet area; run: python3 module2_scope_expansion.py)
# =============================================================================
def _has(lines, category_id, qty=None, unit=None, gate=None, tol=0.02):
    for l in lines:
        if l.category_id != category_id:
            continue
        if qty is not None and abs(l.qty - qty) > tol:
            continue
        if unit is not None and l.unit != unit:
            continue
        if gate is not None and l.gate != gate:
            continue
        return True
    return False

def _none(lines, category_id):
    return not any(l.category_id == category_id for l in lines)


def run_seed():
    ok = True
    def chk(name, cond):
        nonlocal ok
        ok &= cond
        print(f"  [{'PASS' if cond else 'FAIL'}] {name}")

    # ---- CASE 1: facet D — COMPLETE fixture (all numbers green/locked) --------
    # area 28.2 (GREEN test 3); eave 2.00, ridge 6.32/6.56, hip 2.62/4.04 (GREEN
    # tests 17); rake 0.00; valley L4 edge 7.74 ft (XML/study sheet).
    D = M1Interface(
        affected_SF=28.2,
        valley_LF_in_scope=7.74,
        edges=[Edge("EAVE", 2.00, 4.00), Edge("RAKE", 0.00, 2.72),
               Edge("HIP", 2.62, 4.04), Edge("RIDGE", 6.32, 6.56)],
    )
    dl = expand_scope(D, repair_factor=1.0)
    # shakes: ceil(28.2/100*225*1.0)=ceil(63.45)=64 ; felt 0.282 SQ
    chk("D shakes 64 EA",        _has(dl, "SHAKE_FIELD_RR", 64, "EA", "AUTO"))
    chk("D felt 0.5076 SQ (28.2*1.8/100; CSSB 18\"/10\" exposure=1.8x, was 0.282 at 1:1)", _has(dl, "FIELD_FELT", 0.5076, "SQ", "AUTO"))
    chk("D valley metal 7.74 LF",_has(dl, "VALLEY_METAL", 7.74, "LF", "AUTO"))
    chk("D valley IWS 23.22 SF", _has(dl, "IWS", 23.22, "SF", "AUTO"))
    chk("D ridge cap FULL 6.56", _has(dl, "RIDGE_CAPS", 6.56, "LF", "AUTO"))  # 96%>=95
    chk("D hip cap PARTIAL 2.62",_has(dl, "HIP_CAPS", 2.62, "LF", "AUTO"))    # 65%<95
    chk("D starter 2.00 LF",     _has(dl, "STARTER", 2.00, "LF", "AUTO"))     # eave>0
    chk("D NO drip (rake 0%)",   _none(dl, "DRIP_EDGE"))
    chk("D NO steep charge",     _none(dl, "STEEP_CHARGE"))

    # ---- CASE 2: drip + cap BOUNDARY 94% vs 96% (§12, synthetic) -------------
    b94 = expand_scope(M1Interface(edges=[Edge("RAKE", 94.0, 100.0)]))
    b96 = expand_scope(M1Interface(edges=[Edge("RAKE", 96.0, 100.0)]))
    chk("94% -> NO drip", _none(b94, "DRIP_EDGE"))
    chk("96% -> drip FIRES full 100", _has(b96, "DRIP_EDGE", 100.0, "LF", "CONFIRM"))

    # ---- CASE 3: transition fire / no-fire (GREEN test 27) -------------------
    tfire = expand_scope(M1Interface(transitions=[Transition(20.0, 20.0)]))
    chk("transition FIRES -> flash 20 LF", _has(tfire, "TRANSITION_FLASH", 20.0, "LF", "CONFIRM"))
    chk("transition underlayment 60 SF",   _has(tfire, "IWS", 60.0, "SF", "CONFIRM"))
    tno = expand_scope(M1Interface(transitions=[Transition(6.2, 20.0)]))  # 31%
    chk("transition 31% -> NO fire", _none(tno, "TRANSITION_FLASH"))

    # ---- CASE 4: appurtenance grouping (GREEN test 28) ----------------------
    split = M1Interface(appurts=[Appurt("CHIMNEY", 17.5, group="chimA", size_class="A"),
                                 Appurt("CHIMNEY", 9.0,  group="chimA", size_class="A")])
    sl = expand_scope(split)
    chk("grouped chimney counts ONCE", sum(1 for l in sl if l.category_id=="CHIMNEY_FLASH")==1)
    chk("chimney Xact code RFG FLCH", any(l.xact_code=="RFG FLCH" for l in sl))
    standalone = M1Interface(appurts=[Appurt("PIPE", 0.0, group=None)])
    chk("standalone pipe counts ONCE", sum(1 for l in expand_scope(standalone) if l.category_id=="PIPE_JACK_FLASH")==1)

    # ---- CASE 5: informational appurtenance -> NO scope (§12) ----------------
    info = expand_scope(M1Interface(appurts=[Appurt("CHIMNEY", 17.5, contacted=False, size_class="A")]))
    chk("informational appurt -> NO flashing", _none(info, "CHIMNEY_FLASH"))
    chk("informational appurt -> NO appurt IWS", _none(info, "APPURT_IWS"))

    # ---- CASE 6: repair_factor on COUNT only (§ Module 1 H1) -----------------
    d15 = expand_scope(D, repair_factor=1.5)
    # shakes ceil(63.45*1.5)=ceil(95.175)=96 ; felt UNCHANGED 0.282 (factor never on area)
    chk("D rf=1.5 shakes 96 EA",  _has(d15, "SHAKE_FIELD_RR", 96, "EA"))
    chk("D rf=1.5 felt UNCHANGED 0.5076 (factor never on area; 1.8x interlayment)", _has(d15, "FIELD_FELT", 0.5076, "SQ"))

    # =====================================================================
    # GREEN YAGER FACETS — each facet asserted ONCE from green-traceable inputs
    # every total below is the 4th value in the green edge tuples (tests 19-25)
    # =====================================================================

    # ---- CASE 7: N/R merged outside UNION + overlap guard (tests 4-6, 19) ----
    NR = M1Interface(
        affected_SF=142.1,                       # union (test 6); NOT the 151 sum
        edges=[Edge("RIDGE", 15.84, 40.50),      # 39% -> PARTIAL (test 19 "~1/3")
               Edge("RAKE", 10.92, 23.59),       # 46% -> no drip
               Edge("RAKE", 0.00, 25.10),
               Edge("EAVE", 0.00, 17.18)],
    )
    nl = expand_scope(NR)
    chk("N/R union shakes 320 EA", _has(nl, "SHAKE_FIELD_RR", 320, "EA"))   # ceil(142.1*2.25)=320
    chk("N/R union felt 2.5578 SQ (142.1*1.8/100; was 1.421 at 1:1)", _has(nl, "FIELD_FELT", 2.5578, "SQ"))
    chk("N/R ridge cap PARTIAL 15.84", _has(nl, "RIDGE_CAPS", 15.84, "LF"))
    chk("N/R NO drip (both rakes <95%)", _none(nl, "DRIP_EDGE"))
    chk("N/R NO starter (eave 0)", _none(nl, "STARTER"))
    sum_shakes = expand_scope(M1Interface(affected_SF=151.0))               # 65.5+85.5
    chk("OVERLAP GUARD: union 320 != sum 340",
        _has(nl, "SHAKE_FIELD_RR", 320) and _has(sum_shakes, "SHAKE_FIELD_RR", 340))

    # ---- CASE 8: dormer-outside single sides (tests 4, 5) ----------------
    l4 = expand_scope(M1Interface(affected_SF=65.5))
    chk("L4 outside shakes 148 / felt 0.655",
        _has(l4, "SHAKE_FIELD_RR", 148) and _has(l4, "FIELD_FELT", 0.655))
    l5 = expand_scope(M1Interface(affected_SF=85.5))
    chk("L5 outside shakes 193 / felt 0.855",
        _has(l5, "SHAKE_FIELD_RR", 193) and _has(l5, "FIELD_FELT", 0.855))

    # ---- CASE 9: L gable — ridge full, long rake 92% no-drip (test 20) ------
    Lg = M1Interface(edges=[Edge("RIDGE", 17.84, 18.50),   # 96% -> FULL -> 18.50
                            Edge("RAKE", 21.55, 23.35),    # 92% -> no drip
                            Edge("RAKE", 0.00, 2.68),
                            Edge("EAVE", 0.00, 4.20)])
    lg = expand_scope(Lg)
    chk("L ridge cap FULL 18.50", _has(lg, "RIDGE_CAPS", 18.50, "LF"))
    chk("L 92% rake -> NO drip", _none(lg, "DRIP_EDGE"))
    chk("L NO starter (eave 0)", _none(lg, "STARTER"))

    # ---- CASE 10: M gable — two ridge segments + drip on L14 (test 21) -------
    Mg = M1Interface(edges=[Edge("EAVE", 0.00, 6.49),
                            Edge("RAKE", 0.76, 12.46),     # 6% -> no drip
                            Edge("RIDGE", 1.90, 2.00),     # 95% -> FULL -> 2.00
                            Edge("RAKE", 11.69, 11.69),    # 100% -> drip full 11.69
                            Edge("RIDGE", 17.86, 18.50)])  # 96% -> FULL -> 18.50
    mg = expand_scope(Mg)
    chk("M ridge cap FULL 18.50", _has(mg, "RIDGE_CAPS", 18.50, "LF"))
    chk("M ridge cap FULL 2.00",  _has(mg, "RIDGE_CAPS", 2.00, "LF"))
    chk("M two ridge-cap lines",  sum(1 for l in mg if l.category_id == "RIDGE_CAPS") == 2)
    chk("M drip FIRES on L14 full 11.69", _has(mg, "DRIP_EDGE", 11.69, "LF", "CONFIRM"))
    chk("M only ONE drip (L16 6% no)", sum(1 for l in mg if l.category_id == "DRIP_EDGE") == 1)
    chk("M NO starter (eave 0)", _none(mg, "STARTER"))

    # ---- CASE 11: V-J side — drip on L27, ridge partial (test 22) ------------
    VJ = M1Interface(edges=[Edge("RAKE", 22.67, 22.85),    # 99% -> drip full 22.85
                            Edge("RIDGE", 12.88, 40.50),   # 32% -> PARTIAL 12.88
                            Edge("RAKE", 0.00, 22.11)])
    vj = expand_scope(VJ)
    chk("V-J drip FIRES L27 full 22.85", _has(vj, "DRIP_EDGE", 22.85, "LF", "CONFIRM"))
    chk("V-J ridge cap PARTIAL 12.88", _has(vj, "RIDGE_CAPS", 12.88, "LF"))
    chk("V-J only ONE drip (L39 untouched)", sum(1 for l in vj if l.category_id == "DRIP_EDGE") == 1)

    # ---- CASE 12: V-E side — drip on L39, stepflash L35 (test 23) ------------
    VE = M1Interface(edges=[Edge("RAKE", 21.99, 22.11),         # 99% -> drip full 22.11
                            Edge("STEPFLASH", 15.47, 15.47),    # AUTO qty=contact
                            Edge("RAKE", 0.00, 22.85),
                            Edge("STEPFLASH", 0.00, 15.48)])
    ve = expand_scope(VE)
    chk("V-E drip FIRES L39 full 22.11", _has(ve, "DRIP_EDGE", 22.11, "LF", "CONFIRM"))
    chk("V-E stepflash 15.47", _has(ve, "STEP_FLASH", 15.47, "LF", "AUTO"))
    chk("V-E ONE drip / ONE stepflash (west untouched)",
        sum(1 for l in ve if l.category_id == "DRIP_EDGE") == 1 and
        sum(1 for l in ve if l.category_id == "STEP_FLASH") == 1)

    # ---- CASE 13: V FULL union — area + both rakes + both walls + ridge ------
    VF = M1Interface(
        affected_SF=514.7,
        edges=[Edge("RAKE", 22.67, 22.85), Edge("RAKE", 21.99, 22.11),
               Edge("STEPFLASH", 15.48, 15.48), Edge("STEPFLASH", 15.47, 15.47),
               Edge("RIDGE", 40.38, 40.50)],                # 99.7% -> FULL -> 40.50
    )
    vf = expand_scope(VF)
    chk("V full shakes 1159 / felt 5.147",
        _has(vf, "SHAKE_FIELD_RR", 1159) and _has(vf, "FIELD_FELT", 5.147))
    chk("V full both rakes drip (22.85, 22.11)",
        _has(vf, "DRIP_EDGE", 22.85) and _has(vf, "DRIP_EDGE", 22.11))
    chk("V full both stepflash (15.48, 15.47)",
        _has(vf, "STEP_FLASH", 15.48) and _has(vf, "STEP_FLASH", 15.47))
    chk("V full ridge cap CLOSED/FULL 40.50", _has(vf, "RIDGE_CAPS", 40.50, "LF"))

    # ---- CASE 14: P chimney appurtenance-only (test 25) ----------------------
    # field area (footprint excl) 17.5 -> shakes ; zone (footprint incl) 20.5 -> IWS
    P = M1Interface(affected_SF=17.5,
                    appurts=[Appurt("CHIMNEY", affected_SF=20.5, size_class="A")])
    pl = expand_scope(P)
    chk("P shakes 40 / felt 0.175 (field, footprint excl)",
        _has(pl, "SHAKE_FIELD_RR", 40) and _has(pl, "FIELD_FELT", 0.175))
    chk("P appurt IWS 20.5 (zone, footprint incl)", _has(pl, "APPURT_IWS", 20.5, "SF"))
    chk("P chimney flashing 1 EA", _has(pl, "CHIMNEY_FLASH", 1, "EA", "CONFIRM"))

    # =====================================================================
    # GROW: full Yager required_scope — area-driven sides unblocked by Module 1
    # v3.4 (regression_test.py tests 29-30). ENGINE UNCHANGED; each fixture feeds
    # a now-GREEN frozen Module 1 affected_SF and asserts the deterministic
    # shake/felt pair. Grow Plan §2b: E,J,F,I,K,G,H and the M/L AREAS were the
    # blocked items; their geometry is now frozen, so the area-driven lines lock.
    #
    # SCOPE OF THIS GROW (honest): only the AREA-driven lines (shakes + felt) are
    # added for E,J,F,I,K,G,H — v3.4 freezes their AREAS, not their edge contacts,
    # so their ridge-cap/drip/starter lines stay DEFERRED until those edges go
    # green (Grow Plan §3.2). M and L edge lines are already covered in CASE 9/10;
    # here they gain their now-green area-driven shake/felt pair.

    # ---- CASE 15: inside selected-event sides — area-driven (v3.4 areas) -------
    # (side, affected_SF [Module 1 v3.4 frozen], shakes=ceil(SF*2.25), felt=SF/100)
    YAGER_INSIDE = [
        ("E", 28.3,  64, 0.283),   # test 29 (L5)
        ("M", 216.2, 487, 2.162),  # test 29 (L9) — F72-net is a Module 1 concern; area is frozen
        ("L", 214.0, 482, 2.140),  # test 29 (L10)
        ("J", 64.8,  146, 0.648),  # test 29 (L28)
        ("F", 38.0,  86,  0.380),  # test 29 (L29 only; L45 unselected)
        ("I", 69.0,  156, 0.690),  # test 29 (L37 only; L49 unselected)
        ("K", 92.9,  210, 0.929),  # test 29 (L38)
        ("G", 32.3,  73,  0.323),  # test 29 (L83)
        ("H", 32.3,  73,  0.323),  # test 29 (L84)
    ]
    for _name, _sf, _shk, _felt in YAGER_INSIDE:
        _lines = expand_scope(M1Interface(affected_SF=_sf), repair_factor=1.0)
        chk(f"{_name} area-driven: shakes {_shk} / felt {_felt} (SF {_sf})",
            _has(_lines, "SHAKE_FIELD_RR", _shk, "EA", "AUTO") and
            _has(_lines, "FIELD_FELT", _felt, "SQ", "AUTO"))

    # ---- CASE 16: outside selected sides — R/L10 + full N/R union (v3.4) -------
    # R/L10 outside (test 30) and the full N/R outside union L4+L5+L10 (test 30).
    # The union is asserted off 297.3 (overlap-once), NOT 142.1+155.3 — same
    # union-not-sum discipline guarded for the dormer-outside union in CASE 7.
    rl10 = expand_scope(M1Interface(affected_SF=155.3), repair_factor=1.0)
    chk("R/L10 outside: shakes 350 / felt 1.553 (SF 155.3)",
        _has(rl10, "SHAKE_FIELD_RR", 350, "EA", "AUTO") and _has(rl10, "FIELD_FELT", 1.553, "SQ", "AUTO"))
    rnu = expand_scope(M1Interface(affected_SF=297.3), repair_factor=1.0)
    chk("R/N full outside union: shakes 669 / felt 2.973 (union 297.3, overlap-once)",
        _has(rnu, "SHAKE_FIELD_RR", 669, "EA", "AUTO") and _has(rnu, "FIELD_FELT", 2.973, "SQ", "AUTO"))
    # union-not-sum guard: 297.3 union shakes != (155.3 + 142.1=297.4 happens ~equal here,
    # but the guard is structural) — assert the union value is the one scoped.
    chk("R/N union scoped off the 297.3 union value (not a re-summed double-count)",
        _has(rnu, "SHAKE_FIELD_RR", 669, "EA"))

    # ---- DEFERRED (flagged, not silently omitted) — Grow Plan §3 -------------
    # Still gated on a Module 1 freeze (v3.4 froze AREAS only):
    #   - edge contacts + per-edge totals for E,J,F,I,K,G,H  -> their ridge-cap/
    #     drip/starter/stepflash lines (cap full-vs-partial needs the edge totals);
    #   - valley_LF_in_scope as a NAMED frozen Module 1 output per side -> per-side
    #     valley metal + valley IWS (only D's 7.74 XML edge length is well-sourced);
    #   - appurtenance_affected_SF beyond P -> appurt IWS on other appurtenances.
    # These remain DEFERRED, not asserted, to honor the frozen-value firewall.

    print("\nRESULT:", "ALL PASS — Module 2 GROWN to full Yager area-driven scope "
          "(seed + E/M/L/J/F/I/K/G/H + R/L10 + N/R union, all traced to Module 1 v3.4; "
          "edge/valley-LF lines for the new sides DEFERRED pending their Module 1 freeze)"
          if ok else "*** FAIL — do not lock ***")
    return ok


if __name__ == "__main__":
    print("MODULE 2 SCOPE-EXPANSION — SEED REGRESSION\n" + "=" * 44)
    run_seed()
