"""GBPのスケジュール投稿と営業時間。

判定材料は /schedule と同じシフトと帯同予定。
投稿と営業時間は別処理。Googleへは、呼び出し側が明示したときだけ送る。
"""

from __future__ import annotations

import json
import re
from datetime import date
from urllib.parse import quote

from official_site_data import AREAS

PROFILES = ("tokyo", "fukuoka")
WEEKDAYS_JA = "月火水木金土日"
WEEKDAYS_API = ("MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY")
SCHEDULE_URL = "https://karin-sb.jp/schedule"
BOOK_URL = "https://karin-sb.jp/book"
LOCATION_URL = "https://mybusinessbusinessinformation.googleapis.com/v1/{name}"
HOURS_READ_MASK = "name,regularHours,specialHours"
_LOCATION_NAME = re.compile(r"^locations/[A-Za-z0-9_-]+$")
LOCKED_STATUSES = frozenset({"posted", "posting", "unknown"})
HOURS_LOCKED = frozenset({"unknown"})
POSTS_TABLE = "gbp_schedule_posts"
POST_EVENTS_TABLE = "gbp_schedule_post_events"
HOURS_TABLE = "gbp_hours_syncs"

DEFAULT_LABELS = {
    "tokyo": "東京（代々木上原）",
    "fukuoka": "福岡（薬院）",
    "field": "トレーナー帯同",
    "closed": "休業",
}

HOURS_REASON_LABELS = {
    "clinic_only": "通常営業",
    "other_area": "他地域の予定",
    "field": "トレーナー帯同",
    "overlap": "勤務と帯同が重複",
    "off": "休業日",
    "unset": "予定なし",
    "undetermined": "判定不能",
}


class GbpHoursRefused(Exception):
    def __init__(self, detail):
        self.detail = detail
        super().__init__(detail)


class GbpHoursTimeout(Exception):
    """営業時間の応答がなく、更新できたか分からない。"""


def explicit_area(raw):
    area = raw.strip().lower() if isinstance(raw, str) else ""
    return area if area in PROFILES else None


def hours_status(profile, mode, area, has_field):
    """該当地域がその日通常営業か。開く条件以外はすべて休業。"""
    if profile not in PROFILES:
        return "closed", "undetermined"
    if mode == "clinic" and area in PROFILES and has_field:
        return "closed", "overlap"
    if mode == "field":
        return "closed", "field"
    if mode == "off":
        return "closed", "off"
    if mode != "clinic":
        return "closed", "unset"
    if area not in PROFILES:
        return "closed", "undetermined"
    if area != profile:
        return "closed", "other_area"
    return "open", "clinic_only"


def post_entry(profile, mode, area, has_field, labels=None):
    """投稿に載せる1日。時間が無い日は作らない。帯同がある日は施術対応日にしない。"""
    names = labels or DEFAULT_LABELS
    if profile not in PROFILES:
        return None
    if mode == "field" or (mode == "clinic" and area in PROFILES and has_field):
        return {"kind": "field", "label": names["field"]}
    if mode == "clinic" and area == profile:
        return {"kind": "clinic", "label": names[area]}
    if mode == "off":
        return {"kind": "off", "label": names["closed"]}
    return None


def parse_site_clock(hhmm):
    """公式の基本時間。26:00 は翌02:00。推測しない。"""
    text = str(hhmm or "").strip()
    parts = text.split(":")
    if len(parts) != 2:
        return None
    try:
        hour = int(parts[0])
        minute = int(parts[1])
    except ValueError:
        return None
    if minute < 0 or minute > 59 or hour < 0 or hour > 35:
        return None
    if hour == 24:
        return {"hours": 24, "minutes": minute}, 0
    if hour > 24:
        return {"hours": hour - 24, "minutes": minute}, 1
    return {"hours": hour, "minutes": minute}, 0


def regular_hours_for(profile):
    area = AREAS.get(profile) if profile in PROFILES else None
    if not area:
        raise GbpHoursRefused("地域の基本営業時間が確認できないため、設定しません")
    opened = parse_site_clock(area.get("hours_start"))
    closed = parse_site_clock(area.get("hours_end"))
    if not opened or not closed:
        raise GbpHoursRefused("基本営業時間の形式が確認できないため、設定しません")
    open_time, open_extra = opened
    close_time, close_extra = closed
    if open_extra:
        raise GbpHoursRefused("開始時刻が日をまたぐため、設定しません")
    periods = []
    for index, day_name in enumerate(WEEKDAYS_API):
        close_day = WEEKDAYS_API[(index + close_extra) % 7]
        periods.append(
            {
                "openDay": day_name,
                "openTime": open_time,
                "closeDay": close_day,
                "closeTime": close_time,
            }
        )
    return {"periods": periods}


