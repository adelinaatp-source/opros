#!/usr/bin/env python3
"""Строит быстрый статический отчёт из read-only KB-ARM-survey."""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import unicodedata
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from zoneinfo import ZoneInfo


DEFAULT_SOURCE = Path(r"\\PC-BA2\KB-ARM-survey")
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_HTML = PROJECT_ROOT / "index.html"
DEFAULT_ROSTER = PROJECT_ROOT / "data" / "roster.json"
DEFAULT_REPORT = PROJECT_ROOT / "data" / "report.json"
DEFAULT_DETAILS = PROJECT_ROOT / "data" / "details.json"
DEFAULT_STATUS = PROJECT_ROOT / "data" / "update-status.json"
DEFAULT_INDEX = PROJECT_ROOT / "temp" / "source-index.json"
EKB_TZ = ZoneInfo("Asia/Yekaterinburg")
INDEX_VERSION = 3
SCHEMA_VERSION = 2

LEGACY_DATA_RE = re.compile(r"const\s+_ALL\s*=\s*(?P<data>\[.*?\])\s*;", re.DOTALL)
SCENARIOS = {
    "process_survey": ("s1", "owner", "owner_bitrix_id"),
    "gap_survey": ("s2", "respondent", "respondent_bitrix_id"),
    "workday_photo": ("s3", "сотрудник", "owner_bitrix_id"),
}
SCENARIO_INFO = {
    "s1": {"tag": "Процесс", "name": "Основной опрос по процессу", "metric": "Уверенность описания"},
    "s2": {"tag": "Уточнение", "name": "Доопрос", "metric": "Индекс полноты ответов"},
    "s3": {"tag": "Рабочий день", "name": "Фото рабочего дня", "metric": "Полнота карты дня"},
}
EXCLUDED_NAMES = {
    "Хазиахметова Элина Радиковна",
    "Садовин Александр",
    "Балакин Андрей",
    "Гумеров Радик",
    "Морозов Михаил",
}
TABLE_LINE_RE = re.compile(r"^\s*\|(.+)\|\s*$")
HEADING_RE = re.compile(r"^#{1,4}\s+(.+?)\s*$")
NAME_ANNOTATION_RE = re.compile(
    r"(?:\b\u0432\s+)?\u043e\u0442\u043f\u0443\u0441\u043a(?:\u0435)?(?:\s+(?:\u0441|\u0434\u043e))?\b|"
    r"\b(?:\u0432\s+)?\u0434\u0435\u043a\u0440\u0435\u0442(?:\u0435)?\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Session:
    scenario_field: str
    session_id: str
    person_id: str
    name: str
    role: str
    department: str
    created_at: datetime
    source_file: Path
    completion_status: str = "completed"
    title: str = ""
    score: float | None = None
    quality: str = "unknown"
    metrics: tuple[tuple[str, object], ...] = ()
    answers: tuple[tuple[str, str, str], ...] = ()

    @property
    def completed(self) -> bool:
        return self.completion_status == "completed"


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


def split_document(text: str) -> tuple[dict[str, str], str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    meta: dict[str, str] = {}
    body_start = 0
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            body_start = index + 1
            break
        if line.strip() and not line.lstrip().startswith("#") and ":" in line:
            key, value = line.split(":", 1)
            if key.strip() and not key.strip().startswith("-"):
                meta[key.strip()] = unquote(value)
    return meta, "\n".join(lines[body_start:])


def read_document(path: Path) -> tuple[dict[str, str], str]:
    return split_document(path.read_text(encoding="utf-8-sig"))


def parse_frontmatter(path: Path) -> dict[str, str]:
    return read_document(path)[0]


def number(value: object, default: float = 0.0) -> float:
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return default


def integer(value: object) -> int:
    return max(0, int(number(value)))


def quality_label(score: float | None) -> str:
    if score is None:
        return "unknown"
    if score >= 75:
        return "high"
    if score >= 50:
        return "medium"
    return "low"


def clean_cell(value: str, limit: int = 420) -> str:
    value = re.sub(r"\s+", " ", value.replace("`", "")).strip()
    return value if len(value) <= limit else value[: limit - 1].rstrip() + "…"


def extract_answers(body: str, scenario_field: str, limit: int = 10) -> tuple[tuple[str, str, str], ...]:
    """Извлекает содержательные строки таблиц, не публикуя весь исходный документ."""
    rows: list[tuple[str, str, str]] = []
    section = ""
    for raw in body.splitlines():
        heading = HEADING_RE.match(raw)
        if heading:
            section = clean_cell(heading.group(1), 120)
            continue
        match = TABLE_LINE_RE.match(raw)
        if not match:
            continue
        cells = [clean_cell(cell) for cell in match.group(1).split("|")]
        if len(cells) < 2 or all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells if cell):
            continue
        joined = " ".join(cells).casefold()
        if any(label in joined for label in ("формулировка ответ", "термин определение", "время примерно", "id вопроса")):
            continue
        if scenario_field == "s2" and len(cells) >= 4:
            item = (cells[1] or cells[0], cells[2], cells[3])
        elif scenario_field == "s3" and any(word in section.casefold() for word in ("портрет", "потер", "иде", "открыт", "активност")):
            item = (cells[0], cells[1], cells[2] if len(cells) > 2 else section)
        elif scenario_field == "s1" and any(word in section.casefold() for word in ("правил", "расхожд", "пробел", "глоссар")):
            item = (cells[0], cells[1], cells[2] if len(cells) > 2 else section)
        else:
            continue
        if any(item) and item not in rows:
            rows.append(item)
        if len(rows) >= limit:
            break
    return tuple(rows)


def analyze_document(meta: dict[str, str], body: str, field: str) -> dict[str, object]:
    title_match = next((HEADING_RE.match(line) for line in body.splitlines() if HEADING_RE.match(line)), None)
    title = clean_cell(title_match.group(1), 180) if title_match else ""
    metrics: dict[str, object]
    score: float | None
    if field == "s1":
        confidence = number(meta.get("confidence"), -1)
        score = round(confidence * 100, 1) if confidence >= 0 else None
        metrics = {"confidence": confidence if confidence >= 0 else None, "document_status": meta.get("status", "")}
    elif field == "s2":
        asked = integer(meta.get("questions_asked"))
        closed = integer(meta.get("questions_closed"))
        soft = integer(meta.get("questions_closed_soft"))
        partial = integer(meta.get("questions_partial"))
        reassigned = integer(meta.get("questions_reassigned"))
        opened = integer(meta.get("questions_open"))
        grounded = integer(meta.get("questions_grounded"))
        weighted = closed + 0.75 * soft + 0.5 * partial
        score = round(min(100.0, weighted / asked * 100), 1) if asked else None
        metrics = {
            "asked": asked,
            "closed": closed,
            "closed_soft": soft,
            "partial": partial,
            "reassigned": reassigned,
            "open": opened,
            "grounded": grounded,
        }
    else:
        completeness = number(meta.get("полнота"), -1)
        score = round(completeness * 100, 1) if completeness >= 0 else None
        metrics = {
            "completeness": completeness if completeness >= 0 else None,
            "workload_assessed": meta.get("загрузка_оценена", ""),
            "document_status": meta.get("статус", meta.get("status", "")),
        }
    return {
        "title": title,
        "score": score,
        "quality": quality_label(score),
        "metrics": tuple(metrics.items()),
        "answers": extract_answers(body, field),
    }


def load_source_index(index_path: Path, source: Path) -> dict[str, dict[str, object]]:
    try:
        payload = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if payload.get("version") != INDEX_VERSION or payload.get("source") != str(source):
        return {}
    return payload.get("entries", {}) if isinstance(payload.get("entries"), dict) else {}


def write_json(path: Path, payload: object) -> bool:
    content = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False) + "\n"
    try:
        if path.read_text(encoding="utf-8") == content:
            return False
    except OSError:
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8", newline="\n")
    temporary.replace(path)
    return True


