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
    date_candidates: list[str] = field(default_factory=list)
    window_kind: str | None = None

    def missing_for_lookup(self) -> list[str]:
        missing = []
        if not self.area:
            missing.append("area")
        if self.duration_minutes not in (60, 90, 120):
            missing.append("duration")
        if not self.date and not self.date_candidates:
            missing.append("date")
        return missing

    def ready_for_lookup(self) -> bool:
        return not self.missing_for_lookup()

    def dates_to_query(self) -> list[str]:
        if self.date:
            return [self.date]
        return list(self.date_candidates)


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
    candidate_dates: list[str] = field(default_factory=list)
    broaden_dates: list[str] = field(default_factory=list)
    window_kind: str | None = None
    alternative_duration: int | None = None
    alternative_slots: list[str] = field(default_factory=list)
    alternative_dates: list[str] = field(default_factory=list)
    datetime_labels: list[tuple[str, str]] = field(default_factory=list)


PHASE_COLLECTING = "collecting"
PHASE_ALT = "proposing_alt"
PHASE_CONFIRMING = "confirming"
PHASE_GUEST = "guest_info"
PHASE_COMPLETED = "completed"
PHASE_CONSULT = "consult"

DURATION_ASK_REPLY = (
    "施術時間は、60分・90分・120分からお選びいただけます。"
    "ご希望の時間を教えてください。"
)


@dataclass
class BookingDraft:
    """C3短期メモリ上の予約候補条件。DBへは保存しない。予約確定ではない。"""

    reservation_intent: bool = False
    area: str | None = None
    place_type: str | None = None
    course_type: str | None = None
    duration_minutes: int | None = None
    date: str | None = None
    date_range: str | None = None
    date_filter: str | None = None
    date_candidates: list[str] = field(default_factory=list)
    time: str | None = None
    time_period: str | None = None
    preferred_treatment: str | None = None
    concern_summary: str | None = None
    phase: str = PHASE_COLLECTING
    preferred_area: str | None = None
    preferred_place_type: str | None = None
    preferred_date: str | None = None
    preferred_time: str | None = None
    preferred_duration_minutes: int | None = None
    confirmed_area: str | None = None
    confirmed_place_type: str | None = None
    confirmed_date: str | None = None
    confirmed_time: str | None = None
    confirmed_duration_minutes: int | None = None
    alt_duration_minutes: int | None = None
    alt_date: str | None = None
    alt_time: str | None = None
    guest_last_name: str | None = None
    guest_first_name: str | None = None
    guest_phone: str | None = None
    guest_email: str | None = None
    guest_place_name: str | None = None
    booking_id: str | None = None

    @property
    def booking_ready(self) -> bool:
        return is_booking_ready(self)


def is_booking_ready(draft: BookingDraft | None) -> bool:
    """主要条件が具体化しているか。予約確定済みではない。"""
    if draft is None or not draft.reservation_intent:
        return False
    if draft.area not in ("tokyo", "fukuoka"):
        return False
    if not draft.date or not draft.time:
        return False
    if draft.duration_minutes not in (60, 90, 120):
        return False
    return True


def _range_phrases(draft: BookingDraft) -> list[str]:
    out: list[str] = []
    kind = draft.date_range or ""
    if "next" in kind:
        out.append("来週")
    elif kind:
        out.append("今週")
    if draft.date_filter == "weekdays" or "weekday" in kind:
        out.append("平日")
    elif draft.date_filter == "weekend" or kind == "weekend":
        out.append("土日")
    return out


def draft_context_texts(draft: BookingDraft | None) -> list[str]:
    if draft is None:
        return []
    bits: list[str] = []
    if draft.area == "tokyo":
        bits.append("東京")
    elif draft.area == "fukuoka":
        bits.append("福岡")
    if draft.place_type == "visit":
        bits.append("出張")
    elif draft.place_type == "in_house":
        bits.append("院内")
    if draft.duration_minutes in (60, 90, 120):
        bits.append(f"{draft.duration_minutes}分")
    if draft.date:
        bits.append(draft.date.replace("-", "/"))
    else:
        bits.extend(_range_phrases(draft))
    if draft.time:
        bits.append(draft.time)
    elif draft.time_period == "evening":
        bits.append("夕方")
    elif draft.time_period == "morning":
        bits.append("午前")
    elif draft.time_period == "afternoon":
        bits.append("午後")
    if not bits:
        return []
    return [" ".join(bits)]


def _explicit_treatment_preference(text: str) -> str | None:
    raw = (text or "").strip()
    if not raw:
        return None
    if re.search(r"どちら|どっち|詳しく相談", raw):
        return None
    if re.search(r"鍼を受けたい|鍼をお願い|鍼が(いい|希望)|鍼でお願い", raw):
        return "鍼"
    if re.search(r"整体を受けたい|整体をお願い|整体が(いい|希望)|整体でお願い", raw):
        return "整体"
    if re.search(r"美容鍼を受けたい|美容鍼をお願い", raw):
        return "美容鍼"
    return None