def date_payload(value):
    return {"year": value.year, "month": value.month, "day": value.day}


def payload_date(value):
    if not isinstance(value, dict):
        return None
    try:
        return date(int(value["year"]), int(value["month"]), int(value["day"]))
    except (KeyError, TypeError, ValueError):
        return None


def hours_window(period_start, period_end, today):
    """Googleへ出す特別営業時間。今日(JST)から期間末まで。過去日は含めない。"""
    if period_end < period_start:
        return None
    start = period_start if period_start >= today else today
    if period_end < start:
        return None
    return start, period_end


def merge_special_hours(existing_periods, window_start, window_end, closed_dates):
    """窓の中だけ置き換える。窓の外と読めない行は残す。"""
    kept = []
    for period in existing_periods or []:
        if not isinstance(period, dict):
            continue
        start = payload_date(period.get("startDate"))
        if start is None or start < window_start or start > window_end:
            kept.append(period)
    closed = sorted({item for item in closed_dates if window_start <= item <= window_end})
    for item in closed:
        kept.append({"startDate": date_payload(item), "closed": True})
    return {"specialHourPeriods": kept}


def location_hours_get_request(location_name):
    if not _LOCATION_NAME.fullmatch(location_name or ""):
        raise GbpHoursRefused("ロケーション名が不正なため、取得しません")
    url = LOCATION_URL.format(name=location_name) + "?readMask=" + quote(HOURS_READ_MASK, safe=",")
    return {"method": "GET", "url": url, "body": None}


def location_hours_patch_request(location_name, regular_hours, special_hours):
    if not _LOCATION_NAME.fullmatch(location_name or ""):
        raise GbpHoursRefused("ロケーション名が不正なため、更新しません")
    return {
        "method": "PATCH",
        "url": LOCATION_URL.format(name=location_name) + "?updateMask=regularHours,specialHours",
        "body": {"regularHours": regular_hours, "specialHours": special_hours},
    }


def hours_exchange(method, url, *, access_token, body=None, timeout=20):
    """営業時間の GET と PATCH だけ。投稿作成はしない。"""
    if method not in {"GET", "PATCH"}:
        raise GbpHoursRefused("営業時間ではこの操作はしません")
    import requests

    headers = {"Authorization": f"Bearer {access_token}"}
    kwargs = {"headers": headers, "timeout": timeout}
    if body is not None:
        headers["Content-Type"] = "application/json"
        kwargs["json"] = body
    try:
        response = requests.request(method, url, **kwargs)
    except requests.RequestException:
        raise GbpHoursTimeout()
    try:
        parsed = response.json()
    except ValueError:
        parsed = {}
    if not isinstance(parsed, dict):
        parsed = {}
    return response.status_code, parsed


def profile_location_name(config, profile):
    if profile not in PROFILES:
        raise GbpHoursRefused("東京か福岡だけ更新できます")
    name = ((config or {}).get("locations") or {}).get(profile) or ""
    if not _LOCATION_NAME.fullmatch(name):
        raise GbpHoursRefused("この地域のロケーション名が確認できないため、更新しません")
    other = "fukuoka" if profile == "tokyo" else "tokyo"
    other_name = ((config or {}).get("locations") or {}).get(other) or ""
    if other_name and other_name == name:
        raise GbpHoursRefused("東京と福岡のロケーションが同じため、更新しません")
    return name


def plan_hours_update(profile, config, existing_body, closed_dates, window_start, window_end):
    location_name = profile_location_name(config, profile)
    returned = existing_body.get("name") if isinstance(existing_body, dict) else ""
    if returned and returned != location_name:
        raise GbpHoursRefused("応答のロケーションが指定と一致しないため、更新しません")
    existing = []
    if isinstance(existing_body, dict):
        special = existing_body.get("specialHours") if isinstance(existing_body.get("specialHours"), dict) else {}
        existing = special.get("specialHourPeriods") if isinstance(special.get("specialHourPeriods"), list) else []
    regular = regular_hours_for(profile)
    special = merge_special_hours(existing, window_start, window_end, closed_dates)
    request = location_hours_patch_request(location_name, regular, special)
    request["location_name"] = location_name
    request["regularHours"] = regular
    request["specialHours"] = special
    return request