def save_source_index(index_path: Path, source: Path, entries: dict[str, dict[str, object]]) -> None:
    write_json(index_path, {"version": INDEX_VERSION, "source": str(source), "entries": entries})


def parse_datetime(value: str, fallback: datetime) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = datetime.fromisoformat(value[:10])
        except ValueError:
            parsed = fallback
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def split_person(value: str) -> tuple[str, str, str]:
    parts = [part.strip() for part in value.split(",")]
    return (
        clean_person_name(parts[0]) if parts else "",
        parts[1] if len(parts) > 1 else "",
        parts[2] if len(parts) > 2 else "",
    )


def clean_person_name(value: str) -> str:
    value = NAME_ANNOTATION_RE.sub(" ", value)
    return " ".join(value.split()).strip(" ,;-—")


def department_from(meta: dict[str, str], field: str, supplied: str) -> str:
    if field == "s1":
        value = supplied or meta.get("owner_department_path", "")
    elif field == "s2":
        value = meta.get("op", "")
    else:
        value = meta.get("подразделение", "")
    return value.rsplit(" / ", 1)[-1].strip() if " / " in value else value.strip()


def role_from(meta: dict[str, str], field: str, supplied: str) -> str:
    value = supplied or (meta.get("должность", "") if field == "s3" else meta.get("role", ""))
    return "" if value.strip() == "—" else value.strip()


