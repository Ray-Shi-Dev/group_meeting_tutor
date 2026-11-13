#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests for tools/mm_setup.py against a fake Mattermost server. All data is synthetic.

    python3 tests/test_mm_setup.py
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import mm_setup  # noqa: E402

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore[no-redef]

PERSONAL = "personal-secret-token"
BOT_TOKEN = "bot-secret-token"


class Fake:
    def __init__(self, allow_bots: bool):
        self.allow_bots = allow_bots
        self.users = {"alice": {"id": "u_alice", "username": "alice", "is_bot": False}}
        self.channels = {"group-meeting": {"id": "ch_main", "name": "group-meeting"}}
        self.members: set = set()
        self.posts = 0


def handler(fake: Fake):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def out(self, obj, status=200):
            body = json.dumps(obj).encode()
            self.send_response(status)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def auth(self) -> bool:
            if self.headers.get("Authorization") != f"Bearer {PERSONAL}":
                self.out({"id": "api.context.session_expired.app_error"}, 401)
                return False
            return True

        def do_GET(self):
            if not self.auth():
                return
            p = self.path
            if p == "/api/v4/users/me":
                return self.out(fake.users["alice"])
            if p == "/api/v4/teams/name/lab":
                return self.out({"id": "team1", "name": "lab"})
            m = re.match(r"/api/v4/teams/team1/channels/name/([\w-]+)$", p)
            if m:
                ch = fake.channels.get(m.group(1))
                return self.out(ch) if ch else self.out({"id": "app.channel.get_by_name.missing.app_error"}, 404)
            m = re.match(r"/api/v4/users/username/([\w-]+)$", p)
            if m:
                u = fake.users.get(m.group(1))
                return self.out(u) if u else self.out({"id": "app.user.get_by_username.app_error"}, 404)
            self.out({"id": "not_found"}, 404)

        def do_POST(self):
            if not self.auth():
                return
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            p = self.path
            if p == "/api/v4/posts":
                fake.posts += 1
                return self.out({"id": "x"}, 201)
            if p == "/api/v4/channels":
                ch = {"id": "ch_test", "name": body["name"], "type": body["type"]}
                fake.channels[body["name"]] = ch
                return self.out(ch, 201)
            if p == "/api/v4/bots":
                if not fake.allow_bots:
                    return self.out({"id": "api.context.permissions.app_error"}, 403)
                fake.users[body["username"]] = {"id": "u_bot", "username": body["username"], "is_bot": True}
                return self.out({"user_id": "u_bot", "username": body["username"]}, 201)
            m = re.match(r"/api/v4/(teams|channels)/(\w+)/members$", p)
            if m:
                key = (m.group(2), body["user_id"])
                if key in fake.members:
                    return self.out({"id": "app.channel.add_member.exists.app_error"}, 400)
                fake.members.add(key)
                return self.out({"user_id": body["user_id"]}, 201)
            if p == "/api/v4/users/u_bot/tokens":
                if not fake.allow_bots:
                    return self.out({"id": "api.context.permissions.app_error"}, 403)
                return self.out({"id": "tok1", "token": BOT_TOKEN}, 201)
            self.out({"id": "not_found"}, 404)

    return H


def run(base: str, cfg_dir: Path, *extra: str) -> str:
    env = dict(os.environ, MM_SETUP_TOKEN=PERSONAL)
    proc = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "mm_setup.py"), "--channel-url", f"{base}/lab/channels/group-meeting",
         "--config-dir", str(cfg_dir), *extra],
        capture_output=True, text=True, env=env, timeout=60,
    )
    out = proc.stdout + proc.stderr
    assert PERSONAL not in out and BOT_TOKEN not in out, "a token was printed"
    assert proc.returncode == 0, out
    return out


def load(cfg_dir: Path) -> dict:
    with open(cfg_dir / "config.toml", "rb") as fh:
        raw = tomllib.load(fh)
    flat: dict = {}
    for section in raw.values():
        flat.update(section)
    return flat


def serve(fake: Fake):
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler(fake))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_port}"


def test() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="mm_setup_test_"))

    # URL parsing
    assert mm_setup.parse_channel_url("https://mm.example.edu/lab/channels/group-meeting") == (
        "https://mm.example.edu", "lab", "group-meeting")
    assert mm_setup.parse_channel_url("https://example.edu/chat/lab/channels/gm/")[0] == "https://example.edu/chat"
    for bad in ("not a url", "https://mm.example.edu/lab/messages/@bob"):
        try:
            mm_setup.parse_channel_url(bad)
            raise AssertionError("should have been rejected")
        except ValueError:
            pass
    print("1 url parsing ok")

    # A) server lets the user create bots: everything is automatic
    fake = Fake(allow_bots=True)
    server, base = serve(fake)
    d = tmp / "a"
    out = run(base, d)
    cfg = load(d)
    assert cfg["channel_id"] == "ch_main" and cfg["test_channel_id"] == "ch_test"
    assert cfg["reply_mode"] == "test_channel" and cfg["maintainer_username"] == "alice"
    assert cfg["token_file"] == str(d / "mm_token")
    assert (d / "mm_token").read_text().strip() == BOT_TOKEN
    for name in ("mm_token", "mm_token_personal", "config.toml"):
        assert (d / name).stat().st_mode & 0o077 == 0, name
    assert fake.members == {("team1", "u_bot"), ("ch_main", "u_bot"), ("ch_test", "u_bot")}
    assert "Setup is complete" in out and fake.posts == 0
    print("2 fully automatic path ok")

    out = run(base, d)  # idempotent
    assert "already exists" in out and "Setup is complete" in out and fake.posts == 0
    print("3 re-run is idempotent ok")
    server.shutdown()

    # B) only admins can create bots
    fake = Fake(allow_bots=False)
    server, base = serve(fake)
    d = tmp / "b"
    out = run(base, d)
    cfg = load(d)
    assert "needs admin" in out and (d / "admin_request.txt").exists()
    assert "slide-summary-bot" in (d / "admin_request.txt").read_text(encoding="utf-8")
    assert cfg["token_file"] == str(d / "mm_token_personal") and not (d / "mm_token").exists()
    assert cfg["test_channel_id"] == "ch_test" and not fake.members
    print("4 needs-admin path ok")

    # ...the admin creates the bot and hands over its token; the user saves it and re-runs
    fake.users["slide-summary-bot"] = {"id": "u_bot", "username": "slide-summary-bot", "is_bot": True}
    mm_setup.write_secret(d / "mm_token", BOT_TOKEN)
    out = run(base, d, "--force")
    cfg = load(d)
    assert cfg["token_file"] == str(d / "mm_token")
    assert fake.members == {("team1", "u_bot"), ("ch_main", "u_bot"), ("ch_test", "u_bot")}
    assert "Setup is complete" in out and fake.posts == 0
    print("5 after-admin re-run ok")
    server.shutdown()

    shutil.rmtree(tmp, ignore_errors=True)
    print("ALL PASS")


if __name__ == "__main__":
    test()
