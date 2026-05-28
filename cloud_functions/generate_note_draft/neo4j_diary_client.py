"""Neo4j-only diary reader for the note draft generator."""

from __future__ import annotations

import os
import uuid
from typing import Any

from neo4j import GraphDatabase


class Neo4jDiaryClient:
    def __init__(self) -> None:
        self.uri = os.environ.get("NEO4J_URI", "")
        self.username = os.environ.get("NEO4J_USERNAME", "neo4j")
        self.password = os.environ.get("NEO4J_PASSWORD", "")
        self.database = os.environ.get("NEO4J_DATABASE", "").strip() or None
        if not self.uri or not self.password:
            raise ValueError("NEO4J_URI and NEO4J_PASSWORD are required")
        self.driver = GraphDatabase.driver(
            self.uri, auth=(self.username, self.password)
        )

    def close(self) -> None:
        self.driver.close()

    def __enter__(self) -> "Neo4jDiaryClient":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def fetch_diaries(self, limit: int = 300) -> list[dict[str, Any]]:
        query = """
        MATCH (n:Node)
        WHERE (n.type IN ['日記', 'diary'] OR n.id STARTS WITH '日記:')
          AND n.date IS NOT NULL
          AND trim(coalesce(n.detail, '')) <> ''
          AND coalesce(n.detail, '') <> '今日の日記エントリ'
          AND trim(coalesce(n.analysis_content, '')) <> ''
        RETURN properties(n) AS diary
        ORDER BY coalesce(n.date, n.id) DESC
        LIMIT $limit
        """
        session_kwargs = {"database": self.database} if self.database else {}
        with self.driver.session(**session_kwargs) as session:
            result = session.run(query, limit=limit)
            return [dict(record["diary"]) for record in result]

    def fetch_diary(self, diary_id: str) -> dict[str, Any] | None:
        query = """
        MATCH (n:Node {id: $diary_id})
        WHERE n.type IN ['日記', 'diary'] OR n.id STARTS WITH '日記:'
        RETURN properties(n) AS diary
        LIMIT 1
        """
        session_kwargs = {"database": self.database} if self.database else {}
        with self.driver.session(**session_kwargs) as session:
            record = session.run(query, diary_id=diary_id).single()
            return dict(record["diary"]) if record else None

    def fetch_generation_blocked_ids(
        self, lane: str, prompt_version: str
    ) -> set[str]:
        query = """
        MATCH (g:NoteGeneration)-[:USES_DIARY]->(d:Node)
        WHERE g.lane = $lane
          AND g.prompt_version = $prompt_version
          AND g.status IN ['queued', 'drafting', 'drafted', 'generated', 'published']
        RETURN d.id AS diary_id
        """
        session_kwargs = {"database": self.database} if self.database else {}
        with self.driver.session(**session_kwargs) as session:
            result = session.run(
                query, lane=lane, prompt_version=prompt_version
            )
            return {record["diary_id"] for record in result if record["diary_id"]}

    def fetch_generation_theme_history(
        self,
        lane: str,
        prompt_version: str,
        limit: int = 100,
        exclude_diary_id: str | None = None,
    ) -> list[dict[str, Any]]:
        query = """
        MATCH (g:NoteGeneration)-[:USES_DIARY]->(d:Node)
        WHERE g.lane = $lane
          AND g.status IN ['queued', 'drafting', 'drafted', 'generated', 'published']
          AND ($exclude_diary_id IS NULL OR d.id <> $exclude_diary_id)
        RETURN properties(g) AS generation, properties(d) AS diary
        ORDER BY CASE WHEN g.prompt_version = $prompt_version THEN 0 ELSE 1 END,
                 coalesce(g.published_at, g.updated_at, g.created_at) DESC
        LIMIT $limit
        """
        session_kwargs = {"database": self.database} if self.database else {}
        with self.driver.session(**session_kwargs) as session:
            result = session.run(
                query,
                lane=lane,
                prompt_version=prompt_version,
                exclude_diary_id=exclude_diary_id,
                limit=limit,
            )
            return [
                {
                    "generation": dict(record["generation"]),
                    "diary": dict(record["diary"]),
                }
                for record in result
            ]

    def claim_generation(
        self,
        diary_id: str,
        lane: str,
        prompt_version: str,
        run_id: str,
    ) -> dict[str, Any]:
        dedupe_key = f"{lane}:{diary_id}:{prompt_version}"
        generation_id = str(uuid.uuid4())
        session_kwargs = {"database": self.database} if self.database else {}
        with self.driver.session(**session_kwargs) as session:
            with session.begin_transaction() as tx:
                existing = tx.run(
                    """
                    MATCH (g:NoteGeneration {dedupe_key: $dedupe_key})
                    RETURN g.id AS id, g.status AS status, g.run_id AS run_id
                    LIMIT 1
                    """,
                    dedupe_key=dedupe_key,
                ).single()
                if existing and existing["status"] in {
                    "queued",
                    "drafting",
                    "drafted",
                    "generated",
                    "published",
                }:
                    return {
                        "claimed": False,
                        "dedupe_key": dedupe_key,
                        "generation_id": existing["id"],
                        "status": existing["status"],
                        "run_id": existing["run_id"],
                    }
                updated = tx.run(
                    """
                    MATCH (d:Node {id: $diary_id})
                    MERGE (g:NoteGeneration {dedupe_key: $dedupe_key})
                    SET g.id = coalesce(g.id, $generation_id),
                        g.kind = 'note_candidate',
                        g.lane = $lane,
                        g.prompt_version = $prompt_version,
                        g.run_id = $run_id,
                        g.status = 'drafting',
                        g.updated_at = datetime(),
                        g.created_at = coalesce(g.created_at, datetime()),
                        g.attempt_count = coalesce(g.attempt_count, 0) + 1
                    MERGE (g)-[:USES_DIARY]->(d)
                    RETURN g.id AS id, g.status AS status, g.run_id AS run_id
                    """,
                    diary_id=diary_id,
                    dedupe_key=dedupe_key,
                    generation_id=generation_id,
                    lane=lane,
                    prompt_version=prompt_version,
                    run_id=run_id,
                ).single()
                return {
                    "claimed": True,
                    "dedupe_key": dedupe_key,
                    "generation_id": updated["id"],
                    "status": updated["status"],
                    "run_id": updated["run_id"],
                }

    def mark_generation(
        self,
        generation_id: str,
        status: str,
        props: dict[str, Any] | None = None,
    ) -> bool:
        payload = props or {}
        query = """
        MATCH (g:NoteGeneration {id: $generation_id})
        SET g.status = $status,
            g.updated_at = datetime(),
            g += $props
        """
        session_kwargs = {"database": self.database} if self.database else {}
        with self.driver.session(**session_kwargs) as session:
            result = session.run(
                query,
                generation_id=generation_id,
                status=status,
                props=payload,
            )
            summary = result.consume()
            return summary.counters.properties_set > 0

    def mark_published(
        self, diary_id: str, lane: str, prompt_version: str, note_url: str = ""
    ) -> bool:
        query = """
        MATCH (d:Node {id: $diary_id})
        MATCH (g:NoteGeneration)-[:USES_DIARY]->(d)
        WHERE g.lane = $lane AND g.prompt_version = $prompt_version
        SET g.status = 'published',
            g.published_at = datetime(),
            g.updated_at = datetime(),
            g.note_url = $note_url
        """
        session_kwargs = {"database": self.database} if self.database else {}
        with self.driver.session(**session_kwargs) as session:
            result = session.run(
                query,
                diary_id=diary_id,
                lane=lane,
                prompt_version=prompt_version,
                note_url=note_url,
            )
            summary = result.consume()
            return summary.counters.properties_set > 0
