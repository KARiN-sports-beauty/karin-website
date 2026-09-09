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
    time_from: str | None = None
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
    requested_time_from: str | None = None
    available_slots: list[str] = field(default_factory=list)
    requested_time_available: bool | None = None
    missing_fields: list[str] = field(default_factory=list)
    candidate_dates: list[str] = field(default_factory=list)
    broaden_dates: list[str] = field(default_factory=list)
    unfiltered_slots: list[str] = field(default_factory=list)
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

# 最終確認チップ。押下時は通常発話として is_confirming_affirmative へ渡す。
CONFIRM_BOOKING_CHOICE = "はい、予約を確定する"

NAME_NEWLINE_ASK = (
    "ありがとうございます。\n"
    "姓と名を改行してお送りください。\n"
    "\n"
    "例：\n"
    "山田\n"
    "太郎"
)

DURATION_ASK_REPLY = (
    "ありがとうございます。施術時間は60分・90分・120分のどれをご希望ですか？"
)

AREA_ASK_REPLY = "ご希望のエリアを教えてください。東京と福岡のどちらですか？"

INITIAL_RESERVATION_REPLY = (
    "『ご予約』ボタンからWeb予約もご利用いただけます。"
    "このまま私との会話で予約を進めることもできます。"
    "ご希望のエリア（東京または福岡）と施術時間を教えてください。"
)

AREA_AND_DURATION_FOLLOW_REPLY = "ご希望のエリアと施術時間も教えてください。"

DATE_WINDOW_ASK_REPLY = (
    "ご希望の日付や時間帯があれば教えてください。\n"
    "『直近で空いているところ』『平日の夜』『土日で空いている日』など、ざっくりしたご希望でも大丈夫です。"
)
_SOONEST_HORIZON_DAYS = 8
_SOONEST_MATCH_LIMIT = 5
_SOONEST_WINDOW_KINDS = frozenset({"soonest", "upcoming"})


@dataclass
class BookingDraft:
    """会話中の予約条件。DBへは保存しない。DB予約確定ではない。

    検索条件: date_range / date_filter / date_candidates / time_period / time_from
    選択条件: date / time / selected_date / selected_time（候補から選んだ作業中の値）
    確定条件: confirmed_*（ユーザーが最終確認した内容。atomic_create 成功前は未予約）
    """

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
    time_from: str | None = None
    selected_date: str | None = None
    selected_time: str | None = None
    offered_dates: list[str] = field(default_factory=list)
    last_expand_kind: str | None = None
    narrow_from_period: str | None = None
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
    elif draft.time_from:
        bits.append(f"{draft.time_from}以降")
    elif draft.time_period == "night":
        bits.append("夜")
    elif draft.time_period == "evening":
        bits.append("夕方")
    elif draft.time_period == "morning":
        bits.append("午前")
    elif draft.time_period == "afternoon":
        bits.append("午後")
    elif draft.time_period == "daytime":
        bits.append("昼間")
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


def _is_flexible_time_phrase(text: str) -> bool:
    """時間指定なし。日付範囲の希望とは別。"""
    raw = text or ""
    if re.search(r"直近|一番早く|近い日|早め", raw):
        return False
    return bool(
        re.search(
            r"いつでもいい|時間はいつでも|時間指定なし|時間は(なんでも|おまかせ)|"
            r"空いて(る|いる)ところで|空いてる(時間|枠)で|"
            r"何時でも|時間は気にしない",
            raw,
        )
    )


def _is_duration_reply(text: str) -> bool:
    raw = (text or "").strip()
    return bool(re.fullmatch(r"(じゃあ|では)?(60|90|120)\s*分(で|希望|でお願いします)?[。．]?", raw))


def _activate_booking_collection(draft: BookingDraft) -> None:
    draft.reservation_intent = True
    if draft.phase == PHASE_CONSULT:
        draft.phase = PHASE_COLLECTING
        draft.booking_id = None


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
    parsed = parse_booking_request(
        seed + [text],
        today=today,
        preferred_dates=list(draft.offered_dates or draft.date_candidates or []),
    )

    if parsed.area:
        draft.area = parsed.area
        if draft.duration_minutes in (60, 90, 120) or draft.date or draft.date_candidates:
            _activate_booking_collection(draft)
    if parsed.place_type:
        draft.place_type = parsed.place_type
    apply_offered_place_type(draft)
    if parsed.duration_minutes in (60, 90, 120):
        draft.duration_minutes = parsed.duration_minutes
        if wants_reservation or _is_duration_reply(text or "") or draft.reservation_intent:
            _activate_booking_collection(draft)

    flexible_time = _is_flexible_time_phrase(text or "")
    time_from = None if flexible_time else _parse_time_from(text or "")
    clock = None if (flexible_time or time_from) else _parse_clock_time(text or "")
    if flexible_time:
        draft.time = None
        draft.time_from = None
        draft.time_period = None
        draft.selected_time = None
    elif time_from:
        if draft.time_period:
            draft.narrow_from_period = draft.time_period
        draft.time_from = time_from
        draft.time = None
        draft.time_period = None
        draft.selected_time = None
    elif clock:
        if draft.time_period:
            draft.narrow_from_period = draft.time_period
        draft.time = clock
        draft.time_from = None
        draft.time_period = None
        draft.selected_time = clock
    elif parsed.time_range:
        draft.time = None
        draft.time_from = None
        draft.time_period = parsed.time_range

    has_window = bool(re.search(r"今週|来週|平日|土日|週末|直近|一番早く|近い日|早め", text or ""))
    has_weekday = bool(re.search(r"[月火水木金土日]曜", text or ""))
    has_specific = bool(
        re.search(
            r"今日|明日|あさって|\d{4}[-/]\d{1,2}[-/]\d{1,2}|"
            r"\d{1,2}月\d{1,2}日|(?<!\d)\d{1,2}/\d{1,2}(?!\d)|"
            r"(?<!月)(?<!\d)\d{1,2}日(?!時)",
            text or "",
        )
    )
    expand_kind = _search_expand_kind(text or "")
    if expand_kind and not has_specific:
        if re.search(r"平日", text or ""):
            draft.date_filter = "weekdays"
        elif re.search(r"土日|週末", text or ""):
            draft.date_filter = "weekend"
        _apply_search_expand(draft, expand_kind, today)
    elif has_specific and parsed.date:
        draft.last_expand_kind = None
        draft.date = parsed.date
        draft.date_candidates = [parsed.date]
        draft.selected_date = parsed.date
        draft.date_range = None
        if draft.duration_minutes in (60, 90, 120) or draft.area in ("tokyo", "fukuoka"):
            _activate_booking_collection(draft)
    elif has_weekday and parsed.date:
        draft.last_expand_kind = None
        draft.date = parsed.date
        draft.date_candidates = [parsed.date]
        draft.selected_date = parsed.date
        draft.date_range = None
        if draft.duration_minutes in (60, 90, 120) or draft.area in ("tokyo", "fukuoka"):
            _activate_booking_collection(draft)
    elif has_window:
        draft.last_expand_kind = None
        draft.offered_dates = []
        draft.date = None
        draft.selected_date = None
        draft.date_range = parsed.window_kind
        draft.date_candidates = list(parsed.date_candidates)
        if re.search(r"平日", text or ""):
            draft.date_filter = "weekdays"
        elif re.search(r"土日|週末", text or ""):
            draft.date_filter = "weekend"
        elif _is_soonest_phrase(text or ""):
            draft.date_filter = None
        if draft.duration_minutes in (60, 90, 120) or draft.area in ("tokyo", "fukuoka"):
            _activate_booking_collection(draft)
    else:
        draft.last_expand_kind = None
    if parsed.date_candidates and not draft.date and not expand_kind:
        draft.date_candidates = list(parsed.date_candidates)
        if parsed.window_kind and not draft.date_range:
            draft.date_range = parsed.window_kind
    if (
        not draft.date
        and not draft.date_candidates
        and (draft.time or draft.time_from or draft.time_period)
        and not expand_kind
        and not flexible_time
    ):
        day = today or _jst_today()
        draft.date_candidates = [d.isoformat() for d in _soonest_dates(day)]
        draft.date_range = draft.date_range or "upcoming"

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
    if draft.alt_date:
        draft.date = draft.alt_date
        draft.selected_date = draft.alt_date
        draft.date_candidates = [draft.alt_date]
    if draft.alt_time:
        draft.time = draft.alt_time
        draft.time_period = None
        draft.selected_time = draft.alt_time
        draft.time_from = None
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
    current_d = draft.confirmed_duration_minutes or draft.duration_minutes
    if pref_d and current_d and pref_d != current_d:
        head.append(f"第一希望は{pref_d}分だったが、空き状況により{current_d}分で予約。")

    pref_date, pref_time = draft.preferred_date, draft.preferred_time
    conf_date = draft.confirmed_date or draft.date
    conf_time = draft.confirmed_time or draft.time
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
    elif draft.time_from:
        lines.append(f"- 開始時刻: {draft.time_from}以降")
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


