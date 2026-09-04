"""ai_knowledge の Embedding を生成して保存する。

既定: embedding が空の行のみ。
  python scripts/ai_knowledge_embed.py
全件再生成:
  python scripts/ai_knowledge_embed.py --all

OPENAI_API_KEY は環境変数から読む。キーはログに出さない。
"""
from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from dotenv import load_dotenv

load_dotenv(os.path.join(ROOT, ".env"), override=True)

from ai_knowledge import (  # noqa: E402
    EMBEDDING_DIMS,
    EMBEDDING_MODEL,
    embed_knowledge_rows,
    fetch_knowledge_for_embed,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="ai_knowledge の Embedding を更新する")
    parser.add_argument(
        "--all",
        action="store_true",
        help="既存 Embedding も含めて全件再生成する",
    )
    args = parser.parse_args()

    key_set = bool((os.getenv("OPENAI_API_KEY") or "").strip())
    print("OPENAI_API_KEY:", "設定済み" if key_set else "未設定")
    print("model:", EMBEDDING_MODEL)
    print("dims:", EMBEDDING_DIMS)

    rows = fetch_knowledge_for_embed(missing_only=not args.all)
    print("対象件数:", len(rows))
    if not rows:
        print("更新対象なし")
        return 0

    updated = embed_knowledge_rows(rows, force=True)
    print("更新件数:", updated)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
