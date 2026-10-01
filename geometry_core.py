#!/usr/bin/env python3
# Extracted production geometry primitives from regression_test.py.
# CHANGELOG 2026-07-01: stair_edges inner-edge first-row guard included
# (prev_i is None -> ie[n]=vx(ye)), matching the v3.4 regression source.
# CHANGELOG 2026-07-03: unified centerline-extent stair seed for flat valleys; anchor unchanged 3691.

import re
from math import degrees, atan2
import numpy as np
from matplotlib.path import Path

EXPOSURE_IN    = 10.0
SHAKE_WIDTH_IN = 7.0
JOINT_OFFSET_IN= 1.5
LATERAL_STEP_IN= SHAKE_WIDTH_IN/2.0
assert LATERAL_STEP_IN >= JOINT_OFFSET_IN, "lateral_step violates CSSB joint offset"
CLEAR_BAND_FT  = 2.0
APPURT_CLEAR_IN= 21.0
EXP=EXPOSURE_IN/12.; STEP=LATERAL_STEP_IN/12.; BAND=CLEAR_BAND_FT
CLR=APPURT_CLEAR_IN/12.

DEFAULT_SHAKE_MEASUREMENTS = {
    "width_in": SHAKE_WIDTH_IN,
    "exposure_in": EXPOSURE_IN,
    "length_in": 24.0,
    "thickness": "3/4",
    "measurement_source": "default — not field-measured",
}


def resolve_shake_measurements(measurements=None):
    """Return validated per-job shake measurements with legacy defaults.

    A single measured width drives both the shake count and stagger. Exposure
    drives the course grid. Width below 3 in is rejected because width/2 must
    satisfy the CSSB 1.5 in joint-offset floor. Exposure above the length/
    thickness code cap is allowed with a warning flag because field reality may
    differ and must be documented.
    """
    src = dict(DEFAULT_SHAKE_MEASUREMENTS)
    if measurements:
        src.update({k: v for k, v in dict(measurements).items() if v not in (None, "")})
    width = float(src.get("width_in", SHAKE_WIDTH_IN))
    exposure = float(src.get("exposure_in", EXPOSURE_IN))
    length = float(src.get("length_in", 24.0))
    thickness = str(src.get("thickness", "3/4"))
    if width <= 0 or exposure <= 0:
        raise ValueError("shake width and exposure must be greater than 0")
    if width < 3.0:
        raise ValueError("shake width must be at least 3.0 in so width/2 satisfies the 1.5 in joint-offset floor")
    if width > 14.0:
        raise ValueError("shake width exceeds sane upper bound of 14 in")
    if exposure > max(length / 2.0, 1.0):
        raise ValueError("shake exposure exceeds sane upper bound of length/2")
    code_max = 7.5 if (length == 18.0 or thickness in {"3/8", "0.375", "thin"}) else 10.0
    exposure_over_code_max = exposure > code_max + 1e-9
    return {
        "width_in": width,
        "exposure_in": exposure,
        "length_in": length,
        "thickness": thickness,
        "lateral_step_in": width / 2.0,
        "exposure_over_code_max": exposure_over_code_max,
        "code_max_exposure_in": code_max,
        "measurement_source": src.get("measurement_source") or src.get("source") or "field-measured",
    }


def _profile_units(shake_measurements=None):
    prof = resolve_shake_measurements(shake_measurements)
    step_in = prof["lateral_step_in"]
    assert step_in >= JOINT_OFFSET_IN, "lateral_step violates CSSB joint offset"
    return prof["exposure_in"] / 12.0, step_in / 12.0

