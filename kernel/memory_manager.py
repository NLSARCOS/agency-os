#!/usr/bin/env python3
"""
Agency OS v5.0.0 — Memory Manager

Manages agent memory at two levels:
- Short-term: Conversation context per agent (in DB)
- Long-term: Shared knowledge base with TF-IDF similarity search

Inspired by CrewAI memory + LangGraph state persistence.
No external vector DB required — uses built-in TF-IDF for similarity.
"""

from __future__ import annotations

import json
import logging
import math
import re
import threading
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from kernel.state_manager import get_state

logger = logging.getLogger("agency.memory")


@dataclass
class MemoryEntry:
    """A single memory entry."""

    id: int = 0
    agent_id: str = ""
    role: str = ""  # user, assistant, system, knowledge
    content: str = ""
    mission_id: int | None = None
    timestamp: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    relevance: float = 0.0  # For search results


@dataclass
class KnowledgeEntry:
    """A long-term knowledge item shared across agents."""

    id: int = 0
    topic: str = ""
    content: str = ""
    source_agent: str = ""
    tags: list[str] = field(default_factory=list)
    access_count: int = 0
    created_at: str = ""
    updated_at: str = ""


# ── TF-IDF Similarity (No External Deps) ─────────────────────


def _tokenize(text: str) -> list[str]:
    """Simple word tokenizer."""
    text = text.lower()
    text = re.sub(r"[^\w\s]", " ", text)
    return [w for w in text.split() if len(w) > 2]


def _tf(tokens: list[str]) -> dict[str, float]:
    """Term frequency."""
    counts = Counter(tokens)
    total = len(tokens) or 1
    return {t: c / total for t, c in counts.items()}


def _idf(corpus_tokens: list[list[str]]) -> dict[str, float]:
    """Inverse document frequency."""
    n = len(corpus_tokens) or 1
    df: dict[str, int] = Counter()
    for tokens in corpus_tokens:
        for t in set(tokens):
            df[t] += 1
    return {t: math.log(n / (1 + count)) for t, count in df.items()}


def _tfidf_similarity(query: str, documents: list[str]) -> list[float]:
    """Compute TF-IDF cosine similarity between query and documents."""
    if not documents:
        return []

    query_tokens = _tokenize(query)
    doc_tokens = [_tokenize(d) for d in documents]
    all_tokens = [query_tokens] + doc_tokens

    idf_scores = _idf(all_tokens)

    # Query TF-IDF vector
    query_tf = _tf(query_tokens)
    query_vec = {t: tf_val * idf_scores.get(t, 0) for t, tf_val in query_tf.items()}

    similarities = []
    for tokens in doc_tokens:
        doc_tf = _tf(tokens)
        doc_vec = {t: tf_val * idf_scores.get(t, 0) for t, tf_val in doc_tf.items()}

        # Cosine similarity
        all_terms = set(query_vec) | set(doc_vec)
        dot = sum(query_vec.get(t, 0) * doc_vec.get(t, 0) for t in all_terms)
        mag_q = math.sqrt(sum(v**2 for v in query_vec.values())) or 1
        mag_d = math.sqrt(sum(v**2 for v in doc_vec.values())) or 1
        similarities.append(dot / (mag_q * mag_d))

    return similarities


