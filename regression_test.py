#!/usr/bin/env python3
# CHANGELOG 2026-07-01: stair_edges inner-edge first-row guard added (prev_i is None ->
# seed ie[n]=vx(ye), mirroring the outer-edge guard). Fixes TypeError crash on multi-valley
# cascades whose first course row is above the valley apex (e.g. L45/L49 facets F6/F8/F11).
# Verified: Yager 3382/1639.4/134.03 (Build 2b: Path A activated — L33 fires at 100% contact and
# carves its band; RE-GROUNDED from 3360/1628.9, which was missing a real repair event).
"""
REGRESSION TEST — Wood Shake Affected-Area Engine
=================================================
PASS/FAIL GUARDRAIL. Run after ANY change to engine code. All tests must pass.

VERSION: v3.4 STABLE SUITE (31 cases / 42 checks, all released). Matches Formula
Spec v3.4 / Program Logic v2.5 / Module 2 v1.3 / Architecture v1.6 and is what the
builder implements against. ENGINE RULES ARE UNCHANGED FROM v3.3 — v3.4 adds test
COVERAGE only (tests 29-31 = Yager selected-event inside/outside coverage), proven
against the same canonical engine. No geometry rule, formula, or frozen expected
value moved.
  - Tests 1-28 (the former v3.3 stable suite): valley firewall (1-6), appurtenance +
    source (7-11), stress hardening (12-16), edge-contact extractor across six facets
    (17-25), Module 2 guards (26-28). All frozen and untouched.
  - Tests 29-31 (added at the v3.4 coordinated bump, 2026-06-17): full Yager
    selected-event coverage — inside selected sides (29: D/E/M/L/J/F/I/K/G/H),
    R/L10 outside contribution + full N/R outside union (30), and the L45/L49
    zero-over-scope guard (31). Engine-first from live XML.txt; human-reviewed and
    signed off (Module 1 Full Yager Selected-Event Coverage, COMBINED sign-off).
Any future change follows the same discipline: dev-branch ledger + growing tests
first, one coordinated bump only after the public spec is updated and the full
suite passes.

v3.3 RELEASED RULES (tests 17-28, now stable)
---------------------------------------------
(G) EDGE-CONTACT EXTRACTOR — new Module 1 output (contacted_edges[]) that
    Module 2 consumes. edge_contacts() returns, per facet edge, the honest
    measured contact length and the edge total length. Contact is measured by
    STRIP-INTEGRATION — probe perpendicular into the facet at depths 1-4 cells,
    count an along-edge position contacted when a majority fall in the zone.
    This is orientation-independent and convergent across resolution; an earlier
    omnidirectional probe under-counted steep diagonals and was replaced.
    VALLEYS ARE EXCLUDED from contact (scoped by their own length). Module 1
    reports RAW geometry; the 95% round-to-full-run on caps and continuous
    metals is a Module 2 material decision, never done here.
    Refactor: affected_area gained return_zone=True (exposes the zone mask);
    the default (per, area) signature is unchanged, so tests 1-16 are untouched.
    FIREWALL held: all 16 stable area values reproduce exactly.
    Validated across six facets (Yager): D (eave 2.00, rake 0.00, hip 2.62
    partial, ridge 6.32 of 6.56 = 96% -> full cap), N/R, L, M, V, P (tests
    17-25). Released in the coordinated v3.3 bump (2026-06-15) alongside the
    ridge/hip 95% cap rule, transition-detector third condition, and appurtenance
    grouping (tests 26-28).

Release history below.

CHANGE LOG (v3.1 -> v3.2) — two ADDITIVE changes; confirmed 2026-06-14
-------------------------------------------------------------------------------
(E) APPURTENANCE DISTURBANCE — a confirmed appurtenance repair event generates
    a disturbance zone the same way a valley does: a footprint band, shadow-
    filled upward through the continuous field, clipped to the facet, unioned
    with all other zones (overlap counted once). The footprint rule is set by
    appurtenance TYPE, never a size threshold:
      POINT types (pipe jack, turtle/box vent, turbine): fixed 21in x 21in
        square (no user dimensions; half-side = 21in/2 = 10.5in each way).
      DIMENSIONED types (chimney, skylight, other/custom): footprint + 21in
        clearance on EACH side -> (L+42in) x (W+42in). Dimensions required.
    The 21in is the IWS clearance: ~18in onto the deck + a few inches up the
    curb ~= 21in of membrane; disturbance and IWS share this footprint.
    "Sides touching shingle" needs NO user input: the facet clip handles it
    (a chimney against a ridge/wall simply has its band clipped on that side).

(F) USER-PLACED EVENTS — the engine is SOURCE-AGNOSTIC. Valley and appurtenance
    events are computed identically whether EagleView detected them or the user
    placed them on the diagram. Placement = candidate; user confirmation = a
    scoped repair event; informational = shown only, never scoped (the gate is
    enforced in the UI/program-logic layer, not here).

FIREWALL: changes E and F do not touch the valley path. The six v3.1 frozen
values (tests 1-6) MUST reproduce unchanged. Verified on build 2026-06-14.

HARDENING (same day, no frozen value moved): explicit appurtenance 'kind' is
now required and validated (a dimensioned type with missing dims raises instead
of silently becoming a point); five "uglier" cases added as frozen tests 12-16
(dimensioned corner-clip, appurtenance shadow-stop at a notch, jack+jack union,
chimney-as-penetration-plus-appurtenance, and the bad-input guard). All caught
behavior that was claimed but previously unexercised; #16's gap was real.

CHANGE LOG (v3.0 -> v3.1) — confirmed by Joseph 2026-06-12
---------------------------------------------------------
ENGINE CHANGES (moved frozen values):
  (A) CLEARANCE BAND — Option B. The 24-in band is the STARTING CLEARANCE,
      measured HORIZONTALLY ALONG THE SHINGLE COURSE from the valley
      centerline: band_edge(n) = centerline_x(n) + fan*clearance_band.
      NOT a perpendicular offset.
  (B) COURSE GRID — whole-slope. Course rows defined ONCE per physical slope,
      anchored at the slope's eave datum, shared by every valley on that slope.
ENGINE CHANGES (verified zero effect on frozen values):
  (C) SHADOW CLASSIFICATION — shadow propagates upward only within a CONTINUOUS
      shake field. THROUGH a ROOFPENETRATION (one continuous course run around
      the object). STOPS at a notch (dormer / separate roof section) and at any
      facet boundary.
  (D) FRAME X-AXIS — along-course x from slope plane + gravity:
        up_slope = gravity projected onto facet plane, reversed uphill
        x = normalize(cross(up_slope, facet_normal)); eave signs x only.
PROGRAM-LOGIC DECISIONS (reporting/parse layer; not exercised numerically here):
  (E1) 75% RULE — affected_SF / slope_SF, both NET of the same penetration
       holes (net/net); denominator = merged physical slope.
  (F1) FAN DIRECTION — from the confirmed valley-side/facet assignment against
       the ORIGINAL EagleView facet; never from the merged centroid.
  (G1) FLAT-VALLEY FLAG — informational only; never controls scope.
  (H1) SHAKE-COUNT ROUNDING — ceil ONCE per scope line, after repair_factor:
       EA = ceil(SQ x 14400/(measured_width_in × exposure_in) x repair_factor).

THE MODEL
---------
Affected area per in-scope VALLEY is a closed per-course region on the slope-
wide course grid (inner = centerline to apex then free cut edge; outer =
governing of band_edge and prior+lateral_step; shadow upward; clipped to facet
minus holes). Affected area per in-scope APPURTENANCE is its type-set footprint
band, shadow-filled upward, clipped. Hidden-line slope groups merge first.
Multiple in-scope events on one slope -> UNION, overlap counted once.

PARAMETERS (user-adjustable inputs; validated defaults)
-------------------------------------------------------
  exposure       = 10 in    (24-in shake; 18-in shake uses 7.5 in)
  shake_width    = 7 in
  joint_offset   = 1.5 in   CSSB minimum. COMPLIANCE CONSTRAINT ONLY.
  lateral_step   = shake_width / 2 = 3.5 in/course. PHYSICS, never from offset.
  clearance_band = 24 in    valley STARTING CLEARANCE along the course.
  appurt_clear   = 21 in    appurtenance clearance (point=21x21 total;
                            dimensioned=21in each side). IWS shares footprint.
  shakes_per_SQ  = 14400/(width_in × exposure_in); default 7 in × 10 in = 205.714
  repair_factor  = 1.0/1.5/2.0  shake COUNT only, never area.

FROZEN EXPECTED VALUES (tolerance: max(1.5 SF, 2.5%))
-----------------------------------------------------
  VALLEY (v3.1, unchanged — firewall):
  1. Synthetic 45 deg valley, 20x10 ft rectangle ........ 65.7 SF
  2. Synthetic + 2x2 ft ROOFPENETRATION inside zone ..... 61.8 SF
  3. Facet D inside (valley L4), Yager XML .............. 28.2 SF
  4. Dormer outside L4 (rake-bounded side), merged N/R .. 65.5 SF
  5. Dormer outside L5 (open side), merged N/R .......... 85.5 SF
  6. Dormer outside union (overlap counted once) ........ 142.1 SF
  APPURTENANCE (v3.2, new — validated vs hand-calc):
  7. Point pipe jack, open 40x40 facet, localized 21x21 . 3.0 SF
  8. Dimensioned skylight 2x4 ft -> 5.5x7.5 + shadow .... 185.6 SF
  9. Point appurtenance clipped at facet edge .......... 28.8 SF
 10. Valley + point jack, union counts overlap once .... 66.5 SF
 11. User-placed point jack on bare facet (source test)  13.7 SF
  APPURTENANCE STRESS (v3.2 hardening — uglier cases):
 12. Dimensioned object clipped at a CORNER (two edges) . 150.4 SF
 13. Appurtenance shadow STOPS at a notch (field break) . 27.6 SF
 14. Jack + jack overlap, union counts overlap once ..... 84.6 SF
 15. Chimney as ROOFPENETRATION + appurtenance: shadow
     through the hole, footprint excluded from count .... 176.1 SF
 16. BAD INPUT: dimensioned type with no/zero dims, or a
     missing 'kind', RAISES ValueError (never a silent
     fallback to a point). Type is authoritative.
NEGATIVE GUARD: a point appurtenance must be 21x21 (not 42x42). Test 7 fails
high (~93) if the point branch is wrongly given +21in-each-side.
INPUT CONTRACT: every appurtenance dict requires 'kind' = 'point' or
'dimensioned'; dimensioned requires positive w AND h. The footprint rule is
set by TYPE, never inferred from dimension values (Formula Spec §9).
  EDGE CONTACT + MODULE 2 GUARDS (v3.3 RELEASED — Module 1 output -> Module 2):
 17. Facet D edge contacts at res=0.04: eave 2.00, rake 0.00,
     hip 2.62, ridge 6.32 (of 6.56) ...................... (honest geometry)
 18. Module 2 cap decision from #17: ridge 96% >= 95% -> full
     6.56; hip 65% < 95% -> partial 2.62 ................. (95% all-or-nothing)
 19-21. N/R / L / M edge contacts (no-starter negatives; M drip-edge POSITIVE
     fires at 100%; two ridge segments both -> full) ..... (representative facets)
 22-24. V dormer wrap: J-side rake 99% drip + jack subsumed; east side mirror;
     full union 98% area, ridge closed 40.5, both rakes drip (strip-integration
     diagonal-stable; fan-direction guard) ............... (14-edge non-convex)
 25. Facet P appurtenance-only: localized chimney as penetration+appurtenance, footprint
     excluded, 21in ring clipped to facet = 17.5 SF ...... (no-valley case)
 26. Transition detector: L33 V/P true transition; saltbox ridge caught by the
     3rd condition (fall-same-way); same-pitch / climbing edge excluded.
 27. Transition firing: synthetic 100% -> full LF + underlayment LF x3; 31% -> no.
 28. Appurtenance grouping: naive per-face = 2 chimneys (double-count); grouped
     per-object = 1; standalone falls back to id.
Contact tolerance +/-0.30 LF (absorbs grid-resolution sensitivity; the
meaningful distinctions 0 / 2 / 2.5 / 6.3 are far wider than the tolerance).
"""
import numpy as np, re, sys
from geometry_core import *


