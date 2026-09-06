"""KARiN.chatbot C4: 既存Web予約の空き確認。判定ロジックは複製しない。"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

logger = logging.getLogger("karin_chat")

BOOKING_LOOKUP_ERROR_REPLY = (
    "いま予約の空き状況を確認できませんでした。"
    "空いているかどうかは、こちらでは判断できません。"
    "時間をおいて、Web予約ページからご確認ください。"
)

_DATE_RE = re.compile(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})")
_TIME_HM_RE = re.compile(r"(?<!\d)(\d{1,2})[:：](\d{2})(?!\d)")
_TIME_JP_RE = re.compile(r"(?<!\d)(\d{1,2})時(?:半|([0-5]\d)分)?")


@dataclass
class BookingRequest:
    area: str | None = None
    place_type: str | None = None
    duration_minutes: int | None = None
    date: str | None = None
    time: str | None = None
    time_range: str | None = None

    def missing_for_lookup(self) -> list[str]:
        missing = []
        if not self.area:
            missing.append("area")
        if not self.date:
            missing.append("date")
        return missing

    def ready_for_lookup(self) -> bool:
        return not self.missing_for_lookup()


@dataclass
class BookingLookupResult:
    api_called: bool = False
    api_status: str = "skipped_not_needed"
    requested_area: str | None = None
    requested_place_type: str | None = None
    requested_duration: int | None = None
    requested_date: str | None = None
    requested_time: str | None = None
    requested_time_range: str | None = None
    available_slots: list[str] = field(default_factory=list)
    requested_time_available: bool | None = None
    missing_fields: list[str] = field(default_factory=list)


def _jst_today():
    return datetime.now(timezone(timedelta(hours=9))).date()


def parse_booking_request(texts: list[str], *, today=None) -> BookingRequest:
    """会話中の希望条件を読む。夜を19:00に変換しない。空き判定はしない。"""
    req = BookingRequest()
    day = today or _jst_today()
    for raw in texts:
        text = (raw or "").strip()
        if not text:
            continue
        if re.search(r"東京|tokyo", text, re.I):
            req.area = "tokyo"
        if re.search(r"福岡|fukuoka", text, re.I):
            req.area = "fukuoka"
        if re.search(r"出張", text):
            req.place_type = "visit"
        if re.search(r"院内", text):
            req.place_type = "in_house"
        if re.search(r"120分", text):
            req.duration_minutes = 120
        elif re.search(r"90分", text):
            req.duration_minutes = 90
        elif re.search(r"60分", text):
            req.duration_minutes = 60

        dated = _DATE_RE.search(text)
        if dated:
            req.date = f"{int(dated.group(1)):04d}-{int(dated.group(2)):02d}-{int(dated.group(3)):02d}"
        elif re.search(r"あさって", text):
            req.date = (day + timedelta(days=2)).isoformat()
        elif re.search(r"明日", text):
            req.date = (day + timedelta(days=1)).isoformat()
        elif re.search(r"今日", text):
            req.date = day.isoformat()

        clock = _parse_clock_time(text)
        if clock:
            req.time = clock
            req.time_range = None
        elif re.search(r"夜|今夜", text):
            req.time_range = "evening"
            req.time = None
        elif re.search(r"夕方", text):
            req.time_range = "evening"
            req.time = None
        elif re.search(r"午前|朝", text) and not clock:
            req.time_range = "morning"
        elif re.search(r"午後", text) and not clock:
            req.time_range = "afternoon"
    return req


def _parse_clock_time(text: str) -> str | None:
    hm = _TIME_HM_RE.search(text)
    if hm:
        hour = int(hm.group(1))
        minute = int(hm.group(2))
        hour = _adjust_hour(hour, text)
        if 0 <= hour <= 26 and 0 <= minute <= 59:
            return f"{hour:02d}:{minute:02d}"
    jp = _TIME_JP_RE.search(text)
    if not jp:
        return None
    hour = int(jp.group(1))
    if jp.group(0).endswith("時半"):
        minute = 30
    elif jp.group(2):
        minute = int(jp.group(2))
    else:
        minute = 0
    hour = _adjust_hour(hour, text)
    if 0 <= hour <= 26 and 0 <= minute <= 59:
        return f"{hour:02d}:{minute:02d}"
    return None


def _adjust_hour(hour: int, text: str) -> int:
    if hour <= 11 and re.search(r"午後|夜|今夜", text):
        return hour + 12
    return hour


def _selectable_place_type(requested: str | None) -> str | None:
    from app import BOOKING_PLACE_TYPE_OPTIONS, booking_place_type_selectable

    if requested:
        return requested if booking_place_type_selectable(requested) else requested
    for opt in BOOKING_PLACE_TYPE_OPTIONS:
        if opt.get("selectable"):
            return opt["id"]
    return None


def _available_times_from_payload(payload: dict) -> list[str]:
    free = (payload or {}).get("free_row") or {}
    slots = free.get("slots") or []
    return [s.get("time") for s in slots if s.get("available") and s.get("time")]


def _hour(time_label: str) -> int | None:
    try:
        return int(str(time_label).split(":")[0])
    except (TypeError, ValueError, IndexError):
        return None


def _in_time_range(time_label: str, time_range: str | None) -> bool:
    hour = _hour(time_label)
    if hour is None or not time_range:
        return True
    if time_range == "evening":
        return hour >= 18
    if time_range == "morning":
        return hour < 12
    if time_range == "afternoon":
        return 12 <= hour < 18
    return True


def _call_existing_slots(*, area, date, duration_minutes, place_type) -> dict:
    from app import (
        booking_area_selectable,
        booking_place_type_selectable,
        list_web_booking_slots,
    )

    if not booking_area_selectable(area):
        raise ValueError("area_not_selectable")
    if not booking_place_type_selectable(place_type):
        raise ValueError("place_not_selectable")
    return list_web_booking_slots(area, date, duration_minutes, place_type)


def lookup_web_booking_availability(
    texts: list[str],
    *,
    lookup_fn=None,
    today=None,
) -> BookingLookupResult:
    """条件が揃ったときだけ既存の空き枠算出を呼ぶ。"""
    req = parse_booking_request(texts, today=today)
    result = BookingLookupResult(
        requested_area=req.area,
        requested_place_type=req.place_type,
        requested_duration=req.duration_minutes,
        requested_date=req.date,
        requested_time=req.time,
        requested_time_range=req.time_range,
        missing_fields=req.missing_for_lookup(),
        api_status="skipped_insufficient",
    )
    if not req.ready_for_lookup():
        return result

    place_type = _selectable_place_type(req.place_type)
    duration = req.duration_minutes if req.duration_minutes in (60, 90, 120) else 90
    result.requested_place_type = place_type
    result.requested_duration = duration
    if not place_type:
        result.api_status = "skipped_insufficient"
        result.missing_fields = ["place_type"]
        return result

    from app import booking_place_type_selectable

    if not booking_place_type_selectable(place_type):
        result.api_status = "skipped_insufficient"
        result.missing_fields = ["place_type"]
        return result

    caller = lookup_fn or _call_existing_slots
    try:
        payload = caller(
            area=req.area,
            date=req.date,
            duration_minutes=duration,
            place_type=place_type,
        )
    except Exception:
        logger.warning("karin_chat booking_lookup_failed")
        result.api_called = True
        result.api_status = "error"
        return result

    times = _available_times_from_payload(payload or {})
    if req.time:
        shown = [t for t in times if t == req.time]
        result.requested_time_available = req.time in times
        result.available_slots = shown if shown else []
    elif req.time_range:
        result.available_slots = [t for t in times if _in_time_range(t, req.time_range)]
    else:
        result.available_slots = list(times)
    result.api_called = True
    result.api_status = "ok"
    return result


def build_booking_context(result: BookingLookupResult) -> str:
    lines = [
        "以下は既存予約システムから取得したリアルタイム情報です。",
        "この情報以外から空き状況を推測しないでください。",
        "予約可能枠を勝手に追加しないでください。",
        "Knowledgeの営業時間から空いている／空いていないと判断しないでください。",
        "理由（営業時間外、予約がいっぱい、など）を推測して断定しないでください。",
        "氏名・電話・メールを聞いて予約を確定しないでください。空きの案内までです。",
        "具体的な空き時刻（18:00 など）は本文に書かないでください。時刻の一覧は画面側で表示します。",
        "URLや「/book」は本文に書かないでください。予約へ進むボタンは画面側で出します。",
    ]
    if result.api_status == "skipped_insufficient":
        labels = {"area": "東京か福岡か", "date": "希望日", "place_type": "出張か院内か"}
        need = [labels.get(x, x) for x in result.missing_fields]
        lines.append("まだ予約システムへ空き確認していません。空いているとも空いていないとも言わないでください。")
        if need:
            lines.append("不足している確認は次のうち最大2個まで: " + "、".join(need))
        return "\n".join(lines)
    if result.api_status == "error":
        lines.append("予約システムの空き確認に失敗しました。空いている／空いていないは分からない、と伝えてください。")
        lines.append("内部エラーやURL、SQLはユーザーに出さないでください。")
        return "\n".join(lines)

    lines.append(f"requested_area={result.requested_area}")
    lines.append(f"requested_place_type={result.requested_place_type}")
    lines.append(f"requested_duration={result.requested_duration}")
    lines.append(f"requested_date={result.requested_date}")
    lines.append(f"requested_time_range={result.requested_time_range}")
    if result.requested_time:
        if result.requested_time_available:
            lines.append("requested_time_available=yes")
            lines.append("希望の時刻は予約システム上で空きとして確認できました。その具体時刻は本文に書かないでください。")
        else:
            lines.append("requested_time_available=no")
            lines.append("希望の時刻は、予約システムが返した空き枠にはありませんでした。別の時刻を作って提案しないでください。")
    if result.available_slots:
        lines.append("booking_slots_found=yes")
        lines.append(f"booking_slot_count={len(result.available_slots)}")
        lines.append("予約システムで確認済みの空き枠があります。具体的な時刻は本文に書かず、確認できたことだけ伝えてください。")
        lines.append("画面に出ていない時刻を空いていると言わないでください。")
    else:
        lines.append("booking_slots_found=no")
        lines.append("予約システムが返した空き枠はありません。枠を作って提示しないでください。")
        lines.append("ご希望の条件では、現在確認できる空き枠がありませんでした、と伝えてよいです。")
    return "\n".join(lines)
