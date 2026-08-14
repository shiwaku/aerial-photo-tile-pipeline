#!/usr/bin/env python3
"""HTTP Range に対応した静的ファイルサーバ（ローカルプレビュー用）。

PMTiles は 1 ファイルの中から必要な範囲だけを Range リクエストで読む。
標準の `python3 -m http.server` は Range を実装しておらず、常に全体を
200 で返すため PMTiles は読めない。ここだけのために最小限を実装する。

Usage: python3 tools/serve_range.py --directory DIR [--port 8080]
"""

from __future__ import annotations

import argparse
import io
import os
import re
import socketserver
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)")


class _RangeFile(io.RawIOBase):
    """先頭から length バイトだけ読ませるラッパー。

    SimpleHTTPRequestHandler.copyfile() は EOF まで読んでしまうため、
    範囲の終端で止める必要がある。
    """

    def __init__(self, fp, length: int):
        self._fp = fp
        self._remaining = length

    def readable(self) -> bool:
        return True

    def read(self, size: int = -1) -> bytes:
        if self._remaining <= 0:
            return b""
        if size is None or size < 0:
            size = self._remaining
        chunk = self._fp.read(min(size, self._remaining))
        self._remaining -= len(chunk)
        return chunk

    def close(self) -> None:
        try:
            self._fp.close()
        finally:
            super().close()


class RangeHTTPRequestHandler(SimpleHTTPRequestHandler):
    extensions_map = {
        **SimpleHTTPRequestHandler.extensions_map,
        ".pmtiles": "application/octet-stream",
        ".webp": "image/webp",
        ".json": "application/json",
        ".geojson": "application/geo+json",
    }

    def end_headers(self) -> None:
        # 範囲リクエストに対応していることをクライアントに知らせる
        self.send_header("Accept-Ranges", "bytes")
        super().end_headers()

    def send_head(self):
        range_header = self.headers.get("Range")
        if not range_header:
            return super().send_head()

        path = self.translate_path(self.path)
        if not os.path.isfile(path):
            return super().send_head()

        match = RANGE_RE.fullmatch(range_header.strip())
        if not match:
            self.send_error(400, "Invalid Range header")
            return None

        size = os.path.getsize(path)
        start_raw, end_raw = match.group(1), match.group(2)

        if start_raw == "":
            # 末尾 N バイト（bytes=-500）
            if end_raw == "":
                self.send_error(400, "Invalid Range header")
                return None
            length = min(int(end_raw), size)
            start, end = size - length, size - 1
        else:
            start = int(start_raw)
            end = int(end_raw) if end_raw else size - 1
            end = min(end, size - 1)

        if start > end or start >= size:
            self.send_response(416)
            self.send_header("Content-Range", f"bytes */{size}")
            self.end_headers()
            return None

        fp = open(path, "rb")
        fp.seek(start)
        self.send_response(206)
        self.send_header("Content-Type", self.guess_type(path))
        self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Content-Length", str(end - start + 1))
        self.end_headers()
        return _RangeFile(fp, end - start + 1)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--directory", required=True)
    p.add_argument("--port", type=int, default=8080)
    args = p.parse_args()

    if not os.path.isdir(args.directory):
        sys.exit(f"ディレクトリがありません: {args.directory}")

    def handler(*a, **kw):
        return RangeHTTPRequestHandler(*a, directory=args.directory, **kw)

    socketserver.TCPServer.allow_reuse_address = True
    with ThreadingHTTPServer(("", args.port), handler) as httpd:
        print(f"Serving {args.directory} on http://localhost:{args.port}/ "
              f"(Range 対応, Ctrl+C で終了)", flush=True)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n終了しました", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
