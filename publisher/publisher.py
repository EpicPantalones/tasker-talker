"""
tasker-talker publisher
=======================
Reads a YAML config, builds a TaskScheduleMessage, and publishes it
over a ZMQ PUB socket so that any number of subscribers can act on it.

Usage
-----
    python publisher.py [--config message_config.yaml]
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List

import yaml
import zmq

# Allow running directly from the publisher/ directory
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.message import TaskEntry, TaskScheduleMessage

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [publisher] %(levelname)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

def load_config(path: str) -> dict:
    with open(path, "r") as fh:
        return yaml.safe_load(fh)


def resolve_start_time(schedule: dict) -> datetime:
    """Return a timezone-aware UTC datetime for the first task."""
    raw = schedule.get("start_time")
    if raw:
        dt = datetime.fromisoformat(str(raw))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    delay = float(schedule.get("start_delay_seconds", 5))
    return datetime.now(timezone.utc) + timedelta(seconds=delay)


def build_task_entries(schedule: dict, start: datetime) -> List[TaskEntry]:
    """
    Build an ordered list of TaskEntry objects from the schedule config.

    The config may specify tasks explicitly:
        tasks:
          - id: 1
          - id: 7

    Or implicitly via num_tasks (IDs will be 1 … num_tasks):
        num_tasks: 4

    Each task's execution time is offset from *start* by
    (index * interval_seconds).
    """
    interval = float(schedule.get("interval_seconds", 60))

    explicit_tasks: list = schedule.get("tasks", [])
    if explicit_tasks:
        task_ids = [int(t["id"]) for t in explicit_tasks]
    else:
        n = int(schedule.get("num_tasks", 1))
        task_ids = list(range(1, n + 1))

    entries: List[TaskEntry] = []
    for idx, task_id in enumerate(task_ids):
        execute_at = start + timedelta(seconds=idx * interval)
        entries.append(
            TaskEntry(
                task_id=task_id,
                execute_at=execute_at.isoformat(),
            )
        )
    return entries


# ---------------------------------------------------------------------------
# Publisher
# ---------------------------------------------------------------------------

class Publisher:
    def __init__(self, config: dict):
        pub_cfg = config.get("publisher", {})
        self.address: str = pub_cfg.get("address", "tcp://*:5555")
        self.topic: str = pub_cfg.get("topic", "tasks")
        self.schedule: dict = config.get("schedule", {})

        self.repeat: bool = bool(self.schedule.get("repeat", False))
        self.repeat_seconds: float = float(self.schedule.get("repeat_seconds", 300))

        self._ctx = zmq.Context()
        self._sock = self._ctx.socket(zmq.PUB)

    def start(self) -> None:
        self._sock.bind(self.address)
        log.info("Bound to %s (topic=%r)", self.address, self.topic)

        # ZMQ PUB sockets need a brief moment for subscribers to connect.
        # Without this, the very first message is often dropped.
        time.sleep(1.0)

        try:
            self._publish_once()
            if self.repeat:
                log.info("Repeat mode enabled — republishing every %.0f s.", self.repeat_seconds)
                while True:
                    time.sleep(self.repeat_seconds)
                    self._publish_once()
        finally:
            self.stop()

    def _publish_once(self) -> None:
        start = resolve_start_time(self.schedule)
        entries = build_task_entries(self.schedule, start)
        msg = TaskScheduleMessage(topic=self.topic, tasks=entries)

        # ZMQ multipart: [topic_bytes, payload_bytes]
        self._sock.send_multipart(
            [self.topic.encode(), msg.to_json().encode()]
        )
        log.info("Published message %s with %d task(s).", msg.message_id, len(entries))
        log.info("  First task (id=%d) executes at %s", entries[0].task_id, entries[0].execute_at)
        if len(entries) > 1:
            log.info("  Last  task (id=%d) executes at %s", entries[-1].task_id, entries[-1].execute_at)

    def stop(self) -> None:
        self._sock.close()
        self._ctx.term()
        log.info("Publisher shut down.")


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="tasker-talker publisher")
    parser.add_argument(
        "--config",
        default=str(Path(__file__).parent / "message_config.yaml"),
        help="Path to the message config YAML (default: message_config.yaml)",
    )
    args = parser.parse_args()

    config = load_config(args.config)
    Publisher(config).start()


if __name__ == "__main__":
    main()
