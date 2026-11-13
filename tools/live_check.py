#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
真實環境檢查：在握有 token 的機器上執行 main.py，產出「不含內容」的結果報告。

報告只包含：環境檢查、設定檔的非機密欄位、狀態碼、貼文 ID、頁數、字數、耗時。
不包含：token、網址、頻道 ID、帳號名稱、簡報內容、摘要內容。

    python3 tools/live_check.py --config ~/.config/lab-summarizer/config.toml --mode dryrun-fake --result -

模式：
    dryrun-fake    不發文、不呼叫模型：測 Mattermost 讀取、簡報匯出、轉圖
    dryrun-real    不發文、呼叫真的模型：摘要存在 --out 目錄，由人在本機檢視
    test-channel   呼叫真的模型，發到測試頻道（強制，不會發到正式頻道）
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

# 只有符合這些事件代碼的日誌行會進報告，其餘（含 traceback）一律丟棄
EVENT_RE = re.compile(
    r"\b(WINDOW|SUMMARY_OK|VALIDATION_RETRY|RESCUED_CANDIDATE|ACCEPTED_NEAREST|JSON_PARSE_FAIL|"
    r"PROVIDER_FALLBACK|DECK_FETCH_FAIL|DECK_TIMING|RUN_DONE|CLAUDE_CLI_NONZERO|SUSPECTED_INJECTION|"
    r"DELIVER_FAIL|SANDBOX_CONFIG_ERROR|CONFIG_ERROR|ALREADY_RUNNING|REPORT_DM_FAIL|MATTERMOST_ERROR)\b"
)
EXC_RE = re.compile(r"^([A-Za-z_][\w.]*(?:Error|Exception|Exit))\b:?\s*(.*)$")
SAFE_EXC_DETAIL_RE = re.compile(r"^mattermost status=\d+ code=[\w.\-]+$")


def mask(text: str) -> str:
    """遮掉網址、家目錄路徑、長的隨機字串。貼文 ID（26 碼）保留，方便對照。"""
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
        lines.append(f"- {label}：{'有' if which_any(names) else '沒有'}")
    lines.append(f"- TOML 解析器：{'有' if tomllib else '沒有（Python 3.10 請 apt install python3-tomli）'}")

    if not config_path.exists():
        lines.append("- 設定檔：找不到")
        return lines, None
    if tomllib is None:
        return lines, None
    try:
        with open(config_path, "rb") as fh:
            raw = tomllib.load(fh)
    except Exception as exc:
        lines.append(f"- 設定檔：無法解析（{type(exc).__name__}）")
        return lines, None

    flat: Dict[str, Any] = {}
    for section in raw.values():
        if isinstance(section, dict):
            flat.update(section)

    def filled(key: str) -> str:
        return "已填" if str(flat.get(key, "")).strip() else "未填"

    lines.append("- 設定檔：可解析")
    lines.append(f"  - base_url {filled('base_url')}、channel_id {filled('channel_id')}、"
                 f"test_channel_id {filled('test_channel_id')}、maintainer_username {filled('maintainer_username')}")
    lines.append(f"  - reply_mode = {flat.get('reply_mode', 'test_channel')}")
    lines.append(f"  - 隔離：isolation_user {filled('isolation_user')}、allow_direct = {bool(flat.get('allow_direct', False))}")
    lines.append(f"  - vision_timeout_sec = {flat.get('vision_timeout_sec', 420)}、"
                 f"enable_ollama_fallback = {bool(flat.get('enable_ollama_fallback', False))}、"
                 f"enable_html_attachments = {bool(flat.get('enable_html_attachments', False))}")

    token_file = str(flat.get("token_file", "")).strip()
    if os.environ.get("MM_BOT_TOKEN"):
        lines.append("- Token：由環境變數提供")
    elif not token_file:
        lines.append("- Token：token_file 未填，也沒有環境變數")
    else:
        path = Path(token_file).expanduser()
        if not path.exists():
            lines.append("- Token 檔：找不到")
        else:
            loose = bool(path.stat().st_mode & 0o077)
            lines.append(f"- Token 檔：存在，權限{'太寬（請 chmod 600）' if loose else '正確'}")
    return lines, flat


