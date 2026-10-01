#!/usr/bin/env python3
"""
REPAIR LOGIC LIBRARY — authored explanation entries (DATA + lookup)
===================================================================
Additive layer. This is DATA the Module 3 §5 renderer looks up by
(category_id, required_operation, carrier_operation); it authors no claims beyond the
three authored entries below. It does NOT go through the frozen Scope Argument Builder /
argument_pack, does NOT touch Module 1/2, geometry, the Carrier Parser, or the operation
dimension logic, and introduces no pricing or coverage language.

CONDITION-class entries are phrased conditionally on purpose ("Where the existing shakes
cannot be returned to service..."). The renderer surfaces them verbatim; it never asserts
the condition as established and never fabricates evidence.
"""

from __future__ import annotations

# arg_class
CONDITION = "CONDITION"
DEFINITIONAL = "DEFINITIONAL"
# outcome
STANDOFF = "STANDOFF"
DISPEL = "DISPEL"


ENTRIES = [
    {
        "id": "S-1",
        "trigger": {
            "category_id": "SHAKE_FIELD_RR",
            "required_operation": "R_AND_R",
            "carrier_operation": "DETACH_RESET",
        },
        "explanation": (
            "A detach-and-reset operation assumes the existing cedar shakes can be removed "
            "and reinstalled while remaining a serviceable weather-shedding roof covering. "
            "Whether that assumption is valid depends on the physical condition of the "
            "existing roof. Where the existing shakes cannot be removed and returned to "
            "service without compromising their ability to perform as the roof covering, "
            "detach-and-reset is not an equivalent repair operation to remove-and-replace."
        ),
        "arg_class": CONDITION,
        "authority_primary": (
            "Physical condition and serviceability of the existing cedar roof covering"
        ),
        "authority_supporting": (
            "CSSB repair-versus-replacement methodology recognizes repair decisions depend "
            "on roof condition and method rather than a single universal rule "
            "(CSSB Adjusters Guide to Hail)."
        ),
        "outcome": STANDOFF,
        "evidence_required": True,
        "evidence_basis": [
            "brittleness/splitting", "weathering", "enlarged nail holes",
            "damage on withdrawal", "loss of weather resistance",
            "repair difficulty on a poor-condition roof",
        ],
        "suppressed": ["careful-storage-labor argument"],
    },
    {
        "id": "S-2",
        "trigger": {
            "category_id": "SHAKE_FIELD_RR",
            "required_operation": "R_AND_R",
            "carrier_operation": "INSTALL_ONLY",
        },
        "explanation": (
            "A remove-and-replace operation consists of removing and disposing of the "
            "existing roofing material, furnishing new roofing material, and installing that "
            "new material. An install-only operation addresses only the installation of "
            "roofing material; it does not include removal and disposal of the existing roof "
            "covering or furnishing the replacement material. The operations describe "
            "different scopes of work and are therefore not equivalent repair operations."
        ),
        "arg_class": DEFINITIONAL,
        "authority_primary": "Definitional / scope composition",
        "authority_supporting": None,
        "outcome": DISPEL,
        "evidence_required": False,
        "evidence_basis": [],
        "suppressed": [],
    },
    {
        "id": "S-3",
        "trigger": {
            "category_id": "SHAKE_FIELD_RR",
            "required_operation": "R_AND_R",
            "carrier_operation": "REPLACE",
        },
        "explanation": (
            "A remove-and-replace operation includes removal and disposal of the existing "
            "roofing material, furnishing replacement material, and installation of that "
            "replacement material. A replace operation includes furnishing and installing "
            "replacement material but does not, by itself, describe removal and disposal of "
            "the existing roof covering. The operations describe different scopes of work "
            "and are therefore not equivalent repair operations."
        ),
        "arg_class": DEFINITIONAL,
        "authority_primary": "Definitional / scope composition",
        "authority_supporting": None,
        "outcome": DISPEL,
        "evidence_required": False,
        "evidence_basis": [],
        "suppressed": [],
    },
]

# index by exact trigger tuple for O(1), unambiguous lookup
_INDEX = {
    (e["trigger"]["category_id"],
     e["trigger"]["required_operation"],
     e["trigger"]["carrier_operation"]): e
    for e in ENTRIES
}


def lookup_entry(category_id, required_operation, carrier_operation):
    """Return the authored entry whose trigger exactly matches the (category, required op,
    carrier op) triple, or None. Exact match only — no fuzzy/partial matching, so the library
    never surfaces an explanation on an operation pair it was not authored for."""
    return _INDEX.get((category_id, required_operation, carrier_operation))


if __name__ == "__main__":
    for e in ENTRIES:
        t = e["trigger"]
        print(f"{e['id']}: {t['category_id']} · {t['required_operation']} vs "
              f"{t['carrier_operation']}  [{e['arg_class']}/{e['outcome']}]")
