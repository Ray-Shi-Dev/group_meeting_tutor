# -*- coding: utf-8 -*-
"""Mattermost REST API v4 的最小用戶端（只用標準函式庫）。"""

from __future__ import annotations

import json
import mimetypes
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional


class MattermostError(Exception):
    def __init__(self, status: int, code: str):
        self.status = status
        self.code = code
        super().__init__(f"mattermost status={status} code={code}")


class MattermostClient:
    def __init__(self, base_url: str, token: str, timeout: int = 30):
        self.base_url = base_url.rstrip("/")
        self._token = token
        self.timeout = timeout

    # ---------- 底層 ----------
    def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: Any = None,
        data: Optional[bytes] = None,
        content_type: Optional[str] = None,
        raw: bool = False,
        max_bytes: Optional[int] = None,
    ) -> Any:
        headers = {"Authorization": f"Bearer {self._token}"}
        if json_body is not None:
            data = json.dumps(json_body).encode("utf-8")
            content_type = "application/json"
        if content_type:
            headers["Content-Type"] = content_type
        req = urllib.request.Request(
            f"{self.base_url}/api/v4{path}", data=data, headers=headers, method=method
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                if raw:
                    body = resp.read((max_bytes or 0) + 1 if max_bytes else -1)
                    if max_bytes and len(body) > max_bytes:
                        raise MattermostError(413, "file_too_large")
                    return body
                return json.loads(resp.read().decode("utf-8") or "null")
        except urllib.error.HTTPError as exc:
            code = "http_error"
            try:
                code = json.loads(exc.read().decode("utf-8")).get("id", code)
            except Exception:
                pass
            raise MattermostError(exc.code, code) from exc
        except urllib.error.URLError as exc:
            raise MattermostError(0, "unreachable") from exc

    # ---------- 使用者 ----------
    def me(self) -> Dict[str, Any]:
        return self._request("GET", "/users/me")

    def user_by_username(self, username: str) -> Dict[str, Any]:
        return self._request("GET", f"/users/username/{urllib.parse.quote(username.lstrip('@'))}")

    # ---------- 貼文 ----------
    def channel_posts_since(self, channel_id: str, since_ms: int) -> List[Dict[str, Any]]:
        """回傳 since_ms 之後有變動的貼文，依建立時間由舊到新排序。"""
        res = self._request("GET", f"/channels/{channel_id}/posts?since={int(since_ms)}")
        posts = list((res or {}).get("posts", {}).values())
        posts.sort(key=lambda p: p.get("create_at", 0))
        return posts

    def create_post(
        self, channel_id: str, message: str, root_id: str = "", file_ids: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        body: Dict[str, Any] = {"channel_id": channel_id, "message": message}
        if root_id:
            body["root_id"] = root_id
        if file_ids:
            body["file_ids"] = file_ids
        return self._request("POST", "/posts", json_body=body)

    def direct_channel_id(self, user_a: str, user_b: str) -> str:
        return self._request("POST", "/channels/direct", json_body=[user_a, user_b])["id"]

    def permalink(self, post_id: str) -> str:
        return f"{self.base_url}/_redirect/pl/{post_id}"

    # ---------- 檔案 ----------
    def file_info(self, file_id: str) -> Dict[str, Any]:
        return self._request("GET", f"/files/{file_id}/info")

    def download_file(self, file_id: str, max_bytes: int) -> bytes:
        return self._request("GET", f"/files/{file_id}", raw=True, max_bytes=max_bytes)

    def upload_files(self, channel_id: str, paths: List[Path]) -> List[str]:
        """上傳檔案到頻道，回傳 file id 清單（順序與輸入相同）。"""
        ids: List[str] = []
        for path in paths:
            boundary = uuid.uuid4().hex
            mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            parts = [
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"channel_id\"\r\n\r\n{channel_id}\r\n".encode(),
                (
                    f"--{boundary}\r\nContent-Disposition: form-data; name=\"files\"; "
                    f"filename=\"{path.name}\"\r\nContent-Type: {mime}\r\n\r\n"
                ).encode(),
                path.read_bytes(),
                f"\r\n--{boundary}--\r\n".encode(),
            ]
            res = self._request(
                "POST", "/files", data=b"".join(parts),
                content_type=f"multipart/form-data; boundary={boundary}",
            )
            ids.append(res["file_infos"][0]["id"])
        return ids
