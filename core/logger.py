"""Processing log collection and formatting for Streamlit."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


class ProcessingLogger:
    """Collect step-by-step processing logs with timestamps and warnings."""

    def __init__(self) -> None:
        self.entries: list[dict[str, Any]] = []
        self.warnings: list[str] = []

    def log(self, step: str, status: str, message: str) -> None:
        """Append a log entry.

        Parameters
        ----------
        step:
            Short step identifier (e.g. ``"validate"``, ``"clean"``).
        status:
            ``"ok"``, ``"warn"``, ``"error"``.
        message:
            Human-readable description.
        """
        self.entries.append(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "step": step,
                "status": status,
                "message": message,
            }
        )
        if status == "warn":
            self.warnings.append(message)

    def to_markdown(self) -> str:
        """Return a formatted markdown string suitable for ``st.markdown``."""
        lines: list[str] = ["### 处理日志", ""]
        for e in self.entries:
            ts = e["timestamp"][:19].replace("T", " ")
            icon = {"ok": "✅", "warn": "⚠️", "error": "❌"}.get(e["status"], "ℹ️")
            lines.append(f"{icon} **{e['step']}** — {e['message']}  *({ts})*")
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict for downstream error reports."""
        return {
            "entries": self.entries,
            "warnings": self.warnings,
        }
