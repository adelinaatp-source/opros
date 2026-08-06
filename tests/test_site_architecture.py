import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class SiteArchitectureTests(unittest.TestCase):
    def test_site_uses_external_assets_and_data(self) -> None:
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertNotRegex(html, re.compile(r"const\s+_ALL\s*=\s*\["))
        self.assertIn('href="assets/styles.css"', html)
        self.assertIn('src="assets/app.js"', html)
        self.assertLess(max(map(len, html.splitlines())), 800)

        report_path = ROOT / "data" / "report.json"
        details_path = ROOT / "data" / "details.json"
        self.assertTrue(report_path.is_file())
        self.assertTrue(details_path.is_file())

        report = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertEqual(report["schema_version"], 2)
        self.assertIsInstance(report["people"], list)
        self.assertIn("quality", report["summary"])
        self.assertTrue(all("name_check" in person for person in report["people"]))
        self.assertTrue(all("quality" in person for person in report["people"]))
        self.assertTrue(all("conducted_sessions" in person for person in report["people"]))
        self.assertEqual(
            report["summary"]["conducted_sessions"],
            report["summary"]["sessions"] + report["summary"]["partial_sessions"],
        )

    def test_dashboard_uses_conducted_and_clarification_terms(self) -> None:
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        app = (ROOT / "assets" / "app.js").read_text(encoding="utf-8")
        ui = f"{html}\n{app}"

        for marker in (
            "Опрос проведён",
            "Есть вопросы на уточнение",
            "Требуется уточнение",
            "Завершён · требуется уточнение",
            "Полностью закрыто",
            "Закрыто с оговорками",
            "Частично",
            "Открыто",
            "Переадресовано",
        ):
            self.assertIn(marker, ui)

        for obsolete in ("Есть незавершённые", "Незавершён", "Не завершено"):
            self.assertNotIn(obsolete, ui)

    def test_data_files_are_pretty_printed_for_reviewable_diffs(self) -> None:
        for relative in ("data/report.json", "data/details.json", "data/update-status.json"):
            text = (ROOT / relative).read_text(encoding="utf-8")
            self.assertGreater(len(text.splitlines()), 2, relative)
            self.assertLess(max(map(len, text.splitlines())), 1000, relative)


if __name__ == "__main__":
    unittest.main()