class MemoryManager:
    """
    Manages agent memory across two tiers.

    Short-term: Per-agent conversation memory (last N exchanges)
    Long-term: Shared knowledge base with TF-IDF similarity search
    """

    _instance: MemoryManager | None = None
    _lock = threading.Lock()

    def __new__(cls) -> MemoryManager:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False  # type: ignore
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:  # type: ignore
            return
        self._initialized = True
        self._state = get_state()
        self._ensure_knowledge_table()

    def _ensure_knowledge_table(self) -> None:
        """Create knowledge table if not exists."""
        self._state._conn.executescript("""
            CREATE TABLE IF NOT EXISTS knowledge (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                topic TEXT NOT NULL,
                content TEXT NOT NULL,
                source_agent TEXT DEFAULT '',
                tags TEXT DEFAULT '[]',
                access_count INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_knowledge_topic
                ON knowledge(topic);
            CREATE INDEX IF NOT EXISTS idx_knowledge_source
                ON knowledge(source_agent);
        """)
        self._state._conn.commit()

    # ── Short-Term Memory (Per-Agent) ─────────────────────────

    def store(
        self,
        agent_id: str,
        role: str,
        content: str,
        mission_id: int | None = None,
        metadata: dict | None = None,
    ) -> int:
        """Store a memory entry for an agent."""
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            cur = self._state._conn.execute(
                """INSERT INTO agent_memory
                   (agent_id, role, content, mission_id, timestamp, metadata)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    agent_id,
                    role,
                    content[:2000],
                    mission_id,
                    now,
                    json.dumps(metadata or {}),
                ),
            )
            self._state._conn.commit()
            return cur.lastrowid  # type: ignore

    def recall(
        self,
        agent_id: str,
        limit: int = 20,
        mission_id: int | None = None,
    ) -> list[MemoryEntry]:
        """Recall recent memory for an agent."""
        if mission_id:
            rows = self._state._conn.execute(
                """SELECT * FROM agent_memory
                   WHERE agent_id = ? AND mission_id = ?
                   ORDER BY timestamp DESC LIMIT ?""",
                (agent_id, mission_id, limit),
            ).fetchall()
        else:
            rows = self._state._conn.execute(
                """SELECT * FROM agent_memory
                   WHERE agent_id = ?
                   ORDER BY timestamp DESC LIMIT ?""",
                (agent_id, limit),
            ).fetchall()

        return [
            MemoryEntry(
                id=r["id"],
                agent_id=r["agent_id"],
                role=r["role"],
                content=r["content"],
                mission_id=r["mission_id"],
                timestamp=r["timestamp"],
                metadata=json.loads(r["metadata"] or "{}"),
            )
            for r in reversed(rows)  # Chronological order
        ]

    def search_memory(
        self,
        agent_id: str,
        query: str,
        limit: int = 10,
    ) -> list[MemoryEntry]:
        """Search agent memory by relevance using TF-IDF."""
        rows = self._state._conn.execute(
            """SELECT * FROM agent_memory
               WHERE agent_id = ?
               ORDER BY timestamp DESC LIMIT 200""",
            (agent_id,),
        ).fetchall()

        if not rows:
            return []

        contents = [r["content"] for r in rows]
        similarities = _tfidf_similarity(query, contents)

        # Pair and sort by relevance
        scored = sorted(
            zip(rows, similarities),
            key=lambda x: x[1],
            reverse=True,
        )

        return [
            MemoryEntry(
                id=r["id"],
                agent_id=r["agent_id"],
                role=r["role"],
                content=r["content"],
                mission_id=r["mission_id"],
                timestamp=r["timestamp"],
                metadata=json.loads(r["metadata"] or "{}"),
                relevance=round(sim, 3),
            )
            for r, sim in scored[:limit]
            if sim > 0.05  # Minimum relevance threshold
        ]

    def clear_memory(self, agent_id: str) -> int:
        """Clear all memory for an agent."""
        with self._lock:
            cur = self._state._conn.execute(
                "DELETE FROM agent_memory WHERE agent_id = ?",
                (agent_id,),
            )
            self._state._conn.commit()
            return cur.rowcount

    def count_memories(self, agent_id: str) -> int:
        row = self._state._conn.execute(
            "SELECT COUNT(*) as cnt FROM agent_memory WHERE agent_id = ?",
            (agent_id,),
        ).fetchone()
        return row["cnt"] if row else 0

    # ── Long-Term Knowledge Base ──────────────────────────────

    def learn(
        self,
        topic: str,
        content: str,
        source_agent: str = "",
        tags: list[str] | None = None,
    ) -> int:
        """Store knowledge in the long-term shared knowledge base."""
        now = datetime.now(timezone.utc).isoformat()

        # Check for existing knowledge on same topic
        existing = self._state._conn.execute(
            "SELECT id FROM knowledge WHERE topic = ? AND source_agent = ?",
            (topic, source_agent),
        ).fetchone()

        if existing:
            # Update existing
            with self._lock:
                self._state._conn.execute(
                    """UPDATE knowledge
                       SET content = ?, tags = ?, updated_at = ?
                       WHERE id = ?""",
                    (content[:5000], json.dumps(tags or []), now, existing["id"]),
                )
                self._state._conn.commit()
                return existing["id"]
        else:
            with self._lock:
                cur = self._state._conn.execute(
                    """INSERT INTO knowledge
                       (topic, content, source_agent, tags, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        topic,
                        content[:5000],
                        source_agent,
                        json.dumps(tags or []),
                        now,
                        now,
                    ),
                )
                self._state._conn.commit()
                return cur.lastrowid  # type: ignore

    def query_knowledge(
        self,
        query: str,
        limit: int = 5,
        tags: list[str] | None = None,
    ) -> list[KnowledgeEntry]:
        """Search knowledge base by relevance."""
        if tags:
            # Filter by tags first
            rows = self._state._conn.execute(
                "SELECT * FROM knowledge ORDER BY updated_at DESC LIMIT 500"
            ).fetchall()
            rows = [
                r for r in rows if any(t in json.loads(r["tags"] or "[]") for t in tags)
            ]
        else:
            rows = self._state._conn.execute(
                "SELECT * FROM knowledge ORDER BY updated_at DESC LIMIT 500"
            ).fetchall()

        if not rows:
            return []

        # TF-IDF search
        contents = [f"{r['topic']} {r['content']}" for r in rows]
        similarities = _tfidf_similarity(query, contents)

        scored = sorted(
            zip(rows, similarities),
            key=lambda x: x[1],
            reverse=True,
        )

        results = []
        for r, sim in scored[:limit]:
            if sim > 0.03:
                # Increment access count
                self._state._conn.execute(
                    "UPDATE knowledge SET access_count = access_count + 1 WHERE id = ?",
                    (r["id"],),
                )
                results.append(
                    KnowledgeEntry(
                        id=r["id"],
                        topic=r["topic"],
                        content=r["content"],
                        source_agent=r["source_agent"],
                        tags=json.loads(r["tags"] or "[]"),
                        access_count=r["access_count"],
                        created_at=r["created_at"],
                        updated_at=r["updated_at"],
                    )
                )

        if results:
            self._state._conn.commit()
        return results

    def get_all_knowledge(self, limit: int = 50) -> list[KnowledgeEntry]:
        """Get all knowledge entries ordered by access count."""
        rows = self._state._conn.execute(
            """SELECT * FROM knowledge
               ORDER BY access_count DESC, updated_at DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
        return [
            KnowledgeEntry(
                id=r["id"],
                topic=r["topic"],
                content=r["content"][:200],
                source_agent=r["source_agent"],
                tags=json.loads(r["tags"] or "[]"),
                access_count=r["access_count"],
                created_at=r["created_at"],
                updated_at=r["updated_at"],
            )
            for r in rows
        ]

    # ── Cross-Agent Knowledge Sharing ─────────────────────────

    def share_insight(
        self,
        from_agent: str,
        topic: str,
        insight: str,
        tags: list[str] | None = None,
    ) -> int:
        """Agent shares an insight to the shared knowledge base."""
        knowledge_id = self.learn(
            topic=topic,
            content=f"[Insight from {from_agent}] {insight}",
            source_agent=from_agent,
            tags=tags,
        )
        logger.info(
            "Agent '%s' shared knowledge on '%s' (id=%d)",
            from_agent,
            topic,
            knowledge_id,
        )
        return knowledge_id

    def get_context_for_agent(
        self,
        agent_id: str,
        task: str,
        max_memory: int = 5,
        max_knowledge: int = 3,
    ) -> str:
        """
        Build context string for an agent combining:
        1. Recent short-term memory
        2. Relevant long-term knowledge
        """
        parts = []

        # Short-term memory
        memories = self.recall(agent_id, limit=max_memory)
        if memories:
            parts.append("## Recent Memory")
            for m in memories:
                parts.append(f"[{m.role}] {m.content[:300]}")

        # Long-term knowledge
        knowledge = self.query_knowledge(task, limit=max_knowledge)
        if knowledge:
            parts.append("\n## Relevant Knowledge")
            for k in knowledge:
                parts.append(f"[{k.topic}] {k.content[:300]}")

        return "\n".join(parts) if parts else ""

    # ── Stats ─────────────────────────────────────────────────

    def get_stats(self) -> dict:
        memory_count = self._state._conn.execute(
            "SELECT COUNT(*) as cnt FROM agent_memory"
        ).fetchone()["cnt"]

        knowledge_count = self._state._conn.execute(
            "SELECT COUNT(*) as cnt FROM knowledge"
        ).fetchone()["cnt"]

        agents_with_memory = self._state._conn.execute(
            "SELECT DISTINCT agent_id FROM agent_memory"
        ).fetchall()

        return {
            "total_memories": memory_count,
            "total_knowledge": knowledge_count,
            "agents_with_memory": [r["agent_id"] for r in agents_with_memory],
        }


def get_memory_manager() -> MemoryManager:
    return MemoryManager()
