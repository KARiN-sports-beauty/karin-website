"""予約意図の会話フロー。枠計算はモックし、/api/book は呼ばない。

  python scripts/test_karin_chat_reservation_flow.py
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from dotenv import load_dotenv

load_dotenv(os.path.join(ROOT, ".env"), override=True)

from ai_knowledge import get_admin_client  # noqa: E402
from karin_chat import INITIAL_RESERVATION_REPLY, run_chat  # noqa: E402
from karin_chat_booking import BOOKING_LOOKUP_ERROR_REPLY  # noqa: E402
from karin_chat_intent import detect_intents  # noqa: E402
from karin_chat_memory import reset_store_for_tests  # noqa: E402

SNAPSHOT_SELECT = (
    "id,title,content,category,source_type,status,priority,"
    "source_key,source_url,effective_from,effective_to,updated_at,embedding"
)
EXPECTED_HASH = "ec0bff70d737b542f5419ebbaf9d44e76e5e085b06943dc11aa7232efa9fe373"
JST = timezone(timedelta(hours=9))
ASK_SPECIFIC = (
    "ご希望の日時はありますか",
    "具体的な日や時間帯を教えて",
    "何曜日がいいですか",
    "何時がいいですか",
    "いつから痛い",
    "どのようなときに痛",
    "痛みはどのくらい",
)


def snapshot_knowledge(admin) -> tuple[int, str]:
    res = admin.table("ai_knowledge").select(SNAPSHOT_SELECT).order("id").execute()
    rows = list(res.data or [])
    blob = json.dumps(rows, ensure_ascii=False, sort_keys=True, default=str)
    return len(rows), hashlib.sha256(blob.encode("utf-8")).hexdigest()


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


def boom_lookup(**_kwargs):
    raise RuntimeError("internal boom SELECT * FROM secret_table url=https://internal")


def continue_chat(message: str, previous, **kwargs):
    cid = None if previous is None else previous.conversation_id
    return run_chat(message, conversation_id=cid, **kwargs)


def empty_match(*_a, **_k):
    return []


def main() -> int:
    print("mode: 予約会話フロー / Knowledge読み取り専用 / 予約確定なし")
    reset_store_for_tests()
    failures: list[str] = []
    admin = get_admin_client()
    before_n, before_h = snapshot_knowledge(admin)
    print("snapshot before:", before_n, before_h)
    if before_h != EXPECTED_HASH:
        failures.append(f"開始時 hash 不一致 {before_h}")

    print("\n===== A 予約がしたいです → CTA =====")
    t_a = run_chat(
        "予約がしたいです",
        match_fn=empty_match,
        complete_fn=lambda _m: "should-not-run",
    )
    print("  intent", t_a.primary_intent, "cta", t_a.show_booking_cta, "api", t_a.reservation_api_called)
    if t_a.primary_intent != "reservation_intent":
        failures.append(f"A: intent={t_a.primary_intent}")
    if not t_a.show_booking_cta:
        failures.append("A: 初回予約意図なのに CTA がない")
    if t_a.reply != INITIAL_RESERVATION_REPLY:
        failures.append("A: 初回予約案内になっていない")
    for needle in (
        "ヘッダーの『ご予約』",
        "Web予約へ進む",
        "このまま私との会話でご予約をお取りしたい場合",
        "エリア（東京or福岡）と施術時間",
    ):
        if needle not in (t_a.reply or ""):
            failures.append(f"B: 初回案内に「{needle}」がない")
    if (t_a.reply or "").count("ご希望のエリアと施術時間を教えてください") > 1:
        failures.append("C: エリアと施術時間の質問が重複している")
    if "例：東京・90分" in (t_a.reply or ""):
        failures.append("C: 別の重複した質問文がある")
    if t_a.reservation_api_called:
        failures.append("A: 情報不足なのに予約API")
    if t_a.openai_called:
        failures.append("A: 初回案内で LLM を呼んでいる")

    print("\n===== A2 条件入力後は CTA なし =====")
    t_tokyo = continue_chat("東京", t_a, match_fn=empty_match, complete_fn=lambda _m: "should-not-run")
    print("  tokyo cta", t_tokyo.show_booking_cta, "area", t_tokyo.requested_area)
    if t_tokyo.show_booking_cta:
        failures.append("D: 東京入力後も CTA がある")
    if t_tokyo.requested_area != "tokyo":
        failures.append("D: 東京が保持されていない")

    print("\n===== A3 東京で90分予約したい → 再質問せずC9へ =====")
    reset_store_for_tests()
    t_ready = run_chat(
        "東京で90分予約したい",
        match_fn=empty_match,
        complete_fn=lambda _m: "should-not-run",
        lookup_fn=mock_slots("18:00"),
    )
    print("  ready", t_ready.requested_area, t_ready.requested_duration, "cta", t_ready.show_booking_cta)
    if t_ready.reply == INITIAL_RESERVATION_REPLY:
        failures.append("E: 条件済みなのに初回案内へ戻っている")
    if t_ready.requested_area != "tokyo" or t_ready.requested_duration != 90:
        failures.append("E: 東京90分を使っていない")
    if t_ready.show_booking_cta:
        failures.append("E: 条件済みなのに Web予約CTA がある")
    if "例：東京・90分" in (t_ready.reply or ""):
        failures.append("E: 同じ質問を繰り返している")

    print("\n===== B 予約後の身体言及は問診へ行かない =====")
    captured_b: list[list] = []

    def complete_b(messages):
        captured_b.append(messages)
        return "腰のお悩みで、鍼をご希望ですね。ご予約でしたら、Web予約からご希望の日時・施術時間を選んでお進みいただけます。"

    t_b1 = continue_chat("予約がしたいです", None, match_fn=empty_match, complete_fn=complete_b)
    t_b2 = continue_chat(
        "腰が痛くて鍼を受けたいです",
        t_b1,
        match_fn=empty_match,
        complete_fn=complete_b,
        lookup_fn=mock_slots("18:00"),
    )
    print("  B2 intent", t_b2.primary_intent, "cta", t_b2.show_booking_cta)
    if t_b2.primary_intent != "reservation_intent":
        failures.append(f"B: intent={t_b2.primary_intent}")
    if t_b2.show_booking_cta:
        failures.append("B: 予約相談の途中で CTA が出ている")
    if any(p in (t_b2.reply or "") for p in ASK_SPECIFIC):
        failures.append("B: 問診へ移行している")
    steer = "\n".join(m.get("content") or "" for batch in captured_b for m in batch)
    if captured_b and "問診を始めない" not in steer:
        failures.append("B: 予約相談の方針プロンプトがない")

    print("\n===== C 今週の平日 → エリアだけ確認 =====")
    t_c = run_chat(
        "今週の平日でどこか空いてますか？",
        match_fn=empty_match,
        complete_fn=lambda _m: "確認できます。東京・福岡のどちらをご希望ですか？",
        lookup_fn=mock_slots("18:00"),
    )
    print("  C api", t_c.reservation_api_called, "missing", t_c.api_status, "cta", t_c.show_booking_cta)
    if t_c.primary_intent != "reservation_intent":
        failures.append(f"C: intent={t_c.primary_intent}")
    if t_c.reservation_api_called:
        failures.append("C: エリア不足なのに予約API")
    if t_c.show_booking_cta:
        failures.append("C: 空き確認の質問で CTA がある")

    print("\n===== D 東京 → 施術時間 → 今週平日の候補 =====")
    lookup_d = mock_slots("18:00", "19:30")
    captured_d: list[str] = []

    def complete_d(messages):
        captured_d.append("\n".join(m.get("content") or "" for m in messages))
        return "東京と福岡のどちらをご希望ですか？"

    t_d1 = continue_chat(
        "今週の平日でどこか空いてますか？",
        None,
        match_fn=empty_match,
        complete_fn=complete_d,
        lookup_fn=lookup_d,
    )
    t_d2 = continue_chat(
        "東京でお願いします",
        t_d1,
        match_fn=empty_match,
        complete_fn=complete_d,
        lookup_fn=lookup_d,
    )
    t_d3 = continue_chat(
        "90分で",
        t_d2,
        match_fn=empty_match,
        complete_fn=complete_d,
        lookup_fn=lookup_d,
    )
    print("  D2 api", t_d2.reservation_api_called, "D3 calls", len(lookup_d.calls), "dates", t_d3.available_dates)
    if t_d2.reservation_api_called:
        failures.append("D: 施術時間前に予約APIを呼んでいる")
    if "60分" not in (t_d2.reply or "") or "90分" not in (t_d2.reply or ""):
        failures.append("D: 施術時間の確認がない")
    if not lookup_d.calls:
        failures.append("D: 東京・90分後に予約APIを呼んでいない")
    else:
        if any(c.get("area") != "tokyo" for c in lookup_d.calls):
            failures.append("D: area が tokyo でない")
        if any(c.get("duration_minutes") != 90 for c in lookup_d.calls):
            failures.append("D: 90分以外で検索している")
        dates = [c.get("date") for c in lookup_d.calls]
        if len(dates) < 2:
            failures.append(f"D: 複数日を確認していない {dates}")
        weekdays = []
        for iso in dates:
            y, m, d = iso.split("-")
            weekdays.append(datetime(int(y), int(m), int(d)).weekday())
        if any(wd >= 5 for wd in weekdays):
            failures.append("D: 平日以外の日を見ている")
    if t_d3.show_booking_cta:
        failures.append("D: 候補提示で CTA がある")
    if t_d3.available_slots:
        failures.append(f"D: 複数日なのに時刻枠を混ぜている {t_d3.available_slots}")
    if not t_d3.available_dates:
        failures.append("D: 候補日がない")
    if "ご都合の良い日、もしくはご希望の時間帯" not in (t_d3.reply or ""):
        failures.append("D: 日付または時間帯の次の入力を促していない")
    if any(p in (t_d3.reply or "") for p in ASK_SPECIFIC[:4]):
        failures.append("D: 具体日時を聞き返している")

    print("\n===== E 夕方 → 時間帯候補日、19:00へ変換しない =====")
    lookup_e = mock_slots("10:00", "18:00", "19:30")
    t_e = continue_chat(
        "夕方がいいです",
        t_d3,
        match_fn=empty_match,
        complete_fn=lambda _m: "夕方ですと、候補の日に空きがあります。",
        lookup_fn=lookup_e,
    )
    print("  E range", t_e.requested_time_range, "time", t_e.requested_time, "dates", t_e.available_dates, "cta", t_e.show_booking_cta)
    if t_e.requested_time == "19:00":
        failures.append("E: 夕方を19:00に変換している")
    if t_e.requested_time_range != "evening":
        failures.append(f"E: time_range={t_e.requested_time_range}")
    if t_e.show_booking_cta:
        failures.append("E: 夕方候補で CTA がある")
    if any(p in (t_e.reply or "") for p in ASK_SPECIFIC[:4]):
        failures.append("E: 具体日時を聞き返している")
    if not t_e.available_dates:
        failures.append("E: 夕方の候補日がない")

    print("\n===== F 予約相談中は毎回CTAしない =====")
    if t_d3.show_booking_cta or t_e.show_booking_cta:
        failures.append("F: 候補確認中に CTA がある")

    print("\n===== G 水曜日の実在枠 =====")
    lookup_g = mock_slots("18:00", "19:00")
    t_g = continue_chat(
        "この中だと水曜日がいいです",
        t_e,
        match_fn=empty_match,
        complete_fn=lambda _m: "水曜日の空きを確認しました。",
        lookup_fn=lookup_g,
    )
    print("  G date", t_g.requested_date, "slots", t_g.available_slots, "cta", t_g.show_booking_cta)
    if not t_g.requested_date:
        failures.append("G: 水曜日が日付になっていない")
    else:
        y, m, d = t_g.requested_date.split("-")
        if datetime(int(y), int(m), int(d)).weekday() != 2:
            failures.append(f"G: {t_g.requested_date} が水曜日でない")
    if t_g.available_slots != ["18:00", "19:00"]:
        failures.append(f"G: 実在枠と違う {t_g.available_slots}")
    if "20:00" in t_g.available_slots:
        failures.append("G: 存在しない枠を足している")
    if t_g.show_booking_cta:
        failures.append("G: 曜日確認で CTA がある")

    print("\n===== H 具体予約意思では CTA を出さない =====")
    lookup_h = mock_slots("18:00", "19:00")
    t_h = continue_chat(
        "じゃあ水曜日の19時で予約したいです",
        t_g,
        match_fn=empty_match,
        complete_fn=lambda _m: "ご希望の時刻で確認できました。",
        lookup_fn=lookup_h,
    )
    print("  H time", t_h.requested_time, "cta", t_h.show_booking_cta, "slots", t_h.available_slots)
    if t_h.requested_time != "19:00":
        failures.append(f"H: time={t_h.requested_time}")
    if t_h.show_booking_cta:
        failures.append("H: チャット予約開始後に Web予約CTA がある")
    if "20:00" in t_h.available_slots:
        failures.append("H: 存在しない枠を足している")

    print("\n===== I 明確な相談へ切り替え =====")
    t_i = continue_chat(
        "鍼と整体どちらがいいか詳しく相談したいです",
        t_h,
        match_fn=empty_match,
        complete_fn=lambda _m: "鍼と整体は、今のお話だけならどちらも候補になりやすいです。",
    )
    print("  I intent", t_i.primary_intent, "cta", t_i.show_booking_cta)
    if t_i.primary_intent != "treatment_consultation":
        failures.append(f"I: intent={t_i.primary_intent}")
    if t_i.show_booking_cta:
        failures.append("I: 相談へ戻ったのに CTA がある")

    print("\n===== J 実在しない枠を生成しない =====")
    lookup_j = mock_slots("18:00")
    t_j = run_chat(
        "東京で90分、明日空いてますか？",
        lookup_fn=lookup_j,
        match_fn=empty_match,
        complete_fn=lambda _m: "20:00も空いています。",
    )
    if t_j.available_slots not in (["18:00"], []):
        failures.append(f"J: slots={t_j.available_slots}")
    if "18:00" not in (t_j.available_slots or []) and "18:00" not in (t_j.reply or ""):
        failures.append("J: 18:00 の空きが本文にも構造化枠にもない")
    if "20:00" in t_j.available_slots:
        failures.append("J: 本文の20:00を枠に足した")

    print("\n===== K 予約APIエラー =====")
    t_k = run_chat(
        "東京で90分、明日の19時は空いてますか？",
        lookup_fn=boom_lookup,
        match_fn=empty_match,
        complete_fn=lambda _m: "should-not-run",
    )
    if t_k.reply != BOOKING_LOOKUP_ERROR_REPLY:
        failures.append("K: 安全なエラー文でない")
    if t_k.show_booking_cta or t_k.available_slots:
        failures.append("K: エラー時に CTA または枠がある")
    if t_k.openai_called:
        failures.append("K: エラー時に LLM を呼んでいる")
    if any(x in (t_k.reply or "") for x in ("secret_table", "SELECT", "https://internal")):
        failures.append("K: 内部情報漏洩")

    print("\n===== Intent 予約がしたいです =====")
    if detect_intents("予約がしたいです").primary_intent != "reservation_intent":
        failures.append("Intent: 予約がしたいです が reservation でない")

    after_n, after_h = snapshot_knowledge(admin)
    print("snapshot after:", after_n, after_h)
    if (after_n, after_h) != (before_n, before_h):
        failures.append("Knowledge DB がテスト中に変化した")
    if after_h != EXPECTED_HASH:
        failures.append(f"終了時 hash 不一致 {after_h}")

    if failures:
        print("\n予約会話フロー FAIL")
        for item in failures:
            print("-", item)
        return 1
    print("\n予約会話フロー: PASS")
    print(f"Knowledge unchanged: n={after_n} hash={after_h}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