def session_from_cache(relative: str, payload: dict[str, object]) -> Session:
    return Session(
        scenario_field=str(payload["scenario_field"]),
        session_id=str(payload["session_id"]),
        person_id=str(payload.get("person_id", "")),
        name=str(payload["name"]),
        role=str(payload.get("role", "")),
        department=str(payload.get("department", "")),
        created_at=parse_datetime(str(payload["created_at"]), datetime.now(timezone.utc)),
        source_file=Path(relative),
        completion_status=str(payload.get("completion_status", "completed")),
        title=str(payload.get("title", "")),
        score=payload.get("score") if isinstance(payload.get("score"), (int, float)) else None,
        quality=str(payload.get("quality", "unknown")),
        metrics=tuple((str(k), v) for k, v in dict(payload.get("metrics", {})).items()),
        answers=tuple(tuple(str(v) for v in row[:3]) for row in payload.get("answers", [])),
    )


def session_to_cache(session: Session) -> dict[str, object]:
    payload = asdict(session)
    payload["created_at"] = session.created_at.isoformat()
    payload["source_file"] = session.source_file.as_posix()
    payload["metrics"] = dict(session.metrics)
    payload["answers"] = [list(row) for row in session.answers]
    return payload


def discover_sessions(source: Path, index_path: Path | None = None) -> tuple[list[Session], dict[str, object]]:
    if not source.is_dir():
        raise FileNotFoundError(f"Источник недоступен: {source}")
    cached_entries = load_source_index(index_path, source) if index_path else {}
    next_entries: dict[str, dict[str, object]] = {}
    sessions_by_key: dict[tuple[str, str, str], Session] = {}
    diagnostics: dict[str, object] = {
        "files_seen": 0,
        "ignored_files": 0,
        "duplicate_sessions": 0,
        "index_hits": 0,
        "index_misses": 0,
        "malformed_files": [],
    }
    for path in sorted(source.rglob("*.md"), key=lambda value: str(value).casefold()):
        diagnostics["files_seen"] = int(diagnostics["files_seen"]) + 1
        relative = path.relative_to(source).as_posix()
        stat = path.stat()
        cached = cached_entries.get(relative)
        if (
            cached
            and cached.get("size") == stat.st_size
            and cached.get("mtime_ns") == stat.st_mtime_ns
            and cached.get("status") == "ignored"
        ):
            diagnostics["ignored_files"] = int(diagnostics["ignored_files"]) + 1
            diagnostics["index_hits"] = int(diagnostics["index_hits"]) + 1
            next_entries[relative] = cached
            continue
        if (
            cached
            and cached.get("size") == stat.st_size
            and cached.get("mtime_ns") == stat.st_mtime_ns
            and cached.get("status") == "malformed"
        ):
            diagnostics["malformed_files"].append(relative)
            diagnostics["index_hits"] = int(diagnostics["index_hits"]) + 1
            next_entries[relative] = cached
            continue
        if (
            cached
            and cached.get("size") == stat.st_size
            and cached.get("mtime_ns") == stat.st_mtime_ns
            and isinstance(cached.get("session"), dict)
        ):
            session = session_from_cache(relative, cached["session"])
            diagnostics["index_hits"] = int(diagnostics["index_hits"]) + 1
        else:
            meta, body = read_document(path)
            diagnostics["index_misses"] = int(diagnostics["index_misses"]) + 1
            scenario = meta.get("scenario", "")
            if scenario not in SCENARIOS:
                diagnostics["ignored_files"] = int(diagnostics["ignored_files"]) + 1
                next_entries[relative] = {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns, "status": "ignored"}
                continue
            field, person_field, id_field = SCENARIOS[scenario]
            name, supplied_role, supplied_department = split_person(meta.get(person_field, ""))
            session_id = meta.get("session_id", "").strip()
            if not name or not session_id:
                diagnostics["malformed_files"].append(relative)
                next_entries[relative] = {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns, "status": "malformed"}
                continue
            analysis = analyze_document(meta, body, field)
            completion_status = "completed"
            if scenario == "gap_survey":
                completion_status = meta.get("session_status", "").strip() or "incomplete"
            session = Session(
                scenario_field=field,
                session_id=session_id,
                person_id=meta.get(id_field, "").strip(),
                name=name,
                role=role_from(meta, field, supplied_role),
                department=department_from(meta, field, supplied_department),
                created_at=parse_datetime(meta.get("created_at", meta.get("date", "")), datetime.fromtimestamp(stat.st_mtime, timezone.utc)),
                source_file=Path(relative),
                completion_status=completion_status,
                **analysis,
            )
        next_entries[relative] = {
            "size": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
            "session": session_to_cache(session),
        }
        identity = session.person_id or normalize_name(session.name)
        key = (session.scenario_field, session.session_id, identity)
        previous = sessions_by_key.get(key)
        if previous:
            diagnostics["duplicate_sessions"] = int(diagnostics["duplicate_sessions"]) + 1
            if session.created_at > previous.created_at:
                sessions_by_key[key] = session
        else:
            sessions_by_key[key] = session
    if index_path:
        save_source_index(index_path, source, next_entries)
    sessions = sorted(sessions_by_key.values(), key=lambda item: (item.created_at, item.scenario_field, item.name))
    diagnostics["unique_sessions"] = len(sessions)
    completed = [item for item in sessions if item.completed]
    diagnostics["completed_sessions"] = len(completed)
    diagnostics["partial_sessions"] = len(sessions) - len(completed)
    diagnostics["sessions_by_scenario"] = dict(sorted(Counter(item.scenario_field for item in completed).items()))
    diagnostics["all_sessions_by_scenario"] = dict(sorted(Counter(item.scenario_field for item in sessions).items()))
    return sessions, diagnostics


