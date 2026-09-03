import json
import unittest
from pathlib import Path

from bs4 import BeautifulSoup
from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "_site"


@unittest.skipUnless(SITE.exists(), "run build.py before generated-output tests")
class GeneratedOutputTests(unittest.TestCase):
    def load_schema(self, filename):
        return json.loads((ROOT / "schemas" / filename).read_text(encoding="utf-8"))

    def test_manifest_and_indexes_match_published_schemas(self):
        manifest = json.loads((SITE / "rules-manifest.json").read_text(encoding="utf-8"))
        Draft202012Validator(self.load_schema("rules-manifest.schema.json")).validate(manifest)
        index_validator = Draft202012Validator(self.load_schema("rules-index.schema.json"))
        for document in manifest["documents"]:
            index_path = SITE / document["index_path"]
            index = json.loads(index_path.read_text(encoding="utf-8"))
            index_validator.validate(index)
            ids = [rule["id"] for rule in index["rules"]]
            self.assertEqual(len(ids), len(set(ids)))
            self.assertTrue(all(rule["href"] == "#" + rule["id"] for rule in index["rules"]))

    def test_every_indexed_clause_is_an_html_anchor(self):
        manifest = json.loads((SITE / "rules-manifest.json").read_text(encoding="utf-8"))
        for document in manifest["documents"]:
            document_dir = SITE / document["web_path"]
            soup = BeautifulSoup((document_dir / "index.html").read_text(encoding="utf-8"), "html.parser")
            anchors = {str(node["id"]) for node in soup.select("[id]")}
            index = json.loads((document_dir / "rules-index.json").read_text(encoding="utf-8"))
            self.assertFalse({rule["id"] for rule in index["rules"]} - anchors)

    def test_article_index_text_includes_the_normative_body(self):
        index_path = SITE / "2026" / "formula-competition" / "rules-index.json"
        rules = json.loads(index_path.read_text(encoding="utf-8"))["rules"]
        purpose = next(rule for rule in rules if rule["id"] == "formula-competition-1")
        self.assertIn("본 규정은 대학생 자작자동차대회", purpose["text"])
        self.assertGreater(len(purpose["text"]), len("제1조 (목적)"))

    def test_catalog_only_trusts_official_source_urls(self):
        catalog = json.loads((ROOT / "rules" / "catalog.json").read_text(encoding="utf-8"))
        for document in catalog["documents"]:
            source = document["source"]
            self.assertTrue(source["post_url"].startswith("https://www.ksae.org/jajak/bbs/"))
            self.assertTrue(source["attachment_url"].startswith("https://www.ksae.org/jajak/func/download.php?"))
            self.assertRegex(source["pdf_hash"], r"^sha256:[a-f0-9]{64}$")

    def test_reader_preserves_text_spacing_and_uses_native_mathml(self):
        for document in (
            SITE / "2026" / "formula-technical" / "index.html",
            SITE / "2026" / "formula-competition" / "index.html",
        ):
            source = document.read_text(encoding="utf-8")
            self.assertNotIn("MathJax", source)
            self.assertNotIn("FSKASCIITILDE", source)
            self.assertNotRegex(source, r"\[(?:chapter|section|item|fig):[^]]+\]")

        source = (SITE / "2026" / "formula-technical" / "index.html").read_text(encoding="utf-8")
        soup = BeautifulSoup(source, "html.parser")
        self.assertIn("LSD(Limited Slip Differential)", soup.find(id="formula-technical-10-3").get_text(" ", strip=True))
        self.assertIn("제동장치(Brake by wire)", soup.find(id="formula-technical-10-6").get_text(" ", strip=True))
        self.assertIn("0% ~ 100%", soup.find(id="formula-technical-10-8-2").get_text(" ", strip=True))
        self.assertIn("15cm²", soup.find(id="formula-technical-10-9-2").get_text(" ", strip=True))
        self.assertIn("100mm²", soup.find(id="formula-technical-10-9-2").get_text(" ", strip=True))
        self.assertIsNotNone(soup.select_one("#formula-technical-14-1-2 math[display='block']"))
        self.assertEqual(soup.select_one("a[href='#item-TPS-limit']").get_text(strip=True), "제36조 8항 2호 나목")
        self.assertEqual(soup.select_one("#fig-제동등-위치 + p img")["style"], "width:60%")

    def test_home_is_a_plain_document_list(self):
        source = (SITE / "index.html").read_text(encoding="utf-8")
        soup = BeautifulSoup(source, "html.parser")
        self.assertEqual(len(soup.select(".document-row")), 2)
        self.assertEqual(soup.select_one(".home-header .brand")["href"], "./")
        self.assertFalse(soup.select(".rule-card, .status-dot, .eyebrow"))
        self.assertFalse(soup.select(".home-description, .data-files"))
        self.assertNotIn("매년 이어지는 규정", source)
        self.assertNotIn("차량기술규정과 경기진행규정을 연도별로 확인할 수 있습니다.", source)
        pdf_links = soup.select(".document-actions a[href$='.pdf'][target='_blank']")
        self.assertEqual(len(pdf_links), 2)
        self.assertTrue(all(not link.has_attr("download") for link in pdf_links))
        source_links = soup.select(".document-actions a[target='_blank'][rel~='noreferrer']")
        self.assertEqual(len(source_links), 2)
        self.assertTrue(all(link.get_text(strip=True) == "원문" for link in source_links))
        web_links = soup.select(".document-actions a:not([target])")
        self.assertEqual(len(web_links), 2)
        self.assertTrue(all(link.get_text(strip=True) == "웹" for link in web_links))

    def test_reader_has_no_search_and_opens_pdf_in_browser(self):
        source = (SITE / "2026" / "formula-technical" / "index.html").read_text(encoding="utf-8")
        soup = BeautifulSoup(source, "html.parser")
        self.assertIsNone(soup.select_one("#search-toggle, #search-dialog"))
        self.assertIsNone(soup.select_one(".document-meta"))
        self.assertNotIn("2026년판", source)
        pdf_link = soup.select_one(".reader-toolbar a[href$='.pdf']")
        self.assertEqual(pdf_link.get("target"), "_blank")
        self.assertFalse(pdf_link.has_attr("download"))
        theme_button = soup.select_one("#theme-toggle")
        self.assertEqual(theme_button.get("aria-label"), "어두운 테마로 전환")
        self.assertIsNotNone(theme_button.select_one("svg[aria-hidden='true']"))
        toolbar = soup.select_one(".reader-toolbar")
        self.assertEqual(toolbar.select_one(".brand")["href"], "../../")
        toc_button = toolbar.find(recursive=False)
        self.assertEqual(toc_button.get("id"), "toc-toggle")
        self.assertEqual(toc_button.get("aria-label"), "목차")
        self.assertIsNotNone(toc_button.select_one("svg[aria-hidden='true']"))
        self.assertEqual(toc_button.get_text(strip=True), "")

    def test_material_table_has_exactly_three_columns(self):
        source = (SITE / "2026" / "formula-technical" / "index.html").read_text(encoding="utf-8")
        soup = BeautifulSoup(source, "html.parser")
        header = soup.find(string=lambda text: text and text.strip() == "사용 위치")
        table = header.find_parent("table")
        self.assertTrue(table.select("tr"))
        self.assertTrue(all(len(row.find_all(["th", "td"])) == 3 for row in table.select("tr")))


if __name__ == "__main__":
    unittest.main()
