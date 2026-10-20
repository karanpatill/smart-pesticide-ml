"""Download, verify and extract dataset archives listed in configs/datasets.yaml.

Each source may define a `download` block:
    download:
      url: <direct file URL>
      filename: <archive name>
      sha256: <published checksum>

The file is fetched with parallel HTTP range requests (Mendeley's storage
throttles single connections), resumed per segment if interrupted, verified
against the published SHA-256, then extracted to data/raw/<root>/ with
path-traversal protection. Archives stay in data/raw/_downloads/.

Usage:
  python scripts/download_datasets.py --source fruitnet agrifreshnet
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from tqdm import tqdm

from fruitvision.config import load_config, load_yaml, resolve

CHUNK = 1 << 20


# Cloudflare in front of Mendeley rejects urllib's default User-Agent.
HEADERS = {"User-Agent": "curl/8.9.1", "Accept": "*/*"}


def resolve_final_url(url: str) -> tuple[str, int]:
    """Follow redirects with a 1-byte ranged GET; size comes from Content-Range."""
    req = urllib.request.Request(url, headers=HEADERS | {"Range": "bytes=0-0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.geturl(), int(r.headers["Content-Range"].rsplit("/", 1)[1])


def fetch_segment(url: str, part: Path, start: int, end: int, bar: tqdm, retries: int = 20) -> None:
    for attempt in range(retries):
        have = part.stat().st_size if part.exists() else 0
        if start + have > end:
            return
        req = urllib.request.Request(url, headers=HEADERS | {"Range": f"bytes={start + have}-{end}"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r, open(part, "ab") as f:
                if r.status != 206:
                    raise IOError(f"server ignored range request (HTTP {r.status})")
                while chunk := r.read(CHUNK):
                    f.write(chunk)
                    bar.update(len(chunk))
            if part.stat().st_size == end - start + 1:
                return
        except (OSError, IOError) as e:
            if attempt == retries - 1:
                raise RuntimeError(f"segment {start}-{end} failed: {e}") from e


def parallel_download(url: str, dest: Path, workers: int) -> None:
    final_url, size = resolve_final_url(url)
    if dest.exists() and dest.stat().st_size == size:
        print(f"{dest.name}: already downloaded")
        return
    seg = -(-size // workers)
    ranges = [(i * seg, min(size, (i + 1) * seg) - 1) for i in range(workers)]
    parts = [dest.with_suffix(dest.suffix + f".part{i}") for i in range(workers)]
    done = sum(p.stat().st_size for p in parts if p.exists())
    with tqdm(total=size, initial=done, unit="B", unit_scale=True, desc=dest.name) as bar, \
            ThreadPoolExecutor(workers) as ex:
        futs = [ex.submit(fetch_segment, final_url, p, s, e, bar) for p, (s, e) in zip(parts, ranges)]
        for fu in as_completed(futs):
            fu.result()
    with open(dest, "wb") as out:
        for p in parts:
            with open(p, "rb") as f:
                shutil.copyfileobj(f, out, CHUNK)
    for p in parts:
        p.unlink()


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(CHUNK):
            h.update(chunk)
    return h.hexdigest()


def safe_extract(archive: Path, target: Path) -> int:
    target.mkdir(parents=True, exist_ok=True)
    root = target.resolve()
    n = 0
    with zipfile.ZipFile(archive) as z:
        for m in tqdm(z.infolist(), desc=f"extract {archive.name}"):
            dest = (target / m.filename).resolve()
            if not dest.is_relative_to(root):
                raise RuntimeError(f"unsafe path in archive: {m.filename}")
            if m.is_dir():
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            with z.open(m) as src, open(dest, "wb") as dst:
                shutil.copyfileobj(src, dst, CHUNK)
            n += 1
    return n


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", nargs="+", required=True)
    ap.add_argument("--workers", type=int, default=12)
    args = ap.parse_args()

    cfg = load_config()
    sources = load_yaml(cfg["datasets_config"])["sources"]
    raw_dir = resolve(cfg["paths"]["raw_dir"])
    dl_dir = raw_dir / "_downloads"
    dl_dir.mkdir(parents=True, exist_ok=True)

    for name in args.source:
        spec = sources[name]
        d = spec.get("download")
        if not d:
            raise SystemExit(f"source '{name}' has no download block")
        archive = dl_dir / d["filename"]
        parallel_download(d["url"], archive, args.workers)
        digest = sha256(archive)
        if digest != d["sha256"]:
            raise SystemExit(f"{name}: SHA-256 mismatch\n  got      {digest}\n  expected {d['sha256']}")
        print(f"{name}: checksum OK")
        target = raw_dir / spec["root"]
        if target.exists() and any(target.iterdir()):
            print(f"{name}: {target} not empty, skipping extraction")
            continue
        print(f"{name}: extracted {safe_extract(archive, target)} files to {target}")


if __name__ == "__main__":
    main()