def apply_utterance_to_draft(
    draft: BookingDraft,
    text: str,
    *,
    today=None,
    consult_switch: bool = False,
    wants_reservation: bool = False,
) -> BookingDraft:
    """今の発話で分かった条件だけを下書きへ足す。枠の有無は見ない。"""
    if consult_switch:
        draft.reservation_intent = False
    elif wants_reservation:
        draft.reservation_intent = True

    seed: list[str] = []
    if re.search(r"[月火水木金土日]曜", text or "") and not re.search(
        r"今日|明日|あさって|\d{4}[-/]\d{1,2}[-/]\d{1,2}", text or ""
    ):
        seed.extend(_range_phrases(draft))
    parsed = parse_booking_request(seed + [text], today=today)

    if parsed.area:
        draft.area = parsed.area
    if parsed.place_type:
        draft.place_type = parsed.place_type
    if parsed.duration_minutes in (60, 90, 120):
        draft.duration_minutes = parsed.duration_minutes

    clock = _parse_clock_time(text or "")
    if clock:
        draft.time = clock
        draft.time_period = None
    elif parsed.time_range:
        draft.time = None
        draft.time_period = parsed.time_range

    has_window = bool(re.search(r"今週|来週|平日|土日|週末", text or ""))
    has_weekday = bool(re.search(r"[月火水木金土日]曜", text or ""))
    has_specific = bool(
        re.search(
            r"今日|明日|あさって|\d{4}[-/]\d{1,2}[-/]\d{1,2}|"
            r"\d{1,2}月\d{1,2}日|(?<!\d)\d{1,2}/\d{1,2}(?!\d)",
            text or "",
        )
    )
    if has_specific and parsed.date:
        draft.date = parsed.date
    elif has_weekday and parsed.date:
        draft.date = parsed.date
    elif has_window:
        draft.date = None
        draft.date_range = parsed.window_kind
        draft.date_candidates = list(parsed.date_candidates)
        if re.search(r"平日", text or ""):
            draft.date_filter = "weekdays"
        elif re.search(r"土日|週末", text or ""):
            draft.date_filter = "weekend"
    if parsed.date_candidates and not draft.date:
        draft.date_candidates = list(parsed.date_candidates)

    pref = _explicit_treatment_preference(text or "")
    if pref:
        draft.preferred_treatment = pref
    concern = _extract_concern_summary(text or "")
    if concern:
        draft.concern_summary = _merge_concern(draft.concern_summary, concern)
    remember_preferred(draft)
    if consult_switch:
        draft.phase = PHASE_CONSULT
    elif wants_reservation and draft.phase in (PHASE_CONSULT, PHASE_COMPLETED):
        draft.phase = PHASE_COLLECTING
        draft.booking_id = None
    return draft


def remember_preferred(draft: BookingDraft) -> None:
    """最初に具体化した希望は上書きしない。"""
    if draft.area and draft.preferred_area is None:
        draft.preferred_area = draft.area
    if draft.place_type and draft.preferred_place_type is None:
        draft.preferred_place_type = draft.place_type
    if draft.date and draft.preferred_date is None:
        draft.preferred_date = draft.date
    if draft.time and draft.preferred_time is None:
        draft.preferred_time = draft.time
    if draft.duration_minutes in (60, 90, 120) and draft.preferred_duration_minutes is None:
        draft.preferred_duration_minutes = draft.duration_minutes


def _extract_concern_summary(text: str) -> str | None:
    raw = (text or "").strip()
    if not raw:
        return None
    if re.search(r"詳しく相談", raw):
        return None
    if re.search(r"腰(が|の)?(痛|つら)|腰痛", raw):
        return "腰痛"
    if re.search(r"肩(が|の)?(痛|こ|凝)|肩こり", raw):
        return "肩こり"
    if re.search(r"首(が|の)?(痛|こ|凝)", raw):
        return "首の痛み"
    if re.search(r"背中(が|の)?(痛|つら)", raw):
        return "背中の痛み"
    return None


def _merge_concern(current: str | None, added: str) -> str:
    if not current:
        return added
    if added in current:
        return current
    return f"{current}・{added}"


def apply_confirmed_from_working(draft: BookingDraft) -> None:
    draft.confirmed_area = draft.area
    draft.confirmed_place_type = draft.place_type
    draft.confirmed_date = draft.date
    draft.confirmed_time = draft.time
    draft.confirmed_duration_minutes = draft.duration_minutes


def apply_alternative_acceptance(draft: BookingDraft) -> None:
    if draft.alt_duration_minutes in (60, 90, 120):
        draft.duration_minutes = draft.alt_duration_minutes
        draft.confirmed_duration_minutes = draft.alt_duration_minutes
    if draft.alt_date:
        draft.date = draft.alt_date
        draft.confirmed_date = draft.alt_date
    if draft.alt_time:
        draft.time = draft.alt_time
        draft.time_period = None
        draft.confirmed_time = draft.alt_time
    if draft.area:
        draft.confirmed_area = draft.area
    if draft.place_type:
        draft.confirmed_place_type = draft.place_type
    remember_preferred(draft)


