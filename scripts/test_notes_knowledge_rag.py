"""② notes の実相談ベース RAG 確認（読み取り専用）。

Knowledgeの思想を直接聞く質問は使わない。
本番への INSERT / UPDATE / DELETE / Embedding 保存は行わない。

  python scripts/test_notes_knowledge_rag.py
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from dotenv import load_dotenv

load_dotenv(os.path.join(ROOT, ".env"), override=True)

from ai_knowledge import get_admin_client, match_ai_knowledge  # noqa: E402

MATCH_COUNT = 10
INDEX_SELECT = "id,title,source_key,source_type,status"


def format_similarity(value) -> str:
    if value is None:
        return "n/a"
    return f"{float(value):.4f}"


def load_index(admin) -> dict:
    res = admin.table("ai_knowledge").select(INDEX_SELECT).execute()
    rows = list(res.data or [])
    return {str(row["id"]): row for row in rows if row.get("id")}


def annotate(hits: list[dict], by_id: dict) -> list[dict]:
    out = []
    for hit in hits:
        row = by_id.get(str(hit.get("id") or ""))
        item = dict(hit)
        item["source_key"] = (row or {}).get("source_key")
        out.append(item)
    return out


def keys_of(hits: list[dict]) -> list[str]:
    return [h.get("source_key") or "" for h in hits]


def has_all(hits: list[dict], required: tuple[str, ...]) -> bool:
    present = set(keys_of(hits))
    return all(key in present for key in required)


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


def run_case(name: str, query: str, expected: str, required: tuple[str, ...], hits: list[dict]) -> bool:
    ok = has_all(hits, required)
    print(f"\n===== {name} =====")
    print(f"  クエリ: {query}")
    print(f"  期待: {expected}")
    print_hits(hits)
    top = hits[0]["source_key"] if hits else None
    top_sim = format_similarity(hits[0].get("similarity") if hits else None)
    print(f"  1位: {top} similarity={top_sim}")
    print(f"  必須キー: {required} → {'あり' if ok else '不足'}")
    print(f"  判定: {'PASS' if ok else 'FAIL'}")
    return ok


def main() -> int:
    print("mode: read-only")
    print("match_count:", MATCH_COUNT)
    print("1位固定ではない。関連notesが候補に入るかを見る。")
    admin = get_admin_client()
    by_id = load_index(admin)

    def search(query: str) -> list[dict]:
        hits = match_ai_knowledge(
            query, match_count=MATCH_COUNT, similarity_threshold=0.0, admin=admin
        )
        return annotate(hits, by_id)

    cases = [
        (
            "Test 1",
            "腰が痛いので、腰を温めたら良いですか？",
            "notes_body_connection が候補に入る（局所だけ見ない判断材料）。診断Knowledgeではない",
            ("notes_body_connection",),
        ),
        (
            "Test 2",
            "腰が痛いです。",
            "notes_body_connection が候補。notes_undecided_consultation も可",
            ("notes_body_connection",),
        ),
        (
            "Test 3",
            "肩が痛いんですが、何をしたらいいですか？",
            "notes_body_connection と notes_undecided_consultation。approach_candidates は任意",
            ("notes_body_connection", "notes_undecided_consultation"),
        ),
        (
            "Test 4",
            "腰が痛いんですが、鍼と整体だったらどっちがいいですか？",
            "notes_suggestion_stance と notes_approach_candidates。body_connection は任意",
            ("notes_suggestion_stance", "notes_approach_candidates"),
        ),
        (
            "Test 5",
            "まだ予約するか決めてないんですが、ちょっと相談してもいいですか？",
            "notes_reservation_intent が候補（相談を先にする）",
            ("notes_reservation_intent",),
        ),
        (
            "Test 6",
            "腰が痛いんですが、病院に行った方がいいですか？",
            "notes_medical_safety が候補（診断しない・一律に病院へ送らない）",
            ("notes_medical_safety",),
        ),
    ]

    results = []
    failures = []
    for name, query, expected, required in cases:
        hits = search(query)
        ok = run_case(name, query, expected, required, hits)
        top = hits[0] if hits else {}
        related = [k for k in keys_of(hits) if k.startswith("notes_")]
        results.append(
            {
                "name": name,
                "ok": ok,
                "top_key": top.get("source_key"),
                "top_sim": top.get("similarity"),
                "related_notes": related,
            }
        )
        if not ok:
            failures.append(name)

    print("\n========== まとめ ==========")
    for item in results:
        print(
            f"  {item['name']}: {'PASS' if item['ok'] else 'FAIL'}"
            f"  1位={item['top_key']}"
            f"  sim={format_similarity(item['top_sim'])}"
            f"  notes={item['related_notes']}"
        )
    if failures:
        print("失敗:", ", ".join(failures))
        return 1
    print("Test 1〜6: すべて成功")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
