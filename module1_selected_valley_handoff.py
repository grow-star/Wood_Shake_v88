#!/usr/bin/env python3
"""
MODULE 1 — SELECTED REPAIR-EVENT VALLEY HANDOFF  (item: valley-LF missing handoff)
==================================================================================
Closes the gap the audit found: Module 1's geometry already KNOWS every valley's
ID and length; it just never handed the SELECTED valleys' length downstream.

This module adds that handoff. It does NOT add a geometry rule, does NOT decide
which valleys are repair events, and does NOT touch affected-area or cascade math.

LOCKED PRINCIPLE (unchanged):
    XML adjacency  ≠  repair event.
    Repair event   =  user selection (Page 2).

WORKFLOW THIS SERVES:
  Page 1  — parse_valley_geometry(xml): identify ALL valley adjacencies + lengths.
            Geometry map only. Creates NO scope. (Yager: 14 valleys.)
  Page 2  — the UI hands back the user-selected valley IDs (+ features).
  M1 2nd  — build_selected_metadata(geom, selected_ids, selected_features):
            emit the selected-event metadata that downstream scope needs.

DYNAMIC, NOT HARD-CODED:
    selected_valley_LF_total = SUM(XML geometric length of the SELECTED ids).
    Change the selection -> the total changes. Any specific figure (e.g. a given
    roof's validation total) is a RESULT of the chosen IDs, exactly as the
    affected-area SQ is a result, never a constant baked into this rule. No roof-
    or carrier-specific literal lives here.

LENGTH METHOD (validated): true 3-D segment length along each valley's point path,
summed over multi-segment paths. Validated against the frozen anchor L4 = 7.74 LF.
Carrier valley figures are NEVER used as authority here.
"""

import re
import math


# ---- Page 1: geometry map (ALL valleys, no scope) ---------------------------
def parse_valley_geometry(xml_text):
    """Return {valley_id: length_LF} for EVERY type='VALLEY' line in the XML.
       Pure geometry. Implies NO selection and NO scope."""
    pts = {}
    for m in re.finditer(r'<POINT id="(C\d+)" data="([^"]+)"', xml_text):
        x, y, z = (float(v) for v in m.group(2).split(","))
        pts[m.group(1)] = (x, y, z)

    geom = {}
    for m in re.finditer(r'<LINE id="(L\d+)" path="([^"]+)" type="VALLEY"\s*/?>', xml_text):
        vid, path = m.group(1), m.group(2).split(",")
        total = 0.0
        for a, b in zip(path, path[1:]):
            (x1, y1, z1), (x2, y2, z2) = pts[a], pts[b]
            total += math.hypot(math.hypot(x2 - x1, y2 - y1), z2 - z1)
        geom[vid] = round(total, 2)
    return geom


# ---- Page 2 + M1 second pass: selected-event metadata -----------------------
def build_selected_metadata(geom, selected_valley_ids, selected_features=None):
    """Given the geometry map and the USER-selected valley IDs (+ features),
       emit the selected repair-event metadata for downstream scope.

       Output:
         selected_valley_ids       — the user's chosen valley IDs (order preserved)
         selected_valley_lf_by_id  — {id: LF} for each chosen valley
         selected_valley_LF_total  — SUM of those LFs (DYNAMIC; not a constant)
         selected_features         — chosen non-valley features (e.g. chimney 'P')

       A selected ID that is not a valley in the geometry is a caller error
       (the UI must only offer real adjacencies) and raises — we never silently
       invent or drop a selection."""
    selected_valley_ids = list(selected_valley_ids)
    missing = [v for v in selected_valley_ids if v not in geom]
    if missing:
        raise ValueError(f"selected valley IDs absent from XML geometry: {missing}")

    lf_by_id = {v: geom[v] for v in selected_valley_ids}
    return {
        "selected_valley_ids": selected_valley_ids,
        "selected_valley_lf_by_id": lf_by_id,
        "selected_valley_LF_total": round(sum(lf_by_id.values()), 2),
        "selected_features": list(selected_features or []),
    }


# ---- convenience: straight from XML + selection ------------------------------
def selected_valley_handoff(xml_text, selected_valley_ids, selected_features=None):
    """Page 1 + M1 second pass in one call: parse geometry, then resolve the
       user's selection into selected-event metadata."""
    geom = parse_valley_geometry(xml_text)
    meta = build_selected_metadata(geom, selected_valley_ids, selected_features)
    meta["all_valley_ids"] = sorted(geom.keys(), key=lambda s: int(s[1:]))
    return meta
