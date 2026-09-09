"""KARiN.chatbot 利用分析の読み取り専用集計。

chatbot 本体・予約・RAG とは独立する。
会話全文・氏名・電話・メールは扱わない。
失敗しても /api/chat や予約処理へ伝播させない。
"""
from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Callable

logger = logging.getLogger("karin_chat")

JST = timezone(timedelta(hours=9))
LOOKBACK_DAYS = 2
PAGE_SIZE = 1000
MAX_FETCH_ROWS = 50000

USAGE_SELECT = (
    "id,conversation_id,created_at,intent,next_intent,choice_set,"
    "shown_choices,selected_choice,input_type,booking_started,booking_completed"
)

PRESET_TODAY = "today"
PRESET_7D = "7d"
PRESET_30D = "30d"
PRESET_ALL = "all"
PRESET_CUSTOM = "custom"
DEFAULT_PRESET = PRESET_7D
PRESET_LABELS = {
    PRESET_TODAY: "今日",
    PRESET_7D: "過去7日",
    PRESET_30D: "過去30日",
    PRESET_ALL: "全期間",
    PRESET_CUSTOM: "期間指定",
}

_fetch_override: Callable[..., list[dict]] | None = None


@dataclass(frozen=True)
class AnalyticsPeriod:
    preset: str
    label: str
    start: datetime | None
    end: datetime
    start_date: str
    end_date: str


def set_analytics_fetch_for_tests(fn: Callable[..., list[dict]] | None) -> None:
    global _fetch_override
    _fetch_override = fn


def _now_jst(now: datetime | None = None) -> datetime:
    if now is None:
        return datetime.now(JST)
    if now.tzinfo is None:
        return now.replace(tzinfo=JST)
    return now.astimezone(JST)


def _parse_date(value: str | None) -> date | None:
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