def normalize_name(value: str) -> str:
    value = unicodedata.normalize("NFKC", clean_person_name(value)).casefold().replace("ё", "е")
    value = re.sub(r"[^\w]+", " ", value, flags=re.UNICODE)
    return " ".join(value.split())


def name_tokens(value: str) -> tuple[str, ...]:
    return tuple(normalize_name(value).split())


def family_key(value: str) -> str:
    return " ".join(name_tokens(value)[:2])


def canonical_name(sessions: Iterable[Session]) -> str:
    counts = Counter(item.name.strip() for item in sessions if item.name.strip())
    return max(counts, key=lambda name: (counts[name], len(name_tokens(name)), len(name)))


def load_legacy_roster(html: str) -> list[dict[str, object]]:
    match = LEGACY_DATA_RE.search(html)
    if not match:
        raise ValueError("Не найден data/roster.json и legacy-массив _ALL")
    roster = json.loads(match.group("data"))
    if not isinstance(roster, list) or not all(isinstance(row, dict) for row in roster):
        raise ValueError("Legacy-массив _ALL имеет неверный формат")
    return roster


def load_roster(roster_path: Path, html_path: Path) -> tuple[list[dict[str, object]], bool]:
    try:
        roster = json.loads(roster_path.read_text(encoding="utf-8"))
        if not isinstance(roster, list):
            raise ValueError("data/roster.json должен быть массивом")
        return roster, False
    except FileNotFoundError:
        roster = load_legacy_roster(html_path.read_text(encoding="utf-8"))
        canonical = [{key: row.get(key, "") for key in ("f", "d", "o", "u", "t")} for row in roster]
        write_json(roster_path, canonical)
        return canonical, True