def _soonest_dates(today):
    return _booking_horizon(today)[:_SOONEST_HORIZON_DAYS]


def _is_soonest_phrase(text: str) -> bool:
    raw = text or ""
    if re.search(r"直近|一番早く|近い日|早め", raw):
        return True
    if re.search(r"今週|来週|平日|土日|週末", raw):
        return False
    if _is_flexible_time_phrase(raw):
        return False
    return bool(re.search(r"取れるところ|空いているところ|空いてるところ|空いている日|空いてる日", raw))


def _search_expand_kind(text: str) -> str | None:
    """前回候補の再表示ではなく、検索範囲の変更・拡張。"""
    raw = (text or "").strip()
    if not raw:
        return None
    if re.search(r"土日なら|週末なら|土日(で|は)(どう|お願い|空)", raw):
        return None
    if re.search(r"もっと先|もっと後|もう少し先|先の日付|先の方", raw):
        return "further"
    if re.search(
        r"他の平日|ほかの平日|他の日|ほかの日|別の日|他の候補|"
        r"ほかに(空|ある)|他に(空|ない|ある)|他には|"
        r"他の|ほかの|別の",
        raw,
    ):
        return "others"
    return None


def _matching_horizon_dates(
    today,
    date_filter: str | None,
    *,
    exclude: list[str] | None = None,
    after: str | None = None,
) -> list[str]:
    excluded = set(exclude or [])
    after_d = None
    if after:
        try:
            after_d = datetime.strptime(after, "%Y-%m-%d").date()
        except ValueError:
            after_d = None
    weekdays_only = None
    if date_filter == "weekdays":
        weekdays_only = True
    elif date_filter == "weekend":
        weekdays_only = False
    out: list[str] = []
    for d in _booking_horizon(today):
        iso = d.isoformat()
        if iso in excluded:
            continue
        if after_d is not None and d <= after_d:
            continue
        if weekdays_only is True and d.weekday() >= 5:
            continue
        if weekdays_only is False and d.weekday() < 5:
            continue
        out.append(iso)
    return out


def _apply_search_expand(draft: BookingDraft, kind: str, today) -> None:
    """前回提示した日付を除き、同じ時間条件のまま対象日を広げる。"""
    day = today or _jst_today()
    offered = list(draft.offered_dates or [])
    draft.date = None
    draft.selected_date = None
    draft.last_expand_kind = kind
    date_filter = draft.date_filter
    if kind == "further":
        after = max(offered) if offered else None
        draft.date_candidates = _matching_horizon_dates(
            day, date_filter, exclude=offered, after=after
        )
        draft.date_range = "further"
        return
    remaining = [d for d in (draft.date_candidates or []) if d not in offered]
    extra = _matching_horizon_dates(day, date_filter, exclude=offered)
    merged: list[str] = []
    for iso in remaining + extra:
        if iso not in merged:
            merged.append(iso)
    draft.date_candidates = merged
    if merged and draft.date_range in (None, "weekdays_ahead", "weekend", "this_week", "next_week"):
        draft.date_range = "expanded"


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


def parse_booking_request(
    texts: list[str],
    *,
    today=None,
    preferred_dates: list[str] | None = None,
) -> BookingRequest:
    """会話中の希望条件を読む。夜を19:00に変換しない。空き判定はしない。"""
    req = BookingRequest()
    day = today or _jst_today()
    week_which = None
    day_filter = None
    named_weekday = None
    specific_date = None
    soonest_ask = False
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
            else:
                dom = _parse_day_only(text, day, preferred_dates)
                if dom:
                    specific_date = dom

        if re.search(r"来週", text):
            week_which = "next"
        elif re.search(r"今週", text):
            week_which = "this"
        if re.search(r"平日", text):
            day_filter = "weekdays"
        elif re.search(r"土日|週末", text):
            day_filter = "weekend"
        if _is_soonest_phrase(text):
            soonest_ask = True

        wd_match = re.search(r"([月火水木金土日])曜", text)
        if wd_match:
            named_weekday = _WEEKDAY_CHAR.get(wd_match.group(1))

        time_from = _parse_time_from(text)
        clock = None if time_from else _parse_clock_time(text)
        if time_from:
            req.time_from = time_from
            req.time = None
            req.time_range = None
        elif clock:
            req.time = clock
            req.time_from = None
            req.time_range = None
        elif re.search(r"夜|今夜|仕事終わり", text):
            req.time_range = "night"
            req.time = None
        elif re.search(r"夕方", text):
            req.time_range = "evening"
            req.time = None
        elif re.search(r"昼間|日中", text):
            req.time_range = "daytime"
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
    elif soonest_ask:
        req.window_kind = "soonest"
        candidates = list(_soonest_dates(day))

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