def stair_edges(vs,va,fan,top_y,y0,exposure_in=None,shake_width_in=None):
    """Unified per-course band. Below a rising valley's apex the inner edge rides
    the valley line (shared edge with the neighbor) and the outer edge steps out.
    At/above the apex -- and for the whole of a flat valley -- the band fans BOTH
    ways from the valley's cross-slope extent, up to the boundary. The 'both ways'
    open is fan-independent (min edge steps left, max edge steps right)."""
    measurements = {"exposure_in": exposure_in or EXPOSURE_IN, "width_in": shake_width_in or SHAKE_WIDTH_IN}
    exp_ft, step_ft = _profile_units(measurements)
    vs=np.asarray(vs,float); va=np.asarray(va,float); apex=va[1]
    flat = abs(va[1]-vs[1]) < 1e-9
    ax_lo = min(vs[0],va[0]) if flat else float(va[0])
    ax_hi = max(vs[0],va[0]) if flat else float(va[0])
    def vx(yy):
        if yy<=apex and apex!=vs[1]:
            t=(yy-vs[1])/(apex-vs[1]); return vs[0]+t*(va[0]-vs[0])
        return va[0]
    nc=int(np.ceil((top_y-y0)/exp_ft))+1
    oe=np.full(nc,np.nan); ie=np.full(nc,np.nan)
    n0=max(int(np.floor((vs[1]-y0)/EXP+1e-9)),0)
    prev_o=prev_i=None
    for n in range(n0,nc):
        yy=y0+n*exp_ft; ye=max(yy,vs[1])
        if ye<=apex and apex!=vs[1]:
            # BELOW apex (rising valley): inner edge = valley line, outer edge steps out. UNCHANGED.
            be=vx(ye)+fan*BAND
            oe[n]=be if prev_o is None else (max(be,prev_o+fan*step_ft) if fan>0 else min(be,prev_o+fan*step_ft))
            ie[n]=vx(ye)
        else:
            # AT/ABOVE apex (or flat valley): fan BOTH ways from the extent, band on fan side.
            seed_lo=ax_lo-(BAND if fan<0 else 0.0)
            seed_hi=ax_hi+(BAND if fan>0 else 0.0)
            if prev_o is None:
                ie[n]=seed_lo; oe[n]=seed_hi
            else:
                cur_lo=min(prev_o,prev_i); cur_hi=max(prev_o,prev_i)
                ie[n]=min(seed_lo, cur_lo-step_ft)   # min edge steps left (outward)
                oe[n]=max(seed_hi, cur_hi+step_ft)   # max edge steps right (outward)
        prev_o=oe[n]; prev_i=ie[n]
    return oe,ie,nc

def appurt_rect(app):
    """v3.2: appurtenance disturbance footprint, by TYPE (never size threshold).
    app REQUIRES 'kind': 'point' or 'dimensioned'.
      POINT (pipe jack, turtle/box vent, turbine): fixed 21x21 square; no dims.
      DIMENSIONED (chimney, skylight, other/custom): footprint + 21in EACH side;
        requires positive w AND h.
    A dimensioned type with missing/zero dims is an ERROR, never a silent
    fallback to a point — the dropdown type is authoritative (Formula Spec §9).
    Returns rectangle polygon in facet frame (feet)."""
    cx,cy=app['cx'],app['cy']; kind=app.get('kind')
    if kind=='point':
        hx=hy=CLR/2.0
    elif kind=='dimensioned':
        w=app.get('w',0.0); h=app.get('h',0.0)
        if not (w>0 and h>0):
            raise ValueError(f"dimensioned appurtenance requires positive w and h; "
                             f"got w={w}, h={h} (type must not silently become a point)")
        hx=w/2.0+CLR; hy=h/2.0+CLR
    else:
        raise ValueError(f"appurtenance 'kind' must be 'point' or 'dimensioned'; got {kind!r}")
    return [(cx-hx,cy-hy),(cx+hx,cy-hy),(cx+hx,cy+hy),(cx-hx,cy+hy)]

def _shadow_fill_column(fld, bnd):
    """Shared shadow rule: within each contiguous field segment, fill from the
    first band-hit upward to the top of that segment. Used by valley AND
    appurtenance events identically.

    REFERENCE IMPLEMENTATION (v3.8): retained verbatim as the definition of the
    rule and as the equivalence oracle for the vectorized `shadow_fill` below.
    It is no longer called per-column in the hot path (that cost 46% of runtime);
    `shadow_fill` computes the identical result for the whole grid at once."""
    out=np.zeros(len(fld),bool); i=0; N=len(fld)
    while i<N:
        if not fld[i]: i+=1; continue
        k=i
        while k<N and fld[k]: k+=1
        seg=bnd[i:k]
        if seg.any(): out[i+int(np.argmax(seg)):k]=True
        i=k
    return out