def build_staff_note(draft: BookingDraft | None) -> str:
    """既存Web予約の希望伝達事項。AIの診断・推測は入れない。"""
    if draft is None:
        return ""
    head: list[str] = []
    if draft.concern_summary and draft.preferred_treatment:
        head.append(f"{draft.concern_summary}・{draft.preferred_treatment}希望")
    elif draft.concern_summary:
        head.append(draft.concern_summary)
    elif draft.preferred_treatment:
        head.append(f"{draft.preferred_treatment}希望")

    pref_d = draft.preferred_duration_minutes
    conf_d = draft.confirmed_duration_minutes
    if pref_d and conf_d and pref_d != conf_d:
        head.append(f"第一希望は{pref_d}分だったが、空き状況により{conf_d}分で予約。")

    pref_date, pref_time = draft.preferred_date, draft.preferred_time
    conf_date, conf_time = draft.confirmed_date, draft.confirmed_time
    if (pref_date and conf_date and pref_date != conf_date) or (
        pref_time and conf_time and pref_time != conf_time
    ):
        from_s = " ".join(
            x for x in (_format_jp_date(pref_date) if pref_date else "", pref_time or "") if x
        ).strip()
        to_s = " ".join(
            x for x in (_format_jp_date(conf_date) if conf_date else "", conf_time or "") if x
        ).strip()
        head.append(f"第一希望は{from_s}だったが、空き状況により{to_s}で予約。")
    return "\n".join(head)


def build_draft_prompt(draft: BookingDraft | None) -> str:
    if draft is None or not (
        draft.reservation_intent or draft.area or draft.date or draft.time
    ):
        return ""
    lines = [
        "すでに把握している予約条件です。これらを聞き直さないでください。",
        "まだ具体化していない項目だけ、必要なら1つ確認してよいです。",
        "予約を確定しないでください。予約が完了したかのように言わないでください。",
        "「承りました」「予約をお取りしました」は使わないでください。",
    ]
    if draft.reservation_intent:
        lines.append("- 予約意思: あり")
    if draft.area == "tokyo":
        lines.append("- エリア: 東京")
    elif draft.area == "fukuoka":
        lines.append("- エリア: 福岡")
    if draft.place_type == "visit":
        lines.append("- 施術方法: 出張")
    elif draft.place_type == "in_house":
        lines.append("- 施術方法: 院内")
    if draft.duration_minutes:
        lines.append(f"- 施術時間: {draft.duration_minutes}分")
    if draft.date:
        lines.append(f"- 日付: {_format_jp_date(draft.date)}")
    elif draft.date_range:
        lines.append(f"- 日付の範囲: {draft.date_range}")
    if draft.time:
        lines.append(f"- 開始時刻: {draft.time}")
    elif draft.time_period:
        lines.append(f"- 時間帯: {draft.time_period}")
    if draft.preferred_treatment:
        lines.append(
            f"- 希望の施術: {draft.preferred_treatment}（ユーザーが明示したもの。症状から断定しない）"
        )
    if draft.concern_summary:
        lines.append(f"- お悩み（ユーザーの発言）: {draft.concern_summary}")
    if draft.preferred_duration_minutes and draft.confirmed_duration_minutes:
        if draft.preferred_duration_minutes != draft.confirmed_duration_minutes:
            lines.append(
                f"- 元の希望施術時間: {draft.preferred_duration_minutes}分 / 了承済み: {draft.confirmed_duration_minutes}分"
            )
    if is_booking_ready(draft):
        lines.append("主要条件は具体化していますが、予約確定はまだ行いません。")
    return "\n".join(lines)


def _jst_today():
    return datetime.now(timezone(timedelta(hours=9))).date()


def _booking_horizon(today):
    from app import BOOKING_DAYS_AHEAD

    return [today + timedelta(days=i) for i in range(int(BOOKING_DAYS_AHEAD) + 1)]


def _this_week_span(today):
    start = today - timedelta(days=today.weekday())
    return start, start + timedelta(days=6)


def _next_week_span(today):
    start = today - timedelta(days=today.weekday()) + timedelta(days=7)
    return start, start + timedelta(days=6)


def _dates_in_span(start, end, today, horizon, weekdays_only=None):
    out = []
    cur = start
    while cur <= end:
        if cur >= today and cur in horizon:
            if weekdays_only is None or (weekdays_only and cur.weekday() < 5) or (
                weekdays_only is False and cur.weekday() >= 5
            ):
                out.append(cur)
        cur += timedelta(days=1)
    return out


def _next_weekday(today, weekday: int, horizon):
    for d in horizon:
        if d.weekday() == weekday:
            return d
    return None


def _format_jp_date(iso: str) -> str:
    year, month, day = iso.split("-")
    d = datetime(int(year), int(month), int(day)).date()
    wd = "月火水木金土日"[d.weekday()]
    return f"{d.month}月{d.day}日（{wd}）"


