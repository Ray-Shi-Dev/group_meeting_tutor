#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
端到端測試：假的 Mattermost 伺服器 + 假的 Google 匯出 + 假模型。
不需要網路、Claude CLI 或真的 Mattermost。

    python3 tests/test_pipeline.py

需要 poppler-utils 與 reportlab（只有測試用到 reportlab，用來產生測試 PDF）。
有裝 python-pptx 與 LibreOffice 時會多測 PPTX 附件。
"""

from __future__ import annotations

import argparse
import io
import json
import re
import shutil
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main  # noqa: E402
import sources as src  # noqa: E402
from store import Store  # noqa: E402

from reportlab.lib.pagesizes import landscape, A4  # noqa: E402
from reportlab.pdfgen import canvas  # noqa: E402


def make_pdf(n_pages: int, title: str) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=landscape(A4))
    for i in range(1, n_pages + 1):
        c.setFont("Helvetica-Bold", 36)
        c.drawString(72, 400, f"{title} - page {i}")
        c.showPage()
    c.save()
    return buf.getvalue()


def make_pptx(n_slides: int) -> bytes | None:
    try:
        from pptx import Presentation
    except ImportError:
        return None
    prs = Presentation()
    for i in range(n_slides):
        slide = prs.slides.add_slide(prs.slide_layouts[5])
        slide.shapes.title.text = f"PPTX slide {i + 1}"
    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# 假的 Mattermost
# ---------------------------------------------------------------------------
class FakeMM:
    def __init__(self):
        self.posts: dict[str, dict] = {}
        self.files: dict[str, bytes] = {}
        self.created: list[dict] = []
        self.uploads: list[dict] = []
        self.seq = 0

    def add_post(self, pid, message, user="u_alice", files=None, root_id="", type_="", age_min=60):
        now = int(time.time() * 1000)
        self.posts[pid] = {
            "id": pid, "channel_id": "ch_main", "user_id": user, "message": message,
            "root_id": root_id, "type": type_, "delete_at": 0,
            "create_at": now - age_min * 60_000, "update_at": now - age_min * 60_000,
            "metadata": {"files": files or []},
        }


def make_handler(fake: FakeMM):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _json(self, obj, status=200):
            body = json.dumps(obj).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            assert self.headers.get("Authorization") == "Bearer test-token"
            p = self.path
            if p == "/api/v4/users/me":
                return self._json({"id": "u_bot", "username": "summary-bot"})
            if p.startswith("/api/v4/users/username/"):
                return self._json({"id": "u_maint", "username": p.rsplit("/", 1)[1]})
            m = re.match(r"/api/v4/channels/(\w+)/posts\?since=(\d+)", p)
            if m:
                since = int(m.group(2))
                posts = {k: v for k, v in fake.posts.items() if v["update_at"] > since}
                return self._json({"order": list(posts), "posts": posts})
            m = re.match(r"/api/v4/files/(\w+)$", p)
            if m:
                data = fake.files[m.group(1)]
                self.send_response(200)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            self._json({"id": "not_found"}, 404)

        def do_POST(self):
            assert self.headers.get("Authorization") == "Bearer test-token"
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            if self.path == "/api/v4/posts":
                data = json.loads(body)
                fake.seq += 1
                data["id"] = f"reply{fake.seq}"
                fake.created.append(data)
                return self._json(data, 201)
            if self.path == "/api/v4/channels/direct":
                return self._json({"id": "ch_dm"})
            if self.path == "/api/v4/files":
                ctype = self.headers["Content-Type"]
                boundary = ctype.split("boundary=")[1].encode()
                parts = body.split(b"--" + boundary)
                channel = parts[1].split(b"\r\n\r\n", 1)[1].rsplit(b"\r\n", 1)[0].decode()
                head, content = parts[2].split(b"\r\n\r\n", 1)
                content = content.rsplit(b"\r\n", 1)[0]
                name = re.search(rb'filename="([^"]+)"', head).group(1).decode()
                fake.seq += 1
                fid = f"file{fake.seq}"
                fake.uploads.append({"id": fid, "channel": channel, "name": name, "png": content[:8] == b"\x89PNG\r\n\x1a\n", "size": len(content)})
                return self._json({"file_infos": [{"id": fid}]}, 201)
            self._json({"id": "not_found"}, 404)

    return Handler


# ---------------------------------------------------------------------------
# 測試
# ---------------------------------------------------------------------------
def run_main(cfg_path: Path, **flags) -> int:
    args = argparse.Namespace(
        config=str(cfg_path), dry_run=flags.get("dry_run", False), out=flags.get("out", "dryrun_out"),
        fake_llm=True, since_hours=flags.get("since_hours", 0),
        require_test_channel=flags.get("require_test_channel", False),
    )
    return main.run(main.Config.load(str(cfg_path)), args)


def test() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="summarizer_test_"))
    fake = FakeMM()
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(fake))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}"

    ID_OK = "1K58qIA6uO2LasNdfmk41Y4XsP7cEYSg-UGTLBAkTxvY"
    ID_BIG = "1ScJqYvs4XJVaO8lLRPGv2U4FxD408DicDu3LtHBuhNY"
    ID_PRIVATE = "17LQTJllRsCpki2H8dY7YDD0cpp0K9li0gQ4T0PHKz1E"
    ID_HIDDEN = "1DOSu3sFpf4BC9Kr28rpB250bALbrpiObofTtnOeey5Q"
    pdfs = {ID_OK: make_pdf(12, "Paper"), ID_BIG: make_pdf(45, "Long"), ID_HIDDEN: make_pdf(6, "Hidden")}

    def fake_http_get(url, max_bytes, timeout=60):
        for deck_id, data in pdfs.items():
            if deck_id in url and "export/pdf" in url:
                return data, url
        return b"<html>Sign in - Google Accounts</html>", url

    src._http_get = fake_http_get

    # --- 貼文情境 ---
    fake.add_post("p_ok", f"明天我會分享 prima.cpp，簡報調整中\nhttps://docs.google.com/presentation/d/{ID_OK}/edit?usp=sharing")
    fake.add_post("p_big", f"明天分享 Weight-Space Programming https://docs.google.com/presentation/d/{ID_BIG}/edit?usp=sharing")
    fake.add_post("p_private", f"明天分享 MemFreezing https://docs.google.com/presentation/d/{ID_PRIVATE}/edit?usp=sharing")
    fake.add_post("p_hidden", f"這是簡報 [連結](https://docs.google.com/presentation/d/{ID_HIDDEN}/edit)，調整中")
    fake.add_post("p_optout", f"未發表成果 #no-summary https://docs.google.com/presentation/d/{ID_OK}/edit")
    fake.add_post("p_announce", "明天請大家 9:10 上課")
    fake.add_post("p_preview", "我下禮拜三預計會分享本地模型，有興趣可以按個表情")
    fake.add_post("p_sheet", "https://docs.google.com/spreadsheets/d/1dFIX65yt8G9zYlAEP4tO_DApDRQsHj2F7WgP9Jqmet0/edit")
    fake.add_post("p_github", "https://github.com/jingyaogong/minimind 給大家參考")
    fake.add_post("p_video", "demo 影片", files=[{"id": "f_mp4", "name": "demo.mp4", "extension": "mp4"}])
    fake.add_post("p_system", "已將頻道標題更改", type_="system_header_change")
    fake.add_post("p_reply", f"https://docs.google.com/presentation/d/{ID_OK}/edit", root_id="p_ok")
    fake.add_post("p_bot", f"https://docs.google.com/presentation/d/{ID_OK}/edit", user="u_bot")
    fake.add_post("p_old", f"https://docs.google.com/presentation/d/{ID_OK}/edit", age_min=60 * 24 * 9)
    fake.files["f_pdf"] = make_pdf(5, "Attached")
    fake.add_post("p_pdf", "簡報如附件", files=[{"id": "f_pdf", "name": "slides.pdf", "extension": "pdf"}])
    fake.files["f_html"] = b"<html><body><h1>HTML deck</h1></body></html>"
    fake.add_post("p_html", "簡報 html", files=[{"id": "f_html", "name": "deck.html", "extension": "html"}])
    pptx_bytes = make_pptx(4) if shutil.which("soffice") else None
    if pptx_bytes:
        fake.files["f_pptx"] = pptx_bytes
        fake.add_post("p_pptx", "簡報 pptx", files=[{"id": "f_pptx", "name": "talk.pptx", "extension": "pptx"}])
    fake.add_post("p_two", f"兩份 https://docs.google.com/presentation/d/{ID_OK}/edit 和 https://docs.google.com/presentation/d/{ID_HIDDEN}/edit")

    token_file = tmp / "token"
    token_file.write_text("test-token")
    token_file.chmod(0o600)

    def write_cfg(mode: str, db: str) -> Path:
        path = tmp / f"config_{mode}.toml"
        path.write_text(
            f'[mattermost]\nbase_url = "{base}"\nchannel_id = "ch_main"\ntoken_file = "{token_file}"\n'
            f'maintainer_username = "ray"\nreply_mode = "{mode}"\ntest_channel_id = "ch_test"\n'
            f'[llm]\nallow_direct = true\n[paths]\ndb_path = "{tmp / db}"\nwork_root = "{tmp}"\nexchange_root = "{tmp}"\n',
            encoding="utf-8",
        )
        return path

    expected = {"p_ok", "p_big", "p_hidden", "p_pdf", "p_two"} | ({"p_pptx"} if pptx_bytes else set())

    # 1) dry-run：不發文、不寫狀態
    out = tmp / "dry"
    run_main(write_cfg("thread", "dry.sqlite3"), dry_run=True, out=str(out), since_hours=24 * 7)
    assert not fake.created and not fake.uploads, "dry-run 不應該發文"
    produced = {p.stem for p in out.glob("p_*.md")}
    assert produced == expected | {"p_private"}, produced
    assert (out / "p_ok_key1.png").read_bytes()[:4] == b"\x89PNG"
    assert "AI 自動摘要" in (out / "p_ok.md").read_text(encoding="utf-8")
    assert "檢視權限" in (out / "p_private.md").read_text(encoding="utf-8")
    assert "簡報 2 快速導讀" in (out / "p_two.md").read_text(encoding="utf-8")
    print("1 dry-run ok:", sorted(produced))

    # 2) thread 模式：回覆在原貼文底下
    cfg_thread = write_cfg("thread", "thread.sqlite3")
    run_main(cfg_thread, since_hours=24 * 7)
    replies = {c["root_id"]: c for c in fake.created if c.get("root_id")}
    assert set(replies) == expected | {"p_private"}, set(replies)
    assert all(c["channel_id"] == "ch_main" for c in replies.values())
    assert len(replies["p_ok"]["file_ids"]) == 2 and "file_ids" not in replies["p_private"]
    assert len(replies["p_two"]["file_ids"]) == 4
    assert all(u["png"] and u["channel"] == "ch_main" for u in fake.uploads)
    dm = [c for c in fake.created if c["channel_id"] == "ch_dm"]
    assert len(dm) == 1 and "沒開權限：1 則" in dm[0]["message"] and "#no-summary 而跳過：1 則" in dm[0]["message"]
    store = Store(str(tmp / "thread.sqlite3"))
    assert store.status("p_ok") == "done" and store.status("p_private") == "permission_notified"
    assert store.status("p_optout") == "skipped_opt_out" and store.status("p_announce") is None
    store.close()
    print("2 thread mode ok: replies =", len(replies), "uploads =", len(fake.uploads))

    # 3) 45 頁簡報：關鍵頁必須是實際送出的頁面
    big_msg = replies["p_big"]["message"]
    picked = [int(x) for x in re.findall(r"第 (\d+) 頁", big_msg)]
    assert picked == [2, 3], picked
    print("3 long deck ok: key pages =", picked)

    # 4) 再跑一次：全部去重，不重複發文
    before = len(fake.created)
    run_main(cfg_thread, since_hours=24 * 7)
    assert len(fake.created) == before, "第二次執行不應該再發文"
    print("4 dedupe ok")

    # 5) 同一份簡報隔週重貼（新的貼文 ID）要重新摘要
    fake.add_post("p_repost", f"延期到這週 https://docs.google.com/presentation/d/{ID_OK}/edit", age_min=5)
    run_main(cfg_thread, since_hours=24 * 7)
    assert any(c.get("root_id") == "p_repost" for c in fake.created)
    print("5 repost ok")

    # 6) test_channel 模式：發到測試頻道，附原貼文連結，不進討論串
    fake.created.clear(); fake.uploads.clear()
    run_main(write_cfg("test_channel", "testch.sqlite3"), since_hours=24 * 7)
    posts = [c for c in fake.created if c["channel_id"] == "ch_test"]
    assert len(posts) == len(expected) + 2 and all(not c.get("root_id") for c in posts)
    assert all("/_redirect/pl/p_" in c["message"] for c in posts)
    assert all(u["channel"] == "ch_test" for u in fake.uploads)
    print("6 test-channel mode ok")

    # 6b) --require-test-channel：設定檔寫 thread 也只會發到測試頻道
    fake.created.clear(); fake.uploads.clear()
    run_main(write_cfg("thread", "forced.sqlite3"), since_hours=24 * 7, require_test_channel=True)
    non_dm = [c for c in fake.created if c["channel_id"] != "ch_dm"]
    assert non_dm and all(c["channel_id"] == "ch_test" and not c.get("root_id") for c in non_dm)
    assert all(u["channel"] == "ch_test" for u in fake.uploads)
    print("6b forced test-channel ok")

    # 7) HTML 附件：預設關閉，開啟後（有瀏覽器時）可轉檔
    html_src = src.find_deck_sources(fake.posts["p_html"], enable_html=False)
    assert html_src == []
    if shutil.which("google-chrome") or shutil.which("chromium"):
        try:
            pdf = src.convert_to_pdf(fake.files["f_html"], "html", tmp / "htmlconv")
            pages, _ = src.render_pdf(pdf, tmp / "htmlpages")
            print("7 html conversion ok: pages =", len(pages))
        except src.DeckFetchError as exc:
            print("7 html conversion not available here:", exc.code)

    server.shutdown()
    shutil.rmtree(tmp, ignore_errors=True)
    print("ALL PASS")


if __name__ == "__main__":
    test()
