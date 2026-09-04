"""RAG 基盤の初期 Knowledge 登録と Test 1〜5。

チャットAPI・Chat Completions は呼ばない。検索 RPC のみ。
院内施術料金は登録しない。
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from dotenv import load_dotenv

load_dotenv(os.path.join(ROOT, ".env"))

from ai_knowledge import (  # noqa: E402
    EMBEDDING_DIMS,
    EMBEDDING_MODEL,
    embed_knowledge_rows,
    get_admin_client,
    match_ai_knowledge,
)

SEED_TITLES = (
    "KARiN.基本情報",
    "施術について",
    "現在の院内施術",
    "初回30%OFFについて",
)

SEED = [
    {
        "title": "KARiN.基本情報",
        "content": (
            "KARiN.は鍼灸・整体・トレーニング・コンディショニングなどを、"
            "身体の状態や目的に合わせて組み合わせて提供している。"
        ),
        "category": "service",
        "source_type": "official",
        "status": "active",
        "priority": 100,
        "source_url": "https://karin-sb.jp/",
    },
    {
        "title": "施術について",
        "content": (
            "何を受ければいいか分からない場合でも相談できる。"
            "状態や目的を確認したうえで必要な施術内容を組み合わせる。"
        ),
        "category": "service",
        "source_type": "official",
        "status": "active",
        "priority": 100,
        "source_url": "https://karin-sb.jp/treatment",
    },
    {
        "title": "現在の院内施術",
        "content": "現在は出張施術を中心に承っており、院内施術については準備中です。",
        "category": "service",
        "source_type": "official",
        "status": "active",
        "priority": 100,
        "source_url": "https://karin-sb.jp/book",
    },
    {
        "title": "初回30%OFFについて",
        "content": (
            "LINEにご登録いただいた方は、初回のみ30%OFFでご利用いただけます。"
            "Webからご予約いただいた場合でも、LINEにご登録いただいていれば初回30%OFFをご利用いただけます。"
            "ご予約後、当日担当者にLINE登録済みである旨をお伝えください。"
        ),
        "category": "pricing",
        "source_type": "official",
        "status": "active",
        "priority": 100,
        "source_url": "https://karin-sb.jp/",
    },
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def format_similarity(value) -> str:
    if value is None:
        return "n/a"
    return f"{float(value):.4f}"


def print_hits(hits: list[dict]) -> None:
    if not hits:
        print("  検索結果: 0件")
        return
    print(f"  検索結果: {len(hits)}件")
    for i, hit in enumerate(hits, 1):
        print(
            f"  {i}. title={hit.get('title')!r}"
            f"  similarity={format_similarity(hit.get('similarity'))}"
            f"  priority={hit.get('priority')}"
            f"  source_type={hit.get('source_type')}"
        )


def titles_of(hits: list[dict]) -> list[str]:
    return [h.get("title") or "" for h in hits]


def run_case(name: str, query: str, expected: str, ok: bool, hits: list[dict]) -> None:
    print(f"\n===== {name} =====")
    print(f"  クエリ: {query}")
    print(f"  期待: {expected}")
    print_hits(hits)
    print(f"  判定: {'PASS' if ok else 'FAIL'}")


def upsert_seed(admin) -> list[dict]:
    existing = admin.table("ai_knowledge").select("*").in_("title", list(SEED_TITLES)).execute()
    by_title = {row["title"]: row for row in (existing.data or [])}
    rows = []
    for item in SEED:
        payload = dict(item)
        payload["updated_at"] = now_iso()
        found = by_title.get(item["title"])
        if found:
            admin.table("ai_knowledge").update(payload).eq("id", found["id"]).execute()
            payload["id"] = found["id"]
            payload["embedding"] = None
        else:
            payload["created_at"] = now_iso()
            res = admin.table("ai_knowledge").insert(payload).execute()
            payload["id"] = res.data[0]["id"]
            payload["embedding"] = None
        rows.append(payload)
    return rows


def main() -> int:
    print("model:", EMBEDDING_MODEL)
    print("dims:", EMBEDDING_DIMS)
    print("OPENAI_API_KEY:", "設定済み" if (os.getenv("OPENAI_API_KEY") or "").strip() else "未設定")

    admin = get_admin_client()
    rows = upsert_seed(admin)
    print("初期 Knowledge 登録:", len(rows), "件")

    updated = embed_knowledge_rows(rows, force=True)
    print("Embedding 更新:", updated, "件")

    failures = []

    query1 = "初回30%OFFについて知りたい"
    expected1 = "『初回30%OFFについて』が検索結果に含まれる"
    hits1 = match_ai_knowledge(query1, match_count=5, similarity_threshold=0.0, admin=admin)
    ok1 = any("30%OFF" in t for t in titles_of(hits1))
    run_case("Test 1", query1, expected1, ok1, hits1)
    if not ok1:
        failures.append("Test 1: 初回30%OFF が検索されない")

    query2 = "何を受ければいいか分からない"
    expected2 = "『施術について』または『KARiN.基本情報』が検索結果に含まれる"
    hits2 = match_ai_knowledge(query2, match_count=5, similarity_threshold=0.0, admin=admin)
    ok2 = any("施術" in t or "基本情報" in t for t in titles_of(hits2))
    run_case("Test 2", query2, expected2, ok2, hits2)
    if not ok2:
        failures.append("Test 2: 施術・相談の Knowledge が検索されない")

    query3 = "院内で施術できますか？"
    expected3 = "『現在の院内施術』（出張中心・院内は準備中）が検索結果に含まれる"
    hits3 = match_ai_knowledge(query3, match_count=5, similarity_threshold=0.0, admin=admin)
    ok3 = any("院内" in t for t in titles_of(hits3))
    run_case("Test 3", query3, expected3, ok3, hits3)
    if not ok3:
        failures.append("Test 3: 院内準備中の Knowledge が検索されない")

    off_row = next(r for r in rows if r["title"] == "初回30%OFFについて")

    query4 = "初回30%OFFについて知りたい"
    expected4 = "inactive にした『初回30%OFFについて』が検索結果に出ない"
    admin.table("ai_knowledge").update({"status": "inactive", "updated_at": now_iso()}).eq("id", off_row["id"]).execute()
    hits4 = match_ai_knowledge(query4, match_count=5, similarity_threshold=0.0, admin=admin)
    ok4 = not any("30%OFF" in t for t in titles_of(hits4))
    run_case("Test 4", query4, expected4, ok4, hits4)
    if not ok4:
        failures.append("Test 4: inactive なのに 30%OFF が検索された")
    admin.table("ai_knowledge").update({"status": "active", "updated_at": now_iso()}).eq("id", off_row["id"]).execute()
    print("  後処理: 初回30%OFF を active に戻した")

    query5 = "RAGテスト専用フレーズ"
    expected5 = "新規追加した『RAGテスト用 Knowledge』が検索結果に含まれる"
    extra = {
        "title": "RAGテスト用 Knowledge",
        "content": "これは検索テスト専用の一時Knowledgeです。カリンのテストクエリ「RAGテスト専用フレーズ」に答えます。",
        "category": "faq",
        "source_type": "official",
        "status": "active",
        "priority": 100,
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    extra_res = admin.table("ai_knowledge").insert(extra).execute()
    extra_id = extra_res.data[0]["id"]
    extra["id"] = extra_id
    embed_knowledge_rows([extra], force=True)
    hits5 = match_ai_knowledge(query5, match_count=5, similarity_threshold=0.0, admin=admin)
    ok5 = extra_id in {h.get("id") for h in hits5}
    run_case("Test 5", query5, expected5, ok5, hits5)
    if not ok5:
        failures.append("Test 5: 新規 Knowledge が検索されない")

    admin.table("ai_knowledge").update({"status": "inactive", "updated_at": now_iso()}).eq("id", extra_id).execute()
    print("  後処理: テスト用 Knowledge を inactive にした（公式4件は active のまま）")

    print("\n========== まとめ ==========")
    print("  Test 1:", "PASS" if ok1 else "FAIL")
    print("  Test 2:", "PASS" if ok2 else "FAIL")
    print("  Test 3:", "PASS" if ok3 else "FAIL")
    print("  Test 4:", "PASS" if ok4 else "FAIL")
    print("  Test 5:", "PASS" if ok5 else "FAIL")
    if failures:
        print("失敗詳細:")
        for f in failures:
            print("-", f)
        return 1
    print("Test 1〜5: すべて成功")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