_WEEKDAY_CHAR = {"月": 0, "火": 1, "水": 2, "木": 3, "金": 4, "土": 5, "日": 6}


def parse_booking_request(texts: list[str], *, today=None) -> BookingRequest:
    """会話中の希望条件を読む。夜を19:00に変換しない。空き判定はしない。"""
    req = BookingRequest()
    day = today or _jst_today()
    week_which = None
    day_filter = None
    named_weekday = None
    specific_date = None
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
            specific_date = f"{int(dated.group(1)):04d}-{int(dated.group(2)):02d}-{int(dated.group(3)):02d}"
        elif re.search(r"あさって", text):
            specific_date = (day + timedelta(days=2)).isoformat()
        elif re.search(r"明日", text):
            specific_date = (day + timedelta(days=1)).isoformat()
        elif re.search(r"今日", text):
            specific_date = day.isoformat()
        else:
            md = _parse_month_day(text, day)
            if md:
                specific_date = md

        if re.search(r"来週", text):
            week_which = "next"
        elif re.search(r"今週", text):
            week_which = "this"
        if re.search(r"平日", text):
            day_filter = "weekdays"
        elif re.search(r"土日|週末", text):
            day_filter = "weekend"

        wd_match = re.search(r"([月火水木金土日])曜", text)
        if wd_match:
            named_weekday = _WEEKDAY_CHAR.get(wd_match.group(1))

        clock = _parse_clock_time(text)
        if clock:
            req.time = clock
            req.time_range = None
        elif re.search(r"夜|今夜|仕事終わり", text):
            req.time_range = "evening"
            req.time = None
        elif re.search(r"夕方", text):
            req.time_range = "evening"
            req.time = None
        elif re.search(r"午前|朝", text) and not clock:
            req.time_range = "morning"
        elif re.search(r"午後", text) and not clock:
            req.time_range = "afternoon"

    horizon = _booking_horizon(day)
    horizon_set = set(horizon)

    if specific_date:
        req.date = specific_date
        req.date_candidates = [specific_date]
        req.window_kind = None
        return req

    candidates = []
    if week_which == "next":
        start, end = _next_week_span(day)
        req.window_kind = "next_week"
        if day_filter == "weekdays":
            candidates = _dates_in_span(start, end, day, horizon_set, True)
        elif day_filter == "weekend":
            candidates = _dates_in_span(start, end, day, horizon_set, False)
        else:
            candidates = _dates_in_span(start, end, day, horizon_set, None)
    elif week_which == "this":
        start, end = _this_week_span(day)
        req.window_kind = "this_week"
        if day_filter == "weekdays":
            candidates = _dates_in_span(start, end, day, horizon_set, True)
        elif day_filter == "weekend":
            candidates = _dates_in_span(start, end, day, horizon_set, False)
        else:
            candidates = _dates_in_span(start, end, day, horizon_set, None)
        if not candidates and day_filter == "weekdays":
            nstart, nend = _next_week_span(day)
            candidates = _dates_in_span(nstart, nend, day, horizon_set, True)
            req.window_kind = "next_weekdays"
    elif day_filter == "weekdays":
        req.window_kind = "weekdays_ahead"
        this_start, this_end = _this_week_span(day)
        candidates = _dates_in_span(this_start, this_end, day, horizon_set, True)
        if not candidates:
            nstart, nend = _next_week_span(day)
            candidates = _dates_in_span(nstart, nend, day, horizon_set, True)
    elif day_filter == "weekend":
        req.window_kind = "weekend"
        this_start, this_end = _this_week_span(day)
        candidates = _dates_in_span(this_start, this_end, day, horizon_set, False)
        if not candidates:
            nstart, nend = _next_week_span(day)
            candidates = _dates_in_span(nstart, nend, day, horizon_set, False)

    if named_weekday is not None:
        if candidates:
            narrowed = [d for d in candidates if d.weekday() == named_weekday]
            if narrowed:
                req.date = narrowed[0].isoformat()
                req.date_candidates = [req.date]
                req.window_kind = None
                return req
        nxt = _next_weekday(day, named_weekday, horizon)
        if nxt:
            req.date = nxt.isoformat()
            req.date_candidates = [req.date]
            req.window_kind = None
            return req

    if candidates:
        req.date_candidates = [d.isoformat() for d in candidates]
        if len(req.date_candidates) == 1:
            req.date = req.date_candidates[0]
    return req


def _parse_month_day(text: str, today) -> str | None:
    """9/10 や 9月10日。年は付けない。夜を時刻にしない。"""
    if _DATE_RE.search(text or ""):
        return None
    jp = re.search(r"(?<!\d)(\d{1,2})月(\d{1,2})日", text or "")
    slash = re.search(r"(?<!\d)(\d{1,2})/(\d{1,2})(?!\d)", text or "")
    m = jp or slash
    if not m:
        return None
    month = int(m.group(1))
    day_n = int(m.group(2))
    if month < 1 or month > 12 or day_n < 1 or day_n > 31:
        return None
    try:
        candidate = today.replace(month=month, day=day_n)
    except ValueError:
        return None
    if candidate < today:
        try:
            candidate = candidate.replace(year=today.year + 1)
        except ValueError:
            return None
    return candidate.isoformat()


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