def regular_hours_match(expected, actual):
    got = actual.get("periods") if isinstance(actual, dict) else None
    want = expected.get("periods") if isinstance(expected, dict) else None
    return _json_same(want, got)


def window_specials_match(expected, actual, window_start, window_end):
    def in_window(periods):
        items = []
        for period in periods or []:
            if not isinstance(period, dict):
                continue
            start = payload_date(period.get("startDate"))
            if start is None or start < window_start or start > window_end:
                continue
            items.append(
                {
                    "date": start.isoformat(),
                    "closed": bool(period.get("closed")),
                    "openTime": period.get("openTime"),
                    "closeTime": period.get("closeTime"),
                }
            )
        return sorted(items, key=lambda item: item["date"])

    expected_periods = expected.get("specialHourPeriods") if isinstance(expected, dict) else []
    actual_periods = actual.get("specialHourPeriods") if isinstance(actual, dict) else []
    return _json_same(in_window(expected_periods), in_window(actual_periods))


def _json_same(left, right):
    return json.dumps(left, sort_keys=True, default=str) == json.dumps(right, sort_keys=True, default=str)


def format_day_line(day, weekday, label):
    return f"{day.month}月{day.day}日（{weekday}） {label}".rstrip()


def build_schedule_body(profile, days, labels=None, weekdays=WEEKDAYS_JA):
    """確定した予定だけを書く。時間は補わない。"""
    if profile not in PROFILES:
        raise ValueError("profile は tokyo または fukuoka です")
    names = labels or DEFAULT_LABELS
    clinic_lines = []
    field_lines = []
    closed_lines = []
    for item in days or []:
        entry = post_entry(profile, item.get("mode"), item.get("area"), bool(item.get("has_field")), names)
        if not entry:
            continue
        day = item["date"] if isinstance(item.get("date"), date) else date.fromisoformat(item["date"])
        weekday = weekdays[day.weekday()]
        line = format_day_line(day, weekday, entry["label"] if entry["kind"] == "clinic" else "")
        if entry["kind"] == "clinic":
            clinic_lines.append(line)
        elif entry["kind"] == "field":
            field_lines.append(format_day_line(day, weekday, ""))
        else:
            closed_lines.append(format_day_line(day, weekday, ""))
    title = "東京" if profile == "tokyo" else "福岡"
    parts = [
        f"KARiN. {title}のスケジュール案内です。",
        "",
        "この投稿は予定の案内です。受付の空き状況そのものではありません。",
    ]
    if clinic_lines:
        parts.extend(["", "【対応日】", *clinic_lines])
    if field_lines:
        parts.extend(["", "【トレーナー帯同】", *field_lines])
    if closed_lines:
        parts.extend(["", "【休業】", *closed_lines])
    if not (clinic_lines or field_lines or closed_lines):
        parts.extend(
            [
                "",
                "この期間に掲載できる確定した予定はありません。最新の予定はスケジュールページでご確認ください。",
            ]
        )
    else:
        parts.extend(["", "詳細はスケジュールページでご確認ください。"])
    parts.extend(["", SCHEDULE_URL, "", "ご予約はこちら", BOOK_URL])
    return "\n".join(parts).strip() + "\n"


def describe_days(day_facts, labels=None, weekdays=WEEKDAYS_JA):
    names = labels or DEFAULT_LABELS
    rows = []
    for item in day_facts or []:
        day = item["date"] if isinstance(item.get("date"), date) else date.fromisoformat(str(item["date"]))
        mode = item.get("mode") or "unset"
        area = item.get("area")
        has_field = bool(item.get("has_field"))
        hours = {}
        posts = {}
        for profile in PROFILES:
            state, reason = hours_status(profile, mode, area, has_field)
            hours[profile] = {
                "state": state,
                "reason": reason,
                "label": "通常営業" if state == "open" else "休業",
                "reason_label": HOURS_REASON_LABELS.get(reason, reason),
            }
            entry = post_entry(profile, mode, area, has_field, names)
            posts[profile] = entry["label"] if entry else ""
        rows.append(
            {
                "date": day.isoformat(),
                "weekday": weekdays[day.weekday()],
                "mode": mode,
                "area": area,
                "has_field": has_field,
                "hours": hours,
                "post_labels": posts,
            }
        )
    return rows


