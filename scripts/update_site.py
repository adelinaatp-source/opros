#!/usr/bin/env python3
"""Обновляет встроенные данные GitHub Pages из read-only KB-ARM-survey."""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from zoneinfo import ZoneInfo


DEFAULT_SOURCE = Path(r"\\PC-BA2\KB-ARM-survey")
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_HTML = PROJECT_ROOT / "index.html"
DEFAULT_INDEX = PROJECT_ROOT / "temp" / "source-index.json"
EKB_TZ = ZoneInfo("Asia/Yekaterinburg")
INDEX_VERSION = 1

DATA_BLOCK_RE = re.compile(
    r'(?P<prefix>const\s+_ALL\s*=\s*)'
    r'(?P<data>\[.*?\])'
    r'(?P<middle>\s*;\s*\r?\n\s*const\s+SNAPSHOT\s*=\s*)'
    r'"[^"]*"(?P<suffix>\s*;)',
    re.DOTALL,
)

SCENARIOS = {
    "process_survey": ("s1", "owner"),
    "gap_survey": ("s2", "respondent"),
    "workday_photo": ("s3", "сотрудник"),
}


@dataclass(frozen=True)
class Session:
    scenario_field: str
    session_id: str
    name: str
    role: str
    department: str
    created_at: datetime
    source_file: Path


def unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        if value[0] == '"':
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                pass
        return value[1:-1]
    return value


def parse_frontmatter(path: Path) -> dict[str, str]:
    """Читает только простой скалярный YAML front matter, нужный для отчёта."""
    result: dict[str, str] = {}
    with path.open("r", encoding="utf-8-sig", errors="strict") as stream:
        first = stream.readline()
        if first.strip() != "---":
            return {}
        for line in stream:
            if line.strip() == "---":
                return result
            if not line.strip() or line.lstrip().startswith("#") or ":" not in line:
                continue
            key, value = line.split(":", 1)
            key = key.strip()
            if key and not key.startswith("-"):
                result[key] = unquote(value)
    return {}


def load_source_index(index_path: Path, source: Path) -> dict[str, dict[str, object]]:
    try:
        payload = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if payload.get("version") != INDEX_VERSION or payload.get("source") != str(source):
        return {}
    entries = payload.get("entries")
    return entries if isinstance(entries, dict) else {}


def save_source_index(
    index_path: Path,
    source: Path,
    entries: dict[str, dict[str, object]],
) -> None:
    index_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"version": INDEX_VERSION, "source": str(source), "entries": entries}
    temporary = index_path.with_suffix(index_path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
        newline="\n",
    )
    temporary.replace(index_path)


def parse_datetime(value: str, fallback: datetime) -> datetime:
    value = value.strip()
    if not value:
        return fallback.astimezone(timezone.utc)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = datetime.fromisoformat(value[:10])
        except ValueError:
            return fallback.astimezone(timezone.utc)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def split_person(value: str) -> tuple[str, str, str]:
    parts = [part.strip() for part in value.split(",")]
    name = parts[0] if parts else ""
    role = parts[1] if len(parts) > 1 else ""
    department = parts[2] if len(parts) > 2 else ""
    return name, role, department


def department_from(meta: dict[str, str], field: str, owner_department: str) -> str:
    if field == "s1":
        value = owner_department or meta.get("owner_department_path", "")
    elif field == "s2":
        value = meta.get("op", "")
    else:
        value = meta.get("подразделение", "")
    value = value.strip()
    if " / " in value:
        value = value.rsplit(" / ", 1)[-1].strip()
    return value


def role_from(meta: dict[str, str], field: str, owner_role: str) -> str:
    if owner_role:
        return owner_role
    if field == "s3":
        value = meta.get("должность", "")
        return "" if value == "—" else value
    return ""


