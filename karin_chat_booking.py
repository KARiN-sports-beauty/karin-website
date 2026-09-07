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
        re.search(r"今日|明日|あさって|\d{4}[-/]\d{1,2}[-/]\d{1,2}", text or "")
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
    return draft


def build_draft_prompt(draft: BookingDraft | None) -> str:
    if draft is None or not (
        draft.reservation_intent or draft.area or draft.date or draft.time
    ):
        return ""
    lines = [
        "すでに把握している予約条件です。これらを聞き直さないでください。",
        "まだ具体化していない項目だけ、必要なら1つ確認してよいです。",
        "予約を確定しないでください。氏名・電話・メールは聞かないでください。",
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

    dates = req.dates_to_query()
    if not dates:
        return result

    caller = lookup_fn or _call_existing_slots
    matched_dates: list[str] = []
    broaden_dates: list[str] = []
    last_times: list[str] = []
    last_matched: list[str] = []
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

    result.api_called = True
    if not saw_ok:
        result.api_status = "error"
        return result

    result.api_status = "ok"
    result.candidate_dates = matched_dates
    result.broaden_dates = broaden_dates
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
        "ユーザーに希望日時を細かく指定させる前に、確認できた候補日があれば先に示してください。",
        "「ご希望の日時はありますか」「具体的な日や時間帯を教えてください」と聞き返さないでください。",
    ]
    if result.api_status == "skipped_insufficient":
        labels = {"area": "東京か福岡か", "date": "希望の大まかな時期", "place_type": "出張か院内か"}
        need = [labels.get(x, x) for x in result.missing_fields]
        lines.append("まだ予約システムへ空き確認していません。空いているとも空いていないとも言わないでください。")
        if result.missing_fields == ["area"]:
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
        lines.append("候補日を示したあと、この中でご都合の良い日があるか、と最大1つだけ聞いてよい。")
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