def closed_dates_for(rows, profile, window_start, window_end):
    closed = []
    for row in rows or []:
        day = date.fromisoformat(row["date"])
        if day < window_start or day > window_end:
            continue
        if row["hours"][profile]["state"] != "open":
            closed.append(day)
    return closed


def hours_status_caption(status):
    return {
        "applied": "更新済",
        "failed": "失敗",
        "unknown": "要確認",
    }.get(status or "", "未更新")


def hours_preview_rows(rows, today, window):
    preview = {profile: [] for profile in PROFILES}
    for row in rows or []:
        day = date.fromisoformat(row["date"])
        for profile in PROFILES:
            if window is None or day < window[0] or day > window[1]:
                action = "対象外（過去）" if day < today else "対象外"
            elif row["hours"][profile]["state"] == "open":
                action = "通常営業時間"
            else:
                action = "終日休業"
            preview[profile].append(
                {
                    "date": row["date"],
                    "weekday": row["weekday"],
                    "action": action,
                    "reason_label": row["hours"][profile]["reason_label"],
                }
            )
    return preview


def prepare_schedule_save(existing, period_key, profile, body, link_url, staff_id, now):
    if profile not in PROFILES:
        return None, "東京か福岡の投稿だけ保存できます。"
    if existing and (
        existing.get("period_key") != period_key or existing.get("gbp_profile") != profile
    ):
        return None, "別の期間・地域の記録は変更しません。"
    if existing and existing.get("status") in LOCKED_STATUSES:
        return None, "投稿済み、送信中、または成否未確認の記録は、この画面からは変更しません。"
    fields = {
        "period_key": period_key,
        "gbp_profile": profile,
        "status": "draft",
        "body": body,
        "link_url": link_url or SCHEDULE_URL,
        "image_url": None,
        "error_message": None,
        "updated_at": now,
        "created_by": staff_id or None,
    }
    if existing:
        fields["external_id"] = existing.get("external_id")
        fields["posted_at"] = existing.get("posted_at")
    else:
        fields["external_id"] = None
        fields["posted_at"] = None
        fields["created_at"] = now
    event = {
        "event": "edited",
        "body_snapshot": body,
        "link_url": link_url or SCHEDULE_URL,
        "detail": "保存のみ。外部サービスへは投稿していません。",
        "actor_staff_id": staff_id or None,
        "created_at": now,
    }
    return {"fields": fields, "event": event, "is_insert": not bool(existing)}, None


def prepare_schedule_confirm(existing, period_key, profile, body, link_url, staff_id, now):
    if not existing:
        return None, "保存してから確認済にします。"
    prepared, reason = prepare_schedule_save(existing, period_key, profile, body, link_url, staff_id, now)
    if reason:
        return None, reason
    prepared["fields"]["status"] = "ready"
    prepared["event"] = {
        "event": "confirmed",
        "body_snapshot": body,
        "link_url": link_url or SCHEDULE_URL,
        "detail": "確認のみ。外部サービスへは投稿していません。",
        "actor_staff_id": staff_id or None,
        "created_at": now,
    }
    prepared["is_insert"] = False
    return prepared, None


def find_schedule_post(client, period_key, profile):
    res = (
        client.table(POSTS_TABLE)
        .select("*")
        .eq("period_key", period_key)
        .eq("gbp_profile", profile)
        .limit(1)
        .execute()
    )
    rows = res.data or []
    return rows[0] if rows else None


def find_hours_sync(client, period_key, profile):
    res = (
        client.table(HOURS_TABLE)
        .select("*")
        .eq("period_key", period_key)
        .eq("gbp_profile", profile)
        .limit(1)
        .execute()
    )
    rows = res.data or []
    return rows[0] if rows else None


def list_schedule_events(client, post_id):
    if not post_id:
        return []
    res = (
        client.table(POST_EVENTS_TABLE)
        .select("id,event,detail,body_snapshot,created_at")
        .eq("schedule_post_id", post_id)
        .order("created_at", desc=True)
        .limit(10)
        .execute()
    )
    return list(res.data or [])


