#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
One-time Mattermost setup, automated as far as the server allows.

Run on the machine that will hold the token:

    python3 tools/mm_setup.py

It asks for two things and does the rest:
  1. the URL of the group meeting channel (copy it from the browser address bar)
  2. your personal access token (typed hidden; used for setup, never printed)

What it does with your personal token:
  - finds the team and the group meeting channel
  - creates a private test channel (or reuses it)
  - tries to create the bot account; if the server only lets admins do that, it writes a
    ready-to-send request for the admin and stops there. Run it again once the bot exists.
  - adds the bot to the team, the group meeting channel and the test channel
  - creates the bot's access token and saves it straight to a chmod 600 file
  - writes config.toml

Nothing here posts a message. Tokens are written to files only and never shown.
Safe to re-run: every step checks what already exists.
"""

from __future__ import annotations

import argparse
import getpass
import os
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote, urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from mattermost import MattermostClient, MattermostError  # noqa: E402

# Sent to a Chinese-speaking admin, so the template is in Traditional Chinese.
ADMIN_REQUEST_TEMPLATE = """您好，想請您協助開一個 Mattermost Bot 帳號，用在 group meeting 的簡報自動摘要：

1. 建立 Bot 帳號，使用者名稱：{bot}（角色用一般成員即可，不需要系統管理員權限）
2. 把 Bot 加進團隊「{team}」
3. 產生這個 Bot 的 access token，私下傳給我（請不要貼在公開頻道）

Bot 只會被加進 group meeting 頻道和一個私人測試頻道，這兩步我這邊可以自己處理。
用途是每週三讀取頻道裡的簡報連結，並把摘要回覆在討論串。試跑期間只會發到測試頻道。

謝謝！
"""


def parse_channel_url(url: str) -> Tuple[str, str, str]:
    """https://host[/subpath]/<team>/channels/<channel> -> (base_url, team, channel)."""
    parsed = urlparse(url.strip())
    parts = [p for p in parsed.path.split("/") if p]
    if not parsed.scheme or not parsed.netloc or "channels" not in parts:
        raise ValueError("That does not look like a channel URL (expected .../<team>/channels/<channel>).")
    idx = parts.index("channels")
    if idx < 1 or idx + 1 >= len(parts):
        raise ValueError("Could not find the team and channel names in the URL.")
    base = f"{parsed.scheme}://{parsed.netloc}"
    if idx > 1:
        base += "/" + "/".join(parts[: idx - 1])
    return base, parts[idx - 1], parts[idx + 1]


def write_secret(path: Path, value: str) -> None:
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(value.strip() + "\n")
    os.chmod(path, 0o600)


def say(status: str, text: str) -> None:
    print(f"[{status:^11}] {text}")


