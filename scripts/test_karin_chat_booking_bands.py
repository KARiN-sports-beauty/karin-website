"""空き区間の複数保持と 26:00 終了。予約INSERTはしない。

  python scripts/test_karin_chat_booking_bands.py
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
from karin_chat import chat_public_payload, run_chat  # noqa: E402
from karin_chat_booking import (  # noqa: E402
    _availability_intervals,
    _band_rows,
    _consecutive_bands,
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


def snapshot_knowledge(admin) -> tuple[int, str]:
    res = admin.table("ai_knowledge").select(SNAPSHOT_SELECT).order("id").execute()
    rows = list(res.data or [])
    blob = json.dumps(rows, ensure_ascii=False, sort_keys=True, default=str)
    return len(rows), hashlib.sha256(blob.encode("utf-8")).hexdigest()


def hm_series(start: str, last: str) -> list[str]:
    times: list[str] = []
    h, m = [int(x) for x in start.split(":")]
    eh, em = [int(x) for x in last.split(":")]
    while h * 60 + m <= eh * 60 + em:
        times.append(f"{h:02d}:{m:02d}")
        m += 15
        if m >= 60:
            h += 1
            m = 0
    return times


def continue_chat(message: str, previous, **kwargs):
    cid = None if previous is None else previous.conversation_id
    return run_chat(message, conversation_id=cid, **kwargs)


def empty_match(*_a, **_k):
    return []


def complete(_messages):
    return "承知しました。"


def mock_plan(plan):
    calls: list[dict] = []

    def lookup(**kwargs):
        calls.append(dict(kwargs))
        date = kwargs.get("date")
        duration = int(kwargs.get("duration_minutes") or 0)
        times = plan(date, duration)
        return {
            "date": date,
            "area": kwargs.get("area"),
            "place_type": kwargs.get("place_type"),
            "duration_minutes": duration,
            "staff": [],
            "free_row": {
                "staff_name": "フリー",
                "slots": [{"time": t, "available": True} for t in times],
            },
        }

    lookup.calls = calls  # type: ignore[attr-defined]
    return lookup


def jp_date(iso: str) -> str:
    _y, month, day = iso.split("-")
    return f"{int(month)}月{int(day)}日"


def weekday_iso(day: int) -> str:
    today = datetime.now(JST).date()
    for i in range(0, 45):
        d = today + timedelta(days=i)
        if d.day == day and d.weekday() < 5:
            return d.isoformat()
    raise RuntimeError(f"{day}日の平日が予約期間にない")


def start_weekday(lookup):
    kwargs = dict(match_fn=empty_match, complete_fn=complete, lookup_fn=lookup)
    t0 = continue_chat("予約したいです", None, **kwargs)
    t1 = continue_chat("東京で90分", t0, **kwargs)
    t2 = continue_chat("平日", t1, **kwargs)
    return t2, kwargs


def main() -> int:
    print("mode: 空き区間 / Knowledge読み取り専用 / INSERTなし")
    reset_store_for_tests()
    failures: list[str] = []
    admin = get_admin_client()
    before_n, before_h = snapshot_knowledge(admin)
    print("snapshot before:", before_n, before_h)
    if before_h != EXPECTED_HASH:
        failures.append(f"開始時 hash 不一致 {before_h}")

    print("\n===== A 複数区間 =====")
    starts_a = hm_series("19:00", "19:30") + hm_series("24:00", "24:30")
    iv_a = _availability_intervals(starts_a, 90)
    print("  A", iv_a)
    if [ (x["start"], x["end"]) for x in iv_a ] != [("19:00", "21:00"), ("24:00", "26:00")]:
        failures.append(f"A: {iv_a}")
    if iv_a[0]["last_start"] != "19:30" or iv_a[1]["last_start"] != "24:30":
        failures.append(f"A last_start: {iv_a}")
    rows_a = _band_rows({"2026-09-16": starts_a}, 90)
    if "9月16日 19:00〜21:00" not in rows_a or "9月16日 24:00〜26:00" not in rows_a:
        failures.append(f"A rows: {rows_a}")
    if rows_a.count("9月16日") < 2:
        failures.append("A: 1日1行に潰している")

    print("\n===== B 18:00〜26:00 =====")
    starts_b = hm_series("18:00", "24:30")
    iv_b = _availability_intervals(starts_b, 90)
    print("  B", iv_b)
    if len(iv_b) != 1 or iv_b[0]["start"] != "18:00" or iv_b[0]["end"] != "26:00":
        failures.append(f"B: {iv_b}")
    if iv_b[0]["last_start"] != "24:30":
        failures.append(f"B last_start 混同 {iv_b}")
    if "25:15" in _format_from(iv_b):
        failures.append("B: 26:00 を 25:15 にしている")

    print("\n===== C 飛びは連結しない =====")
    starts_c = hm_series("18:00", "18:30") + hm_series("21:30", "24:30")
    iv_c = _availability_intervals(starts_c, 90)
    print("  C", iv_c)
    if [ (x["start"], x["end"]) for x in iv_c ] != [("18:00", "20:00"), ("21:30", "26:00")]:
        failures.append(f"C: {iv_c}")
    if any(x["start"] == "18:00" and x["end"] == "26:00" for x in iv_c):
        failures.append("C: 18:00〜26:00 に連結している")

    print("\n===== D 20:00 と 21:00 で分離 =====")
    starts_d = hm_series("18:00", "20:00") + hm_series("21:00", "24:30")
    iv_d = _availability_intervals(starts_d, 90)
    print("  D", iv_d)
    if len(iv_d) != 2:
        failures.append(f"D bands={iv_d}")
    elif iv_d[0]["start"] != "18:00" or iv_d[1]["start"] != "21:00":
        failures.append(f"D starts {iv_d}")
    if iv_d[-1]["end"] != "26:00":
        failures.append(f"D 終了 {iv_d}")
    if _consecutive_bands(starts_d) != [("18:00", "20:00"), ("21:00", "24:30")]:
        failures.append(f"D consecutive {_consecutive_bands(starts_d)}")

    print("\n===== E 空き終了と最終開始を混同しない =====")
    iv_e = _availability_intervals(hm_series("18:00", "24:30"), 90)
    if iv_e[0]["end"] == iv_e[0]["last_start"]:
        failures.append("E: 空き終了と最終開始が同じ")
    if iv_e[0]["last_start"] != "24:30" or iv_e[0]["end"] != "26:00":
        failures.append(f"E: {iv_e}")
    if _availability_intervals(["23:45"], 90)[0]["end"] == "25:15":
        if _availability_intervals(hm_series("18:00", "24:30"), 90)[0]["end"] == "25:15":
            failures.append("E: 90分だから 26:00 を 25:15 にしている")

    today = datetime.now(JST).date()
    weekday_dates = list(parse_booking_request(["平日"], today=today).date_candidates or [])
    if len(weekday_dates) < 3:
        failures.append(f"平日候補が足りない {weekday_dates}")
        weekday_dates = (weekday_dates + ["2026-09-16", "2026-09-17", "2026-09-18"])[:3]
    d_a, d_b, d_c = weekday_dates[0], weekday_dates[1], weekday_dates[2]
    d16 = weekday_iso(16)
    print("  weekday targets", d_a, d_b, d_c, "16日", d16)

    patterns = {
        d_a: hm_series("19:00", "19:30") + hm_series("24:00", "24:30"),
        d_b: hm_series("18:00", "24:30"),
        d_c: hm_series("18:00", "22:30"),
        d16: hm_series("19:00", "19:30") + hm_series("24:00", "24:30"),
    }

    def sept_plan(date, duration):
        if duration != 90:
            return []
        return list(patterns.get(str(date), []))

    print("\n===== 平日 → 夜 =====")
    reset_store_for_tests()
    lookup_n = mock_plan(sept_plan)
    kwargs_n = dict(match_fn=empty_match, complete_fn=complete, lookup_fn=lookup_n)
    t0 = continue_chat("予約したいです", None, **kwargs_n)
    t1 = continue_chat("東京で90分", t0, **kwargs_n)
    t_night = continue_chat("平日の夜", t1, **kwargs_n)
    reply_n = t_night.reply or ""
    print("  night", t_night.time_period, reply_n[:280])
    if t_night.time_period != "night":
        failures.append(f"night period={t_night.time_period}")
    if t_night.requested_time == "19:00":
        failures.append("夜を 19:00 に固定変換している")
    if jp_date(d_a) + " 19:00〜21:00" not in reply_n:
        failures.append(f"複数区間の前半がない {reply_n[:280]}")
    if jp_date(d_a) + " 24:00〜26:00" not in reply_n:
        failures.append(f"複数区間の後半がない {reply_n[:280]}")
    if jp_date(d_b) + " 18:00〜26:00" not in reply_n:
        failures.append(f"連続26:00がない {reply_n[:280]}")
    if "25:15" in reply_n:
        failures.append("連続空きを 25:15 にしている")
    if jp_date(d_c) + " 18:00〜24:00" not in reply_n:
        failures.append(f"18:00〜24:00 がない {reply_n[:280]}")

    print("\n===== 平日検索 =====")
    reset_store_for_tests()
    lookup_w = mock_plan(sept_plan)
    t, kw = start_weekday(lookup_w)
    print("  weekday", t.available_dates, (t.reply or "")[:160])
    if not t.available_dates:
        failures.append("平日の候補日がない")

    print("\n===== 18時以降 =====")
    reset_store_for_tests()
    lookup_f = mock_plan(sept_plan)
    kwargs_f = dict(match_fn=empty_match, complete_fn=complete, lookup_fn=lookup_f)
    t0 = continue_chat("予約したいです", None, **kwargs_f)
    t1 = continue_chat("東京で90分", t0, **kwargs_f)
    t_from = continue_chat("平日の18時以降", t1, **kwargs_f)
    print("  from", t_from.time_from, (t_from.reply or "")[:180])
    if t_from.time_from != "18:00":
        failures.append(f"18時以降 time_from={t_from.time_from}")
    if t_from.requested_time == "18:00" and t_from.time_from is None:
        failures.append("18時以降を固定18:00にしている")
    if jp_date(d_b) not in (t_from.reply or "") and jp_date(d_c) not in (t_from.reply or ""):
        failures.append("18時以降の候補日がない")

    print("\n===== 9月16日 / 16日 / 24時以降 =====")
    reset_store_for_tests()
    lookup_d = mock_plan(sept_plan)
    t, kw = start_weekday(lookup_d)
    t_night = continue_chat("夜", t, **kw)
    t_16 = continue_chat("9月16日", t_night, **kw)
    print("  16日", t_16.requested_date, (t_16.reply or "")[:200])
    if t_16.requested_date != d16 and t_16.selected_date != d16:
        failures.append(f"9月16日 date={t_16.requested_date}")
    if "24:00〜26:00" not in (t_16.reply or "") or "19:00〜21:00" not in (t_16.reply or ""):
        failures.append(f"16日の2区間がない {(t_16.reply or '')[:200]}")
    if any(
        jp_date(d) in (t_16.reply or "")
        for d in (d_a, d_b, d_c)
        if d != d16
    ):
        failures.append("16日指定後に他の候補日が残っている")

    reset_store_for_tests()
    lookup_d2 = mock_plan(sept_plan)
    t, kw = start_weekday(lookup_d2)
    t_night = continue_chat("夜", t, **kw)
    t_day = continue_chat("16日", t_night, **kw)
    if t_day.requested_date != d16 and t_day.selected_date != d16:
        failures.append(f"16日 date={t_day.requested_date}")

    t_late = continue_chat("24時以降", t_day, **kw)
    print("  24時以降", t_late.time_from, (t_late.reply or "")[:160])
    if _parse_time_from("24時以降") != "24:00":
        failures.append(f"parse 24時以降 {_parse_time_from('24時以降')}")
    if t_late.time_from != "24:00":
        failures.append(f"24時以降 time_from={t_late.time_from}")
    if "24:00〜26:00" not in (t_late.reply or ""):
        failures.append(f"24時以降に後半区間がない {(t_late.reply or '')[:200]}")
    if "19:00〜21:00" in (t_late.reply or ""):
        failures.append("24時以降なのに前半区間が残っている")

    print("\n===== 候補選択後の絞り込み =====")
    t_pick = continue_chat("24:00", t_late, **kw)
    print("  pick", t_pick.selected_time, (t_pick.reply or "")[:120])
    if t_pick.selected_time != "24:00" and t_pick.requested_time != "24:00":
        failures.append(f"24:00 選択 {t_pick.selected_time}")
    payload = chat_public_payload(t_pick)
    if payload.get("available_slots") and "進めますか" in (t_pick.reply or ""):
        failures.append("選択後に構造化枠が残っている")
    if t_pick.booking_completed:
        failures.append("空き確認だけで予約完了している")

    after_n, after_h = snapshot_knowledge(admin)
    print("snapshot after:", after_n, after_h)
    if after_h != before_h:
        failures.append("Knowledge hash が変わった")

    if failures:
        print("\nFAIL")
        for item in failures:
            print(" -", item)
        return 1
    print("\nPASS")
    return 0


def _format_from(intervals: list[dict[str, str]]) -> str:
    return ",".join(f"{x['start']}〜{x['end']}" for x in intervals)


if __name__ == "__main__":
    raise SystemExit(main())
