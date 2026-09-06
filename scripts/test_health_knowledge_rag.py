"""③ health Knowledge の実相談ベース RAG 確認。

本番への INSERT / UPDATE / DELETE は行わない。
C1安全ゲートを置き換えない。health を診断データベースとして使わない。

  python scripts/test_health_knowledge_rag.py
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

from ai_knowledge import get_admin_client, match_ai_knowledge  # noqa: E402
from karin_chat import EMERGENCY_REPLY, run_chat  # noqa: E402
from karin_chat_intent import detect_intents  # noqa: E402
from karin_chat_memory import reset_store_for_tests  # noqa: E402

MATCH_COUNT = 10
INDEX_SELECT = "id,title,source_key,source_type,status"
SNAPSHOT_SELECT = (
    "id,title,content,category,source_type,status,priority,"
    "source_key,source_url,effective_from,effective_to,updated_at,embedding"
)
HEALTH_KEYS = {
    "health_general",
    "health_back_pain",
    "health_shoulder_neck",
    "health_sleep",
    "health_hydration",
    "health_heat_illness",
    "health_exercise",
}


def format_similarity(value) -> str:
    if value is None:
        return "n/a"
    return f"{float(value):.4f}"


def snapshot_knowledge(admin) -> tuple[int, str]:
    res = admin.table("ai_knowledge").select(SNAPSHOT_SELECT).order("id").execute()
    rows = list(res.data or [])
    blob = json.dumps(rows, ensure_ascii=False, sort_keys=True, default=str)
    digest = hashlib.sha256(blob.encode("utf-8")).hexdigest()
    return len(rows), digest


def type_counts(admin) -> dict[str, int]:
    res = admin.table("ai_knowledge").select("source_type,status,source_key").execute()
    rows = list(res.data or [])
    return {
        "official_active_canonical": sum(
            1
            for r in rows
            if r.get("source_type") == "official"
            and r.get("status") == "active"
            and r.get("source_key")
        ),
        "notes": sum(1 for r in rows if r.get("source_type") == "notes"),
        "health": sum(1 for r in rows if r.get("source_type") == "health"),
        "inactive": sum(1 for r in rows if r.get("status") != "active"),
    }


def load_index(admin) -> dict:
    res = admin.table("ai_knowledge").select(INDEX_SELECT).execute()
    rows = list(res.data or [])
    return {str(row["id"]): row for row in rows if row.get("id")}


def annotate(hits: list[dict], by_id: dict) -> list[dict]:
    out = []
    for hit in hits:
        row = by_id.get(str(hit.get("id") or ""))
        item = dict(hit)
        if row:
            item["source_key"] = row.get("source_key")
            item["source_type"] = row.get("source_type")
            item["title"] = item.get("title") or row.get("title")
        out.append(item)
    return out


def keys_of(hits: list[dict]) -> list[str]:
    return [h.get("source_key") or "" for h in hits]


def print_hits(hits: list[dict]) -> None:
    if not hits:
        print("  検索結果: 0件")
        return
    print(f"  検索結果: {len(hits)}件")
    for i, hit in enumerate(hits, 1):
        print(
            f"  {i}. source_key={hit.get('source_key')!r}"
            f"  title={hit.get('title')!r}"
            f"  source_type={hit.get('source_type')}"
            f"  similarity={format_similarity(hit.get('similarity'))}"
        )


def main() -> int:
    print("mode: read-only")
    print("match_count:", MATCH_COUNT)
    print("C1安全ゲート優先。healthは診断データベースではない。")
    reset_store_for_tests()
    admin = get_admin_client()
    before_n, before_h = snapshot_knowledge(admin)
    counts = type_counts(admin)
    print(f"snapshot before: n={before_n} hash={before_h[:16]}...")
    print(
        "counts:",
        f"official_active_canonical={counts['official_active_canonical']}",
        f"notes={counts['notes']}",
        f"health={counts['health']}",
        f"inactive={counts['inactive']}",
    )
    failures: list[str] = []
    if counts["official_active_canonical"] != 19:
        failures.append(f"official active canonical が 19 ではない: {counts}")
    if counts["notes"] != 6:
        failures.append(f"notes が 6 ではない: {counts}")
    if counts["health"] < 7:
        failures.append(f"health が 7 未満: {counts}")
    if counts["inactive"] != 2:
        failures.append(f"inactive が 2 ではない: {counts}")

    by_id = load_index(admin)

    def search(query: str) -> list[dict]:
        hits = match_ai_knowledge(
            query, match_count=MATCH_COUNT, similarity_threshold=0.0, admin=admin
        )
        return annotate(hits, by_id)

    print("\n===== Test 1 睡眠 =====")
    q1 = "最近寝つきが悪いんですが、何か気をつけることありますか？"
    h1 = search(q1)
    print(f"  クエリ: {q1}")
    print_hits(h1)
    intent1 = detect_intents(q1)
    print("  intent:", intent1.primary_intent, "source_types:", intent1.source_types)
    health1 = [k for k in keys_of(h1) if k in HEALTH_KEYS]
    if "health" not in intent1.source_types:
        failures.append("Test1: source_type=health が候補になっていない")
    if "health_sleep" not in keys_of(h1) and not health1:
        failures.append("Test1: health Knowledge が検索候補にない")
    if "health_sleep" not in keys_of(h1):
        failures.append("Test1: health_sleep が候補にない")

    print("\n===== Test 2 水分・暑さ =====")
    q2 = "暑い日に運動するとき、水分ってどう取ったらいいですか？"
    h2 = search(q2)
    print(f"  クエリ: {q2}")
    print_hits(h2)
    intent2 = detect_intents(q2)
    print("  intent:", intent2.primary_intent, "source_types:", intent2.source_types)
    keys2 = set(keys_of(h2))
    if "health_hydration" not in keys2 and "health_heat_illness" not in keys2:
        failures.append("Test2: hydration / heat 関連が候補にない")
    if "health" not in intent2.source_types:
        failures.append("Test2: health が検索対象でない")

    print("\n===== Test 3 腰痛の日常 =====")
    q3 = "腰が痛いんですが、日常生活で気をつけることありますか？"
    h3 = search(q3)
    print(f"  クエリ: {q3}")
    print_hits(h3)
    intent3 = detect_intents(q3)
    print("  intent:", intent3.primary_intent, "source_types:", intent3.source_types)
    if "health_back_pain" not in keys_of(h3):
        failures.append("Test3: health_back_pain が候補にない")
    if "health" not in intent3.source_types:
        failures.append("Test3: health が検索対象でない")
    if "notes" not in intent3.source_types:
        failures.append("Test3: notes も候補であるべき（health固定ではない）")

    print("\n===== Test 4 肩こり =====")
    q4 = "肩こりが気になるんですが、普段何に気をつけたらいいですか？"
    h4 = search(q4)
    print(f"  クエリ: {q4}")
    print_hits(h4)
    intent4 = detect_intents(q4)
    print("  intent:", intent4.primary_intent, "source_types:", intent4.source_types)
    if "health_shoulder_neck" not in keys_of(h4):
        failures.append("Test4: health_shoulder_neck が候補にない")

    print("\n===== Test 5 運動の始め方 =====")
    q5 = "運動を始めたいんですが、いきなり頑張っても大丈夫ですか？"
    h5 = search(q5)
    print(f"  クエリ: {q5}")
    print_hits(h5)
    intent5 = detect_intents(q5)
    print("  intent:", intent5.primary_intent, "source_types:", intent5.source_types)
    if "health_exercise" not in keys_of(h5):
        failures.append("Test5: health_exercise が候補にない")
    if intent5.primary_intent != "health_general":
        failures.append(f"Test5: intent={intent5.primary_intent}")
    if intent5.source_types == ["official"]:
        failures.append("Test5: official だけに固定されている")

    print("\n===== Test 6 料金はofficial =====")
    q6 = "東京で90分受けたいんですが、いくらですか？"
    intent6 = detect_intents(q6)
    turn6 = run_chat(q6)
    print(f"  クエリ: {q6}")
    print("  intent:", intent6.primary_intent, "source_types:", intent6.source_types)
    print("  knowledge_keys:", turn6.knowledge_keys)
    print("  reply_preview:", (turn6.reply or "")[:160].replace("\n", " / "))
    if intent6.source_types != ["official"]:
        failures.append(f"Test6: source_types={intent6.source_types}（official であるべき）")
    if "visit_course_prices" not in turn6.knowledge_keys:
        failures.append("Test6: official の料金Knowledgeが使われていない")
    if turn6.knowledge_source_types == ["health"]:
        failures.append("Test6: health を主要根拠にしている")
    if any(k in HEALTH_KEYS for k in turn6.knowledge_keys) and "visit_course_prices" not in turn6.knowledge_keys:
        failures.append("Test6: 料金なのに health 側だけを見ている")

    print("\n===== Test 7 施術候補はnotes =====")
    q7 = "腰が痛いんですが、鍼と整体どっちがいいですか？"
    intent7 = detect_intents(q7)
    turn7 = run_chat(q7)
    print(f"  クエリ: {q7}")
    print("  intent:", intent7.primary_intent, "source_types:", intent7.source_types)
    print("  knowledge_keys:", turn7.knowledge_keys)
    print("  reply_preview:", (turn7.reply or "")[:160].replace("\n", " / "))
    if "notes" not in intent7.source_types:
        failures.append("Test7: notes が候補でない")
    notes7 = [k for k in turn7.knowledge_keys if str(k).startswith("notes_")]
    if not notes7:
        failures.append("Test7: notes の施術提案方針が使われていない")
    if not (
        "notes_suggestion_stance" in turn7.knowledge_keys
        or "notes_approach_candidates" in turn7.knowledge_keys
    ):
        failures.append("Test7: 施術候補のnotesがない")
    if intent7.source_types == ["health"]:
        failures.append("Test7: health だけで施術を決めようとしている")
    if any(p in (turn7.reply or "") for p in ("絶対に整体", "絶対に鍼", "原因です")):
        failures.append("Test7: 診断・断定がある")

    print("\n===== Test 8 緊急はC1 =====")
    q8 = "急に右半身に力が入らなくなりました"

    def boom(*_a, **_k):
        raise AssertionError("Test8: C1通過後にRAG/OpenAIを呼んではいけない")

    turn8 = run_chat(q8, match_fn=boom, complete_fn=boom)
    print(f"  クエリ: {q8}")
    print("  emergency:", turn8.emergency, "rag:", turn8.rag_called, "openai:", turn8.openai_called)
    print("  reply_preview:", (turn8.reply or "")[:120])
    if not turn8.emergency:
        failures.append("Test8: C1安全ゲートが最優先になっていない")
    if turn8.rag_called or turn8.openai_called:
        failures.append("Test8: health RAG または OpenAI を通常処理として呼んでいる")
    if turn8.reply != EMERGENCY_REPLY:
        failures.append("Test8: 固定の受診優先文でない")

    after_n, after_h = snapshot_knowledge(admin)
    print(f"\nsnapshot after: n={after_n} hash={after_h[:16]}...")
    if (after_n, after_h) != (before_n, before_h):
        failures.append("Knowledge DB snapshot がテスト前後で変化した")

    if failures:
        print("\nFAIL")
        for item in failures:
            print("-", item)
        return 1
    print("\nHealth RAGテスト: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
