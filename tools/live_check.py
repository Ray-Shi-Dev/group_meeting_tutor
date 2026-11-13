#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Live environment check: run main.py on the machine that holds the token and produce a content-free report.

The report contains only: environment checks, non-secret config fields, status codes, post ids,
page counts, character counts and timings. It never contains the token, URLs, channel ids,
account names, slide content or summary content.

    python3 tools/live_check.py --config ~/.config/lab-summarizer/config.toml --mode dryrun-fake --result -

Modes:
        dryrun-fake    no posting, no model calls: tests Mattermost reads, deck export and rendering
        dryrun-real    no posting, real model: summaries stay in the --out directory for a human to read
        test-channel   real model, posts to the test channel only (forced; never the real channel)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import tomllib
except ModuleNotFoundError:
    try:
        import tomli as tomllib  # type: ignore[no-redef]
    except ModuleNotFoundError:
        tomllib = None  # type: ignore[assignment]

ROOT = Path(__file__).resolve().parent.parent
MODES = ("dryrun-fake", "dryrun-real", "test-channel")

# Only log lines carrying one of these event codes reach the report; everything else (tracebacks too) is dropped.
EVENT_RE = re.compile(
    r"\b(WINDOW|SUMMARY_OK|VALIDATION_RETRY|RESCUED_CANDIDATE|ACCEPTED_NEAREST|JSON_PARSE_FAIL|"
    r"PROVIDER_FALLBACK|DECK_FETCH_FAIL|DECK_TIMING|RUN_DONE|CLAUDE_CLI_NONZERO|SUSPECTED_INJECTION|"
    r"DELIVER_FAIL|SANDBOX_CONFIG_ERROR|CONFIG_ERROR|ALREADY_RUNNING|REPORT_DM_FAIL|MATTERMOST_ERROR)\b"
)
EXC_RE = re.compile(r"^([A-Za-z_][\w.]*(?:Error|Exception|Exit))\b:?\s*(.*)$")
SAFE_EXC_DETAIL_RE = re.compile(r"^mattermost status=\d+ code=[\w.\-]+$")


def mask(text: str) -> str:
    """Mask URLs, home directory paths and long random strings. Post ids (26 chars) are kept for cross-reference."""
    text = re.sub(r"https?://\S+", "<url>", text)
    text = re.sub(r"/(?:home|Users)/[^/\s'\"`]+", "~", text)
    text = re.sub(r"(sk-[A-Za-z0-9\-_]+|eyJ[A-Za-z0-9\-_.]+|[A-Za-z0-9+/=_\-]{32,})", "<redacted>", text)
    return text


def which_any(names: Tuple[str, ...]) -> str:
    for name in names:
        if shutil.which(name):
            return name
    return ""


def preflight(config_path: Path) -> Tuple[List[str], Optional[Dict[str, Any]]]:
    lines = [f"- Python：{sys.version.split()[0]}"]
    for label, names in (
        ("poppler", ("pdftoppm",)), ("LibreOffice", ("soffice", "libreoffice")),
        ("Chromium", ("chromium", "chromium-browser", "google-chrome")),
    ):
        lines.append(f"- {label}: {'yes' if which_any(names) else 'no'}")
    lines.append(f"- TOML parser: {'yes' if tomllib else 'no (on Python 3.10: apt install python3-tomli)'}")

    if not config_path.exists():
        lines.append("- Config file: not found")
        return lines, None
    if tomllib is None:
        return lines, None
    try:
        with open(config_path, "rb") as fh:
            raw = tomllib.load(fh)
    except Exception as exc:
        lines.append(f"- Config file: cannot be parsed ({type(exc).__name__})")
        return lines, None

    flat: Dict[str, Any] = {}
    for section in raw.values():
        if isinstance(section, dict):
            flat.update(section)

    def filled(key: str) -> str:
        return "set" if str(flat.get(key, "")).strip() else "empty"

    lines.append("- Config file: parsed")
    lines.append(f"  - base_url {filled('base_url')}、channel_id {filled('channel_id')}、"
                 f"test_channel_id {filled('test_channel_id')}、maintainer_username {filled('maintainer_username')}")
    lines.append(f"  - reply_mode = {flat.get('reply_mode', 'test_channel')}")
    lines.append(f"  - isolation: isolation_user {filled('isolation_user')}, allow_direct = {bool(flat.get('allow_direct', False))}")
    lines.append(f"  - vision_timeout_sec = {flat.get('vision_timeout_sec', 420)}、"
                 f"enable_ollama_fallback = {bool(flat.get('enable_ollama_fallback', False))}、"
                 f"enable_html_attachments = {bool(flat.get('enable_html_attachments', False))}")

    token_file = str(flat.get("token_file", "")).strip()
    if os.environ.get("MM_BOT_TOKEN"):
        lines.append("- Token: provided by environment variable")
    elif not token_file:
        lines.append("- Token: token_file is empty and no environment variable is set")
    else:
        path = Path(token_file).expanduser()
        if not path.exists():
            lines.append("- Token file: not found")
        else:
            loose = bool(path.stat().st_mode & 0o077)
            lines.append(f"- Token file: present, permissions {'too open (run chmod 600)' if loose else 'ok'}")
    return lines, flat


