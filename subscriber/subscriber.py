"""
tasker-talker subscriber
========================
Connects to a ZMQ PUB socket, receives TaskScheduleMessages, and
schedules the corresponding local scripts to run at the instructed times.

Usage
-----
    python subscriber/subscriber.py [--config task_config.yaml]
"""

from __future__ import annotations

import argparse
import datetime
import logging
import os
import shlex
import subprocess
import sys
import threading
from pathlib import Path
from typing import Dict, Optional

import yaml
import zmq

# Allow running directly from the subscriber/ directory
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.message import TaskEntry, TaskScheduleMessage

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [subscriber] %(levelname)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

def load_config(path: str) -> dict:
    with open(path, "r") as fh:
        return yaml.safe_load(fh)


def parse_task_map(config: dict) -> Dict[int, dict]:
    """
    Return a mapping of  task_id (int) → task definition dict.

    Expected config shape:
        tasks:
          1:
            name: "Collect data"
            script: "./scripts/collect.sh"
            args: ["--verbose"]
            env: {}          # optional extra environment variables
          2:
            ...
    """
    raw: dict = config.get("tasks", {})
    return {int(k): v for k, v in raw.items()}


# ---------------------------------------------------------------------------
# Task runner
# ---------------------------------------------------------------------------

def _run_task(task_id: int, task_def: dict) -> None:
    """Execute the script defined for *task_id*."""
    script: Optional[str] = task_def.get("script")
    if not script:
        log.warning("Task %d has no 'script' defined — skipping.", task_id)
        return

    extra_args: list = task_def.get("args", []) or []
    extra_env: dict = task_def.get("env", {}) or {}

    # Build command list
    cmd = shlex.split(script) + [str(a) for a in extra_args]

    # Merge current environment with any task-specific overrides
    env = {**os.environ, **{str(k): str(v) for k, v in extra_env.items()}}

    log.info("Task %d  → running: %s", task_id, " ".join(cmd))
    try:
        result = subprocess.run(cmd, env=env, check=False)
        if result.returncode == 0:
            log.info("Task %d  ✓ finished (exit 0).", task_id)
        else:
            log.warning("Task %d  ✗ exited with code %d.", task_id, result.returncode)
    except FileNotFoundError:
        log.error("Task %d  script not found: %s", task_id, cmd[0])
    except Exception as exc:  # noqa: BLE001
        log.error("Task %d  unexpected error: %s", task_id, exc)


def schedule_entry(entry: TaskEntry, task_map: Dict[int, dict]) -> None:
    """
    Schedule *entry* to run at entry.execute_at_dt.

    Uses a threading.Timer so the main receive loop is never blocked.
    Tasks that are already in the past are skipped with a warning.
    Tasks whose ID is not in task_map are skipped with a warning.
    """
    now = datetime.datetime.now(datetime.timezone.utc)
    delay = (entry.execute_at_dt - now).total_seconds()

    if delay < 0:
        log.warning(
            "Task %d was scheduled for the past (%s) — skipping.",
            entry.task_id,
            entry.execute_at,
        )
        return

    task_def = task_map.get(entry.task_id)
    if task_def is None:
        log.warning(
            "Task %d has no entry in task_config — skipping.",
            entry.task_id,
        )
        return

    log.info(
        "Scheduled task %d ('%s') to run in %.1f s (at %s).",
        entry.task_id,
        task_def.get("name", ""),
        delay,
        entry.execute_at,
    )

    t = threading.Timer(delay, _run_task, args=(entry.task_id, task_def))
    t.daemon = True
    t.start()


# ---------------------------------------------------------------------------
# Subscriber
# ---------------------------------------------------------------------------

class Subscriber:
    def __init__(self, config: dict):
        sub_cfg = config.get("subscriber", {})
        self.address: str = sub_cfg.get("address", "tcp://localhost:5555")
        self.topic: str = sub_cfg.get("topic", "tasks")
        self.task_map: Dict[int, dict] = parse_task_map(config)

        self._ctx = zmq.Context()
        self._sock = self._ctx.socket(zmq.SUB)

    def start(self) -> None:
        self._sock.connect(self.address)
        self._sock.setsockopt_string(zmq.SUBSCRIBE, self.topic)
        log.info("Connected to %s subscribing to topic %r", self.address, self.topic)
        log.info(
            "Registered tasks: %s",
            ", ".join(str(k) for k in sorted(self.task_map)) or "(none)",
        )

        try:
            self._receive_loop()
        except KeyboardInterrupt:
            log.info("Interrupted — shutting down.")
        finally:
            self.stop()

    def _receive_loop(self) -> None:
        while True:
            # Blocking receive — will wait until a message arrives.
            parts = self._sock.recv_multipart()

            if len(parts) < 2:
                log.warning("Received malformed message (expected 2 frames), ignoring.")
                continue

            _topic_frame, payload_frame = parts[0], parts[1]

            try:
                msg = TaskScheduleMessage.from_json(payload_frame.decode())
            except Exception as exc:  # noqa: BLE001
                log.error("Failed to parse message: %s", exc)
                continue

            log.info(
                "Received message %s with %d task(s) published at %s.",
                msg.message_id,
                len(msg.tasks),
                msg.publish_time,
            )

            for entry in msg.tasks:
                schedule_entry(entry, self.task_map)

    def stop(self) -> None:
        self._sock.close()
        self._ctx.term()
        log.info("Subscriber shut down.")


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="tasker-talker subscriber")
    parser.add_argument(
        "--config",
        default=str(Path(__file__).parent / "task_config.yaml"),
        help="Path to the task config YAML (default: task_config.yaml)",
    )
    args = parser.parse_args()

    config = load_config(args.config)
    Subscriber(config).start()


if __name__ == "__main__":
    main()