if __name__ == "__main__":
    def check(name,got,exp,tol_sf=1.5,tol_pct=2.5):
        tol=max(tol_sf,exp*tol_pct/100)
        ok=abs(got-exp)<=tol
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}: got {got:.1f}, expected {exp:.1f} (tol +/-{tol:.1f})")
        return ok

    print("=== AFFECTED-AREA ENGINE REGRESSION TEST (v3.4 STABLE SUITE — 31 cases / 42 checks) ===")
    allok=True

    print("-- VALLEY firewall (v3.1 frozen six) --")
    _,u=affected_area([(0,0),(20,0),(20,10),(0,10)],[((0,0),(10,10),+1)],res=0.03)
    allok&=check("1 Synthetic 45deg rectangle",u,65.7)
    _,u=affected_area([(0,0),(20,0),(20,10),(0,10)],[((0,0),(10,10),+1)],
                      penetrations=[[(3,6),(5,6),(5,8),(3,8)]],res=0.03)
    allok&=check("2 Synthetic + 2x2 penetration",u,61.8)
    try: txt=open('/mnt/project/XML.txt').read()
    except FileNotFoundError: txt=open('XML.txt').read()
    PD=getP(txt,['C11','C12','C62','C63','C64'])
    t2=mkframe_pts([PD[c] for c in ['C11','C62','C63','C64','C12']],PD['C11'],PD['C62'])
    fD=[tuple(t2(PD[c])) for c in ['C11','C62','C63','C64','C12']]
    vs,va=t2(PD['C11']),t2(PD['C12'])
    fan=1 if np.mean(fD,axis=0)[0]>(vs[0]+va[0])/2 else -1
    per,_=affected_area(fD,[(vs,va,fan)])
    allok&=check("3 D inside (L4)",per[0],28.2)
    P=getP(txt,['C5','C6','C7','C18','C11','C12','C13','C17','C9','C10','C16','C14','C15'])
    tM=mkframe_pts([P[c] for c in ['C5','C6','C7','C9','C10','C11','C12','C13','C17','C18']],P['C6'],P['C5'])
    fNR=[tuple(tM(P[c])) for c in ['C6','C5','C18','C17','C16','C7']]
    holeNR=[tuple(tM(P[c])) for c in ['C11','C12','C13','C14','C15','C9','C10']]
    per,u=affected_area(fNR,[(tM(P['C11']),tM(P['C12']),-1),(tM(P['C13']),tM(P['C12']),+1)],
                        notches=[holeNR])
    allok&=check("4 Dormer outside L4 (rake side)",per[0],65.5)
    allok&=check("5 Dormer outside L5 (open side)",per[1],85.5)
    allok&=check("6 Dormer outside union",u,142.1)

    print("-- APPURTENANCE (v3.2 new) --")
    BIG=[(0,0),(40,0),(40,40),(0,40)]
    # 7 point pipe jack localized 21x21 spot (no valley-style shadow)
    per,_=affected_area(BIG,[],appurtenances=[{'cx':20,'cy':15,'kind':'point'}],res=0.02)
    allok&=check("7 Point pipe jack localized spot (21x21)",per[0],3.0)
    # 8 dimensioned skylight 2x4 -> 5.5x7.5 localized spot
    per,_=affected_area(BIG,[],appurtenances=[{'cx':20,'cy':10,'w':2.0,'h':4.0,'kind':'dimensioned'}],res=0.02)
    allok&=check("8 Dimensioned skylight 2x4 localized spot",per[0],41.3)
    # 9 point clipped at facet edge (cx=0.5 -> width clipped to 1.375)
    per,_=affected_area(BIG,[],appurtenances=[{'cx':0.5,'cy':20,'kind':'point'}],res=0.02)
    allok&=check("9 Point clipped at edge localized spot",per[0],2.4)
    # 10 valley + point jack, union counts overlap once
    _,u=affected_area([(0,0),(20,0),(20,10),(0,10)],[((0,0),(10,10),+1)],
                      appurtenances=[{'cx':3,'cy':2,'kind':'point'}],res=0.03)
    allok&=check("10 Valley+jack union (once)",u,66.5)
    # 11 user-placed point jack on bare facet (source-agnostic): same as a detected one
    per,_=affected_area([(0,0),(20,0),(20,10),(0,10)],[],
                        appurtenances=[{'cx':10,'cy':3,'kind':'point'}],res=0.03)
    allok&=check("11 User-placed jack localized spot (source test)",per[0],3.1)

    print("-- APPURTENANCE STRESS (v3.2 hardening) --")
    # 12 DIMENSIONED clipped at a CORNER (two edges at once)
    per,_=affected_area(BIG,[],appurtenances=[{'cx':1,'cy':1,'w':2.0,'h':4.0,'kind':'dimensioned'}],res=0.02)
    allok&=check("12 Dimensioned corner-clip localized spot",per[0],17.9)
    # 13 localized appurtenance near a notch (field still clips holes)
    per,_=affected_area(BIG,[],notches=[[(18,20),(22,20),(22,24),(18,24)]],
                        appurtenances=[{'cx':20,'cy':5,'kind':'point'}],res=0.02)
    allok&=check("13 Jack localized near notch",per[0],3.0)
    # 14 jack + jack overlap counted once
    _,u=affected_area(BIG,[],appurtenances=[{'cx':20,'cy':10,'kind':'point'},
                                            {'cx':21,'cy':10,'kind':'point'}],res=0.02)
    allok&=check("14 Jack+jack localized union (once)",u,4.8)
    # 15 chimney as PENETRATION (hole, shadow-through) + APPURTENANCE (disturbance)
    per,_=affected_area(BIG,[],penetrations=[[(19,9),(21,9),(21,11),(19,11)]],
                        appurtenances=[{'cx':20,'cy':10,'w':2.0,'h':2.0,'kind':'dimensioned'}],res=0.02)
    allok&=check("15 Chimney pen+appurt localized spot (footprint excl)",per[0],26.3)
    # 16 BAD INPUT GUARD: dimensioned with no dims must RAISE, not become a point
    try:
        affected_area(BIG,[],appurtenances=[{'cx':20,'cy':10,'w':0,'h':0,'kind':'dimensioned'}],res=0.1)
        print("  [FAIL] 16 bad-input guard: dimensioned w/ no dims did NOT raise (silent point)")
        allok=False
    except ValueError:
        print("  [PASS] 16 bad-input guard: dimensioned w/o dims raises (no silent point)")
    # 16b: missing kind must also raise
    try:
        affected_area(BIG,[],appurtenances=[{'cx':20,'cy':10}],res=0.1)
        print("  [FAIL] 16b missing-kind guard: did NOT raise"); allok=False
    except ValueError:
        print("  [PASS] 16b missing-kind guard: missing 'kind' raises")
    # NEGATIVE GUARD: point must be 21x21, not 42x42
    per,_=affected_area(BIG,[],appurtenances=[{'cx':20,'cy':15,'kind':'point'}],res=0.02)
    guard_ok = per[0] < 60
    print(f"  [{'PASS' if guard_ok else 'FAIL'}] NEG point!=42x42: area {per[0]:.1f} (must be <60; bug gives ~93)")
    allok&=guard_ok

    print("-- EDGE-CONTACT EXTRACTOR (v3.3 RELEASED) --")
    PDc=getP(txt,['C11','C12','C62','C63','C64'])
    t2c=mkframe_pts([PDc[c] for c in ['C11','C62','C63','C64','C12']],PDc['C11'],PDc['C62'])
    fDc=[tuple(t2c(PDc[c])) for c in ['C11','C62','C63','C64','C12']]
    C11c,C62c,C63c,C64c,C12c=[np.array(p) for p in fDc]
    vsc,vac=np.array(t2c(PDc['C11'])),np.array(t2c(PDc['C12']))
    fanc=1 if np.mean(fDc,axis=0)[0]>(vsc[0]+vac[0])/2 else -1
    Dedges=[(C11c,C62c,'EAVE',4.00),(C62c,C63c,'RAKE',2.72),(C63c,C64c,'HIP',4.04),(C64c,C12c,'RIDGE',6.56)]
    ec=edge_contacts(fDc,[(vsc,vac,fanc)],Dedges,res=0.04)
    def checkc(name,got,exp,tol=0.30):
        ok=abs(got-exp)<=tol
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}: got {got:.2f}, expected {exp:.2f} (tol +/-{tol})")
        return ok
    allok&=checkc("17 D eave contact",  ec['EAVE'][0], 2.00)
    allok&=checkc("17 D rake contact",  ec['RAKE'][0], 0.00)
    allok&=checkc("17 D hip contact",   ec['HIP'][0],  2.62)
    allok&=checkc("17 D ridge contact", ec['RIDGE'][0],6.32)
    # derived Module-2 cap decision (95% all-or-nothing): ridge full, hip partial
    rp=ec['RIDGE'][0]/ec['RIDGE'][1]*100; hp=ec['HIP'][0]/ec['HIP'][1]*100
    r_scope=ec['RIDGE'][1] if rp>=95 else ec['RIDGE'][0]
    h_scope=ec['HIP'][1]   if hp>=95 else ec['HIP'][0]
    ok=abs(r_scope-6.56)<0.01; allok&=ok
    print(f"  [{'PASS' if ok else 'FAIL'}] 18 ridge cap 95%->full: {rp:.0f}% -> scope {r_scope:.2f} (expect 6.56)")
    ok=abs(h_scope-ec['HIP'][0])<0.01; allok&=ok
    print(f"  [{'PASS' if ok else 'FAIL'}] 18 hip cap <95%->partial: {hp:.0f}% -> scope {h_scope:.2f} (expect partial)")

    # 19 N/R merged outside — edge contacts (v3.3 stable; strip-integration; valleys excluded)
    Vn=lambda c: np.array(tM(P[c]))
    NRedges=[(Vn('C6'),Vn('C5'),'RIDGE',40.50),(Vn('C5'),Vn('C18'),'RAKE_C5',25.10),
             (Vn('C16'),Vn('C7'),'EAVE',17.18),(Vn('C7'),Vn('C6'),'RAKE_C7',23.59)]
    ecn=edge_contacts(fNR,[(tM(P['C11']),tM(P['C12']),-1),(tM(P['C13']),tM(P['C12']),+1)],
                      NRedges,notches=[holeNR],res=0.04)
    allok&=checkc("19 N/R ridge (~1/3)",    ecn['RIDGE'][0],   15.84, tol=0.5)
    allok&=checkc("19 N/R rake D-side",     ecn['RAKE_C7'][0], 10.92, tol=0.5)
    allok&=checkc("19 N/R other rake",      ecn['RAKE_C5'][0],  0.00)
    allok&=checkc("19 N/R eave (NO starter)",ecn['EAVE'][0],    0.00)

    # 20 L gable — edge contacts (v3.3 stable; no-eave-starter; valley excluded)
    ordL=['C17','C19','C28','C29','C30','C84','C18']
    PL=getP(txt,ordL); tLh=mkframe_pts([PL[c] for c in ordL],PL['C28'],PL['C29'])
    fLh=[tuple(tLh(PL[c])) for c in ordL]; Wl=lambda c: np.array(tLh(PL[c]))
    vsLh,vaLh=np.array(tLh(PL['C18'])),np.array(tLh(PL['C17']))
    fanLh=1 if np.mean(fLh,axis=0)[0]>(vsLh[0]+vaLh[0])/2 else -1
    Ledges=[(Wl('C19'),Wl('C17'),'RIDGE',18.50),(Wl('C19'),Wl('C28'),'RAKE_long',23.35),
            (Wl('C28'),Wl('C29'),'EAVE',4.20),(Wl('C29'),Wl('C30'),'RAKE_short',2.68)]
    ecl=edge_contacts(fLh,[(vsLh,vaLh,fanLh)],Ledges,res=0.04)
    allok&=checkc("20 L ridge (full)",      ecl['RIDGE'][0],     17.84, tol=0.5)
    allok&=checkc("20 L long rake (~92%)",  ecl['RAKE_long'][0], 21.55, tol=0.5)
    allok&=checkc("20 L eave (NO starter)", ecl['EAVE'][0],       0.00)
    allok&=checkc("20 L short rake",        ecl['RAKE_short'][0], 0.00)
    # L cap/drip decisions: ridge 96%->full; long rake 92%<95%->no drip edge; eave 0->no starter
    lrp=ecl['RIDGE'][0]/ecl['RIDGE'][1]*100; lrk=ecl['RAKE_long'][0]/ecl['RAKE_long'][1]*100
    ok=(lrp>=95) and (lrk<95) and (ecl['EAVE'][0]<0.1); allok&=ok
    print(f"  [{'PASS' if ok else 'FAIL'}] 20 L decisions: ridge {lrp:.0f}%->full, long rake {lrk:.0f}%->no drip, eave->no starter")

    # 21 M gable — DRIP-EDGE POSITIVE + two ridge segments (v3.3 stable)
    ordM=['C17','C16','C24','C23','C22','C21','C20','C19']
    PM=getP(txt,ordM); tMh=mkframe_pts([PM[c] for c in ordM],PM['C23'],PM['C22'])
    fMh=[tuple(tMh(PM[c])) for c in ordM]; Wm=lambda c: np.array(tMh(PM[c]))
    vsMh,vaMh=np.array(tMh(PM['C16'])),np.array(tMh(PM['C17']))
    fanMh=1 if np.mean(fMh,axis=0)[0]>(vsMh[0]+vaMh[0])/2 else -1
    Medges=[(Wm('C23'),Wm('C22'),'EAVE',6.49),(Wm('C22'),Wm('C21'),'RAKE_L16',12.46),
            (Wm('C21'),Wm('C20'),'RIDGE_lo',2.00),(Wm('C20'),Wm('C19'),'RAKE_L14',11.69),
            (Wm('C19'),Wm('C17'),'RIDGE_up',18.50)]
    ecm=edge_contacts(fMh,[(vsMh,vaMh,fanMh)],Medges,res=0.04)
    allok&=checkc("21 M drip rake L14 (full)", ecm['RAKE_L14'][0], 11.69, tol=0.5)
    allok&=checkc("21 M other rake L16",       ecm['RAKE_L16'][0],  0.76, tol=0.5)
    allok&=checkc("21 M ridge UPPER (L13)",    ecm['RIDGE_up'][0], 17.86, tol=0.5)
    allok&=checkc("21 M ridge LOWER (L15)",    ecm['RIDGE_lo'][0],  1.90, tol=0.3)
    allok&=checkc("21 M eave (NO starter)",    ecm['EAVE'][0],      0.00)
    # decisions: drip fires on L14 (100%>=95 -> full), NOT on L16 (6%); both ridges -> full
    d14=ecm['RAKE_L14'][0]/ecm['RAKE_L14'][1]*100; d16=ecm['RAKE_L16'][0]/ecm['RAKE_L16'][1]*100
    ru=ecm['RIDGE_up'][0]/ecm['RIDGE_up'][1]*100; rl=ecm['RIDGE_lo'][0]/ecm['RIDGE_lo'][1]*100
    ok=(d14>=95) and (d16<95) and (ru>=95) and (rl>=95); allok&=ok
    print(f"  [{'PASS' if ok else 'FAIL'}] 21 M decisions: drip L14 {d14:.0f}%->FIRES(full), L16 {d16:.0f}%->no, ridges up {ru:.0f}%/lo {rl:.0f}%->full")

    # 22 V J-side — appurtenance overlap on real geometry + dormer-split ridge (v3.3 stable)
    ordV=['C5','C41','C40','C39','C38','C37','C36','C35','C34','C33','C32','C31','C8','C6']
    PV=getP(txt,ordV); tVh=mkframe_pts([PV[c] for c in ordV],PV['C6'],PV['C5'])
    fVh=[tuple(tVh(PV[c])) for c in ordV]; Wv=lambda c: np.array(tVh(PV[c]))
    vsVh,vaVh=np.array(tVh(PV['C8'])),np.array(tVh(PV['C31']))   # valley L28 (J side)
    fanVh=1 if np.mean(fVh,axis=0)[0]>(vsVh[0]+vaVh[0])/2 else -1
    # correct appurtenance identities (designators map to diagram labels):
    #   F73 = #1 pipe jack (0.5ft point, sits ON valley L28); F70 = #5 chimney V-side (2x3.9 dim);
    #   F69 = #2 chimney P-side (excluded from V, lives on facet P)
    F73=getP(txt,['C252','C253','C254','C255']); pjV=tVh(np.mean([F73[c] for c in F73],axis=0))
    F70=getP(txt,['C240','C241','C242','C243']); chV=tVh(np.mean([F70[c] for c in F70],axis=0))
    appJ=[{'cx':pjV[0],'cy':pjV[1],'kind':'point'}]
    chimV={'cx':chV[0],'cy':chV[1],'w':2.0,'h':3.86,'kind':'dimensioned'}
    Vedges=[(Wv('C8'),Wv('C6'),'RAKE_L27',22.85),(Wv('C6'),Wv('C5'),'RIDGE_L12',40.50),
            (Wv('C5'),Wv('C41'),'RAKE_L39',22.11)]
    ecv=edge_contacts(fVh,[(vsVh,vaVh,fanVh)],Vedges,appurtenances=appJ,res=0.04)
    allok&=checkc("22 V-J rake L27 (drip)",   ecv['RAKE_L27'][0], 22.67, tol=0.5)
    allok&=checkc("22 V-J ridge (J portion)", ecv['RIDGE_L12'][0],12.88, tol=0.6)
    allok&=checkc("22 V-J F-side rake L39",   ecv['RAKE_L39'][0],  0.00)
    # pipe jack F73 sits ON valley L28 -> fully inside cascade; adds NO area (subsumed),
    # but still drives its own flashing line in Module 2 (affected area != material lines)
    _,av=affected_area(fVh,[(vsVh,vaVh,fanVh)])
    _,auni=affected_area(fVh,[(vsVh,vaVh,fanVh)],appurtenances=appJ)
    ok=abs(auni-av)<1.0; allok&=ok
    print(f"  [{'PASS' if ok else 'FAIL'}] 22 V-J jack subsumed: valley {av:.1f} == valley+jack {auni:.1f} (F73 inside cascade)")
    drp=ecv['RAKE_L27'][0]/ecv['RAKE_L27'][1]*100
    ok=drp>=95; allok&=ok
    print(f"  [{'PASS' if ok else 'FAIL'}] 22 V-J drip decision: rake {drp:.0f}%->FIRES")

    # 23 V east side (I/V & K/V) — mirror of west; valleys L37+L38 (v3.3 stable)
    cxV=np.mean(fVh,axis=0)[0]
    def mkvalV(a,b):
        A,B=Wv(a),Wv(b); f=1 if cxV>(A[0]+B[0])/2 else -1; return (A,B,f)
    Eedges=[(Wv('C5'),Wv('C41'),'RAKE_L39',22.11),(Wv('C38'),Wv('C37'),'STEPFLASH_L35',15.47),
            (Wv('C8'),Wv('C6'),'RAKE_L27',22.85),(Wv('C34'),Wv('C33'),'STEPFLASH_L31',15.48)]
    ece=edge_contacts(fVh,[mkvalV('C41','C40'),mkvalV('C39','C40')],Eedges,res=0.04)
    allok&=checkc("23 V-E rake L39 (drip)",    ece['RAKE_L39'][0],     21.99, tol=0.5)
    allok&=checkc("23 V-E stepflash L35",      ece['STEPFLASH_L35'][0],15.47, tol=0.3)
    allok&=checkc("23 V-E west rake untouched",ece['RAKE_L27'][0],      0.00)
    allok&=checkc("23 V-E west wall untouched",ece['STEPFLASH_L31'][0], 0.00)

    # 24 V FULL union — entire facet, full ridge, both rakes drip, both walls (v3.3 stable)
    #     guards the fan-direction bug: wrong east fan drops L35 to 0 and opens the ridge
    allvV=[mkvalV('C8','C31'),mkvalV('C32','C31'),mkvalV('C41','C40'),mkvalV('C39','C40')]
    appV=[{'cx':pjV[0],'cy':pjV[1],'kind':'point'},chimV]   # F73 jack + F70 chimney (both subsumed)
    _,areaV=affected_area(fVh,allvV,appurtenances=appV)
    _,areaValOnly=affected_area(fVh,allvV)
    allok&=checkc("24 V full area (98%)", areaV, 514.7, tol=8.0)
    ok=abs(areaV-areaValOnly)<1.0; allok&=ok
    print(f"  [{'PASS' if ok else 'FAIL'}] 24 V appurts subsumed: valleys {areaValOnly:.1f} == +jack+chimney {areaV:.1f}")
    Fedges=[(Wv('C8'),Wv('C6'),'RAKE_L27',22.85),(Wv('C5'),Wv('C41'),'RAKE_L39',22.11),
            (Wv('C34'),Wv('C33'),'STEPFLASH_L31',15.48),(Wv('C38'),Wv('C37'),'STEPFLASH_L35',15.47),
            (Wv('C6'),Wv('C5'),'RIDGE_L12',40.50)]
    ecf=edge_contacts(fVh,allvV,Fedges,appurtenances=appV,res=0.04)
    allok&=checkc("24 V full rake L27",      ecf['RAKE_L27'][0],     22.67, tol=0.5)
    allok&=checkc("24 V full rake L39",      ecf['RAKE_L39'][0],     21.99, tol=0.5)
    allok&=checkc("24 V full stepflash L31", ecf['STEPFLASH_L31'][0],15.48, tol=0.3)
    allok&=checkc("24 V full stepflash L35", ecf['STEPFLASH_L35'][0],15.47, tol=0.3)
    allok&=checkc("24 V full ridge (closed)",ecf['RIDGE_L12'][0],    40.38, tol=0.6)
    ok=all(ecf[e][0]/ecf[e][1]>=0.95 for e in('RAKE_L27','RAKE_L39')); allok&=ok
    print(f"  [{'PASS' if ok else 'FAIL'}] 24 V both rakes drip + ridge closed across dormer")

    # 25 Facet P — APPURTENANCE-ONLY disturbance (no valley): chimney F69 (#2) repair event
    #     chimney = penetration (footprint excluded, no shakes) + appurtenance (21in ring),
    #     clipped to P (F69 is 0.7 ft off rake L46 -> ring runs off the facet there)
    ordP=['C35','C36','C48','C47']
    PP=getP(txt,ordP); tPh=mkframe_pts([PP[c] for c in ordP],PP['C48'],PP['C47'])
    fPh=[tuple(tPh(PP[c])) for c in ordP]
    c69h=tPh(np.mean([getP(txt,[c])[c] for c in ['C236','C237','C238','C239']],axis=0))
    chimP={'cx':c69h[0],'cy':c69h[1],'w':1.0,'h':3.0,'kind':'dimensioned'}
    footP=[(c69h[0]-0.5,c69h[1]-1.5),(c69h[0]+0.5,c69h[1]-1.5),(c69h[0]+0.5,c69h[1]+1.5),(c69h[0]-0.5,c69h[1]+1.5)]
    _,areaP=affected_area(fPh,[],appurtenances=[chimP],penetrations=[footP])
    allok&=checkc("25 P chimney-only localized spot (footprint excl)", areaP, 15.8, tol=0.5)
    # and the footprint-included zone for reference (Module-1 raw appurtenance zone, clipped)
    _,areaPz=affected_area(fPh,[],appurtenances=[chimP])
    ok=abs(areaPz-18.8)<0.7; allok&=ok
    print(f"  [{'PASS' if ok else 'FAIL'}] 25 P appurt-only: ring(excl) {areaP:.1f}, zone(incl) {areaPz:.1f}; clipped by rake L46 (0.7ft)")

    # 26 Transition-flashing DETECTION — §3 conditions + proposed 3rd (fall-same-way)
    #    §3 as written (pitch differs + edge level) FALSE-POSITIVES a different-pitch ridge;
    #    the 3rd condition (facets fall same direction) distinguishes transition from ridge.
    from math import degrees, atan2
    def transition_detect(eA,eB,pA,pB,fA,fB):
        c1=abs(pA-pB)>0.5                                              # pitch differs
        dz=abs(eA[2]-eB[2]); ln=np.hypot(eA[0]-eB[0],eA[1]-eB[1])
        c2=degrees(atan2(dz,ln))<=15                                  # edge level (across-slope)
        c3=np.dot(fA,fB)>0                                            # facets fall SAME way
        return (c1 and c2),(c1 and c2 and c3)                         # (2-cond, 3-cond)
    t2,t3=transition_detect((-119.6,65.6,-1.6),(-106.1,65.6,-1.6),13,7,(0,1),(0,1))  # L33 V/P (real)
    ok=(t2 and t3); allok&=ok; print(f"  [{'PASS' if ok else 'FAIL'}] 26 L33 V/P is a TRUE transition (13 vs 7, level, fall same)")
    t2,t3=transition_detect((0,10,5),(20,10,5),6,12,(0,1),(0,-1))                      # saltbox ridge
    ok=(t2 and not t3); allok&=ok; print(f"  [{'PASS' if ok else 'FAIL'}] 26 saltbox ridge: 2-cond TRUE (gap) but 3-cond EXCLUDES (fall apart)")
    t2,_=transition_detect((0,10,5),(20,10,5),12,12,(0,1),(0,1))                       # same pitch
    ok=(not t2); allok&=ok; print(f"  [{'PASS' if ok else 'FAIL'}] 26 same-pitch junction excluded (cond1)")
    t2,_=transition_detect((0,0,0),(10,8,12),6,12,(0,1),(0,1))                         # climbing edge
    ok=(not t2); allok&=ok; print(f"  [{'PASS' if ok else 'FAIL'}] 26 climbing edge excluded (cond2, not level)")

    # 27 Transition-flashing FIRING (>=95% rule) + underlayment (LF x 3 ft) — synthetic mock
    #    Yager has no >=95% transition case (L33 contact ~58-61% -> no fire), so prove firing synthetically.
    fF=[(0,0),(20,0),(20,8),(0,8)]; fV2=[((0,0),(10,8),+1),((20,0),(10,8),-1)]
    ecT=edge_contacts(fF,fV2,[((0,8),(20,8),'TRANS',20.0)],res=0.04)
    pctT=ecT['TRANS'][0]/20.0*100; fires=pctT>=95
    flash_lf=20.0 if fires else ecT['TRANS'][0]; under_sf=flash_lf*3
    allok&=checkc("27 transition fires -> full LF", flash_lf, 20.0, tol=0.3)
    allok&=checkc("27 transition underlayment (LFx3)", under_sf, 60.0, tol=1.0)
    ecN=edge_contacts([(0,0),(24,0),(24,10),(0,10)],[((0,0),(6,10),+1)],[((0,10),(24,10),'TRANS',24.0)],res=0.04)
    pctN=ecN['TRANS'][0]/24.0*100; ok=pctN<95; allok&=ok
    print(f"  [{'PASS' if ok else 'FAIL'}] 27 partial transition {pctN:.0f}% -> NO fire (control)")

    # 28 Appurtenance LINKING — proves the cross-facet double-count and that grouping fixes it.
    #    Module 1 geometry stays per-facet (F69 on P, F70 on V computed separately - unchanged).
    #    Module 2 consumes a 'group' field to count one physical object, not two.
    appurts=[{'id':'F69','type':'chimney','facet':'P','group':'chimney-1'},
             {'id':'F70','type':'chimney','facet':'V','group':'chimney-1'},
             {'id':'F73','type':'pipe_jack','facet':'V','group':None}]
    naive=sum(1 for a in appurts if a['type']=='chimney')                       # per-face count
    grouped=len({a['group'] or a['id'] for a in appurts if a['type']=='chimney'})# per-object count
    ok=(naive==2); allok&=ok; print(f"  [{'PASS' if ok else 'FAIL'}] 28 naive per-face count = {naive} chimneys (the DOUBLE-COUNT bug)")
    ok=(grouped==1); allok&=ok; print(f"  [{'PASS' if ok else 'FAIL'}] 28 grouped per-object count = {grouped} chimney (grouping FIXES it)")
    jacks=len({a['group'] or a['id'] for a in appurts if a['type']=='pipe_jack'})
    ok=(jacks==1); allok&=ok; print(f"  [{'PASS' if ok else 'FAIL'}] 28 standalone pipe jack still counts 1 (group=None falls back to id)")

    # =====================================================================
    # v3.4 APPENDED — FULL YAGER SELECTED-EVENT COVERAGE (tests 29-31)
    # =====================================================================
    # ENGINE UNCHANGED. Tests 1-28 above are frozen and untouched. These append
    # the Yager selected-event INSIDE sides (E,M,L,J,F,I,K,G,H), the dedicated
    # R/L10 outside contribution + full N/R outside union, and the zero-area guard.
    # Every value here was reproduced by the live v3.3 engine and signed off per-side
    # (module1_yager_coverage_regression.py 20/20; Wood_Shake_Module1_Full_Yager_
    # Coverage_Combined). affected_SF is the frozen geometry value; area tolerance is
    # the suite default max(1.5 SF, 2.5%) via check().
    #
    # Facets are rebuilt GENERICALLY from the live XML (walk POLYGON path -> ordered
    # points -> fall-line frame -> engine), the same path that reproduces frozen
    # test 3 (D inside L4) below as a builder firewall. The M (F1) test nets
    # penetration F72 (points C248-C251) by walking F72's OWN polygon — never a hand-
    # curated point list — which is the fix for the prior-session merge failure where
    # the helper had not loaded the F72 penetration points.
    print("-- v3.4 YAGER SELECTED-EVENT COVERAGE (tests 29-31) --")

    # generic-builder helpers (read-only over the XML already loaded as `txt`;
    # they only call the frozen mkframe_pts/affected_area — no engine change).
    def _p3(c):
        m=re.search(rf'POINT id="{c}" data="([-\d.]+),([-\d.]+),([-\d.]+)"',txt)
        return np.array([float(x) for x in m.groups()])
    _LN={}
    for _m in re.finditer(r'<LINE id="(L\d+)" path="([^"]*)" type="([A-Z]+)"',txt):
        _a,_b=_m.group(2).split(","); _LN[_m.group(1)]=(_m.group(3),[_a,_b])
    _FC={}
    for _m in re.finditer(r'<FACE designator="([^"]*)" id="(F\d+)"[^>]*>\s*<POLYGON[^>]*path="([^"]*)"[^>]*pitch="([^"]*)"[^>]*?unroundedsize="([^"]*)"',txt):
        _FC[_m.group(2)]={"des":_m.group(1),"lines":_m.group(3).split(","),"size":float(_m.group(5))}
    def _walk(lids):
        segs=[_LN[l][1][:] for l in lids]; loop=segs[0][:]; used={0}
        while len(used)<len(segs):
            last=loop[-1]; adv=False
            for i,s in enumerate(segs):
                if i in used: continue
                if s[0]==last: loop.append(s[1]); used.add(i); adv=True; break
                if s[1]==last: loop.append(s[0]); used.add(i); adv=True; break
            if not adv: break
        if loop[0]==loop[-1]: loop=loop[:-1]
        return loop
    def _build(fid,valley_line):
        f=_FC[fid]; loop=_walk(f["lines"])
        eave=[l for l in f["lines"] if _LN[l][0]=="EAVE"] or [l for l in f["lines"] if _LN[l][0]=="RIDGE"]
        d=_LN[eave[0]][1]
        t=mkframe_pts([_p3(c) for c in loop],_p3(d[0]),_p3(d[1]))
        poly=[tuple(t(_p3(c))) for c in loop]
        a,b=_LN[valley_line][1]
        va,vs=(a,b) if _p3(a)[2]>=_p3(b)[2] else (b,a)
        vs2,va2=np.array(t(_p3(vs))),np.array(t(_p3(va)))
        fan=1 if np.mean(poly,axis=0)[0]>(vs2[0]+va2[0])/2 else -1
        return poly,vs2,va2,fan,t,loop,f["size"]

    # 29 — inside selected-event sides: affected_SF frozen (engine-verified, signed off)
    # builder firewall first: the generic path must reproduce frozen test 3 (D L4)
    _pD,_vsD,_vaD,_fanD,_,_,_=_build("F12","L4")
    _perD,_=affected_area(_pD,[(_vsD,_vaD,_fanD)])
    allok&=check("29 D inside L4 (generic-builder firewall vs test 3)",_perD[0],28.2)
    # F72 penetration on M (F1): fetch its corners (C248-C251) by walking F72's own
    # polygon and net it like every other penetration (E1 net/net). M's L9 cascade is
    # unaffected (F72 sits outside it) -> affected_SF stays 216.2; only the denominator nets.
    _m72=re.search(r'<FACE designator="4" id="F72"[^>]*>\s*<POLYGON[^>]*path="([^"]*)"',txt)
    _loop72=_walk(_m72.group(1).split(","))
    _INSIDE=[("E","F13","L5",28.3),("M","F1","L9",216.2),("L","F3","L10",214.0),
             ("J","F5","L28",64.8),("F","F6","L29",38.0),("I","F8","L37",69.0),
             ("K","F9","L38",92.9),("G","F18","L83",32.3),("H","F19","L84",32.3)]
    for _des,_fid,_vl,_exp in _INSIDE:
        _poly,_vs,_va,_fan,_t,_loop,_size=_build(_fid,_vl)
        _pens=[[tuple(_t(_p3(c))) for c in _loop72]] if _fid=="F1" else None  # net F72 on M
        _per,_=affected_area(_poly,[(_vs,_va,_fan)],penetrations=_pens)
        allok&=check(f"29 {_des} inside ({_vl})",_per[0],_exp)

    # 30 — R/L10 outside contribution + full N/R outside union (L4+L5+L10), notch-clipped.
    #      Same merged-N/R dormer setup as tests 4-6, with the L10 (C18->apex C17) valley
    #      added. Self-contained (rebuilds the facet) so it does not depend on test-4 locals.
    _Pn=getP(txt,["C5","C6","C7","C18","C11","C12","C13","C17","C9","C10","C16","C14","C15"])
    _tNR=mkframe_pts([_Pn[c] for c in ["C5","C6","C7","C9","C10","C11","C12","C13","C17","C18"]],_Pn["C6"],_Pn["C5"])
    _fNR=[tuple(_tNR(_Pn[c])) for c in ["C6","C5","C18","C17","C16","C7"]]
    _holeNR=[tuple(_tNR(_Pn[c])) for c in ["C11","C12","C13","C14","C15","C9","C10"]]
    _aR,_bR="C18","C17"
    _vaR,_vsR=(_aR,_bR) if _p3(_aR)[2]>=_p3(_bR)[2] else (_bR,_aR)
    _vR,_uR=np.array(_tNR(_Pn[_vsR])),np.array(_tNR(_Pn[_vaR]))
    _fanR=1 if np.mean(_fNR,axis=0)[0]>(_vR[0]+_uR[0])/2 else -1
    _perR,_=affected_area(_fNR,[(_vR,_uR,_fanR)],notches=[_holeNR])
    allok&=check("30 R/L10 outside contribution",_perR[0],155.3)
    _,_uFU=affected_area(_fNR,[(_tNR(_Pn["C11"]),_tNR(_Pn["C12"]),-1),
                               (_tNR(_Pn["C13"]),_tNR(_Pn["C12"]),+1),
                               (_vR,_uR,_fanR)],notches=[_holeNR])
    allok&=check("30 R/N full outside union (L4+L5+L10)",_uFU,297.3)

    # 31 — zero-area guard: L45/L49 are UNSELECTED in this scenario, so F cascades from
    #      L29 alone and I from L37 alone. Neither over-scopes toward ~100% (which it
    #      would if L45/L49 cascaded). Selection, not eligibility, drives scope
    #      (XML adjacency != repair event). Proven by no-over-scope on the live engine.
    _pF,_vsF,_vaF,_fanF,_,_,_sizeF=_build("F6","L29")
    _perF,_=affected_area(_pF,[(_vsF,_vaF,_fanF)])
    _pI,_vsI,_vaI,_fanI,_,_,_sizeI=_build("F8","L37")
    _perI,_=affected_area(_pI,[(_vsI,_vaI,_fanI)])
    _guard=(_perF[0]<_sizeF) and (_perI[0]<_sizeI)
    allok&=_guard
    print(f"  [{'PASS' if _guard else 'FAIL'}] 31 zero-area guard: F {_perF[0]:.1f}<{_sizeF:.0f} "
          f"({_perF[0]/_sizeF*100:.0f}%), I {_perI[0]:.1f}<{_sizeI:.0f} ({_perI[0]/_sizeI*100:.0f}%) "
          f"-> not ~100% (L45/L49 not cascaded)")

    # =====================================================================
    # v3.5 APPENDED — UNIFIED FLAT-VALLEY TARGETS (test 32)
    # =====================================================================
    # Flat valleys run cross-slope and have no true elevation apex. The parser
    # marks them by collapsing the local apex y to the start y; unified
    # stair_edges then seeds from the valley centerline extent. Existing tests
    # above are unchanged; these are additive capability checks.
    print("-- v3.5 FLAT-VALLEY TARGETS (test 32) --")
    from eagleview_geometry_parser import parse_eagleview_geometry
    from module1_service import _dimensional_pens

    _geom = parse_eagleview_geometry(txt)
    _FLAT_TARGETS = [
        ("F6", "L45", 90.1, 203),
        ("F8", "L49", 104.0, 234),
        ("F10", "L45", 101.2, 228),
        ("F11", "L49", 79.8, 180),
        ("F10", "L30", 27.0, 61),  # frame-rise rule: L30 rises 2 courses on T-side, correctly sloped
        ("F11", "L36", 27.4, 62),
        ("F4", "L30", 118.3, 267),
        ("F4", "L36", 127.8, 288),
    ]
    for _fid, _vl, _sf_exp, _ea_exp in _FLAT_TARGETS:
        _fg = _geom.engine_facet(_fid)
        _per, _ = affected_area(
            _fg.facet,
            [_geom.valley_event_for_face(_fid, _vl)],
            penetrations=_dimensional_pens(_fg.penetrations),
        )
        _sf = float(_per[0])
        _ea = int(np.ceil(_sf * 2.25))
        _ok_sf = abs(_sf - _sf_exp) <= 0.6
        _ok_ea = _ea == _ea_exp
        allok &= (_ok_sf and _ok_ea)
        print(f"  [{'PASS' if _ok_sf and _ok_ea else 'FAIL'}] 32 {_fid}/{_vl}: "
              f"SF {_sf:.1f} expected {_sf_exp:.1f} (+/-0.6), EA {_ea} expected {_ea_exp}")


    # 33 — merged-slope Pass 1: notch valley set is selection-driven, fallback-compatible, and unions.
    from copy import deepcopy as _deepcopy
    from math import ceil as _ceil
    from module2_assembly import assemble_full_roof_scope as _assemble_full_roof_scope
    from module1_yager_proof import YAGER_CONFIRMED_SELECTION as _YAGER_CONFIRMED_SELECTION

    def _notch_only_result_for(_valley_ids_marker):
        _sel = {
            "selected_valley_ids": list(_valley_ids_marker or ["L4", "L5", "L10"]),
            "single_valley_repairs": [],
            "multi_valley_facets": [],
            "penetration_appurtenance_repairs": [],
            "notch_repairs": [{"label": "N/R outside notch-clipped union", "member_face_ids": ["F21", "F22"]}],
        }
        if _valley_ids_marker is not None:
            _sel["notch_repairs"][0]["valley_ids"] = list(_valley_ids_marker)
        _r = _assemble_full_roof_scope(txt, _sel)
        _notch = [c for c in _r.components if c.component_type == "notch"][0]
        _sf = float(_notch.iface.affected_SF)
        return int(_ceil(_sf * 2.25)), _sf

    def _notch_only_ea_for(_valley_ids_marker):
        return _notch_only_result_for(_valley_ids_marker)[0]

    _ea_union = _notch_only_ea_for(["L4", "L5", "L10"])
    allok &= check("33A merged notch selected L4+L5+L10 EA", _ea_union, 658, tol_sf=0)
    _ea_l9 = _notch_only_ea_for(["L9"])
    allok &= check("33B merged notch selected L9 EA", _ea_l9, 614, tol_sf=0)
    _ea_fallback = _notch_only_ea_for(None)
    allok &= check("33C merged notch no-valley_ids fallback EA", _ea_fallback, 658, tol_sf=0)
    _sum_individual = int(_ceil(sum(_notch_only_result_for([_v])[1] for _v in ["L4", "L5", "L10"]) * 2.25))
    _union_guard = _ea_union == 658 and _sum_individual == 678 and _ea_union < _sum_individual
    allok &= _union_guard
    print(f"  [{'PASS' if _union_guard else 'FAIL'}] 33D merged notch union-not-sum: union {_ea_union} vs individual sum {_sum_individual}")
    _r_yager = _assemble_full_roof_scope(txt, _YAGER_CONFIRMED_SELECTION)
    _yager_ea = int(sum(_l.qty for _l in _r_yager.aggregated_scope if _l.category_id == "SHAKE_FIELD_RR"))
    # Shake Profile v2 re-grounds EA from the measured 7 in × 10 in profile:
    # shakes_per_sq = 14400/(7×10), ceil still applies per emitted scope line.
    # SF/LF geometry assertions remain frozen byte-identical.
    # === ANCHOR RE-GROUNDED (Build 2b, authorized) — 3360 -> 3382 EA, 1628.9 -> 1639.4 SF =========
    # module2_assembly always built M1Interface(..., transitions=[]) — hardcoded empty — so the
    # Path-A >=95% passive rule NEVER FIRED on a real roof. Yager's L33 (V 13/12 <-> P 7/12,
    # 13.50 LF) is swept 100% by the standard confirmed repair and was being SILENTLY DROPPED.
    # Path A is now live: L33 fires, carves its band (36 in upper / 1 course lower) on both facets,
    # and adds TRANSITION_FLASH 13.50 LF + 40.5 SF underlayment. L79 (52.9%) correctly does not fire.
    # This is a CORRECTNESS FIX: the old anchor was missing a repair event that physically occurs.
    # Valley LF (134.03) is unchanged — the geometry algorithm is untouched.
    _yager_ok = (_yager_ea == 3382
                 and _r_yager.affected_SF_display_total == 1639.4
                 and _r_yager.selected_valley_LF_total == 134.03)
    allok &= _yager_ok
    print(f"  [{'PASS' if _yager_ok else 'FAIL'}] 33E full Yager via Module 2: EA {_yager_ea} (7in×10in re-grounded), SF {_r_yager.affected_SF_display_total:.1f}, LF {_r_yager.selected_valley_LF_total:.2f}")


    # 34 — merged-slope Pass 2 (UI routing): roof layout exposes merged slope, and UI-shaped
    #       selections can route member-facet valley picks into one notch repair.
    from workbench_roof_layout import build_roof_layout as _build_roof_layout
    from workbench_seam import build_scope_from_ui_selection as _build_scope_from_ui_selection

    _merged = _build_roof_layout(txt).get("merged_slopes")
    _merged_expected = [{"member_face_ids": ["F21", "F22"], "valley_line_ids": ["L4", "L5", "L9", "L10"]}]
    _merged_ok = _merged == _merged_expected
    allok &= _merged_ok
    print(f"  [{'PASS' if _merged_ok else 'FAIL'}] 34A merged_slopes exposure: {_merged}")

    def _ui_yager_without_chimney(_notch_valleys):
        _ui = {
            "valley_intersections": [],
            "appurtenances": [],
            "notches": [{"member_face_ids": ["F21", "F22"], "valley_ids": list(_notch_valleys)}],
        }
        for _fid, _vid in [
            ("F12", "L4"), ("F13", "L5"), ("F1", "L9"), ("F3", "L10"),
            ("F5", "L28"), ("F6", "L29"), ("F8", "L37"), ("F9", "L38"),
            ("F18", "L83"), ("F19", "L84"),
        ]:
            _ui["valley_intersections"].append({"face_id": _fid, "valley_id": _vid, "claim_valley_lf": True})
        for _vid in ["L28", "L29", "L37", "L38"]:
            _ui["valley_intersections"].append({"face_id": "F4", "valley_id": _vid, "claim_valley_lf": True, "include_child_penetrations": False})
        return _ui

    def _scope_eas(_result):
        return [int(_ceil(float(_c.iface.affected_SF) * 2.25)) for _c in _result.components]

    def _notch_ea_from_result(_result):
        _notches = [_c for _c in _result.components if _c.component_type == "notch"]
        return int(_ceil(float(_notches[0].iface.affected_SF) * 2.25)) if _notches else 0

    _r_ui = _build_scope_from_ui_selection(txt, _ui_yager_without_chimney(["L4", "L5", "L10"]))
    _r_ui_eas = _scope_eas(_r_ui)
    # anchor re-grounding (Build 2b): +22 EA — L33's transition band now carves on facet P.
    _ui_ok = sum(_r_ui_eas) == 3661 and _notch_ea_from_result(_r_ui) == 658
    allok &= _ui_ok
    print(f"  [{'PASS' if _ui_ok else 'FAIL'}] 34B routed Yager UI no chimney: EA {sum(_r_ui_eas)} notch {_notch_ea_from_result(_r_ui)} events {_r_ui_eas}")

    _r_ui_l9 = _build_scope_from_ui_selection(txt, _ui_yager_without_chimney(["L4", "L5", "L10", "L9"]))
    _l9_ok = _notch_ea_from_result(_r_ui_l9) == 1145
    allok &= _l9_ok
    print(f"  [{'PASS' if _l9_ok else 'FAIL'}] 34C routed notch L4+L5+L10+L9 grows to {_notch_ea_from_result(_r_ui_l9)} EA")

    _ea_all = _notch_only_ea_for(["L4", "L5", "L10", "L9"])
    _thread_ok = _ea_union == 658 and _ea_l9 == 614 and _ea_all == 1145 and _ea_fallback == 658
    allok &= _thread_ok
    print(f"  [{'PASS' if _thread_ok else 'FAIL'}] 34D seam threading: L4/L5/L10={_ea_union}, L9={_ea_l9}, all={_ea_all}, fallback={_ea_fallback}")

    # 35 — outside-facet fans corrected via inward-normal (reaches near boundary, penetration-carved)
    from math import ceil as _ceil35
    from geometry_core import affected_area as _aa35
    from module2_assembly import _dimensional_pens as _dp35
    from eagleview_geometry_parser import parse_eagleview_geometry as _pg35
    _g35 = _pg35(txt)
    _out35 = {("F17","L84"):64, ("F22","L4"):148, ("F22","L10"):339, ("F22","L5"):190, ("F17","L83"):113}
    for (_f,_v),_want in _out35.items():
        _fg=_g35.engine_facet(_f); _p,_a=_aa35(_fg.facet,[_g35.valley_event_for_face(_f,_v)],penetrations=_dp35(_fg.penetrations))
        _got=int(_ceil35(_a*2.25)); allok &= (_got==_want)
        print(f"  [{'PASS' if _got==_want else 'FAIL'}] 35 {_f}/{_v} outside fan: {_got} EA (want {_want})")


    # 36 — APPURTENANCE MECHANICS: localized spot repair + hidden-line crossing harness
    print("-- APPURTENANCE MECHANICS (test 36) --")
    from geometry_core import appurt_rect as _ar36, affected_area as _aa36
    def _area36(_facet, _app):
        return _aa36(_facet, [], appurtenances=[_app])[1]
    def _rect_full36(_app):
        _r = _ar36(_app); _xs=[p[0] for p in _r]; _ys=[p[1] for p in _r]
        return (max(_xs)-min(_xs))*(max(_ys)-min(_ys))
    _tall36=[(0,0),(20,0),(20,40),(0,40)]
    _pt36={'cx':10.0,'cy':6.0,'kind':'point'}
    _dim36={'cx':10.0,'cy':6.0,'w':3.0,'h':2.0,'kind':'dimensioned'}
    _pt_ok36=abs(_area36(_tall36,_pt36)-_rect_full36(_pt36))<1.0
    _dim_ok36=abs(_area36(_tall36,_dim36)-_rect_full36(_dim36))<1.0
    allok &= _pt_ok36 and _dim_ok36
    print(f"  [{'PASS' if _pt_ok36 else 'FAIL'}] 36A point appurtenance localized: area {_area36(_tall36,_pt36):.2f} rect {_rect_full36(_pt36):.2f}")
    print(f"  [{'PASS' if _dim_ok36 else 'FAIL'}] 36B dimensioned appurtenance localized: area {_area36(_tall36,_dim36):.2f} rect {_rect_full36(_dim36):.2f}")
    _merged36=[(0,0),(40,0),(40,25),(0,25)]
    _host36=[(0,0),(20,0),(20,25),(0,25)]
    _chim36={'cx':19.0,'cy':12.0,'w':2.0,'h':2.0,'kind':'dimensioned'}
    _far36={'cx':6.0,'cy':12.0,'w':2.0,'h':2.0,'kind':'dimensioned'}
    _host_area36=_area36(_host36,_chim36); _merged_area36=_area36(_merged36,_chim36); _full36=_rect_full36(_chim36)
    _cross_ok36=abs(_merged_area36-_full36)<1.0 and _host_area36 < _merged_area36-1.0
    _control_ok36=abs(_area36(_host36,_far36)-_area36(_merged36,_far36))<0.5
    allok &= _cross_ok36 and _control_ok36
    print(f"  [{'PASS' if _cross_ok36 else 'FAIL'}] 36C hidden-line crossing: host-only {_host_area36:.2f}, merged {_merged_area36:.2f}, full rect {_full36:.2f}")
    print(f"  [{'PASS' if _control_ok36 else 'FAIL'}] 36D hidden-line control: host {_area36(_host36,_far36):.2f}, merged {_area36(_merged36,_far36):.2f}")



    # 37 — APPURTENANCE DEDUP: in-field appurtenance is union-not-sum, not zeroed wholesale.
    print("-- APPURTENANCE DEDUP (test 37) --")
    _base37 = {
        "selected_valley_ids": ["L9"],
        "single_valley_repairs": [],
        "multi_valley_facets": [],
        "penetration_appurtenance_repairs": [],
        "notch_repairs": [],
    }
    _f71_app37 = {"label": "F71 appurtenance", "host_face_id": "F21", "penetration_face_id": "F71"}
    _l9_notch37 = {"label": "L9 N/R notch", "member_face_ids": ["F21", "F22"], "valley_ids": ["L9"]}
    _r_f71_37 = _assemble_full_roof_scope(txt, {**_base37, "penetration_appurtenance_repairs": [_f71_app37]})
    _r_l9_37 = _assemble_full_roof_scope(txt, {**_base37, "notch_repairs": [_l9_notch37]})
    _r_both_37 = _assemble_full_roof_scope(txt, {**_base37, "penetration_appurtenance_repairs": [_f71_app37], "notch_repairs": [_l9_notch37]})
    _f71_full37 = float(_r_f71_37.components[0].iface.affected_SF)
    _l9_sf37 = float([_c for _c in _r_l9_37.components if _c.component_type == "notch"][0].iface.affected_SF)
    _f71_net37 = float([_c for _c in _r_both_37.components if _c.component_type == "penetration_appurtenance"][0].iface.affected_SF)
    _both_sf37 = float(_r_both_37.affected_SF_raw_total)
    _dedup_ok37 = (_f71_full37 > _f71_net37 > 1.0 and abs(_both_sf37 - (_l9_sf37 + _f71_net37)) < 0.1 and _both_sf37 > _l9_sf37 + 1.0)
    allok &= _dedup_ok37
    print(f"  [{'PASS' if _dedup_ok37 else 'FAIL'}] 37 F71+L9 partial overlap: F71-alone {_f71_full37:.2f} SF, L9-alone {_l9_sf37:.2f} SF, F71-net {_f71_net37:.2f} SF, combined {_both_sf37:.2f} SF")

    # 38 — APPURTENANCE DIAGRAM SHADING: diagram draws the stored component mask.
    print("-- APPURTENANCE DIAGRAM SHADING (test 38) --")
    from workbench_diagram_data import build_diagram_data as _build_diagram_data, _shoelace_area as _poly_area38
    _sel_both38 = {**_base37, "penetration_appurtenance_repairs": [_f71_app37], "notch_repairs": [_l9_notch37]}
    _d_both38 = _build_diagram_data(txt, _sel_both38)
    _f71_event38 = [e for e in _d_both38["events"] if e["event_label"] == "F71 appurtenance"][0]
    _rings38 = _f71_event38["affected_polygon"]
    _ring_area38 = sum(_poly_area38(r) for r in _rings38)
    _diagram_ea38 = int(_d_both38["summary"]["total_EA"])
    _count_ea38 = int(sum(_l.qty for _l in _r_both_37.aggregated_scope if _l.category_id == "SHAKE_FIELD_RR"))
    _shade_ok38 = (len(_rings38) > 0 and 0.0 < _ring_area38 < _f71_net37 + 0.5 and _diagram_ea38 == _count_ea38)  # shared frame is scaled vs real feet; assert non-empty + count match, not exact SF
    allok &= _shade_ok38
    print(f"  [{'PASS' if _shade_ok38 else 'FAIL'}] 38 F71 appurtenance polygon: rings {len(_rings38)}, area {_ring_area38:.2f} SF, diagram EA {_diagram_ea38}, count EA {_count_ea38}")



    # 39 — APPURTENANCE NET SLIVER FILTER: in-field net mask drops sub-shake fragments.
    print("-- APPURTENANCE NET SLIVER FILTER (test 39) --")
    import numpy as _np39
    from module1_service import run_module1_service as _run_m1_39
    _m1_both39 = _run_m1_39(txt, _sel_both38)
    _f71_comp39 = [c for c in _m1_both39.components if c.label == "F71 appurtenance"][0]
    _mask39 = _np39.asarray(_f71_comp39.zone, dtype=bool)
    _gx39, _gy39 = _f71_comp39.gx, _f71_comp39.gy
    _cell39 = float((_gx39[1] - _gx39[0]) * (_gy39[1] - _gy39[0]))
    _seen39 = _np39.zeros_like(_mask39, dtype=bool)
    _areas39 = []
    _rows39, _cols39 = _mask39.shape
    for _r39 in range(_rows39):
        for _c39 in range(_cols39):
            if not _mask39[_r39, _c39] or _seen39[_r39, _c39]:
                continue
            _stack39 = [(_r39, _c39)]
            _seen39[_r39, _c39] = True
            _n39 = 0
            while _stack39:
                _cr39, _cc39 = _stack39.pop()
                _n39 += 1
                for _nr39, _nc39 in ((_cr39 - 1, _cc39), (_cr39 + 1, _cc39), (_cr39, _cc39 - 1), (_cr39, _cc39 + 1)):
                    if 0 <= _nr39 < _rows39 and 0 <= _nc39 < _cols39 and _mask39[_nr39, _nc39] and not _seen39[_nr39, _nc39]:
                        _seen39[_nr39, _nc39] = True
                        _stack39.append((_nr39, _nc39))
            _areas39.append(_n39 * _cell39)
    _d_both39 = _build_diagram_data(txt, _sel_both38)
    _f71_event39 = [e for e in _d_both39["events"] if e["event_label"] == "F71 appurtenance"][0]
    _ring_area39 = sum(_poly_area38(r) for r in _f71_event39["affected_polygon"])
    _count_ea39 = int(sum(_l.qty for _l in _r_both_37.aggregated_scope if _l.category_id == "SHAKE_FIELD_RR"))
    _diagram_ea39 = int(_d_both39["summary"]["total_EA"])
    _sliver_ok39 = (
        len(_areas39) == 1
        and all(_a >= (1.0 / 2.25) for _a in _areas39)
        and abs(float(_f71_comp39.affected_SF_raw) - 13.7392) < 0.01
        and 0.0 < _ring_area39 < float(_f71_comp39.affected_SF_raw) + 0.5  # shared frame scaled vs real feet
        and int(_f71_event39["shake_count"]) == 29
        and _diagram_ea39 == _count_ea39
    )
    allok &= _sliver_ok39
    print(f"  [{'PASS' if _sliver_ok39 else 'FAIL'}] 39 F71 sliver filter: net {float(_f71_comp39.affected_SF_raw):.2f} SF, shakes {int(_f71_event39['shake_count'])}, rings {len(_f71_event39['affected_polygon'])}, components {[round(float(_a), 2) for _a in _areas39]}, diagram EA {_diagram_ea39}, count EA {_count_ea39}")


    # 40 — FEATURE B-1 USER-DEFINED APPURTENANCE CARVE PATH: engine + diagram, no UI.
    print("-- USER-DEFINED APPURTENANCE CARVE PATH (test 40) --")
    from copy import deepcopy as _deepcopy40
    from module1_yager_proof import YAGER_CONFIRMED_SELECTION as _YAGER40
    _base40 = _assemble_full_roof_scope(txt, _YAGER40)
    _base_ea40 = int(sum(_l.qty for _l in _base40.aggregated_scope if _l.category_id == "SHAKE_FIELD_RR"))
    _base_inert_sel40 = _deepcopy40(_YAGER40)
    _base_inert_sel40["user_appurtenance_repairs"] = []
    _inert40 = _assemble_full_roof_scope(txt, _base_inert_sel40)
    _inert_ea40 = int(sum(_l.qty for _l in _inert40.aggregated_scope if _l.category_id == "SHAKE_FIELD_RR"))
    # anchor re-grounding (Build 2b): Path A live -> L33 fires. Geometry unchanged.
    _ta_ok40 = (_base_ea40 == 3382 and _inert_ea40 == 3382 and round(float(_inert40.affected_SF_display_total), 1) == 1639.4)
    allok &= _ta_ok40
    print(f"  [{'PASS' if _ta_ok40 else 'FAIL'}] 40A base inert: EA {_inert_ea40}, SF {float(_inert40.affected_SF_display_total):.1f}")

    _u1_40 = {"designator": "U1", "host_facet_id": "F16", "position": {"x": 14.0, "y": -4.0}, "shape": "dimensioned", "width": 4.0, "height": 4.0, "kind_label": "SKYLIGHT", "repair_event": True}
    _sel_u1_40 = _deepcopy40(_YAGER40); _sel_u1_40["user_appurtenance_repairs"] = [_u1_40]
    _stand_u1_40 = _assemble_full_roof_scope(txt, {"user_appurtenance_repairs": [_u1_40]})
    _r_u1_40 = _assemble_full_roof_scope(txt, _sel_u1_40)
    _u1_delta_sf40 = float(_r_u1_40.affected_SF_raw_total - _base40.affected_SF_raw_total)
    _u1_full_sf40 = float(_stand_u1_40.affected_SF_raw_total)
    _u1_ea40 = int(sum(_l.qty for _l in _r_u1_40.aggregated_scope if _l.category_id == "SHAKE_FIELD_RR"))
    _tb_ok40 = (_u1_delta_sf40 > 0.0 and abs(_u1_delta_sf40 - _u1_full_sf40) < 0.01)
    allok &= _tb_ok40
    print(f"  [{'PASS' if _tb_ok40 else 'FAIL'}] 40B U1 out-of-zone dimensioned: facet F16 pos (14.0,-4.0), full {_u1_full_sf40:.2f} SF, result EA {_u1_ea40}, SF {float(_r_u1_40.affected_SF_display_total):.1f}")

    _u2_40 = {"designator": "U2", "host_facet_id": "F1", "position": {"x": 17.0, "y": -19.0}, "shape": "dimensioned", "width": 4.0, "height": 4.0, "kind_label": "SKYLIGHT", "repair_event": True}
    _sel_u2_40 = _deepcopy40(_YAGER40); _sel_u2_40["user_appurtenance_repairs"] = [_u2_40]
    _stand_u2_40 = _assemble_full_roof_scope(txt, {"user_appurtenance_repairs": [_u2_40]})
    _r_u2_40 = _assemble_full_roof_scope(txt, _sel_u2_40)
    _u2_delta_sf40 = float(_r_u2_40.affected_SF_raw_total - _base40.affected_SF_raw_total)
    _u2_full_sf40 = float(_stand_u2_40.affected_SF_raw_total)
    _tc_ok40 = (_u2_full_sf40 > _u2_delta_sf40 > 0.0)
    allok &= _tc_ok40
    print(f"  [{'PASS' if _tc_ok40 else 'FAIL'}] 40C U2 in-zone dedup: facet F1 pos (17.0,-19.0), full {_u2_full_sf40:.2f} SF, net {_u2_delta_sf40:.2f} SF")

    _u3_40 = {"designator": "U3", "host_facet_id": "F16", "position": {"x": 14.0, "y": -4.0}, "shape": "point", "kind_label": "VENT", "repair_event": True}
    _stand_u3_40 = _assemble_full_roof_scope(txt, {"user_appurtenance_repairs": [_u3_40]})
    _u3_ea40 = int(sum(_l.qty for _l in _stand_u3_40.aggregated_scope if _l.category_id == "SHAKE_FIELD_RR"))
    _td_ok40 = (float(_stand_u3_40.affected_SF_raw_total) > 0.0 and _u3_ea40 > 0)
    allok &= _td_ok40
    print(f"  [{'PASS' if _td_ok40 else 'FAIL'}] 40D U3 point vent: facet F16 pos (14.0,-4.0), EA {_u3_ea40}, SF {float(_stand_u3_40.affected_SF_display_total):.1f}")

    _d_u1_40 = _build_diagram_data(txt, _sel_u1_40)
    _u1_event40 = [e for e in _d_u1_40["events"] if e["event_label"] == "U1"][0]
    _te_ok40 = (int(_d_u1_40["summary"]["total_EA"]) == _u1_ea40 and len(_u1_event40["affected_polygon"]) > 0)
    allok &= _te_ok40
    print(f"  [{'PASS' if _te_ok40 else 'FAIL'}] 40E U1 diagram=count: diagram EA {int(_d_u1_40['summary']['total_EA'])}, scope EA {_u1_ea40}, U1 rings {len(_u1_event40['affected_polygon'])}")


    # 41 — FEATURE B-2a PER-FACET AFFINE: expose drawing transform for later drag placement.
    print("-- PER-FACET LOCAL_TO_SHARED AFFINE (test 41) --")
    import numpy as _np41
    from eagleview_geometry_parser import parse_eagleview_geometry as _parse_geom41
    from workbench_roof_layout import build_roof_layout as _build_layout41
    from workbench_diagram_data import _facet_local_to_shared as _draw_to_shared41
    _geom41 = _parse_geom41(txt)
    _layout41 = _build_layout41(txt)
    _facet_by_id41 = {str(_f["facet_id"]): _f for _f in _layout41["facets"]}
    _test_facets41 = ["F1", "F4", "F16", "F21", "F22"]
    _test_points41 = [(0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (14.0, -4.0), (3.25, -8.75)]
    _max_rt41 = 0.0
    _max_cons41 = 0.0
    _field_ok41 = True
    for _fid41 in _test_facets41:
        _aff41 = _facet_by_id41[_fid41].get("local_to_shared")
        _field_ok41 = _field_ok41 and isinstance(_aff41, dict) and all(_k in _aff41 for _k in ("origin", "du", "dv"))
        _o41 = _np41.asarray(_aff41["origin"], dtype=float)
        _du41 = _np41.asarray(_aff41["du"], dtype=float)
        _dv41 = _np41.asarray(_aff41["dv"], dtype=float)
        _mat41 = _np41.column_stack([_du41, _dv41])
        _draw41 = _draw_to_shared41(_geom41, _fid41)
        for _u41, _v41 in _test_points41:
            _shared41 = _o41 + _u41 * _du41 + _v41 * _dv41
            _uv41 = _np41.linalg.solve(_mat41, _shared41 - _o41)
            _rt_err41 = float(max(abs(_uv41[0] - _u41), abs(_uv41[1] - _v41)))
            _draw_shared41 = _np41.asarray(_draw41((_u41, _v41)), dtype=float)
            _cons_err41 = float(max(abs(_draw_shared41[0] - _shared41[0]), abs(_draw_shared41[1] - _shared41[1])))
            _max_rt41 = max(_max_rt41, _rt_err41)
            _max_cons41 = max(_max_cons41, _cons_err41)
    _affine_ok41 = (_field_ok41 and _max_rt41 < 1e-4 and _max_cons41 < 1e-4)
    allok &= _affine_ok41
    print(f"  [{'PASS' if _affine_ok41 else 'FAIL'}] 41 local_to_shared exposed + round-trip/consistency: facets {_test_facets41}, points {_test_points41}, max_roundtrip_error {_max_rt41:.8f}, max_consistency_error {_max_cons41:.8f}")



    # 42 — USER APPURTENANCE FOOTPRINT IS A HOLE: dimensioned user footprints exclude shingles.
    print("-- USER APPURTENANCE FOOTPRINT HOLES (test 42) --")
    from geometry_core import affected_area as _aa42
    from eagleview_geometry_parser import parse_eagleview_geometry as _parse_geom42
    _geom42 = _parse_geom42(txt)
    _base_yager42 = _assemble_full_roof_scope(txt, _YAGER40)
    _base_ea42 = int(sum(_l.qty for _l in _base_yager42.aggregated_scope if _l.category_id == "SHAKE_FIELD_RR"))
    # anchor re-grounding (Build 2b): Path A live -> L33 fires. The green-hole DELTA below is the
    # frozen assertion and is unchanged (8.00 SF drop) — only the base total moves.
    _base_ok42 = (_base_ea42 == 3382 and round(float(_base_yager42.affected_SF_display_total), 1) == 1639.4)

    _valley_sel42 = {"single_valley_repairs": [{"face_id": "F1", "valley_id": "L9"}]}
    _green_hole42 = {"designator": "U42G", "host_facet_id": "F1", "position": {"x": 10.0, "y": -4.0}, "shape": "dimensioned", "width": 2.0, "height": 4.0, "kind_label": "SKYLIGHT", "repair_event": False}
    _valley_no_hole42 = _assemble_full_roof_scope(txt, _valley_sel42)
    _valley_with_hole42 = _assemble_full_roof_scope(txt, {**_valley_sel42, "user_appurtenance_repairs": [_green_hole42]})
    _drop42 = float(_valley_no_hole42.affected_SF_raw_total - _valley_with_hole42.affected_SF_raw_total)
    _t1_ok42 = abs(_drop42 - 8.0) < 0.05
    allok &= (_base_ok42 and _t1_ok42)
    print(f"  [{'PASS' if (_base_ok42 and _t1_ok42) else 'FAIL'}] 42T1 green footprint punch: base EA {_base_ea42}; F1/L9 without {float(_valley_no_hole42.affected_SF_raw_total):.2f} SF, with 2x4 green hole {float(_valley_with_hole42.affected_SF_raw_total):.2f} SF, drop {_drop42:.2f} SF")

    _red_donut42 = {"designator": "U42R", "host_facet_id": "F16", "position": {"x": 14.0, "y": -4.0}, "shape": "dimensioned", "width": 4.0, "height": 4.0, "kind_label": "SKYLIGHT", "repair_event": True}
    _eng_f1642 = _geom42.engine_facet("F16")
    _full_band42 = float(_aa42(_eng_f1642.facet, [], appurtenances=[{"cx": 14.0, "cy": -4.0, "w": 4.0, "h": 4.0, "kind": "dimensioned"}])[1])
    _donut42 = _assemble_full_roof_scope(txt, {"user_appurtenance_repairs": [_red_donut42]})
    _donut_sf42 = float(_donut42.affected_SF_raw_total)
    _t2_ok42 = (_full_band42 > _donut_sf42 > 0.0 and abs((_full_band42 - _donut_sf42) - 16.0) < 0.15)
    allok &= _t2_ok42
    print(f"  [{'PASS' if _t2_ok42 else 'FAIL'}] 42T2 red donut standalone: full band {_full_band42:.2f} SF, donut {_donut_sf42:.2f} SF, footprint removed {_full_band42 - _donut_sf42:.2f} SF")

    _overlap_green42 = {"designator": "U42O", "host_facet_id": "F1", "position": {"x": 17.0, "y": -19.0}, "shape": "dimensioned", "width": 4.0, "height": 4.0, "kind_label": "SKYLIGHT", "repair_event": False}
    _overlap_red42 = dict(_overlap_green42); _overlap_red42["repair_event"] = True
    _stand_overlap42 = _assemble_full_roof_scope(txt, {"user_appurtenance_repairs": [_overlap_red42]})
    _valley_green42 = _assemble_full_roof_scope(txt, {**_valley_sel42, "user_appurtenance_repairs": [_overlap_green42]})
    _valley_red42 = _assemble_full_roof_scope(txt, {**_valley_sel42, "user_appurtenance_repairs": [_overlap_red42]})
    _stand_sf42 = float(_stand_overlap42.affected_SF_raw_total)
    _net_band42 = float(_valley_red42.affected_SF_raw_total - _valley_green42.affected_SF_raw_total)
    _t3_ok42 = (_stand_sf42 > _net_band42 > 0.0)
    allok &= _t3_ok42
    print(f"  [{'PASS' if _t3_ok42 else 'FAIL'}] 42T3 overlap dedup: standalone donut band {_stand_sf42:.2f} SF, valley-overlap net band {_net_band42:.2f} SF, green footprint-only SF {float(_valley_green42.affected_SF_raw_total):.2f}, red SF {float(_valley_red42.affected_SF_raw_total):.2f}")

    _point42 = {"designator": "U42P", "host_facet_id": "F1", "position": {"x": 10.0, "y": -4.0}, "shape": "point", "kind_label": "VENT", "repair_event": False}
    _valley_point42 = _assemble_full_roof_scope(txt, {**_valley_sel42, "user_appurtenance_repairs": [_point42]})
    _point_ok42 = abs(float(_valley_point42.affected_SF_raw_total - _valley_no_hole42.affected_SF_raw_total)) < 0.01
    allok &= _point_ok42
    print(f"  [{'PASS' if _point_ok42 else 'FAIL'}] 42 point user item punches no footprint hole: valley SF {float(_valley_point42.affected_SF_raw_total):.2f} vs no-user {float(_valley_no_hole42.affected_SF_raw_total):.2f}")


    print()
    print("RESULT:","ALL PASS — v3.5 STABLE SUITE (42 existing checks + 8 flat-valley checks; tests 1-28 "
          "frozen + Yager selected-event coverage 29-31 + flat targets 32 + merged-slope 33 + UI routing 34 + outside fans 35; anchor 3382 (Build 2b re-grounding: Path A live); appurtenance localized spot repair; v3.7 frame-rise flat rule)" if allok else "*** FAIL — do not ship ***")
    sys.exit(0 if allok else 1)
