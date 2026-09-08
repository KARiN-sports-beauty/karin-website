"""幅広い日付・時間条件と、既存枠算出への引き渡し。

  python scripts/test_karin_chat_booking_window.py
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from dotenv import load_dotenv

load_dotenv(os.path.join(ROOT, ".env"), override=True)

from ai_knowledge import get_admin_client  # noqa: E402
from karin_chat import run_chat  # noqa: E402
from karin_chat_booking import (  # noqa: E402
    DATE_WINDOW_ASK_REPLY,
    _call_existing_slots,
    _parse_clock_time,
    _parse_day_only,
    _parse_month_day,
    _parse_time_from,
    parse_booking_request,
)
from karin_chat_memory import reset_store_for_tests  # noqa: E402

SNAPSHOT_SELECT = (
    "id,title,content,category,source_type,status,priority,"
    "source_key,source_url,effective_from,effective_to,updated_at,embedding"
)
EXPECTED_HASH = "ec0bff70d737b542f5419ebbaf9d44e76e5e085b06943dc11aa7232efa9fe373"
JST = timezone(timedelta(hours=9))
DATE_ASK_LOOP = "ご希望の日付や時間帯があれば教えてください。"
NO_SLOT_GENERIC = "ご希望の条件では、現在確認できる空き枠がありませんでした。"


def snapshot_knowledge(admin) -> tuple[int, str]:
    res = admin.table("ai_knowledge").select(SNAPSHOT_SELECT).order("id").execute()
    rows = list(res.data or [])
    blob = json.dumps(rows, ensure_ascii=False, sort_keys=True, default=str)
    return len(rows), hashlib.sha256(blob.encode("utf-8")).hexdigest()


def today_jst():
    return datetime.now(JST).date()


def next_iso(month: int, day: int) -> str:
    today = today_jst()
    try:
        candidate = today.replace(month=month, day=day)
    except ValueError:
        candidate = today
    if candidate < today:
        candidate = candidate.replace(year=today.year + 1)
    return candidate.isoformat()


def day_iso(day: int) -> str:
    today = today_jst()
    for i in range(0, 45):
        d = today + timedelta(days=i)
        if d.day == day:
            return d.isoformat()
    raise RuntimeError(f"{day}日が予約期間にない")


def jp_date(iso: str) -> str:
    _y, month, day = iso.split("-")
    return f"{int(month)}月{int(day)}日"


def continue_chat(message: str, previous, **kwargs):
    cid = None if previous is None else previous.conversation_id
    return run_chat(message, conversation_id=cid, **kwargs)


def empty_match(*_a, **_k):
    return []


def complete(_messages):
    return "承知しました。"


def mock_slots(*times: str):
    calls: list[dict] = []

    def lookup(**kwargs):
        calls.append(dict(kwargs))
        slots = [{"time": t, "available": True} for t in times]
        return {
            "date": kwargs.get("date"),
            "area": kwargs.get("area"),
            "place_type": kwargs.get("place_type"),
            "duration_minutes": kwargs.get("duration_minutes"),
            "staff": [],
            "free_row": {"staff_name": "フリー", "slots": slots},
        }

    lookup.calls = calls  # type: ignore[attr-defined]
    return lookup


def mock_by_date(plan, default=None):
    calls: list[dict] = []
    default = [] if default is None else list(default)

    def lookup(**kwargs):
        calls.append(dict(kwargs))
        date = kwargs.get("date")
        times = plan.get(date, default)
        slots = [{"time": t, "available": True} for t in times]
        return {
            "date": date,
            "area": kwargs.get("area"),
            "place_type": kwargs.get("place_type"),
            "duration_minutes": kwargs.get("duration_minutes"),
            "staff": [],
            "free_row": {"staff_name": "フリー", "slots": slots},
        }

    lookup.calls = calls  # type: ignore[attr-defined]
    return lookup


def recording_real_lookup():
    calls: list[dict] = []

    def lookup(**kwargs):
        calls.append(dict(kwargs))
        return _call_existing_slots(**kwargs)

    lookup.calls = calls  # type: ignore[attr-defined]
    return lookup


def start_area_duration(lookup):
    kwargs = dict(match_fn=empty_match, complete_fn=complete, lookup_fn=lookup)
    t0 = continue_chat("予約がしたいです", None, **kwargs)
    t1 = continue_chat("東京で90分", t0, **kwargs)
    return t1, kwargs


def later_calls(lookup, n_before: int) -> list[dict]:
    return list(lookup.calls[n_before:])


def main() -> int:
    print("mode: 予約ウィンドウ / Knowledge読み取り専用 / 予約確定なし")
    reset_store_for_tests()
    failures: list[str] = []
    admin = get_admin_client()
    before_n, before_h = snapshot_knowledge(admin)
    print("snapshot before:", before_n, before_h)
    if before_h != EXPECTED_HASH:
        failures.append(f"開始時 hash 不一致 {before_h}")

    today = today_jst()
    d910 = next_iso(9, 10)
    print("  today", today, "9/10 →", d910)

    print("\n===== parse A-I =====")
    if _parse_time_from("直近で18時〜取れるところ") != "18:00":
        failures.append("A parse: 直近で18時〜 の time_from")
    if _parse_time_from("18:00") is not None:
        failures.append("D parse: 18:00 を time_from にしている")
    if _parse_clock_time("18:00") != "18:00":
        failures.append("D parse: 18:00 が time でない")
    if _parse_time_from("18:00〜") != "18:00":
        failures.append("E parse: 18:00〜")
    if _parse_time_from("18時以降") != "18:00":
        failures.append("F parse: 18時以降")
    if _parse_month_day("9/10", today) != d910:
        failures.append(f"G parse: 9/10 → {_parse_month_day('9/10', today)}")
    if _parse_month_day("9月10日", today) != d910:
        failures.append(f"H parse: 9月10日 → {_parse_month_day('9月10日', today)}")
    if _parse_day_only("10日", today, [d910, next_iso(9, 11)]) != d910:
        failures.append(f"I parse: 10日 → {_parse_day_only('10日', today, [d910])}")
    soon = parse_booking_request(["直近で18時〜取れるところ"], today=today)
    if soon.time_from != "18:00" or not soon.date_candidates:
        failures.append(f"A parse req: from={soon.time_from} cands={soon.date_candidates[:3]}")
    night = parse_booking_request(["平日の夜"], today=today)
    if night.time_range != "night" or not night.date_candidates:
        failures.append(f"B parse: range={night.time_range} cands={night.date_candidates}")
    weekend = parse_booking_request(["土日で空いている日"], today=today)
    if weekend.window_kind != "weekend" or not weekend.date_candidates:
        failures.append(f"C parse: window={weekend.window_kind}")

    print("\n===== A 直近で18時〜 は日付を聞き返さない =====")
    reset_store_for_tests()
    lookup_a = mock_slots("19:00", "19:30", "20:00")
    t, kw = start_area_duration(lookup_a)
    if DATE_ASK_LOOP not in (t.reply or ""):
        failures.append("Q: エリア・時間後に日付/時間帯の案内がない")
    t_a = continue_chat("直近で18時〜取れるところ", t, **kw)
    print("  A from", t_a.time_from, "dates", t_a.available_dates, "calls", len(lookup_a.calls))
    print("  A reply", (t_a.reply or "")[:120])
    if t_a.time_from != "18:00":
        failures.append(f"A: time_from={t_a.time_from}")
    if t_a.reply == DATE_WINDOW_ASK_REPLY or (t_a.reply or "").strip() == DATE_ASK_LOOP:
        failures.append("A: 直近で18時〜 なのに日付を聞き返している")
    if (t_a.reply or "").count(DATE_ASK_LOOP) and "直近" not in (t_a.reply or ""):
        if "空き" not in (t_a.reply or "") and "どの日" not in (t_a.reply or ""):
            failures.append("A: 検索せず同じ質問に戻っている")
    if not lookup_a.calls:
        failures.append("A: 既存枠検索を呼んでいない")
    else:
        args0 = lookup_a.calls[0]
        print("  A first lookup", args0)
        if args0.get("area") != "tokyo" or args0.get("duration_minutes") != 90:
            failures.append(f"A: lookup args={args0}")

    print("\n===== B 平日の夜 =====")
    reset_store_for_tests()
    lookup_b = mock_slots("18:00", "19:00")
    t, kw = start_area_duration(lookup_b)
    t_b = continue_chat("平日の夜", t, **kw)
    print("  B period", t_b.time_period, "dates", t_b.available_dates)
    if t_b.time_period != "night":
        failures.append(f"B: time_period={t_b.time_period}")
    if t_b.reply == DATE_WINDOW_ASK_REPLY:
        failures.append("B: 平日の夜なのに日付質問へ戻っている")

    print("\n===== C 土日で空いている日 =====")
    reset_store_for_tests()
    lookup_c = mock_slots("10:00", "11:00")
    t, kw = start_area_duration(lookup_c)
    t_c = continue_chat("土日で空いている日", t, **kw)
    print("  C range", t_c.date_range, "dates", t_c.available_dates)
    if t_c.date_range != "weekend":
        failures.append(f"C: date_range={t_c.date_range}")
    if t_c.reply == DATE_WINDOW_ASK_REPLY:
        failures.append("C: 土日指定なのに日付質問へ戻っている")

    print("\n===== D E F 時刻保持 =====")
    reset_store_for_tests()
    lookup_d = mock_slots("18:00", "19:00")
    t, kw = start_area_duration(lookup_d)
    t_d = continue_chat("18:00", t, **kw)
    print("  D time", t_d.requested_time, "from", t_d.time_from, "api", bool(lookup_d.calls))
    if t_d.requested_time != "18:00":
        failures.append(f"D: time={t_d.requested_time}")
    if t_d.reply == DATE_WINDOW_ASK_REPLY:
        failures.append("D: 18:00 なのに日付質問へ戻っている")
    reset_store_for_tests()
    lookup_e = mock_slots("18:00", "19:00")
    t, kw = start_area_duration(lookup_e)
    t_e = continue_chat("18:00〜", t, **kw)
    if t_e.time_from != "18:00":
        failures.append(f"E: time_from={t_e.time_from}")
    reset_store_for_tests()
    lookup_f = mock_slots("18:00", "19:00")
    t, kw = start_area_duration(lookup_f)
    t_f = continue_chat("18時以降", t, **kw)
    if t_f.time_from != "18:00":
        failures.append(f"F: time_from={t_f.time_from}")

    print("\n===== G H 9/10 と 9月10日 =====")
    reset_store_for_tests()
    lookup_g = mock_slots("19:00", "19:30")
    t, kw = start_area_duration(lookup_g)
    n_before = len(lookup_g.calls)
    t_g = continue_chat("9/10", t, **kw)
    print("  G date", t_g.requested_date, t_g.selected_date, "calls", later_calls(lookup_g, n_before))
    if t_g.requested_date != d910 and t_g.selected_date != d910:
        failures.append(f"G: 9/10 → {t_g.requested_date}/{t_g.selected_date} expected {d910}")
    g_dates = {c.get("date") for c in later_calls(lookup_g, n_before)}
    if g_dates and g_dates != {d910}:
        failures.append(f"G: lookup dates={g_dates}")
    reset_store_for_tests()
    lookup_h = mock_slots("19:00", "19:30")
    t, kw = start_area_duration(lookup_h)
    n_before = len(lookup_h.calls)
    t_h = continue_chat("9月10日", t, **kw)
    if t_h.requested_date != d910 and t_h.selected_date != d910:
        failures.append(f"H: 9月10日 → {t_h.requested_date}")
    h_dates = {c.get("date") for c in later_calls(lookup_h, n_before)}
    if h_dates and h_dates != {d910}:
        failures.append(f"H: lookup dates={h_dates}")

    print("\n===== I 10日 =====")
    reset_store_for_tests()
    lookup_i = mock_by_date({d910: ["19:00", "19:30"]}, default=["18:00"])
    t, kw = start_area_duration(lookup_i)
    t_soon = continue_chat("直近で18時〜取れるところ", t, **kw)
    n_before = len(lookup_i.calls)
    t_i = continue_chat("10日", t_soon, **kw)
    print("  I date", t_i.requested_date, "from", t_i.time_from)
    if t_i.requested_date != d910 and t_i.selected_date != d910:
        failures.append(f"I: 10日 → {t_i.requested_date}")

    print("\n===== J 来週の平日 → 夜 → 17日 =====")
    reset_store_for_tests()
    lookup_j = mock_slots("18:00", "19:00", "20:00")
    t, kw = start_area_duration(lookup_j)
    t_w = continue_chat("来週の平日", t, **kw)
    t_n = continue_chat("夜", t_w, **kw)
    d17 = day_iso(17)
    t_j = continue_chat("17日", t_n, **kw)
    print("  J date", t_j.requested_date, "period", t_j.time_period, "target", d17)
    if t_j.requested_date != d17 and t_j.selected_date != d17:
        failures.append(f"J: 17日 → {t_j.requested_date} expected {d17}")
    if t_j.time_period != "night":
        failures.append(f"J: 夜が消えている time_period={t_j.time_period}")

    print("\n===== K 来週の平日 → 18時以降 → 17日 =====")
    reset_store_for_tests()
    lookup_k = mock_slots("18:00", "19:00")
    t, kw = start_area_duration(lookup_k)
    t_w = continue_chat("来週の平日", t, **kw)
    t_from = continue_chat("18時以降", t_w, **kw)
    t_k = continue_chat("17日", t_from, **kw)
    print("  K date", t_k.requested_date, "from", t_k.time_from)
    if t_k.requested_date != d17 and t_k.selected_date != d17:
        failures.append(f"K: 17日 → {t_k.requested_date}")
    if t_k.time_from != "18:00":
        failures.append(f"K: time_from が消えている {t_k.time_from}")

    print("\n===== L 直近で18時〜 → 9/10 は日付を絞る =====")
    reset_store_for_tests()
    lookup_l = mock_slots("19:00", "19:30", "20:00")
    t, kw = start_area_duration(lookup_l)
    t_soon = continue_chat("直近で18時〜取れるところ", t, **kw)
    n_before = len(lookup_l.calls)
    t_l = continue_chat("9/10", t_soon, **kw)
    later = later_calls(lookup_l, n_before)
    later_dates = [c.get("date") for c in later]
    print("  L date", t_l.requested_date, "from", t_l.time_from, "later", later_dates)
    if t_l.requested_date != d910 and t_l.selected_date != d910:
        failures.append(f"L: 9/10 → {t_l.requested_date}")
    if t_l.time_from != "18:00" and t_l.requested_time not in ("18:00", None):
        failures.append(f"P: 9/10指定後に時間条件が消えた from={t_l.time_from} time={t_l.requested_time}")
    if later and any(d != d910 for d in later_dates):
        failures.append(f"L/O: 9/10指定後に他日を検索 {later_dates}")
    if jp_date(d910) not in (t_l.reply or "") and d910 not in (t_l.available_dates or []):
        if "空きがありませんでした" in (t_l.reply or "") and "19:00" not in (t_l.reply or ""):
            failures.append("L: 9/10の空きを返していない")

    print("\n===== M N 実在枠 9/10 =====")
    reset_store_for_tests()
    real = recording_real_lookup()
    live_payload = None
    try:
        live_payload = _call_existing_slots(
            area="tokyo", date=d910, duration_minutes=90, place_type="visit"
        )
    except Exception as exc:
        failures.append(f"M: 既存枠算出を呼べない {type(exc).__name__}")
    live_times = []
    if live_payload:
        live_times = [
            s.get("time")
            for s in ((live_payload.get("free_row") or {}).get("slots") or [])
            if s.get("available") and s.get("time")
        ]
    from_18 = [t for t in live_times if str(t) >= "18:00"]
    print("  live 9/10 times", live_times[:8], "from18", from_18[:8])
    t, kw = start_area_duration(real)
    t_m = continue_chat("直近で18時〜取れるところ", t, **kw)
    n_before = len(real.calls)
    t_m2 = continue_chat("9/10", t_m, **kw)
    m_later = later_calls(real, n_before)
    print("  M later args", m_later)
    print("  M reply", (t_m2.reply or "")[:160])
    if m_later:
        last = m_later[-1]
        if last.get("area") != "tokyo" or last.get("duration_minutes") != 90:
            failures.append(f"M: 最終条件 {last}")
        if last.get("date") != d910:
            failures.append(f"M: date={last.get('date')} expected {d910}")
        if any(c.get("date") != d910 for c in m_later):
            failures.append(f"O: 9/10後に他日 { [c.get('date') for c in m_later] }")
    if from_18:
        if NO_SLOT_GENERIC in (t_m2.reply or "") and "同じ日で空いている" not in (t_m2.reply or ""):
            failures.append("S/M: 実在空きがあるのに空きなし")
        if not any(x in (t_m2.reply or "") for x in from_18[:3]) and from_18[0] not in (
            t_m2.available_slots or []
        ):
            if jp_date(d910) not in (t_m2.reply or ""):
                failures.append("M: 9/10の実在空きが返信にない")
        if t_m2.time_from != "18:00":
            failures.append(f"P: 実検索後 time_from={t_m2.time_from}")
    reset_store_for_tests()
    real2 = recording_real_lookup()
    t, kw = start_area_duration(real2)
    t_n1 = continue_chat("直近で18時〜取れるところ", t, **kw)
    t_n2 = continue_chat("9月10日", t_n1, **kw)
    if t_n2.requested_date != d910 and t_n2.selected_date != d910:
        failures.append(f"N: 9月10日 → {t_n2.requested_date}")
    if from_18 and NO_SLOT_GENERIC in (t_n2.reply or "") and "同じ日で空いている" not in (
        t_n2.reply or ""
    ):
        failures.append("N: 9月10日で実在空きなのに空きなし")

    print("\n===== S 空きなしは本当に無いときだけ =====")
    reset_store_for_tests()
    lookup_s = mock_slots("19:00", "19:30")
    t, kw = start_area_duration(lookup_s)
    t_s0 = continue_chat("18:00", t, **kw)
    t_s = continue_chat("9/10", t_s0, **kw)
    print("  S reply", (t_s.reply or "")[:160])
    if NO_SLOT_GENERIC in (t_s.reply or "") and "19:00" not in (t_s.reply or ""):
        failures.append("S: 19:00があるのに汎用空きなし")
    if "19:00" not in (t_s.reply or "") and "19:00" not in (t_s.available_slots or []):
        failures.append("S: 同じ日の他枠を出していない")

    print("\n===== Q R 同じ質問を繰り返さない =====")
    reset_store_for_tests()
    lookup_r = mock_slots("19:00")
    t, kw = start_area_duration(lookup_r)
    first_ask = t.reply or ""
    t_r1 = continue_chat("直近で18時〜取れるところ", t, **kw)
    t_r2 = continue_chat("18:00", t_r1, **kw)
    if (t_r1.reply or "").strip() == first_ask.strip():
        failures.append("R: 直近入力後も同じ追加質問")
    if (t_r2.reply or "").strip() == first_ask.strip():
        failures.append("R: 18:00入力後も同じ追加質問")
    if t_r1.reply == DATE_WINDOW_ASK_REPLY and t_r2.reply == DATE_WINDOW_ASK_REPLY:
        failures.append("R: 日付質問が2回連続")

    after_n, after_h = snapshot_knowledge(admin)
    print("snapshot after:", after_n, after_h)
    if after_h != before_h or after_n != before_n:
        failures.append("Knowledge DB が変更されている")

    if failures:
        print("\n予約ウィンドウ: FAIL")
        for item in failures:
            print("-", item)
        return 1
    print("\n予約ウィンドウ: PASS")
    print(f"Knowledge unchanged: n={after_n} hash={after_h}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
