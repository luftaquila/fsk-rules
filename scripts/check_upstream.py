#!/usr/bin/env python3
"""Check the official KSAE board for Formula rules additions or PDF changes."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from bs4 import BeautifulSoup


ROOT = Path(__file__).resolve().parents[1]
BOARD_URL = "https://www.ksae.org/jajak/bbs/?code=J_rule"
MAX_PDF_BYTES = 20 * 1024 * 1024
USER_AGENT = "fsk-rules-upstream-check/1.0 (+https://github.com/luftaquila/fsk-rules)"


def fetch(url: str, timeout: int = 30) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        final = urllib.parse.urlparse(response.geturl())
        if final.scheme != "https" or final.hostname != "www.ksae.org":
            raise ValueError(f"공식 호스트 밖으로 리디렉션되었습니다: {response.geturl()}")
        length = response.headers.get("Content-Length")
        if length and int(length) > MAX_PDF_BYTES:
            raise ValueError(f"응답이 허용 크기를 초과합니다: {url}")
        contents = response.read(MAX_PDF_BYTES + 1)
        if len(contents) > MAX_PDF_BYTES:
            raise ValueError(f"응답이 허용 크기를 초과합니다: {url}")
        return contents


def classify_title(title: str) -> tuple[int, str] | None:
    compact = " ".join(title.split())
    year_match = re.search(r"\b(20\d{2})\b", compact)
    if not year_match or "Formula" not in compact or any(word in compact for word in ("Baja", "자율주행", "Autonomous")):
        return None
    if "차량기술규정" in compact:
        document = "formula-technical"
    elif "경기진행규정" in compact:
        document = "formula-competition"
    else:
        return None
    return int(year_match.group(1)), document


def parse_board_page(source: bytes, base_url: str = BOARD_URL) -> tuple[list[dict], list[str]]:
    soup = BeautifulSoup(source, "html.parser")
    records: list[dict] = []
    for row in soup.select("table.bbs tbody tr"):
        title_link = row.select_one("td.tit a[href*='number=']")
        download = row.select_one("a[href*='/jajak/func/download.php']")
        if not title_link or not download:
            continue
        title = title_link.get_text(" ", strip=True)
        classification = classify_title(title)
        if not classification:
            continue
        edition, document = classification
        post_url = urllib.parse.urljoin(base_url, title_link.get("href"))
        post_id_match = re.search(r"(?:\?|&)number=(\d+)", post_url)
        if not post_id_match:
            continue
        cells = row.find_all("td", recursive=False)
        published = cells[-1].get_text(" ", strip=True) if cells else ""
        records.append(
            {
                "edition": edition,
                "document": document,
                "title": title,
                "post_id": int(post_id_match.group(1)),
                "post_url": post_url,
                "attachment_url": urllib.parse.urljoin(base_url, download.get("href")),
                "published_date": published,
            }
        )
    pages = sorted(
        {
            urllib.parse.urljoin(base_url, link.get("href"))
            for link in soup.select("ul.pager a[href*='page=']")
        }
    )
    return records, pages


def validate_download_url(url: str) -> None:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != "www.ksae.org" or parsed.path != "/jajak/func/download.php":
        raise ValueError(f"검증되지 않은 첨부 URL: {url}")


def download_pdf(url: str) -> tuple[bytes, str]:
    validate_download_url(url)
    contents = fetch(url)
    if len(contents) > MAX_PDF_BYTES:
        raise ValueError(f"PDF가 {MAX_PDF_BYTES}바이트를 초과합니다: {url}")
    if not contents.startswith(b"%PDF-"):
        raise ValueError(f"PDF 헤더가 없습니다: {url}")
    return contents, "sha256:" + hashlib.sha256(contents).hexdigest()


def collect_candidates(board_url: str = BOARD_URL) -> list[dict]:
    first = fetch(board_url)
    records, pages = parse_board_page(first, board_url)
    visited = {board_url}
    for page in pages:
        if page in visited:
            continue
        visited.add(page)
        page_records, _ = parse_board_page(fetch(page), page)
        records.extend(page_records)
    latest: dict[tuple[int, str], dict] = {}
    for record in records:
        key = (record["edition"], record["document"])
        if key not in latest or record["post_id"] > latest[key]["post_id"]:
            latest[key] = record
    return sorted(latest.values(), key=lambda item: (item["edition"], item["document"]), reverse=True)


def check(catalog: dict, download_dir: Path | None = None) -> dict:
    known = {(item["edition"], item["document"]): item for item in catalog["documents"]}
    latest_edition = int(catalog["latest_edition"])
    candidates = [item for item in collect_candidates() if item["edition"] >= latest_edition]
    observations: list[dict] = []
    changes: list[dict] = []
    for candidate in candidates:
        contents, digest = download_pdf(candidate["attachment_url"])
        candidate["pdf_hash"] = digest
        current = known.get((candidate["edition"], candidate["document"]))
        if current is None:
            candidate["change"] = "new_document"
        elif candidate["post_id"] != current["source"]["post_id"]:
            candidate["change"] = "source_post_changed"
        elif digest != current["source"]["pdf_hash"]:
            candidate["change"] = "source_pdf_changed"
        else:
            candidate["change"] = "unchanged"
        observations.append(candidate)
        if candidate["change"] != "unchanged":
            changes.append(candidate)
            if download_dir:
                download_dir.mkdir(parents=True, exist_ok=True)
                filename = f'{candidate["edition"]}-{candidate["document"]}-{digest[7:19]}.pdf'
                (download_dir / filename).write_bytes(contents)
    return {
        "schema_version": 1,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "board_url": BOARD_URL,
        "status": "changes" if changes else "unchanged",
        "changes": changes,
        "observations": observations,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=ROOT / "rules" / "catalog.json")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--download-dir", type=Path)
    args = parser.parse_args()
    catalog = json.loads(args.catalog.read_text(encoding="utf-8"))
    report = check(catalog, args.download_dir)
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        sys.stdout.write(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