def cli_smoke(flat: Dict[str, Any]) -> List[str]:
    """確認 Claude CLI 的三個參數與程式的假設一致（STATUS 的 T3）。"""
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
    version = mask(out.strip().splitlines()[0]) if code == 0 and out.strip() else "無法取得"
    lines.append(f"- `claude --version`：exit={code}，{version}")
    if code != 0:
        lines.append(f"  - stderr 尾端：{mask(' '.join(err.split())[-160:])}")
        return lines

    system = '只輸出這個 JSON，不要任何其他文字：{"ok": true}'
    for label, tool_args in (("--allowedTools Read", ["--allowedTools", "Read"]), ('--tools ""', ["--tools", ""])):
        code, out, err, secs = run(
            ["-p", "--system-prompt", system, *tool_args, "--output-format", "json"], "請輸出 JSON", 180
        )
        detail = f"exit={code}，耗時 {secs:.0f}s"
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
                    detail += (f"，外層是 JSON 物件（欄位：{keys}），result 是字串：{isinstance(result, str)}，"
                               f"內層 JSON 正確：{inner_ok}，is_error = {outer.get('is_error')}")
                else:
                    detail += f"，外層是 JSON 但不是物件（{type(outer).__name__}）"
            except json.JSONDecodeError:
                detail += f"，輸出不是 JSON（長度 {len(out)}）"
        else:
            detail += f"，stderr 尾端：{mask(' '.join(err.split())[-160:])}"
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

    # 未預期的例外：只回報類別名稱；細節只有在確定不含機密的格式時才保留
    crash = ""
    non_empty = [l.strip() for l in output.splitlines() if l.strip()]
    crashed = "Traceback (most recent call last)" in output
    if (crashed or code not in (0, 1)) and non_empty:
        m = EXC_RE.match(non_empty[-1])
        if m:
            detail = m.group(2).strip()
            crash = m.group(1) + (f"（{detail}）" if SAFE_EXC_DETAIL_RE.match(detail) else "")
        elif code == 124:
            crash = "執行超過 45 分鐘被終止"
        elif not events:
            crash = "程式以錯誤結束，沒有可回報的事件（多半是設定檔欄位錯誤，請在本機直接執行 main.py 查看訊息）"
    return code, events, crash


def main() -> None:
    parser = argparse.ArgumentParser(description="真實環境檢查（輸出不含內容的報告）")
    parser.add_argument("--config", required=True)
    parser.add_argument("--mode", choices=MODES, default="dryrun-fake")
    parser.add_argument("--since-hours", type=int, default=168)
    parser.add_argument("--out", default="", help="dry-run 輸出目錄（預設在設定檔旁的 last_dryrun/）")
    parser.add_argument("--result", default="-", help="報告檔路徑；- 表示印到終端機")
    args = parser.parse_args()

    config_path = Path(args.config).expanduser()
    out_dir = Path(args.out).expanduser() if args.out else config_path.parent / "last_dryrun"

    report: List[str] = [
        "# 真實環境檢查結果",
        "",
        f"- 時間（UTC）：{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}",
        f"- commit：{os.environ.get('GITHUB_SHA', '本機執行')[:12]}",
        f"- 模式：{args.mode}，回溯 {args.since_hours} 小時",
        "",
        "## 環境",
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
        report += ["", "## 執行", f"- main.py 結束代碼：{code}（0 全部成功、1 有失敗項目、5 連不上 Mattermost 或 token 無效、其他為異常）"]
        if crash:
            report.append(f"- 異常：{crash}")
        if args.mode != "test-channel":
            mds = len([p for p in out_dir.glob("*.md") if not p.name.startswith("_")]) if out_dir.exists() else 0
            pngs = len(list(out_dir.glob("*.png"))) if out_dir.exists() else 0
            report.append(f"- 產出：{mds} 份回覆草稿、{pngs} 張關鍵頁圖片（留在執行機器上，未上傳）")
        report += ["", "## 事件", "```"] + (events or ["（沒有事件）"]) + ["```"]
        ok = code == 0 and not crash
    else:
        report += ["", "## 執行", "- 設定檔有問題，未執行 main.py"]

    text = "\n".join(report) + "\n"
    if args.result == "-":
        print(text)
    else:
        Path(args.result).write_text(text, encoding="utf-8")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
