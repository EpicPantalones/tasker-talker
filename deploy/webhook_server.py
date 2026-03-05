"""
deploy/webhook_server.py
========================
A minimal HTTP server that listens for GitHub push webhook events and triggers
a `git pull` (and optional service restart) when a push hits the configured
branch.

No external dependencies — uses only the Python standard library.

Usage
-----
    python deploy/webhook_server.py [--port 9000] [--secret <your_webhook_secret>]
                                    [--branch main] [--service tasker-talker-subscriber]

GitHub configuration
--------------------
In your GitHub repository → Settings → Webhooks → Add webhook:
  Payload URL : http://<your-machine-ip>:<port>/webhook
  Content type: application/json
  Secret      : <same value you pass to --secret>
  Events      : Just the push event

Security note
-------------
Always set a webhook secret so this server can verify that requests genuinely
come from GitHub.  Without one, anyone who can reach the port can trigger a
git pull + service restart.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import http.server
import json
import logging
import os
import subprocess
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [webhook] %(levelname)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger(__name__)

# Repository root is one level above this file.
REPO_DIR = str(Path(__file__).resolve().parent.parent)


# ---------------------------------------------------------------------------
# Request handler
# ---------------------------------------------------------------------------

class WebhookHandler(http.server.BaseHTTPRequestHandler):
    """Handles incoming GitHub webhook POST requests."""

    # These are injected by the factory below.
    secret: bytes = b""
    branch: str = "main"
    service: str = ""

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            self._respond(200, {"status": "ok"})
        else:
            self._respond(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/webhook":
            self._respond(404, {"error": "not found"})
            return

        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)

        # --- verify signature ------------------------------------------------
        if self.secret:
            sig_header = self.headers.get("X-Hub-Signature-256", "")
            if not self._verify_signature(body, sig_header):
                log.warning("Signature verification failed — ignoring request.")
                self._respond(403, {"error": "invalid signature"})
                return

        # --- parse event -----------------------------------------------------
        event = self.headers.get("X-GitHub-Event", "")
        if event != "push":
            log.info("Ignoring non-push event: %r", event)
            self._respond(200, {"status": "ignored", "event": event})
            return

        try:
            payload = json.loads(body)
        except json.JSONDecodeError as exc:
            log.error("Failed to parse payload: %s", exc)
            self._respond(400, {"error": "bad json"})
            return

        pushed_ref = payload.get("ref", "")
        target_ref = f"refs/heads/{self.branch}"

        if pushed_ref != target_ref:
            log.info("Push to %r — not target branch (%r), skipping.", pushed_ref, target_ref)
            self._respond(200, {"status": "ignored", "ref": pushed_ref})
            return

        pusher = payload.get("pusher", {}).get("name", "unknown")
        head = payload.get("after", "")[:7]
        log.info("Push event from %s — new HEAD %s — triggering update.", pusher, head)

        self._respond(200, {"status": "accepted"})

        # Run the update script in a subprocess (non-blocking from handler).
        update_script = str(Path(REPO_DIR) / "deploy" / "auto_update.sh")
        cmd = ["bash", update_script, "--repo-dir", REPO_DIR]
        if self.service:
            cmd += ["--service", self.service]
        else:
            cmd += ["--no-restart"]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            for line in result.stdout.splitlines():
                log.info("update: %s", line)
            if result.returncode != 0:
                log.error("Update script failed (exit %d): %s", result.returncode, result.stderr)
        except subprocess.TimeoutExpired:
            log.error("Update script timed out.")

    # --- helpers -------------------------------------------------------------

    def _verify_signature(self, body: bytes, header: str) -> bool:
        expected = "sha256=" + hmac.new(self.secret, body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, header)

    def _respond(self, code: int, data: dict) -> None:
        payload = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt: str, *args: object) -> None:  # suppress default access log
        log.debug(fmt, *args)


def make_handler(secret: str, branch: str, service: str) -> type:
    """Factory that injects config into the handler class."""

    class ConfiguredHandler(WebhookHandler):
        pass

    ConfiguredHandler.secret = secret.encode() if secret else b""
    ConfiguredHandler.branch = branch
    ConfiguredHandler.service = service
    return ConfiguredHandler


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="tasker-talker GitHub webhook server")
    parser.add_argument("--port",    type=int, default=9000,  help="Port to listen on (default: 9000)")
    parser.add_argument("--secret",  default=os.environ.get("WEBHOOK_SECRET", ""),
                        help="GitHub webhook secret (or set WEBHOOK_SECRET env var)")
    parser.add_argument("--branch",  default="main",          help="Branch that triggers an update (default: main)")
    parser.add_argument("--service", default="tasker-talker-subscriber",
                        help="systemd service to restart after pull (empty = no restart)")
    args = parser.parse_args()

    if not args.secret:
        log.warning("No webhook secret configured — requests will NOT be verified!")

    handler_cls = make_handler(args.secret, args.branch, args.service)
    server = http.server.HTTPServer(("", args.port), handler_cls)
    log.info("Webhook server listening on port %d (branch=%r)", args.port, args.branch)
    log.info("Configure GitHub: Payload URL → http://<this-machine>:%d/webhook", args.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("Shutdown.")


if __name__ == "__main__":
    main()
