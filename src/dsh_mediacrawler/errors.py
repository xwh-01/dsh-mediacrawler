from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class AdapterError(Exception):
    code: str
    message: str
    retryable: bool = False
    run_id: str | None = None
    remediation: str | None = None

    def __str__(self) -> str:
        return self.message

    def response(self) -> dict[str, Any]:
        error: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
        }
        if self.run_id:
            error["run_id"] = self.run_id
        if self.remediation:
            error["remediation"] = self.remediation
        return {"ok": False, "error": error}
