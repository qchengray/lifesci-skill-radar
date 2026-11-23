from datetime import date
from pathlib import Path
import tempfile
import unittest
from urllib.error import HTTPError

from radar.update import delta, load_catalog, observe, previous_periods, rank, read_history, render_board, report_period, save_snapshot

def row(stars, repo_id=1):
    return {"stars": stars, "status": "ok" if stars is not None else "unavailable", "repo_id": repo_id}

class RadarTests(unittest.TestCase):
    def test_catalog(self):
        sources = load_catalog(Path(__file__).resolve().parents[1])
        self.assertGreaterEqual(len(sources), 10)

    def test_observe_preserves_zero_and_excludes_private(self):
        data = {"id": 42, "visibility": "public", "stargazers_count": 0}
        result = observe({"repo": "a/b"}, None, lambda path, token: data)
        self.assertEqual((result["stars"], result["repo_id"]), (0, 42))
        data["visibility"] = "private"
        self.assertIsNone(observe({"repo": "a/b"}, None, lambda path, token: data)["stars"])

    def test_observe_failure(self):
        def fail(path, token):
            raise HTTPError(path, 403, "", None, None)
        result = observe({"repo": "a/b"}, None, fail)
        self.assertEqual(result["status"], "http_403")
        self.assertIsNone(result["stars"])

    def test_rank_ties_and_zero(self):
        self.assertEqual(rank({"z": row(4), "a": row(4), "b": row(0), "c": row(None)}),
                         {"a": 1, "z": 1, "b": 3})

    def test_delta_requires_identity_and_observations(self):
        self.assertEqual(delta(row(0), row(0)), 0)
        self.assertEqual(delta(row(4), row(2)), -2)
        self.assertIsNone(delta(row(2, 1), row(2, 2)))
        self.assertIsNone(delta(row(None), row(0)))

    def test_calendar_boundaries(self):
        weekly, monthly = previous_periods(date(2027, 1, 4))
        self.assertEqual(weekly, ("weekly", "2026-W53", date(2026, 12, 28), date(2027, 1, 3)))
        self.assertEqual(monthly, ("monthly", "2026-12", date(2026, 12, 1), date(2026, 12, 31)))

    def test_snapshot_and_partial_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            day = date(2026, 11, 19)
            save_snapshot(root, day, {"a/b": row(0)})
            history = read_history(root)
            self.assertEqual(history[day]["a/b"]["stars"], 0)
            report_period(root, history, "weekly", "2026-W47", date(2026, 11, 16), date(2026, 11, 22))
            text = (root / "reports/weekly/2026-W47.md").read_text()
            self.assertIn("1/7", text)
            self.assertIn("非整期", text)
            self.assertIn("暂无两个", text)

    def test_dashboard_requires_same_complete_rank_cohort(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            yesterday = date(2026, 11, 21)
            today = date(2026, 11, 22)
            items = [{"repo": key, "kind":"MCP", "tier":"上游", "track":"x", "use":"x", "evidence":"https://example.org"}
                     for key in ["a/b", "c/d"]]
            history = {yesterday: {"a/b": row(0, 1), "c/d": row(5, 2)}, today: {"a/b": row(1, 1), "c/d": row(None, 2)}}
            render_board(root, items, history)
            line = (root / "catalog/README.md").read_text().splitlines()[7]
            self.assertIn("| 1 | +1 | — | — |", line)

if __name__ == "__main__":
    unittest.main()
