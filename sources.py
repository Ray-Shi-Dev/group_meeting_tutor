# -*- coding: utf-8 -*-
"""
Slide sources: find decks in a post, fetch them as PDF, render each page to PNG.

Supported:
- Google Slides links (native decks, or .pptx files uploaded to Drive)
- Post attachments: PDF, PPTX (needs LibreOffice), HTML (off by default, needs Chrome/Chromium)

Rendering uses poppler (pdftoppm / pdftotext / pdfinfo). Debian/Ubuntu: apt install poppler-utils
"""

from __future__ import annotations

import re
import shutil
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Matched against the raw message, so URLs hidden inside [text](url) links are found too.
GSLIDES_RE = re.compile(r"https?://docs\.google\.com/presentation/d/([A-Za-z0-9_-]{20,})")
OPT_OUT_TAG = "#no-summary"

ATTACHMENT_EXTS = {"pdf": "附加檔案 (PDF)", "pptx": "附加檔案 (PPTX)", "html": "附加檔案 (HTML)", "htm": "附加檔案 (HTML)"}


@dataclass
class DeckSource:
    kind: str        # "gslides" | "attachment"
    ref: str         # Google deck id or Mattermost file id
    label: str       # source type shown to readers and to the model (kept in Chinese)
    ext: str = ""    # attachment extension


class DeckFetchError(Exception):
    """code: PERMISSION | UNSUPPORTED | TOO_LARGE | CONVERT_FAILED | NETWORK | EMPTY"""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def is_opted_out(message: str) -> bool:
    return OPT_OUT_TAG in (message or "").lower()


def find_deck_sources(post: Dict[str, Any], enable_html: bool = False) -> List[DeckSource]:
    """All decks in one post. Posts with only GitHub links, spreadsheets, videos etc. return []."""
    sources: List[DeckSource] = []
    seen = set()
    for deck_id in GSLIDES_RE.findall(post.get("message") or ""):
        if deck_id not in seen:
            seen.add(deck_id)
            sources.append(DeckSource("gslides", deck_id, "Google Slides"))

    files = (post.get("metadata") or {}).get("files") or []
    for info in files:
        ext = (info.get("extension") or "").lower().lstrip(".")
        if ext not in ATTACHMENT_EXTS:
            continue
        if ext in ("html", "htm") and not enable_html:
            continue
        sources.append(DeckSource("attachment", info["id"], ATTACHMENT_EXTS[ext], ext))
    return sources