def discover_sessions(
    source: Path,
    index_path: Path | None = None,
) -> tuple[list[Session], dict[str, object]]:
    if not source.is_dir():
        raise FileNotFoundError(f"Источник недоступен: {source}")

    sessions_by_key: dict[tuple[str, str, str], Session] = {}
    files_seen = 0
    ignored_files = 0
    malformed_files: list[str] = []
    duplicate_sessions = 0
    index_hits = 0
    index_misses = 0
    cached_entries = load_source_index(index_path, source) if index_path else {}
    next_entries: dict[str, dict[str, object]] = {}

    for path in sorted(source.rglob("*.md"), key=lambda item: str(item).casefold()):
        files_seen += 1
        try:
            path_stat = path.stat()
            relative_path = path.relative_to(source).as_posix()
            cached = cached_entries.get(relative_path)
            if (
                cached
                and cached.get("size") == path_stat.st_size
                and cached.get("mtime_ns") == path_stat.st_mtime_ns
                and isinstance(cached.get("meta"), dict)
            ):
                meta = {str(key): str(value) for key, value in cached["meta"].items()}
                index_hits += 1
            else:
                meta = parse_frontmatter(path)
                index_misses += 1
            next_entries[relative_path] = {
                "size": path_stat.st_size,
                "mtime_ns": path_stat.st_mtime_ns,
                "meta": meta,
            }
        except (OSError, UnicodeError) as exc:
            malformed_files.append(f"{path}: {exc}")
            continue

        scenario = meta.get("scenario", "")
        definition = SCENARIOS.get(scenario)
        if not definition:
            ignored_files += 1
            continue
        if scenario == "gap_survey" and meta.get("session_status", "completed").casefold() != "completed":
            ignored_files += 1
            continue

        field, name_key = definition
        name, owner_role, owner_department = split_person(meta.get(name_key, ""))
        name = name.strip()
        session_id = meta.get("session_id", "").strip()
        if not name or not session_id:
            malformed_files.append(str(path))
            continue

        fallback = datetime.fromtimestamp(path_stat.st_mtime, tz=timezone.utc)
        created_at = parse_datetime(meta.get("created_at", meta.get("date", "")), fallback)
        session = Session(
            scenario_field=field,
            session_id=session_id,
            name=name,
            role=role_from(meta, field, owner_role),
            department=department_from(meta, field, owner_department),
            created_at=created_at,
            source_file=path,
        )
        key = (field, session_id, normalize_name(name))
        previous = sessions_by_key.get(key)
        if previous:
            duplicate_sessions += 1
            if session.created_at > previous.created_at:
                sessions_by_key[key] = session
        else:
            sessions_by_key[key] = session

    sessions = sorted(
        sessions_by_key.values(),
        key=lambda item: (item.created_at, item.scenario_field, normalize_name(item.name)),
    )
    if index_path:
        save_source_index(index_path, source, next_entries)
    diagnostics: dict[str, object] = {
        "markdown_files": files_seen,
        "ignored_files": ignored_files,
        "malformed_files": malformed_files,
        "duplicate_sessions": duplicate_sessions,
        "unique_sessions": len(sessions),
        "sessions_by_scenario": dict(Counter(item.scenario_field for item in sessions)),
        "source_index": str(index_path) if index_path else None,
        "index_hits": index_hits,
        "index_misses": index_misses,
    }
    return sessions, diagnostics