def save_schedule_post(client, existing, prepared):
    fields = prepared["fields"]
    if prepared["is_insert"]:
        res = client.table(POSTS_TABLE).insert(fields).execute()
    else:
        query = client.table(POSTS_TABLE).update(fields).eq("id", existing["id"])
        expected = existing.get("status")
        if expected:
            query = query.eq("status", expected)
        res = query.execute()
        if expected and not (res.data or []):
            from external_posts import ExternalPostConflict

            raise ExternalPostConflict("状態が変わったため保存しませんでした。画面を開き直してください。")
    rows = res.data or []
    saved = rows[0] if rows else dict(existing or {})
    event = dict(prepared["event"])
    event["schedule_post_id"] = saved["id"]
    client.table(POST_EVENTS_TABLE).insert(event).execute()
    return saved


def update_schedule_post_if_status(client, post_id, from_statuses, fields):
    statuses = [status for status in from_statuses if status]
    query = client.table(POSTS_TABLE).update(fields).eq("id", post_id)
    if len(statuses) == 1:
        query = query.eq("status", statuses[0])
    elif statuses:
        query = query.in_("status", statuses)
    res = query.execute()
    rows = res.data or []
    return rows[0] if rows else None


def insert_schedule_event(client, post_id, event):
    payload = dict(event)
    payload["schedule_post_id"] = post_id
    client.table(POST_EVENTS_TABLE).insert(payload).execute()


def schedule_post_store():
    return {
        "update_if_status": update_schedule_post_if_status,
        "insert_event": insert_schedule_event,
    }


def perform_schedule_gbp_send(client, record, **kwargs):
    import gbp_local_post

    kwargs = dict(kwargs)
    kwargs["post_store"] = schedule_post_store()
    return gbp_local_post.perform_notes_gbp_send(client, record, **kwargs)


def perform_schedule_gbp_check(client, record, **kwargs):
    import gbp_local_post

    kwargs = dict(kwargs)
    kwargs["post_store"] = schedule_post_store()
    return gbp_local_post.perform_notes_gbp_check(client, record, **kwargs)


def upsert_hours_sync(client, existing, fields):
    if existing:
        res = client.table(HOURS_TABLE).update(fields).eq("id", existing["id"]).execute()
    else:
        res = client.table(HOURS_TABLE).insert(fields).execute()
    rows = res.data or []
    return rows[0] if rows else fields


def perform_hours_apply(
    client,
    *,
    period_key,
    profile,
    config,
    token_exchange,
    hours_http,
    closed_dates,
    window_start,
    window_end,
    now,
    existing=None,
):
    """GETして窓の中だけ PATCH し、再GETで確認する。投稿は作らない。"""
    import gbp_read

    if profile not in PROFILES:
        return {"ok": False, "status": "failed", "message": "東京か福岡だけ更新できます。"}
    if existing and existing.get("status") in HOURS_LOCKED:
        return {
            "ok": False,
            "status": "unknown",
            "message": "前回の営業時間更新が未確認です。再実行せず、確認してください。",
        }
    if window_start is None or window_end is None or window_end < window_start:
        return {"ok": False, "status": "failed", "message": "更新できる日付がありません。"}
    try:
        location_name = profile_location_name(config, profile)
        token = gbp_read.fetch_access_token(config, token_exchange)
        get_req = location_hours_get_request(location_name)
        status, body = hours_http(get_req["method"], get_req["url"], access_token=token, body=None)
        if status != 200:
            return _hours_result(False, "failed", "営業時間を取得できなかったため、更新していません。")
        planned = plan_hours_update(profile, config, body, closed_dates, window_start, window_end)
    except GbpHoursRefused as exc:
        return _hours_result(False, "failed", exc.detail)
    except GbpHoursTimeout:
        return _hours_result(False, "unknown", "営業時間の取得が確認できないため、更新していません。")
    except gbp_read.GbpReadError as exc:
        return _hours_result(False, "failed", exc.detail)
    try:
        patch_status, patch_body = hours_http(
            planned["method"], planned["url"], access_token=token, body=planned["body"]
        )
        timed_out = False
    except GbpHoursTimeout:
        patch_status, patch_body, timed_out = None, {}, True
    except Exception:
        patch_status, patch_body, timed_out = None, {}, True
    payload_text = json.dumps(
        {
            "regularHours": planned["regularHours"],
            "specialHours": planned["specialHours"],
            "window_start": window_start.isoformat(),
            "window_end": window_end.isoformat(),
        },
        ensure_ascii=False,
    )
    if timed_out or patch_status is None or patch_status >= 500:
        saved = _store_hours(
            client,
            existing,
            period_key,
            profile,
            "unknown",
            payload_text,
            now,
            "結果不明。自動では再実行しません。",
        )
        return _hours_result(False, "unknown", "営業時間の更新結果を確定できません。自動では再実行しません。", saved)
    if patch_status != 200:
        saved = _store_hours(
            client,
            existing,
            period_key,
            profile,
            "failed",
            payload_text,
            now,
            "営業時間の更新に失敗しました。",
        )
        return _hours_result(False, "failed", "営業時間の更新に失敗しました。自動では再実行しません。", saved)
    try:
        confirm_status, confirm_body = hours_http(
            get_req["method"], get_req["url"], access_token=token, body=None
        )
    except GbpHoursTimeout:
        saved = _store_hours(
            client, existing, period_key, profile, "unknown", payload_text, now, "更新後の確認ができませんでした。"
        )
        return _hours_result(False, "unknown", "更新後の確認ができませんでした。自動では再実行しません。", saved)
    if confirm_status != 200:
        saved = _store_hours(
            client, existing, period_key, profile, "unknown", payload_text, now, "更新後の確認ができませんでした。"
        )
        return _hours_result(False, "unknown", "更新後の確認ができませんでした。自動では再実行しません。", saved)
    actual_regular = confirm_body.get("regularHours") if isinstance(confirm_body, dict) else None
    actual_special = confirm_body.get("specialHours") if isinstance(confirm_body, dict) else None
    if not regular_hours_match(planned["regularHours"], actual_regular) or not window_specials_match(
        planned["specialHours"], actual_special, window_start, window_end
    ):
        saved = _store_hours(
            client,
            existing,
            period_key,
            profile,
            "unknown",
            payload_text,
            now,
            "更新内容を確認できませんでした。",
        )
        return _hours_result(False, "unknown", "更新内容を確認できないため、成功にしていません。", saved)
    saved = _store_hours(client, existing, period_key, profile, "applied", payload_text, now, None, applied=True)
    return _hours_result(True, "applied", "営業時間を更新し、内容を確認しました。", saved)