def select_roster_index(roster: list[dict[str, object]], name: str) -> tuple[int | None, str]:
    normalized = normalize_name(name)
    exact = [index for index, row in enumerate(roster) if normalize_name(str(row.get("f", ""))) == normalized]
    if exact:
        selected = max(
            exact,
            key=lambda index: (
                bool(str(roster[index].get("d", "")).strip()),
                bool(str(roster[index].get("o", "")).strip()),
                bool(str(roster[index].get("u", "")).strip()),
                len(str(roster[index].get("f", ""))),
                -index,
            ),
        )
        return selected, "exact" if len(exact) == 1 else "duplicate_exact"
    key = family_key(name)
    family = [index for index, row in enumerate(roster) if family_key(str(row.get("f", ""))) == key]
    if len(family) == 1:
        return family[0], "family"
    return None, "ambiguous" if len(family) > 1 or len(exact) > 1 else "new"


def fio_audit(roster: list[dict[str, object]], sessions: list[Session]) -> dict[str, object]:
    id_names: dict[str, set[str]] = defaultdict(set)
    name_ids: dict[str, set[str]] = defaultdict(set)
    for session in sessions:
        if session.person_id:
            id_names[session.person_id].add(session.name)
            name_ids[normalize_name(session.name)].add(session.person_id)
    roster_exact = Counter(normalize_name(str(row.get("f", ""))) for row in roster)
    roster_family = Counter(family_key(str(row.get("f", ""))) for row in roster)
    return {
        "bitrix_ids_with_name_variants": [
            {"person_id": person_id, "names": sorted(names)}
            for person_id, names in sorted(id_names.items())
            if len(names) > 1
        ],
        "names_with_multiple_bitrix_ids": [
            {"name": name, "person_ids": sorted(ids)}
            for name, ids in sorted(name_ids.items())
            if len(ids) > 1
        ],
        "duplicate_full_names_in_roster": sorted(name for name, count in roster_exact.items() if name and count > 1),
        "ambiguous_family_names_in_roster": sorted(name for name, count in roster_family.items() if name and count > 1),
        "short_names_in_roster": sorted(str(row.get("f", "")) for row in roster if len(name_tokens(str(row.get("f", "")))) < 3),
    }


def refresh_roster(roster: list[dict[str, object]], sessions: list[Session]) -> tuple[list[dict[str, object]], dict[str, object]]:
    refreshed = [
        {**row, "f": clean_person_name(str(row.get("f", ""))), "s1": 0, "s2": 0, "s3": 0, "vs": 0, "last": ""}
        for row in roster
    ]
    department_management = {
        str(row.get("o", "")): str(row.get("u", ""))
        for row in roster
        if str(row.get("o", "")) and str(row.get("u", ""))
    }
    families_by_id: dict[str, set[str]] = defaultdict(set)
    for session in sessions:
        if session.person_id:
            families_by_id[session.person_id].add(family_key(session.name))
    groups: dict[str, list[Session]] = defaultdict(list)
    for session in sessions:
        if session.person_id and len(families_by_id[session.person_id]) == 1:
            identity = f"id:{session.person_id}"
        elif session.person_id:
            identity = f"id:{session.person_id}:name:{normalize_name(session.name)}"
        else:
            identity = f"name:{normalize_name(session.name)}"
        groups[identity].append(session)
    match_types: Counter[str] = Counter()
    new_people: list[str] = []
    ambiguous_people: list[str] = []
    person_meta: dict[int, dict[str, object]] = {}
    for person_key, person_sessions in sorted(groups.items()):
        display_name = canonical_name(person_sessions)
        index, match_type = select_roster_index(refreshed, display_name)
        if index is None:
            latest = max(person_sessions, key=lambda item: item.created_at)
            department = latest.department or "Не указано"
            refreshed.append({
                "f": display_name,
                "d": latest.role,
                "o": department,
                "u": department_management.get(department, "Не указано"),
                "t": "T1",
                "s1": 0,
                "s2": 0,
                "s3": 0,
                "vs": 0,
                "last": "",
            })
            index = len(refreshed) - 1
            new_people.append(display_name)
            if match_type == "ambiguous":
                ambiguous_people.append(display_name)
        match_types[match_type] += 1
        row = refreshed[index]
        latest = max(person_sessions, key=lambda item: item.created_at)
        completed_sessions = [item for item in person_sessions if item.completed]
        for field in ("s1", "s2", "s3"):
            row[field] = int(row.get(field, 0)) + sum(1 for item in completed_sessions if item.scenario_field == field)
        row["vs"] = int(row["s1"]) + int(row["s2"]) + int(row["s3"])
        previous_last = parse_datetime(str(row.get("last", "")), datetime.min.replace(tzinfo=timezone.utc))
        if latest.created_at >= previous_last:
            row["last"] = latest.created_at.isoformat(timespec="seconds")
        if not str(row.get("d", "")) and latest.role:
            row["d"] = latest.role
        if not str(row.get("o", "")) and latest.department:
            row["o"] = latest.department
            row["u"] = department_management.get(latest.department, str(row.get("u", "")) or "Не указано")
        if match_type == "family" and len(name_tokens(display_name)) > len(name_tokens(str(row.get("f", "")))):
            row["f"] = display_name
        if index in person_meta:
            person_meta[index]["sessions"].extend(person_sessions)
            if person_meta[index]["name_check"] == "exact" and match_type != "exact":
                person_meta[index]["name_check"] = match_type
        else:
            person_meta[index] = {"person_key": f"roster:{index}", "name_check": match_type, "sessions": list(person_sessions)}
    totals = {field: sum(int(row.get(field, 0)) for row in refreshed) for field in ("s1", "s2", "s3")}
    source_totals = Counter(item.scenario_field for item in sessions if item.completed)
    if any(totals[field] != source_totals[field] for field in ("s1", "s2", "s3")):
        raise ValueError(f"Не все сессии перенесены: источник={dict(source_totals)}, реестр={totals}")
    return refreshed, {
        "person_meta": person_meta,
        "people_in_source": len(groups),
        "match_types": dict(match_types),
        "new_people": new_people,
        "ambiguous_people_added_as_new": ambiguous_people,
        "roster_rows_before": len(roster),
        "roster_rows_after": len(refreshed),
        "sessions_applied_to_roster": totals,
        "partial_sessions_applied_to_roster": sum(1 for item in sessions if not item.completed),
    }