def parse_usage_timestamp(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip().replace("Z", "+00:00")
        if not text:
            return None
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(JST)


def resolve_period(
    preset: str | None,
    start_s: str | None = None,
    end_s: str | None = None,
    *,
    now: datetime | None = None,
) -> AnalyticsPeriod:
    current = _now_jst(now)
    today = current.date()
    range_end = datetime.combine(today + timedelta(days=1), time.min, tzinfo=JST)
    key = (preset or DEFAULT_PRESET).strip().lower()

    if key == PRESET_CUSTOM:
        start_d = _parse_date(start_s)
        end_d = _parse_date(end_s)
        if start_d and end_d and start_d <= end_d:
            start = datetime.combine(start_d, time.min, tzinfo=JST)
            end = datetime.combine(end_d + timedelta(days=1), time.min, tzinfo=JST)
            return AnalyticsPeriod(
                preset=PRESET_CUSTOM,
                label=f"{start_d.isoformat()} 〜 {end_d.isoformat()}",
                start=start,
                end=end,
                start_date=start_d.isoformat(),
                end_date=end_d.isoformat(),
            )
        key = DEFAULT_PRESET

    if key == PRESET_TODAY:
        start = datetime.combine(today, time.min, tzinfo=JST)
        return AnalyticsPeriod(
            preset=PRESET_TODAY,
            label=PRESET_LABELS[PRESET_TODAY],
            start=start,
            end=range_end,
            start_date=today.isoformat(),
            end_date=today.isoformat(),
        )
    if key == PRESET_30D:
        start_d = today - timedelta(days=29)
        start = datetime.combine(start_d, time.min, tzinfo=JST)
        return AnalyticsPeriod(
            preset=PRESET_30D,
            label=PRESET_LABELS[PRESET_30D],
            start=start,
            end=range_end,
            start_date=start_d.isoformat(),
            end_date=today.isoformat(),
        )
    if key == PRESET_ALL:
        return AnalyticsPeriod(
            preset=PRESET_ALL,
            label=PRESET_LABELS[PRESET_ALL],
            start=None,
            end=range_end,
            start_date="",
            end_date=today.isoformat(),
        )

    start_d = today - timedelta(days=6)
    start = datetime.combine(start_d, time.min, tzinfo=JST)
    return AnalyticsPeriod(
        preset=PRESET_7D,
        label=PRESET_LABELS[PRESET_7D],
        start=start,
        end=range_end,
        start_date=start_d.isoformat(),
        end_date=today.isoformat(),
    )


def rate_percent(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(100.0 * numerator / denominator, 1)


def format_rate(numerator: int, denominator: int) -> str:
    value = rate_percent(numerator, denominator)
    if value is None:
        return "—"
    return f"{value:.1f}%"


def _as_str_list(value: Any) -> list[str]:
    if isinstance(value, list):
        items = value
    elif isinstance(value, tuple):
        items = list(value)
    else:
        return []
    out: list[str] = []
    for item in items:
        label = str(item).strip()
        if label:
            out.append(label)
    return out


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    text = str(value or "").strip().lower()
    return text in {"true", "t", "1", "yes"}


def _in_period(ts: datetime | None, period: AnalyticsPeriod) -> bool:
    if ts is None:
        return False
    if period.start is not None and ts < period.start:
        return False
    return ts < period.end


def _known_intent_names() -> list[str]:
    try:
        from karin_chat_intent import (
            INTENT_CAMPAIGN,
            INTENT_CONSULTATION,
            INTENT_CORPORATE_VISIT,
            INTENT_HEALTH,
            INTENT_HOURS,
            INTENT_PRICE,
            INTENT_RESERVATION,
            INTENT_RESERVATION_INFO,
            INTENT_SAFETY,
            INTENT_SERVICE,
            INTENT_TRAINER_ACCOMPANY,
            INTENT_TREATMENT,
            INTENT_UNCLEAR,
        )
    except Exception:
        return []
    return [
        INTENT_SAFETY,
        INTENT_TRAINER_ACCOMPANY,
        INTENT_CORPORATE_VISIT,
        INTENT_TREATMENT,
        INTENT_CAMPAIGN,
        INTENT_PRICE,
        INTENT_HOURS,
        INTENT_SERVICE,
        INTENT_RESERVATION_INFO,
        INTENT_RESERVATION,
        INTENT_CONSULTATION,
        INTENT_HEALTH,
        INTENT_UNCLEAR,
    ]


def _known_choice_catalog() -> tuple[dict[str, list[str]], str]:
    try:
        from karin_chat_choices import CHOICE_SETS, FREE_OTHER, with_other
    except Exception:
        return {}, "その他・自由に相談"
    catalog = {name: with_other(list(labels)) for name, labels in CHOICE_SETS.items()}
    return catalog, FREE_OTHER


def empty_usage_report(
    period: AnalyticsPeriod | None = None,
    *,
    error: str | None = None,
) -> dict[str, Any]:
    current = period or resolve_period(DEFAULT_PRESET)
    catalog, _other = _known_choice_catalog()
    intents = [{"name": name, "count": 0} for name in _known_intent_names()]
    choice_sets = [
        {
            "key": name,
            "displays": 0,
            "selections": 0,
            "rate": "—",
        }
        for name in catalog
    ]
    choice_options = [
        {
            "choice_set": name,
            "options": [
                {"label": label, "count": 0, "rate": "—"} for label in labels
            ],
        }
        for name, labels in catalog.items()
    ]
    return {
        "period_label": current.label,
        "preset": current.preset,
        "start_date": current.start_date,
        "end_date": current.end_date,
        "error": error,
        "conversation_count": 0,
        "booking_started_count": 0,
        "booking_completed_count": 0,
        "booking_start_rate": "—",
        "booking_complete_rate": "—",
        "booking_overall_rate": "—",
        "intents": intents,
        "choice_sets": choice_sets,
        "choice_options": choice_options,
        "daily": [],
        "row_count": 0,
    }


def fetch_usage_log_rows(
    start: datetime | None,
    end: datetime,
    *,
    client=None,
) -> list[dict]:
    from ai_knowledge import get_admin_client

    db = client or get_admin_client()
    lookback_start = None
    if start is not None:
        lookback_start = start - timedelta(days=LOOKBACK_DAYS)
    rows: list[dict] = []
    offset = 0
    while offset < MAX_FETCH_ROWS:
        query = db.table("chatbot_usage_logs").select(USAGE_SELECT)
        if lookback_start is not None:
            query = query.gte("created_at", lookback_start.isoformat())
        query = query.lt("created_at", end.isoformat())
        query = query.order("created_at").order("id")
        query = query.range(offset, offset + PAGE_SIZE - 1)
        chunk = list((query.execute().data or []))
        rows.extend(chunk)
        if len(chunk) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
    return rows


def aggregate_usage_rows(
    rows: list[dict] | None,
    period: AnalyticsPeriod,
) -> dict[str, Any]:
    report = empty_usage_report(period)
    catalog, _other = _known_choice_catalog()
    parsed: list[dict] = []
    for raw in rows or []:
        ts = parse_usage_timestamp(raw.get("created_at"))
        parsed.append(
            {
                "id": str(raw.get("id") or ""),
                "conversation_id": str(raw.get("conversation_id") or "").strip(),
                "created_at": ts,
                "next_intent": (raw.get("next_intent") or "").strip() or None,
                "choice_set": (raw.get("choice_set") or "").strip() or None,
                "shown_choices": _as_str_list(raw.get("shown_choices")),
                "selected_choice": (raw.get("selected_choice") or "").strip() or None,
                "booking_started": _truthy(raw.get("booking_started")),
                "booking_completed": _truthy(raw.get("booking_completed")),
                "in_period": _in_period(ts, period),
            }
        )
    parsed.sort(
        key=lambda row: (
            row["conversation_id"],
            row["created_at"] or datetime.min.replace(tzinfo=JST),
            row["id"],
        )
    )

    conversations: set[str] = set()
    started: set[str] = set()
    completed: set[str] = set()
    intent_counts: dict[str, int] = defaultdict(int)
    displays: dict[str, int] = defaultdict(int)
    selections: dict[str, int] = defaultdict(int)
    option_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    daily_conv: dict[str, set[str]] = defaultdict(set)
    daily_started: dict[str, int] = defaultdict(int)
    daily_completed: dict[str, int] = defaultdict(int)
    in_period_rows = 0

    by_conversation: dict[str, list[dict]] = defaultdict(list)
    for row in parsed:
        cid = row["conversation_id"]
        if not cid:
            continue
        by_conversation[cid].append(row)

    for cid, items in by_conversation.items():
        for index, row in enumerate(items):
            if not row["in_period"]:
                continue
            in_period_rows += 1
            conversations.add(cid)
            if row["booking_started"]:
                started.add(cid)
            if row["booking_completed"]:
                completed.add(cid)
            intent_name = row["next_intent"] or "（なし）"
            intent_counts[intent_name] += 1
            if row["choice_set"]:
                displays[row["choice_set"]] += 1
            if row["created_at"] is not None:
                day_key = row["created_at"].date().isoformat()
                daily_conv[day_key].add(cid)
                if row["booking_started"]:
                    daily_started[day_key] += 1
                if row["booking_completed"]:
                    daily_completed[day_key] += 1
            selected = row["selected_choice"]
            if not selected or index <= 0:
                continue
            prev = items[index - 1]
            prev_set = prev.get("choice_set")
            prev_shown = prev.get("shown_choices") or []
            if not prev_set or selected not in prev_shown:
                continue
            selections[prev_set] += 1
            option_counts[prev_set][selected] += 1

    conv_n = len(conversations)
    started_n = len(started)
    completed_n = len(completed)

    intent_rows: list[dict] = []
    seen_intents: set[str] = set()
    for name in _known_intent_names():
        intent_rows.append({"name": name, "count": int(intent_counts.get(name) or 0)})
        seen_intents.add(name)
    extras = sorted(
        name
        for name in intent_counts
        if name not in seen_intents and name != "（なし）"
    )
    for name in extras:
        intent_rows.append({"name": name, "count": int(intent_counts[name])})
    none_count = int(intent_counts.get("（なし）") or 0)
    if none_count:
        intent_rows.append({"name": "（なし）", "count": none_count})

    set_names = list(catalog.keys())
    for name in displays:
        if name not in set_names:
            set_names.append(name)
    for name in selections:
        if name not in set_names:
            set_names.append(name)

    choice_set_rows = []
    option_groups = []
    for name in set_names:
        shown_n = int(displays.get(name) or 0)
        selected_n = int(selections.get(name) or 0)
        labels = list(catalog.get(name) or [])
        for label in option_counts.get(name, {}):
            if label not in labels:
                labels.append(label)
        options = []
        for label in labels:
            count = int(option_counts.get(name, {}).get(label) or 0)
            options.append(
                {
                    "label": label,
                    "count": count,
                    "rate": format_rate(count, selected_n),
                }
            )
        choice_set_rows.append(
            {
                "key": name,
                "displays": shown_n,
                "selections": selected_n,
                "rate": format_rate(selected_n, shown_n),
            }
        )
        option_groups.append({"choice_set": name, "options": options})

    daily_keys: list[str] = []
    if period.preset != PRESET_ALL and period.start is not None:
        cursor = period.start.date()
        last = (period.end - timedelta(seconds=1)).date()
        while cursor <= last:
            daily_keys.append(cursor.isoformat())
            cursor += timedelta(days=1)
    else:
        daily_keys = sorted(daily_conv.keys())

    max_conv = max((len(daily_conv.get(key) or []) for key in daily_keys), default=0)
    daily_rows = []
    for key in daily_keys:
        conv_day = len(daily_conv.get(key) or [])
        bar = 0 if max_conv <= 0 else int(round(100 * conv_day / max_conv))
        day_obj = date.fromisoformat(key)
        daily_rows.append(
            {
                "date": key,
                "short_date": f"{day_obj.month}/{day_obj.day}",
                "conversations": conv_day,
                "started": int(daily_started.get(key) or 0),
                "completed": int(daily_completed.get(key) or 0),
                "bar_pct": bar,
            }
        )

    report.update(
        {
            "conversation_count": conv_n,
            "booking_started_count": started_n,
            "booking_completed_count": completed_n,
            "booking_start_rate": format_rate(started_n, conv_n),
            "booking_complete_rate": format_rate(completed_n, started_n),
            "booking_overall_rate": format_rate(completed_n, conv_n),
            "intents": intent_rows,
            "choice_sets": choice_set_rows,
            "choice_options": option_groups,
            "daily": daily_rows,
            "row_count": in_period_rows,
        }
    )
    return report


def load_usage_analytics(
    *,
    preset: str | None = DEFAULT_PRESET,
    start: str | None = None,
    end: str | None = None,
    now: datetime | None = None,
    client=None,
    rows: list[dict] | None = None,
) -> dict[str, Any]:
    period = resolve_period(preset, start, end, now=now)
    try:
        if rows is not None:
            source = rows
        elif callable(_fetch_override):
            source = _fetch_override(
                start=period.start,
                end=period.end,
                preset=period.preset,
            )
        else:
            source = fetch_usage_log_rows(period.start, period.end, client=client)
        return aggregate_usage_rows(source, period)
    except Exception:
        logger.exception("chatbot analytics failed")
        return empty_usage_report(
            period,
            error="利用ログの取得に失敗しました。チャットや予約には影響しません。",
        )
