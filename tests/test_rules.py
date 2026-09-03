import json
import tempfile
import unittest
from pathlib import Path

from bs4 import BeautifulSoup
from jsonschema import Draft202012Validator

from tex2html import (
    LITERAL_TILDE_TOKEN,
    annotate_rules,
    apply_figure_widths,
    broken_internal_references,
    convert_tblr,
    expand_deferred_competition_tail,
    normalize_text,
    preprocess_tex,
    resolve_html_reference_labels,
    strip_color_groups,
    validate_rule_key_labels,
)


ROOT = Path(__file__).resolve().parents[1]


class RuleIndexTests(unittest.TestCase):
    def test_machine_ids_and_citations_follow_article_hierarchy(self):
        fragment = """
        <h1 id="old-chapter">제1장 일반사항</h1>
        <h2 id="old-purpose">제1조 (목적)</h2>
        <p>목적 본문</p>
        <ol><li>첫 항<ol><li>첫 호<ol><li>가목</li></ol></li></ol></li><li>둘째 항</li></ol>
        <span id="rules-index-end"></span>
        <h1>부칙</h1><h2>인덱스 제외</h2><ol><li>제외</li></ol>
        """
        soup, rules = annotate_rules(fragment, 2026, "formula-technical")
        self.assertEqual(
            [rule["id"] for rule in rules],
            [
                "formula-technical-1",
                "formula-technical-1-1",
                "formula-technical-1-1-1",
                "formula-technical-1-1-1-1",
                "formula-technical-1-2",
            ],
        )
        self.assertEqual(rules[3]["citation"], "제1조 1항 1호 가목")
        self.assertEqual(rules[0]["text"], "제1조 (목적) 목적 본문 첫 항 첫 호 가목 둘째 항")
        self.assertTrue(all(rule["content_hash"].startswith("sha256:") for rule in rules))
        self.assertIsNotNone(soup.find(id="old-purpose"))

    def test_hash_does_not_depend_on_edition(self):
        fragment = "<h2>제1조 (목적)</h2><ol><li>같은 내용</li></ol>"
        _, first = annotate_rules(fragment, 2026, "formula-technical")
        _, second = annotate_rules(fragment, 2027, "formula-technical")
        self.assertEqual(first[1]["content_hash"], second[1]["content_hash"])

    def test_rule_key_survives_a_clause_number_change(self):
        first_fragment = """
        <h2>제1조 (제동장치)</h2>
        <ol><li>제동등 <span id="rule-formula-technical.brake-light"></span></li></ol>
        """
        moved_fragment = """
        <h2>제1조 (제동장치)</h2>
        <ol><li>새 조항</li><li>제동등 <span id="rule-formula-technical.brake-light"></span></li></ol>
        """
        first_soup, first = annotate_rules(first_fragment, 2026, "formula-technical")
        moved_soup, moved = annotate_rules(moved_fragment, 2027, "formula-technical")
        first_rule = next(rule for rule in first if rule.get("rule_key") == "formula-technical.brake-light")
        moved_rule = next(rule for rule in moved if rule.get("rule_key") == "formula-technical.brake-light")

        self.assertEqual(first_rule["id"], "formula-technical-1-1")
        self.assertEqual(moved_rule["id"], "formula-technical-1-2")
        self.assertEqual(first_rule["content_hash"], moved_rule["content_hash"])
        self.assertEqual(
            moved_soup.find(id="formula-technical-1-2")["data-rule-key"],
            "formula-technical.brake-light",
        )
        self.assertIsNotNone(first_soup.find(id="rule-formula-technical.brake-light"))

    def test_article_can_have_a_rule_key(self):
        fragment = """
        <h2>제1조 (접지)</h2><div id="rule-formula-technical.grounding"></div>
        <p>접지 본문</p>
        """
        soup, rules = annotate_rules(fragment, 2026, "formula-technical")
        self.assertEqual(rules[0]["rule_key"], "formula-technical.grounding")
        self.assertEqual(soup.find(id="formula-technical-1")["data-rule-key"], "formula-technical.grounding")

        _, repeated_rules = annotate_rules(str(soup), 2026, "formula-technical")
        self.assertEqual(repeated_rules[0]["rule_key"], "formula-technical.grounding")

    def test_duplicate_rule_keys_fail_the_build(self):
        fragment = """
        <h2>제1조 (제동장치)</h2><ol>
          <li>첫째 <span id="rule-formula-technical.brake-light"></span></li>
          <li>둘째 <span id="rule-formula-technical.brake-light"></span></li>
        </ol>
        """
        with self.assertRaisesRegex(ValueError, "중복 영구 규정 키"):
            annotate_rules(fragment, 2026, "formula-technical")

    def test_one_clause_cannot_have_multiple_rule_keys(self):
        fragment = """
        <h2>제1조 (제동장치)</h2><ol><li>제동등
          <span id="rule-formula-technical.brake-light"></span>
          <span id="rule-formula-technical.stop-lamp"></span>
        </li></ol>
        """
        with self.assertRaisesRegex(ValueError, "하나의 조항에 영구 규정 키가 여러 개임"):
            annotate_rules(fragment, 2026, "formula-technical")

    def test_rule_key_must_match_its_document(self):
        fragment = """
        <h2>제1조 (제동장치)</h2><ol>
          <li>제동등 <span id="rule-formula-competition.brake-light"></span></li>
        </ol>
        """
        with self.assertRaisesRegex(ValueError, "문서와 영구 규정 키가 일치하지 않음"):
            annotate_rules(fragment, 2026, "formula-technical")

    def test_latex_rule_key_is_validated_before_label_normalization(self):
        with self.assertRaisesRegex(ValueError, "잘못된 영구 규정 키"):
            validate_rule_key_labels(
                r"\item 제동등\label{rule:formula-technical.brake light}",
                "formula-technical",
            )

        validate_rule_key_labels(
            "% \\label{rule:not-a-real-key}\n"
            r"\item 제동등\label{rule:formula-technical.brake-light}",
            "formula-technical",
        )

    def test_article_hash_covers_its_body(self):
        _, first = annotate_rules("<h2>제1조 (목적)</h2><p>첫 내용</p>", 2026, "formula-technical")
        _, second = annotate_rules("<h2>제1조 (목적)</h2><p>바뀐 내용</p>", 2026, "formula-technical")
        self.assertNotEqual(first[0]["content_hash"], second[0]["content_hash"])

    def test_rule_key_metadata_does_not_change_content_hash(self):
        without_key = '<h2>제1조 (접지)</h2><div id="section-grounding"></div><p>접지 본문</p>'
        with_key = (
            '<h2>제1조 (접지)</h2><div id="section-grounding"></div>'
            '<div id="rule-formula-technical.grounding"></div><p>접지 본문</p>'
        )
        _, first = annotate_rules(without_key, 2026, "formula-technical")
        _, second = annotate_rules(with_key, 2026, "formula-technical")
        self.assertEqual(first[0]["content_hash"], second[0]["content_hash"])

    def test_reference_display_does_not_change_hash(self):
        first = '<h2>제1조 (목적)</h2><p><a href="#formula-technical-2">[section:대상]</a></p>'
        second = '<h2>제1조 (목적)</h2><p><a href="#formula-technical-2">제2조</a></p>'
        _, first_rules = annotate_rules(first, 2026, "formula-technical")
        _, second_rules = annotate_rules(second, 2026, "formula-technical")
        self.assertEqual(first_rules[0]["content_hash"], second_rules[0]["content_hash"])
        self.assertIn("[section:대상]", first_rules[0]["text"])
        self.assertIn("제2조", second_rules[0]["text"])

    def test_text_normalization_is_unicode_and_whitespace_stable(self):
        self.assertEqual(normalize_text("  가\n\t나  "), "가 나")

    def test_color_wrapper_does_not_leave_a_group_around_list_items(self):
        source = "{\\color{blue}\n\\item 새 항목\n}"
        self.assertEqual(strip_color_groups(source), "\n\\item 새 항목\n")

    def test_tblr_does_not_count_escaped_ampersands_as_columns(self):
        source = r"""\begin{tblr}{colspec={|l|l|l|}}
        위치 & 원형 & 각형 \\
        메인 롤 후프 \& 전방 롤 후프 & 25mm & 불가 \\
        \end{tblr}"""
        converted = convert_tblr(source)
        self.assertIn(r"\begin{tabular}{|l|l|l|}", converted)
        self.assertNotIn(r"\begin{tabular}{|l|l|l|l|}", converted)

    def test_competition_tail_expands_after_article_ten(self):
        source = (ROOT / "rules/2026/formula-competition/rules.tex").read_text(encoding="utf-8")
        expanded = expand_deferred_competition_tail(source)
        self.assertLess(expanded.index(r"\section{오토크로스 경기}"), expanded.index(r"\section{내구레이싱 경기}"))
        self.assertNotIn("CompetitionRulesTail", expanded)

    def test_literal_ranges_survive_pandoc_preprocessing(self):
        processed = preprocess_tex("\\begin{document}0\\% \\string~ 100\\%, 15㎠, 100㎟\\end{document}")
        self.assertIn(f"0\\% {LITERAL_TILDE_TOKEN} 100\\%", processed)
        self.assertNotIn(r"\string~", processed)
        self.assertIn("15cm²", processed)
        self.assertIn("100mm²", processed)

    def test_missing_aux_references_are_recovered_from_html_anchors(self):
        fragment = """
        <h2>제1조 (목적)</h2><div id="section-purpose"></div>
        <ol><li>본문 <span id="item-body"></span>
          <ol><li>세부 항목 <span id="item-detail"></span></li></ol>
        </li></ol>
        <p><a href="#section-purpose">1</a></p>
        <p><a href="#item-body">[item:body]</a></p>
        <p><a href="#item-detail">.</a>을 따른다.</p>
        """
        soup, rules = annotate_rules(fragment, 2026, "formula-technical")
        self.assertTrue(resolve_html_reference_labels(soup, rules))
        self.assertEqual(soup.select_one("a[href='#section-purpose']").get_text(), "제1조")
        self.assertEqual(soup.select_one("a[href='#item-body']").get_text(), "제1조 1항")
        self.assertEqual(soup.select_one("a[href='#item-detail']").get_text(), "제1조 1항 1번")

    def test_internal_reference_without_a_target_is_reported(self):
        soup, _ = annotate_rules('<p><a href="#item-missing">1</a></p>', 2026, "formula-technical")
        self.assertEqual(broken_internal_references(soup), ["#item-missing"])

    def test_figure_width_is_not_dependent_on_pandoc(self):
        soup = BeautifulSoup('<p><img src="assets/제동등 위치.jpg"></p>', "html.parser")
        apply_figure_widths(soup, r"\fig{제동등 위치}{formula}{0.6}")
        self.assertEqual(soup.img["style"], "width:60%")


