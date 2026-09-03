#!/usr/bin/env python3
"""Validate document versions and package immutable release artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCUMENTS = ("formula-technical", "formula-competition")
DOCUMENT_TAG = re.compile(r"^(formula-technical|formula-competition)-(\d{4})-r([1-9]\d*)$")
SITE_TAG = re.compile(r"^site-(\d{8})\.([1-9]\d*)$")
HASH_PATTERN = re.compile(r"^sha256:[a-f0-9]{64}$")
COMMIT_PATTERN = re.compile(r"^[a-f0-9]{40}$")


def load_catalog(root: Path = ROOT) -> dict:
    catalog = json.loads((root / "rules" / "catalog.json").read_text(encoding="utf-8"))
    validate_catalog(catalog)
    return catalog


def validate_catalog(catalog: dict) -> None:
    if (
        catalog.get("schema_version") != 2
        or not isinstance(catalog.get("latest_edition"), int)
        or not isinstance(catalog.get("documents"), list)
    ):
        raise ValueError("catalog schema_version/latest_edition이 올바르지 않습니다.")
    seen: set[tuple[int, str]] = set()
    documents_by_edition: dict[int, set[str]] = {}
    for entry in catalog.get("documents", []):
        key = (entry.get("edition"), entry.get("document"))
        if key in seen or entry.get("document") not in DOCUMENTS:
            raise ValueError(f"중복되거나 올바르지 않은 문서: {key}")
        if not isinstance(entry.get("edition"), int) or not isinstance(entry.get("revision"), int) or entry["revision"] < 1:
            raise ValueError(f"문서 edition/revision이 올바르지 않습니다: {key}")
        if not HASH_PATTERN.fullmatch(entry.get("source", {}).get("pdf_hash", "")):
            raise ValueError(f"공식 PDF 해시가 올바르지 않습니다: {key}")
        seen.add(key)
        documents_by_edition.setdefault(entry["edition"], set()).add(entry["document"])
    if not seen:
        raise ValueError("catalog에 문서가 없습니다.")
    expected_documents = set(DOCUMENTS)
    incomplete = {
        edition: sorted(expected_documents - documents)
        for edition, documents in documents_by_edition.items()
        if documents != expected_documents
    }
    if incomplete:
        raise ValueError(f"연도별 문서 구성이 완전하지 않습니다: {incomplete}")
    if catalog["latest_edition"] != max(documents_by_edition):
        raise ValueError("latest_edition은 catalog의 가장 최근 연도여야 합니다.")


def validate_source_commit(source_commit: str) -> None:
    if not COMMIT_PATTERN.fullmatch(source_commit):
        raise ValueError("source commit은 40자리 Git SHA여야 합니다.")


def document_version(entry: dict) -> str:
    return f'{entry["edition"]}-r{entry["revision"]}'


def document_tag(entry: dict) -> str:
    return f'{entry["document"]}-{document_version(entry)}'


def git_head(root: Path = ROOT) -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()


def _digest_file(digest, logical_path: str, payload: bytes) -> None:
    encoded = logical_path.encode("utf-8")
    digest.update(len(encoded).to_bytes(4, "big"))
    digest.update(encoded)
    digest.update(len(payload).to_bytes(8, "big"))
    digest.update(payload)


def document_digest(entry: dict, root: Path = ROOT) -> str:
    digest = hashlib.sha256()
    metadata = {key: value for key, value in entry.items() if key not in {"revision", "pdf_source", "aux_source"}}
    _digest_file(digest, "catalog-entry.json", json.dumps(metadata, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode())
    paths = [
        Path(entry["tex"]),
        Path(entry["entrypoint"]),
        Path("template.tex"),
        Path("latexmkrc"),
        Path("tex2html.py"),
        Path("build.py"),
        Path("requirements.txt"),
        Path("build-dependencies.json"),
        Path("scripts/download_build_assets.py"),
        Path("scripts/release_contract.py"),
    ]
    assets = root / entry["assets"]
    paths.extend(path.relative_to(root) for path in sorted(assets.rglob("*")) if path.is_file())
    for relative in sorted(set(paths), key=lambda value: value.as_posix()):
        _digest_file(digest, relative.as_posix(), (root / relative).read_bytes())
    return f"sha256:{digest.hexdigest()}"


def public_document(entry: dict, root: Path = ROOT) -> dict:
    return {
        "revision": entry["revision"],
        "version": document_version(entry),
        "release_tag": document_tag(entry),
        "document_digest": document_digest(entry, root),
    }


def parse_document_tag(tag: str) -> tuple[str, int, int]:
    match = DOCUMENT_TAG.fullmatch(tag)
    if not match:
        raise ValueError(f"올바르지 않은 문서 태그입니다: {tag}")
    return match.group(1), int(match.group(2)), int(match.group(3))


def parse_site_tag(tag: str) -> tuple[str, int]:
    match = SITE_TAG.fullmatch(tag)
    if not match:
        raise ValueError(f"올바르지 않은 사이트 태그입니다: {tag}")
    try:
        datetime.strptime(match.group(1), "%Y%m%d")
    except ValueError as error:
        raise ValueError(f"올바르지 않은 사이트 태그 날짜입니다: {tag}") from error
    return match.group(1), int(match.group(2))


def catalog_entry(catalog: dict, document: str, edition: int) -> dict:
    matches = [entry for entry in catalog["documents"] if entry["document"] == document and entry["edition"] == edition]
    if len(matches) != 1:
        raise ValueError(f"catalog 문서를 정확히 하나 찾을 수 없습니다: {document} {edition}")
    return matches[0]


def validate_built_manifest(
    manifest: dict,
    catalog: dict,
    source_commit: str,
    site_tag: str | None,
    root: Path = ROOT,
) -> None:
    if manifest.get("schema_version") != 2:
        raise ValueError("빌드 manifest는 schema v2여야 합니다.")
    if manifest.get("deployment") != {"site_tag": site_tag, "source_commit": source_commit}:
        raise ValueError("빌드 manifest의 deployment 정보가 릴리스와 일치하지 않습니다.")
    documents = manifest.get("documents")
    if not isinstance(documents, list):
        raise ValueError("빌드 manifest에 documents 배열이 없습니다.")
    actual = {(document.get("edition"), document.get("document")): document for document in documents}
    expected_keys = {(entry["edition"], entry["document"]) for entry in catalog["documents"]}
    if len(actual) != len(documents) or set(actual) != expected_keys:
        raise ValueError("빌드 manifest의 문서 목록이 catalog와 일치하지 않습니다.")
    for entry in catalog["documents"]:
        document = actual[(entry["edition"], entry["document"])]
        expected = public_document(entry, root)
        if any(document.get(key) != value for key, value in expected.items()):
            raise ValueError(f'빌드 manifest의 문서 버전이 catalog와 일치하지 않습니다: {entry["document"]}')


def release_manifest_url(repository: str, tag: str) -> str:
    return f"https://github.com/{repository}/releases/download/{tag}/{tag}-release.json"


def fetch_json(url: str) -> dict:
    headers = {"Accept": "application/octet-stream", "User-Agent": "fsk-rules-release/1"}
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as response:
        return json.load(response)


def document_release_digest(manifest: dict, tag: str) -> str:
    document = manifest.get("document", {})
    digest = manifest.get("document_digest")
    if (
        manifest.get("schema_version") != 1
        or manifest.get("release_tag") != tag
        or not isinstance(manifest.get("source_commit"), str)
        or not COMMIT_PATTERN.fullmatch(manifest["source_commit"])
        or not isinstance(digest, str)
        or not HASH_PATTERN.fullmatch(digest)
        or document.get("release_tag") != tag
        or document.get("document_digest") != digest
    ):
        raise ValueError(f"Release manifest가 손상되었습니다: {tag}")
    return digest


def version_state(catalog: dict, tags: list[str], manifests: dict[str, dict], root: Path = ROOT) -> list[dict]:
    results = []
    for entry in catalog["documents"]:
        prefix = f'{entry["document"]}-{entry["edition"]}-r'
        released = sorted(
            (int(tag.removeprefix(prefix)), tag)
            for tag in tags
            if tag.startswith(prefix) and tag.removeprefix(prefix).isdigit()
        )
        revisions = [revision for revision, _ in released]
        if revisions and revisions != list(range(1, revisions[-1] + 1)):
            raise ValueError(f'문서 태그가 연속적이지 않습니다: {entry["document"]} {revisions}')
        current_digest = document_digest(entry, root)
        if not released:
            if entry["revision"] != 1:
                raise ValueError(f'{entry["document"]} {entry["edition"]}: 최초 revision은 1이어야 합니다.')
            state = "initial"
        else:
            last_revision, last_tag = released[-1]
            for _, released_tag in released:
                if released_tag not in manifests:
                    raise ValueError(f"Release manifest가 없습니다: {released_tag}")
                document_release_digest(manifests[released_tag], released_tag)
            previous_digest = document_release_digest(manifests[last_tag], last_tag)
            expected = last_revision if current_digest == previous_digest else last_revision + 1
            if entry["revision"] != expected:
                change = "변경되지 않았" if current_digest == previous_digest else "변경되었"
                raise ValueError(f'{entry["document"]} digest가 {change}지만 revision은 {entry["revision"]}입니다. 기대값: {expected}')
            state = "released" if expected == last_revision else "candidate"
        results.append({"document": entry["document"], "edition": entry["edition"], "revision": entry["revision"], "state": state, "document_digest": current_digest})
    return results


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def deterministic_zip(output: Path, source_root: Path, paths: list[Path]) -> None:
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(paths, key=lambda value: value.as_posix()):
            relative = path.relative_to(source_root).as_posix()
            info = zipfile.ZipInfo(relative, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes())


def package_document(site: Path, output: Path, tag: str, source_commit: str, root: Path = ROOT) -> list[Path]:
    validate_source_commit(source_commit)
    document, edition, revision = parse_document_tag(tag)
    catalog = load_catalog(root)
    entry = catalog_entry(catalog, document, edition)
    if entry["revision"] != revision or document_tag(entry) != tag:
        raise ValueError("태그가 catalog의 문서 revision과 일치하지 않습니다.")
    manifest = json.loads((site / "rules-manifest.json").read_text(encoding="utf-8"))
    validate_built_manifest(manifest, catalog, source_commit, None, root)
    output.mkdir(parents=True, exist_ok=True)
    document_dir = site / str(edition) / document
    pdf = document_dir / entry["pdf_filename"]
    index = document_dir / "rules-index.json"
    if not pdf.is_file() or not index.is_file():
        raise FileNotFoundError("문서 PDF 또는 rules-index.json이 없습니다.")
    pdf_asset = output / f"{tag}.pdf"
    index_asset = output / f"{tag}-rules-index.json"
    shutil.copy2(pdf, pdf_asset)
    shutil.copy2(index, index_asset)
    zip_asset = output / f"{tag}-web.zip"
    archive_paths = [path for path in document_dir.rglob("*") if path.is_file()]
    archive_paths.extend(path for path in (site / "style.css", site / "viewer.js") if path.is_file())
    fonts = site / "fonts"
    if fonts.exists():
        archive_paths.extend(path for path in fonts.rglob("*") if path.is_file())
    deterministic_zip(zip_asset, site, archive_paths)
    release = {
        "schema_version": 1,
        "release_tag": tag,
        "source_commit": source_commit,
        "document": {
            "edition": edition,
            "document": document,
            **public_document(entry, root),
            "source": entry["source"],
        },
        "document_digest": document_digest(entry, root),
        "artifacts": {},
    }
    for path in (pdf_asset, zip_asset, index_asset):
        release["artifacts"][path.name] = {"sha256": f"sha256:{sha256_file(path)}", "size": path.stat().st_size}
    manifest_asset = output / f"{tag}-release.json"
    manifest_asset.write_text(json.dumps(release, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    artifacts = [pdf_asset, zip_asset, index_asset, manifest_asset]
    sums = output / f"{tag}-SHA256SUMS"
    sums.write_text("".join(f"{sha256_file(path)}  {path.name}\n" for path in artifacts), encoding="utf-8")
    return [*artifacts, sums]


def package_site(site: Path, output: Path, tag: str, source_commit: str, root: Path = ROOT) -> list[Path]:
    parse_site_tag(tag)
    validate_source_commit(source_commit)
    manifest = json.loads((site / "rules-manifest.json").read_text(encoding="utf-8"))
    validate_built_manifest(manifest, load_catalog(root), source_commit, tag, root)
    output.mkdir(parents=True, exist_ok=True)
    zip_asset = output / f"{tag}-web.zip"
    deterministic_zip(zip_asset, site, [path for path in site.rglob("*") if path.is_file()])
    manifest_asset = output / f"{tag}-rules-manifest.json"
    shutil.copy2(site / "rules-manifest.json", manifest_asset)
    release = {
        "schema_version": 1,
        "release_tag": tag,
        "source_commit": source_commit,
        "rules_manifest_sha256": f"sha256:{sha256_file(manifest_asset)}",
        "site_archive_sha256": f"sha256:{sha256_file(zip_asset)}",
    }
    release_asset = output / f"{tag}-release.json"
    release_asset.write_text(json.dumps(release, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    artifacts = [zip_asset, manifest_asset, release_asset]
    sums = output / f"{tag}-SHA256SUMS"
    sums.write_text("".join(f"{sha256_file(path)}  {path.name}\n" for path in artifacts), encoding="utf-8")
    return [*artifacts, sums]


def extract_site(archive_path: Path, output: Path) -> None:
    root = output.resolve()
    root.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive_path) as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            target = (root / info.filename).resolve()
            if root not in target.parents:
                raise ValueError(f"사이트 archive 경로가 출력 범위를 벗어났습니다: {info.filename}")
            mode = info.external_attr >> 16
            if mode and (mode & 0o170000) != 0o100000:
                raise ValueError(f"사이트 archive에는 일반 파일만 허용됩니다: {info.filename}")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(info))


def git_tags(root: Path = ROOT) -> list[str]:
    output = subprocess.check_output(["git", "tag", "--list"], cwd=root, text=True)
    return [line for line in output.splitlines() if DOCUMENT_TAG.fullmatch(line)]


def validate_site_tag_sequence(tag: str, tags: list[str]) -> None:
    date, sequence = parse_site_tag(tag)
    current = (int(date), sequence)
    existing = sorted(
        (int(match.group(1)), int(match.group(2)))
        for candidate in tags
        if candidate != tag and (match := SITE_TAG.fullmatch(candidate))
    )
    if existing and current <= existing[-1]:
        raise ValueError(f"site 태그는 기존 태그보다 나중이어야 합니다: {existing[-1]}")
    same_date = [candidate_sequence for candidate_date, candidate_sequence in existing if candidate_date == current[0]]
    expected = list(range(1, sequence))
    if same_date != expected:
        raise ValueError(f"같은 날짜의 site 태그가 연속적이지 않습니다: {same_date}, 기대값 {expected}")


def command_check_catalog(args) -> None:
    catalog = load_catalog(args.root)
    tags = git_tags(args.root)
    manifests = {}
    for tag in tags:
        try:
            manifests[tag] = fetch_json(release_manifest_url(args.repository, tag))
        except Exception as error:
            raise ValueError(f"Release manifest를 불러올 수 없습니다: {tag}") from error
    print(json.dumps(version_state(catalog, tags, manifests, args.root), ensure_ascii=False, indent=2))


def command_check_tag(args) -> None:
    document, edition, revision = parse_document_tag(args.tag)
    entry = catalog_entry(load_catalog(args.root), document, edition)
    if revision != entry["revision"] or args.tag != document_tag(entry):
        raise ValueError("태그와 catalog revision이 일치하지 않습니다.")
    prefix = f"{document}-{edition}-r"
    revisions = sorted(
        int(tag.removeprefix(prefix))
        for tag in git_tags(args.root)
        if tag.startswith(prefix) and tag != args.tag and tag.removeprefix(prefix).isdigit()
    )
    if revisions != list(range(1, revision)):
        raise ValueError(f"이전 문서 태그가 연속적이지 않습니다: {revisions}, 기대값 {list(range(1, revision))}")
    current_digest = document_digest(entry, args.root)
    if revision > 1:
        previous_tag = f"{prefix}{revision - 1}"
        previous = fetch_json(release_manifest_url(args.repository, previous_tag))
        if document_release_digest(previous, previous_tag) == current_digest:
            raise ValueError("문서 digest가 바뀌지 않아 revision을 증가시킬 수 없습니다.")
    print(json.dumps({"tag": args.tag, "document_digest": current_digest}))


def command_check_site(args) -> None:
    all_tags = subprocess.check_output(["git", "tag", "--list"], cwd=args.root, text=True).splitlines()
    validate_site_tag_sequence(args.tag, all_tags)
    catalog = load_catalog(args.root)
    releases = []
    for entry in catalog["documents"]:
        tag = document_tag(entry)
        release = fetch_json(release_manifest_url(args.repository, tag))
        expected_digest = document_digest(entry, args.root)
        if document_release_digest(release, tag) != expected_digest:
            raise ValueError(f"현재 문서와 Release가 일치하지 않습니다: {tag}")
        releases.append({"release_tag": tag, "document_digest": expected_digest})
    print(json.dumps({"site_tag": args.tag, "documents": releases}, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    subparsers = parser.add_subparsers(dest="command", required=True)
    check_catalog = subparsers.add_parser("check-catalog")
    check_catalog.add_argument("--repository", default="luftaquila/fsk-rules")
    check_catalog.set_defaults(handler=command_check_catalog)
    check_tag = subparsers.add_parser("check-tag")
    check_tag.add_argument("--tag", required=True)
    check_tag.add_argument("--repository", default="luftaquila/fsk-rules")
    check_tag.set_defaults(handler=command_check_tag)
    check_site = subparsers.add_parser("check-site")
    check_site.add_argument("--tag", required=True)
    check_site.add_argument("--repository", default="luftaquila/fsk-rules")
    check_site.set_defaults(handler=command_check_site)
    document_package = subparsers.add_parser("package-document")
    document_package.add_argument("--site", type=Path, required=True)
    document_package.add_argument("--output", type=Path, required=True)
    document_package.add_argument("--tag", required=True)
    document_package.add_argument("--source-commit", required=True)
    document_package.set_defaults(handler=lambda args: package_document(args.site, args.output, args.tag, args.source_commit, args.root))
    site_package = subparsers.add_parser("package-site")
    site_package.add_argument("--site", type=Path, required=True)
    site_package.add_argument("--output", type=Path, required=True)
    site_package.add_argument("--tag", required=True)
    site_package.add_argument("--source-commit", required=True)
    site_package.set_defaults(handler=lambda args: package_site(args.site, args.output, args.tag, args.source_commit, args.root))
    site_extract = subparsers.add_parser("extract-site")
    site_extract.add_argument("--archive", type=Path, required=True)
    site_extract.add_argument("--output", type=Path, required=True)
    site_extract.set_defaults(handler=lambda args: extract_site(args.archive, args.output))
    args = parser.parse_args()
    args.root = args.root.resolve()
    args.handler(args)


if __name__ == "__main__":
    main()
