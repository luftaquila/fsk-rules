#!/usr/bin/env python3
"""Download the exact font inputs declared by build-dependencies.json."""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import io
import json
import urllib.request
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def download(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "fsk-rules-build/1"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def verified_download(entry: dict) -> bytes:
    payload = download(entry["url"])
    digest = hashlib.sha256(payload).hexdigest()
    if digest != entry["sha256"]:
        raise ValueError(f'{entry["name"]}: SHA-256 불일치 ({digest})')
    return payload


def install(config_path: Path, output: Path) -> None:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if config.get("schema_version") != 1 or not isinstance(config.get("assets"), list):
        raise ValueError("build-dependencies.json 스키마가 올바르지 않습니다.")
    output.mkdir(parents=True, exist_ok=True)
    installed: set[str] = set()
    for entry in config["assets"]:
        payload = verified_download(entry)
        if "archive_members" not in entry:
            filename = entry["filename"]
            if Path(filename).name != filename or filename in installed:
                raise ValueError(f'{entry["name"]}: 중복 또는 잘못된 파일 이름 ({filename})')
            installed.add(filename)
            (output / filename).write_bytes(payload)
            continue
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            for rule in entry["archive_members"]:
                matches = sorted(name for name in archive.namelist() if fnmatch.fnmatch(name, rule["pattern"]))
                if not matches:
                    raise ValueError(f'{entry["name"]}: archive member 없음 ({rule["pattern"]})')
                for name in matches:
                    filename = Path(name).name
                    if not filename or filename in installed:
                        raise ValueError(f'{entry["name"]}: 중복 또는 잘못된 archive member ({name})')
                    installed.add(filename)
                    (output / filename).write_bytes(archive.read(name))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "build-dependencies.json")
    parser.add_argument("--output", type=Path, default=ROOT / "fonts")
    args = parser.parse_args()
    install(args.config.resolve(), args.output.resolve())


if __name__ == "__main__":
    main()
