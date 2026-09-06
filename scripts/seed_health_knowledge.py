"""health_knowledge_data.py → ③ health Knowledge の本番投入。

Embedding は生成しない。① official / ② notes は更新しない。
公式同期スクリプトとは独立。RAG検索は呼ばない。

  python scripts/seed_health_knowledge.py --dry-run
  python scripts/seed_health_knowledge.py --apply
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
from health_knowledge_data import (  # noqa: E402
    HEALTH_SOURCE_TYPE,
    SOURCE_KEYS,
    iter_knowledge_payloads,
    validate_health_payloads,
)
from notes_ai_data import SOURCE_KEYS as NOTES_KEYS  # noqa: E402

HEALTH_PRIORITY = 60
OFFICIAL = "official"
NOTES = "notes"
ALLOWED_KEYS = set(SOURCE_KEYS)
FULL_SELECT = (
    "id,title,content,category,source_type,status,priority,"
    "source_key,source_url,updated_at,embedding"
)
EXISTING_SELECT = (
    "id,title,content,category,source_type,status,priority,source_key,updated_at"
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def counts_from_rows(rows: list[dict]) -> dict[str, int]:
    official_active_canonical = sum(
        1
        for r in rows
        if r.get("source_type") == OFFICIAL
        and r.get("status") == "active"
        and r.get("source_key")
    )
    return {
        "total": len(rows),
        "active": sum(1 for r in rows if r.get("status") == "active"),
        "inactive": sum(1 for r in rows if r.get("status") != "active"),
        "official": sum(1 for r in rows if r.get("source_type") == OFFICIAL),
        "official_active_canonical": official_active_canonical,
        "notes": sum(1 for r in rows if r.get("source_type") == NOTES),
        "health": sum(1 for r in rows if r.get("source_type") == HEALTH_SOURCE_TYPE),
    }


def print_counts(label: str, counts: dict[str, int]) -> None:
    print(
        f"{label}: total={counts['total']} active={counts['active']} "
        f"inactive={counts['inactive']} official={counts['official']} "
        f"official_active_canonical={counts['official_active_canonical']} "
        f"notes={counts['notes']} health={counts['health']}"
    )


def fetch_all(admin) -> list[dict]:
    res = admin.table("ai_knowledge").select(FULL_SELECT).order("id").execute()
    return list(res.data or [])


def fingerprint(rows: list[dict], source_type: str, allowed_keys: set[str] | None = None) -> tuple[int, str]:
    picked = []
    for r in rows:
        if r.get("source_type") != source_type:
            continue
        if allowed_keys is not None and (r.get("source_key") or "") not in allowed_keys:
            continue
        picked.append(
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
        )
    picked.sort(key=lambda x: str(x.get("id") or ""))
    blob = json.dumps(picked, ensure_ascii=False, sort_keys=True, default=str)
    return len(picked), hashlib.sha256(blob.encode("utf-8")).hexdigest()


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
        "source_type": HEALTH_SOURCE_TYPE,
        "status": "active",
        "priority": HEALTH_PRIORITY,
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
        ("source_type", HEALTH_SOURCE_TYPE),
        ("status", "active"),
    )
    for field, expected in pairs:
        actual = existing.get(field) or ""
        if actual != expected:
            diffs.append(field)
    return diffs


def load_payloads() -> list[dict]:
    problems = validate_health_payloads()
    if problems:
        raise RuntimeError("health_knowledge_data.py の検証に失敗: " + "; ".join(problems))
    payloads = iter_knowledge_payloads()
    for payload in payloads:
        key = payload["source_key"]
        if key not in ALLOWED_KEYS:
            raise RuntimeError(f"許可されていない source_key です: {key}")
        if payload.get("source_type") != HEALTH_SOURCE_TYPE:
            raise RuntimeError(f"{key}: source_type が health ではありません")
        if not str(key).startswith("health_"):
            raise RuntimeError(f"{key}: health_ 接頭辞がありません")
    if len(payloads) != 7:
        raise RuntimeError(f"投入対象は7件であるべきです: {len(payloads)}")
    return payloads


def main() -> int:
    parser = argparse.ArgumentParser(description="③ health Knowledge を本番へ投入する（Embeddingなし）")
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
    before_official_active = [
        r
        for r in before_rows
        if r.get("source_type") == OFFICIAL and r.get("status") == "active" and r.get("source_key")
    ]
    before_official_n, before_official_hash = fingerprint(before_official_active, OFFICIAL)
    before_notes_n, before_notes_hash = fingerprint(before_rows, NOTES, set(NOTES_KEYS))
    existing = fetch_existing_by_keys(admin, [p["source_key"] for p in payloads])

    print("mode:", "dry-run" if dry_run else "apply")
    print("OPENAI: 未使用（Embedding生成なし）")
    print_counts("DB before", before_counts)
    print("official active+source_key:", before_official_n, "hash:", before_official_hash[:16])
    print("notes:", before_notes_n, "hash:", before_notes_hash[:16])
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
        print(f"  source_type: {HEALTH_SOURCE_TYPE}")
        print(f"  chars: {len(payload['content'] or '')}")
        print(f"  → {action}")
        if found is None:
            planned_insert.append(payload)
        else:
            if found.get("source_type") not in (None, HEALTH_SOURCE_TYPE):
                print("error: 既存行の source_type が health ではありません:", found.get("source_type"))
                return 1
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
    after_official_active = [
        r
        for r in after_rows
        if r.get("source_type") == OFFICIAL and r.get("status") == "active" and r.get("source_key")
    ]
    after_official_n, after_official_hash = fingerprint(after_official_active, OFFICIAL)
    after_notes_n, after_notes_hash = fingerprint(after_rows, NOTES, set(NOTES_KEYS))
    print()
    print_counts("DB after", after_counts)
    print("official active+source_key:", after_official_n, "hash:", after_official_hash[:16])
    print("notes:", after_notes_n, "hash:", after_notes_hash[:16])
    print("INSERT件数:", inserted)

    if (after_official_n, after_official_hash) != (before_official_n, before_official_hash):
        print("error: ① official に変更があります")
        return 1
    if (after_notes_n, after_notes_hash) != (before_notes_n, before_notes_hash):
        print("error: ② notes に変更があります")
        return 1
    if after_counts["official_active_canonical"] != 19:
        print("error: official active canonical が 19 ではありません", after_counts)
        return 1
    if after_counts["notes"] != 6:
        print("error: notes が 6 ではありません", after_counts)
        return 1
    if after_counts["inactive"] != 2:
        print("error: inactive が 2 ではありません", after_counts)
        return 1

    health_rows = [
        r
        for r in after_rows
        if r.get("source_type") == HEALTH_SOURCE_TYPE and r.get("source_key") in ALLOWED_KEYS
    ]
    by_key = {(r.get("source_key") or ""): r for r in health_rows}
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
        if row.get("category") != "health":
            print("error: category が health ではありません:", key)
            return 1
        if inserted and row.get("embedding") is not None and key in {p["source_key"] for p in planned_insert}:
            print("error: 新規行の embedding が設定されています（今回はNULLであるべき）:", key)
            return 1

    if after_counts["health"] < 7:
        print("error: health が 7 件未満です", after_counts)
        return 1
    print("official 19件 / notes 6件 / inactive 2件: 変更なし")
    print("Embedding: 生成していない")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
