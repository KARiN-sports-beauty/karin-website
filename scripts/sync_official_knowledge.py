"""official_site_data.py → ①公式Knowledge の一方向同期。

対象: source_type=official かつ official_site_data に存在する source_key のみ。
② notes / ③ health は読まない・更新しない。
source_key=NULL の行は同期対象外。即 DELETE しない（正本に無い active 公式は inactive）。

  python scripts/sync_official_knowledge.py --dry-run
  python scripts/sync_official_knowledge.py --apply

RAG検索・RPC・既存テストは呼ばない。キーはログに出さない。
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

from ai_knowledge import (  # noqa: E402
    EMBEDDING_DIMS,
    EMBEDDING_MODEL,
    embed_texts,
    get_admin_client,
    save_embedding,
)
from official_site_data import iter_knowledge_payloads  # noqa: E402

OFFICIAL = "official"
OFFICIAL_PRIORITY = 100
NON_OFFICIAL_TYPES = ("notes", "health")
SELECT_OFFICIAL = (
    "id,title,content,category,source_type,status,priority,"
    "source_url,source_key,effective_from,effective_to,embedding,updated_at"
)
SELECT_AUDIT = (
    "id,title,content,category,source_type,status,priority,"
    "source_url,source_key,effective_from,effective_to,updated_at"
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def content_changed(existing: dict, payload: dict) -> bool:
    return (existing.get("content") or "") != (payload.get("content") or "")


def metadata_changed(existing: dict, payload: dict) -> bool:
    checks = (
        (existing.get("title") or "") != (payload.get("title") or ""),
        (existing.get("category") or "") != (payload.get("category") or ""),
        (existing.get("source_type") or "") != OFFICIAL,
        (existing.get("source_url") or "") != (payload.get("source_url") or ""),
        existing.get("priority") != OFFICIAL_PRIORITY,
        (existing.get("status") or "") != "active",
    )
    return any(checks)


def needs_embedding(existing: dict | None, payload: dict) -> bool:
    if existing is None:
        return True
    if existing.get("embedding") is None:
        return True
    return content_changed(existing, payload)


def canonical_fields(payload: dict) -> dict:
    return {
        "title": payload["title"],
        "content": payload["content"],
        "category": payload["category"],
        "source_type": OFFICIAL,
        "status": "active",
        "priority": OFFICIAL_PRIORITY,
        "source_url": payload.get("source_url"),
        "source_key": payload["source_key"],
        "updated_at": now_iso(),
    }


def fetch_official_with_source_key(admin) -> list[dict]:
    res = (
        admin.table("ai_knowledge")
        .select(SELECT_OFFICIAL)
        .eq("source_type", OFFICIAL)
        .not_.is_("source_key", "null")
        .execute()
    )
    return list(res.data or [])


def index_by_source_key(rows: list[dict]) -> dict[str, dict]:
    """同一source_keyが複数ある場合は active を優先し、次に updated_at が新しい行。"""
    ranked: dict[str, dict] = {}
    for row in rows:
        key = (row.get("source_key") or "").strip()
        if not key:
            continue
        prev = ranked.get(key)
        if prev is None:
            ranked[key] = row
            continue
        prev_active = prev.get("status") == "active"
        row_active = row.get("status") == "active"
        if row_active and not prev_active:
            ranked[key] = row
        elif row_active == prev_active:
            if str(row.get("updated_at") or "") > str(prev.get("updated_at") or ""):
                ranked[key] = row
    return ranked


def snapshot_notes_health(admin) -> tuple[int, str]:
    rows = []
    for source_type in NON_OFFICIAL_TYPES:
        res = (
            admin.table("ai_knowledge")
            .select(SELECT_AUDIT)
            .eq("source_type", source_type)
            .execute()
        )
        rows.extend(res.data or [])
    blob = json.dumps(rows, ensure_ascii=False, sort_keys=True, default=str)
    digest = hashlib.sha256(blob.encode("utf-8")).hexdigest()
    return len(rows), digest


def build_plan(payloads: list[dict], official_rows: list[dict]) -> list[dict]:
    by_key = index_by_source_key(official_rows)
    payload_keys = {p["source_key"] for p in payloads}
    plan = []

    for payload in payloads:
        key = payload["source_key"]
        existing = by_key.get(key)
        if existing is None:
            action = "INSERT"
            embed = "UPDATE"
        elif content_changed(existing, payload) or metadata_changed(existing, payload):
            action = "UPDATE"
            embed = "UPDATE" if needs_embedding(existing, payload) else "NO CHANGE"
        else:
            action = "NO CHANGE"
            embed = "UPDATE" if needs_embedding(existing, payload) else "NO CHANGE"
        plan.append(
            {
                "source_key": key,
                "action": action,
                "embed": embed,
                "payload": payload,
                "existing": existing,
            }
        )

    for row in official_rows:
        key = (row.get("source_key") or "").strip()
        if not key or key in payload_keys:
            continue
        if row.get("status") != "active":
            continue
        plan.append(
            {
                "source_key": key,
                "action": "INACTIVE",
                "embed": "NO CHANGE",
                "payload": None,
                "existing": row,
            }
        )
    return plan


def print_plan(plan: list[dict], dry_run: bool) -> None:
    print("mode:", "dry-run" if dry_run else "apply")
    print("model:", EMBEDDING_MODEL)
    print("dims:", EMBEDDING_DIMS)
    print("OPENAI_API_KEY:", "設定済み" if (os.getenv("OPENAI_API_KEY") or "").strip() else "未設定")
    print()
    for item in plan:
        print(f"{item['source_key']}\n→ {item['action']}\n→ embedding {item['embed']}")
        print()
    counts = {}
    for item in plan:
        counts[item["action"]] = counts.get(item["action"], 0) + 1
    embed_n = sum(1 for item in plan if item["embed"] == "UPDATE")
    print("summary:", counts, "embedding UPDATE:", embed_n)


def apply_plan(admin, plan: list[dict]) -> dict[str, int]:
    stats = {"INSERT": 0, "UPDATE": 0, "INACTIVE": 0, "NO CHANGE": 0, "embedding": 0}
    embed_jobs: list[tuple[str, str]] = []

    for item in plan:
        action = item["action"]
        payload = item["payload"]
        existing = item["existing"]

        if action == "NO CHANGE":
            stats["NO CHANGE"] += 1
            if item["embed"] == "UPDATE" and existing:
                embed_jobs.append((existing["id"], existing["content"]))
            continue

        if action == "INACTIVE":
            admin.table("ai_knowledge").update(
                {"status": "inactive", "updated_at": now_iso()}
            ).eq("id", existing["id"]).eq("source_type", OFFICIAL).execute()
            stats["INACTIVE"] += 1
            continue

        fields = canonical_fields(payload)
        if action == "UPDATE":
            admin.table("ai_knowledge").update(fields).eq("id", existing["id"]).eq(
                "source_type", OFFICIAL
            ).execute()
            stats["UPDATE"] += 1
            row_id = existing["id"]
            content = fields["content"]
        else:
            insert_data = dict(fields)
            insert_data["created_at"] = now_iso()
            inserted = True
            try:
                res = admin.table("ai_knowledge").insert(insert_data).execute()
                row_id = res.data[0]["id"]
            except Exception:
                found = (
                    admin.table("ai_knowledge")
                    .select("id")
                    .eq("source_type", OFFICIAL)
                    .eq("source_key", payload["source_key"])
                    .eq("status", "active")
                    .limit(1)
                    .execute()
                )
                if not found.data:
                    raise
                row_id = found.data[0]["id"]
                admin.table("ai_knowledge").update(fields).eq("id", row_id).eq(
                    "source_type", OFFICIAL
                ).execute()
                inserted = False
            if inserted:
                stats["INSERT"] += 1
            else:
                stats["UPDATE"] += 1
            content = fields["content"]

        if item["embed"] == "UPDATE":
            embed_jobs.append((row_id, content))

    if embed_jobs:
        vectors = embed_texts([content for _id, content in embed_jobs])
        for (row_id, _content), vec in zip(embed_jobs, vectors):
            save_embedding(admin, row_id, vec)
        stats["embedding"] = len(embed_jobs)

    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description="①公式Knowledgeを official_site_data から同期する")
    parser.add_argument("--dry-run", action="store_true", help="DBを変更せず計画だけ表示する")
    parser.add_argument("--apply", action="store_true", help="本番同期を実行する")
    args = parser.parse_args()
    if args.dry_run and args.apply:
        print("error: --dry-run と --apply は同時に指定できない")
        return 2
    dry_run = not args.apply

    payloads = iter_knowledge_payloads()
    if not payloads:
        print("error: 正本の payload が空です")
        return 1
    keys = [p["source_key"] for p in payloads]
    if len(keys) != len(set(keys)):
        print("error: official_site_data の source_key が重複しています")
        return 1
    for p in payloads:
        if p.get("source_type") != OFFICIAL:
            print("error: 正本に official 以外が含まれています:", p.get("source_key"))
            return 1

    admin = get_admin_client()
    before_n, before_hash = snapshot_notes_health(admin)
    official_rows = fetch_official_with_source_key(admin)
    plan = build_plan(payloads, official_rows)
    print_plan(plan, dry_run=dry_run)
    print("notes/health 件数(同期前):", before_n, "hash:", before_hash)

    if dry_run:
        print("dry-run: DB書き込みなし")
        return 0

    stats = apply_plan(admin, plan)
    after_n, after_hash = snapshot_notes_health(admin)
    print("apply summary:", stats)
    print("notes/health 件数(同期後):", after_n, "hash:", after_hash)
    if (before_n, before_hash) != (after_n, after_hash):
        print("error: notes/health に変更があります")
        return 1
    print("notes/health: 変更なし")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
