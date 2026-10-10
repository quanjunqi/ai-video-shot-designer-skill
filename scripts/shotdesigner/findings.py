"""Shared validation finding model with legacy-dict compatibility."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


Severity = Literal["ERROR", "WARNING"]


@dataclass(frozen=True)
class Finding:
    code: str
    severity: Severity
    message: str
    path: str | None = None
    rule_source: str | None = None

    def as_dict(self):
        value = {"level": self.severity, "code": self.code, "message": self.message}
        if self.path is not None:
            value["path"] = self.path
        if self.rule_source is not None:
            value["rule_source"] = self.rule_source
        return value


def append_to_legacy(findings, errors, warnings):
    for finding in findings:
        target = errors if finding.severity == "ERROR" else warnings
        target.append(finding.as_dict())