def cli_smoke(flat: Dict[str, Any]) -> List[str]:
    """Check that the three Claude CLI flags behave the way the harness assumes (T3 in STATUS)."""
    claude_bin = str(flat.get("claude_bin", "claude"))
    user = str(flat.get("isolation_user", "")).strip()
    prefix = ["sudo", "-n", "-H", "-u", user, "--"] if user else []
    lines: List[str] = []

    def run(args: List[str], stdin: str, timeout: int) -> Tuple[int, str, str, float]:
        started = time.monotonic()
        try:
            proc = subprocess.run(
                prefix + [claude_bin] + args, input=stdin, text=True, capture_output=True,
                timeout=timeout, check=False, cwd="/tmp",
            )
            return proc.returncode, proc.stdout, proc.stderr, time.monotonic() - started
        except FileNotFoundError:
            return 127, "", "not found", 0.0
        except subprocess.TimeoutExpired:
            return 124, "", "timeout", time.monotonic() - started

    code, out, err, _ = run(["--version"], "", 30)
    version = mask(out.strip().splitlines()[0]) if code == 0 and out.strip() else "unavailable"
    lines.append(f"- `claude --version`：exit={code}，{version}")
    if code != 0:
        lines.append(f"  - stderr tail: {mask(' '.join(err.split())[-160:])}")
        return lines

    system = 'Output exactly this JSON and nothing else: {"ok": true}'
    for label, tool_args in (("--allowedTools Read", ["--allowedTools", "Read"]), ('--tools ""', ["--tools", ""])):
        code, out, err, secs = run(
            ["-p", "--system-prompt", system, *tool_args, "--output-format", "json"], "Output the JSON.", 180
        )
        detail = f"exit={code}, {secs:.0f}s"
        if code == 0:
            try:
                outer = json.loads(out)
                if isinstance(outer, dict):
                    keys = ",".join(sorted(map(str, outer.keys())))[:200]
                    result = outer.get("result")
                    inner_ok = False
                    if isinstance(result, str):
                        try:
                            start, end = result.find("{"), result.rfind("}")
                            inner_ok = json.loads(result[start : end + 1]).get("ok") is True
                        except Exception:
                            inner_ok = False
                    detail += (f", outer JSON object (keys: {keys}), result is a string: {isinstance(result, str)}, "
                                          f"inner JSON correct: {inner_ok}, is_error = {outer.get('is_error')}")
                else:
                    detail += f", outer JSON is not an object ({type(outer).__name__})"
            except json.JSONDecodeError:
                detail += f", output is not JSON (length {len(out)})"
        else:
            detail += f", stderr tail: {mask(' '.join(err.split())[-160:])}"
        lines.append(f"- `-p {label} --output-format json`：{detail}")
    return lines


