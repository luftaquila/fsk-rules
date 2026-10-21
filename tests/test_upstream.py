import unittest
import urllib.error
from unittest import mock

from scripts.check_upstream import FETCH_ATTEMPTS, classify_title, fetch, parse_board_page, validate_download_url


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


@mock.patch("scripts.check_upstream.time.sleep")
class UpstreamFetchRetryTests(unittest.TestCase):
    url = "https://www.ksae.org/jajak/bbs/?code=J_rule"

    def test_retries_transient_network_errors(self, sleep):
        handshake = urllib.error.URLError(TimeoutError("The handshake operation timed out"))
        with mock.patch("scripts.check_upstream.fetch_once", side_effect=[handshake, TimeoutError(), b"ok"]) as fetch_once:
            self.assertEqual(fetch(self.url), b"ok")
        self.assertEqual(fetch_once.call_count, 3)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [5, 10])

    def test_retries_server_errors(self, sleep):
        unavailable = urllib.error.HTTPError(self.url, 503, "Service Unavailable", None, None)
        self.addCleanup(unavailable.close)
        with mock.patch("scripts.check_upstream.fetch_once", side_effect=[unavailable, b"ok"]):
            self.assertEqual(fetch(self.url), b"ok")

    def test_gives_up_after_final_attempt(self, sleep):
        with mock.patch("scripts.check_upstream.fetch_once", side_effect=TimeoutError()) as fetch_once:
            with self.assertRaises(TimeoutError):
                fetch(self.url)
        self.assertEqual(fetch_once.call_count, FETCH_ATTEMPTS)
        self.assertEqual(sleep.call_count, FETCH_ATTEMPTS - 1)

    def test_does_not_retry_permanent_errors(self, sleep):
        not_found = urllib.error.HTTPError(self.url, 404, "Not Found", None, None)
        self.addCleanup(not_found.close)
        redirected = ValueError("공식 호스트 밖으로 리디렉션되었습니다")
        for error in (not_found, redirected):
            with mock.patch("scripts.check_upstream.fetch_once", side_effect=error) as fetch_once:
                with self.assertRaises(type(error)):
                    fetch(self.url)
            self.assertEqual(fetch_once.call_count, 1)
        sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