def aggregate_quality(sessions: Iterable[Session]) -> dict[str, object]:
    values = [item.score for item in sessions if item.score is not None]
    counts = Counter(item.quality for item in sessions)
    return {
        "average": round(sum(values) / len(values), 1) if values else None,
        "high": counts["high"],
        "medium": counts["medium"],
        "low": counts["low"],
        "unknown": counts["unknown"],
    }


def is_excluded(row: dict[str, object]) -> str:
    name = str(row.get("f", "")).strip()
    role = str(row.get("d", ""))
    if name in EXCLUDED_NAMES:
        return "ручное исключение"
    if re.search(r"стаж[её]р", role, re.I):
        return "стажёр"
    if re.search(r"курьер", role, re.I):
        return "курьер"
    if re.search(r"ловец|вебхук|уч[её]тк", role + " " + name, re.I):
        return "служебная учётка"
    if str(row.get("o", "")) == "Обособленные подразделения":
        return "исключённый отдел"
    return ""


def person_payload(row: dict[str, object], index: int, meta: dict[str, object] | None) -> tuple[dict[str, object], dict[str, object] | None]:
    sessions: list[Session] = list(meta.get("sessions", [])) if meta else []
    completed_sessions = [session for session in sessions if session.completed]
    partial_sessions = [session for session in sessions if not session.completed]
    by_scenario: dict[str, list[Session]] = defaultdict(list)
    for session in completed_sessions:
        by_scenario[session.scenario_field].append(session)
    quality = aggregate_quality(completed_sessions)
    key = str(meta.get("person_key")) if meta else f"roster:{index}"
    person = {
        "key": key,
        "f": row.get("f", ""),
        "d": row.get("d", ""),
        "o": row.get("o", ""),
        "u": row.get("u", ""),
        "t": row.get("t", "T1"),
        "s1": int(row.get("s1", 0)),
        "s2": int(row.get("s2", 0)),
        "s3": int(row.get("s3", 0)),
        "vs": int(row.get("vs", 0)),
        "last": row.get("last", ""),
        "partial_sessions": len(partial_sessions),
        "partial_quality": aggregate_quality(partial_sessions),
        "name_check": str(meta.get("name_check", "not_in_source")) if meta else "not_in_source",
        "quality": quality,
        "scenario_quality": {field: aggregate_quality(items) for field, items in by_scenario.items()},
        "excluded_reason": is_excluded(row),
    }
    if not sessions:
        return person, None
    detail_sessions = []
    for session in sorted(sessions, key=lambda item: item.created_at, reverse=True):
        detail_sessions.append({
            "scenario": session.scenario_field,
            "session_id": session.session_id,
            "source_file": session.source_file.as_posix(),
            "created_at": session.created_at.isoformat(timespec="seconds"),
            "completed": session.completed,
            "completion_status": session.completion_status,
            "title": session.title,
            "score": session.score,
            "quality": session.quality,
            "metrics": dict(session.metrics),
            "answers": [list(answer) for answer in session.answers],
        })
    return person, {"name": row.get("f", ""), "sessions": detail_sessions}


