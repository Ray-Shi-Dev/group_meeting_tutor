#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
實驗室 Group Meeting 簡報自動摘要 Agent：主流程

    python3 main.py --config config.toml                 # 正式執行（依設定檔的 reply_mode 發文）
    python3 main.py --config config.toml --dry-run       # 不發文，結果寫到 --out 目錄
    python3 main.py --config config.toml --dry-run --fake-llm   # 連模型都不呼叫，只測抓貼文與轉圖
    python3 main.py --config config.toml --since-hours 720      # 測試用：回溯 30 天的貼文

需要 Python 3.10+ 與 poppler-utils（3.10 另需 python3-tomli）。
"""

from __future__ import annotations

import argparse
import fcntl
import json
import logging
import os
import shutil
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # Python 3.10：apt install python3-tomli
    import tomli as tomllib  # type: ignore[no-redef]

import sources as src
from mattermost import MattermostClient, MattermostError
from store import Store
from summary_harness import (
    PERMISSION_REMINDER_REPLY,
    SandboxConfigurationError,
    SlideDeckInput,
    SlideSummaryHarness,
    SummaryGenerationError,
    SummaryOutput,
    SuspectedInjectionError,
    format_combined_mattermost_reply,
    make_run_deadline,
)

logger = logging.getLogger("lab_slide_summarizer")


# ---------------------------------------------------------------------------
# 設定
# ---------------------------------------------------------------------------
@dataclass
class Config:
    base_url: str
    channel_id: str
    token_file: str = ""
    maintainer_username: str = ""
    reply_mode: str = "test_channel"      # "thread" | "test_channel"
    test_channel_id: str = ""

    timezone: str = "Asia/Taipei"
    window_weekday: int = 2               # 0=週一 … 2=週三
    window_hour: int = 12
    budget_sec: int = 1800

    max_download_mb: int = 60
    max_pages: int = 150
    enable_html_attachments: bool = False

    claude_bin: str = "claude"
    isolation_user: str = ""
    allow_direct: bool = False
    vision_timeout_sec: int = 420
    text_timeout_sec: int = 90
    claude_max_vision_pages: int = 32
    enable_ollama_fallback: bool = False
    ollama_url: str = "http://127.0.0.1:11434/api/chat"
    ollama_model: str = "qwen2.5vl:7b"

    db_path: str = "state.sqlite3"
    work_root: str = ""                   # 空字串＝系統暫存目錄
    exchange_root: str = "/var/tmp"

    @staticmethod
    def load(path: str) -> "Config":
        with open(path, "rb") as fh:
            raw = tomllib.load(fh)
        flat: Dict[str, Any] = {}
        for section in ("mattermost", "schedule", "sources", "llm", "paths"):
            flat.update(raw.get(section, {}))
        known = set(Config.__dataclass_fields__)
        unknown = set(flat) - known
        if unknown:
            raise SystemExit(f"設定檔有不認得的欄位：{sorted(unknown)}")
        cfg = Config(**flat)
        if cfg.reply_mode not in ("thread", "test_channel"):
            raise SystemExit("reply_mode 必須是 thread 或 test_channel")
        if cfg.reply_mode == "test_channel" and not cfg.test_channel_id:
            raise SystemExit("reply_mode=test_channel 時必須設定 test_channel_id")
        return cfg


def load_token(cfg: Config) -> str:
    """優先讀環境變數 MM_BOT_TOKEN（讀完即從環境移除），否則讀 token_file。"""
    token = os.environ.pop("MM_BOT_TOKEN", "").strip()
    if token:
        return token
    if not cfg.token_file:
        raise SystemExit("找不到 Mattermost token：請設定 MM_BOT_TOKEN 或 token_file")
    path = Path(cfg.token_file)
    if path.stat().st_mode & 0o077:
        raise SystemExit(f"{path} 的權限太寬，請 chmod 600")
    return path.read_text(encoding="utf-8").strip()


def window_start(now: datetime, weekday: int, hour: int) -> datetime:
    """回傳 now 之前最近一次的「週 weekday 的 hour 點」。週三 08:30 執行時＝上週三 12:00。"""
    cand = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    cand -= timedelta(days=(now.weekday() - weekday) % 7)
    if cand >= now:
        cand -= timedelta(days=7)
    return cand


# ---------------------------------------------------------------------------
# 假模型（--fake-llm）：只用來測抓貼文、轉圖、發文的管線，不消耗訂閱額度
# ---------------------------------------------------------------------------
def install_fake_llm(harness: SlideSummaryHarness) -> None:
    def fake(prompt: str, pages: Optional[List[Tuple[int, Path]]], timeout_sec: int) -> str:
        nums = [n for n, _ in (pages or [])] or [1]
        picks = nums[1:3] if len(nums) >= 3 else nums[:2]
        return json.dumps(
            {
                "in_progress": False,
                "one_liner": "【假模型測試輸出】這不是真正的摘要，只用來確認抓貼文、轉圖與發文流程是否正常運作。",
                "why_it_matters": "如果你在頻道看到這段文字，代表管線已經打通，接下來可以換成真正的模型來產生摘要內容。",
                "takeaways": ["抓貼文與匯出簡報的流程可以正常運作", "關鍵頁面的圖片可以正常上傳並顯示"],
                "key_points": ["成功找到含簡報的貼文", "成功把簡報轉成逐頁圖片", "成功把回覆送到指定位置"],
                "glossary": [],
                "questions": ["這則測試訊息有出現在正確的位置嗎", "附圖的頁碼和內容對得起來嗎"],
                "key_pages": picks,
            },
            ensure_ascii=False,
        )

    harness._providers = lambda: [("fake-llm", fake, harness.claude_max_vision_pages)]  # type: ignore[method-assign]


# ---------------------------------------------------------------------------
# 單次執行
# ---------------------------------------------------------------------------
@dataclass
class RunReport:
    done: List[str] = field(default_factory=list)
    degraded: List[str] = field(default_factory=list)
    permission: List[str] = field(default_factory=list)
    failed: List[str] = field(default_factory=list)
    blocked: List[str] = field(default_factory=list)
    opted_out: int = 0

    def to_message(self, mm: MattermostClient, dry_run: bool) -> str:
        def links(ids: List[str]) -> str:
            return "\n".join(f"  - {mm.permalink(i.split(' ')[0])} {' '.join(i.split(' ')[1:])}".rstrip() for i in ids)

        lines = [f"**簡報摘要 Agent 執行結果**{'（dry-run）' if dry_run else ''}"]
        lines.append(f"- 成功：{len(self.done)} 則")
        if self.degraded:
            lines.append(f"- 其中非 Claude 一次通過（請抽查品質）：{len(self.degraded)} 則\n{links(self.degraded)}")
        if self.permission:
            lines.append(f"- 簡報沒開權限：{len(self.permission)} 則\n{links(self.permission)}")
        if self.failed:
            lines.append(f"- 失敗：{len(self.failed)} 則\n{links(self.failed)}")
        if self.blocked:
            lines.append(f"- ⚠️ 輸出含疑似憑證而被攔下（請檢查該簡報是否藏有指令）：{len(self.blocked)} 則\n{links(self.blocked)}")
        if self.opted_out:
            lines.append(f"- 標了 #no-summary 而跳過：{self.opted_out} 則")
        return "\n".join(lines)

    @property
    def nothing_happened(self) -> bool:
        return not (self.done or self.permission or self.failed or self.blocked or self.opted_out)


def build_decks_for_post(
    post: Dict[str, Any], cfg: Config, mm: MattermostClient, work_dir: Path
) -> Tuple[List[SlideDeckInput], List[str]]:
    """回傳（可摘要的簡報, 錯誤代碼清單）。"""
    decks: List[SlideDeckInput] = []
    errors: List[str] = []
    max_bytes = cfg.max_download_mb * 1024 * 1024

    for idx, source in enumerate(src.find_deck_sources(post, cfg.enable_html_attachments), start=1):
        deck_dir = work_dir / f"{post['id']}_{idx}"
        try:
            if source.kind == "gslides":
                pdf = src.fetch_gslides_pdf(source.ref, max_bytes, deck_dir / "conv")
            else:
                try:
                    data = mm.download_file(source.ref, max_bytes)
                except MattermostError as exc:
                    raise src.DeckFetchError("TOO_LARGE" if exc.status == 413 else "NETWORK") from exc
                pdf = src.convert_to_pdf(data, source.ext, deck_dir / "conv")
            pages, text = src.render_pdf(pdf, deck_dir / "pages", cfg.max_pages)
        except src.DeckFetchError as exc:
            errors.append(exc.code)
            logger.warning("DECK_FETCH_FAIL post_id=%s deck=%d kind=%s code=%s", post["id"], idx, source.kind, exc.code)
            continue

        decks.append(
            SlideDeckInput(
                post_id=post["id"], deck_index=idx, source_label=source.label,
                post_message=post.get("message") or "", total_pages=len(pages),
                page_png_paths=pages, speaker_notes=text,
            )
        )
    return decks, errors


def run(cfg: Config, args: argparse.Namespace) -> int:
    """執行一次。回傳 0 全部成功、1 有失敗項目、2 以上為無法執行。"""
    try:
        return _run(cfg, args)
    except MattermostError as exc:
        # 連不上、token 無效、Bot 不在頻道裡等：沒有任何貼文被處理
        logger.error("MATTERMOST_ERROR status=%s code=%s", exc.status, exc.code)
        return 5


def _run(cfg: Config, args: argparse.Namespace) -> int:
    lock_fh = open(cfg.db_path + ".lock", "w")
    try:
        fcntl.flock(lock_fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        logger.error("ALREADY_RUNNING")
        return 2

    if getattr(args, "require_test_channel", False):
        # 自動化檢查專用：不管設定檔怎麼寫，一律只發到測試頻道
        if not cfg.test_channel_id:
            logger.error("CONFIG_ERROR require_test_channel_without_test_channel_id")
            return 4
        cfg.reply_mode = "test_channel"

    mm = MattermostClient(cfg.base_url, load_token(cfg))
    try:
        harness = SlideSummaryHarness(
            claude_bin=cfg.claude_bin,
            claude_max_vision_pages=cfg.claude_max_vision_pages,
            ollama_url=cfg.ollama_url,
            ollama_model=cfg.ollama_model,
            enable_ollama_fallback=cfg.enable_ollama_fallback,
            vision_timeout_sec=cfg.vision_timeout_sec,
            text_timeout_sec=cfg.text_timeout_sec,
            isolation_user=None if args.fake_llm else (cfg.isolation_user or None),
            allow_direct=True if args.fake_llm else cfg.allow_direct,
            exchange_root=cfg.exchange_root,
        )
    except SandboxConfigurationError as exc:
        logger.error("SANDBOX_CONFIG_ERROR %s", exc)
        return 3
    if args.fake_llm:
        install_fake_llm(harness)

    me = mm.me()
    tz = ZoneInfo(cfg.timezone)
    now = datetime.now(tz)
    start = now - timedelta(hours=args.since_hours) if args.since_hours else window_start(now, cfg.window_weekday, cfg.window_hour)
    since_ms = int(start.timestamp() * 1000)

    posts = [
        p for p in mm.channel_posts_since(cfg.channel_id, since_ms)
        if not p.get("root_id") and not p.get("delete_at") and not p.get("type")
        and p.get("create_at", 0) >= since_ms and p.get("user_id") != me["id"]
    ]
    logger.info("WINDOW start=%s candidates=%d", start.isoformat(timespec="minutes"), len(posts))

    store = Store(cfg.db_path)
    deadline = make_run_deadline(cfg.budget_sec)
    work_dir = Path(tempfile.mkdtemp(prefix="lab_summarizer_", dir=cfg.work_root or None))
    os.chmod(work_dir, 0o700)
    out_dir = Path(args.out) if args.dry_run else None
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)

    report = RunReport()

    def deliver(post: Dict[str, Any], message: str, uploads: List[Path]) -> str:
        """依模式送出一則回覆，回傳回覆的 post id（dry-run 回傳空字串）。"""
        if out_dir:
            (out_dir / f"{post['id']}.md").write_text(message, encoding="utf-8")
            for i, png in enumerate(uploads, start=1):
                shutil.copy(png, out_dir / f"{post['id']}_key{i}.png")
            return ""
        if cfg.reply_mode == "thread":
            channel, root, body = post["channel_id"], post["id"], message
        else:
            channel, root = cfg.test_channel_id, ""
            body = f"原貼文：{mm.permalink(post['id'])}\n\n{message}"
        file_ids = mm.upload_files(channel, uploads) if uploads else []
        return mm.create_post(channel, body, root_id=root, file_ids=file_ids)["id"]

    try:
        for post in posts:
            pid = post["id"]
            if store.is_final(pid) and not args.dry_run:
                continue
            if src.is_opted_out(post.get("message") or ""):
                report.opted_out += 1
                if not args.dry_run:
                    store.record(pid, "skipped_opt_out")
                continue
            if not src.find_deck_sources(post, cfg.enable_html_attachments):
                continue
            if time.monotonic() > deadline - 15:
                report.failed.append(f"{pid} DEADLINE")
                if not args.dry_run:
                    store.record(pid, "failed", detail="DEADLINE")
                continue

            decks, fetch_errors = build_decks_for_post(post, cfg, mm, work_dir)
            summaries: List[Tuple[SlideDeckInput, SummaryOutput]] = []
            errors = list(fetch_errors)
            blocked = False

            for deck in decks:
                started = time.monotonic()
                outcome = "ok"
                try:
                    summaries.append((deck, harness.summarize_single_deck(deck, deadline)))
                except SuspectedInjectionError:
                    blocked = True
                    outcome = "blocked"
                except SummaryGenerationError as exc:
                    errors.append(exc.reason_code)
                    outcome = "failed"
                logger.info(
                    "DECK_TIMING post_id=%s deck=%d pages=%d elapsed=%ds outcome=%s",
                    deck.post_id, deck.deck_index, deck.total_pages,
                    int(time.monotonic() - started), outcome,
                )

            try:
                if blocked:
                    # 同一則貼文只要有一份簡報被攔下，整則都不發，交給維護者人工檢查
                    report.blocked.append(pid)
                    if not args.dry_run:
                        store.record(pid, "blocked_injection")
                elif summaries:
                    message, uploads = format_combined_mattermost_reply(summaries)
                    reply_id = deliver(post, message, uploads)
                    providers = ",".join(s.provider_used for _, s in summaries)
                    report.done.append(pid)
                    if any(s.degraded for _, s in summaries) and not args.fake_llm:
                        report.degraded.append(f"{pid} {providers}")
                    if errors:
                        report.failed.append(f"{pid} 部分簡報失敗:{','.join(errors)}")
                    if not args.dry_run:
                        store.record(pid, "done", reply_id=reply_id, provider=providers, detail=",".join(errors))
                elif errors and all(e == "PERMISSION" for e in errors):
                    reply_id = deliver(post, PERMISSION_REMINDER_REPLY, [])
                    report.permission.append(pid)
                    if not args.dry_run:
                        store.record(pid, "permission_notified", reply_id=reply_id)
                else:
                    report.failed.append(f"{pid} {','.join(errors) or 'UNKNOWN'}")
                    if not args.dry_run:
                        store.record(pid, "failed", detail=",".join(errors))
            except MattermostError as exc:
                logger.error("DELIVER_FAIL post_id=%s status=%s code=%s", pid, exc.status, exc.code)
                report.failed.append(f"{pid} POST_FAILED:{exc.code}")
                if not args.dry_run:
                    store.record(pid, "failed", detail=f"POST_FAILED:{exc.code}")
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
        store.close()

    summary = report.to_message(mm, args.dry_run)
    logger.info(
        "RUN_DONE done=%d degraded=%d permission=%d failed=%d blocked=%d opted_out=%d",
        len(report.done), len(report.degraded), len(report.permission),
        len(report.failed), len(report.blocked), report.opted_out,
    )
    if out_dir:
        (out_dir / "_report.md").write_text(summary, encoding="utf-8")
    elif cfg.maintainer_username and not report.nothing_happened:
        try:
            maintainer = mm.user_by_username(cfg.maintainer_username)
            mm.create_post(mm.direct_channel_id(me["id"], maintainer["id"]), summary)
        except MattermostError as exc:
            logger.error("REPORT_DM_FAIL status=%s code=%s", exc.status, exc.code)

    return 1 if (report.failed or report.blocked) else 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Group Meeting 簡報自動摘要 Agent")
    parser.add_argument("--config", required=True)
    parser.add_argument("--dry-run", action="store_true", help="不發文、不寫狀態，結果存到 --out")
    parser.add_argument("--out", default="dryrun_out", help="dry-run 的輸出目錄")
    parser.add_argument("--fake-llm", action="store_true", help="用固定的假摘要代替模型，只測管線")
    parser.add_argument("--since-hours", type=int, default=0, help="測試用：改成回溯指定小時數的貼文")
    parser.add_argument(
        "--require-test-channel", action="store_true",
        help="強制只發到測試頻道（忽略設定檔的 reply_mode），自動化檢查使用",
    )
    args = parser.parse_args()
    sys.exit(run(Config.load(args.config), args))


if __name__ == "__main__":
    main()