class Setup:
    def __init__(self, mm: MattermostClient, config_dir: Path, bot_username: str, test_channel_name: str):
        self.mm = mm
        self.dir = config_dir
        self.bot_username = bot_username
        self.test_channel_name = test_channel_name
        self.todo: List[str] = []

    def call(self, method: str, path: str, body: Any = None) -> Any:
        return self.mm._request(method, path, json_body=body)

    def get_or_none(self, path: str) -> Optional[Dict[str, Any]]:
        try:
            return self.call("GET", path)
        except MattermostError as exc:
            if exc.status == 404:
                return None
            raise

    # ---------- steps ----------
    def test_channel(self, team_id: str) -> Dict[str, Any]:
        name = quote(self.test_channel_name)
        found = self.get_or_none(f"/teams/{team_id}/channels/name/{name}")
        if found:
            say("ok", f"Test channel ~{self.test_channel_name} already exists.")
            return found
        created = self.call("POST", "/channels", {
            "team_id": team_id, "name": self.test_channel_name, "type": "P",
            "display_name": "Slide summary test",
            "purpose": "Trial output of the slide summary agent",
        })
        say("done", f"Created private test channel ~{self.test_channel_name}.")
        return created

    def bot(self, team_name: str) -> Optional[str]:
        """Return the bot's user id, or None if an admin has to create it."""
        existing = self.get_or_none(f"/users/username/{quote(self.bot_username)}")
        if existing:
            if not existing.get("is_bot"):
                say("stop", f"@{self.bot_username} exists but is not a bot account. Pick another --bot-username.")
                sys.exit(1)
            say("ok", f"Bot @{self.bot_username} already exists.")
            return existing["id"]
        try:
            created = self.call("POST", "/bots", {
                "username": self.bot_username, "display_name": "簡報摘要小幫手",
                "description": "Group meeting slide summaries",
            })
            say("done", f"Created bot @{self.bot_username}.")
            return created["user_id"]
        except MattermostError as exc:
            request = self.dir / "admin_request.txt"
            request.write_text(ADMIN_REQUEST_TEMPLATE.format(bot=self.bot_username, team=team_name), encoding="utf-8")
            say("needs admin", f"This server does not let you create bots (status {exc.status}, {exc.code}).")
            self.todo.append(
                f"Send the message in {request} to your Mattermost admin. When you get the bot token, save it "
                f"with:  nano {self.dir / 'mm_token'} && chmod 600 {self.dir / 'mm_token'}   then run this script again."
            )
            return None

    def add_member(self, path: str, body: Dict[str, str], label: str) -> None:
        try:
            self.call("POST", path, body)
            say("done", f"Added the bot to {label}.")
        except MattermostError as exc:
            # Mattermost returns an error or the existing membership when already a member, depending on version.
            if "exists" in exc.code or "already" in exc.code:
                say("ok", f"Bot is already in {label}.")
            else:
                say("problem", f"Could not add the bot to {label} (status {exc.status}, {exc.code}).")
                self.todo.append(f"Add @{self.bot_username} to {label} by hand (or ask the admin).")

    def bot_token(self, bot_id: str) -> None:
        path = self.dir / "mm_token"
        if path.exists() and path.read_text(encoding="utf-8").strip():
            os.chmod(path, 0o600)
            say("ok", f"Bot token file already present at {path}.")
            return
        try:
            created = self.call("POST", f"/users/{bot_id}/tokens", {"description": "slide summary agent"})
            write_secret(path, created["token"])
            say("done", f"Created the bot's access token and saved it to {path} (chmod 600).")
        except MattermostError as exc:
            say("needs admin", f"Could not create a token for the bot (status {exc.status}, {exc.code}).")
            self.todo.append(
                f"Ask whoever created @{self.bot_username} for its access token and save it with:  "
                f"nano {path} && chmod 600 {path}   then run this script again."
            )

    def write_config(self, base_url: str, main_id: str, test_id: str, maintainer: str, token_file: Path, force: bool) -> None:
        path = self.dir / "config.toml"
        claude_bin = shutil.which("claude") or "claude"
        text = f'''# Written by tools/mm_setup.py. Safe to edit by hand.

[mattermost]
base_url = "{base_url}"
channel_id = "{main_id}"
token_file = "{token_file}"
maintainer_username = "{maintainer}"
reply_mode = "test_channel"
test_channel_id = "{test_id}"

[llm]
claude_bin = "{claude_bin}"
isolation_user = ""
allow_direct = true

[paths]
db_path = "{self.dir / 'state.sqlite3'}"
exchange_root = "/var/tmp"
'''
        if path.exists() and not force:
            current = path.read_text(encoding="utf-8")
            wanted = f'token_file = "{token_file}"'
            if wanted in current:
                say("ok", f"{path} already exists; left as is.")
            else:
                (self.dir / "config.generated.toml").write_text(text, encoding="utf-8")
                os.chmod(self.dir / "config.generated.toml", 0o600)
                say("ok", f"{path} already exists; left as is. A fresh version is in config.generated.toml.")
                self.todo.append(
                    f"Your existing config.toml points at a different token file. To switch to the bot token, "
                    f"run this script again with --force (or copy config.generated.toml over config.toml)."
                )
            return
        path.write_text(text, encoding="utf-8")
        os.chmod(path, 0o600)
        say("done", f"Wrote {path}.")


