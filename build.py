#!/usr/bin/env python3
"""Catalog-driven PDF, web reader, and rules-index build."""

from __future__ import annotations

import argparse
import html
import json
import shutil
import subprocess
from argparse import Namespace
from pathlib import Path

from tex2html import convert


ROOT = Path(__file__).resolve().parent
CATALOG = ROOT / "rules" / "catalog.json"


def load_catalog() -> dict:
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    keys: set[tuple[int, str]] = set()
    for document in catalog["documents"]:
        key = (int(document["edition"]), document["document"])
        if key in keys:
            raise ValueError(f"중복 카탈로그 문서: {key}")
        keys.add(key)
        for field in ("tex", "entrypoint", "assets", "pdf_source", "aux_source"):
            if not (ROOT / document[field]).exists() and field not in {"pdf_source", "aux_source"}:
                raise FileNotFoundError(f"{field}: {document[field]}")
    return catalog


def compile_pdf(entry: dict) -> None:
    command = [
        "latexmk",
        "-lualatex",
        "-interaction=nonstopmode",
        "-halt-on-error",
        entry["entrypoint"],
    ]
    try:
        subprocess.run(command, cwd=ROOT, check=True)
    except FileNotFoundError as error:
        raise SystemExit("latexmk가 필요합니다. 또는 CI에서 --skip-pdf를 사용하세요.") from error


def public_document(entry: dict) -> dict:
    base = f'{entry["edition"]}/{entry["document"]}'
    return {
        "edition": entry["edition"],
        "document": entry["document"],
        "title": entry["title"],
        "short_title": entry["short_title"],
        "effective_date": entry["effective_date"],
        "web_path": f"{base}/",
        "pdf_path": f'{base}/{entry["pdf_filename"]}',
        "index_path": f"{base}/rules-index.json",
        "source": {
            key: entry["source"][key]
            for key in ("status", "post_id", "published_date", "post_url", "pdf_hash")
        },
    }


def render_home(catalog: dict) -> str:
    editions: dict[int, list[dict]] = {}
    for entry in sorted(catalog["documents"], key=lambda item: (-item["edition"], item["document"])):
        editions.setdefault(int(entry["edition"]), []).append(entry)

    edition_sections = []
    for edition, entries in editions.items():
        documents = []
        for entry in entries:
            base = f"{entry['edition']}/{entry['document']}"
            documents.append(
                f"""<li class="document-row">
  <div class="document-name">
    <h3>{html.escape(entry['short_title'])}</h3>
    <p>{html.escape(entry['title'])}</p>
  </div>
  <time datetime="{html.escape(entry['effective_date'])}">시행 {html.escape(entry['effective_date'])}</time>
  <div class="document-actions">
    <a href="{html.escape(entry['source']['post_url'])}" target="_blank" rel="noopener noreferrer">원문</a>
    <a href="{base}/">웹</a>
    <a href="{base}/{html.escape(entry['pdf_filename'])}" target="_blank" rel="noopener">PDF</a>
  </div>
</li>"""
            )
        edition_sections.append(
            f"""<section class="edition-section" aria-labelledby="edition-{edition}">
  <h2 id="edition-{edition}">{edition}년</h2>
  <ul class="document-list">{''.join(documents)}</ul>
</section>"""
        )

    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="description" content="Formula Student Korea 규정 아카이브">
  <title>FSK Rules</title>
  <link rel="stylesheet" href="style.css">
  <script defer src="home.js"></script>
</head>
<body class="home-page">
  <header class="home-header"><a class="brand" href="?choose=1">FSK 규정</a></header>
  <main class="home-main">
    <h1>Formula Student Korea 규정</h1>
    <div class="edition-list">{''.join(edition_sections)}</div>
  </main>
</body>
</html>
"""


def render_legacy_redirect(catalog: dict) -> str:
    latest = next(
        entry
        for entry in catalog["documents"]
        if entry["edition"] == catalog["latest_edition"] and entry["document"] == "formula-technical"
    )
    target = f'{latest["edition"]}/{latest["document"]}/'
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="robots" content="noindex"><title>FSK Rules 이동</title></head>
<body><p><a href="{target}">최신 차량기술규정으로 이동</a></p>
<script>location.replace({json.dumps(target)} + location.hash);</script></body></html>
"""


def build(args: argparse.Namespace) -> None:
    catalog = load_catalog()
    output = args.output.resolve()
    if output in {Path("/"), Path.home().resolve(), ROOT}:
        raise ValueError(f"안전하지 않은 출력 디렉터리입니다: {output}")
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)

    for entry in catalog["documents"]:
        if not args.skip_pdf:
            compile_pdf(entry)
        destination = output / str(entry["edition"]) / entry["document"]
        destination.mkdir(parents=True)
        pdf_source = ROOT / entry["pdf_source"]
        if pdf_source.exists():
            shutil.copy2(pdf_source, destination / entry["pdf_filename"])
        elif not args.allow_missing_pdf:
            raise FileNotFoundError(f"PDF가 없습니다: {pdf_source}")
        shutil.copytree(ROOT / entry["assets"], destination / "assets")
        convert(
            Namespace(
                input=ROOT / entry["tex"],
                output=destination / "index.html",
                edition=entry["edition"],
                document=entry["document"],
                title=entry["title"],
                pdf_filename=entry["pdf_filename"],
                asset_dir=ROOT / entry["assets"],
                aux=ROOT / entry["aux_source"],
                index_output=destination / "rules-index.json",
            )
        )

    public_catalog = {
        "schema_version": 1,
        "latest_edition": catalog["latest_edition"],
        "documents": [public_document(entry) for entry in catalog["documents"]],
    }
    (output / "rules-manifest.json").write_text(
        json.dumps(public_catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (output / "index.html").write_text(render_home(catalog), encoding="utf-8")
    (output / "formula.html").write_text(render_legacy_redirect(catalog), encoding="utf-8")
    for filename in ("style.css", "viewer.js", "home.js"):
        shutil.copy2(ROOT / filename, output / filename)
    shutil.copytree(ROOT / "schemas", output / "schemas")
    fonts = ROOT / "fonts"
    if fonts.exists():
        web_fonts = output / "fonts"
        web_fonts.mkdir()
        for filename in (
            "Pretendard-Regular.woff2",
            "Pretendard-Bold.woff2",
            "STIXTwoMath-Regular.woff2",
        ):
            source = fonts / filename
            if source.exists():
                shutil.copy2(source, web_fonts / filename)
    latest_technical = next(
        (
            entry
            for entry in catalog["documents"]
            if entry["edition"] == catalog["latest_edition"] and entry["document"] == "formula-technical"
        ),
        None,
    )
    if latest_technical:
        source = output / str(latest_technical["edition"]) / latest_technical["document"] / latest_technical["pdf_filename"]
        if source.exists():
            shutil.copy2(source, output / "formula.pdf")
    print(f"사이트 빌드 완료: {output}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "_site")
    parser.add_argument("--skip-pdf", action="store_true", help="이미 컴파일된 PDF를 사용")
    parser.add_argument("--allow-missing-pdf", action="store_true", help="HTML 검증용으로 PDF 없이 빌드")
    return parser.parse_args()


if __name__ == "__main__":
    build(parse_args())
