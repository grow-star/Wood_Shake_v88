#!/usr/bin/env python3
"""Shared Category Registry v1 — canonical production home.

Authority: Wood_Shake_Shared_Category_Registry_v1.md. This module is shared
infrastructure for Module 3 keying/comparison and Carrier Parser Part B.
"""

import hashlib
from typing import Mapping, Optional

# v58: POWER_VENT added (28 -> 29 ids). v74: DEBRIS_DISPOSAL, ROOFER_LABOR, EQUIPMENT, FLUE_CAP added
# (29 -> 33 ids) — a controlled operation guarded by the hash below. The constant was literally named
# REGISTRY_28, which became a lie the moment a 29th id landed, so it is now REGISTRY, with REGISTRY_28
# kept as a DEPRECATED ALIAS so every existing import keeps working byte-for-byte. Do not add ids to
# the alias. The four v74 ids are RECEIVE-ONLY (recognised on the carrier side, never emitted by the
# required scope) — the GENERAL_LABOR precedent. See PART 2 of the v74 build.
REGISTRY = [
    "APPURT_IWS","BOX_VENT","CHIMNEY_CHASE_COVER","CHIMNEY_FLASH","DEBRIS_DISPOSAL",
    "DRIP_EDGE","ENDWALL_FLASH","EQUIPMENT","FIELD_COVERING","FIELD_FELT",
    "FIELD_TEAROFF","FLUE_CAP","GABLE_CORNICE","GENERAL_LABOR","HIGH_SLOPE_CHARGE",
    "HIP_CAPS","IWS","PIPE_JACK_FLASH","POWER_VENT","RIDGE_CAPS",
    "RIDGE_HIP_CAP","RIDGE_VENT","ROOFER_LABOR","SHAKE_FIELD_RR","SKYLIGHT_FLASH",
    "STARTER","STEEP_CHARGE","STEP_FLASH","TRANSITION_FLASH","TURBINE_VENT",
    "UNMAPPED","VALLEY_METAL","VENT_CAP",
]
REGISTRY_28 = REGISTRY          # DEPRECATED ALIAS — the name is historical; there are 33 ids now.
REGISTRY_SET = set(REGISTRY)
REGISTRY_HASH = "72dc2aee2f78e7e90eda4d4a1c437f4730c922255135371a390cf73931f83da6"


def registry_fingerprint(ids):
    data = "".join(x + "\n" for x in sorted(set(ids)))
    return hashlib.sha256(data.encode()).hexdigest()


# =============================================================================================
# POWER ATTIC VENT — ONE TYPE, TWO OPERATIONS. **THE FAN CARVES. THE COVER DOES NOT.**
# =============================================================================================
# Binding domain rule (Joseph). A roof-mount power attic vent is detected by EagleView as an
# ordinary PENETRATION, and carriers write it as its own line — Devore's Travelers estimate has
# "12. R&R Roof mount power attic vent  1.00 EA" listed SEPARATELY from
# '11. Exhaust cap - through roof - up to 4"  4.00 EA'. They are NOT the same item and must never
# be conflated: mapping the power vent to VENT_CAP would mis-compare against the carrier.
#
# The two operations differ in EXACTLY ONE THING — whether the shake field is disturbed:
#
#   COVER ONLY   POWER_VENT 1 EA.  ZERO affected area. Nothing is carved. The cover lifts off the
#                                  existing curb; the surrounding shakes are never opened.
#   FAN / UNIT   POWER_VENT 1 EA.  NORMAL footprint carve, exactly like any other appurtenance —
#                                  the unit comes out of the deck, so the field around it is opened.
#
# THIS IS NOT AN ACCESSORY/REPAIR DISTINCTION. It is two operations on ONE type. Both emit the same
# material line; only the carve differs.
#
# APPURT_IWS MUST FALL OUT FOR FREE. module2_scope_expansion emits APPURT_IWS only when the
# appurtenance's affected_SF > 0. A cover-only vent is therefore given NO appurtenance geometry at
# all, so its affected_SF is 0 and the ice & water simply never fires. There is NO if-statement
# suppressing IWS anywhere, and there must never be one: if you find yourself writing one, the
# carve has been modelled in the wrong place.
#
# WHY THE PREDICATE LIVES HERE: the carve is decided in TWO independent places — module2_assembly
# (the SCOPE) and module1_service (the DIAGRAM). This project has shipped the same bug five times by
# letting two consumers each hold their own copy of a rule; the v56 transition-band bug was exactly
# that. One authority, imported by both. This module is the shared vocabulary, it is imported
# everywhere already, and it depends on nothing (hashlib only), so it cannot create a cycle.
POWER_VENT_CATEGORY = "POWER_VENT"
POWER_VENT_COVER = "COVER"          # cover only  -> carves NOTHING
POWER_VENT_FAN = "FAN"              # fan / full unit -> normal footprint carve
POWER_VENT_OPERATIONS = (POWER_VENT_COVER, POWER_VENT_FAN)

# What page 2 may send, normalized. Anything else is not a recognised assertion.
_POWER_VENT_OPERATION_ALIASES = {
    "COVER": POWER_VENT_COVER, "COVER_ONLY": POWER_VENT_COVER, "COVER ONLY": POWER_VENT_COVER,
    "FAN": POWER_VENT_FAN, "UNIT": POWER_VENT_FAN, "FAN_UNIT": POWER_VENT_FAN,
    "FAN / FULL UNIT": POWER_VENT_FAN, "FULL_UNIT": POWER_VENT_FAN, "FULL UNIT": POWER_VENT_FAN,
}


def is_power_vent(row: Optional[Mapping[str, object]]) -> bool:
    """True when this confirmed-selection row is a power attic vent."""
    if not isinstance(row, Mapping):
        return False
    return str(row.get("kind_label") or row.get("type") or "").strip().upper() == POWER_VENT_CATEGORY


def power_vent_operation(row: Optional[Mapping[str, object]]) -> Optional[str]:
    """The normalized operation on a power-vent row, or None if it is not a power vent / not stated.

    NEVER GUESSES. Page 2 makes the choice REQUIRED, so an unstated operation means the payload did
    not come from the UI. See appurtenance_carves for what an unstated operation does."""
    if not is_power_vent(row):
        return None
    raw = str(row.get("operation") or row.get("power_vent_operation") or "").strip().upper()
    return _POWER_VENT_OPERATION_ALIASES.get(raw)


def appurtenance_carves(row: Optional[Mapping[str, object]]) -> bool:
    """Does this appurtenance row disturb the shake field?

    THE ONLY PLACE THIS QUESTION IS ANSWERED. Both the scope (module2_assembly) and the diagram
    (module1_service) import this, so the picture cannot disagree with the numbers.

    Everything carves except a power attic vent whose operation is COVER ONLY.

    FAIL-SAFE ON AN UNSTATED OPERATION: a power-vent row with no recognised operation CARVES. Page 2
    makes the choice required, so this only happens to a hand-built payload — and carving is the
    conservative branch, because it is the one the reviewer can see in the diagram and challenge. The
    dangerous default would be to silently carve nothing and quietly under-scope the claim."""
    if not is_power_vent(row):
        return True
    return power_vent_operation(row) != POWER_VENT_COVER
