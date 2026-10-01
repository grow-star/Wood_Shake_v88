#!/usr/bin/env python3
"""
MODULE 3 — LANGUAGE GUARD  (application-layer; the renderer stays dumb)
======================================================================
Every NEW editable surface in Module 3 (Argument Builder prose, summary prose,
photo captions, custom "Other" attachment names, user-added supporting-doc labels)
is a place where prohibited coverage/UPPA language could re-enter a system whose
legal posture has so far been protected by the ABSENCE of free text. This guard is
the single chokepoint every editable surface passes through before export.

Two tiers:
  HARD BLOCK  — coverage / legal / payment-conclusion language. CANNOT survive into
                any rendered/exported artifact. Export is refused.
  SOFT WARN   — tone-risk / argumentative wording that may be acceptable in context
                but must be reviewed. Does NOT block; forces user review.

Scope: scans ONLY editable, report-bound text. Does NOT scan uploaded estimate/PDF
contents or any third-party document, NOR carrier-quoted `source_text`, NOR generated
labels, NOR the fixed canonical attachment labels. Raw filenames are never rendered —
only controlled labels; the "Other" custom label IS scanned.

This module adds NO renderer logic, NO calculation, NO pricing, NO scope decision.
"""

import re

# Lists are non-exhaustive ("including but not limited to"); extend as needed.
HARD_BLOCK = [
    "owed", "underpaid", "wrongfully denied", "bad faith", "carrier failed",
    "carrier must", "should pay", "coverage applies", "improper denial", "payment due",
]
SOFT_WARN = [
    "insufficient", "inadequate", "unreasonable", "omitted", "failed to include",
    "dispute", "denial", "not warranted", "excluded",
]

# Controlled list for EXTRA attachments (fixed labels); only "Other" allows a custom name.
CONTROLLED_EXTRAS = [
    "Engineer Report", "ITEL Report", "Manufacturer Documentation",
    "Building Code Documentation", "Weather Report", "Prior Correspondence",
    "Other Supporting Documentation",
]
OTHER_LABEL = "Other"   # the only extra that allows a user-typed custom name (which IS scanned)

def _hits(text, terms):
    t = text or ""
    return [term for term in terms if re.search(r"\b" + re.escape(term) + r"\b", t, re.IGNORECASE)]

def scan_text(text):
    """Returns {'hard': [...], 'soft': [...]} for one string (case-insensitive, word-boundary)."""
    return {"hard": _hits(text, HARD_BLOCK), "soft": _hits(text, SOFT_WARN)}

# the editable surfaces that can reach the exported package
EDITABLE_SURFACE_KEYS = ["argument_prose", "summary_prose", "photo_captions",
                         "custom_attachment_labels", "supporting_doc_labels"]

def collect_editable_surfaces(project):
    """Pull ONLY user-editable, report-bound text from a project. EXCLUDES carrier-quoted
       source_text, uploaded PDF/estimate contents, generated labels, and fixed canonical
       attachment labels. Custom 'Other' attachment names ARE included."""
    atts = project.get("attachments", [])
    return {
        "argument_prose": project.get("argument_prose", ""),
        "summary_prose": project.get("summary_prose", ""),
        "photo_captions": list((project.get("captions") or {}).values()),
        # only user-typed custom labels (source 'user_other'); fixed/controlled labels are safe
        "custom_attachment_labels": [a["label"] for a in atts if a.get("source") == "user_other"],
        "supporting_doc_labels": project.get("supporting_doc_labels", []),
    }

def guard_surfaces(surfaces):
    """surfaces: {name -> str | list[str]}. Aggregates hits with their location."""
    hard, soft = [], []
    for name, val in surfaces.items():
        for txt in (val if isinstance(val, list) else [val]):
            r = scan_text(txt)
            hard += [{"surface": name, "term": h, "text": txt} for h in r["hard"]]
            soft += [{"surface": name, "term": s, "text": txt} for s in r["soft"]]
    return {"hard": hard, "soft": soft, "blocked": bool(hard), "review_required": bool(soft)}

def export_gate(surfaces):
    """Decision gate: allow_export is False iff any HARD term is present on any surface."""
    g = guard_surfaces(surfaces)
    g["allow_export"] = not g["blocked"]
    return g

def safe_export(project, render_fn):
    """App-layer export: collect editable surfaces, run the gate, and render ONLY if not hard-blocked.
       Proves the survive-property — a hard term yields NO artifact. Soft terms render WITH a review flag."""
    gate = export_gate(collect_editable_surfaces(project))
    if not gate["allow_export"]:
        return {"exported": False, "artifact": None, "gate": gate}
    return {"exported": True, "artifact": render_fn(), "gate": gate}

def validate_extra_label(label, custom_name=None):
    """Controlled extra attachments: must be from CONTROLLED_EXTRAS, or 'Other' + a (scanned) custom name."""
    if label in CONTROLLED_EXTRAS:
        return {"ok": True, "label": label, "scanned": False}
    if label == OTHER_LABEL:
        scan = scan_text(custom_name or "")
        return {"ok": not scan["hard"], "label": custom_name, "scanned": True,
                "hard": scan["hard"], "soft": scan["soft"]}
    return {"ok": False, "reason": "not in controlled list and not 'Other'"}
