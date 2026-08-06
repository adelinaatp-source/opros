import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from update_site import (  # noqa: E402
    Session,
    analyze_document,
    build_payloads,
    clean_person_name,
    discover_sessions,
    extract_answers,
    is_excluded,
    normalize_name,
    refresh_roster,
)


def session(
    field: str,
    session_id: str,
    name: str,
    person_id: str = "42",
    completion_status: str = "completed",
) -> Session:
    return Session(
        scenario_field=field,
        session_id=session_id,
        person_id=person_id,
        name=name,
        role="Аналитик",
        department="Отдел",
        created_at=datetime(2026, 8, 6, tzinfo=timezone.utc),
        source_file=Path(f"{session_id}.md"),
        completion_status=completion_status,
        score=80.0,
        quality="high",
    )


class UpdateSiteTests(unittest.TestCase):
    def test_partial_gap_is_kept_for_details_but_not_counted_as_completed(self):
        roster = [
            {"f": "Иванов Иван Иванович", "d": "Аналитик", "o": "Отдел", "u": "Управление", "t": "T1"},
        ]
        sessions = [
            session(
                "s2",
                "partial-gap",
                "Иванов Иван Иванович",
                completion_status="interrupted-partial",
            ),
        ]

        refreshed, diagnostics = refresh_roster(roster, sessions)
        diagnostics.update({
            "files_seen": 1,
            "unique_sessions": 1,
            "completed_sessions": 0,
            "partial_sessions": 1,
            "sessions_by_scenario": {},
            "all_sessions_by_scenario": {"s2": 1},
            "ignored_files": 0,
            "duplicate_sessions": 0,
            "malformed_files": [],
        })
        report, details, status = build_payloads(refreshed, sessions, diagnostics)

        self.assertEqual((refreshed[0]["s2"], refreshed[0]["vs"]), (0, 0))
        self.assertEqual(report["summary"]["sessions"], 0)
        self.assertEqual(report["summary"]["partial_sessions"], 1)
        self.assertEqual(report["people"][0]["partial_sessions"], 1)
        detail = details["people"]["roster:0"]["sessions"][0]
        self.assertFalse(detail["completed"])
        self.assertEqual(detail["completion_status"], "interrupted-partial")
        self.assertEqual(detail["source_file"], "partial-gap.md")
        self.assertEqual((status["included_sessions"], status["included_partial_sessions"]), (0, 1))

    def test_name_normalization_handles_yo_and_punctuation(self):
        self.assertEqual(normalize_name(" Белозёрова-Светлана "), "белозерова светлана")

    def test_removes_hr_annotations_from_fio(self):
        self.assertEqual(clean_person_name("Ахметьянова Евгения в отпуске до Семеновна"), "Ахметьянова Евгения Семеновна")
        self.assertEqual(clean_person_name("Ахметшина Эльвира Отпуск с Фуатовна"), "Ахметшина Эльвира Фуатовна")
        self.assertEqual(clean_person_name("Гадельшин Вильданотпуск Ильвирович"), "Гадельшин Вильдан Ильвирович")

    def test_couriers_are_excluded_from_dashboard(self):
        self.assertEqual(is_excluded({"f": "Иванов Иван", "d": "Курьер", "o": "Отдел"}), "курьер")
        self.assertEqual(is_excluded({"f": "Иванов Иван", "d": "Аналитик", "o": "Отдел"}), "")

    def test_excluded_people_do_not_change_dashboard_totals(self):
        roster = [
            {"f": "Курьеров Кирилл Кириллович", "d": "Курьер", "o": "Отдел", "u": "Управление", "t": "T1"},
            {"f": "Иванов Иван Иванович", "d": "Аналитик", "o": "Отдел", "u": "Управление", "t": "T1"},
        ]
        sessions = [
            session("s1", "courier", "Курьеров Кирилл Кириллович", person_id="41"),
            session("s2", "analyst", "Иванов Иван Иванович", person_id="42"),
        ]

        refreshed, diagnostics = refresh_roster(roster, sessions)
        diagnostics.update({
            "files_seen": 2,
            "unique_sessions": 2,
            "sessions_by_scenario": {"s1": 1, "s2": 1},
            "ignored_files": 0,
            "duplicate_sessions": 0,
            "malformed_files": [],
        })
        report, _, status = build_payloads(refreshed, sessions, diagnostics)

        self.assertEqual(report["summary"]["sessions"], 1)
        self.assertEqual(report["scenarios"]["s1"]["sessions"], 0)
        self.assertEqual(report["scenarios"]["s2"]["sessions"], 1)
        self.assertEqual((status["unique_sessions"], status["included_sessions"], status["excluded_sessions"]), (2, 1, 1))

    def test_gap_quality_uses_documented_weighted_formula(self):
        meta = {
            "questions_asked": "10",
            "questions_closed": "2",
            "questions_closed_soft": "4",
            "questions_partial": "2",
            "questions_reassigned": "1",
            "questions_open": "1",
            "questions_grounded": "6",
        }
        result = analyze_document(meta, "# Доопрос", "s2")

        self.assertEqual(result["score"], 60.0)
        self.assertEqual(result["quality"], "medium")
        self.assertEqual(dict(result["metrics"])["grounded"], 6)

    def test_extracts_exact_answer_rows_from_gap_table(self):
        body = """# Протокол
## 2. Реестр решений
| ID вопроса | Формулировка | Ответ (конкретика) | Статус |
|---|---|---|---|
| GAP-01 | Кто согласует? | Руководитель отдела. | closed |
"""
        answers = extract_answers(body, "s2")

        self.assertEqual(answers, (("Кто согласует?", "Руководитель отдела.", "closed"),))

    def test_refresh_uses_bitrix_identity_and_does_not_add_duplicate_fio(self):
        roster = [
            {"f": "Иванов Иван Иванович", "d": "", "o": "Отдел", "u": "Управление", "t": "T1"},
            {"f": "Иванов Иван Иванович", "d": "Аналитик", "o": "Отдел", "u": "Управление", "t": "T1"},
        ]
        sessions = [
            session("s1", "one", "Иванов Иван Иванович"),
            session("s2", "two", "Иванов Иван Иванович"),
        ]

        refreshed, diagnostics = refresh_roster(roster, sessions)

        self.assertEqual(len(refreshed), 2)
        self.assertEqual(diagnostics["match_types"], {"duplicate_exact": 1})
        self.assertEqual(diagnostics["new_people"], [])
        self.assertEqual(sum(row["vs"] for row in refreshed), 2)

    def test_conflicting_bitrix_id_does_not_mix_different_people(self):
        roster = [
            {"f": "Иванов Иван Иванович", "d": "", "o": "Отдел", "u": "Управление", "t": "T1"},
            {"f": "Петров Пётр Петрович", "d": "", "o": "Отдел", "u": "Управление", "t": "T1"},
        ]
        sessions = [
            session("s1", "one", "Иванов Иван Иванович", person_id="598"),
            session("s2", "two", "Петров Пётр Петрович", person_id="598"),
        ]

        refreshed, diagnostics = refresh_roster(roster, sessions)

        self.assertEqual(diagnostics["people_in_source"], 2)
        self.assertEqual((refreshed[0]["s1"], refreshed[0]["s2"]), (1, 0))
        self.assertEqual((refreshed[1]["s1"], refreshed[1]["s2"]), (0, 1))

    def test_two_bitrix_ids_for_same_fio_are_summed_without_losing_sessions(self):
        roster = [
            {"f": "Иванов Иван Иванович", "d": "", "o": "Отдел", "u": "Управление", "t": "T1"},
        ]
        sessions = [
            session("s1", "one", "Иванов Иван Иванович", person_id="42"),
            session("s2", "two", "Иванов Иван Иванович", person_id="43"),
        ]

        refreshed, diagnostics = refresh_roster(roster, sessions)

        self.assertEqual(diagnostics["people_in_source"], 2)
        self.assertEqual((refreshed[0]["s1"], refreshed[0]["s2"], refreshed[0]["vs"]), (1, 1, 2))

    def test_discovery_caches_sessions_and_ignored_documents(self):
        project_temp = Path(__file__).resolve().parents[1] / "temp"
        project_temp.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=project_temp) as temp:
            root = Path(temp)
            completed = root / "completed.md"
            completed.write_text(
                """---
owner: "Иванов Иван Иванович, Аналитик, Отдел"
owner_bitrix_id: 42
scenario: process_survey
session_id: session-1
created_at: 2026-08-06T03:00:00Z
confidence: 0.8
---
# Документ
""",
                encoding="utf-8",
            )
            ignored = root / "ignored.md"
            ignored.write_text("# Обычная заметка\n", encoding="utf-8")
            index_path = root / "source-index.json"

            sessions, first = discover_sessions(root, index_path=index_path)
            cached_sessions, second = discover_sessions(root, index_path=index_path)

        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions, cached_sessions)
        self.assertEqual(first["index_misses"], 2)
        self.assertEqual(first["ignored_files"], 1)
        self.assertEqual(second["index_hits"], 2)
        self.assertEqual(second["index_misses"], 0)

    def test_discovery_keeps_partial_gap_session_with_answers(self):
        project_temp = Path(__file__).resolve().parents[1] / "temp"
        project_temp.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=project_temp) as temp:
            root = Path(temp)
            partial = root / "partial-gap.md"
            partial.write_text(
                """---
respondent: "Иванов Иван Иванович, Аналитик, Отдел"
respondent_bitrix_id: 42
scenario: gap_survey
session_status: interrupted-partial
session_id: partial-gap-1
created_at: 2026-08-06T03:00:00Z
questions_asked: 2
questions_closed: 1
questions_partial: 1
---
# Незавершённый доопрос

| № | Вопрос | Ответ | Статус |
|---|---|---|---|
| 1 | Что мешает процессу? | Долгое согласование | Закрыт |
""",
                encoding="utf-8",
            )

            sessions, diagnostics = discover_sessions(root, index_path=None)

        self.assertEqual(len(sessions), 1)
        self.assertFalse(sessions[0].completed)
        self.assertEqual(sessions[0].completion_status, "interrupted-partial")
        self.assertTrue(sessions[0].answers)
        self.assertEqual(diagnostics["completed_sessions"], 0)
        self.assertEqual(diagnostics["partial_sessions"], 1)
        self.assertEqual(diagnostics["ignored_files"], 0)


if __name__ == "__main__":
    unittest.main()
