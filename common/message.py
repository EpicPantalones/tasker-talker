"""
Shared message schema for tasker-talker.

Messages published over ZMQ are JSON-encoded TaskScheduleMessage objects.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import List


@dataclass
class TaskEntry:
    """A single task to be executed at a specific time."""
    task_id: int
    execute_at: str  # ISO 8601 UTC timestamp

    @property
    def execute_at_dt(self) -> datetime:
        return datetime.fromisoformat(self.execute_at)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "TaskEntry":
        return cls(task_id=data["task_id"], execute_at=data["execute_at"])


@dataclass
class TaskScheduleMessage:
    """
    A schedule message published by the publisher.

    Fields
    ------
    message_id  : unique identifier for this message (UUID4 string)
    publish_time: ISO 8601 UTC timestamp of when the message was published
    topic       : ZMQ topic string used for filtering
    tasks       : ordered list of TaskEntry objects
    """
    topic: str
    tasks: List[TaskEntry]
    message_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    publish_time: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    # ------------------------------------------------------------------
    # Serialisation helpers
    # ------------------------------------------------------------------

    def to_json(self) -> str:
        data = {
            "message_id": self.message_id,
            "publish_time": self.publish_time,
            "topic": self.topic,
            "tasks": [t.to_dict() for t in self.tasks],
        }
        return json.dumps(data)

    @classmethod
    def from_json(cls, raw: str) -> "TaskScheduleMessage":
        data = json.loads(raw)
        tasks = [TaskEntry.from_dict(t) for t in data["tasks"]]
        return cls(
            topic=data["topic"],
            tasks=tasks,
            message_id=data["message_id"],
            publish_time=data["publish_time"],
        )

    def __str__(self) -> str:
        lines = [
            f"TaskScheduleMessage(id={self.message_id})",
            f"  published : {self.publish_time}",
            f"  topic     : {self.topic}",
        ]
        for t in self.tasks:
            lines.append(f"  task {t.task_id:>3} : execute_at={t.execute_at}")
        return "\n".join(lines)
