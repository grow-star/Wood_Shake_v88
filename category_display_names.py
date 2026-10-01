#!/usr/bin/env python3
"""
CATEGORY DISPLAY NAMES — one map, used by every section of the report
====================================================================
An adjuster must never see a database identifier. `SHAKE_FIELD_RR` and `PIPE_JACK_FLASH` are
engine keys; the report is read by people.

Defined ONCE here and imported wherever a category is shown (§2, §5, and anywhere else), so the
name of a thing cannot drift between two sections of the same document.

Covers all 28 registry ids. An unknown id falls back to a readable form of the id itself — never a
crash, never a blank.
"""

from __future__ import annotations

from shared_category_registry import REGISTRY_28

CATEGORY_DISPLAY_NAME = {
    "SHAKE_FIELD_RR": "Wood shake field",
    "VALLEY_METAL": "Valley metal",
    "PIPE_JACK_FLASH": "Pipe jack flashing",
    # Named "Power attic vent" — the words a roofer and an adjuster both use, and the words the
    # carrier writes ("R&R Roof mount power attic vent"). Deliberately NOT "vent cap": Devore's
    # Travelers estimate lists the two separately, so conflating them would mis-compare.
    "POWER_VENT": "Power attic vent",
    "CHIMNEY_FLASH": "Chimney flashing",
    "CHIMNEY_CHASE_COVER": "Chimney chase cover",
    "SKYLIGHT_FLASH": "Skylight flashing",
    "STEP_FLASH": "Step flashing",
    "ENDWALL_FLASH": "Endwall flashing",
    "TRANSITION_FLASH": "Transition flashing",
    "DRIP_EDGE": "Drip edge",
    "STARTER": "Starter course",
    "RIDGE_CAPS": "Ridge caps",
    "HIP_CAPS": "Hip caps",
    "RIDGE_HIP_CAP": "Ridge and hip cap",
    "RIDGE_VENT": "Ridge vent",
    "BOX_VENT": "Box / turtle vent",
    "TURBINE_VENT": "Turbine vent",
    "VENT_CAP": "Vent cap",
    "IWS": "Ice & water shield",
    "APPURT_IWS": "Ice & water (appurtenance)",
    "FIELD_FELT": "Field felt / underlayment",
    "FIELD_TEAROFF": "Field tear-off",
    "FIELD_COVERING": "Field covering",
    "GABLE_CORNICE": "Gable cornice",
    "GENERAL_LABOR": "General labor",
    "STEEP_CHARGE": "Steep-slope charge",
    "HIGH_SLOPE_CHARGE": "High-slope charge",
    # v74 — four receive-only carrier categories (recognised & acknowledged, never a required side).
    "DEBRIS_DISPOSAL": "Debris disposal / haul-off",
    "ROOFER_LABOR": "Roofer labor",
    "EQUIPMENT": "Equipment (ladders, staging, lifts)",
    "FLUE_CAP": "Flue cap",
    "UNMAPPED": "Unmapped item (held for review)",
}

# Comparison keys the report may show that are not plain registry ids.
CATEGORY_DISPLAY_NAME["RIDGE_HIP_CAP__combined"] = "Ridge and hip cap (combined)"


def category_display_name(category_id) -> str:
    """Human-readable name for a category. Never crashes, never returns blank.

    An id we do not know still renders READABLY (underscores to spaces, title-cased) rather than
    leaking a raw database key or, worse, an empty cell that reads as a rendering bug.
    """
    if category_id is None:
        return "Unspecified item"
    key = str(category_id).strip()
    if not key:
        return "Unspecified item"
    if key in CATEGORY_DISPLAY_NAME:
        return CATEGORY_DISPLAY_NAME[key]
    return key.replace("_", " ").strip().capitalize() or key


def _self_check() -> bool:
    missing = [c for c in REGISTRY_28 if c not in CATEGORY_DISPLAY_NAME]
    if missing:
        print("  [FAIL] registry ids with no display name:", missing)
        return False
    print(f"  [PASS] all {len(REGISTRY_28)} registry ids have a display name")
    print(f"  [PASS] unknown id falls back readably: "
          f"{category_display_name('SOME_NEW_THING')!r}")
    return True


if __name__ == "__main__":
    raise SystemExit(0 if _self_check() else 1)
