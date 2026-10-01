#!/usr/bin/env python3
"""
REPORT ROOF DIAGRAM (SVG)
=========================
Renders the §4 roof picture from the SAME data the page-2 totals come from:

    workbench_roof_layout.build_roof_layout(...)   -> facet polygons, valleys, transitions
    workbench_diagram_data.build_diagram_data(...) -> per-event affected_polygon rings + summary

THE DIAGRAM READS FROM THE MATH, NEVER THE REVERSE. This module does not compute area, does not
re-derive a zone, and does not re-scale independently: it draws the polygons the engine already
produced, in the shared roof coordinate space, and reports the affected SF the engine already
counted. If the picture and the numbers ever disagree, the picture is wrong — so it is built from
the numbers.

Visual language matches page 2 so the report's picture and the workbench agree at a glance:
    facet outline   light fill, grey stroke
    affected area   red fill (the repair zone)
    valley          solid accent line
    transition      dotted line

No pricing appears here, or anywhere in the SVG.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional, Sequence

VIEW_W = 760.0
VIEW_H = 520.0
PAD = 18.0

FACET_FILL = "#f4f6f8"
FACET_STROKE = "#b9c2cd"
AFFECTED_FILL = "#e4606a"
AFFECTED_STROKE = "#b8323d"
# v63 DEFECT 4: a full slope replacement reads as REPLACED, not as a scatter of red repair boxes. Its
# own visual language (indigo), the same family page 2 uses to distinguish replacement from repair.
REPLACED_FILL = "#7a5cc0"
REPLACED_STROKE = "#5b3fa8"
VALLEY_STROKE = "#33485e"
TRANSITION_STROKE = "#6b5b95"


def _all_points(layout: Mapping[str, Any]) -> list:
    pts: list = []
    for facet in layout.get("facets", []) or []:
        for p in (facet.get("polygon") or []):
            pts.append((float(p[0]), float(p[1])))
    return pts


def _projector(layout: Mapping[str, Any]):
    """One shared transform for EVERYTHING drawn — facets, zones, valleys, transitions.

    A single projector is the whole point: if the affected polygons were scaled by a different
    transform than the facets they sit on, the picture would silently lie about where the repair is.
    """
    pts = _all_points(layout)
    if not pts:
        return (lambda xy: (0.0, 0.0)), 1.0
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    minx, maxx = min(xs), max(xs)
    miny, maxy = min(ys), max(ys)
    span_x = max(maxx - minx, 1e-9)
    span_y = max(maxy - miny, 1e-9)
    scale = min((VIEW_W - 2 * PAD) / span_x, (VIEW_H - 2 * PAD) / span_y)
    off_x = (VIEW_W - span_x * scale) / 2.0
    off_y = (VIEW_H - span_y * scale) / 2.0

    def project(xy):
        x = (float(xy[0]) - minx) * scale + off_x
        y = VIEW_H - ((float(xy[1]) - miny) * scale + off_y)     # SVG y grows downward
        return (x, y)

    return project, scale


def _points_attr(ring: Sequence[Sequence[float]], project) -> str:
    return " ".join(f"{project(p)[0]:.2f},{project(p)[1]:.2f}" for p in ring)


def build_report_diagram_svg(layout: Optional[Mapping[str, Any]],
                             diagram: Optional[Mapping[str, Any]] = None) -> str:
    """Return an SVG string, or "" when there is nothing to draw (caller falls back to the stub)."""
    if not layout or not (layout.get("facets") or []):
        return ""

    project, _scale = _projector(layout)
    parts: list = []

    # --- facets (the roof itself) ---
    for facet in layout.get("facets", []) or []:
        ring = facet.get("polygon") or []
        if len(ring) < 3:
            continue
        parts.append(
            f"<polygon class='rf-facet' points='{_points_attr(ring, project)}' />")

    # --- affected zones — the polygons the ENGINE produced, drawn as-is. A REPLACED facet (v63) gets
    #     its own indigo language; an appurtenance subsumed into a replacement is NOT drawn as a
    #     separate red box (the whole facet is already shown as replaced). Repair zones are unchanged.
    affected_polys = 0
    has_replacement = False
    for event in (diagram or {}).get("events", []) or []:
        kind = event.get("kind")
        if kind == "subsumed":
            continue
        cls = "rf-replaced" if kind == "replacement" else "rf-affected"
        if kind == "replacement":
            has_replacement = True
        for ring in (event.get("affected_polygon") or []):
            if len(ring) < 3:
                continue
            parts.append(
                f"<polygon class='{cls}' points='{_points_attr(ring, project)}' />")
            affected_polys += 1

    # --- valleys (solid) and transitions (dotted) — same language as page 2 ---
    for valley in layout.get("valleys", []) or []:
        line = valley.get("line") or []
        if len(line) < 2:
            continue
        a, b = project(line[0]), project(line[1])
        parts.append(f"<line class='rf-valley' x1='{a[0]:.2f}' y1='{a[1]:.2f}' "
                     f"x2='{b[0]:.2f}' y2='{b[1]:.2f}' />")
    for transition in layout.get("transitions", []) or []:
        line = transition.get("line") or []
        if len(line) < 2:
            continue
        a, b = project(line[0]), project(line[1])
        parts.append(f"<line class='rf-transition' x1='{a[0]:.2f}' y1='{a[1]:.2f}' "
                     f"x2='{b[0]:.2f}' y2='{b[1]:.2f}' />")

    style = (
        "<style>"
        f".rf-facet{{fill:{FACET_FILL};stroke:{FACET_STROKE};stroke-width:1;}}"
        f".rf-affected{{fill:{AFFECTED_FILL};fill-opacity:.55;stroke:{AFFECTED_STROKE};stroke-width:1;}}"
        f".rf-replaced{{fill:{REPLACED_FILL};fill-opacity:.42;stroke:{REPLACED_STROKE};stroke-width:1.5;}}"
        f".rf-valley{{stroke:{VALLEY_STROKE};stroke-width:2;stroke-linecap:round;}}"
        f".rf-transition{{stroke:{TRANSITION_STROKE};stroke-width:2;stroke-dasharray:6 5;stroke-linecap:round;}}"
        "</style>"
    )

    return (f"<svg class='roof-svg' viewBox='0 0 {VIEW_W:.0f} {VIEW_H:.0f}' "
            f"xmlns='http://www.w3.org/2000/svg' role='img' "
            f"aria-label='Roof diagram with the affected repair area shaded'>"
            f"{style}{''.join(parts)}</svg>")


def affected_polygon_count(diagram: Optional[Mapping[str, Any]]) -> int:
    return sum(len(ev.get("affected_polygon") or [])
               for ev in (diagram or {}).get("events", []) or [])


def affected_SF_from_diagram(diagram: Optional[Mapping[str, Any]]) -> float:
    """The SF the ENGINE counted for the events we just drew — never re-measured from the picture."""
    return round(sum(float(ev.get("affected_SF") or 0.0)
                     for ev in (diagram or {}).get("events", []) or []), 1)
