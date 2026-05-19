"""
Vector Database Integration
Support semantic search for long-term memory
"""

from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json

# Try to import vector database libraries
try:
    import chromadb
    from chromadb.config import Settings
    CHROMADB_AVAILABLE = True
except ImportError:
    CHROMADB_AVAILABLE = False
    print("[VectorStore] ChromaDB not installed, using memory fallback")

try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False
    print("[VectorStore] NumPy not installed")

from config.settings import settings


@dataclass
class MemoryEntry:
    """Memory entry"""
    id: str
    content: str
    memory_type: str  # conversation, fact, experience, feedback
    metadata: Dict[str, Any]
    embedding: Optional[List[float]] = None
    timestamp: datetime = None
    importance_score: float = 1.0
    access_count: int = 0
    last_accessed: Optional[datetime] = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()


class VectorStore:
    """
    Vector database storage
    Support semantic search for memory retrieval
    """

    def __init__(
        self,
        collection_name: str = "agent_memory",
        persist_directory: str = "./data/vector_store"
    ):
        self.collection_name = collection_name
        self.persist_directory = persist_directory

        # Initialize vector database
        self.client = None
        self.collection = None
        self._memory_buffer: Dict[str, MemoryEntry] = {}

        if CHROMADB_AVAILABLE:
            try:
                self.client = chromadb.Client(Settings(
                    chroma_db_impl="duckdb+parquet",
                    persist_directory=persist_directory
                ))
                self.collection = self.client.get_or_create_collection(
                    name=collection_name,
                    metadata={"hnsw:space": "cosine"}
                )
                print("[VectorStore] ChromaDB initialized")
            except Exception as e:
                print(f"[VectorStore] ChromaDB init failed: {e}")

    def _get_embedding(self, text: str) -> List[float]:
        """Get text embedding - simplified version without external model"""
        # Simple hash-based embedding for demo
        return self._simple_hash_embedding(text)

    def _simple_hash_embedding(self, text: str, dim: int = 384) -> List[float]:
        """Simple hash embedding (fallback when no model available)"""
        hash_obj = hashlib.md5(text.encode())
        hash_int = int(hash_obj.hexdigest(), 16)

        # Generate pseudo-random vector
        if NUMPY_AVAILABLE:
            import numpy as np
            np.random.seed(hash_int % (2**32))
            vector = np.random.randn(dim)
            vector = vector / np.linalg.norm(vector)
            return vector.tolist()
        else:
            # Pure Python fallback
            import random
            random.seed(hash_int % (2**32))
            vector = [random.gauss(0, 1) for _ in range(dim)]
            # Normalize
            magnitude = sum(x**2 for x in vector) ** 0.5
            return [x / magnitude for x in vector]

    async def add_memory(
        self,
        content: str,
        memory_type: str = "conversation",
        metadata: Dict[str, Any] = None,
        importance_score: float = 1.0
    ) -> str:
        """Add memory"""
        memory_id = hashlib.md5(
            f"{content}{datetime.now().isoformat()}".encode()
        ).hexdigest()

        embedding = self._get_embedding(content)

        entry = MemoryEntry(
            id=memory_id,
            content=content,
            memory_type=memory_type,
            metadata=metadata or {},
            embedding=embedding,
            importance_score=importance_score
        )

        if self.collection:
            try:
                self.collection.add(
                    ids=[memory_id],
                    embeddings=[embedding],
                    documents=[content],
                    metadatas=[{
                        "memory_type": memory_type,
                        "timestamp": entry.timestamp.isoformat(),
                        "importance_score": importance_score,
                        **(metadata or {})
                    }]
                )
            except Exception as e:
                print(f"[VectorStore] ChromaDB store failed: {e}")
                self._memory_buffer[memory_id] = entry
        else:
            self._memory_buffer[memory_id] = entry

        print(f"[VectorStore] Added memory: {memory_id[:8]}... ({memory_type})")
        return memory_id

    async def search(
        self,
        query: str,
        memory_type: str = None,
        top_k: int = 5,
        min_similarity: float = 0.5
    ) -> List[Dict[str, Any]]:
        """Semantic search memory"""
        query_embedding = self._get_embedding(query)
        results = []

        if self.collection:
            try:
                where_filter = {"memory_type": memory_type} if memory_type else None

                db_results = self.collection.query(
                    query_embeddings=[query_embedding],
                    n_results=top_k,
                    where=where_filter
                )

                for i, doc_id in enumerate(db_results["ids"][0]):
                    distance = db_results["distances"][0][i]
                    similarity = 1 - distance

                    if similarity >= min_similarity:
                        results.append({
                            "id": doc_id,
                            "content": db_results["documents"][0][i],
                            "similarity": similarity,
                            "metadata": db_results["metadatas"][0][i]
                        })
            except Exception as e:
                print(f"[VectorStore] ChromaDB search failed: {e}")

        # Fallback to memory buffer
        if len(results) < top_k:
            buffer_results = self._search_buffer(
                query_embedding, memory_type, top_k - len(results), min_similarity
            )
            results.extend(buffer_results)

        results.sort(key=lambda x: x["similarity"], reverse=True)
        return results[:top_k]

    def _search_buffer(
        self,
        query_embedding: List[float],
        memory_type: Optional[str],
        top_k: int,
        min_similarity: float
    ) -> List[Dict[str, Any]]:
        """Search memory buffer"""
        results = []

        for entry in self._memory_buffer.values():
            if memory_type and entry.memory_type != memory_type:
                continue

            similarity = self._cosine_similarity(query_embedding, entry.embedding)

            if similarity >= min_similarity:
                results.append({
                    "id": entry.id,
                    "content": entry.content,
                    "similarity": similarity,
                    "metadata": {
                        "memory_type": entry.memory_type,
                        "timestamp": entry.timestamp.isoformat(),
                        "importance_score": entry.importance_score
                    }
                })

        results.sort(key=lambda x: x["similarity"], reverse=True)
        return results[:top_k]

    def _cosine_similarity(self, a: List[float], b: List[float]) -> float:
        """Calculate cosine similarity"""
        if NUMPY_AVAILABLE:
            import numpy as np
            a_array = np.array(a)
            b_array = np.array(b)
            return float(np.dot(a_array, b_array) / (np.linalg.norm(a_array) * np.linalg.norm(b_array)))
        else:
            # Pure Python
            dot = sum(x * y for x, y in zip(a, b))
            mag_a = sum(x**2 for x in a) ** 0.5
            mag_b = sum(x**2 for x in b) ** 0.5
            return dot / (mag_a * mag_b) if mag_a > 0 and mag_b > 0 else 0

    async def get_recent_memories(
        self,
        memory_type: str = None,
        limit: int = 10,
        hours: int = None
    ) -> List[Dict[str, Any]]:
        """Get recent memories"""
        memories = []

        for entry in self._memory_buffer.values():
            if memory_type and entry.memory_type != memory_type:
                continue

            if hours:
                from datetime import timedelta
                if datetime.now() - entry.timestamp > timedelta(hours=hours):
                    continue

            memories.append({
                "id": entry.id,
                "content": entry.content,
                "metadata": {
                    "memory_type": entry.memory_type,
                    "importance_score": entry.importance_score
                },
                "timestamp": entry.timestamp
            })

        memories.sort(key=lambda x: x["timestamp"], reverse=True)
        return memories[:limit]

    def get_stats(self) -> Dict[str, Any]:
        """Get storage stats"""
        return {
            "chroma_available": self.collection is not None,
            "buffer_size": len(self._memory_buffer),
            "collection_name": self.collection_name
        }


# Global instance
vector_store = VectorStore()
