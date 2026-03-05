# tasker-talker

A lightweight ZMQ-based task coordinator.  
A single **publisher** broadcasts a time-stamped execution schedule; any number of **subscribers** running on different machines listen for it and launch their locally-configured scripts at the instructed times.

---

## Project structure

```
tasker-talker/
├── common/
│   ├── __init__.py
│   └── message.py          # Shared message schema (TaskScheduleMessage)
│
├── publisher/
│   ├── __init__.py
│   ├── publisher.py        # ZMQ publisher entrypoint
│   └── message_config.yaml # Publisher configuration
│
├── subscriber/
│   ├── __init__.py
│   ├── subscriber.py       # ZMQ subscriber entrypoint
│   └── task_config.yaml    # Subscriber / task configuration
│
├── scripts/                # Example scripts invoked by the subscriber
│   ├── task1.sh
│   ├── task2.sh
│   ├── task3.py
│   └── task4.sh
│
├── requirements.txt
├── .gitignore
└── README.md
```

---

## How it works

```
Publisher                            Subscriber(s)
─────────────────                    ─────────────────────────────────
reads message_config.yaml            reads task_config.yaml
builds TaskScheduleMessage           connects to publisher address
  task 1 → T₀                        subscribes to topic
  task 2 → T₀ + I
  task 3 → T₀ + 2I        ──────►   receives message
  …                                  for each task entry:
publishes over ZMQ PUB                 schedules threading.Timer
                                       timer fires → runs script
```

1. The **publisher** reads `message_config.yaml`, calculates a set of UTC execution timestamps, and publishes a single JSON message over a ZMQ PUB socket.
2. Every **subscriber** (one per machine) receives that message and, for each task entry, starts a `threading.Timer` set to fire at `execute_at`.  When the timer fires, the script mapped to that task ID is invoked via `subprocess`.
3. Because all machines receive the **same absolute timestamps**, their tasks fire in a coordinated, wall-clock-synchronised manner (requires NTP/clock sync on all machines).

---

## Requirements

- Python ≥ 3.9
- `pyzmq` and `PyYAML` (see `requirements.txt`)

```bash
pip install -r requirements.txt
```

---

## Quick-start (single machine)

### 1 – Make example scripts executable

```bash
chmod +x scripts/*.sh
```

### 2 – Start the subscriber (terminal 1)

```bash
python subscriber/subscriber.py --config subscriber/task_config.yaml
```

### 3 – Start the publisher (terminal 2)

```bash
python publisher/publisher.py --config publisher/message_config.yaml
```

The subscriber will receive the schedule and start printing output from each script as their timers fire.

---

## Multi-machine setup

| Machine | Role | Command |
|---------|------|---------|
| `machine-A` (controller) | publisher | `python publisher/publisher.py` |
| `machine-B` | subscriber | `python subscriber/subscriber.py` |
| `machine-C` | subscriber | `python subscriber/subscriber.py` (its own `task_config.yaml`) |

Each subscriber machine needs its own `task_config.yaml`.  They can map the **same task IDs to different scripts**, or only register a subset of task IDs — tasks with no local mapping are silently skipped.

Update the subscriber `address` in each `task_config.yaml` to point at the publisher machine, e.g.:

```yaml
subscriber:
  address: "tcp://192.168.1.100:5555"
  topic: "tasks"
```

Update the publisher `address` to bind on the correct interface:

```yaml
publisher:
  address: "tcp://*:5555"   # binds all interfaces
```

> **Clock synchronisation** — all machines must have their clocks in sync (NTP) for scheduled tasks to fire at the right wall-clock time.

---

## Configuration reference

### `publisher/message_config.yaml`

| Key | Type | Description |
|-----|------|-------------|
| `publisher.address` | string | ZMQ bind address, e.g. `tcp://*:5555` |
| `publisher.topic` | string | Topic prefix for all messages |
| `schedule.start_time` | ISO 8601 string \| null | Absolute UTC start time for task 1.  If null, uses `now + start_delay_seconds` |
| `schedule.start_delay_seconds` | float | Seconds from now until task 1 fires (when `start_time` is null) |
| `schedule.interval_seconds` | float | Seconds between consecutive task execution times |
| `schedule.tasks` | list of `{id: int}` | Explicit ordered list of task IDs to schedule |
| `schedule.num_tasks` | int | Auto-generate IDs 1…N (used only when `tasks` is absent) |
| `schedule.repeat` | bool | Re-publish on a fixed cadence |
| `schedule.repeat_seconds` | float | Cadence for repeat publishing |

### `subscriber/task_config.yaml`

| Key | Type | Description |
|-----|------|-------------|
| `subscriber.address` | string | Publisher address to connect to |
| `subscriber.topic` | string | Must match publisher topic |
| `tasks.<id>.name` | string | Human-readable label |
| `tasks.<id>.script` | string | Command or path to execute (shell-split) |
| `tasks.<id>.args` | list | Additional CLI arguments appended to the command |
| `tasks.<id>.env` | mapping | Extra environment variables injected at runtime |

---

## Message format

Messages are sent as ZMQ multipart frames: `[topic, json_payload]`.

```json
{
  "message_id": "d4f1e2a3-...",
  "publish_time": "2026-03-05T10:00:00+00:00",
  "topic": "tasks",
  "tasks": [
    { "task_id": 1, "execute_at": "2026-03-05T10:00:10+00:00" },
    { "task_id": 2, "execute_at": "2026-03-05T10:00:40+00:00" },
    { "task_id": 3, "execute_at": "2026-03-05T10:01:10+00:00" }
  ]
}
```

---

## License

MIT
