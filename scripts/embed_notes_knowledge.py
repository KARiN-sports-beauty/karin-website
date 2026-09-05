"""notes 6件だけ Embedding を生成・保存する。

正本 notes_ai_data.py と DB 本文が一致していること。
① official は更新しない。OpenAI は Embedding 生成時のみ。

  python scripts/embed_notes_knowledge.py --dry-run
  python scripts/embed_notes_knowledge.py --apply
"""
from __future__ import annotations

import argparse
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
    embed_texts,
    get_admin_client,
    save_embedding,
)
from notes_ai_data import SOURCE_KEYS, iter_knowledge_payloads  # noqa: E402

NOTES = "notes"
OFFICIAL = "official"
SELECT = (
    "id,title,content,category,source_type,status,priority,"
    "source_key,updated_at,embedding"
)


def official_fingerprint(rows: list[dict]) -> tuple[int, str]:
    official = [
        r
        for r in rows
        if r.get("source_type") == OFFICIAL and r.get("status") == "active" and r.get("source_key")
    ]
    slim = [
        {
            "id": r.get("id"),
            "title": r.get("title"),
            "content": r.get("content"),
            "status": r.get("status"),
            "source_key": r.get("source_key"),
            "embedding": r.get("embedding"),
        }
        for r in official
    ]
    blob = json.dumps(slim, ensure_ascii=False, sort_keys=True, default=str)
    return len(official), hashlib.sha256(blob.encode("utf-8")).hexdigest()


def embedding_len(value) -> int | None:
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return None
    if isinstance(value, list):
        return len(value)
    return None


def fetch_all(admin) -> list[dict]:
    res = admin.table("ai_knowledge").select(SELECT).order("id").execute()
    return list(res.data or [])


def load_notes_rows(rows: list[dict]) -> tuple[dict[str, dict], list[str]]:
    payloads = {p["source_key"]: p for p in iter_knowledge_payloads()}
    found: dict[str, dict] = {}
    mismatches: list[str] = []
    for row in rows:
        key = (row.get("source_key") or "").strip()
        if key not in SOURCE_KEYS:
            continue
        if row.get("source_type") != NOTES:
            mismatches.append(f"{key}: source_type={row.get('source_type')}（notes であるべき）")
            continue
        payload = payloads[key]
        if (row.get("content") or "") != payload["content"]:
            mismatches.append(f"{key}: DB本文が notes_ai_data.py と一致しない")
            continue
        if (row.get("title") or "") != payload["title"]:
            mismatches.append(f"{key}: title が正本と一致しない")
            continue
        if row.get("status") != "active":
            mismatches.append(f"{key}: status={row.get('status')}（active であるべき）")
            continue
        found[key] = row
    missing = [k for k in SOURCE_KEYS if k not in found and not any(m.startswith(k + ":") for m in mismatches)]
    for key in missing:
        mismatches.append(f"{key}: DBに見つからない")
    return found, mismatches


def main() -> int:
    parser = argparse.ArgumentParser(description="② notes 6件だけ Embedding する")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.dry_run and args.apply:
        print("error: --dry-run と --apply は同時に指定できない")
        return 2
    dry_run = not args.apply

    admin = get_admin_client()
    rows = fetch_all(admin)
    before_n, before_hash = official_fingerprint(rows)
    found, mismatches = load_notes_rows(rows)

    print("mode:", "dry-run" if dry_run else "apply")
    print("model:", EMBEDDING_MODEL)
    print("dims:", EMBEDDING_DIMS)
    print("OPENAI_API_KEY:", "設定済み" if (os.getenv("OPENAI_API_KEY") or "").strip() else "未設定")
    print("official active+source_key:", before_n, "hash:", before_hash)

    if mismatches:
        print("error: 正本とDBの差異があるため Embedding を中止します")
        for msg in mismatches:
            print("-", msg)
        return 1

    targets = [found[k] for k in SOURCE_KEYS]
    print("対象件数:", len(targets))
    for row in targets:
        print(
            f"  {row['source_key']} embed_now={row.get('embedding') is not None}"
            f" chars={len(row.get('content') or '')}"
        )

    if dry_run:
        print("dry-run: Embedding生成・保存なし")
        return 0

    vectors = embed_texts([row["content"] for row in targets])
    api_calls = 1
    success = 0
    failed = 0
    for row, vec in zip(targets, vectors):
        if len(vec) != EMBEDDING_DIMS:
            print("error: 次元が違います:", row["source_key"], len(vec))
            failed += 1
            continue
        save_embedding(admin, row["id"], vec)
        success += 1
        print("saved:", row["source_key"])

    after_rows = fetch_all(admin)
    after_n, after_hash = official_fingerprint(after_rows)
    print("API呼び出し件数:", api_calls, f"（入力テキスト {len(targets)} 件）")
    print("成功:", success, "失敗:", failed)
    print("official after:", after_n, "hash:", after_hash)
    if (after_n, after_hash) != (before_n, before_hash):
        print("error: ① official 19件に変更があります")
        return 1

    notes_after = {
        (r.get("source_key") or ""): r
        for r in after_rows
        if r.get("source_type") == NOTES and r.get("source_key") in SOURCE_KEYS
    }
    for key in SOURCE_KEYS:
        row = notes_after.get(key)
        dim = embedding_len(row.get("embedding") if row else None)
        if dim != EMBEDDING_DIMS:
            print("error: embedding 未保存または次元不正:", key, dim)
            return 1
    print("official 19件: 変更なし")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