def shadow_fill(field, band):
    """VECTORIZED shadow fill (v3.8 performance). Bit-identical to applying
    `_shadow_fill_column` down every column, computed over the whole 2-D grid in
    one pass.

    The RULE IS UNCHANGED: within each contiguous True-run of `field` down a
    column, fill from that run's first band-hit row through the end of the run.
    Implementation: label each contiguous field run down a column (`segid`), take
    the minimum band-hit row within each (segment, column) via `np.minimum.at`,
    then keep the field cells at or below their segment's first hit. `big` (= n)
    is the "no hit in this segment" sentinel, so segments without a hit stay
    empty exactly as the per-column version leaves them.

    Formulation: a cell is filled iff it is field AND at least one band-hit has
    occurred at-or-above it WITHIN its own contiguous run. Let c = cumulative
    count of hits down the column. For a run beginning at row s, the number of
    hits inside the run at-or-above row r is c[r] - c_excl[s], where c_excl[s] is
    the hit count strictly above s. Because run starts move downward and c_excl is
    non-decreasing, `np.maximum.accumulate` of "c_excl at run starts, -1 elsewhere"
    propagates each run's baseline to its own rows. This uses only cumsum and
    maximum.accumulate (fast C reductions) — no `np.minimum.at`, which is an
    unbuffered scatter and was itself a major cost.

    field, band: 2-D bool arrays (rows = y, cols = x). Returns a 2-D bool array."""
    F=np.asarray(field,bool); B=np.asarray(band,bool)&F
    n,m=F.shape
    if n==0 or m==0: return np.zeros(F.shape,bool)
    prevF=np.vstack([np.zeros((1,m),bool),F[:-1,:]])
    start=F&~prevF                                     # first row of each contiguous field run
    c=np.cumsum(B,axis=0,dtype=np.int32)               # hits at-or-above, cumulative
    c_excl=c-B                                         # hits strictly above this row
    base=np.where(start,c_excl,-1).astype(np.int32)    # baseline recorded at each run start
    seg_base=np.maximum.accumulate(base,axis=0)        # each cell inherits its run's baseline
    return F&(seg_base>=0)&((c-seg_base)>0)            # a hit occurred at-or-above, within this run

# ---- v3.8 performance: per-facet grid + point-in-polygon mask cache ----------
# The meshgrid and the containment masks depend ONLY on the facet polygon, the
# penetration holes, the notch holes, `res`, and the resolved shake measurements.
# They do NOT depend on which valley is being processed, yet affected_area was
# rebuilding them on every call (79 calls on Yager). Cache them on a key that
# includes every one of those inputs, so a different facet / hole set / resolution
# / measurement profile can never hit a stale entry (and neither can another roof,
# since its polygons differ).
_GRID_CACHE = {}
_GRID_CACHE_MAX = 64          # bounded: cannot grow without limit across roofs

def _poly_key(poly):
    return tuple((float(x),float(y)) for x,y in poly)

def _grid_cache_key(facet,pens,nots,res,prof):
    return (_poly_key(facet),
            tuple(_poly_key(h) for h in (pens or [])),
            tuple(_poly_key(h) for h in (nots or [])),
            float(res),
            float(prof["width_in"]), float(prof["exposure_in"]))

def clear_grid_cache():
    """Drop all cached grids/masks (e.g. between roofs). Purely a memory control:
    correctness never depends on this, because the key is complete."""
    _GRID_CACHE.clear()

_AREA_CACHE = {}
_AREA_CACHE_MAX = 64

def _hashable_valleys(valleys):
    out=[]
    for vs,va,fan in valleys:
        out.append((tuple(float(v) for v in np.asarray(vs,float).ravel()),
                    tuple(float(v) for v in np.asarray(va,float).ravel()),
                    repr(fan)))
    return tuple(out)