def build_payloads(roster: list[dict[str, object]], sessions: list[Session], diagnostics: dict[str, object]) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    people: list[dict[str, object]] = []
    details: dict[str, object] = {}
    person_meta = diagnostics.pop("person_meta")
    for index, row in enumerate(roster):
        person, detail = person_payload(row, index, person_meta.get(index))
        people.append(person)
        if detail:
            details[person["key"]] = detail
    visible = [person for person in people if not person["excluded_reason"]]
    excluded_sessions = {
        session
        for index, row in enumerate(roster)
        if is_excluded(row)
        for session in person_meta.get(index, {}).get("sessions", [])
    }
    included_all_sessions = [session for session in sessions if session not in excluded_sessions]
    included_sessions = [session for session in included_all_sessions if session.completed]
    included_partial_sessions = [session for session in included_all_sessions if not session.completed]
    excluded_completed_sessions = [session for session in excluded_sessions if session.completed]
    excluded_partial_sessions = [session for session in excluded_sessions if not session.completed]
    latest = max(item.created_at for item in sessions).astimezone(EKB_TZ)
    snapshot = latest.strftime("%d.%m.%Y в %H:%M (Екб)")
    scenario_payload = {}
    for field, info in SCENARIO_INFO.items():
        subset = [session for session in included_sessions if session.scenario_field == field]
        partial_subset = [session for session in included_partial_sessions if session.scenario_field == field]
        scenario_payload[field] = {
            **info,
            "sessions": len(subset),
            "partial_sessions": len(partial_subset),
            "quality": aggregate_quality(subset),
            "partial_quality": aggregate_quality(partial_subset),
        }
    fio = fio_audit(roster, sessions)
    fio["unmatched_or_new_people"] = diagnostics["new_people"]
    fio["ambiguous_people"] = diagnostics["ambiguous_people_added_as_new"]
    fio["issue_count"] = sum(
        len(fio[key])
        for key in (
            "bitrix_ids_with_name_variants",
            "names_with_multiple_bitrix_ids",
            "duplicate_full_names_in_roster",
            "unmatched_or_new_people",
            "ambiguous_people",
        )
    )
    fio["warning_count"] = fio["issue_count"] + len(fio["short_names_in_roster"])
    report = {
        "schema_version": SCHEMA_VERSION,
        "snapshot": snapshot,
        "summary": {
            "people": len(visible),
            "passed_people": sum(1 for person in visible if person["vs"] > 0),
            "not_passed_people": sum(1 for person in visible if person["vs"] == 0),
            "sessions": len(included_sessions),
            "partial_sessions": len(included_partial_sessions),
            "quality": aggregate_quality(included_sessions),
            "fio_issues": fio["issue_count"],
            "excluded_people": len(people) - len(visible),
        },
        "quality_method": {
            "high": "75–100",
            "medium": "50–74,9",
            "low": "ниже 50",
            "s1": "уверенность описания из документа × 100",
            "s2": "(полностью закрытые + 0,75 × закрытые с оговорками + 0,5 × частичные) / всего задано × 100",
            "s3": "полнота карты рабочего дня из документа × 100",
            "warning": "Это индекс полноты/обоснованности, а не экспертная оценка истинности ответа.",
        },
        "scenarios": scenario_payload,
        "fio_audit": fio,
        "people": people,
    }
    detail_payload = {"schema_version": SCHEMA_VERSION, "snapshot": snapshot, "people": details}
    status = {
        "schema_version": SCHEMA_VERSION,
        "snapshot": snapshot,
        "source": "KB-ARM-survey (read-only)",
        "source_files": diagnostics["files_seen"],
        "unique_sessions": diagnostics["unique_sessions"],
        "completed_sessions": diagnostics.get("completed_sessions", sum(1 for item in sessions if item.completed)),
        "partial_sessions": diagnostics.get("partial_sessions", sum(1 for item in sessions if not item.completed)),
        "sessions_by_scenario": diagnostics["sessions_by_scenario"],
        "all_sessions_by_scenario": diagnostics.get(
            "all_sessions_by_scenario",
            dict(sorted(Counter(item.scenario_field for item in sessions).items())),
        ),
        "included_sessions": len(included_sessions),
        "included_partial_sessions": len(included_partial_sessions),
        "excluded_sessions": len(excluded_completed_sessions),
        "excluded_partial_sessions": len(excluded_partial_sessions),
        "included_sessions_by_scenario": dict(sorted(Counter(item.scenario_field for item in included_sessions).items())),
        "ignored_files": diagnostics["ignored_files"],
        "duplicate_sessions": diagnostics["duplicate_sessions"],
        "malformed_files": diagnostics["malformed_files"],
        "fio": {"match_types": diagnostics["match_types"], "issue_count": fio["issue_count"]},
    }
    return report, detail_payload, status