class ContractTests(unittest.TestCase):
    def validator(self, filename):
        schema = json.loads((ROOT / "schemas" / filename).read_text(encoding="utf-8"))
        return Draft202012Validator(schema)

    def test_verified_rule_refs_accept_multiple_references(self):
        payload = {
            "status": "verified",
            "references": [
                {
                    "edition": 2026,
                    "document": "formula-technical",
                    "rule_key": "formula-technical.brake-light",
                    "clause_id": "formula-technical-10-9",
                    "citation": "제10조 9항",
                    "source_hash": "sha256:" + "a" * 64,
                },
                {
                    "edition": 2026,
                    "document": "formula-competition",
                    "rule_key": "formula-competition.vehicle-inspection",
                    "clause_id": "formula-competition-3-1",
                    "citation": "제3조 1항",
                    "source_hash": "sha256:" + "b" * 64,
                },
            ],
        }
        self.validator("rule-refs.schema.json").validate(payload)

    def test_no_direct_rule_requires_empty_references(self):
        valid = {"status": "no_direct_rule", "references": []}
        self.validator("rule-refs.schema.json").validate(valid)
        invalid = {
            "status": "no_direct_rule",
            "references": [{
                "edition": 2026,
                "document": "formula-technical",
                "rule_key": "formula-technical.purpose",
                "clause_id": "formula-technical-1",
                "citation": "제1조",
                "source_hash": "sha256:" + "a" * 64,
            }],
        }
        self.assertTrue(list(self.validator("rule-refs.schema.json").iter_errors(invalid)))

    def test_verified_rule_ref_requires_rule_key(self):
        payload = {
            "status": "verified",
            "references": [{
                "edition": 2026,
                "document": "formula-technical",
                "clause_id": "formula-technical-10-9",
                "citation": "제10조 9항",
                "source_hash": "sha256:" + "a" * 64,
            }],
        }
        self.assertTrue(list(self.validator("rule-refs.schema.json").iter_errors(payload)))


class PdfTemplateTests(unittest.TestCase):
    def test_hanja_fallback_and_missing_glyph_failure_are_enabled(self):
        template = (ROOT / "template.tex").read_text(encoding="utf-8")
        self.assertIn(r"\setmainhanjafont{Noto Sans CJK KR}", template)
        self.assertIn(r"\tracinglostchars=3", template)


if __name__ == "__main__":
    unittest.main()
