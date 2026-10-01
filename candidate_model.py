#!/usr/bin/env python3
"""Common candidate envelope for Module 1 detected/user-origin geometry candidates."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Literal, Tuple

CandidateKind = Literal["face", "valley", "penetration", "transition", "appurtenance", "notch"]
CandidateOrigin = Literal["xml", "user"]


@dataclass(frozen=True)
class Candidate:
    kind: CandidateKind
    source_ids: Tuple[str, ...]
    origin: CandidateOrigin
    params: Dict[str, Any] = field(default_factory=dict)
    confirmed: bool = False

    def __post_init__(self) -> None:
        if self.kind not in {"face", "valley", "penetration", "transition", "appurtenance", "notch"}:
            raise ValueError(f"unsupported candidate kind: {self.kind!r}")
        if self.origin not in {"xml", "user"}:
            raise ValueError(f"unsupported candidate origin: {self.origin!r}")
        if self.confirmed is not False:
            raise ValueError("emitters/builders must not confirm candidates")
        object.__setattr__(self, "source_ids", tuple(self.source_ids))