# ---------------------------------------------------------------------------
# Fetch as PDF
# ---------------------------------------------------------------------------
def _http_get(url: str, max_bytes: int, timeout: int = 60) -> Tuple[bytes, str]:
    req = urllib.request.Request(url, headers={"User-Agent": "lab-slide-summarizer/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read(max_bytes + 1)
            if len(body) > max_bytes:
                raise DeckFetchError("TOO_LARGE")
            return body, resp.geturl()
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403, 404):
            raise DeckFetchError("PERMISSION") from exc
        raise DeckFetchError("NETWORK") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise DeckFetchError("NETWORK") from exc


def fetch_gslides_pdf(
    deck_id: str,
    max_bytes: int,
    work_dir: Path,
    export_base: str = "https://docs.google.com/presentation/d",
    drive_base: str = "https://drive.google.com/uc",
) -> bytes:
    """
    Export a PDF without logging in. If the deck is not shared by link, Google redirects to a
    sign-in page (HTML); anything that does not start with %PDF is treated as PERMISSION.
    For .pptx files uploaded to Drive that cannot be exported directly, download and convert.
    """
    try:
        body, _ = _http_get(f"{export_base}/{deck_id}/export/pdf", max_bytes)
        if body.startswith(b"%PDF"):
            return body
    except DeckFetchError as exc:
        if exc.code not in ("PERMISSION", "NETWORK"):
            raise
        first_error: Optional[DeckFetchError] = exc
    else:
        first_error = None

    try:
        body, _ = _http_get(f"{drive_base}?export=download&id={deck_id}", max_bytes)
    except DeckFetchError as exc:
        raise (first_error or exc)
    if body.startswith(b"%PDF"):
        return body
    if body.startswith(b"PK"):
        return convert_to_pdf(body, "pptx", work_dir)
    raise DeckFetchError("PERMISSION")


def _find_binary(names: Tuple[str, ...]) -> Optional[str]:
    for name in names:
        path = shutil.which(name)
        if path:
            return path
    return None


def convert_to_pdf(data: bytes, ext: str, work_dir: Path, timeout: int = 180) -> bytes:
    """Convert PPTX or HTML to PDF. PDFs are returned as is."""
    ext = ext.lower()
    if ext == "pdf":
        if not data.startswith(b"%PDF"):
            raise DeckFetchError("UNSUPPORTED")
        return data

    work_dir.mkdir(parents=True, exist_ok=True)
    src = work_dir / f"input.{ext}"
    out = work_dir / "input.pdf"
    src.write_bytes(data)
    out.unlink(missing_ok=True)

    if ext == "pptx":
        binary = _find_binary(("soffice", "libreoffice"))
        if not binary:
            raise DeckFetchError("UNSUPPORTED")
        cmd = [binary, "--headless", "--convert-to", "pdf", "--outdir", str(work_dir), str(src)]
    elif ext in ("html", "htm"):
        binary = _find_binary(("chromium", "chromium-browser", "google-chrome"))
        if not binary:
            raise DeckFetchError("UNSUPPORTED")
        cmd = [
            binary, "--headless", "--disable-gpu", "--no-pdf-header-footer",
            f"--print-to-pdf={out}", src.as_uri(),
        ]
    else:
        raise DeckFetchError("UNSUPPORTED")

    try:
        subprocess.run(cmd, capture_output=True, timeout=timeout, check=False, cwd=str(work_dir))
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise DeckFetchError("CONVERT_FAILED") from exc
    if not out.exists() or not out.read_bytes().startswith(b"%PDF"):
        raise DeckFetchError("CONVERT_FAILED")
    return out.read_bytes()


# ---------------------------------------------------------------------------
# PDF -> PNG + text
# ---------------------------------------------------------------------------
def render_pdf(
    pdf_bytes: bytes, out_dir: Path, max_pages: int = 150, width_px: int = 1600
) -> Tuple[List[Path], str]:
    """Return (PNG paths for pages 1..N, extracted text). Pages beyond max_pages are ignored."""
    for tool in ("pdftoppm", "pdftotext", "pdfinfo"):
        if not shutil.which(tool):
            raise DeckFetchError("UNSUPPORTED")

    out_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = out_dir / "deck.pdf"
    pdf_path.write_bytes(pdf_bytes)

    try:
        info = subprocess.run(
            ["pdfinfo", str(pdf_path)], capture_output=True, text=True, timeout=30, check=False
        )
        match = re.search(r"^Pages:\s+(\d+)", info.stdout, flags=re.MULTILINE)
        if info.returncode != 0 or not match:
            raise DeckFetchError("CONVERT_FAILED")
        total = min(int(match.group(1)), max_pages)
        if total < 1:
            raise DeckFetchError("EMPTY")

        subprocess.run(
            ["pdftoppm", "-png", "-scale-to-x", str(width_px), "-scale-to-y", "-1",
             "-f", "1", "-l", str(total), str(pdf_path), str(out_dir / "p")],
            capture_output=True, timeout=300, check=True,
        )
        text = subprocess.run(
            ["pdftotext", "-f", "1", "-l", str(total), "-layout", str(pdf_path), "-"],
            capture_output=True, text=True, timeout=60, check=False,
        ).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        raise DeckFetchError("CONVERT_FAILED") from exc

    # pdftoppm zero-pads by page count (p-1.png, p-01.png, p-001.png); sort by the page number.
    def _page_no(p: Path) -> int:
        return int(p.stem.rsplit("-", 1)[1])

    pages = sorted(out_dir.glob("p-*.png"), key=_page_no)
    if len(pages) != total:
        raise DeckFetchError("CONVERT_FAILED")
    return pages, text
