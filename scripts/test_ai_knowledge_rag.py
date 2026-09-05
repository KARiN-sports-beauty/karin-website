"""RAG 回帰テスト（本番 ai_knowledge は読み取り専用）。

チャットAPI・Chat Completions は呼ばない。検索 RPC のみ。
本番への INSERT / UPDATE / DELETE / Embedding 保存は行わない。
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

from ai_knowledge import (  # noqa: E402
    EMBEDDING_DIMS,
    EMBEDDING_MODEL,
    get_admin_client,
    match_ai_knowledge,
)

SNAPSHOT_SELECT = (
    "id,title,content,category,source_type,status,priority,"
    "source_key,source_url,effective_from,effective_to,updated_at,embedding"
)
INDEX_SELECT = "id,title,source_key,source_type,status"


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
            f"  source_key={hit.get('source_key')!r}"
            f"  similarity={format_similarity(hit.get('similarity'))}"
            f"  priority={hit.get('priority')}"
            f"  source_type={hit.get('source_type')}"
        )


def run_case(name: str, query: str, expected: str, ok: bool, hits: list[dict]) -> None:
    print(f"\n===== {name} =====")
    print(f"  クエリ: {query}")
    print(f"  期待: {expected}")
    print_hits(hits)
    print(f"  判定: {'PASS' if ok else 'FAIL'}")


def snapshot_knowledge(admin) -> tuple[int, str]:
    res = admin.table("ai_knowledge").select(SNAPSHOT_SELECT).order("id").execute()
    rows = list(res.data or [])
    blob = json.dumps(rows, ensure_ascii=False, sort_keys=True, default=str)
    digest = hashlib.sha256(blob.encode("utf-8")).hexdigest()
    return len(rows), digest


def load_index(admin) -> dict:
    res = admin.table("ai_knowledge").select(INDEX_SELECT).execute()
    rows = list(res.data or [])
    by_id = {str(row["id"]): row for row in rows if row.get("id")}
    inactive_ids = {str(row["id"]) for row in rows if row.get("status") != "active"}
    return {"rows": rows, "by_id": by_id, "inactive_ids": inactive_ids}


def annotate_hits(hits: list[dict], by_id: dict) -> list[dict]:
    annotated = []
    for hit in hits:
        row = by_id.get(str(hit.get("id") or ""))
        item = dict(hit)
        item["source_key"] = (row or {}).get("source_key")
        item["row_status"] = (row or {}).get("status")
        annotated.append(item)
    return annotated


def source_keys_of(hits: list[dict]) -> list[str]:
    return [h.get("source_key") or "" for h in hits]


def has_source_key(hits: list[dict], key: str) -> bool:
    return key in source_keys_of(hits)


def all_hits_active(hits: list[dict], inactive_ids: set[str]) -> bool:
    for hit in hits:
        hid = str(hit.get("id") or "")
        if hid in inactive_ids:
            return False
        if hit.get("row_status") and hit.get("row_status") != "active":
            return False
    return True


def search(admin, index: dict, query: str, match_count: int = 5) -> list[dict]:
    hits = match_ai_knowledge(
        query, match_count=match_count, similarity_threshold=0.0, admin=admin
    )
    return annotate_hits(hits, index["by_id"])


def main() -> int:
    print("mode: read-only")
    print("model:", EMBEDDING_MODEL)
    print("dims:", EMBEDDING_DIMS)
    print("OPENAI_API_KEY:", "設定済み" if (os.getenv("OPENAI_API_KEY") or "").strip() else "未設定")
    print("本番 ai_knowledge: SELECT / RPC のみ（INSERT/UPDATE/DELETE なし）")

    admin = get_admin_client()
    before_n, before_hash = snapshot_knowledge(admin)
    print("snapshot before: 件数=", before_n, "hash=", before_hash)

    index = load_index(admin)
    inactive_n = len(index["inactive_ids"])
    print("index: 全件=", len(index["rows"]), "inactive=", inactive_n)

    failures: list[str] = []

    def record(name: str, query: str, expected: str, ok: bool, hits: list[dict], fail_msg: str) -> None:
        run_case(name, query, expected, ok, hits)
        if not ok:
            failures.append(fail_msg)

    query1 = "初回30%OFFについて知りたい"
    hits1 = search(admin, index, query1)
    ok1 = has_source_key(hits1, "first_visit_discount") and all_hits_active(
        hits1, index["inactive_ids"]
    )
    record(
        "RAG-01",
        query1,
        "source_key=first_visit_discount が検索結果に含まれる（本番をupsertしない）",
        ok1,
        hits1,
        "RAG-01: 初回30%OFF（first_visit_discount）が検索されない",
    )

    query2 = "何を受ければいいか分からない"
    hits2 = search(admin, index, query2)
    ok2 = (
        has_source_key(hits2, "treatment_policy") or has_source_key(hits2, "basic_info")
    ) and all_hits_active(hits2, index["inactive_ids"])
    record(
        "RAG-02",
        query2,
        "source_key=treatment_policy または basic_info が検索結果に含まれる",
        ok2,
        hits2,
        "RAG-02: 施術・相談の Knowledge が検索されない",
    )

    query3 = "院内で施術できますか？"
    hits3 = search(admin, index, query3)
    ok3 = has_source_key(hits3, "in_house_status") and all_hits_active(
        hits3, index["inactive_ids"]
    )
    record(
        "RAG-03",
        query3,
        "source_key=in_house_status が検索結果に含まれる",
        ok3,
        hits3,
        "RAG-03: 院内施術の Knowledge が検索されない",
    )

    nl_cases = [
        ("NL-割引-01", "割引はありますか？", "first_visit_discount"),
        ("NL-割引-02", "初回って安くなりますか？", "first_visit_discount"),
        ("NL-割引-03", "初めてなんですけど、体験できますか？", "first_visit_discount"),
        ("NL-割引-04", "初回は何か特典ありますか？", "first_visit_discount"),
        ("NL-相談-01", "何を受ければいいかわかりません", "treatment_policy"),
        ("NL-相談-02", "自分に合う施術がわからないです", "treatment_policy"),
        ("NL-院内-01", "院内で施術できますか？", "in_house_status"),
    ]
    for name, query, key in nl_cases:
        hits = search(admin, index, query)
        ok = has_source_key(hits, key) and all_hits_active(hits, index["inactive_ids"])
        record(
            name,
            query,
            f"source_key={key} が上位候補に含まれる（1位固定ではない）",
            ok,
            hits,
            f"{name}: {key} が検索されない",
        )

    query_shop = "お店で受けることはできますか？"
    hits_shop = search(admin, index, query_shop)
    ok_shop = bool(hits_shop) and all_hits_active(hits_shop, index["inactive_ids"])
    record(
        "NL-院内-02",
        query_shop,
        "検索が動作し、結果は active のみ。in_house_status の1位は必須としない",
        ok_shop,
        hits_shop,
        "NL-院内-02: 検索結果が空、または inactive が含まれる",
    )

    query4 = "初回30%OFFについて知りたい"
    hits4 = search(admin, index, query4)
    ok4_active = all_hits_active(hits4, index["inactive_ids"])
    ok4_inactive_absent = True
    extra_phrase_hits = []
    leftover = [
        row
        for row in index["rows"]
        if row.get("status") != "active"
        and ("RAGテスト" in (row.get("title") or "") or not row.get("source_key"))
    ]
    if leftover:
        extra_phrase_hits = search(admin, index, "RAGテスト専用フレーズ")
        leftover_ids = {str(row["id"]) for row in leftover}
        ok4_inactive_absent = all(
            str(h.get("id") or "") not in leftover_ids for h in extra_phrase_hits
        )
        print(
            f"\n  RAG-04 補足: 既存 inactive {len(leftover)}件を読み取り専用で確認"
            "（本番公式は変更しない）"
        )
        print_hits(extra_phrase_hits)
    ok4 = ok4_active and ok4_inactive_absent
    run_case(
        "RAG-04",
        query4,
        "inactive Knowledge は検索結果に含まれない。本番公式の status は変更しない",
        ok4,
        hits4,
    )
    if leftover:
        print("  専用フレーズ検索: 既存 inactive 行が結果に出ないこと")
        print(f"  判定(inactive除外): {'PASS' if ok4_inactive_absent else 'FAIL'}")
    if not ok4:
        failures.append("RAG-04: inactive Knowledge が検索結果に含まれた")

    query5 = "オイルトリートメントの追加料金は？"
    hits5 = search(admin, index, query5)
    ok5 = has_source_key(hits5, "add_on_oil") and all_hits_active(
        hits5, index["inactive_ids"]
    )
    record(
        "RAG-05",
        query5,
        "既存 active 公式 Knowledge（source_key=add_on_oil）が検索できる。本番へ新規INSERTしない",
        ok5,
        hits5,
        "RAG-05: 同期済み active Knowledge（add_on_oil）が検索されない",
    )

    after_n, after_hash = snapshot_knowledge(admin)
    print("\nsnapshot after: 件数=", after_n, "hash=", after_hash)
    snapshot_ok = (before_n, before_hash) == (after_n, after_hash)
    print("DB変更:", "なし" if snapshot_ok else "あり（予期しない変更）")
    if not snapshot_ok:
        failures.append("本番 ai_knowledge の件数または内容ハッシュがテスト前後で変わった")

    print("\n========== まとめ ==========")
    print("  RAG-01:", "PASS" if ok1 else "FAIL")
    print("  RAG-02:", "PASS" if ok2 else "FAIL")
    print("  RAG-03:", "PASS" if ok3 else "FAIL")
    print("  RAG-04:", "PASS" if ok4 else "FAIL")
    print("  RAG-05:", "PASS" if ok5 else "FAIL")
    print("  snapshot:", "PASS" if snapshot_ok else "FAIL")
    if failures:
        print("失敗詳細:")
        for item in failures:
            print("-", item)
        return 1
    print("RAG回帰: 成功（本番DBは読み取り専用）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