def normalize_name(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold().replace("ё", "е")
    value = re.sub(r"[^0-9a-zа-я]+", " ", value, flags=re.IGNORECASE)
    return " ".join(value.split())


def name_tokens(value: str) -> tuple[str, ...]:
    return tuple(normalize_name(value).split())


def family_key(value: str) -> tuple[str, ...]:
    return name_tokens(value)[:2]


def compatible_names(left: str, right: str) -> bool:
    a, b = name_tokens(left), name_tokens(right)
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    return len(shorter) >= 2 and tuple(longer[: len(shorter)]) == tuple(shorter)


def candidate_score(row: dict[str, object]) -> tuple[int, int, str]:
    filled = sum(bool(str(row.get(key, "")).strip()) for key in ("d", "o", "u"))
    return (len(name_tokens(str(row.get("f", "")))), filled, normalize_name(str(row.get("f", ""))))


def select_roster_index(name: str, roster: list[dict[str, object]]) -> tuple[int | None, str]:
    exact = [i for i, row in enumerate(roster) if normalize_name(str(row.get("f", ""))) == normalize_name(name)]
    if len(exact) == 1 and len(name_tokens(name)) >= 3:
        return exact[0], "exact"
    if len(exact) > 1:
        exact.sort(key=lambda i: candidate_score(roster[i]), reverse=True)
        return exact[0], "duplicate-exact"

    key = family_key(name)
    candidates = [i for i, row in enumerate(roster) if key and family_key(str(row.get("f", ""))) == key]
    compatible = [i for i in candidates if compatible_names(name, str(roster[i].get("f", "")))]
    if compatible:
        candidates = compatible
    if not candidates:
        return None, "new"
    if len(candidates) == 1:
        return candidates[0], "family"

    longest = max(len(name_tokens(str(roster[i].get("f", "")))) for i in candidates)
    best = [i for i in candidates if len(name_tokens(str(roster[i].get("f", "")))) == longest]
    distinct = {normalize_name(str(roster[i].get("f", ""))) for i in best}
    if len(distinct) > 1:
        return None, "ambiguous"
    best.sort(key=lambda i: candidate_score(roster[i]), reverse=True)
    return best[0], "family-longest"


def management_by_department(roster: Iterable[dict[str, object]]) -> dict[str, str]:
    choices: dict[str, Counter[str]] = defaultdict(Counter)
    for row in roster:
        department = str(row.get("o", "")).strip()
        management = str(row.get("u", "")).strip()
        if department and management:
            choices[department][management] += 1
    return {department: counts.most_common(1)[0][0] for department, counts in choices.items()}


def refresh_roster(
    roster: list[dict[str, object]], sessions: list[Session]
) -> tuple[list[dict[str, object]], dict[str, object]]:
    refreshed = [dict(row) for row in roster]
    for row in refreshed:
        row.update({"s1": 0, "s2": 0, "s3": 0, "vs": 0, "last": ""})

    by_person: dict[str, list[Session]] = defaultdict(list)
    display_names: dict[str, str] = {}
    for session in sessions:
        key = normalize_name(session.name)
        by_person[key].append(session)
        display_names[key] = session.name

    department_management = management_by_department(refreshed)
    match_types: Counter[str] = Counter()
    new_people: list[str] = []
    ambiguous_people: list[str] = []
    latest_by_roster_index: dict[int, datetime] = {}

    for person_key in sorted(by_person):
        person_sessions = by_person[person_key]
        display_name = display_names[person_key]
        index, match_type = select_roster_index(display_name, refreshed)
        match_types[match_type] += 1
        if index is None and match_type == "ambiguous":
            ambiguous_people.append(display_name)
        if index is None:
            latest_meta = max(person_sessions, key=lambda item: item.created_at)
            department = latest_meta.department or "Не указано"
            row: dict[str, object] = {
                "f": display_name,
                "d": latest_meta.role,
                "o": department,
                "u": department_management.get(department, "Не указано"),
                "t": "T1",
                "s1": 0,
                "s2": 0,
                "s3": 0,
                "vs": 0,
                "last": "",
            }
            refreshed.append(row)
            index = len(refreshed) - 1
            new_people.append(display_name)

        row = refreshed[index]
        latest = max(person_sessions, key=lambda item: item.created_at)
        for field in ("s1", "s2", "s3"):
            row[field] = int(row.get(field, 0)) + sum(
                1 for item in person_sessions if item.scenario_field == field
            )
        row["vs"] = int(row["s1"]) + int(row["s2"]) + int(row["s3"])
        if latest.created_at >= latest_by_roster_index.get(index, datetime.min.replace(tzinfo=timezone.utc)):
            row["last"] = latest.created_at.isoformat(timespec="seconds")
            latest_by_roster_index[index] = latest.created_at
        if not str(row.get("d", "")).strip() and latest.role:
            row["d"] = latest.role
        if not str(row.get("o", "")).strip() and latest.department:
            row["o"] = latest.department
            row["u"] = department_management.get(latest.department, str(row.get("u", "")) or "Не указано")

    source_totals = Counter(item.scenario_field for item in sessions)
    roster_totals = {
        field: sum(int(row.get(field, 0)) for row in refreshed)
        for field in ("s1", "s2", "s3")
    }
    if any(roster_totals[field] != source_totals[field] for field in ("s1", "s2", "s3")):
        raise ValueError(
            f"Не все сессии перенесены в реестр: источник={dict(source_totals)}, "
            f"реестр={roster_totals}"
        )

    diagnostics: dict[str, object] = {
        "people_in_source": len(by_person),
        "match_types": dict(match_types),
        "new_people": new_people,
        "ambiguous_people_added_as_new": ambiguous_people,
        "roster_rows_before": len(roster),
        "roster_rows_after": len(refreshed),
        "sessions_applied_to_roster": roster_totals,
    }
    return refreshed, diagnostics


def snapshot_label(sessions: list[Session]) -> str:
    if not sessions:
        raise ValueError("В источнике нет завершённых сессий поддерживаемых сценариев")
    latest = max(item.created_at for item in sessions).astimezone(EKB_TZ)
    return latest.strftime("%d.%m.%Y в %H:%M (Екб)")


def load_html_data(html: str) -> tuple[re.Match[str], list[dict[str, object]]]:
    match = DATA_BLOCK_RE.search(html)
    if not match:
        raise ValueError("В index.html не найден блок const _ALL / const SNAPSHOT")
    data = json.loads(match.group("data"))
    if not isinstance(data, list) or not all(isinstance(row, dict) for row in data):
        raise ValueError("const _ALL должен содержать JSON-массив объектов")
    return match, data


def render_html(html: str, roster: list[dict[str, object]], snapshot: str) -> str:
    match = DATA_BLOCK_RE.search(html)
    if not match:
        raise ValueError("В index.html не найден блок данных")
    compact = json.dumps(roster, ensure_ascii=False, separators=(",", ":"))
    replacement = (
        match.group("prefix")
        + compact
        + match.group("middle")
        + json.dumps(snapshot, ensure_ascii=False)
        + match.group("suffix")
    )
    return html[: match.start()] + replacement + html[match.end() :]


def assert_filter_contract(before: str, after: str) -> None:
    required = (
        'id="tabs"',
        'id="segFilter"',
        'data-f="all"',
        'data-f="none"',
        'data-f="pass"',
        'data-f="cov"',
        'id="selUnit"',
        'id="search"',
        'rFilter="all"',
        'rUnit',
        'rQuery',
        'rSort',
    )
    for marker in required:
        if marker not in before or marker not in after:
            raise ValueError(f"Нарушен контракт фильтров: отсутствует {marker}")

    normalized_before = DATA_BLOCK_RE.sub("<DATA_BLOCK>", before, count=1)
    normalized_after = DATA_BLOCK_RE.sub("<DATA_BLOCK>", after, count=1)
    if normalized_before != normalized_after:
        raise ValueError("Обновление изменило HTML за пределами _ALL и SNAPSHOT")


def update(
    source: Path,
    html_path: Path,
    check: bool = False,
    index_path: Path | None = DEFAULT_INDEX,
) -> tuple[bool, dict[str, object]]:
    original = html_path.read_text(encoding="utf-8")
    _, roster = load_html_data(original)
    sessions, source_diagnostics = discover_sessions(source, index_path=index_path)
    refreshed, roster_diagnostics = refresh_roster(roster, sessions)
    snapshot = snapshot_label(sessions)
    rendered = render_html(original, refreshed, snapshot)
    assert_filter_contract(original, rendered)

    changed = rendered != original
    if changed and not check:
        html_path.write_text(rendered, encoding="utf-8", newline="\n")

    diagnostics = {
        "source": str(source),
        "html": str(html_path),
        "snapshot": snapshot,
        "changed": changed,
        **source_diagnostics,
        **roster_diagnostics,
    }
    return changed, diagnostics


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--html", type=Path, default=DEFAULT_HTML)
    parser.add_argument("--index", type=Path, default=DEFAULT_INDEX)
    parser.add_argument("--check", action="store_true", help="Проверить и показать результат без записи")
    parser.add_argument("--json", action="store_true", help="Вывести диагностику в JSON")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        changed, diagnostics = update(
            args.source,
            args.html,
            check=args.check,
            index_path=args.index,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(diagnostics, ensure_ascii=False, indent=2))
    else:
        print(
            f"Сессий: {diagnostics['unique_sessions']} "
            f"({diagnostics['sessions_by_scenario']}), людей: {diagnostics['people_in_source']}, "
            f"снимок: {diagnostics['snapshot']}, index.html: "
            f"{'изменится' if args.check and changed else 'обновлён' if changed else 'без изменений'}"
        )
        print(
            f"Индекс источника: {diagnostics['index_hits']} из кэша, "
            f"{diagnostics['index_misses']} перечитано"
        )
        if diagnostics["new_people"]:
            print(f"Добавлены отсутствовавшие в реестре: {len(diagnostics['new_people'])}")
        if diagnostics["malformed_files"]:
            print(f"Файлы с неполными метаданными: {len(diagnostics['malformed_files'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
