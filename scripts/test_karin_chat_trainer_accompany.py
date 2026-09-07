"""トレーナー帯同はチャット受付せず、お問い合わせフォームへ誘導する。

  python scripts/test_karin_chat_trainer_accompany.py
"""
from __future__ import annotations

import hashlib
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from dotenv import load_dotenv

load_dotenv(os.path.join(ROOT, ".env"), override=True)

from ai_knowledge import get_admin_client  # noqa: E402
from karin_chat import (  # noqa: E402
    CORPORATE_VISIT_REPLY,
    INITIAL_RESERVATION_REPLY,
    INQUIRY_FOLLOWUP_REPLY,
    TRAINER_ACCOMPANY_FOLLOWUP_REPLY,
    TRAINER_ACCOMPANY_REPLY,
    chat_public_payload,
    run_chat,
)
from karin_chat_intent import detect_intents  # noqa: E402
from karin_chat_memory import get_or_create_conversation, reset_store_for_tests  # noqa: E402

SNAPSHOT_SELECT = (
    "id,title,content,category,source_type,status,priority,"
    "source_key,source_url,effective_from,effective_to,updated_at,embedding"
)
EXPECTED_HASH = "ec0bff70d737b542f5419ebbaf9d44e76e5e085b06943dc11aa7232efa9fe373"
FORBIDDEN = (
    "ご依頼を承知しました",
    "手配を進めます",
    "トレーナーを手配します",
    "こちらで調整します",
    "こちらから連絡します",
    "予約をお取りします",
    "依頼を受け付けました",
    "手配します",
    "依頼を承知しました",
    "訪問させていただきます",
    "訪問を確定",
    "日程を確定",
)
HEARING = (
    "日程を教えて",
    "目的を教えて",
    "サポート内容",
    "ツアー帯同ですか",
    "救急処置も必要",
    "場所を教えて",
)


def snapshot_knowledge(admin) -> tuple[int, str]:
    res = admin.table("ai_knowledge").select(SNAPSHOT_SELECT).order("id").execute()
    rows = list(res.data or [])
    blob = json.dumps(rows, ensure_ascii=False, sort_keys=True, default=str)
    return len(rows), hashlib.sha256(blob.encode("utf-8")).hexdigest()


def continue_chat(message: str, previous, **kwargs):
    cid = None if previous is None else previous.conversation_id
    return run_chat(message, conversation_id=cid, **kwargs)


def expect_inquiry_cta(payload: dict, label: str, failures: list[str]) -> None:
    if payload.get("show_inquiry_cta") is not True:
        failures.append(f"{label}: show_inquiry_cta がない")
    if payload.get("show_contact_cta") is not True:
        failures.append(f"{label}: show_contact_cta 互換フラグがない")
    if payload.get("inquiry_required") is not True:
        failures.append(f"{label}: inquiry_required がない")
    if payload.get("contact_url") != "/contact":
        failures.append(f"{label}: contact_url が /contact でない")
    if payload.get("show_booking_cta"):
        failures.append(f"{label}: 予約CTAが出ている")


def empty_match(*_a, **_k):
    return []


def complete(_messages):
    return "承知しました。日程とサポート内容を教えてください。手配を進めます。"


def boom_lookup(**_kwargs):
    raise RuntimeError("booking should not run")


def boom_book(*_a, **_k):
    raise RuntimeError("/api/book should not run")


def has_forbidden(reply: str) -> list[str]:
    return [p for p in FORBIDDEN if p in (reply or "")]


