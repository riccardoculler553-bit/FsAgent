# kb/retriever.py
"""
KBRetriever — Qdrant 向量知识库
=================================
存储层  : Qdrant（内置 Dashboard: http://localhost:6333/dashboard）
Embedding: DeepSeek /v1/embeddings
启动    : .\qdrant.exe --disable-telemetry
管理    : 浏览器访问 http://localhost:6333/dashboard

目录:
  qdrant_data/    ← Qdrant 持久化目录（自动创建）
"""

import os
import uuid
import asyncio
import httpx
from pathlib import Path

# qdrant_client 可能不在系统 Python 中, 懒加载
QdrantClient = None
PointStruct = None
Distance = None
VectorParams = None

def _ensure_qdrant():
    global QdrantClient, PointStruct, Distance, VectorParams
    if QdrantClient is None:
        from qdrant_client import QdrantClient as QC
        from qdrant_client.models import PointStruct as PS, Distance as D, VectorParams as VP
        QdrantClient = QC
        PointStruct = PS
        Distance = D
        VectorParams = VP

# ── 配置 ────────────────────────────────────────────────────
KB_DIR = Path(os.getenv("KB_DIR", "qdrant_data"))
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
COLLECTION_NAME = "finance_knowledge"
VECTOR_SIZE = 1536

DEEPSEEK_API_KEY  = os.getenv("DEEPSEEK_API_KEY", "sk-d14c8f313d2f436cbe5c4f3503e7097e")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")

# ── Embedding ────────────────────────────────────────────────

async def _embed(texts: list[str]) -> list[list[float]]:
    """DeepSeek embedding, 失败 fallback 字符频率"""
    try:
        async with httpx.AsyncClient(
            base_url=DEEPSEEK_BASE_URL,
            headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"},
            timeout=20.0,
        ) as client:
            resp = await client.post("/v1/embeddings", json={"model": "deepseek-embedding", "input": texts})
            if resp.status_code == 200:
                data = resp.json()
                return [item["embedding"] for item in data["data"]]
    except Exception as e:
        print(f"  [KBRetriever] embedding 失败: {e}, fallback")
    return _fallback_embed(texts)

def _fallback_embed(texts: list[str]) -> list[list[float]]:
    result = []
    for text in texts:
        vec = [0.0] * VECTOR_SIZE
        for ch in text:
            vec[ord(ch) % VECTOR_SIZE] += 1.0
        norm = sum(x * x for x in vec) ** 0.5 or 1.0
        result.append([x / norm for x in vec])
    return result

# ── KBRetriever ────────────────────────────────────────────────

class KBRetriever:

    def __init__(self):
        _ensure_qdrant()
        KB_DIR.mkdir(parents=True, exist_ok=True)
        self._client = QdrantClient(url=QDRANT_URL)
        self._ensure_collection()
        print(f"  [KBRetriever] Qdrant 就绪, 文档数: {self.doc_count}")

    def _ensure_collection(self):
        _ensure_qdrant()
        collections = [c.name for c in self._client.get_collections().collections]
        if COLLECTION_NAME not in collections:
            self._client.create_collection(
                collection_name=COLLECTION_NAME,
                vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
            )

    # ── 写入 ──

    async def add_documents(self, docs: list[dict]) -> int:
        if not docs:
            return 0
        texts = [f"{d.get('title','')}\n{d.get('content','')}" for d in docs]
        vectors = await _embed(texts)
        points = []
        for i, doc in enumerate(docs):
            did = doc.get("id") or str(uuid.uuid4())
            points.append(PointStruct(
                id=did,
                vector=vectors[i],
                payload={
                    "title": doc.get("title", ""),
                    "content": doc.get("content", ""),
                    "source": doc.get("source", ""),
                    "tags": ",".join(doc.get("tags", [])),
                },
            ))
        self._client.upsert(collection_name=COLLECTION_NAME, points=points)
        print(f"  [KBRetriever] upsert {len(docs)} 条, 当前 {self.doc_count} 条")
        return len(docs)

    # ── 检索 ──

    async def search(self, query: str, top_k: int = 5) -> list[dict]:
        if self.doc_count == 0:
            return []
        vecs = await _embed([query])
        results = self._client.query_points(
            collection_name=COLLECTION_NAME,
            query=vecs[0],
            limit=min(top_k, self.doc_count),
        )
        return [
            {
                "id": r.id,
                "title": r.payload.get("title", ""),
                "content": r.payload.get("content", ""),
                "source": r.payload.get("source", ""),
                "tags": (r.payload.get("tags", "") or "").split(","),
                "_score": round(r.score, 4),
            }
            for r in results.points
        ]

    # ── 管理 ──

    def delete(self, doc_id: str) -> bool:
        try:
            self._client.delete(collection_name=COLLECTION_NAME, points_selector=[doc_id])
            return True
        except Exception as e:
            print(f"  [KBRetriever] delete 失败: {e}")
            return False

    def list_all(self, limit: int = 100) -> list[dict]:
        results = self._client.scroll(
            collection_name=COLLECTION_NAME,
            limit=limit,
            with_payload=True,
        )
        points = results[0] if isinstance(results, tuple) else results
        return [
            {"id": r.id, "title": r.payload.get("title",""),
             "source": r.payload.get("source",""),
             "tags": (r.payload.get("tags","") or "").split(",")}
            for r in points
        ]

    def clear(self):
        self._client.delete_collection(COLLECTION_NAME)
        self._ensure_collection()
        print("  [KBRetriever] 知识库已清空")

    @property
    def doc_count(self) -> int:
        return self._client.count(collection_name=COLLECTION_NAME).count