def run_main(config_path: Path, mode: str, since_hours: int, out_dir: Path) -> Tuple[int, List[str], str]:
    cmd = [sys.executable, str(ROOT / "main.py"), "--config", str(config_path)]
    if since_hours:
        cmd += ["--since-hours", str(since_hours)]
    if mode == "dryrun-fake":
        cmd += ["--dry-run", "--fake-llm", "--out", str(out_dir)]
    elif mode == "dryrun-real":
        cmd += ["--dry-run", "--out", str(out_dir)]
    else:
        cmd += ["--require-test-channel"]

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=45 * 60, check=False, cwd=str(ROOT))
        code, output = proc.returncode, proc.stderr + "\n" + proc.stdout
    except subprocess.TimeoutExpired as exc:
        code = 124
        output = ((exc.stderr or b"").decode("utf-8", "replace") if isinstance(exc.stderr, bytes) else (exc.stderr or ""))

    events = [mask(line.strip()) for line in output.splitlines() if EVENT_RE.search(line)]

    # Unexpected exceptions: report the class name only; keep details only when the format is known to be safe.
    crash = ""
    non_empty = [l.strip() for l in output.splitlines() if l.strip()]
    crashed = "Traceback (most recent call last)" in output
    if (crashed or code not in (0, 1)) and non_empty:
        m = EXC_RE.match(non_empty[-1])
        if m:
            detail = m.group(2).strip()
            crash = m.group(1) + (f"（{detail}）" if SAFE_EXC_DETAIL_RE.match(detail) else "")
        elif code == 124:
            crash = "killed after running for more than 45 minutes"
        elif not events:
            crash = "exited with an error and no reportable events (usually a config problem; run main.py locally to see the message)"
    return code, events, crash


def main() -> None:
    parser = argparse.ArgumentParser(description="Live environment check (content-free report)")
    parser.add_argument("--config", required=True)
    parser.add_argument("--mode", choices=MODES, default="dryrun-fake")
    parser.add_argument("--since-hours", type=int, default=168)
    parser.add_argument("--out", default="", help="dry-run output directory (default: last_dryrun/ next to the config)")
    parser.add_argument("--result", default="-", help="report file path; - prints to the terminal")
    args = parser.parse_args()

    config_path = Path(args.config).expanduser()
    out_dir = Path(args.out).expanduser() if args.out else config_path.parent / "last_dryrun"

    report: List[str] = [
        "# Live check result",
        "",
        f"- Time (UTC): {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}",
        f"- Commit: {os.environ.get('GITHUB_SHA', 'local run')[:12]}",
        f"- Mode: {args.mode}, looking back {args.since_hours} hours",
        "",
        "## Environment",
    ]
    pre_lines, flat = preflight(config_path)
    report += pre_lines

    ok = flat is not None
    if ok and args.mode != "dryrun-fake":
        report += ["", "## Claude CLI"]
        report += cli_smoke(flat)  # type: ignore[arg-type]

    if ok:
        if args.mode != "test-channel" and out_dir.exists():
            shutil.rmtree(out_dir, ignore_errors=True)
        code, events, crash = run_main(config_path, args.mode, args.since_hours, out_dir)
        report += ["", "## Run", f"- main.py exit code: {code} (0 all good, 1 some items failed, 5 Mattermost unreachable or bad token, other = abnormal)"]
        if crash:
            report.append(f"- Abnormal exit: {crash}")
        if args.mode != "test-channel":
            mds = len([p for p in out_dir.glob("*.md") if not p.name.startswith("_")]) if out_dir.exists() else 0
            pngs = len(list(out_dir.glob("*.png"))) if out_dir.exists() else 0
            report.append(f"- Output: {mds} reply drafts, {pngs} key-page images (kept on the machine, not uploaded)")
        report += ["", "## Events", "```"] + (events or ["(no events)"]) + ["```"]
        ok = code == 0 and not crash
    else:
        report += ["", "## Run", "- Config problem; main.py was not run"]

    text = "\n".join(report) + "\n"
    if args.result == "-":
        print(text)
    else:
        Path(args.result).write_text(text, encoding="utf-8")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