def update(
    source: Path,
    html_path: Path = DEFAULT_HTML,
    check: bool = False,
    index_path: Path | None = DEFAULT_INDEX,
    roster_path: Path = DEFAULT_ROSTER,
    report_path: Path = DEFAULT_REPORT,
    details_path: Path = DEFAULT_DETAILS,
    status_path: Path = DEFAULT_STATUS,
) -> tuple[bool, dict[str, object]]:
    started = time.perf_counter()
    roster, bootstrapped = load_roster(roster_path, html_path)
    cleaned_roster = [{**row, "f": clean_person_name(str(row.get("f", "")))} for row in roster]
    roster_changed = cleaned_roster != roster
    roster = cleaned_roster
    if roster_changed and not check:
        write_json(roster_path, roster)
    sessions, source_diagnostics = discover_sessions(source, index_path=index_path)
    if not sessions:
        raise ValueError("В источнике нет завершённых поддерживаемых сессий")
    refreshed, roster_diagnostics = refresh_roster(roster, sessions)
    combined = {**source_diagnostics, **roster_diagnostics}
    report, details, status = build_payloads(refreshed, sessions, combined)
    outputs = {"report": report_path, "details": details_path, "status": status_path}
    changed_files: list[str] = [roster_path.relative_to(PROJECT_ROOT).as_posix()] if roster_changed else []
    for key, path in outputs.items():
        content = json.dumps({"report": report, "details": details, "status": status}[key], ensure_ascii=False, indent=2) + "\n"
        try:
            changed = path.read_text(encoding="utf-8") != content
        except OSError:
            changed = True
        if changed:
            changed_files.append(path.relative_to(PROJECT_ROOT).as_posix())
            if not check:
                write_json(path, {"report": report, "details": details, "status": status}[key])
    diagnostics = {
        "source": str(source),
        "snapshot": report["snapshot"],
        "changed": bool(changed_files),
        "changed_files": changed_files,
        "roster_bootstrapped": bootstrapped,
        "duration_seconds": round(time.perf_counter() - started, 3),
        **combined,
        "fio_issue_count": report["summary"]["fio_issues"],
        "quality": report["summary"]["quality"],
    }
    return bool(changed_files), diagnostics


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--html", type=Path, default=DEFAULT_HTML)
    parser.add_argument("--index", type=Path, default=DEFAULT_INDEX)
    parser.add_argument("--roster", type=Path, default=DEFAULT_ROSTER)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        _, diagnostics = update(
            source=args.source,
            html_path=args.html,
            check=args.check,
            index_path=args.index,
            roster_path=args.roster,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(diagnostics, ensure_ascii=False, indent=2, default=str))
    else:
        action = "изменятся" if args.check and diagnostics["changed"] else "обновлены" if diagnostics["changed"] else "без изменений"
        print(
            f"Сессий: {diagnostics['unique_sessions']} ({diagnostics['sessions_by_scenario']}), "
            f"людей в источнике: {diagnostics['people_in_source']}, снимок: {diagnostics['snapshot']}, данные: {action}"
        )
        print(
            f"Индекс: {diagnostics['index_hits']} из кэша, {diagnostics['index_misses']} перечитано; "
            f"ФИО-проблем: {diagnostics['fio_issue_count']}; {diagnostics['duration_seconds']} с"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
