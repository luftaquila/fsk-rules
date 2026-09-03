import copy
import hashlib
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import pypandoc
from jsonschema import Draft202012Validator

from scripts.download_build_assets import install, verified_download
from scripts.release_contract import (
    check_rule_key_continuity,
    document_digest,
    extract_site,
    package_document,
    package_site,
    parse_document_tag,
    parse_site_tag,
    validate_catalog,
    validate_site_tag_sequence,
    version_state,
)


ROOT = Path(__file__).resolve().parents[1]
SOURCE_COMMIT = "a" * 40


def source_metadata(post_id: int) -> dict:
    return {
        "status": "verified",
        "post_id": post_id,
        "published_date": "2026-01-02",
        "post_url": f"https://www.ksae.org/jajak/bbs/?number={post_id}",
        "attachment_url": f"https://www.ksae.org/jajak/func/download.php?id={post_id}",
        "pdf_hash": "sha256:" + "1" * 64,
    }


def catalog_entry(document: str, post_id: int) -> dict:
    stem = "formula" if document == "formula-technical" else "competition"
    return {
        "edition": 2026,
        "revision": 1,
        "document": document,
        "title": document,
        "short_title": document,
        "tex": f"rules/2026/{document}/rules.tex",
        "entrypoint": f"{stem}.tex",
        "assets": f"rules/2026/{document}/assets",
        "pdf_source": f"{stem}.pdf",
        "aux_source": f"{stem}.aux",
        "pdf_filename": f"{document}-2026.pdf",
        "effective_date": "2026-01-01",
        "source": source_metadata(post_id),
    }


def make_source_root(root: Path) -> dict:
    catalog = {
        "schema_version": 2,
        "latest_edition": 2026,
        "documents": [
            catalog_entry("formula-technical", 1),
            catalog_entry("formula-competition", 2),
        ],
    }
    (root / "rules").mkdir(parents=True)
    (root / "scripts").mkdir()
    (root / "rules" / "catalog.json").write_text(json.dumps(catalog), encoding="utf-8")
    for entry in catalog["documents"]:
        tex = root / entry["tex"]
        tex.parent.mkdir(parents=True)
        tex.write_text(entry["document"], encoding="utf-8")
        assets = root / entry["assets"]
        assets.mkdir()
        (assets / "figure.txt").write_text(entry["document"], encoding="utf-8")
        (root / entry["entrypoint"]).write_text(entry["document"], encoding="utf-8")
    for relative in (
        "template.tex",
        "latexmkrc",
        "tex2html.py",
        "build.py",
        "requirements.txt",
        "build-dependencies.json",
        "scripts/download_build_assets.py",
        "scripts/release_contract.py",
    ):
        (root / relative).write_text(relative, encoding="utf-8")
    return catalog


def built_manifest(catalog: dict, root: Path, site_tag: str | None) -> dict:
    documents = []
    for entry in catalog["documents"]:
        documents.append(
            {
                "edition": entry["edition"],
                "document": entry["document"],
                "revision": entry["revision"],
                "version": f'{entry["edition"]}-r{entry["revision"]}',
                "release_tag": f'{entry["document"]}-{entry["edition"]}-r{entry["revision"]}',
                "document_digest": document_digest(entry, root),
            }
        )
    return {
        "schema_version": 2,
        "deployment": {"site_tag": site_tag, "source_commit": SOURCE_COMMIT},
        "documents": documents,
    }