def _parse_day_only(text: str, today, preferred_dates: list[str] | None = None) -> str | None:
    """「11日」を、直前の候補日または予約可能な直近の日付へ解決する。"""
    if re.search(r"\d{1,2}月\d{1,2}日", text or ""):
        return None
    if _DATE_RE.search(text or "") or re.search(r"(?<!\d)\d{1,2}/\d{1,2}(?!\d)", text or ""):
        return None
    m = re.search(r"(?<!月)(?<!\d)(\d{1,2})日(?!時)", text or "")
    if not m:
        return None
    day_n = int(m.group(1))
    if day_n < 1 or day_n > 31:
        return None
    for iso in preferred_dates or []:
        try:
            if int(iso.split("-")[2]) == day_n:
                return iso
        except (TypeError, ValueError, IndexError):
            continue
    horizon = _booking_horizon(today)
    for d in horizon:
        if d.day == day_n:
            return d.isoformat()
    return None


def _parse_time_from(text: str) -> str | None:
    """「18:00〜」「18時以降」は開始時刻以降。「18:00で」「18時頃」は含めない。"""
    raw = text or ""
    hm = re.search(
        r"(?<!\d)(\d{1,2})[:：](\d{2})\s*(?:[〜～~]|以降|から)",
        raw,
    )
    if hm:
        hour = int(hm.group(1))
        minute = int(hm.group(2))
        hour = _adjust_hour(hour, raw)
        if 0 <= hour <= 26 and 0 <= minute <= 59:
            return f"{hour:02d}:{minute:02d}"
    jp = re.search(
        r"(?<!\d)(\d{1,2})時(?:半|([0-5]\d)分)?(?:以降|から|[〜～~])",
        raw,
    )
    if not jp:
        return None
    hour = int(jp.group(1))
    minute = 30 if "時半" in jp.group(0) else (int(jp.group(2)) if jp.group(2) else 0)
    hour = _adjust_hour(hour, raw)
    if 0 <= hour <= 26 and 0 <= minute <= 59:
        return f"{hour:02d}:{minute:02d}"
    return None


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


def chat_in_house_booking_enabled() -> bool:
    """院内チャット予約を有効化するか。Web予約の selectable と揃える。"""
    from app import booking_place_type_selectable

    return booking_place_type_selectable("in_house")


def guest_fields_for_place(place_type: str | None) -> list[str]:
    """施術場所ごとの必要項目。院内提供開始後もこの対応表を使う。"""
    fields = ["name", "phone", "email"]
    if place_type == "in_house":
        return fields
    return fields + ["dispatch_destination"]


def current_chat_booking_place_type(draft: BookingDraft | None = None) -> str:
    """現在のチャット予約で使う施術場所。院内は提供開始まで有効化しない。"""
    requested = None
    if draft is not None:
        requested = draft.confirmed_place_type or draft.place_type
    return _selectable_place_type(requested) or "visit"


def apply_offered_place_type(draft: BookingDraft) -> None:
    offered = current_chat_booking_place_type(draft)
    draft.place_type = offered
    if draft.confirmed_place_type:
        draft.confirmed_place_type = offered


def _selectable_place_type(requested: str | None) -> str | None:
    from app import BOOKING_PLACE_TYPE_OPTIONS, booking_place_type_selectable

    if requested and booking_place_type_selectable(requested):
        return requested
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


def _time_to_min(time_label: str) -> int | None:
    try:
        hour, minute = str(time_label).split(":")
        return int(hour) * 60 + int(minute)
    except (TypeError, ValueError, IndexError):
        return None


def _in_time_range(time_label: str, time_range: str | None) -> bool:
    hour = _hour(time_label)
    if hour is None or not time_range:
        return True
    if time_range == "night":
        return hour >= 18
    if time_range == "evening":
        return hour >= 16
    if time_range == "morning":
        return hour < 12
    if time_range == "afternoon":
        return 12 <= hour < 17
    if time_range == "daytime":
        return 10 <= hour < 17
    return True


def _filter_times(times: list[str], req: BookingRequest) -> list[str]:
    if req.time:
        return [t for t in times if t == req.time]
    if req.time_from:
        start = _time_to_min(req.time_from)
        if start is None:
            return list(times)
        out = []
        for t in times:
            mins = _time_to_min(t)
            if mins is not None and mins >= start:
                out.append(t)
        return out
    if req.time_range:
        return [t for t in times if _in_time_range(t, req.time_range)]
    return list(times)


