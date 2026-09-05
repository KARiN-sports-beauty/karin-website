"""notes_ai_data.py → ② notes Knowledge の本番投入。

Embedding は生成しない。① official は更新しない。
公式同期スクリプトとは独立。RAG検索は呼ばない。

  python scripts/seed_notes_knowledge.py --dry-run
  python scripts/seed_notes_knowledge.py --apply
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from dotenv import load_dotenv

load_dotenv(os.path.join(ROOT, ".env"), override=True)

from ai_knowledge import get_admin_client  # noqa: E402
from notes_ai_data import (  # noqa: E402
    NOT_CREATED_SOURCE_KEYS,
    NOTES_SOURCE_TYPE,
    SOURCE_KEYS,
    iter_knowledge_payloads,
    validate_notes_payloads,
)

NOTES_PRIORITY = 80
OFFICIAL = "official"
ALLOWED_KEYS = set(SOURCE_KEYS)
FORBIDDEN_KEYS = set(NOT_CREATED_SOURCE_KEYS)
OFFICIAL_SELECT = (
    "id,title,content,category,source_type,status,priority,"
    "source_key,source_url,updated_at,embedding"
)
EXISTING_SELECT = (
    "id,title,content,category,source_type,status,priority,source_key,updated_at"
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def counts_from_rows(rows: list[dict]) -> dict[str, int]:
    return {
        "total": len(rows),
        "active": sum(1 for r in rows if r.get("status") == "active"),
        "inactive": sum(1 for r in rows if r.get("status") != "active"),
        "official": sum(1 for r in rows if r.get("source_type") == OFFICIAL),
        "notes": sum(1 for r in rows if r.get("source_type") == NOTES_SOURCE_TYPE),
        "health": sum(1 for r in rows if r.get("source_type") == "health"),
    }


def print_counts(label: str, counts: dict[str, int]) -> None:
    print(
        f"{label}: total={counts['total']} active={counts['active']} "
        f"inactive={counts['inactive']} official={counts['official']} "
        f"notes={counts['notes']} health={counts['health']}"
    )


def fetch_all(admin) -> list[dict]:
    res = admin.table("ai_knowledge").select(OFFICIAL_SELECT).order("id").execute()
    return list(res.data or [])


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
            "category": r.get("category"),
            "source_type": r.get("source_type"),
            "status": r.get("status"),
            "priority": r.get("priority"),
            "source_key": r.get("source_key"),
            "embedding": r.get("embedding"),
        }
        for r in official
    ]
    blob = json.dumps(slim, ensure_ascii=False, sort_keys=True, default=str)
    return len(official), hashlib.sha256(blob.encode("utf-8")).hexdigest()


def fetch_existing_by_keys(admin, keys: list[str]) -> dict[str, dict]:
    res = (
        admin.table("ai_knowledge")
        .select(EXISTING_SELECT)
        .in_("source_key", keys)
        .execute()
    )
    found: dict[str, dict] = {}
    for row in res.data or []:
        key = (row.get("source_key") or "").strip()
        if key:
            found[key] = row
    return found


def payload_to_insert(payload: dict) -> dict:
    return {
        "title": payload["title"],
        "content": payload["content"],
        "category": payload["category"],
        "source_type": NOTES_SOURCE_TYPE,
        "status": "active",
        "priority": NOTES_PRIORITY,
        "source_key": payload["source_key"],
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }


def describe_diff(existing: dict, payload: dict) -> list[str]:
    diffs = []
    pairs = (
        ("title", payload["title"]),
        ("content", payload["content"]),
        ("category", payload["category"]),
        ("source_type", NOTES_SOURCE_TYPE),
        ("status", "active"),
    )
    for field, expected in pairs:
        actual = existing.get(field) or ""
        if actual != expected:
            diffs.append(field)
    return diffs


def load_payloads() -> list[dict]:
    problems = validate_notes_payloads()
    if problems:
        raise RuntimeError("notes_ai_data.py の検証に失敗: " + "; ".join(problems))
    payloads = iter_knowledge_payloads()
    for payload in payloads:
        key = payload["source_key"]
        if key in FORBIDDEN_KEYS:
            raise RuntimeError(f"投入禁止の source_key です: {key}")
        if key not in ALLOWED_KEYS:
            raise RuntimeError(f"許可されていない source_key です: {key}")
        if payload.get("source_type") != NOTES_SOURCE_TYPE:
            raise RuntimeError(f"{key}: source_type が notes ではありません")
        if not str(key).startswith("notes_"):
            raise RuntimeError(f"{key}: notes_ 接頭辞がありません")
    if len(payloads) != 6:
        raise RuntimeError(f"投入対象は6件であるべきです: {len(payloads)}")
    return payloads


def main() -> int:
    parser = argparse.ArgumentParser(description="② notes Knowledge を本番へ投入する（Embeddingなし）")
    parser.add_argument("--dry-run", action="store_true", help="DBを変更せず計画だけ表示する")
    parser.add_argument("--apply", action="store_true", help="本番DBへINSERTする")
    args = parser.parse_args()
    if args.dry_run and args.apply:
        print("error: --dry-run と --apply は同時に指定できない")
        return 2
    dry_run = not args.apply

    payloads = load_payloads()
    admin = get_admin_client()
    before_rows = fetch_all(admin)
    before_counts = counts_from_rows(before_rows)
    before_official_n, before_official_hash = official_fingerprint(before_rows)
    existing = fetch_existing_by_keys(admin, [p["source_key"] for p in payloads])

    print("mode:", "dry-run" if dry_run else "apply")
    print("OPENAI: 未使用（Embedding生成なし）")
    print_counts("DB before", before_counts)
    print("official active+source_key:", before_official_n, "hash:", before_official_hash)
    print()

    planned_insert = []
    skipped = []
    for payload in payloads:
        key = payload["source_key"]
        found = existing.get(key)
        action = "INSERT" if found is None else "SKIP (既存source_keyあり・UPDATEしない)"
        print(f"{key}")
        print(f"  title: {payload['title']}")
        print(f"  category: {payload['category']}")
        print(f"  status: active")
        print(f"  source_type: {NOTES_SOURCE_TYPE}")
        print(f"  chars: {len(payload['content'] or '')}")
        print(f"  → {action}")
        if found is None:
            planned_insert.append(payload)
        else:
            diffs = describe_diff(found, payload)
            skipped.append((payload, found, diffs))
            print(f"    existing id={found.get('id')} status={found.get('status')} source_type={found.get('source_type')}")
            print(f"    差分フィールド: {diffs or 'なし（本文・メタ一致）'}")
        print()

    print("投入予定 INSERT:", len(planned_insert))
    print("SKIP:", len(skipped))

    if dry_run:
        print("dry-run: DB書き込みなし")
        return 0

    inserted = 0
    for payload in planned_insert:
        row = payload_to_insert(payload)
        if "embedding" in row:
            raise RuntimeError("embedding を投入してはいけません")
        admin.table("ai_knowledge").insert(row).execute()
        inserted += 1
        print("inserted:", payload["source_key"])

    after_rows = fetch_all(admin)
    after_counts = counts_from_rows(after_rows)
    after_official_n, after_official_hash = official_fingerprint(after_rows)
    print()
    print_counts("DB after", after_counts)
    print("official active+source_key:", after_official_n, "hash:", after_official_hash)
    print("INSERT件数:", inserted)

    if (after_official_n, after_official_hash) != (before_official_n, before_official_hash):
        print("error: ① official 19件に変更があります")
        return 1

    notes_rows = [
        r
        for r in after_rows
        if r.get("source_type") == NOTES_SOURCE_TYPE and r.get("source_key") in ALLOWED_KEYS
    ]
    by_key = {(r.get("source_key") or ""): r for r in notes_rows}
    payload_by_key = {p["source_key"]: p for p in payloads}
    for key in SOURCE_KEYS:
        row = by_key.get(key)
        if row is None:
            print("error: 投入後に欠けています:", key)
            return 1
        if row.get("status") != "active":
            print("error: status が active ではありません:", key)
            return 1
        if (row.get("content") or "") != payload_by_key[key]["content"]:
            print("error: 本文が正本と一致しません:", key)
            return 1
        if row.get("embedding") is not None:
            print("error: embedding が設定されています（今回はNULLであるべき）:", key)
            return 1

    expected = {"total": 27, "active": 25, "inactive": 2, "official": 21, "notes": 6, "health": 0}
    # official は active 19 + inactive 2 = 21。ユーザー期待の official:19 は active 公式。
    if after_counts["notes"] != 6 or after_counts["health"] != 0:
        print("error: notes/health 件数が期待と違います", after_counts)
        return 1
    if after_counts["active"] != 25 or after_counts["inactive"] != 2 or after_counts["total"] != 27:
        print("error: 総件数/status が期待と違います", after_counts)
        return 1
    print("official 19件: 変更なし")
    print("Embedding: 生成していない")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