class CatalogContractTests(unittest.TestCase):
    def test_source_catalog_matches_its_published_schema(self):
        catalog = json.loads((ROOT / "rules" / "catalog.json").read_text(encoding="utf-8"))
        schema = json.loads((ROOT / "schemas" / "source-catalog.schema.json").read_text(encoding="utf-8"))
        Draft202012Validator(schema).validate(catalog)
        validate_catalog(catalog)

    def test_every_edition_requires_both_documents_and_latest_year(self):
        catalog = {
            "schema_version": 2,
            "latest_edition": 2025,
            "documents": [catalog_entry("formula-technical", 1)],
        }
        with self.assertRaisesRegex(ValueError, "완전하지"):
            validate_catalog(catalog)

        catalog["documents"].append(catalog_entry("formula-competition", 2))
        with self.assertRaisesRegex(ValueError, "latest_edition"):
            validate_catalog(catalog)

    def test_document_and_site_tags_are_strict(self):
        self.assertEqual(parse_document_tag("formula-technical-2026-r12"), ("formula-technical", 2026, 12))
        self.assertEqual(parse_site_tag("site-20260903.2"), ("20260903", 2))
        for invalid in ("formula-technical-2026-r0", "technical-2026-r1", "formula-technical-26-r1"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                parse_document_tag(invalid)
        for invalid in ("site-20260903.0", "site-2026-09-03.1", "site-20261340.1", "20260903.1"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                parse_site_tag(invalid)

    def test_site_tags_are_monotonic_and_daily_sequences_are_contiguous(self):
        validate_site_tag_sequence("site-20260903.2", ["site-20260903.1", "2026"])
        validate_site_tag_sequence("site-20260904.1", ["site-20260903.1", "site-20260903.2"])
        with self.assertRaises(ValueError):
            validate_site_tag_sequence("site-20260902.1", ["site-20260903.1"])
        with self.assertRaises(ValueError):
            validate_site_tag_sequence("site-20260903.3", ["site-20260903.1"])


class RevisionTests(unittest.TestCase):
    def test_digest_ignores_revision_and_generated_pdf_locations(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            entry = make_source_root(root)["documents"][0]
            original = document_digest(entry, root)
            metadata_only = copy.deepcopy(entry)
            metadata_only["revision"] = 99
            metadata_only["pdf_source"] = "another.pdf"
            metadata_only["aux_source"] = "another.aux"
            self.assertEqual(document_digest(metadata_only, root), original)

            (root / entry["tex"]).write_text("changed rule", encoding="utf-8")
            self.assertNotEqual(document_digest(entry, root), original)

    def test_revision_state_requires_exactly_one_bump_for_changed_inputs(self):
        catalog = {
            "schema_version": 2,
            "latest_edition": 2026,
            "documents": [
                catalog_entry("formula-technical", 1),
                catalog_entry("formula-competition", 2),
            ],
        }
        old_digest = "sha256:" + "1" * 64
        new_digest = "sha256:" + "2" * 64
        tag = "formula-technical-2026-r1"
        manifests = {
            tag: {
                "schema_version": 1,
                "release_tag": tag,
                "source_commit": SOURCE_COMMIT,
                "document_digest": old_digest,
                "document": {"release_tag": tag, "document_digest": old_digest},
            }
        }

        with patch("scripts.release_contract.document_digest", return_value=old_digest):
            states = version_state(catalog, [tag], manifests)
        self.assertEqual(states[0]["state"], "released")

        catalog["documents"][0]["revision"] = 2
        with patch("scripts.release_contract.document_digest", return_value=new_digest):
            states = version_state(catalog, [tag], manifests)
        self.assertEqual(states[0]["state"], "candidate")

        with patch("scripts.release_contract.document_digest", return_value=old_digest):
            with self.assertRaisesRegex(ValueError, "기대값: 1"):
                version_state(catalog, [tag], manifests)

        with patch("scripts.release_contract.document_digest", return_value=new_digest):
            with self.assertRaisesRegex(ValueError, "연속적이지"):
                version_state(catalog, [tag, "formula-technical-2026-r3"], manifests)


class RuleKeyContinuityTests(unittest.TestCase):
    def index(self, *keys: str) -> dict:
        return {
            "schema_version": 2,
            "edition": 2026,
            "document": "formula-technical",
            "rules": [{"id": f"formula-technical-{n}", "rule_key": key} for n, key in enumerate(keys, start=1)],
        }

    def test_released_rule_keys_may_only_disappear_when_declared_retired(self):
        entry = catalog_entry("formula-technical", 1)
        previous = self.index("formula-technical.brake-light", "formula-technical.grounding")
        result = check_rule_key_continuity(
            entry, previous, self.index("formula-technical.brake-light", "formula-technical.grounding", "formula-technical.wheels")
        )
        self.assertEqual(result["added"], ["formula-technical.wheels"])
        self.assertEqual(result["retired"], [])

        with self.assertRaisesRegex(ValueError, "선언 없이 제거"):
            check_rule_key_continuity(entry, previous, self.index("formula-technical.brake-light"))

        entry["retired_rule_keys"] = ["formula-technical.grounding"]
        result = check_rule_key_continuity(entry, previous, self.index("formula-technical.brake-light"))
        self.assertEqual(result["retired"], ["formula-technical.grounding"])

        with self.assertRaisesRegex(ValueError, "아직 존재합니다"):
            check_rule_key_continuity(entry, previous, previous)

    def test_catalog_rejects_malformed_retired_rule_keys(self):
        catalog = {
            "schema_version": 2,
            "latest_edition": 2026,
            "documents": [catalog_entry("formula-technical", 1), catalog_entry("formula-competition", 2)],
        }
        catalog["documents"][0]["retired_rule_keys"] = ["formula-technical.brake-light"]
        validate_catalog(catalog)
        for retired in (["formula-competition.brake-light"], ["formula-technical.brake light"], ["a", "a"]):
            catalog["documents"][0]["retired_rule_keys"] = retired
            with self.assertRaisesRegex(ValueError, "retired_rule_keys"):
                validate_catalog(catalog)


class PackagingTests(unittest.TestCase):
    def load_schema(self, filename: str) -> dict:
        return json.loads((ROOT / "schemas" / filename).read_text(encoding="utf-8"))

    def test_document_release_contains_versioned_assets_and_valid_checksums(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            source = workspace / "source"
            site = workspace / "site"
            output = workspace / "release"
            catalog = make_source_root(source)
            entry = catalog["documents"][0]
            document_dir = site / "2026" / "formula-technical"
            document_dir.mkdir(parents=True)
            (document_dir / entry["pdf_filename"]).write_bytes(b"pdf")
            (document_dir / "rules-index.json").write_text('{"rules": []}', encoding="utf-8")
            (document_dir / "index.html").write_text("<html></html>", encoding="utf-8")
            (site / "style.css").write_text("body {}", encoding="utf-8")
            (site / "viewer.js").write_text("", encoding="utf-8")
            (site / "fonts").mkdir()
            (site / "fonts" / "font.woff2").write_bytes(b"font")
            (site / "rules-manifest.json").write_text(
                json.dumps(built_manifest(catalog, source, None)), encoding="utf-8"
            )

            tag = "formula-technical-2026-r1"
            artifacts = package_document(site, output, tag, SOURCE_COMMIT, source)
            self.assertEqual(len(artifacts), 5)
            release = json.loads((output / f"{tag}-release.json").read_text(encoding="utf-8"))
            Draft202012Validator(self.load_schema("document-release.schema.json")).validate(release)
            self.assertEqual(release["document_digest"], release["document"]["document_digest"])
            with zipfile.ZipFile(output / f"{tag}-web.zip") as archive:
                self.assertEqual(
                    set(archive.namelist()),
                    {
                        "2026/formula-technical/formula-technical-2026.pdf",
                        "2026/formula-technical/index.html",
                        "2026/formula-technical/rules-index.json",
                        "fonts/font.woff2",
                        "style.css",
                        "viewer.js",
                    },
                )
            self.assert_checksums(output / f"{tag}-SHA256SUMS", output)

            stale = built_manifest(catalog, source, None)
            stale["documents"][0]["document_digest"] = "sha256:" + "0" * 64
            (site / "rules-manifest.json").write_text(json.dumps(stale), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "문서 버전"):
                package_document(site, workspace / "stale-release", tag, SOURCE_COMMIT, source)

    def test_site_release_round_trips_and_rejects_path_traversal(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            source = workspace / "source"
            site = workspace / "site"
            output = workspace / "release"
            extracted = workspace / "extracted"
            catalog = make_source_root(source)
            site.mkdir()
            manifest = built_manifest(catalog, source, "site-20260903.1")
            (site / "rules-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            (site / "index.html").write_text("published", encoding="utf-8")

            tag = "site-20260903.1"
            package_site(site, output, tag, SOURCE_COMMIT, source)
            release = json.loads((output / f"{tag}-release.json").read_text(encoding="utf-8"))
            Draft202012Validator(self.load_schema("site-release.schema.json")).validate(release)
            self.assert_checksums(output / f"{tag}-SHA256SUMS", output)
            extract_site(output / f"{tag}-web.zip", extracted)
            self.assertEqual((extracted / "index.html").read_text(encoding="utf-8"), "published")

            malicious = workspace / "malicious.zip"
            with zipfile.ZipFile(malicious, "w") as archive:
                archive.writestr("../outside.txt", "no")
            with self.assertRaisesRegex(ValueError, "출력 범위"):
                extract_site(malicious, workspace / "malicious-output")
            self.assertFalse((workspace / "outside.txt").exists())

    def assert_checksums(self, sums_path: Path, directory: Path) -> None:
        for line in sums_path.read_text(encoding="utf-8").splitlines():
            expected, filename = line.split("  ", 1)
            actual = hashlib.sha256((directory / filename).read_bytes()).hexdigest()
            self.assertEqual(actual, expected)


class BuildDependencyTests(unittest.TestCase):
    def test_document_build_toolchain_is_pinned_and_used_by_ci(self):
        dependencies = json.loads((ROOT / "build-dependencies.json").read_text(encoding="utf-8"))
        schema = json.loads((ROOT / "schemas" / "build-dependencies.schema.json").read_text(encoding="utf-8"))
        Draft202012Validator(schema).validate(dependencies)
        toolchain = dependencies["toolchain"]
        workflow = (ROOT / ".github" / "workflows" / "build.yml").read_text(encoding="utf-8")
        requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
        self.assertIn(f'python-version: "{toolchain["python"]}"', workflow)
        self.assertIn(f'latex-action@{toolchain["latex_action"]}', workflow)
        self.assertIn(f'docker_image: {toolchain["texlive_image"]}', workflow)
        self.assertIn(f'pypandoc_binary=={toolchain["pypandoc_binary"]}', requirements)
        self.assertEqual(str(pypandoc.get_pandoc_version()), toolchain["pandoc"])

    def test_downloaded_dependency_must_match_its_declared_hash(self):
        entry = {"name": "font", "url": "https://example.invalid/font", "sha256": "0" * 64}
        with patch("scripts.download_build_assets.download", return_value=b"unexpected"):
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                verified_download(entry)

    def test_archive_members_are_flattened_only_into_the_requested_output(self):
        archive_buffer = io.BytesIO()
        with zipfile.ZipFile(archive_buffer, "w") as archive:
            archive.writestr("nested/font.ttf", b"archive-font")
        config = {
            "schema_version": 1,
            "assets": [
                {"name": "direct", "filename": "direct.otf"},
                {"name": "archive", "archive_members": [{"pattern": "nested/*.ttf"}]},
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "dependencies.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")
            output = root / "output"
            with patch(
                "scripts.download_build_assets.verified_download",
                side_effect=[b"direct-font", archive_buffer.getvalue()],
            ):
                install(config_path, output)
            self.assertEqual((output / "direct.otf").read_bytes(), b"direct-font")
            self.assertEqual((output / "font.ttf").read_bytes(), b"archive-font")
            self.assertEqual(sorted(path.name for path in output.iterdir()), ["direct.otf", "font.ttf"])


if __name__ == "__main__":
    unittest.main()