def _apply_draft_to_request(req: BookingRequest, draft: BookingDraft | None) -> None:
    if draft is None:
        return
    if draft.area:
        req.area = draft.area
    if draft.place_type:
        req.place_type = draft.place_type
    if draft.duration_minutes in (60, 90, 120):
        req.duration_minutes = draft.duration_minutes
    pick = draft.selected_date or draft.date
    if pick:
        req.date = pick
        req.date_candidates = [pick]
        req.window_kind = None
    elif draft.date_candidates:
        req.date_candidates = list(draft.date_candidates)
        if draft.date_range and not req.window_kind:
            req.window_kind = draft.date_range
    if draft.time:
        req.time = draft.time
        req.time_from = None
        req.time_range = None
    elif draft.time_from:
        req.time_from = draft.time_from
        req.time = None
        req.time_range = None
    elif draft.time_period:
        req.time_range = draft.time_period
        req.time = None


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
    draft: BookingDraft | None = None,
) -> BookingLookupResult:
    """条件が揃ったときだけ既存の空き枠算出を呼ぶ。枠計算自体は複製しない。"""
    merged = list(draft_context_texts(draft)) + list(texts or [])
    preferred = None if draft is None else list(draft.offered_dates or draft.date_candidates or [])
    req = parse_booking_request(merged, today=today, preferred_dates=preferred)
    _apply_draft_to_request(req, draft)
    if not req.date and not req.date_candidates:
        if req.time or req.time_from or req.time_range:
            day = today or _jst_today()
            req.date_candidates = [d.isoformat() for d in _soonest_dates(day)]
            req.window_kind = req.window_kind or "upcoming"
            if draft is not None and not draft.date:
                draft.date_candidates = list(req.date_candidates)
                if not draft.date_range:
                    draft.date_range = req.window_kind
    result = BookingLookupResult(
        requested_area=req.area,
        requested_place_type=req.place_type,
        requested_duration=req.duration_minutes,
        requested_date=req.date,
        requested_time=req.time,
        requested_time_range=req.time_range,
        requested_time_from=req.time_from,
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
    last_unfiltered: list[str] = []
    datetime_labels: list[tuple[str, str]] = []
    saw_ok = False
    saw_error = False
    match_cap = (
        _SOONEST_MATCH_LIMIT
        if (req.window_kind in _SOONEST_WINDOW_KINDS and not req.date)
        else None
    )

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
            last_unfiltered = times
        if matched:
            matched_dates.append(date)
            last_times = times
            last_matched = matched
            for t in matched:
                datetime_labels.append((date, t))
            if match_cap and len(matched_dates) >= match_cap:
                break

    result.api_called = True
    if not saw_ok:
        result.api_status = "error"
        return result

    result.api_status = "ok"
    result.candidate_dates = matched_dates
    result.broaden_dates = broaden_dates
    result.datetime_labels = datetime_labels
    result.unfiltered_slots = last_unfiltered if len(dates) == 1 else []
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
            "place_type": "施術場所",
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
    if result.available_slots or result.candidate_dates or result.broaden_dates:
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


def add_minutes_to_hm(start_time: str, duration_minutes: int) -> str | None:
    """開始時刻に施術時間を足す。26:00 のような 24時超も許可する。"""
    mins = _time_to_min(start_time)
    if mins is None:
        return None
    try:
        added = int(duration_minutes)
    except (TypeError, ValueError):
        return None
    if added <= 0:
        return None
    total = mins + added
    hour, minute = divmod(total, 60)
    return f"{hour:02d}:{minute:02d}"


def format_booking_datetime(
    date: str | None,
    start_time: str | None,
    duration_minutes: int | None = None,
) -> str:
    """表示用。内部の ISO / HH:MM は変えない。"""
    date_s = _format_jp_date_short(date) if date else ""
    start_s = (start_time or "").strip()
    if not date_s and not start_s:
        return ""
    if duration_minutes in (60, 90, 120) and start_s:
        end_s = add_minutes_to_hm(start_s, duration_minutes)
        if end_s:
            return f"{date_s}{start_s}〜{end_s}"
    return f"{date_s}{start_s}".strip()


def _period_label(period: str | None) -> str:
    return {
        "night": "夜",
        "evening": "夕方",
        "daytime": "昼間",
        "afternoon": "午後",
        "morning": "午前",
    }.get(period or "", "")


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
    if re.search(r"詳しく相談|予約する前に|変更したい|ちょっと待って|やっぱり|じゃなくて", raw):
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


def is_confirming_affirmative(text: str) -> bool:
    """confirming 中の最終確認への肯定。条件変更や保留は含めない。"""
    raw = (text or "").strip()
    if not raw:
        return False
    if is_booking_condition_change(raw) or is_booking_defer(raw):
        return False
    if raw == CONFIRM_BOOKING_CHOICE:
        return True
    if is_explicit_booking_confirm(raw):
        return True
    return bool(
        re.search(
            r"^(はい|お願いします|大丈夫です|"
            r"この内容でお願いします|これでお願いします|"
            r"それでお願いします)([。．!！]?)$",
            raw,
        )
    )


def is_booking_defer(text: str) -> bool:
    raw = (text or "").strip()
    return bool(re.search(r"ちょっと待って|待ってて|あとで", raw)) and not bool(
        re.search(r"変更|じゃなく", raw)
    )


def is_booking_condition_change(text: str) -> bool:
    raw = (text or "").strip()
    if not raw:
        return False
    if re.search(r"変更したい|やっぱり|じゃなくて", raw):
        return True
    if re.search(r"(?<!\d)(60|90|120)分", raw) and re.search(r"変更|じゃなく|にして", raw):
        return True
    return False


def accept_final_confirmation(draft: BookingDraft) -> None:
    apply_confirmed_from_working(draft)
    apply_offered_place_type(draft)
    draft.confirmed_place_type = current_chat_booking_place_type(draft)
    draft.phase = PHASE_GUEST


def reopen_collecting_from_confirming(draft: BookingDraft) -> None:
    draft.phase = PHASE_COLLECTING
    draft.confirmed_date = None
    draft.confirmed_time = None
    draft.confirmed_duration_minutes = None
    draft.confirmed_area = None
    draft.confirmed_place_type = None


def is_accepting_alternative(text: str, draft: BookingDraft) -> bool:
    if draft.phase != PHASE_ALT:
        return False
    raw = (text or "").strip()
    if draft.alt_duration_minutes and re.search(rf"{draft.alt_duration_minutes}分", raw):
        return True
    return is_soft_proceed(raw)


def required_guest_fields(draft: BookingDraft) -> list[str]:
    return guest_fields_for_place(current_chat_booking_place_type(draft))


def missing_guest_fields(draft: BookingDraft) -> list[str]:
    missing: list[str] = []
    if not (draft.guest_last_name and draft.guest_first_name):
        missing.append("name")
    if not draft.guest_phone:
        missing.append("phone")
    if not draft.guest_email:
        missing.append("email")
    if "dispatch_destination" in required_guest_fields(draft) and not draft.guest_place_name:
        missing.append("dispatch_destination")
    return missing


def guest_info_complete(draft: BookingDraft) -> bool:
    return not missing_guest_fields(draft)


def guest_display_name(draft: BookingDraft) -> str | None:
    if draft.guest_last_name and draft.guest_first_name:
        return f"{draft.guest_last_name} {draft.guest_first_name}"
    return None


_NAME_TRAIL_RE = re.compile(
    r"(です|ます|と申します|といいます|お願いします)。?$"
)
_NAME_PREFIX_RE = re.compile(r"^(?:お名前|氏名|名前)[は:：]?\s*")
_LAST_LABEL_RE = re.compile(r"姓[は:：]\s*([^\s、,：:\n]+)")
_FIRST_LABEL_RE = re.compile(r"(?<![お氏])名(?!前)[は:：]\s*([^\s、,：:\n]+)")
_FULL_NAME_LABEL_RE = re.compile(r"(?:お名前|氏名|名前)[は:：]\s*([^\n、,。]+)")
_PLACE_LABEL_RE = re.compile(r"出張先[は:：]?\s*([^\n、,]+)")
_NOT_A_NAME = frozenset(
    {
        "はい",
        "ええ",
        "うん",
        "いいえ",
        "お願いします",
        "お願い",
        "大丈夫",
        "大丈夫です",
    }
)
_NAME_CHARS_RE = re.compile(r"^[一-龥々〆ヵヶぁ-んァ-ンA-Za-z]+$")
_FILLER_TOKEN_RE = re.compile(
    r"^(?:電話(?:番号)?|メール(?:アドレス)?|番号|姓|名|お名前|氏名|名前|出張先)$"
)


def _clean_guest_token(token: str) -> str:
    raw = _NAME_TRAIL_RE.sub("", (token or "").strip()).strip("。、, ")
    raw = re.sub(r"^(?:電話(?:番号)?|メール(?:アドレス)?)[は:：]\s*", "", raw)
    if raw in _NOT_A_NAME:
        return ""
    return raw


def _is_name_token(token: str) -> bool:
    raw = _clean_guest_token(token)
    if not raw or raw in _NOT_A_NAME or len(raw) > 15:
        return False
    if re.search(r"\d|@|http", raw):
        return False
    if re.search(r"お願い|確認|予約|メール|電話|出張", raw):
        return False
    if _FILLER_TOKEN_RE.fullmatch(raw):
        return False
    if _looks_like_place(raw):
        return False
    return bool(_NAME_CHARS_RE.fullmatch(raw))


def _is_name_part(token: str) -> bool:
    """単独の姓または名。空白なしフルネームは含めない。"""
    raw = _clean_guest_token(token)
    if not _is_name_token(raw):
        return False
    if re.fullmatch(r"[A-Za-z]+", raw):
        return True
    return 1 <= len(raw) <= 3


def _is_ambiguous_fullname(token: str) -> bool:
    raw = _clean_guest_token(token)
    if not _is_name_token(raw):
        return False
    return len(raw) == 4 and not re.fullmatch(r"[A-Za-z]+", raw)


def _split_explicit_name(token: str) -> tuple[str, str] | None:
    """空白・中点で明確に分かれている場合だけ姓/名にする。文字数では推測しない。"""
    raw = _NAME_PREFIX_RE.sub("", (token or "").strip())
    raw = _NAME_TRAIL_RE.sub("", raw).strip("。、,")
    if not raw or raw in _NOT_A_NAME:
        return None
    if re.search(r"\d|@|http", raw):
        return None
    if re.search(r"お願い|確認|予約|メール|電話|出張先", raw):
        return None
    parts = [p for p in re.split(r"[\s　・]+", raw) if p]
    if len(parts) != 2:
        return None
    if not _is_name_token(parts[0]) or not _is_name_token(parts[1]):
        return None
    return parts[0], parts[1]


def _looks_like_place(token: str) -> bool:
    raw = _clean_guest_token(token)
    if len(raw) < 2:
        return False
    return bool(
        re.search(
            r"区|市|町|村|都|道|府|県|丁目|番地|駅|出張|マンション|アパート|ビル|住所",
            raw,
        )
    )


def _extract_labeled(pattern: re.Pattern, text: str) -> tuple[str | None, str]:
    match = pattern.search(text)
    if not match:
        return None, text
    value = match.group(1)
    rest = text[: match.start()] + " " + text[match.end() :]
    return value, rest


def _apply_name_parts(draft: BookingDraft, last: str | None, first: str | None) -> None:
    last_c = _clean_guest_token(last or "")
    first_c = _clean_guest_token(first or "")
    if last_c and not draft.guest_last_name:
        draft.guest_last_name = last_c
    if first_c and not draft.guest_first_name:
        draft.guest_first_name = first_c


def _assign_unlabeled_guest_tokens(draft: BookingDraft, leftover: list[str]) -> None:
    tokens = [_clean_guest_token(c) for c in leftover]
    tokens = [t for t in tokens if t and not _FILLER_TOKEN_RE.fullmatch(t)]
    need_place = (
        "dispatch_destination" in required_guest_fields(draft) and not draft.guest_place_name
    )

    if not (draft.guest_last_name and draft.guest_first_name):
        if (
            not draft.guest_last_name
            and not draft.guest_first_name
            and len(tokens) >= 2
            and _is_name_part(tokens[0])
            and _is_name_part(tokens[1])
        ):
            _apply_name_parts(draft, tokens[0], tokens[1])
            tokens = tokens[2:]
        elif draft.guest_last_name and not draft.guest_first_name and tokens and _is_name_part(tokens[0]):
            _apply_name_parts(draft, None, tokens[0])
            tokens = tokens[1:]
        elif draft.guest_first_name and not draft.guest_last_name and tokens and _is_name_part(tokens[0]):
            _apply_name_parts(draft, tokens[0], None)
            tokens = tokens[1:]
        elif (
            not draft.guest_last_name
            and not draft.guest_first_name
            and tokens
            and _is_name_part(tokens[0])
            and (len(tokens) == 1 or not _is_name_part(tokens[1]))
        ):
            _apply_name_parts(draft, tokens[0], None)
            tokens = tokens[1:]

    if not need_place or draft.guest_place_name:
        return
    names_done = bool(draft.guest_last_name and draft.guest_first_name)
    for part in tokens:
        if _looks_like_place(part):
            draft.guest_place_name = part
            return
    remain = [t for t in tokens if not _is_ambiguous_fullname(t)]
    if names_done and remain:
        draft.guest_place_name = remain[0]
        return
    if len(remain) == 1 and not _is_name_part(remain[0]):
        draft.guest_place_name = remain[0]


def parse_guest_info(draft: BookingDraft, text: str) -> BookingDraft:
    """1ターンから last/first/phone/email/dispatch を、明確な値だけ取る。

    空白なし氏名を文字数で姓・名に分割しない。既存値は消さない。
    改行で姓と名が並んでいる場合は、ラベルなしでも順番どおり取り込む。
    """
    raw = (text or "").strip()
    if not raw:
        return draft

    last_v, raw = _extract_labeled(_LAST_LABEL_RE, raw)
    first_v, raw = _extract_labeled(_FIRST_LABEL_RE, raw)
    full_v, raw_after_full = _extract_labeled(_FULL_NAME_LABEL_RE, raw)
    if last_v:
        _apply_name_parts(draft, last_v, None)
    if first_v:
        _apply_name_parts(draft, None, first_v)
    if full_v and not (draft.guest_last_name and draft.guest_first_name):
        pair = _split_explicit_name(full_v)
        if pair:
            _apply_name_parts(draft, pair[0], pair[1])
            raw = raw_after_full

    mail = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", raw)
    if mail:
        if not draft.guest_email:
            draft.guest_email = mail.group(0)
        raw = raw[: mail.start()] + " " + raw[mail.end() :]
    phone = re.search(r"0\d{1,4}[-\s]?\d{1,4}[-\s]?\d{3,4}", raw)
    if phone:
        digits = re.sub(r"[^\d]", "", phone.group(0))
        if not draft.guest_phone:
            draft.guest_phone = digits
        raw = raw[: phone.start()] + " " + raw[phone.end() :]
    place, raw = _extract_labeled(_PLACE_LABEL_RE, raw)
    if place and not draft.guest_place_name:
        draft.guest_place_name = _clean_guest_token(place) or place.strip("。、,")

    chunks = [
        p.strip("。、, ")
        for p in re.split(r"[\n、,。]+", raw)
        if p.strip("。、, ")
    ]
    leftover: list[str] = []
    for chunk in chunks:
        pair = _split_explicit_name(chunk)
        if pair and not (draft.guest_last_name and draft.guest_first_name):
            _apply_name_parts(draft, pair[0], pair[1])
            continue
        leftover.append(chunk)

    _assign_unlabeled_guest_tokens(draft, leftover)
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


def _slot_step_minutes() -> int:
    from app import BOOKING_SLOT_STEP_MINUTES

    try:
        return int(BOOKING_SLOT_STEP_MINUTES)
    except (TypeError, ValueError):
        return 15


def _consecutive_bands(times: list[str]) -> list[tuple[str, str]]:
    """連続した予約開始可能時刻の区間。15分超の飛びは連結しない。"""
    step = _slot_step_minutes()
    ordered = sorted({t for t in times if _time_to_min(t) is not None}, key=_time_to_min)
    if not ordered:
        return []
    bands: list[tuple[str, str]] = []
    start = prev = ordered[0]
    for t in ordered[1:]:
        if (_time_to_min(t) or 0) - (_time_to_min(prev) or 0) <= step:
            prev = t
        else:
            bands.append((start, prev))
            start = prev = t
    bands.append((start, prev))
    return bands


def _availability_intervals(
    times: list[str], duration_minutes: int | None = None
) -> list[dict[str, str]]:
    """開始可能時刻から連続区間を組む。1日に複数区間があり得る。

    start / last_start は予約開始可能時刻。
    end は空き区間の終了（last_start＋施術時間）。最終開始時刻とは別物。
    """
    intervals: list[dict[str, str]] = []
    for start, last_start in _consecutive_bands(times):
        occupancy_end = last_start
        if duration_minutes in (60, 90, 120):
            computed = add_minutes_to_hm(last_start, duration_minutes)
            if computed:
                occupancy_end = computed
        intervals.append(
            {
                "start": start,
                "end": occupancy_end,
                "last_start": last_start,
            }
        )
    return intervals


def _format_interval(interval: dict[str, str]) -> str:
    start = interval["start"]
    end = interval["end"]
    if start == end:
        return start
    return f"{start}〜{end}"


def _format_bands(times: list[str], duration_minutes: int | None = None) -> str:
    return "、".join(
        _format_interval(item) for item in _availability_intervals(times, duration_minutes)
    )


def _group_times_by_date(labels: list[tuple[str, str]]) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    for date, time_label in labels:
        grouped.setdefault(date, [])
        if time_label not in grouped[date]:
            grouped[date].append(time_label)
    return grouped


def _band_rows(grouped: dict[str, list[str]], duration_minutes: int | None = None) -> str:
    lines = []
    for date, times in grouped.items():
        date_s = _format_jp_date_short(date)
        intervals = _availability_intervals(times, duration_minutes)
        if not intervals:
            continue
        for interval in intervals:
            lines.append(f"・{date_s} {_format_interval(interval)}")
    return "\n".join(lines)


def should_hide_slot_ui(draft: BookingDraft | None, reply: str = "") -> bool:
    """本文で日時が完結している／最終確認以降は構造化枠を出さない。"""
    if draft is not None and draft.phase in (PHASE_CONFIRMING, PHASE_GUEST, PHASE_COMPLETED):
        return True
    return "この日時でご予約を進めますか" in (reply or "")


def remember_offers(draft: BookingDraft, result: BookingLookupResult) -> None:
    seen = list(draft.offered_dates or [])
    for iso in result.candidate_dates or []:
        if iso not in seen:
            seen.append(iso)
    if seen:
        draft.offered_dates = seen


def _selected_datetime_reply(draft: BookingDraft, date_iso: str, slot: str) -> str:
    draft.selected_date = date_iso
    draft.date = date_iso
    draft.selected_time = slot
    draft.time = slot
    draft.time_from = None
    draft.date_candidates = [date_iso]
    when = format_booking_datetime(date_iso, slot, draft.duration_minutes)
    return (
        f"{when}で空きが確認できました。\n"
        "この日時でご予約を進めますか？"
    )


def _window_phrase(draft: BookingDraft) -> str:
    kind = draft.date_range or ""
    filt = draft.date_filter or ""
    nextish = "next" in kind
    if filt == "weekend" or kind == "weekend":
        return "来週の土日" if nextish else "土日"
    if filt == "weekdays" or "weekday" in kind:
        return "来週の平日" if nextish else "平日"
    if kind == "next_week":
        return "来週"
    if kind in ("this_week",):
        return "今週"
    if draft.date:
        return _format_jp_date_short(draft.date)
    return ""


def draft_missing_for_lookup(draft: BookingDraft | None) -> list[str]:
    if draft is None:
        return ["area", "duration", "date"]
    missing = []
    if draft.area not in ("tokyo", "fukuoka"):
        missing.append("area")
    if draft.duration_minutes not in (60, 90, 120):
        missing.append("duration")
    if not draft.date and not draft.date_candidates:
        missing.append("date")
    return missing


def build_missing_conditions_reply(draft: BookingDraft, missing: list[str]) -> str | None:
    need_area = "area" in missing or draft.area not in ("tokyo", "fukuoka")
    need_duration = "duration" in missing or draft.duration_minutes not in (60, 90, 120)
    need_date = "date" in missing or (
        not draft.date and not draft.date_candidates
    )
    has_window = bool(
        draft.date
        or draft.date_candidates
        or draft.date_range
        or draft.time_period
        or draft.time_from
        or draft.time
    )
    window = _window_phrase(draft)
    dur = (
        f"{draft.duration_minutes}分"
        if draft.duration_minutes in (60, 90, 120)
        else ""
    )
    if need_area and need_duration:
        if has_window:
            return AREA_AND_DURATION_FOLLOW_REPLY
        return INITIAL_RESERVATION_REPLY
    if need_area:
        if window and dur:
            return (
                f"{window}で{dur}ですね。\n"
                "東京・福岡のどちらでのご利用をご希望ですか？"
            )
        if dur and need_date:
            return (
                f"{dur}ですね。東京・福岡のどちらでのご利用をご希望ですか？"
                "日付や時間帯の希望があれば、あわせて教えてください。"
            )
        if dur:
            return f"{dur}ですね。東京・福岡のどちらでのご利用をご希望ですか？"
        return AREA_ASK_REPLY
    if need_duration:
        return DURATION_ASK_REPLY
    if need_date:
        return DATE_WINDOW_ASK_REPLY
    return None


def _period_word_for(draft: BookingDraft) -> str:
    return _period_label(draft.time_period or draft.narrow_from_period)


def _availability_intro(draft: BookingDraft) -> str:
    window = _window_phrase(draft)
    dur = (
        f"{draft.duration_minutes}分"
        if draft.duration_minutes in (60, 90, 120)
        else ""
    )
    area = "東京" if draft.area == "tokyo" else ("福岡" if draft.area == "fukuoka" else "")
    if area and dur and window:
        head = f"{area}で{dur}、{window}ですね。"
    else:
        bits = [x for x in (area, dur, window) if x]
        head = f"{'、'.join(bits)}ですね。" if bits else ""
    if not draft.time and not draft.time_from and not draft.time_period:
        if head:
            return f"{head}時間の希望がなければ、空いている時間を幅広く確認します。"
        return "空きが確認できる日時は以下です。"
    if head:
        return f"{head}空きが確認できる日時は以下です。"
    return "空きが確認できる日時は以下です。"


def _ask_which_day(draft: BookingDraft, result: BookingLookupResult) -> bool:
    return (draft.date_range in _SOONEST_WINDOW_KINDS) or (
        result.window_kind in _SOONEST_WINDOW_KINDS
    )


def _other_slots_on_date_reply(draft: BookingDraft, slots: list[str]) -> str:
    date_iso = draft.date or ""
    duration = draft.duration_minutes if draft.duration_minutes in (60, 90, 120) else None
    want = draft.time or (f"{draft.time_from}以降" if draft.time_from else "ご希望の時間")
    rows = "\n".join(
        f"・{format_booking_datetime(date_iso, t, duration)}" for t in slots
    )
    return (
        f"{_format_jp_date_short(date_iso)}は{want}の空きがありませんでした。\n"
        f"同じ日で空いている時間は以下です。\n\n{rows}\n\n"
        "ご都合の良い日時があれば教えてください。"
    )


def _no_other_dates_reply(draft: BookingDraft) -> str:
    shown = [_format_jp_date_short(d) for d in (draft.offered_dates or [])]
    if draft.date_filter == "weekend" or draft.date_range == "weekend":
        kind = "土日"
    elif draft.date_filter == "weekdays" or "weekday" in (draft.date_range or ""):
        kind = "平日"
    else:
        kind = "日"
    if shown:
        listed = "、".join(shown)
        return (
            f"現在の条件では{listed}以外の{kind}は空きがありませんでした。"
            "時間帯や施術時間を変えて探すこともできます。"
        )
    return (
        f"現在の条件では、他の{kind}に確認できる空きがありませんでした。"
        "時間帯や施術時間を変えて探すこともできます。"
    )


def build_candidate_reply(result: BookingLookupResult, draft: BookingDraft) -> str | None:
    if result.api_status == "skipped_insufficient":
        missing = result.missing_fields or draft_missing_for_lookup(draft)
        if missing:
            return build_missing_conditions_reply(draft, missing)
        if draft.last_expand_kind:
            return _no_other_dates_reply(draft)
        return build_missing_conditions_reply(draft, missing)
    if result.api_status != "ok":
        return None
    if result.alternative_duration:
        store_alternative_from_lookup(draft, result)
        return build_alternative_reply(result, draft)

    labels = list(result.datetime_labels or [])
    dates = list(result.candidate_dates or [])
    if draft.date:
        labels = [(d, t) for d, t in labels if d == draft.date]
        dates = [d for d in dates if d == draft.date]
    if draft.date and draft.time:
        labels = [(d, t) for d, t in labels if t == draft.time]
    grouped = _group_times_by_date(labels)
    remember_offers(draft, result)
    if draft.date:
        draft.offered_dates = [draft.date]

    duration = draft.duration_minutes if draft.duration_minutes in (60, 90, 120) else None
    period_word = _period_word_for(draft)
    weekdayish = draft.date_filter == "weekdays" or "weekday" in (draft.date_range or "")

    if not dates and not labels:
        if draft.last_expand_kind:
            return _no_other_dates_reply(draft)
        if draft.date and result.unfiltered_slots:
            return _other_slots_on_date_reply(draft, result.unfiltered_slots)
        if draft.date:
            return _no_slots_on_date_reply(draft)
        if draft.time_from and period_word:
            return (
                f"先ほどご案内した{period_word}の候補のうち、{draft.time_from}以降で確認できる空きはありませんでした。"
                "別の時間帯でも探せますので、希望があれば教えてください。"
            )
        if draft.time and period_word:
            return (
                f"先ほどご案内した{period_word}の候補のうち、{draft.time}で確認できる空きはありませんでした。"
                "別の時間帯でも探せますので、希望があれば教えてください。"
            )
        return (
            "ご希望の条件では、現在確認できる空き枠がありませんでした。"
            "別の日や時間帯、施術時間でも探せますので、希望があれば教えてください。"
        )

    if draft.date and draft.time and labels:
        date_iso, slot = labels[0]
        return _selected_datetime_reply(draft, date_iso, slot)

    if draft.time_from and grouped:
        if draft.date:
            times = grouped.get(draft.date) or []
            if len(times) == 1:
                return _selected_datetime_reply(draft, draft.date, times[0])
            if times:
                rows = _band_rows({draft.date: times}, duration)
                return (
                    f"{_format_jp_date_short(draft.date)}は{draft.time_from}以降で以下の空きがあります。\n\n"
                    f"{rows}\n\nご都合の良い開始時間があれば教えてください。"
                )
        if len(grouped) == 1:
            date_iso = next(iter(grouped))
            times = grouped[date_iso]
            if len(times) == 1:
                return _selected_datetime_reply(draft, date_iso, times[0])
        rows = _band_rows(grouped, duration)
        intro = f"{draft.time_from}以降で空きが確認できました。"
        if draft.last_expand_kind:
            intro = f"ほかの日で、{draft.time_from}以降の空きが確認できました。"
        elif period_word:
            intro = (
                f"先ほどご案内した{period_word}の候補のうち、{draft.time_from}以降で空きがあるのは以下です。"
            )
        ask = (
            "どの日にしますか？"
            if _ask_which_day(draft, result)
            else "ご希望の日や開始時間があれば教えてください。"
        )
        return f"{intro}\n\n{rows}\n\n{ask}"

    if (
        draft.time_period in ("night", "evening", "daytime", "afternoon", "morning")
        and grouped
        and not draft.time
        and not draft.time_from
    ):
        rows = _band_rows(grouped, duration)
        if weekdayish and period_word:
            title = f"平日の{period_word}で空きが確認できる日時は以下です。"
        elif period_word:
            title = f"{period_word}で空きが確認できる日時は以下です。"
        else:
            title = "空きが確認できる日時は以下です。"
        return (
            f"{title}\n\n{rows}\n\n"
            "ご希望の日や開始時間があれば教えてください。"
        )

    if len(dates) > 1 and not (draft.date and result.available_slots):
        if draft.time and grouped:
            rows = "\n".join(
                f"・{format_booking_datetime(d, draft.time, duration)}"
                for d in dates
                if d in grouped
            )
            intro = f"{format_booking_datetime(None, draft.time, duration)}で空きが確認できました。"
            if draft.last_expand_kind:
                intro = f"ほかの日で、{format_booking_datetime(None, draft.time, duration)}の空きが確認できました。"
            elif period_word:
                intro = (
                    f"先ほどご案内した{period_word}の候補のうち、"
                    f"{format_booking_datetime(None, draft.time, duration)}で空きがあるのは以下です。"
                )
            return (
                f"{intro}\n\n{rows}\n\n"
                "ご都合の良い日時があれば教えてください。"
            )
        if grouped and not weekdayish:
            rows = _band_rows(grouped, duration)
            return (
                f"{_availability_intro(draft)}\n\n{rows}\n\n"
                "ご希望の日や開始時間があれば教えてください。"
            )
        bullets = "\n".join(f"・{_format_jp_date_short(d)}" for d in dates)
        ask = (
            "どの日にしますか？"
            if _ask_which_day(draft, result)
            else "この中でご都合の良い日、もしくはご希望の時間帯を教えてください。"
        )
        if weekdayish:
            title = "平日の空き状況を確認したところ、以下の日付に空きがあります。"
            if draft.last_expand_kind:
                title = "ほかの平日で空きが確認できた日付は以下です。"
            return (
                f"{title}\n\n{bullets}\n\n"
                f"{ask}"
            )
        return (
            f"空きが確認できた日付は以下です。\n\n{bullets}\n\n"
            f"{ask}"
        )

    slots = result.available_slots or [t for _d, t in labels]
    date_iso = result.requested_date or draft.date
    if date_iso and draft.time and draft.time in slots:
        return _selected_datetime_reply(draft, date_iso, draft.time)
    if date_iso and len(slots) == 1:
        return _selected_datetime_reply(draft, date_iso, slots[0])
    if date_iso and slots:
        rows = "\n".join(
            f"・{format_booking_datetime(date_iso, t, duration)}" for t in slots
        )
        return (
            f"{_format_jp_date_short(date_iso)}は以下の時間に空きがあります。\n\n{rows}\n\n"
            "ご都合の良い日時があれば教えてください。"
        )
    return None


def _request_line(draft: BookingDraft) -> str:
    if draft.preferred_treatment:
        return f"ご要望：{draft.preferred_treatment}を希望"
    return "ご要望：特になし"


def _place_label(place_type: str | None) -> str:
    if place_type == "visit":
        return "出張"
    if place_type == "in_house":
        return "院内"
    return "未定"


def build_confirmation_reply(draft: BookingDraft) -> str:
    date_iso = draft.confirmed_date or draft.selected_date or draft.date
    time_s = draft.confirmed_time or draft.selected_time or draft.time
    duration = draft.confirmed_duration_minutes or draft.duration_minutes
    area = _area_label(draft.confirmed_area or draft.area)
    place = draft.confirmed_place_type or draft.place_type
    date_line = format_booking_datetime(date_iso, time_s, duration)
    lines = [
        "予約内容をご確認ください。",
        "",
        f"日時：{date_line}",
        f"施術時間：{duration}分" if duration else "施術時間：未定",
        f"エリア：{area}" if area else "エリア：未定",
        f"施術場所：{_place_label(place)}",
    ]
    if place == "visit" and draft.guest_place_name:
        lines.append(f"出張先：{draft.guest_place_name}")
    if draft.guest_last_name and draft.guest_first_name:
        lines.append(f"お名前：{draft.guest_last_name} {draft.guest_first_name}")
    if draft.guest_phone:
        lines.append(f"電話番号：{draft.guest_phone}")
    if draft.guest_email:
        lines.append(f"メールアドレス：{draft.guest_email}")
    lines.extend(
        [
            _request_line(draft),
            "",
            "この内容で予約を確定しますか？",
        ]
    )
    return "\n".join(lines)


_GUEST_FIELD_LABELS = {
    "name": "姓と名",
    "phone": "お電話番号",
    "email": "メールアドレス",
    "dispatch_destination": "出張先",
}


def build_guest_info_ask(draft: BookingDraft) -> str:
    missing = missing_guest_fields(draft)
    required = required_guest_fields(draft)
    if not missing:
        return "予約に必要な情報を確認しています。"
    if missing == required:
        items = "姓・名・電話番号・メールアドレス"
        if "dispatch_destination" in required:
            items += "・出張先"
        return (
            "ご予約に必要な情報をお伺いします。\n"
            f"{items}を、分かる範囲でまとめて入力してください。\n"
            "「姓：」などのラベルは不要です。改行でも1行でも大丈夫です。"
        )

    name_bit = None
    other: list[str] = []
    if "name" in missing:
        has_last = bool(draft.guest_last_name)
        has_first = bool(draft.guest_first_name)
        if not has_last and not has_first:
            name_bit = "お名前の姓と名"
        elif has_last and not has_first:
            name_bit = "お名前の名"
        else:
            name_bit = "お名前の姓"
    for key in missing:
        if key == "name":
            continue
        label = _GUEST_FIELD_LABELS.get(key)
        if label:
            other.append(label)
    bits = ([name_bit] if name_bit else []) + other
    unrecognized_name = bool(
        "name" in missing and not draft.guest_last_name and not draft.guest_first_name
    )
    if unrecognized_name:
        if not other:
            return NAME_NEWLINE_ASK
        extra = "と".join(other)
        return f"{NAME_NEWLINE_ASK}\nあわせて、{extra}も教えてください。"
    if len(bits) == 1:
        return f"ありがとうございます。あと、{bits[0]}だけ教えてください。"
    joined = "と".join(bits)
    return f"ありがとうございます。{joined}を教えてください。"


def build_booking_success_reply(draft: BookingDraft) -> str:
    date_iso = draft.confirmed_date or draft.date
    time_s = draft.confirmed_time or draft.time
    duration = draft.confirmed_duration_minutes or draft.duration_minutes
    date_line = format_booking_datetime(date_iso, time_s, duration)
    return (
        "ご予約が完了しました。\n"
        f"日時：{date_line}\n"
        f"施術時間：{duration}分\n"
        "確認メールをお送りします。当日はどうぞよろしくお願いいたします。"
    )


def enter_confirming(draft: BookingDraft) -> None:
    if draft.phase == PHASE_ALT:
        apply_alternative_acceptance(draft)
    draft.selected_date = draft.date
    draft.selected_time = draft.time
    apply_offered_place_type(draft)
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
    place_type = current_chat_booking_place_type(draft)
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

