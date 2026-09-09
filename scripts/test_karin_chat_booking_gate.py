"""予約条件が揃うまで空き検索しない。LLMの架空日時を出さない。

  python scripts/test_karin_chat_booking_gate.py
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from datetime import date, datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from dotenv import load_dotenv

load_dotenv(os.path.join(ROOT, ".env"), override=True)

from ai_knowledge import get_admin_client  # noqa: E402
from karin_chat import run_chat  # noqa: E402
from karin_chat_booking import parse_booking_request  # noqa: E402
from karin_chat_memory import reset_store_for_tests  # noqa: E402

SNAPSHOT_SELECT = (
    "id,title,content,category,source_type,status,priority,"
    "source_key,source_url,effective_from,effective_to,updated_at,embedding"
)
EXPECTED_HASH = "ec0bff70d737b542f5419ebbaf9d44e76e5e085b06943dc11aa7232efa9fe373"
JST = timezone(timedelta(hours=9))
PLACEHOLDER = re.compile(r"[◯○〇]月|[◯○〇]曜日|[◯○〇]{2}:[◯○〇]{2}|○月○日")


def snapshot_knowledge(admin) -> tuple[int, str]:
    res = admin.table("ai_knowledge").select(SNAPSHOT_SELECT).order("id").execute()
    rows = list(res.data or [])
    blob = json.dumps(rows, ensure_ascii=False, sort_keys=True, default=str)
    return len(rows), hashlib.sha256(blob.encode("utf-8")).hexdigest()


def continue_chat(message: str, previous, **kwargs):
    cid = None if previous is None else previous.conversation_id
    return run_chat(message, conversation_id=cid, **kwargs)


def empty_match(*_a, **_k):
    return []


def forbidden_complete(_messages):
    return "来週の土日、90分の施術の空き状況を確認しました。以下の日程で空いています。\n・◯月◯日（◯曜日）◯◯:◯◯"


def mock_plan(plan):
    calls: list[dict] = []

    def lookup(**kwargs):
        calls.append(dict(kwargs))
        date_s = kwargs.get("date")
        duration = int(kwargs.get("duration_minutes") or 0)
        times = plan(date_s, duration)
        return {
            "date": date_s,
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


def jp_date(iso: str) -> str:
    _y, month, day = iso.split("-")
    return f"{int(month)}月{int(day)}日"


def next_weekend(today: date) -> tuple[str, str]:
    start = today - timedelta(days=today.weekday()) + timedelta(days=7)
    sat = start + timedelta(days=5)
    sun = start + timedelta(days=6)
    return sat.isoformat(), sun.isoformat()


def main() -> int:
    print("mode: 予約条件ゲート / Knowledge読み取り専用 / INSERTなし")
    reset_store_for_tests()
    failures: list[str] = []
    admin = get_admin_client()
    before_n, before_h = snapshot_knowledge(admin)
    print("snapshot before:", before_n, before_h)
    if before_h != EXPECTED_HASH:
        failures.append(f"開始時 hash 不一致 {before_h}")

    today = datetime.now(JST).date()
    sat, sun = next_weekend(today)
    print("  next weekend", sat, sun)

    kwargs = dict(match_fn=empty_match, complete_fn=forbidden_complete)

    print("\n===== E F G parse =====")
    nxt = parse_booking_request(["来週の土日は？"], today=today)
    if sat not in nxt.date_candidates or sun not in nxt.date_candidates:
        failures.append(f"E: 来週の土日 → {nxt.date_candidates}")
    if nxt.window_kind != "next_week":
        failures.append(f"E: window_kind={nxt.window_kind}")
    sat_only = parse_booking_request(["土曜日"], today=today)
    if not sat_only.date:
        failures.append("F: 土曜日が日付にならない")
    else:
        got = datetime.fromisoformat(sat_only.date).date()
        if got.weekday() != 5 or got < today:
            failures.append(f"F: 土曜日 → {sat_only.date}")
    next_sat = parse_booking_request(["来週の土曜"], today=today)
    if next_sat.date != sat and sat not in (next_sat.date_candidates or []):
        failures.append(f"G: 来週の土曜 → {next_sat.date} {next_sat.date_candidates}")

    print("\n===== A 90分のみ =====")
    reset_store_for_tests()
    lookup_a = mock_plan(lambda *_: ["18:00"])
    t0 = continue_chat("予約したいです", None, lookup_fn=lookup_a, **kwargs)
    t_a = continue_chat("90分", t0, lookup_fn=lookup_a, **kwargs)
    print("  A", t_a.requested_duration, t_a.api_status, (t_a.reply or "")[:160])
    if lookup_a.calls:
        failures.append(f"A: 90分だけで検索している {lookup_a.calls}")
    if t_a.requested_duration != 90:
        failures.append(f"A: duration={t_a.requested_duration}")
    if "日付" not in (t_a.reply or "") and "時間帯" not in (t_a.reply or ""):
        failures.append(f"A: 日付の確認がない {(t_a.reply or '')[:160]}")
    if PLACEHOLDER.search(t_a.reply or ""):
        failures.append("A: プレースホルダーがある")
    if t_a.openai_called:
        failures.append("A: LLMに落ちている")

    print("\n===== B 90分 + 来週の土日 =====")
    reset_store_for_tests()
    lookup_b = mock_plan(lambda *_: ["18:00"])
    t0 = continue_chat("予約したいです", None, lookup_fn=lookup_b, **kwargs)
    t1 = continue_chat("90分", t0, lookup_fn=lookup_b, **kwargs)
    t_b = continue_chat("来週の土日は？", t1, lookup_fn=lookup_b, **kwargs)
    print("  B", t_b.date_range, t_b.available_dates, (t_b.reply or "")[:180])
    if lookup_b.calls:
        failures.append(f"B: エリア前に検索している {lookup_b.calls}")
    if sat not in (t_b.available_dates or []) and t_b.date_range != "next_week":
        failures.append(f"B: 来週土日が保持されていない range={t_b.date_range} dates={t_b.available_dates}")
    if "東京" not in (t_b.reply or "") or "福岡" not in (t_b.reply or ""):
        failures.append(f"B: エリア確認がない {(t_b.reply or '')[:180]}")
    if "院内" in (t_b.reply or "") and "出張か" in (t_b.reply or ""):
        failures.append("B: 院内を選択肢にしている")
    if PLACEHOLDER.search(t_b.reply or ""):
        failures.append("B: プレースホルダーがある")
    if t_b.openai_called:
        failures.append("B: LLMに落ちている")
    if t_b.time_period or t_b.requested_time:
        failures.append(f"B: 時間を勝手に設定 {t_b.time_period} {t_b.requested_time}")

    print("\n===== C D I 東京 + 来週土日 =====")
    reset_store_for_tests()

    def weekend_plan(day_s, duration):
        if duration != 90:
            return []
        if day_s == sat:
            return hm_series("18:00", "24:30")
        if day_s == sun:
            return hm_series("19:00", "20:30")
        return []

    lookup_c = mock_plan(weekend_plan)
    t0 = continue_chat("予約したいです", None, lookup_fn=lookup_c, **kwargs)
    t1 = continue_chat("90分", t0, lookup_fn=lookup_c, **kwargs)
    t2 = continue_chat("来週の土日は？", t1, lookup_fn=lookup_c, **kwargs)
    n_before = len(lookup_c.calls)
    t_c = continue_chat("東京", t2, lookup_fn=lookup_c, **kwargs)
    print("  C dates", [c.get("date") for c in lookup_c.calls[n_before:]], (t_c.reply or "")[:220])
    later = lookup_c.calls[n_before:]
    if not later:
        failures.append("C: 東京後に検索していない")
    else:
        got_dates = {c.get("date") for c in later}
        if sat not in got_dates or sun not in got_dates:
            failures.append(f"C: 9/19・9/20相当を検索していない {got_dates}")
        if any(c.get("area") != "tokyo" for c in later):
            failures.append("C: area が tokyo でない")
        if any(c.get("duration_minutes") != 90 for c in later):
            failures.append("C: 90分以外で検索")
    if "施術時間" in (t_c.reply or "") and "60分" in (t_c.reply or "") and "教えて" in (t_c.reply or ""):
        failures.append("M: 施術時間を再質問している")
    if "東京・福岡" in (t_c.reply or "") or "どちらでのご利用" in (t_c.reply or ""):
        failures.append("M: エリアを再質問している")
    if jp_date(sat) not in (t_c.reply or "") or "18:00" not in (t_c.reply or ""):
        failures.append(f"I: 実データがない {(t_c.reply or '')[:220]}")
    if PLACEHOLDER.search(t_c.reply or ""):
        failures.append("J: 実データ回答にプレースホルダー")
    if t_c.openai_called:
        failures.append("C: LLMに落ちている")
    if t_c.requested_time or t_c.time_period:
        failures.append("D: 時間指定なしなのに time が入った")

    print("\n===== H 空きなし =====")
    reset_store_for_tests()
    lookup_h = mock_plan(lambda *_: [])
    t0 = continue_chat("予約したいです", None, lookup_fn=lookup_h, **kwargs)
    t1 = continue_chat("東京で90分", t0, lookup_fn=lookup_h, **kwargs)
    t_h = continue_chat("来週の土日は？", t1, lookup_fn=lookup_h, **kwargs)
    print("  H", (t_h.reply or "")[:180])
    if "空き枠がありません" not in (t_h.reply or "") and "空きがありません" not in (t_h.reply or ""):
        failures.append(f"H: 空きなしの説明がない {(t_h.reply or '')[:180]}")
    if PLACEHOLDER.search(t_h.reply or ""):
        failures.append("H: 空きなしなのにプレースホルダー")
    if "空き状況を確認しました" in (t_h.reply or "") and "◯" in (t_h.reply or ""):
        failures.append("H: 架空候補を出している")

    print("\n===== L 日付だけ → エリア =====")
    reset_store_for_tests()
    lookup_l = mock_plan(lambda *_: ["18:00"])
    t0 = continue_chat("予約したいです", None, lookup_fn=lookup_l, **kwargs)
    t1 = continue_chat("90分", t0, lookup_fn=lookup_l, **kwargs)
    t_l = continue_chat("来週の土日は？", t1, lookup_fn=lookup_l, **kwargs)
    if lookup_l.calls:
        failures.append("L: area未入力で検索した")
    if "東京" not in (t_l.reply or ""):
        failures.append("L: エリア確認がない")

    print("\n===== K 身体相談→予約移行 =====")
    reset_store_for_tests()
    lookup_k = mock_plan(lambda d, dur: hm_series("18:00", "18:30") if dur == 90 else [])
    t0 = continue_chat("腰が痛いです", None, lookup_fn=lookup_k, **kwargs)
    t1 = continue_chat("鍼を受けたいです", t0, lookup_fn=lookup_k, **kwargs)
    t2 = continue_chat("東京", t1, lookup_fn=lookup_k, **kwargs)
    t3 = continue_chat("90分", t2, lookup_fn=lookup_k, **kwargs)
    n_before = len(lookup_k.calls)
    t_k = continue_chat("予約したいです", t3, lookup_fn=lookup_k, **kwargs)
    print("  K", t_k.requested_area, t_k.requested_duration, t_k.preferred_treatment, (t_k.reply or "")[:160])
    if t_k.requested_area != "tokyo":
        failures.append(f"K: area={t_k.requested_area}")
    if t_k.requested_duration != 90:
        failures.append(f"K: duration={t_k.requested_duration}")
    if t_k.preferred_treatment != "鍼":
        failures.append(f"K: treatment={t_k.preferred_treatment}")
    if "東京・福岡" in (t_k.reply or "") or "施術時間は60分" in (t_k.reply or ""):
        failures.append("K: 既知のarea/durationを再質問している")
    if lookup_k.calls[n_before:]:
        failures.append("K: 日付前に検索している")

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


if __name__ == "__main__":
    raise SystemExit(main())
