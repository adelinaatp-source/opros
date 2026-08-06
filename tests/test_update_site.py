import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from update_site import (  # noqa: E402
    Session,
    assert_filter_contract,
    discover_sessions,
    normalize_name,
    refresh_roster,
    render_html,
)


class UpdateSiteTests(unittest.TestCase):
    def test_name_normalization_handles_yo_and_punctuation(self):
        self.assertEqual(normalize_name(" Белозёрова-Светлана "), "белозерова светлана")

    def test_refresh_deduplicates_short_roster_card_by_family(self):
        roster = [
            {"f": "Багрова Виктория Сергеевнв", "d": "Товаровед", "o": "Товароведы", "u": "Коммерческое", "s1": 9, "s2": 9, "s3": 9, "vs": 27, "last": "old"},
            {"f": "Иванов Иван Иванович", "d": "", "o": "Отдел", "u": "Управление", "s1": 1, "s2": 0, "s3": 0, "vs": 1, "last": "old"},
        ]
        sessions = [
            Session("s1", "one", "Багрова Виктория Сергеевна", "", "Товароведы", datetime(2026, 8, 6, tzinfo=timezone.utc), Path("one.md")),
            Session("s3", "two", "Багрова Виктория Сергеевна", "", "Товароведы", datetime(2026, 8, 6, 1, tzinfo=timezone.utc), Path("two.md")),
            Session("s2", "three", "Багрова Виктория", "", "Товароведы", datetime(2026, 8, 6, 2, tzinfo=timezone.utc), Path("three.md")),
        ]

        refreshed, diagnostics = refresh_roster(roster, sessions)

        self.assertEqual(len(refreshed), 2)
        self.assertEqual((refreshed[0]["s1"], refreshed[0]["s2"], refreshed[0]["s3"]), (1, 1, 1))
        self.assertEqual(refreshed[0]["vs"], 3)
        self.assertEqual(refreshed[1]["vs"], 0)
        self.assertEqual(diagnostics["new_people"], [])

    def test_discovery_deduplicates_process_documents_by_session(self):
        temp_root = Path(__file__).resolve().parents[1] / "temp"
        temp_root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temp_root) as temp:
            root = Path(temp)
            folder = root / "общие" / "01A-методология"
            folder.mkdir(parents=True)
            frontmatter = """---
owner: "Иванов Иван Иванович, Аналитик, Отдел"
scenario: process_survey
session_id: session-1
created_at: 2026-08-06T03:00:00Z
---
# Документ
"""
            (folder / "one.md").write_text(frontmatter, encoding="utf-8")
            (folder / "two.md").write_text(frontmatter, encoding="utf-8")

            index_path = root / "source-index.json"
            sessions, diagnostics = discover_sessions(root, index_path=index_path)
            cached_sessions, cached_diagnostics = discover_sessions(root, index_path=index_path)
            (folder / "two.md").write_text(
                frontmatter.replace("session-1", "session-2") + "# Изменено\n",
                encoding="utf-8",
            )
            updated_sessions, updated_diagnostics = discover_sessions(root, index_path=index_path)

        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions, cached_sessions)
        self.assertEqual(diagnostics["duplicate_sessions"], 1)
        self.assertEqual(diagnostics["sessions_by_scenario"], {"s1": 1})
        self.assertEqual(diagnostics["index_misses"], 2)
        self.assertEqual(cached_diagnostics["index_hits"], 2)
        self.assertEqual(cached_diagnostics["index_misses"], 0)
        self.assertEqual(len(updated_sessions), 2)
        self.assertEqual(updated_diagnostics["index_hits"], 1)
        self.assertEqual(updated_diagnostics["index_misses"], 1)

    def test_render_changes_only_data_block_and_snapshot(self):
        roster = [{"f": "Иванов Иван", "s1": 1, "s2": 0, "s3": 0, "vs": 1, "last": ""}]
        original = """<button id="tabs"></button>
<div id="segFilter"><button data-f="all"></button><button data-f="none"></button><button data-f="pass"></button><button data-f="cov"></button></div>
<select id="selUnit"></select><input id="search">
<script>
const _ALL = []
;
const SNAPSHOT = "старый";
let rFilter="all", rQuery="", rUnit="", rSort={};
</script>"""

        rendered = render_html(original, roster, "06.08.2026 в 08:50 (Екб)")
        assert_filter_contract(original, rendered)

        self.assertIn(json.dumps(roster, ensure_ascii=False, separators=(",", ":")), rendered)
        self.assertIn('const SNAPSHOT = "06.08.2026 в 08:50 (Екб)";', rendered)


if __name__ == "__main__":
    unittest.main()