def main() -> None:
    parser = argparse.ArgumentParser(description="One-time Mattermost setup for the slide summary agent")
    parser.add_argument("--channel-url", default="", help="URL of the group meeting channel")
    parser.add_argument("--config-dir", default="~/.config/lab-summarizer")
    parser.add_argument("--bot-username", default="slide-summary-bot")
    parser.add_argument("--test-channel-name", default="slide-summary-test")
    parser.add_argument("--force", action="store_true", help="overwrite an existing config.toml")
    args = parser.parse_args()

    config_dir = Path(args.config_dir).expanduser()
    config_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(config_dir, 0o700)

    url = args.channel_url or input("Paste the URL of the group meeting channel: ")
    try:
        base_url, team_name, channel_name = parse_channel_url(url)
    except ValueError as exc:
        sys.exit(str(exc))

    personal_file = config_dir / "mm_token_personal"
    token = os.environ.pop("MM_SETUP_TOKEN", "").strip()
    if not token and personal_file.exists():
        token = personal_file.read_text(encoding="utf-8").strip()
    if not token:
        token = getpass.getpass("Your Mattermost personal access token (input is hidden): ").strip()
    if not token:
        sys.exit("No token given.")

    mm = MattermostClient(base_url, token)
    setup = Setup(mm, config_dir, args.bot_username, args.test_channel_name)

    try:
        me = mm.me()
        say("ok", f"Signed in as @{me['username']}.")
        write_secret(personal_file, token)

        team = setup.call("GET", f"/teams/name/{quote(team_name)}")
        main_channel = setup.call("GET", f"/teams/{team['id']}/channels/name/{quote(channel_name)}")
        say("ok", f"Found team {team_name} and channel ~{channel_name}.")

        test_channel = setup.test_channel(team["id"])
        bot_id = setup.bot(team_name)

        if bot_id:
            setup.add_member(f"/teams/{team['id']}/members", {"team_id": team["id"], "user_id": bot_id}, f"team {team_name}")
            setup.add_member(f"/channels/{main_channel['id']}/members", {"user_id": bot_id}, f"~{channel_name}")
            setup.add_member(f"/channels/{test_channel['id']}/members", {"user_id": bot_id}, f"~{args.test_channel_name}")
            setup.bot_token(bot_id)

        bot_token_file = config_dir / "mm_token"
        have_bot_token = bot_token_file.exists() and bool(bot_token_file.read_text(encoding="utf-8").strip())
        setup.write_config(
            base_url, main_channel["id"], test_channel["id"], me["username"],
            bot_token_file if have_bot_token else personal_file, args.force,
        )
    except MattermostError as exc:
        hint = {
            0: "the server could not be reached (are you on the lab network or VPN?)",
            401: "the token was rejected (expired or mistyped)",
            403: "your account is not allowed to do this",
            404: "the team or channel was not found (check the URL)",
        }.get(exc.status, "unexpected response")
        say("stop", f"Mattermost said status {exc.status}, {exc.code}: {hint}.")
        sys.exit(1)

    print()
    if not have_bot_token:
        print("For now the config uses YOUR personal token. That is fine for read-only dry runs;")
        print("note the agent skips posts written by the token's owner, so your own posts will not show up.")
    if setup.todo:
        print("\nLeft for you to do:")
        for i, item in enumerate(setup.todo, 1):
            print(f"  {i}. {item}")
    else:
        print("Setup is complete.")
    print("\nNext, check that everything works (posts nothing, prints nothing secret):")
    print(f"  python3 tools/live_check.py --config {config_dir / 'config.toml'} --mode dryrun-fake --since-hours 1440 --result -")


if __name__ == "__main__":
    main()
