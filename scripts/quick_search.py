#!/usr/bin/env python3
"""Quick retrieval + synthesis test against the (possibly partial) LanceDB index.
Makes external calls: embeddings -> xinference (bge-m3), synthesis -> local Qwen.
Prints the raw answer + evidence (LOCAL diagnostic; egress safeguard not applied here)."""
from __future__ import annotations

import sys

from src import embeddings, qwen, store

query = sys.argv[1] if len(sys.argv) > 1 else "Jane Doe"
k = int(sys.argv[2]) if len(sys.argv) > 2 else 8

print(f">>> query: {query!r}  (top_k={k})\n")
vec = embeddings.embed_one(query)
chunks = store.search(vec, k)
print(f"retrieved {len(chunks)} chunks:\n")
for i, c in enumerate(chunks, 1):
    snip = c.text.replace("\n", " ")[:160]
    print(f"[{i}] score={c.score:.3f} from={c.sender[:50]} date={c.date_iso[:10]} folder={c.folder}")
    print(f"    subj: {c.subject[:80]}")
    print(f"    {snip}\n")

print("=== Qwen synthesis (local model, external call) ===\n")
ans = qwen.synthesize(query, chunks)
print(ans)
