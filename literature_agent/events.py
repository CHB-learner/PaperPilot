from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


class EventLogger:
    def __init__(self, output_dir: Path) -> None:
        self.path = output_dir / "events.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def emit(self, event_type: str, stage: str, message: str, **payload: Any) -> None:
        record = {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "type": event_type,
            "stage": stage,
            "message": message,
            **payload,
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def read_events(path: Path, limit: int = 20) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()[-limit:]
    events = []
    for line in lines:
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events
