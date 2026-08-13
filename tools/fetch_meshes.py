#!/usr/bin/env python3
"""図郭リスト（CSV）に従ってオルソ画像を一括ダウンロードし、平置きで展開する。

ZIP の中がディレクトリ 1 段に入っている配布形式に対応し、
画像とワールドファイルを出力先へ平置きする（パイプラインは平置きを前提とする）。

既に展開済みの図郭はスキップするため、中断しても再実行でそのまま続けられる。
"""

from __future__ import annotations

import argparse
import csv
import os
import shutil
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed

IMAGE_EXTS = {".tif", ".tiff", ".jpg", ".jpeg", ".png"}
WORLD_EXTS = {".tfw", ".jgw", ".pgw", ".wld", ".prj", ".aux.xml"}


def target_exists(out_dir: str, mesh_no: str) -> bool:
    """その図郭の画像が既に展開済みかどうか。

    大文字小文字・拡張子は問わない。再撮影分が `<図郭コード>_2.tif` のように
    接尾辞付きで配布される場合があるため、前方一致で判定する。
    """
    stem = mesh_no.lower()
    for name in os.listdir(out_dir) if os.path.isdir(out_dir) else []:
        base, ext = os.path.splitext(name)
        if base.lower().startswith(stem) and ext.lower() in IMAGE_EXTS:
            return True
    return False


def download(url: str, dest: str, timeout: int) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "aerial-photo-tile-pipeline"})
    with urllib.request.urlopen(req, timeout=timeout) as r, open(dest, "wb") as f:
        shutil.copyfileobj(r, f)


def extract_flat(zip_path: str, out_dir: str) -> list[str]:
    """ZIP 内の画像・ワールドファイルを階層を潰して out_dir に展開する。"""
    written = []
    with zipfile.ZipFile(zip_path) as z:
        for info in z.infolist():
            if info.is_dir():
                continue
            name = os.path.basename(info.filename)
            if not name:
                continue
            ext = os.path.splitext(name)[1].lower()
            if ext not in IMAGE_EXTS and ext not in WORLD_EXTS:
                continue
            dest = os.path.join(out_dir, name)
            with z.open(info) as src, open(dest, "wb") as dst:
                shutil.copyfileobj(src, dst)
            written.append(name)
    return written


def process(mesh_no: str, url: str, out_dir: str, zip_dir: str, keep_zip: bool, timeout: int) -> tuple[str, str]:
    if target_exists(out_dir, mesh_no):
        return mesh_no, "skip"

    zip_path = os.path.join(zip_dir, f"{mesh_no}.zip")
    try:
        if not (os.path.exists(zip_path) and os.path.getsize(zip_path) > 0):
            tmp = zip_path + ".part"
            download(url, tmp, timeout)
            os.replace(tmp, zip_path)
        written = extract_flat(zip_path, out_dir)
        if not written:
            return mesh_no, "empty（ZIP に画像が入っていません）"
    except urllib.error.HTTPError as e:
        return mesh_no, f"error HTTP {e.code}"
    except (urllib.error.URLError, TimeoutError) as e:
        return mesh_no, f"error {e}"
    except zipfile.BadZipFile:
        os.remove(zip_path)
        return mesh_no, "error 壊れた ZIP（削除したので再実行してください）"

    if not keep_zip:
        os.remove(zip_path)
    return mesh_no, "done"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("mesh_list", help="図郭リスト CSV（mesh_no,url）")
    p.add_argument("--out-dir", required=True, help="展開先（平置き）")
    p.add_argument("--zip-dir", default=None, help="ZIP の一時置き場（既定: <out-dir>/../_zip）")
    p.add_argument("--jobs", type=int, default=4, help="並列ダウンロード数（既定 4）")
    p.add_argument("--limit", type=int, default=None, help="先頭 N 件だけ取得する")
    p.add_argument("--keep-zip", action="store_true", help="展開後も ZIP を残す")
    p.add_argument("--timeout", type=int, default=300)
    args = p.parse_args()

    with open(args.mesh_list, encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if r.get("mesh_no") and r.get("url")]
    if args.limit:
        rows = rows[: args.limit]
    if not rows:
        print("ERROR: 図郭リストが空です", file=sys.stderr)
        return 1

    out_dir = args.out_dir
    zip_dir = args.zip_dir or os.path.join(os.path.dirname(os.path.abspath(out_dir)), "_zip")
    os.makedirs(out_dir, exist_ok=True)
    os.makedirs(zip_dir, exist_ok=True)

    print(f"取得対象: {len(rows)} 図郭 / 並列 {args.jobs} / 展開先 {out_dir}")

    counts = {"done": 0, "skip": 0, "error": 0}
    errors = []
    with ThreadPoolExecutor(max_workers=args.jobs) as ex:
        futures = {
            ex.submit(process, r["mesh_no"], r["url"], out_dir, zip_dir, args.keep_zip, args.timeout): r
            for r in rows
        }
        for i, fut in enumerate(as_completed(futures), 1):
            mesh_no, status = fut.result()
            key = "error" if status.startswith(("error", "empty")) else status
            counts[key] = counts.get(key, 0) + 1
            if key == "error":
                errors.append((mesh_no, status))
            if i % 20 == 0 or i == len(rows):
                # ログにリダイレクトしても進捗が追えるよう毎回フラッシュする
                print(
                    f"  {i}/{len(rows)}  done={counts['done']} "
                    f"skip={counts['skip']} error={counts['error']}",
                    flush=True,
                )

    if not args.keep_zip:
        try:
            os.rmdir(zip_dir)
        except OSError:
            pass

    total = sum(
        os.path.getsize(os.path.join(out_dir, n)) for n in os.listdir(out_dir)
    )
    print(f"完了: done={counts['done']} skip={counts['skip']} error={counts['error']}")
    print(f"展開後サイズ: {total / 1024 / 1024:.1f} MB")
    if errors:
        print("失敗した図郭:", file=sys.stderr)
        for mesh_no, status in errors[:20]:
            print(f"  {mesh_no}: {status}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