def _filter_times(times: list[str], req: BookingRequest) -> list[str]:
    if req.time:
        return [t for t in times if t == req.time]
    if req.time_range:
        return [t for t in times if _in_time_range(t, req.time_range)]
    return list(times)


def lookup_web_booking_availability(
    texts: list[str],
    *,
    lookup_fn=None,
    today=None,
    draft: BookingDraft | None = None,
) -> BookingLookupResult:
    """条件が揃ったときだけ既存の空き枠算出を呼ぶ。枠計算自体は複製しない。"""
    merged = list(draft_context_texts(draft)) + list(texts or [])
    req = parse_booking_request(merged, today=today)
    result = BookingLookupResult(
        requested_area=req.area,
        requested_place_type=req.place_type,
        requested_duration=req.duration_minutes,
        requested_date=req.date,
        requested_time=req.time,
        requested_time_range=req.time_range,
        missing_fields=req.missing_for_lookup(),
        api_status="skipped_insufficient",
        window_kind=req.window_kind,
        candidate_dates=list(req.date_candidates),
    )
    if not req.ready_for_lookup():
        return result

    place_type = _selectable_place_type(req.place_type)
    if req.duration_minutes not in (60, 90, 120):
        result.requested_place_type = place_type
        return result
    duration = req.duration_minutes
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

    dates = req.dates_to_query()
    if not dates:
        return result

    caller = lookup_fn or _call_existing_slots
    matched_dates: list[str] = []
    broaden_dates: list[str] = []
    last_times: list[str] = []
    last_matched: list[str] = []
    datetime_labels: list[tuple[str, str]] = []
    saw_ok = False
    saw_error = False

    for date in dates:
        try:
            payload = caller(
                area=req.area,
                date=date,
                duration_minutes=duration,
                place_type=place_type,
            )
        except Exception:
            logger.warning("karin_chat booking_lookup_failed")
            saw_error = True
            continue
        saw_ok = True
        times = _available_times_from_payload(payload or {})
        matched = _filter_times(times, req)
        if times:
            broaden_dates.append(date)
        if matched:
            matched_dates.append(date)
            last_times = times
            last_matched = matched
            for t in matched:
                datetime_labels.append((date, t))

    result.api_called = True
    if not saw_ok:
        result.api_status = "error"
        return result

    result.api_status = "ok"
    result.candidate_dates = matched_dates
    result.broaden_dates = broaden_dates
    result.datetime_labels = datetime_labels
    if req.time:
        result.requested_time_available = bool(last_matched) and req.time in last_matched
    if len(dates) == 1:
        result.requested_date = dates[0]
        result.available_slots = last_matched
    else:
        result.available_slots = []
        if len(matched_dates) == 1:
            result.requested_date = matched_dates[0]
            result.available_slots = last_matched
    _fill_duration_alternatives(
        result, req, dates, place_type, duration, caller
    )
    return result