def _hashable_apps(apps):
    return tuple(tuple(sorted((str(k),repr(v)) for k,v in a.items())) for a in (apps or []))

def _band_key(bands):
    return tuple((float(b["x0"]),float(b["x1"]),float(b["y0"]),float(b["y1"])) for b in (bands or []))

def _area_cache_key(facet,valleys,pens,nots,apps,res,prof,return_zone,bands=None):
    """COMPLETE key: every input affected_area's result depends on. Any difference in
    facet, valleys, penetration holes, notch holes, appurtenances, resolution, or the
    resolved measurements is a MISS, so a stale result can never be reused (across
    facets, measurement profiles, or roofs)."""
    return (_poly_key(facet),
            _hashable_valleys(valleys),
            tuple(_poly_key(h) for h in (pens or [])),
            tuple(_poly_key(h) for h in (nots or [])),
            _hashable_apps(apps),
            float(res),
            float(prof["width_in"]), float(prof["exposure_in"]),
            bool(return_zone),
            _band_key(bands))

def clear_area_cache():
    _AREA_CACHE.clear()

def _facet_grid(facet,pens,nots,res,prof):
    """Return (gx,gy,X,Y,pts,inside,field) for this facet, from cache when the
    exact same inputs were seen before."""
    key=_grid_cache_key(facet,pens,nots,res,prof)
    hit=_GRID_CACHE.get(key)
    if hit is not None: return hit
    pf=Path(facet)
    pen_paths=[Path(h) for h in (pens or [])]
    not_paths=[Path(h) for h in (nots or [])]
    top_y=max(p[1] for p in facet); y0=min(p[1] for p in facet)
    gx=np.arange(min(p[0] for p in facet)-0.3,max(p[0] for p in facet)+0.3,res)
    gy=np.arange(y0-0.3,top_y+0.3,res)
    X,Y=np.meshgrid(gx,gy)
    pts=np.column_stack([X.ravel(),Y.ravel()])
    in_facet=pf.contains_points(pts).reshape(X.shape)
    in_pen=np.zeros(X.shape,bool); in_not=np.zeros(X.shape,bool)
    for h in pen_paths: in_pen|=h.contains_points(pts).reshape(X.shape)
    for h in not_paths: in_not|=h.contains_points(pts).reshape(X.shape)
    inside=in_facet&~in_pen&~in_not                 # countable shake field
    field =in_facet&~in_not                          # shadow medium
    val=(gx,gy,X,Y,pts,inside,field)
    if len(_GRID_CACHE)>=_GRID_CACHE_MAX: _GRID_CACHE.clear()
    _GRID_CACHE[key]=val
    return val

