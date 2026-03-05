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
├── deploy/                 # Auto-update & deployment helpers
│   ├── auto_update.sh                    # git pull + optional service restart
│   ├── webhook_server.py                 # GitHub webhook listener (stdlib only)
│   ├── tasker-talker-subscriber.service  # systemd unit for the subscriber
│   └── tasker-talker-webhook.service     # systemd unit for the webhook server
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

## Auto-update on push

Neither Git nor ZMQ polls GitHub automatically — you need to add that yourself.
Two approaches are included; pick one (or use both on different machines).

### Option A — Cron polling (simplest)

Adds a cron job that runs `deploy/auto_update.sh` on a schedule.  The script
does a fast `git fetch` and only pulls + restarts when new commits exist.

```bash
# Make the script executable
chmod +x deploy/auto_update.sh

# Open your crontab
crontab -e
```

Add a line like this (polls every 5 minutes):

```cron
*/5 * * * * /home/<you>/tasker-talker/deploy/auto_update.sh >> /var/log/tasker-talker-update.log 2>&1
```

The script accepts optional flags:

| Flag | Default | Description |
|------|---------|-------------|
| `--repo-dir <path>` | parent of the script | Path to the cloned repo |
| `--service <name>` | `tasker-talker-subscriber` | systemd service to restart |
| `--no-restart` | — | Skip the service restart |

---

### Option B — GitHub webhook (instant)

GitHub POSTs a JSON payload to your machine whenever you push.  A small
stdlib-only Python server (`deploy/webhook_server.py`) receives it, verifies
the HMAC signature, and calls `auto_update.sh`.

#### 1 – Run the webhook server

```bash
export WEBHOOK_SECRET=your_secret_here
python deploy/webhook_server.py --port 9000 --branch main
```

Or run it as a systemd service (recommended — edit the placeholders first):

```bash
sudo cp deploy/tasker-talker-webhook.service /etc/systemd/system/
# edit /etc/systemd/system/tasker-talker-webhook.service — replace <your-username>
echo 'WEBHOOK_SECRET=your_secret_here' | sudo tee /etc/tasker-talker.env
sudo chmod 600 /etc/tasker-talker.env
sudo systemctl daemon-reload
sudo systemctl enable --now tasker-talker-webhook
```

#### 2 – Configure the webhook on GitHub

1. Go to your repository → **Settings → Webhooks → Add webhook**.
2. Set **Payload URL** to `http://<your-machine-ip>:9000/webhook`.
3. Set **Content type** to `application/json`.
4. Set **Secret** to the same value as `WEBHOOK_SECRET`.
5. Choose **Just the push event** and save.

> **Firewall** — port 9000 (or whichever you choose) must be reachable from
> GitHub's IP ranges.  If your machine is behind NAT, use a reverse proxy
> (nginx, Caddy) or a tunnel (ngrok, Cloudflare Tunnel).

---

### Running the subscriber as a systemd service

Both auto-update methods optionally restart the subscriber service.  Install
it so systemd manages it:

```bash
sudo cp deploy/tasker-talker-subscriber.service /etc/systemd/system/
# edit the file — replace <your-username> and adjust the Python path
sudo systemctl daemon-reload
sudo systemctl enable --now tasker-talker-subscriber
```

Useful commands:

```bash
sudo systemctl status tasker-talker-subscriber
journalctl -u tasker-talker-subscriber -f   # live logs
sudo systemctl restart tasker-talker-subscriber
```

---

## License

MIT