def main() -> int:
    print("mode: トレーナー帯同 → お問い合わせ / Knowledge読み取り専用")
    reset_store_for_tests()
    failures: list[str] = []
    admin = get_admin_client()
    before_n, before_h = snapshot_knowledge(admin)
    print("snapshot before:", before_n, before_h)
    if before_h != EXPECTED_HASH:
        failures.append(f"開始時 hash 不一致 {before_h}")

    kw = dict(
        match_fn=empty_match,
        complete_fn=complete,
        lookup_fn=boom_lookup,
        book_fn=boom_book,
    )

    print("\n===== 1 依頼したいです → フォーム案内 + CTA =====")
    t1 = run_chat("トレーナー帯同を依頼したいです", **kw)
    p1 = chat_public_payload(t1)
    print("  intent", t1.primary_intent, "inquiry_cta", p1.get("show_inquiry_cta"), "contact_url", p1.get("contact_url"))
    if t1.primary_intent != "trainer_accompaniment":
        failures.append(f"1: intent={t1.primary_intent}")
    if "inquiry_required" not in t1.secondary_intents:
        failures.append("1: inquiry_required にまとまっていない")
    if t1.reply != TRAINER_ACCOMPANY_REPLY:
        failures.append("1: 指定の案内文でない")
    expect_inquiry_cta(p1, "1", failures)
    if t1.openai_called or t1.rag_called or t1.reservation_api_called:
        failures.append("1: LLM/RAG/予約APIを呼んでいる")
    if t1.booking_completed or t1.booking_create_called:
        failures.append("1: 予約確定している")
    if has_forbidden(t1.reply):
        failures.append(f"1: 禁止表現 {has_forbidden(t1.reply)}")
    draft1 = get_or_create_conversation(t1.conversation_id).booking_draft
    if draft1.reservation_intent or draft1.date or draft1.phase != "collecting":
        failures.append("1: BookingDraft に依頼を保存している")

    print("\n===== 2 ツアー帯同 → ヒアリングしない =====")
    t2 = continue_chat("ツアー帯同", t1, **kw)
    print("  2 intent", t2.primary_intent, (t2.reply or "")[:80])
    if t2.primary_intent != "trainer_accompaniment":
        failures.append(f"2: intent={t2.primary_intent}")
    if t2.reply != TRAINER_ACCOMPANY_FOLLOWUP_REPLY:
        failures.append("2: 短いフォーム案内でない")
    if any(h in (t2.reply or "") for h in HEARING):
        failures.append("2: ヒアリングを始めている")
    if t2.openai_called or t2.reservation_api_called:
        failures.append("2: LLMまたは予約APIを呼んでいる")
    expect_inquiry_cta(chat_public_payload(t2), "2", failures)

    print("\n===== 3 詳細を続けても手配しない =====")
    t3a = continue_chat("10/3〜25", t2, **kw)
    t3b = continue_chat("救急処置、ケア", t3a, **kw)
    t3c = continue_chat("特にないです", t3b, **kw)
    t3d = continue_chat("よろしくお願いします", t3c, **kw)
    for label, turn in (("3a", t3a), ("3b", t3b), ("3c", t3c), ("3d", t3d)):
        bad = has_forbidden(turn.reply)
        if bad:
            failures.append(f"{label}: 禁止表現 {bad}")
        if turn.reply != TRAINER_ACCOMPANY_FOLLOWUP_REPLY:
            failures.append(f"{label}: フォーム案内を維持していない")
        if turn.openai_called or turn.reservation_api_called or turn.booking_create_called:
            failures.append(f"{label}: 予約/LLM を呼んでいる")
        expect_inquiry_cta(chat_public_payload(turn), label, failures)
    draft3 = get_or_create_conversation(t3d.conversation_id).booking_draft
    if draft3.date or draft3.time or draft3.booking_id:
        failures.append("3: 帯同内容を予約Draftへ入れている")

    print("\n===== C1 企業訪問 → フォーム案内 + CTA =====")
    reset_store_for_tests()
    c1 = run_chat("企業訪問をお願いしたいです", **kw)
    pc1 = chat_public_payload(c1)
    print("  intent", c1.primary_intent, "inquiry_cta", pc1.get("show_inquiry_cta"), "contact_url", pc1.get("contact_url"))
    if c1.primary_intent != "corporate_visit":
        failures.append(f"C1: intent={c1.primary_intent}")
    if "inquiry_required" not in c1.secondary_intents:
        failures.append("C1: inquiry_required にまとまっていない")
    if c1.reply != CORPORATE_VISIT_REPLY:
        failures.append("C1: 指定の案内文でない")
    expect_inquiry_cta(pc1, "C1", failures)
    if c1.openai_called or c1.rag_called or c1.reservation_api_called:
        failures.append("C1: LLM/RAG/予約APIを呼んでいる")
    if c1.booking_completed or c1.booking_create_called:
        failures.append("C1: 予約確定している")
    if has_forbidden(c1.reply):
        failures.append(f"C1: 禁止表現 {has_forbidden(c1.reply)}")
    draft_c = get_or_create_conversation(c1.conversation_id).booking_draft
    if draft_c.reservation_intent or draft_c.date:
        failures.append("C1: BookingDraft に依頼を保存している")

    print("\n===== C2 人数・日付を続けても確定しない =====")
    c2 = continue_chat("10月3日に20人でお願いしたい", c1, **kw)
    print("  C2", c2.primary_intent, (c2.reply or "")[:80])
    if c2.primary_intent != "corporate_visit":
        failures.append(f"C2: intent={c2.primary_intent}")
    if c2.reply != INQUIRY_FOLLOWUP_REPLY:
        failures.append("C2: 短いフォーム案内でない")
    if has_forbidden(c2.reply):
        failures.append(f"C2: 禁止表現 {has_forbidden(c2.reply)}")
    if c2.openai_called or c2.reservation_api_called or c2.booking_create_called:
        failures.append("C2: 予約/LLM を呼んでいる")
    expect_inquiry_cta(chat_public_payload(c2), "C2", failures)

    print("\n===== C3 ストレッチ希望でも手配しない =====")
    c3 = continue_chat("ストレッチをしてほしい", c2, **kw)
    if c3.reply != INQUIRY_FOLLOWUP_REPLY:
        failures.append("C3: フォーム案内を維持していない")
    if has_forbidden(c3.reply) or "訪問させていただきます" in (c3.reply or ""):
        failures.append(f"C3: 禁止表現 {has_forbidden(c3.reply)}")
    if c3.reservation_api_called or c3.booking_create_called:
        failures.append("C3: 予約処理を呼んでいる")
    expect_inquiry_cta(chat_public_payload(c3), "C3", failures)

    print("\n===== C4 よろしくお願いします =====")
    c4a = continue_chat("特にありません", c3, **kw)
    c4 = continue_chat("よろしくお願いします", c4a, **kw)
    if c4.reply != INQUIRY_FOLLOWUP_REPLY:
        failures.append("C4: フォーム案内を維持していない")
    if has_forbidden(c4.reply):
        failures.append(f"C4: 禁止表現 {has_forbidden(c4.reply)}")
    if c4.openai_called or c4.reservation_api_called:
        failures.append("C4: LLMまたは予約API")
    expect_inquiry_cta(chat_public_payload(c4), "C4", failures)
    draft_c4 = get_or_create_conversation(c4.conversation_id).booking_draft
    if draft_c4.date or draft_c4.booking_id:
        failures.append("C4: 企業訪問を予約Draftへ入れている")

    print("\n===== 4 通常予約フロー =====")
    reset_store_for_tests()
    t4 = run_chat(
        "予約がしたいです",
        match_fn=empty_match,
        complete_fn=lambda _m: "should-not-run",
        lookup_fn=boom_lookup,
        book_fn=boom_book,
    )
    print("  4 intent", t4.primary_intent, "book_cta", t4.show_booking_cta)
    if t4.primary_intent != "reservation_intent":
        failures.append(f"4: intent={t4.primary_intent}")
    if t4.reply != INITIAL_RESERVATION_REPLY:
        failures.append("4: C9初回予約案内になっていない")
    if not t4.show_booking_cta:
        failures.append("4: 予約CTAがない")
    if t4.show_contact_cta or t4.show_inquiry_cta:
        failures.append("4: 通常予約にお問い合わせCTAがある")
    p4 = chat_public_payload(t4)
    if p4.get("show_inquiry_cta") or p4.get("contact_url"):
        failures.append("4: 予約フローの公開JSONに inquiry CTA がある")

    print("\n===== 5 通常の身体相談 =====")
    t5 = run_chat(
        "腰が痛いです",
        match_fn=empty_match,
        complete_fn=lambda _m: "腰のお悩みですね。無理のない範囲で様子を見つつ、必要なら施術の候補も整理できます。",
        lookup_fn=boom_lookup,
        book_fn=boom_book,
    )
    print("  5 intent", t5.primary_intent, "cta", t5.show_booking_cta, t5.show_inquiry_cta)
    if t5.primary_intent != "consultation":
        failures.append(f"5: intent={t5.primary_intent}")
    if t5.show_contact_cta or t5.show_inquiry_cta or t5.show_booking_cta:
        failures.append("5: 相談中にCTAがある")
    if t5.reservation_api_called:
        failures.append("5: 相談で予約API")

    print("\n===== 6 CTA が /contact へ =====")
    js_path = os.path.join(ROOT, "static", "js", "karin_chat.js")
    widget_path = os.path.join(ROOT, "templates", "_karin_chat.html")
    js = open(js_path, encoding="utf-8").read()
    widget = open(widget_path, encoding="utf-8").read()
    if "appendContactCta" not in js or "showInquiryCta" not in js:
        failures.append("6: お問い合わせCTAのDOM生成がない")
    if 'link.textContent = "お問い合わせフォームへ"' not in js:
        failures.append("6: CTA文言がない")
    if "resolveContactUrl" not in js or 'raw === "/contact"' not in js:
        failures.append("6: /contact への遷移がない")
    if "show_inquiry_cta === true" not in js:
        failures.append("6: show_inquiry_cta を見ていない")
    if "if (options.showInquiryCta)" not in js or "appendContactCta(col, options.contactUrl)" not in js:
        failures.append("6: 問い合わせCTAの描画条件がない")
    inquiry_block = js.split("if (options.showInquiryCta)", 1)[-1].split("} else if", 1)[0]
    if "looksLikeEmergencyReply" in inquiry_block:
        failures.append("6: 問い合わせCTAが緊急判定で消える")
    if "data-contact-url" not in widget:
        failures.append("6: テンプレートに contact URL がない")
    if "innerHTML" in js:
        failures.append("6: innerHTML を使っている")
    if "救急処置" not in TRAINER_ACCOMPANY_REPLY:
        failures.append("6: 帯同案内の誤判定回帰が無効")
    from app import app

    with app.test_client() as client:
        contact = client.get("/contact")
        print("  /contact", contact.status_code)
        if contact.status_code != 200:
            failures.append("6: /contact が開けない")

        print("\n===== /api/chat 実レスポンス =====")
        reset_store_for_tests()
        trainer_api = client.post(
            "/api/chat", json={"message": "トレーナー帯同を依頼したいです"}
        )
        trainer_body = trainer_api.get_json(silent=True) or {}
        print("  trainer keys", sorted(trainer_body.keys()))
        print(
            "  trainer flags",
            {
                k: trainer_body.get(k)
                for k in (
                    "show_inquiry_cta",
                    "show_contact_cta",
                    "inquiry_required",
                    "contact_url",
                    "show_booking_cta",
                )
            },
        )
        if trainer_api.status_code != 200:
            failures.append("API trainer: status != 200")
        expect_inquiry_cta(trainer_body, "API trainer", failures)
        if trainer_body.get("reply") != TRAINER_ACCOMPANY_REPLY:
            failures.append("API trainer: 案内文が違う")
        trainer_follow = client.post(
            "/api/chat",
            json={
                "message": "ツアー帯同",
                "conversation_id": trainer_body.get("conversation_id"),
            },
        )
        expect_inquiry_cta(trainer_follow.get_json(silent=True) or {}, "API trainer follow", failures)

        reset_store_for_tests()
        corp_api = client.post(
            "/api/chat", json={"message": "企業訪問をお願いしたいです"}
        )
        corp_body = corp_api.get_json(silent=True) or {}
        print(
            "  corporate flags",
            {
                k: corp_body.get(k)
                for k in (
                    "show_inquiry_cta",
                    "show_contact_cta",
                    "inquiry_required",
                    "contact_url",
                    "show_booking_cta",
                )
            },
        )
        if corp_api.status_code != 200:
            failures.append("API corporate: status != 200")
        expect_inquiry_cta(corp_body, "API corporate", failures)
        if corp_body.get("reply") != CORPORATE_VISIT_REPLY:
            failures.append("API corporate: 案内文が違う")
        corp_follow = client.post(
            "/api/chat",
            json={
                "message": "10月3日に20人でお願いしたい",
                "conversation_id": corp_body.get("conversation_id"),
            },
        )
        expect_inquiry_cta(corp_follow.get_json(silent=True) or {}, "API corporate follow", failures)

    print("\n===== 7 /api/book を呼ばない =====")
    src_chat = open(os.path.join(ROOT, "karin_chat.py"), encoding="utf-8").read()
    src_intent = open(os.path.join(ROOT, "karin_chat_intent.py"), encoding="utf-8").read()
    if "/api/book" in src_chat or "/api/book" in src_intent:
        failures.append("7: チャット側が /api/book を参照している")
    if t1.reservation_api_called or t3d.booking_create_called:
        failures.append("7: 帯同フローから予約処理が呼ばれた")
    if c1.reservation_api_called or c4.booking_create_called:
        failures.append("7: 企業訪問フローから予約処理が呼ばれた")

    print("\n===== Intent 優先 =====")
    if detect_intents("トレーナー帯同を依頼したいです").primary_intent != "trainer_accompaniment":
        failures.append("Intent: 依頼したいです が trainer_accompaniment でない")
    corp_intent = detect_intents("企業訪問をお願いしたいです")
    if corp_intent.primary_intent != "corporate_visit":
        failures.append(f"Intent: 企業訪問が {corp_intent.primary_intent}")
    if "inquiry_required" not in corp_intent.secondary_intents:
        failures.append("Intent: 企業訪問が inquiry_required でない")
    if detect_intents("出張で施術をお願いすることはできますか？").primary_intent != "service_info":
        failures.append("Intent: 出張の可否確認が service_info でない")

    after_n, after_h = snapshot_knowledge(admin)
    print("snapshot after:", after_n, after_h)
    if (after_n, after_h) != (before_n, before_h):
        failures.append("Knowledge DB がテスト中に変化した")
    if after_h != EXPECTED_HASH:
        failures.append(f"終了時 hash 不一致 {after_h}")

    if failures:
        print("\n問い合わせ誘導 FAIL")
        for item in failures:
            print("-", item)
        return 1
    print("\n問い合わせ誘導: PASS")
    print(f"Knowledge unchanged: n={after_n} hash={after_h}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