def affected_area(facet,valleys,penetrations=None,notches=None,
                  appurtenances=None,res=0.04,return_zone=False,
                  shake_measurements=None, width_in=None, exposure_in=None,
                  transition_bands=None):
    """Union of per-event zones (valleys + appurtenances), shadow-filled per
    rule (C), clipped to facet minus all holes. Source-agnostic: events from
    EagleView and user placement are identical here (rule F).
    penetrations: ROOFPENETRATION holes (shadow continues through).
    notches: dormer/separate-section holes (shadow stops).
    appurtenances: list of dict(cx,cy,w,h) confirmed appurtenance events.
    transition_bands: list of dict(x0,x1,y0,y1) in FACET-FRAME coords — the tear-off band of a
    user-confirmed pitch-transition repair event (spec amendment: Transition Repair Events v0.1).
    ADDITIVE: default None -> not one bit of existing behavior changes. Like appurtenances, a
    transition band is a localized strip (its extent is specified: 36 in up-slope / 1 course
    down-slope), so it is clipped to the facet and UNIONED with every other event's zone —
    never summed.
    return_zone: if True, also return (zone_mask, gx, gy) for edge-contact
    extraction (v3.3 stable). Default False keeps the frozen (per, area) signature."""
    if shake_measurements is None and (width_in is not None or exposure_in is not None):
        shake_measurements = {"width_in": width_in or SHAKE_WIDTH_IN, "exposure_in": exposure_in or EXPOSURE_IN}
    prof = resolve_shake_measurements(shake_measurements)
    exp_ft = prof["exposure_in"] / 12.0
    # v3.8: memoize the whole result. edge_contacts() calls affected_area once per
    # component and Module 2 calls it again directly, so the SAME (facet, valleys,
    # holes, appurtenances, res, measurements) zone was being recomputed many times
    # (79 calls for ~13 distinct inputs on Yager). The key below is complete, so this
    # is a pure speed change. `per` is copied out so no caller can mutate cached state;
    # the mask/grid arrays are treated as read-only by every caller (verified).
    try:
        _key=_area_cache_key(facet,valleys,penetrations,notches,appurtenances,res,prof,return_zone,
                             transition_bands)
    except TypeError:
        _key=None                                    # unhashable input -> just compute, never cache
    if _key is not None:
        _hit=_AREA_CACHE.get(_key)
        if _hit is not None:
            if return_zone:
                _per,_area,_zone,_gx,_gy=_hit
                return list(_per),_area,_zone,_gx,_gy
            _per,_area=_hit
            return list(_per),_area
    top_y=max(p[1] for p in facet); y0=min(p[1] for p in facet)
    # v3.8: grid + containment masks are identical for every valley on this facet ->
    # build once and reuse (cache key covers facet, holes, res, and measurements).
    gx,gy,X,Y,pts,inside,field=_facet_grid(facet,penetrations,notches,res,prof)
    union=np.zeros(X.shape,bool); per=[]
    # ---- VALLEY events (v3.1 path, unchanged) ----
    for vs,va,fan in valleys:
        vs=np.asarray(vs,float); va=np.asarray(va,float)
        oe,ie,nc=stair_edges(vs,va,fan,top_y,y0,exposure_in=prof["exposure_in"],shake_width_in=prof["width_in"])
        nidx=np.clip(((Y-y0)//exp_ft).astype(int),0,nc-1)
        lo=np.minimum(oe[nidx],ie[nidx]); hi=np.maximum(oe[nidx],ie[nidx])
        inband=(X>=lo-1e-9)&(X<=hi+1e-9)&(Y>=vs[1])
        # v3.8: whole-grid vectorized shadow fill, bit-identical to the per-column loop.
        dist=shadow_fill(field, inband&field)
        per.append((dist&inside).sum()*res*res)
        union|=dist
    # ---- TRANSITION repair events (user-confirmed; band of defined extent) ----
    # The band's extent is SPECIFIED (36 in up-slope on the upper facet, 1 course down-slope on the
    # lower one), so like an appurtenance it is a localized strip: clipped to the facet, unioned with
    # every other zone. It is NOT valley-style shadow-filled to the ridge — that would erase the
    # specified 36 in and strip the whole upper slope.
    for band in (transition_bands or []):
        bx0=float(band["x0"]); bx1=float(band["x1"]); by0=float(band["y0"]); by1=float(band["y1"])
        dist=(X>=bx0-1e-9)&(X<=bx1+1e-9)&(Y>=by0-1e-9)&(Y<=by1+1e-9)&field
        per.append((dist&inside).sum()*res*res)
        union|=dist

    # ---- APPURTENANCE events (localized spot repair, no valley-style shadow fill) ----
    for app in (appurtenances or []):
        rect=Path(appurt_rect(app))
        dist=rect.contains_points(pts).reshape(X.shape)&field
        per.append((dist&inside).sum()*res*res)
        union|=dist
    zone=union&inside
    area=zone.sum()*res*res
    if _key is not None:
        if len(_AREA_CACHE)>=_AREA_CACHE_MAX: _AREA_CACHE.clear()
        _AREA_CACHE[_key]=(list(per),area,zone,gx,gy) if return_zone else (list(per),area)
    if return_zone:
        return per,area,zone,gx,gy
    return per,area

# ---- v3.3 RELEASED: edge-contact extractor (Module 1 output -> contacted_edges[]) ----
def edge_contact_lf(A,B,zone,gx,gy,res,facet):
    """Strip-integration contact length (diagonal-stable). Probes PERPENDICULAR
    into the facet at depths 1-4 cells and counts an along-edge position as
    contacted when a majority of those depths fall in the zone. Averaging over
    depth makes it orientation-independent and convergent across resolution for
    the edges that drive materials (ridge/eave/rake/hip). An earlier
    perpendicular-only/omnidirectional probe under-counted steep diagonals
    (a 45-deg edge staircases through the grid); this does not.
    NOTE: valleys are NOT measured by contact (scoped by their own length);
    edge_contacts() skips them. Valley contact is intrinsically unstable here
    (sub-cell gap on a 45-deg edge) and unused."""
    A=np.asarray(A,float); B=np.asarray(B,float); L=float(np.hypot(*(B-A)))
    if L<=0: return 0.0
    d=(B-A)/L; nrm=np.array([-d[1],d[0]])
    pf=Path([tuple(p) for p in facet]); mid=(A+B)/2
    if not pf.contains_point(tuple(mid+nrm*res*3)): nrm=-nrm   # inward normal
    H,W=zone.shape; n=max(int(L/(res*0.5)),2)
    # v3.8: vectorized over the n along-edge positions x 4 probe depths. Same rule,
    # same arithmetic, same rounding (np.rint == round-half-to-even, matching Python's
    # round() used before), same majority threshold (>=2 of 4 depths inside the zone).
    t=((np.arange(n)+0.5)/n)[:,None]                       # (n,1)
    base=A[None,:]+t*(B-A)[None,:]                         # (n,2)
    k=np.array([1.0,2.0,3.0,4.0])[None,:,None]             # (1,4,1)
    p=base[:,None,:]+nrm[None,None,:]*(k*res)              # (n,4,2)
    jx=np.rint((p[:,:,0]-gx[0])/res).astype(np.int64)
    iy=np.rint((p[:,:,1]-gy[0])/res).astype(np.int64)
    ok=(iy>=0)&(iy<H)&(jx>=0)&(jx<W)
    z=np.zeros((n,4),bool)
    z[ok]=zone[iy[ok],jx[ok]]
    hit=int((z.sum(axis=1)>=2).sum())
    return hit/n*L

def edge_contacts(facet,valleys,edges,penetrations=None,notches=None,
                  appurtenances=None,res=0.04,shake_measurements=None):
    """edges: list of (A, B, etype, total_lf). Returns {etype: (contact_lf,
    total_lf)} — the contacted_edges[] interface Module 2 consumes. VALLEY-type
    edges are SKIPPED (valley metal/underlayment scoped by the valley's own
    length, never by contact). Contact is honest geometry; Module 2 applies the
    material rules (95% round-to-full on ridge/hip caps, drip edge, transition)."""
    _,_,zone,gx,gy=affected_area(facet,valleys,penetrations,notches,
                                 appurtenances,res=res,return_zone=True,
                                 shake_measurements=shake_measurements)
    out={}
    for A,B,et,tot in edges:
        if 'VALLEY' in et.upper():
            continue
        out[et]=(edge_contact_lf(A,B,zone,gx,gy,res,facet),tot)
    return out


def transition_detect(eA, eB, pA, pB, fA, fB):
    """Return (two_condition, true_transition) for a shared roof edge.

    Production transition primitive formerly hosted in regression_test.py and
    consumed by transition_enumerator.py.
    """
    c1 = abs(pA - pB) > 0.5
    dz = abs(eA[2] - eB[2])
    ln = np.hypot(eA[0] - eB[0], eA[1] - eB[1])
    c2 = degrees(atan2(dz, ln)) <= 15
    c3 = np.dot(fA, fB) > 0
    return (c1 and c2), (c1 and c2 and c3)

# ---- XML helpers ----
def getP(txt,ids):
    P={}
    for c in ids:
        m=re.search(rf'POINT id="{c}" data="([-\d.]+),([-\d.]+),([-\d.]+)"',txt)
        if m: P[c]=tuple(float(z) for z in m.groups())
    return P

def mkframe_pts(points3d_order, eave_a, eave_b):
    """Fall-line frame per rule (D)."""
    pp=[np.array(p,float) for p in points3d_order]
    nrm=np.zeros(3)
    for i in range(len(pp)): nrm+=np.cross(pp[i],pp[(i+1)%len(pp)])
    nrm/=np.linalg.norm(nrm)
    if nrm[2]<0: nrm=-nrm
    g=np.array([0,0,-1.0])
    fall=g-np.dot(g,nrm)*nrm; fall/=np.linalg.norm(fall)
    up=-fall
    x=np.cross(up,nrm); x/=np.linalg.norm(x)
    er=np.array(eave_b,float)-np.array(eave_a,float)
    if np.dot(x,er)<0: x=-x
    O=pp[0]
    return lambda p3: np.array([np.dot(np.array(p3,float)-O,x),
                                np.dot(np.array(p3,float)-O,up)])


def excluded_region_aware_notch_fan(facet, holes, seg_a, seg_b, band=2.0, reach=8.0, res=0.4):
    """Excluded-region-aware notch fan (general, topology-driven).

    On a merged slope, a repair cascade must fan into the OPEN roof field -- inside the
    merged facet and OUTSIDE every excluded region. An excluded region is any hole in the
    repair field: a dormer, a courtyard, a chimney chase, a mechanical well, a cluster of
    skylights -- they are ALL treated identically here. The rule never asks what created a
    hole; it only asks which side of the valley leads to open field.

    Determined as PURE GEOMETRY, before any affected_area/cascade runs:
      1. Adjacency: if exactly one side within `band` of the valley is blocked (inside an
         excluded region or outside the facet), fan to the clear side.
      2. Otherwise, fan toward the side whose LOCAL open field (up the fall line, within
         `reach`, inside facet and outside all excluded regions) is larger -- the connected
         repair region, not merely the nearest hole.
      3. If both sides are geometrically symmetric, mark ambiguous and fall back
         deterministically toward the facet centroid x.

    Returns +1 (fan toward +x in the frame) or -1. Independent of cascade fragmentation.
    """
    fp = np.asarray(facet, dtype=float)[:, :2]
    def _pip(pt, poly):
        x, y = pt; n = len(poly); c = False; j = n - 1
        for i in range(n):
            xi, yi = poly[i][0], poly[i][1]; xj, yj = poly[j][0], poly[j][1]
            if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi + 1e-30) + xi):
                c = not c
            j = i
        return c
    def _in_excluded(pt):
        return any(_pip(pt, h) for h in holes)
    a = np.asarray(seg_a, dtype=float)[:2]; b = np.asarray(seg_b, dtype=float)[:2]
    mid = (a + b) / 2.0
    d = b - a; d = d / (np.linalg.norm(d) + 1e-30)
    nrm = np.array([-d[1], d[0]])
    def _xfan(vec): return 1 if vec[0] > 0 else -1
    p_plus = mid + nrm * band; p_minus = mid - nrm * band
    plus_valid = _pip(p_plus, fp) and not _in_excluded(p_plus)
    minus_valid = _pip(p_minus, fp) and not _in_excluded(p_minus)
    if plus_valid and not minus_valid:
        return _xfan(nrm)
    if minus_valid and not plus_valid:
        return _xfan(-nrm)
    up = float(fp[:, 1].max() - mid[1]); up = up if up > 1.0 else 25.0
    def _open(side):
        perp = side * nrm; area = 0.0
        for i in range(1, int(reach / res) + 1):
            for k in range(0, int(up / res) + 1):
                pt = mid + perp * (i * res) + np.array([0.0, k * res])
                if _pip(pt, fp) and not _in_excluded(pt):
                    area += res * res
        return area
    pa, ma = _open(1), _open(-1)
    if abs(pa - ma) > 3.0:
        return _xfan(nrm) if pa > ma else _xfan(-nrm)
    cen = fp.mean(axis=0)
    return 1 if cen[0] > mid[0] else -1