def build_booking_context(result: BookingLookupResult) -> str:
    lines = [
        "以下は既存予約システムから取得したリアルタイム情報です。",
        "この情報以外から空き状況を推測しないでください。",
        "予約可能枠を勝手に追加しないでください。",
        "Knowledgeの営業時間から空いている／空いていないと判断しないでください。",
        "理由（営業時間外、予約がいっぱい、など）を推測して断定しないでください。",
        "予約が完了したかのように言わないでください。「承りました」「予約をお取りしました」は禁止です。",
        "具体的な空き時刻（18:00 など）は本文に書かないでください。時刻の一覧は画面側で表示します。",
        "URLや「/book」は本文に書かないでください。予約へ進むボタンは画面側で出します。",
        "ユーザーに希望日時を細かく指定させる前に、確認できた候補日があれば先に示してください。",
        "「ご希望の日時はありますか」「具体的な日や時間帯を教えてください」と聞き返さないでください。",
    ]
    if result.api_status == "skipped_insufficient":
        labels = {
            "area": "東京か福岡か",
            "date": "希望の大まかな時期",
            "place_type": "出張か院内か",
            "duration": "施術時間（60・90・120分）",
        }
        need = [labels.get(x, x) for x in result.missing_fields]
        lines.append("まだ予約システムへ空き確認していません。空いているとも空いていないとも言わないでください。")
        if "duration" in result.missing_fields:
            lines.append("施術時間がまだ決まっていないので空き確認はしていません。60分・90分・120分の希望を1つ確認してください。")
            lines.append("空いているとも空いていないとも言わないでください。")
        elif result.missing_fields == ["area"]:
            lines.append("不足している確認はエリア（東京か福岡か）だけです。希望日や時刻を重ねて聞かないでください。")
        elif need:
            lines.append("不足している確認は次のうち最大1個: " + "、".join(need[:1]))
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
    if result.candidate_dates:
        pretty = "、".join(_format_jp_date(d) for d in result.candidate_dates)
        lines.append("booking_candidate_dates=" + ",".join(result.candidate_dates))
        lines.append(
            f"予約システムで空きが確認できた日: {pretty}。"
            "本文ではこの日付だけを候補として案内してよい。ここにない日を空いていると言わない。"
        )
        lines.append(
            "候補日を示したあと、この中でご都合の良い日、もしくはご希望の時間帯があれば教えてください、と聞いてよい。"
        )
        lines.append("何曜日がいいですか、何時がいいですか、と条件を追加で取りにいかないでください。")
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
    elif result.candidate_dates:
        lines.append("booking_slots_found=yes")
        lines.append("複数日の候補があるため、本文では日付だけを案内し、具体時刻は書かないでください。")
    elif result.broaden_dates:
        pretty = "、".join(_format_jp_date(d) for d in result.broaden_dates)
        lines.append("booking_slots_found=no")
        lines.append("指定の時間帯では空きがありませんでした。枠を作らないでください。")
        lines.append(
            f"時間帯を少し広げると、予約システム上は {pretty} に空きがあります。"
            "この日付以外を空いていると言わないでください。"
        )
        lines.append("別の曜日でも探せると伝えてよい。存在しない枠は出さない。")
    else:
        lines.append("booking_slots_found=no")
        lines.append("予約システムが返した空き枠はありません。枠を作って提示しないでください。")
        lines.append("ご希望の条件では、現在確認できる空き枠がありませんでした、と伝えてよいです。")
        lines.append("別の曜日や時間帯でも探せる、と案内してよい。")
    return "\n".join(lines)


def _shorter_durations(duration: int) -> list[int]:
    if duration == 120:
        return [90, 60]
    if duration == 90:
        return [60]
    return []


def _fill_duration_alternatives(
    result: BookingLookupResult,
    req: BookingRequest,
    dates: list[str],
    place_type: str,
    duration: int,
    caller,
) -> None:
    """希望時間で空きがないときだけ、短い施術時間を既存枠算出で確認する。"""
    if result.available_slots or result.candidate_dates:
        return
    if not req.time:
        return
    for shorter in _shorter_durations(duration):
        alt_dates: list[str] = []
        alt_slots: list[str] = []
        for date in dates:
            try:
                payload = caller(
                    area=req.area,
                    date=date,
                    duration_minutes=shorter,
                    place_type=place_type,
                )
            except Exception:
                logger.warning("karin_chat booking_alt_lookup_failed")
                continue
            times = _available_times_from_payload(payload or {})
            matched = _filter_times(times, req)
            if matched:
                alt_dates.append(date)
                alt_slots = matched
        if alt_dates:
            result.alternative_duration = shorter
            result.alternative_dates = alt_dates
            if len(alt_dates) == 1:
                result.alternative_slots = alt_slots
            return


def _format_jp_date_short(iso: str) -> str:
    _year, month, day = iso.split("-")
    return f"{int(month)}月{int(day)}日"


def _area_label(area: str | None) -> str:
    if area == "tokyo":
        return "東京"
    if area == "fukuoka":
        return "福岡"
    return area or ""


def is_soft_proceed(text: str) -> bool:
    raw = (text or "").strip()
    if not raw:
        return False
    if re.search(r"詳しく相談|予約する前に", raw):
        return False
    return bool(re.search(r"お願い(します|しますね)?|それで(お願い|大丈夫|いい)|はい[。．]?$", raw))


def is_explicit_booking_confirm(text: str) -> bool:
    raw = (text or "").strip()
    return bool(
        re.search(
            r"この内容で予約|予約を確定|確定して|"
            r"この内容で(お願い|進めて)|チャットで予約",
            raw,
        )
    )


def is_accepting_alternative(text: str, draft: BookingDraft) -> bool:
    if draft.phase != PHASE_ALT:
        return False
    raw = (text or "").strip()
    if draft.alt_duration_minutes and re.search(rf"{draft.alt_duration_minutes}分", raw):
        return True
    return is_soft_proceed(raw)


def guest_info_complete(draft: BookingDraft) -> bool:
    if not (
        draft.guest_last_name
        and draft.guest_first_name
        and draft.guest_phone
        and draft.guest_email
    ):
        return False
    place = draft.confirmed_place_type or draft.place_type
    if place == "visit" and not draft.guest_place_name:
        return False
    return True


