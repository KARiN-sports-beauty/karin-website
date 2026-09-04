"""カリン RAG 用の薄いヘルパー。Flask の予約・ブログ処理には触れない。

OpenAI Embeddings（text-embedding-3-small / 1536）と
Supabase RPC match_ai_knowledge のみを扱う。
検索に psycopg2 は使わない。APIキーはログに出さない。
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI
from supabase import Client, create_client

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMS = 1536

_DEFAULT_SUPABASE_URL = "https://pmuvlinhusxesmhwsxtz.supabase.co"


def _require_env(name: str) -> str:
    value = (os.getenv(name) or "").strip()
    if not value:
        raise RuntimeError(f"{name} が未設定です")
    return value


def get_admin_client() -> Client:
    url = (os.getenv("SUPABASE_URL") or _DEFAULT_SUPABASE_URL).strip()
    key = (os.getenv("SUPABASE_SERVICE_KEY") or "").strip()
    if not key:
        raise RuntimeError("SUPABASE_SERVICE_KEY が未設定です（RAG は service_role のみ）")
    return create_client(url, key)


def get_openai_client() -> OpenAI:
    return OpenAI(api_key=_require_env("OPENAI_API_KEY"))


def embed_texts(texts: list[str]) -> list[list[float]]:
    cleaned = [(t or "").replace("\x00", "").strip() for t in texts]
    if not cleaned or any(not t for t in cleaned):
        raise ValueError("Embedding するテキストが空です")
    client = get_openai_client()
    response = client.embeddings.create(model=EMBEDDING_MODEL, input=cleaned)
    vectors = [item.embedding for item in sorted(response.data, key=lambda x: x.index)]
    for vec in vectors:
        if len(vec) != EMBEDDING_DIMS:
            raise RuntimeError(f"Embedding 次元が {len(vec)} です（期待値 {EMBEDDING_DIMS}）")
    return vectors


def embed_content(text: str) -> list[float]:
    return embed_texts([text])[0]


def save_embedding(admin: Client, knowledge_id: str, embedding: list[float]) -> None:
    from datetime import datetime, timezone

    admin.table("ai_knowledge").update(
        {
            "embedding": embedding,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    ).eq("id", knowledge_id).execute()


def embed_knowledge_rows(rows: list[dict], *, force: bool = False) -> int:
    """content から Embedding を生成して保存。force=False なら embedding 未設定のみ。"""
    admin = get_admin_client()
    targets = []
    for row in rows:
        if not row.get("id") or not (row.get("content") or "").strip():
            continue
        if force or row.get("embedding") is None:
            targets.append(row)
    if not targets:
        return 0
    vectors = embed_texts([row["content"] for row in targets])
    for row, vec in zip(targets, vectors):
        save_embedding(admin, row["id"], vec)
    return len(targets)


def fetch_knowledge_for_embed(*, missing_only: bool = True) -> list[dict]:
    admin = get_admin_client()
    res = admin.table("ai_knowledge").select("id, title, content, embedding").execute()
    rows = list(res.data or [])
    if missing_only:
        rows = [r for r in rows if r.get("embedding") is None]
    return rows


def match_ai_knowledge(
    query: str,
    match_count: int = 5,
    similarity_threshold: float = 0.0,
    admin: Client | None = None,
) -> list[dict]:
    """クエリ文を Embedding し、Supabase RPC で類似 Knowledge を返す。"""
    client = admin or get_admin_client()
    query_embedding = embed_content(query)
    res = client.rpc(
        "match_ai_knowledge",
        {
            "query_embedding": query_embedding,
            "match_count": match_count,
            "similarity_threshold": similarity_threshold,
        },
    ).execute()
    return list(res.data or [])