def perform_hours_check(
    client,
    *,
    period_key,
    profile,
    config,
    token_exchange,
    hours_http,
    expected_payload,
    window_start,
    window_end,
    now,
    existing=None,
):
    import gbp_read

    if not existing or existing.get("status") != "unknown":
        return {"ok": False, "status": existing.get("status") if existing else None, "message": "未確認の更新だけ確認します。"}
    try:
        payload = json.loads(expected_payload or existing.get("payload") or "{}")
        location_name = profile_location_name(config, profile)
        token = gbp_read.fetch_access_token(config, token_exchange)
        get_req = location_hours_get_request(location_name)
        status, body = hours_http(get_req["method"], get_req["url"], access_token=token, body=None)
    except GbpHoursRefused as exc:
        return _hours_result(False, "unknown", exc.detail, existing)
    except GbpHoursTimeout:
        return _hours_result(False, "unknown", "営業時間を取得できませんでした。", existing)
    except gbp_read.GbpReadError as exc:
        return _hours_result(False, "unknown", exc.detail, existing)
    if status != 200:
        return _hours_result(False, "unknown", "営業時間を取得できなかったため、確定しません。", existing)
    actual_regular = body.get("regularHours") if isinstance(body, dict) else None
    actual_special = body.get("specialHours") if isinstance(body, dict) else None
    if regular_hours_match(payload.get("regularHours"), actual_regular) and window_specials_match(
        payload.get("specialHours"), actual_special, window_start, window_end
    ):
        saved = _store_hours(
            client, existing, period_key, profile, "applied", existing.get("payload"), now, None, applied=True
        )
        return _hours_result(True, "applied", "営業時間の更新内容を確認しました。", saved)
    return _hours_result(False, "unknown", "営業時間の内容が一致しないため、成功にしていません。", existing)


def _store_hours(client, existing, period_key, profile, status, payload, now, error, applied=False):
    fields = {
        "period_key": period_key,
        "gbp_profile": profile,
        "status": status,
        "payload": payload,
        "error_message": error,
        "updated_at": now,
        "applied_at": now if applied else (existing or {}).get("applied_at"),
    }
    try:
        return upsert_hours_sync(client, existing, fields)
    except Exception:
        return fields


def _hours_result(ok, status, message, record=None):
    return {"ok": ok, "status": status, "message": message, "record": record}
