"""検索範囲の拡張。「他の平日は？」で前回候補を再表示しない。

  python scripts/test_karin_chat_booking_expand.py
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
from karin_chat_booking import _search_expand_kind  # noqa: E402
from karin_chat_intent import detect_intents, _is_reservation_want  # noqa: E402
from karin_chat_memory import get_or_create_conversation, reset_store_for_tests  # noqa: E402

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
    return "LLM再利用してはいけない"


def mock_by_date(plan, default=None):
    calls: list[dict] = []
    default = [] if default is None else list(default)

    def lookup(**kwargs):
        calls.append(dict(kwargs))
        date = kwargs.get("date")
        times = plan.get(date, default)
        return {
            "date": date,
            "area": kwargs.get("area"),
            "place_type": kwargs.get("place_type"),
            "duration_minutes": kwargs.get("duration_minutes"),
            "staff": [],
            "free_row": {
                "staff_name": "フリー",
                "slots": [{"time": t, "available": True} for t in times],
            },
        }

    lookup.calls = calls  # type: ignore[attr-defined]
    return lookup


def later(lookup, n_before: int) -> list[dict]:
    return list(lookup.calls[n_before:])


def dates_of(calls: list[dict]) -> list[str]:
    return [c.get("date") for c in calls]


def draft_of(turn):
    return get_or_create_conversation(turn.conversation_id).booking_draft


def dump(label, turn, lookup=None, n_before=0):
    d = draft_of(turn)
    calls = later(lookup, n_before) if lookup is not None else []
    print(
        f"  {label} phase={d.phase} range={d.date_range} filter={d.date_filter} "
        f"date={d.date} time={d.time} from={d.time_from} period={d.time_period}"
    )
    print(f"    cands={d.date_candidates} offered={d.offered_dates}")
    print(f"    lookup dates={dates_of(calls)} slots={turn.available_slots} avail_dates={turn.available_dates}")
    print(f"    reply={(turn.reply or '')[:120].replace(chr(10), ' / ')}")
    return d, calls


def start(lookup):
    kwargs = dict(match_fn=empty_match, complete_fn=complete, lookup_fn=lookup)
    t0 = continue_chat("予約がしたいです", None, **kwargs)
    t1 = continue_chat("東京で90分", t0, **kwargs)
    return t1, kwargs


def main() -> int:
    print("mode: 予約検索範囲拡張 / Knowledge読み取り専用")
    reset_store_for_tests()
    failures: list[str] = []
    admin = get_admin_client()
    before_n, before_h = snapshot_knowledge(admin)
    print("snapshot before:", before_n, before_h)
    if before_h != EXPECTED_HASH:
        failures.append(f"開始時 hash 不一致 {before_h}")

    d910 = next_iso(9, 10)
    d11 = day_iso(11)
    print("  9/10", d910, "11日", d11)

    print("\n===== intent 他の平日は空いてないん？ =====")
    q = "他の平日は空いてないん？"
    print("  want", _is_reservation_want(q), "kind", _search_expand_kind(q))
    print("  no prior", detect_intents(q).primary_intent)
    print("  with prior", detect_intents(q, ["予約がしたいです", "平日"]).primary_intent)
    if _search_expand_kind(q) != "others":
        failures.append("expand kind が others でない")
    if detect_intents(q).primary_intent != "unclear":
        failures.append("単独では unclear であるべき")
    if detect_intents(q, ["予約がしたいです"]).primary_intent != "reservation_intent":
        failures.append("予約継続中なのに reservation_intent にならない")
    if _search_expand_kind("もっと先は？") != "further":
        failures.append("もっと先 が further でない")
    if _search_expand_kind("土日なら？") is not None:
        failures.append("土日なら を expand に分類している")
    if _search_expand_kind("夕方") or _search_expand_kind("18時以降") or _search_expand_kind("11日"):
        failures.append("具体化を expand に分類している")

    print("\n===== A 平日 → 他の平日は？ =====")
    reset_store_for_tests()
    lookup_a = mock_by_date({}, default=["10:00", "18:00"])
    t, kw = start(lookup_a)
    n0 = len(lookup_a.calls)
    t_w = continue_chat("平日", t, **kw)
    d0, c0 = dump("A 平日", t_w, lookup_a, n0)
    first_dates = list(t_w.available_dates or [])
    first_reply = t_w.reply
    n1 = len(lookup_a.calls)
    t_a = continue_chat("他の平日は空いてないん？", t_w, **kw)
    d1, c1 = dump("A 他の平日", t_a, lookup_a, n1)
    if t_a.reply == first_reply:
        failures.append("A/J: 他の平日で同じ回答を繰り返している")
    queried = dates_of(c1)
    if queried and any(x in first_dates for x in queried):
        failures.append(f"A: 前回提示日を再検索している {queried} vs {first_dates}")
    if d1.last_expand_kind != "others":
        failures.append(f"A: last_expand_kind={d1.last_expand_kind}")
    if d1.date_filter != "weekdays":
        failures.append(f"A: date_filter={d1.date_filter}")
    if d1.time or d1.time_from:
        failures.append("A: 平日だけなのに時刻条件がある")
    if d1.phase != "collecting":
        failures.append(f"A: phase={d1.phase}")
    if c1 and (c1[0].get("area") != "tokyo" or c1[0].get("duration_minutes") != 90):
        failures.append(f"A: lookup args={c1[0]}")

    print("\n===== A2 18:00保持のまま他の平日 =====")
    reset_store_for_tests()
    d9, d11 = day_iso(9), day_iso(11)
    plan = {d9: ["18:00"], d11: ["18:00"]}
    lookup_a2 = mock_by_date(plan, default=[])
    t, kw = start(lookup_a2)
    t_clock = continue_chat("18:00", t, **kw)
    t_w = continue_chat("平日", t_clock, **kw)
    dump("A2 平日", t_w, lookup_a2, 0)
    first_reply = t_w.reply
    first_dates = list(t_w.available_dates or [])
    n1 = len(lookup_a2.calls)
    t_a2 = continue_chat("他の平日は空いてないん？", t_w, **kw)
    d_a2, c1 = dump("A2 他の平日", t_a2, lookup_a2, n1)
    if d_a2.time != "18:00":
        failures.append(f"A2: 18:00 が保持されていない time={d_a2.time} from={d_a2.time_from}")
    if t_a2.reply == first_reply:
        failures.append("A2: 同じ18:00候補を繰り返している")
    if dates_of(c1) and any(x in first_dates for x in dates_of(c1)):
        failures.append(f"A2: 提示済み日を再検索 {dates_of(c1)}")

    print("\n===== B 平日 → 別の日は？ =====")
    reset_store_for_tests()
    lookup_b = mock_by_date({}, default=["10:00"])
    t, kw = start(lookup_b)
    t_w = continue_chat("平日", t, **kw)
    first_dates = list(t_w.available_dates or [])
    n1 = len(lookup_b.calls)
    t_b = continue_chat("別の日は？", t_w, **kw)
    _d, c1 = dump("B 別の日", t_b, lookup_b, n1)
    if t_b.reply == t_w.reply:
        failures.append("B: 別の日で同じ回答")
    if dates_of(c1) and any(x in first_dates for x in dates_of(c1)):
        failures.append(f"B: 前回日を再検索 {dates_of(c1)}")

    print("\n===== C 平日 → もっと先は？ =====")
    reset_store_for_tests()
    lookup_c = mock_by_date({}, default=["10:00"])
    t, kw = start(lookup_c)
    t_w = continue_chat("平日", t, **kw)
    first_dates = list(t_w.available_dates or [])
    last_shown = max(first_dates) if first_dates else None
    n1 = len(lookup_c.calls)
    t_c = continue_chat("もっと先は？", t_w, **kw)
    d_c, c1 = dump("C もっと先", t_c, lookup_c, n1)
    if t_c.reply == t_w.reply:
        failures.append("C: もっと先で同じ回答")
    if d_c.last_expand_kind != "further":
        failures.append(f"C: kind={d_c.last_expand_kind}")
    if last_shown and any((x or "") <= last_shown for x in dates_of(c1)):
        failures.append(f"C: もっと先なのに {last_shown} 以前を検索 {dates_of(c1)}")

    print("\n===== D 平日 → 土日なら？ =====")
    reset_store_for_tests()
    lookup_d = mock_by_date({}, default=["10:00"])
    t, kw = start(lookup_d)
    t_w = continue_chat("平日", t, **kw)
    weekday_dates = list(t_w.available_dates or [])
    n1 = len(lookup_d.calls)
    t_d = continue_chat("土日なら？", t_w, **kw)
    d_d, c1 = dump("D 土日", t_d, lookup_d, n1)
    if t_d.reply == t_w.reply:
        failures.append("D: 土日で平日と同じ回答")
    if d_d.date_filter != "weekend":
        failures.append(f"D: date_filter={d_d.date_filter}")
    if dates_of(c1) and set(dates_of(c1)) <= set(weekday_dates):
        failures.append(f"D: 土日なのに平日だけ検索 {dates_of(c1)}")

    print("\n===== E 平日 → 夕方 → 18時以降 =====")
    reset_store_for_tests()
    lookup_e = mock_by_date({}, default=["17:00", "18:00", "19:00"])
    t, kw = start(lookup_e)
    t_w = continue_chat("平日", t, **kw)
    t_e = continue_chat("夕方", t_w, **kw)
    dump("E 夕方", t_e, lookup_e, 0)
    n1 = len(lookup_e.calls)
    t_from = continue_chat("18時以降", t_e, **kw)
    d_f, c1 = dump("E 18時以降", t_from, lookup_e, n1)
    if t_e.time_period != "evening":
        failures.append(f"E: evening={t_e.time_period}")
    if d_f.time_from != "18:00":
        failures.append(f"E: time_from={d_f.time_from}")
    if d_f.date_filter != "weekdays":
        failures.append("E: 平日条件が消えた")
    if d_f.date:
        failures.append(f"E: 日付が確定している {d_f.date}")

    print("\n===== F 平日 → 18時以降 → 11日 =====")
    reset_store_for_tests()
    lookup_f = mock_by_date({}, default=["18:00", "19:00"])
    t, kw = start(lookup_f)
    t_w = continue_chat("平日", t, **kw)
    t_from = continue_chat("18時以降", t_w, **kw)
    n1 = len(lookup_f.calls)
    t_11 = continue_chat("11日", t_from, **kw)
    d11_draft, c1 = dump("F 11日", t_11, lookup_f, n1)
    if d11_draft.date != d11 and d11_draft.selected_date != d11:
        failures.append(f"F: 11日 → {d11_draft.date}")
    if d11_draft.time_from != "18:00":
        failures.append(f"F: time_from 消失 {d11_draft.time_from}")
    if dates_of(c1) and any(x != d11 for x in dates_of(c1)):
        failures.append(f"F: 11日以外を検索 {dates_of(c1)}")

    print("\n===== G 18時以降 → 11日 =====")
    reset_store_for_tests()
    lookup_g = mock_by_date({}, default=["18:00", "19:00"])
    t, kw = start(lookup_g)
    t_from = continue_chat("18時以降", t, **kw)
    n1 = len(lookup_g.calls)
    t_g = continue_chat("11日", t_from, **kw)
    dg, c1 = dump("G 11日", t_g, lookup_g, n1)
    if dg.date != d11 and dg.selected_date != d11:
        failures.append(f"G: date={dg.date}")
    if dg.time_from != "18:00":
        failures.append(f"G: time_from={dg.time_from}")
    if dates_of(c1) != [d11] and dates_of(c1) and set(dates_of(c1)) != {d11}:
        failures.append(f"G: lookup {dates_of(c1)}")

    print("\n===== H 直近で18時以降空いているところ =====")
    reset_store_for_tests()
    lookup_h = mock_by_date({}, default=["19:00"])
    t, kw = start(lookup_h)
    n0 = len(lookup_h.calls)
    t_h = continue_chat("直近で18時以降空いているところ", t, **kw)
    dh, c0 = dump("H 直近", t_h, lookup_h, n0)
    if dh.time_from != "18:00":
        failures.append(f"H: time_from={dh.time_from}")
    if not c0:
        failures.append("H: 検索していない")
    if "ご希望の日付や時間帯があれば教えてください。" == (t_h.reply or "").split("\n")[0]:
        failures.append("H: 日付質問へ戻っている")

    print("\n===== I 9/10 と 9月10日 =====")
    reset_store_for_tests()
    lookup_i = mock_by_date({d910: ["19:00"]}, default=["19:00"])
    t, kw = start(lookup_i)
    t_i1 = continue_chat("9/10", t, **kw)
    reset_store_for_tests()
    t, kw = start(lookup_i)
    t_i2 = continue_chat("9月10日", t, **kw)
    print("  slash", t_i1.requested_date, "jp", t_i2.requested_date)
    if t_i1.requested_date != d910 or t_i2.requested_date != d910:
        failures.append(f"I: {t_i1.requested_date} vs {t_i2.requested_date} vs {d910}")

    print("\n===== K 本当に他にない場合 =====")
    reset_store_for_tests()
    today = today_jst()
    this_week = []
    cur = today - timedelta(days=today.weekday())
    for i in range(5):
        d = cur + timedelta(days=i)
        if d >= today:
            this_week.append(d.isoformat())
    plan = {iso: ["18:00"] for iso in this_week}
    lookup_k = mock_by_date(plan, default=[])
    t, kw = start(lookup_k)
    t_w = continue_chat("平日", t, **kw)
    n1 = len(lookup_k.calls)
    t_k = continue_chat("他の平日は？", t_w, **kw)
    dump("K 他にない", t_k, lookup_k, n1)
    if t_k.reply == t_w.reply:
        failures.append("K: 他にないのに同じ候補を再表示")
    if "以外の平日は空きがありませんでした" not in (t_k.reply or "") and "他の平日に確認できる空きがありませんでした" not in (
        t_k.reply or ""
    ):
        if t_k.available_dates and set(t_k.available_dates) <= set(t_w.available_dates or []):
            failures.append("K: 他にないことを伝えていない")

    after_n, after_h = snapshot_knowledge(admin)
    print("snapshot after:", after_n, after_h)
    if after_h != before_h or after_n != before_n:
        failures.append("Knowledge DB が変更されている")

    if failures:
        print("\n予約検索範囲拡張: FAIL")
        for item in failures:
            print("-", item)
        return 1
    print("\n予約検索範囲拡張: PASS")
    print(f"Knowledge unchanged: n={after_n} hash={after_h}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