def parse_guest_info(draft: BookingDraft, text: str) -> BookingDraft:
    raw = (text or "").strip()
    mail = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", raw)
    if mail:
        draft.guest_email = mail.group(0)
    phone = re.search(r"0\d{1,4}[-\s]?\d{1,4}[-\s]?\d{3,4}", raw)
    if phone:
        draft.guest_phone = re.sub(r"[^\d]", "", phone.group(0))
    name = re.search(
        r"([一-龥ぁ-んァ-ンA-Za-z]{1,15})[\s　]+([一-龥ぁ-んァ-ンA-Za-z]{1,15})",
        raw,
    )
    if name and not re.search(r"@|分|時", name.group(0)):
        draft.guest_last_name = name.group(1)
        draft.guest_first_name = name.group(2)
    place = re.search(r"出張先[は:：]?\s*(\S+)", raw)
    if place:
        draft.guest_place_name = place.group(1).strip("。、")
    return draft


def store_alternative_from_lookup(draft: BookingDraft, result: BookingLookupResult) -> None:
    if not result.alternative_duration:
        return
    draft.phase = PHASE_ALT
    draft.alt_duration_minutes = result.alternative_duration
    if result.alternative_dates:
        draft.alt_date = result.alternative_dates[0]
    if result.alternative_slots:
        draft.alt_time = result.alternative_slots[0]
    elif result.requested_time:
        draft.alt_time = result.requested_time


def build_alternative_reply(result: BookingLookupResult, draft: BookingDraft) -> str:
    date_iso = (result.alternative_dates or [result.requested_date or draft.date or ""])[0]
    date_s = _format_jp_date_short(date_iso) if date_iso else ""
    time_s = result.requested_time or draft.time or ""
    want = result.requested_duration or draft.duration_minutes
    alt = result.alternative_duration
    when = f"{date_s}{time_s}".strip()
    return (
        f"{when}は{want}分では空きがありませんでした。\n"
        f"ただ、{alt}分でしたら空きがあります。\n\n"
        f"{alt}分でのご予約はいかがでしょうか？"
    )


def build_candidate_reply(result: BookingLookupResult, draft: BookingDraft) -> str | None:
    if result.api_status == "skipped_insufficient":
        missing = result.missing_fields or []
        if "area" in missing:
            return None
        if "duration" in missing and (
            draft.date or draft.time or draft.date_range or draft.time_period
        ):
            return DURATION_ASK_REPLY
        return None
    if result.api_status != "ok":
        return None
    if result.alternative_duration:
        store_alternative_from_lookup(draft, result)
        return build_alternative_reply(result, draft)

    labels = result.datetime_labels or []
    dates = result.candidate_dates or []
    if not dates and not result.available_slots:
        return (
            "ご希望の条件では、現在確認できる空き枠がありませんでした。"
            "別の日や時間帯、施術時間でも探せますので、希望があれば教えてください。"
        )

    if len(dates) > 1 and not result.available_slots:
        bullets = "\n".join(f"・{_format_jp_date_short(d)}" for d in dates)
        if draft.time and all(t == draft.time for _d, t in labels):
            rows = "\n".join(f"・{_format_jp_date_short(d)} {draft.time}" for d in dates)
            return (
                f"{draft.time}頃で空きが確認できました。\n\n{rows}\n\n"
                "ご都合の良い日時があれば教えてください。"
            )
        weekdayish = draft.date_filter == "weekdays" or "weekday" in (draft.date_range or "")
        if draft.time_period == "evening" and weekdayish:
            return (
                f"平日の夕方で空きが確認できるのは以下の日付です。\n\n{bullets}\n\n"
                "この中でご都合の良い日、もしくはご希望の時間帯があれば教えてください。"
            )
        if weekdayish:
            return (
                f"平日での空き状況を確認したところ、以下の日付に空きがあります。\n\n{bullets}\n\n"
                "この中でご都合の良い日、もしくはご希望の時間帯があれば教えてください。"
            )
        return (
            f"空きが確認できた日付は以下です。\n\n{bullets}\n\n"
            "この中でご都合の良い日、もしくはご希望の時間帯があれば教えてください。"
        )

    slots = result.available_slots or []
    date_iso = result.requested_date or draft.date
    if date_iso and len(slots) == 1:
        return (
            f"{_format_jp_date_short(date_iso)} {slots[0]}に空きが確認できました。\n"
            "この日時でご予約を進めますか？"
        )
    if date_iso and slots:
        rows = "\n".join(f"・{_format_jp_date_short(date_iso)} {t}" for t in slots)
        return (
            f"{_format_jp_date_short(date_iso)}は以下の時間に空きがあります。\n\n{rows}\n\n"
            "ご都合の良い日時があれば教えてください。"
        )
    return None


def build_confirmation_reply(draft: BookingDraft) -> str:
    date_iso = draft.confirmed_date or draft.date
    time_s = draft.confirmed_time or draft.time
    duration = draft.confirmed_duration_minutes or draft.duration_minutes
    area = _area_label(draft.confirmed_area or draft.area)
    treatment = draft.preferred_treatment or "未指定"
    note = build_staff_note(draft)
    date_line = f"{_format_jp_date_short(date_iso) if date_iso else ''} {time_s or ''}".strip()
    lines = [
        "予約内容をご確認ください。",
        "",
        f"日時：{date_line}",
        f"施術時間：{duration}分" if duration else "施術時間：未定",
        f"エリア：{area}" if area else "エリア：未定",
        f"施術：{treatment}",
    ]
    if note:
        lines.extend(["", "希望伝達事項：", note])
    lines.extend(["", "この内容で予約を確定しますか？"])
    return "\n".join(lines)


