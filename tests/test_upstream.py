import unittest

from scripts.check_upstream import classify_title, parse_board_page, validate_download_url


class UpstreamParserTests(unittest.TestCase):
    def test_classifies_only_formula_documents(self):
        self.assertEqual(
            classify_title("2026 대학생 자작자동차대회 - Formula Student Korea 차량기술규정"),
            (2026, "formula-technical"),
        )
        self.assertEqual(
            classify_title("2026 대학생 자작자동차대회 - Formula Student Korea 경기진행규정"),
            (2026, "formula-competition"),
        )
        self.assertIsNone(classify_title("2026 Baja Formula 경기진행규정"))
        self.assertIsNone(classify_title("2026 자율주행 Formula 경기진행규정"))

    def test_parses_board_row_and_pagination(self):
        source = """
        <table class='bbs'><tbody><tr>
          <td>1</td><td class='tit'><a href='/jajak/bbs/?number=71369&amp;mode=view&amp;code=J_rule'>
          <span>2026 Formula Student Korea 경기진행규정</span></a></td>
          <td><a href='/jajak/func/download.php?path=abc'><img alt='pdf'></a></td>
          <td>10</td><td>2026-03-23</td>
        </tr></tbody></table>
        <ul class='pager'><li><a href='/jajak/bbs/index.php?page=2&amp;code=J_rule'>2</a></li></ul>
        """.encode()
        records, pages = parse_board_page(source)
        self.assertEqual(records[0]["post_id"], 71369)
        self.assertEqual(records[0]["document"], "formula-competition")
        self.assertEqual(records[0]["published_date"], "2026-03-23")
        self.assertIn("page=2", pages[0])

    def test_rejects_non_official_download_hosts(self):
        validate_download_url("https://www.ksae.org/jajak/func/download.php?path=abc")
        with self.assertRaises(ValueError):
            validate_download_url("https://example.com/jajak/func/download.php?path=abc")


if __name__ == "__main__":
    unittest.main()
