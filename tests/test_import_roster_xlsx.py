import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from import_roster_xlsx import synchronize_roster  # noqa: E402


class ImportRosterTests(unittest.TestCase):
    def test_updates_position_by_exact_name_without_removing_rows(self):
        roster = [{"f": "Акбашева Юлия Викторовна", "d": "", "u": "Финансовое управление", "o": "Бухгалтерия", "t": "T1"}]
        directory = [{"ФИО": "Акбашева Юлия Викторовна", "Должность": "Старший бухгалтер", "Подразделение": "Финансовое управление", "Отдел": "Отдел учета МФО."}]

        refreshed, stats = synchronize_roster(roster, directory)

        self.assertEqual(len(refreshed), len(roster))
        self.assertEqual(refreshed[0]["d"], "Старший бухгалтер")
        self.assertEqual(refreshed[0]["o"], "Бухгалтерия")
        self.assertEqual(stats["positions_updated"], 1)

    def test_uses_unique_family_and_given_name_for_short_fio(self):
        roster = [{"f": "Исхакова Лилия", "d": "—", "u": "СКС-Ломбард", "o": "СКС-Ломбард", "t": "T1"}]
        directory = [{"ФИО": "Исхакова Лилия Радиславовна", "Должность": "товаровед-кассир ломбарда", "Подразделение": "Коммерческое управление", "Отдел": "Товароведы"}]

        refreshed, stats = synchronize_roster(roster, directory)

        self.assertEqual(refreshed[0]["f"], "Исхакова Лилия")
        self.assertEqual(refreshed[0]["d"], "товаровед-кассир ломбарда")
        self.assertEqual(refreshed[0]["u"], "Коммерческое управление")
        self.assertEqual(refreshed[0]["o"], "Товароведы")
        self.assertEqual(stats["matched_family_given"], 1)

    def test_does_not_guess_when_family_and_given_name_are_ambiguous(self):
        roster = [{"f": "Иванов Иван", "d": "Старая должность", "u": "Управление", "o": "Отдел", "t": "T1"}]
        directory = [
            {"ФИО": "Иванов Иван Иванович", "Должность": "Аналитик"},
            {"ФИО": "Иванов Иван Петрович", "Должность": "Бухгалтер"},
        ]

        refreshed, stats = synchronize_roster(roster, directory)

        self.assertEqual(refreshed, roster)
        self.assertEqual(stats["unmatched"], 1)

    def test_matches_reordered_name_and_ignores_role_noise(self):
        roster = [{"f": "Старший товаровед Диярова Регина Раисовна", "d": "", "u": "Управление", "o": "Отдел", "t": "T1"}]
        directory = [{"ФИО": "Диярова Регина Раисовна", "Должность": "Старший товаровед-кассир ломбарда"}]

        refreshed, stats = synchronize_roster(roster, directory)

        self.assertEqual(refreshed[0]["d"], "Старший товаровед-кассир ломбарда")
        self.assertEqual(stats["matched_token_subset"], 1)

    def test_marks_short_duplicate_as_alias_without_deleting_it(self):
        roster = [
            {"f": "Канагатуллина Зиля Закировна", "d": "", "u": "Управление", "o": "Отдел", "t": "T1"},
            {"f": "Канагатуллина Зиля", "d": "", "u": "Управление", "o": "Отдел", "t": "T1"},
        ]
        directory = [{"ФИО": "Канагатуллина Зиля Закировна", "Должность": "Старший товаровед"}]

        refreshed, stats = synchronize_roster(roster, directory)

        self.assertEqual(len(refreshed), 2)
        self.assertNotIn("hr_alias_of", refreshed[0])
        self.assertEqual(refreshed[1]["hr_alias_of"], "Канагатуллина Зиля Закировна")
        self.assertEqual(stats["aliases_marked"], 1)


if __name__ == "__main__":
    unittest.main()
