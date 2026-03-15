"""
neo4j_client.py
---------------
Neo4j Aura Free への接続・書き込みラッパー。

環境変数:
    NEO4J_URI      : bolt/neo4j+s URI (例: neo4j+s://xxxxxxxx.databases.neo4j.io)
    NEO4J_USERNAME : ユーザー名 (デフォルト: neo4j)
    NEO4J_PASSWORD : パスワード
"""

import os
import json
from typing import Optional, Set
from datetime import datetime, timezone

# dotenv があれば自動読み込み
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from neo4j import GraphDatabase


class Neo4jClient:
    """ナレッジグラフ 専用 Neo4j クライアント。"""

    # JSON文字列として保存するプロパティ（Cypherプロパティには文字列しか使えない大型フィールド）
    _JSON_PROPS = {"analysis_content", "emotion_history", "tags"}

    def __init__(
        self,
        uri: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
    ):
        self._uri = uri or os.getenv("NEO4J_URI", "")
        self._username = username or os.getenv("NEO4J_USERNAME", "neo4j")
        self._password = password or os.getenv("NEO4J_PASSWORD", "")
        if not self._uri or not self._password:
            raise ValueError(
                "NEO4J_URI と NEO4J_PASSWORD が未設定です。.env を確認してください。"
            )
        self._driver = GraphDatabase.driver(
            self._uri, auth=(self._username, self._password)
        )

    def close(self):
        self._driver.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    # ──────────────────────────────────────────
    # 書き込み
    # ──────────────────────────────────────────

    @staticmethod
    def _serialize_props(props: dict) -> dict:
        """大型フィールドをJSON文字列にシリアライズして Neo4j プロパティに変換する。"""
        result = {}
        for k, v in props.items():
            if v is None:
                continue
            if k in Neo4jClient._JSON_PROPS and not isinstance(v, str):
                result[k] = json.dumps(v, ensure_ascii=False)
            elif isinstance(v, (dict, list)):
                result[k] = json.dumps(v, ensure_ascii=False)
            else:
                result[k] = v
        return result

    def upsert_node(self, node: dict) -> None:
        """ノードを MERGE で投入する。既存なら指定プロパティを上書きする。"""
        nid = node.get("id")
        ntype = node.get("type", "Unknown")
        if not nid:
            return

        props = self._serialize_props({k: v for k, v in node.items() if k != "id"})

        with self._driver.session() as session:
            session.run(
                """
                MERGE (n:Node {id: $id})
                SET n += $props
                SET n:$(ntype)
                """,
                id=nid,
                props=props,
                ntype=ntype,
            )

    def upsert_node_batch(self, nodes: list) -> int:
        """ノードを一括 MERGE する。処理件数を返す。"""
        with self._driver.session() as session:
            for node in nodes:
                nid = node.get("id")
                ntype = node.get("type", "Unknown")
                if not nid:
                    continue
                props = self._serialize_props(
                    {k: v for k, v in node.items() if k != "id"}
                )
                session.run(
                    """
                    MERGE (n:Node {id: $id})
                    SET n += $props
                    WITH n
                    CALL apoc.create.addLabels(n, [$ntype]) YIELD node
                    RETURN node
                    """,
                    id=nid,
                    props=props,
                    ntype=ntype,
                )
        return len(nodes)

    def upsert_node_batch_simple(self, nodes: list) -> int:
        """APOC不要版: ノードを一括 MERGE する。ラベルは固定 :Node のみ。"""
        count = 0
        with self._driver.session() as session:
            for node in nodes:
                nid = node.get("id")
                if not nid:
                    continue
                props = self._serialize_props(
                    {k: v for k, v in node.items() if k != "id"}
                )
                session.run(
                    """
                    MERGE (n:Node {id: $id})
                    SET n += $props
                    """,
                    id=nid,
                    props=props,
                )
                count += 1
        return count

    def upsert_edge_batch_simple(self, edges: list) -> int:
        """エッジを一括 MERGE する。リレーションタイプは固定 RELATED_TO。
        
        エッジの type プロパティは rel.type に保持する。
        """
        count = 0
        with self._driver.session() as session:
            for edge in edges:
                source = edge.get("source")
                target = edge.get("target")
                rel_type = edge.get("type", "RELATED_TO")
                if not source or not target or source == target:
                    continue
                props = self._serialize_props(
                    {k: v for k, v in edge.items() if k not in ("source", "target")}
                )
                session.run(
                    """
                    MATCH (a:Node {id: $source})
                    MATCH (b:Node {id: $target})
                    MERGE (a)-[r:RELATED_TO {source: $source, target: $target, rel_type: $rel_type}]->(b)
                    SET r += $props
                    """,
                    source=source,
                    target=target,
                    rel_type=rel_type,
                    props=props,
                )
                count += 1
        return count

    # ──────────────────────────────────────────
    # 感情減衰
    # ──────────────────────────────────────────

    def apply_emotion_decay_cypher(
        self,
        daily_node_ids: Set[str],
        today_str: str,
        decay_rates: Optional[dict] = None,
    ) -> None:
        """感情ノードの active_sentiment をCypherで減衰させる。

        Args:
            daily_node_ids: 今日言及された全ノードID集合
            today_str: YYYY-MM-DD 形式の今日の日付
            decay_rates: カテゴリ別の減衰係数。省略時はデフォルト値を使用。
        """
        if decay_rates is None:
            decay_rates = {
                "喜び": 0.30,
                "達成感": 0.15,
                "不安": 0.05,
                "怒り": 0.20,
                "その他": 0.10,
            }

        mentioned_ids = list(daily_node_ids)

        with self._driver.session() as session:
            # 今日言及された感情ノード → active_sentiment を sentiment 水準に戻す
            session.run(
                """
                MATCH (n:Node)
                WHERE n.type = '感情' AND n.id IN $mentioned_ids
                SET n.active_sentiment = n.sentiment
                """,
                mentioned_ids=mentioned_ids,
            )

            # 今日言及されなかった感情ノード → カテゴリ別係数で減衰
            for category, rate in decay_rates.items():
                session.run(
                    """
                    MATCH (n:Node)
                    WHERE n.type = '感情'
                      AND n.emotion_category = $category
                      AND NOT n.id IN $mentioned_ids
                    SET n.active_sentiment = round(
                        coalesce(n.active_sentiment, n.sentiment, 0.0) * (1.0 - $rate),
                        4
                    )
                    """,
                    category=category,
                    rate=rate,
                    mentioned_ids=mentioned_ids,
                )

    # ──────────────────────────────────────────
    # ウェイト減衰
    # ──────────────────────────────────────────

    def apply_weight_decay_cypher(
        self,
        daily_node_ids: Set[str],
        daily_edge_keys: Set[str],
        decay_per_day: float = 0.05,
        min_weight: float = 0.1,
    ) -> None:
        """言及されなかったノード・エッジのウェイトを減衰させる。"""
        mentioned_ids = list(daily_node_ids)

        with self._driver.session() as session:
            # ノード減衰（日記型除く）
            session.run(
                """
                MATCH (n:Node)
                WHERE NOT n.id IN $mentioned_ids
                  AND n.type <> '日記'
                SET n.weight = CASE
                    WHEN coalesce(n.weight, 1.0) - $decay < $min_weight THEN $min_weight
                    ELSE round(coalesce(n.weight, 1.0) - $decay, 4)
                END
                """,
                mentioned_ids=mentioned_ids,
                decay=decay_per_day,
                min_weight=min_weight,
            )

    # ──────────────────────────────────────────
    # ユーティリティ
    # ──────────────────────────────────────────

    def count_nodes(self) -> int:
        with self._driver.session() as session:
            result = session.run("MATCH (n:Node) RETURN count(n) AS cnt")
            return result.single()["cnt"]

    def count_edges(self) -> int:
        with self._driver.session() as session:
            result = session.run(
                "MATCH (:Node)-[r:RELATED_TO]->(:Node) RETURN count(r) AS cnt"
            )
            return result.single()["cnt"]

    def test_connection(self) -> bool:
        """接続テスト。成功すれば True を返す。"""
        try:
            with self._driver.session() as session:
                session.run("RETURN 1 AS ok").single()
            return True
        except Exception as e:
            print(f"❌ 接続失敗: {e}")
            return False


if __name__ == "__main__":
    client = Neo4jClient()
    if client.test_connection():
        print("✅ Neo4j Aura Free への接続に成功しました！")
        print(f"   現在のノード数: {client.count_nodes()}")
        print(f"   現在のエッジ数: {client.count_edges()}")
    client.close()
