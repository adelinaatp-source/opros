#!/usr/bin/env python3
"""Обновляет должности реестра из кадрового XLSX без удаления строк и телефонов."""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path, PurePosixPath
from zipfile import ZipFile


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROSTER = PROJECT_ROOT / "data" / "roster.json"
PLACEHOLDERS = {"", "-", "—", "none", "null", "nan", "undefined", "не указано"}
GENERIC_ORG = PLACEHOLDERS | {"скс-ломбард", "скс ломбард"}
NAME_NOISE = {"оп", "то", "старший", "товаровед"}


def normalize(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold().replace("ё", "е")
    text = re.sub(r"[^0-9a-zа-я]+", " ", text)
    return " ".join(text.split())


def family_given_key(value: object) -> str:
    return " ".join(normalize(value).split()[:2])


def meaningful_name_tokens(value: object) -> frozenset[str]:
    return frozenset(token for token in normalize(value).split() if token not in NAME_NOISE)


def clean_text(value: object) -> str:
    text = " ".join(str(value or "").split()).strip(" ,;")
    return "" if normalize(text) in PLACEHOLDERS else text


def _column_number(reference: str) -> int:
    letters = re.match(r"[A-Z]+", reference)
    if not letters:
        raise ValueError(f"Некорректный адрес ячейки: {reference}")
    result = 0
    for char in letters.group(0):
        result = result * 26 + ord(char) - ord("A") + 1
    return result


def read_xlsx_sheet(path: Path, sheet_name: str) -> list[list[object]]:
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    rel_ns = {"r": "http://schemas.openxmlformats.org/package/2006/relationships"}
    doc_rel = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
    with ZipFile(path) as archive:
        shared: list[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            shared = ["".join(node.text or "" for node in item.findall(".//m:t", ns)) for item in root.findall("m:si", ns)]

        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        relation_id = next(
            (sheet.attrib[doc_rel] for sheet in workbook.findall("m:sheets/m:sheet", ns) if sheet.attrib.get("name") == sheet_name),
            None,
        )
        if relation_id is None:
            raise ValueError(f"Лист «{sheet_name}» не найден")
        relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        target = next(
            (item.attrib["Target"] for item in relationships.findall("r:Relationship", rel_ns) if item.attrib.get("Id") == relation_id),
            None,
        )
        if not target:
            raise ValueError(f"Не найден файл листа «{sheet_name}»")
        sheet_path = str(PurePosixPath("xl") / target.lstrip("/")) if not target.startswith("xl/") else target
        sheet = ET.fromstring(archive.read(sheet_path))

        rows: list[list[object]] = []
        for row_node in sheet.findall(".//m:sheetData/m:row", ns):
            values: dict[int, object] = {}
            for cell in row_node.findall("m:c", ns):
                reference = cell.attrib.get("r", "")
                cell_type = cell.attrib.get("t", "")
                value_node = cell.find("m:v", ns)
                if cell_type == "inlineStr":
                    value: object = "".join(node.text or "" for node in cell.findall(".//m:t", ns))
                elif value_node is None:
                    value = ""
                elif cell_type == "s":
                    value = shared[int(value_node.text or 0)]
                else:
                    value = value_node.text or ""
                values[_column_number(reference)] = value
            width = max(values, default=0)
            rows.append([values.get(column, "") for column in range(1, width + 1)])
        return rows


def load_directory(path: Path, sheet_name: str = "Все сотрудники") -> list[dict[str, str]]:
    rows = read_xlsx_sheet(path, sheet_name)
    header_index = next(
        (index for index, row in enumerate(rows) if "ФИО" in row and "Должность" in row),
        None,
    )
    if header_index is None:
        raise ValueError("В XLSX не найдены колонки «ФИО» и «Должность»")
    headers = [clean_text(value) for value in rows[header_index]]
    result: list[dict[str, str]] = []
    for values in rows[header_index + 1 :]:
        row = {header: clean_text(values[index] if index < len(values) else "") for index, header in enumerate(headers) if header}
        if row.get("ФИО"):
            result.append(row)
    return result


def should_replace_org(management: object, department: object) -> bool:
    normalized_management = normalize(management)
    normalized_department = normalize(department)
    return (
        normalized_management in GENERIC_ORG
        or normalized_department in GENERIC_ORG
        or normalized_management == normalized_department
    )


def synchronize_roster(
    roster: list[dict[str, object]],
    directory: list[dict[str, str]],
) -> tuple[list[dict[str, object]], dict[str, object]]:
    by_full: dict[str, dict[str, str]] = {}
    by_pair: dict[str, list[dict[str, str]]] = defaultdict(list)
    for source in directory:
        full_key = normalize(source.get("ФИО"))
        if full_key:
            by_full[full_key] = source
            by_pair[family_given_key(source.get("ФИО"))].append(source)

    refreshed: list[dict[str, object]] = []
    stats = {
        "roster_rows": len(roster),
        "directory_rows": len(directory),
        "matched_exact": 0,
        "matched_family_given": 0,
        "matched_token_subset": 0,
        "unmatched": 0,
        "unmatched_names": [],
        "positions_updated": 0,
        "position_placeholders_cleared": 0,
        "organization_placeholders_replaced": 0,
        "aliases_marked": 0,
        "directory_without_position": [],
    }
    for original in roster:
        row = dict(original)
        row.pop("hr_alias_of", None)
        full_key = normalize(row.get("f"))
        source = by_full.get(full_key)
        match_type = "exact"
        if source is None:
            candidates = by_pair.get(family_given_key(row.get("f")), [])
            source = candidates[0] if len(candidates) == 1 else None
            match_type = "family_given"
        if source is None:
            roster_tokens = meaningful_name_tokens(row.get("f"))
            candidates = [
                candidate
                for candidate in directory
                if len(roster_tokens) >= 2 and roster_tokens <= meaningful_name_tokens(candidate.get("ФИО"))
            ]
            source = candidates[0] if len(candidates) == 1 else None
            match_type = "token_subset"
        if source is None:
            stats["unmatched"] += 1
            stats["unmatched_names"].append(str(row.get("f", "")))
            row.pop("hr_name", None)
            row.pop("hr_match", None)
        else:
            stats[f"matched_{match_type}"] += 1
            row["hr_name"] = source.get("ФИО", "")
            row["hr_match"] = match_type
            source_position = clean_text(source.get("Должность"))
            old_position = clean_text(row.get("d"))
            if source_position:
                if old_position != source_position:
                    stats["positions_updated"] += 1
                row["d"] = source_position
            else:
                if str(row.get("d", "")).strip() and not old_position:
                    stats["position_placeholders_cleared"] += 1
                row["d"] = old_position
                stats["directory_without_position"].append(source.get("ФИО", ""))

            if should_replace_org(row.get("u"), row.get("o")):
                management = clean_text(source.get("Подразделение"))
                department = clean_text(source.get("Отдел"))
                before = (clean_text(row.get("u")), clean_text(row.get("o")))
                if management:
                    row["u"] = management
                if department:
                    row["o"] = department
                if before != (clean_text(row.get("u")), clean_text(row.get("o"))):
                    stats["organization_placeholders_replaced"] += 1

        for key in ("d", "o", "u"):
            cleaned = clean_text(row.get(key))
            if str(row.get(key, "")).strip() and not cleaned:
                if key == "d":
                    stats["position_placeholders_cleared"] += 1
                row[key] = ""
        refreshed.append(row)

    hr_groups: dict[str, list[int]] = defaultdict(list)
    for index, row in enumerate(refreshed):
        if row.get("hr_name"):
            hr_groups[normalize(row.get("hr_name"))].append(index)
    for hr_key, indexes in hr_groups.items():
        if len(indexes) < 2:
            continue
        primary = max(
            indexes,
            key=lambda index: (
                normalize(refreshed[index].get("f")) == hr_key,
                bool(clean_text(refreshed[index].get("d"))),
                bool(clean_text(refreshed[index].get("o"))),
                bool(clean_text(refreshed[index].get("u"))),
                len(str(refreshed[index].get("f", ""))),
                -index,
            ),
        )
        for index in indexes:
            if index != primary:
                refreshed[index]["hr_alias_of"] = refreshed[primary].get("f", "")
                stats["aliases_marked"] += 1

    stats["directory_without_position"] = sorted(set(stats["directory_without_position"]))
    stats["unmatched_names"] = sorted(stats["unmatched_names"])
    if len(refreshed) != len(roster):
        raise AssertionError("Импорт не должен удалять или добавлять строки реестра")
    return refreshed, stats


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("xlsx", type=Path, help="Кадровый файл XLSX")
    parser.add_argument("--roster", type=Path, default=DEFAULT_ROSTER)
    parser.add_argument("--sheet", default="Все сотрудники")
    parser.add_argument("--check", action="store_true", help="Только показать изменения")
    args = parser.parse_args()

    roster = json.loads(args.roster.read_text(encoding="utf-8"))
    if not isinstance(roster, list):
        raise ValueError("data/roster.json должен быть массивом")
    directory = load_directory(args.xlsx, args.sheet)
    refreshed, stats = synchronize_roster(roster, directory)
    changed = refreshed != roster
    if changed and not args.check:
        args.roster.write_text(json.dumps(refreshed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({**stats, "changed": changed, "written": changed and not args.check}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