def build_guest_info_ask(draft: BookingDraft) -> str:
    place = draft.confirmed_place_type or draft.place_type
    extra = "出張先のエリア・住所も教えてください。" if place == "visit" else ""
    return (
        "この内容で予約を進める場合は、氏名（姓と名）、電話番号、メールアドレスを教えてください。"
        + ((" " + extra) if extra else "")
        + "\nまだ予約は確定していません。"
    )


def build_booking_success_reply(draft: BookingDraft) -> str:
    date_iso = draft.confirmed_date or draft.date
    time_s = draft.confirmed_time or draft.time
    duration = draft.confirmed_duration_minutes or draft.duration_minutes
    date_line = f"{_format_jp_date_short(date_iso) if date_iso else ''} {time_s or ''}".strip()
    return (
        "ご予約が完了しました。\n"
        f"日時：{date_line}\n"
        f"施術時間：{duration}分\n"
        "確認メールをお送りします。当日はどうぞよろしくお願いいたします。"
    )


def enter_confirming(draft: BookingDraft) -> None:
    if draft.phase == PHASE_ALT:
        apply_alternative_acceptance(draft)
    else:
        apply_confirmed_from_working(draft)
    if not draft.confirmed_place_type:
        draft.confirmed_place_type = _selectable_place_type(draft.place_type)
    draft.phase = PHASE_CONFIRMING


def complete_chat_booking(
    draft: BookingDraft,
    *,
    lookup_fn=None,
    create_fn=None,
) -> dict:
    """最終空き再確認のあと、既存の atomic_create_web_reservation で確定する。"""
    from app import (
        BOOKING_FREE_STAFF_KEY,
        BookingSlotConflictError,
        atomic_create_web_reservation,
        build_booking_course_label,
        booking_place_type_label,
        send_booking_confirmation_email,
        send_line_message,
    )

    area = draft.confirmed_area or draft.area
    place_type = draft.confirmed_place_type or _selectable_place_type(draft.place_type)
    date = draft.confirmed_date or draft.date
    time_hm = draft.confirmed_time or draft.time
    duration = draft.confirmed_duration_minutes or draft.duration_minutes
    if area not in ("tokyo", "fukuoka") or not date or not time_hm:
        raise BookingSlotConflictError("予約条件が不足しています")
    if duration not in (60, 90, 120):
        raise BookingSlotConflictError("施術時間が不正です")
    if not guest_info_complete(draft):
        raise BookingSlotConflictError("予約者情報が不足しています")

    caller = lookup_fn or _call_existing_slots
    payload = caller(
        area=area,
        date=date,
        duration_minutes=duration,
        place_type=place_type,
    )
    times = _available_times_from_payload(payload or {})
    if time_hm not in times:
        raise BookingSlotConflictError("ご指定の日時は予約できませんでした。")

    note = build_staff_note(draft) or None
    course_label = build_booking_course_label(
        draft.course_type or "total_conditioning", duration
    )
    creator = create_fn or atomic_create_web_reservation
    booking_result = creator(
        area,
        place_type,
        date,
        time_hm,
        BOOKING_FREE_STAFF_KEY,
        duration,
        draft.guest_last_name,
        draft.guest_first_name,
        draft.guest_phone,
        draft.guest_email,
        course_label,
        note,
        place_name=draft.guest_place_name,
    )
    if create_fn is None:
        assigned = (booking_result or {}).get("staff_name") or ""
        area_label = "東京" if area == "tokyo" else "福岡"
        place_label = booking_place_type_label(place_type)
        line_message = (
            "【チャット予約】\n"
            f"日時：{date} {time_hm}\n"
            f"エリア：{area_label}\n"
            f"施術方法：{place_label}\n"
            f"担当：{assigned}\n"
            f"お名前：{draft.guest_last_name} {draft.guest_first_name}\n"
            f"電話：{draft.guest_phone}\n"
            f"メール：{draft.guest_email}\n"
            f"メニュー：{course_label}\n"
            f"出張先：{draft.guest_place_name or '—'}\n"
            f"要望：{note or 'なし'}\n"
        )
        try:
            send_line_message(line_message)
        except Exception:
            logger.warning("karin_chat line_notify_failed")
        try:
            send_booking_confirmation_email(
                draft.guest_email,
                draft.guest_last_name,
                draft.guest_first_name,
                date,
                time_hm,
                duration,
                area,
                assigned,
                course_label,
                note or "",
                place_type=place_type,
                place_name=draft.guest_place_name,
            )
        except Exception:
            logger.warning("karin_chat mail_notify_failed")
    draft.phase = PHASE_COMPLETED
    draft.booking_id = str((booking_result or {}).get("booking_id") or "")
    return booking_result or {}

