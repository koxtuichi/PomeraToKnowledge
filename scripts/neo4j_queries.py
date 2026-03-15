"""
neo4j_queries.py
----------------
感情トレンド推移・人物間タスク依存関係などの分析クエリ集。
Neo4jClient を受け取り、Cypherクエリを実行して結果を返す。
"""

from typing import Optional
import json


def emotion_trend(client, emotion_category: Optional[str] = None, days: int = 30) -> list:
    """感情の active_sentiment 時系列推移を取得する。

    Args:
        client: Neo4jClient インスタンス
        emotion_category: 対象感情カテゴリ (None で全カテゴリ)
        days: 取得するhistory履歴の最大日数（現在は全件取得後にクライアント側でフィルタ）

    Returns:
        [{"id": ..., "label": ..., "category": ..., "history": [...]}]
    """
    with client._driver.session() as session:
        if emotion_category:
            result = session.run(
                """
                MATCH (n:Node)
                WHERE n.type = '感情' AND n.emotion_category = $category
                RETURN n.id AS id, n.label AS label,
                       n.emotion_category AS category,
                       n.emotion_history AS history_raw,
                       n.trend AS trend,
                       n.peak_sentiment AS peak,
                       n.active_sentiment AS active
                ORDER BY n.id
                """,
                category=emotion_category,
            )
        else:
            result = session.run(
                """
                MATCH (n:Node)
                WHERE n.type = '感情'
                RETURN n.id AS id, n.label AS label,
                       n.emotion_category AS category,
                       n.emotion_history AS history_raw,
                       n.trend AS trend,
                       n.peak_sentiment AS peak,
                       n.active_sentiment AS active
                ORDER BY n.emotion_category, n.id
                """
            )

        rows = []
        for record in result:
            history_raw = record["history_raw"]
            history = []
            if isinstance(history_raw, str):
                try:
                    history = json.loads(history_raw)
                except Exception:
                    history = []
            elif isinstance(history_raw, list):
                history = history_raw

            rows.append({
                "id": record["id"],
                "label": record["label"],
                "category": record["category"],
                "trend": record["trend"],
                "peak": record["peak"],
                "active": record["active"],
                "history": history,
            })

        return rows


def task_dependencies_by_person(client, person_name: str) -> dict:
    """人物に紐づくタスクと、そのタスクにかかる制約・原動力を返す。

    Args:
        client: Neo4jClient インスタンス
        person_name: 人物ラベル (例: '江頭さん')

    Returns:
        {
          "person": {"id": ..., "label": ...},
          "tasks": [
            {
              "task": {"id": ..., "label": ..., "status": ...},
              "constraints": [...],
              "motivators": [...]
            }
          ]
        }
    """
    with client._driver.session() as session:
        # 人物ノードを取得
        person_result = session.run(
            """
            MATCH (p:Node {type: '人物'})
            WHERE p.label = $name OR p.id CONTAINS $name
            RETURN p.id AS id, p.label AS label
            LIMIT 1
            """,
            name=person_name,
        )
        person_record = person_result.single()
        if not person_record:
            return {"person": None, "tasks": []}

        person = {"id": person_record["id"], "label": person_record["label"]}

        # その人物に関連するタスク (対象にする / 言及する)
        tasks_result = session.run(
            """
            MATCH (t:Node {type: 'タスク'})-[r:RELATED_TO]->(p:Node {id: $person_id})
            RETURN t.id AS tid, t.label AS tlabel, t.status AS tstatus, t.detail AS tdetail
            UNION
            MATCH (d:Node)-[r:RELATED_TO]->(t:Node {type: 'タスク'})
            WHERE d.type = '日記' AND t.id IN [
                (t2:Node)-[r2:RELATED_TO]->(p2:Node {id: $person_id}) | t2.id
            ]
            RETURN t.id AS tid, t.label AS tlabel, t.status AS tstatus, t.detail AS tdetail
            """,
            person_id=person["id"],
        )

        tasks = []
        seen_task_ids = set()
        for tr in tasks_result:
            tid = tr["tid"]
            if tid in seen_task_ids:
                continue
            seen_task_ids.add(tid)

            # 制約
            constraints_result = session.run(
                """
                MATCH (c:Node {type: '制約'})-[r:RELATED_TO]->(t:Node {id: $tid})
                WHERE r.rel_type = '阻害する'
                RETURN c.id AS cid, c.label AS clabel, c.constraint_type AS ctype
                """,
                tid=tid,
            )
            constraints = [
                {"id": r["cid"], "label": r["clabel"], "type": r["ctype"]}
                for r in constraints_result
            ]

            # 原動力
            motivators_result = session.run(
                """
                MATCH (m:Node)-[r:RELATED_TO]->(t:Node {id: $tid})
                WHERE r.rel_type = '原動力になる'
                RETURN m.id AS mid, m.label AS mlabel, m.type AS mtype
                """,
                tid=tid,
            )
            motivators = [
                {"id": r["mid"], "label": r["mlabel"], "type": r["mtype"]}
                for r in motivators_result
            ]

            tasks.append({
                "task": {
                    "id": tid,
                    "label": tr["tlabel"],
                    "status": tr["tstatus"],
                    "detail": tr["tdetail"],
                },
                "constraints": constraints,
                "motivators": motivators,
            })

        return {"person": person, "tasks": tasks}


def gravity_heatmap(client) -> list:
    """制約ノードが阻害しているタスク一覧と重力スコア (エッジのweight)。

    Returns:
        [{"constraint": ..., "tasks": [...], "total_gravity": float}]
    """
    with client._driver.session() as session:
        result = session.run(
            """
            MATCH (c:Node {type: '制約'})-[r:RELATED_TO]->(t:Node {type: 'タスク'})
            WHERE r.rel_type = '阻害する'
            RETURN c.id AS cid,
                   c.label AS clabel,
                   c.constraint_type AS ctype,
                   t.id AS tid,
                   t.label AS tlabel,
                   t.status AS tstatus,
                   coalesce(r.weight, 1.0) AS edge_weight
            ORDER BY edge_weight DESC
            """
        )

        constraint_map = {}
        for record in result:
            cid = record["cid"]
            if cid not in constraint_map:
                constraint_map[cid] = {
                    "constraint": {
                        "id": cid,
                        "label": record["clabel"],
                        "type": record["ctype"],
                    },
                    "tasks": [],
                    "total_gravity": 0.0,
                }
            constraint_map[cid]["tasks"].append({
                "id": record["tid"],
                "label": record["tlabel"],
                "status": record["tstatus"],
                "edge_weight": record["edge_weight"],
            })
            constraint_map[cid]["total_gravity"] += record["edge_weight"]

        return sorted(
            list(constraint_map.values()),
            key=lambda x: x["total_gravity"],
            reverse=True,
        )


def cross_diary_timeline(client, node_id: str) -> list:
    """特定ノードが複数日記にわたって言及された時系列を返す。

    Args:
        client: Neo4jClient インスタンス
        node_id: 追跡対象のノードID (例: 'タスク:絵の制作とYouTube投稿')

    Returns:
        [{"date": "YYYY-MM-DD", "diary_id": ..., "diary_label": ..., "edge_label": ...}]
    """
    with client._driver.session() as session:
        result = session.run(
            """
            MATCH (d:Node)-[r:RELATED_TO]->(n:Node {id: $node_id})
            WHERE d.type = '日記' AND r.rel_type = '言及する'
            RETURN d.date AS date,
                   d.id AS diary_id,
                   d.label AS diary_label,
                   r.label AS edge_label
            ORDER BY d.date ASC
            """,
            node_id=node_id,
        )

        return [
            {
                "date": r["date"],
                "diary_id": r["diary_id"],
                "diary_label": r["diary_label"],
                "edge_label": r["edge_label"],
            }
            for r in result
        ]


def list_all_persons(client) -> list:
    """人物ノード一覧を返す。"""
    with client._driver.session() as session:
        result = session.run(
            """
            MATCH (n:Node {type: '人物'})
            RETURN n.id AS id, n.label AS label, n.detail AS detail
            ORDER BY n.label
            """
        )
        return [{"id": r["id"], "label": r["label"], "detail": r["detail"]} for r in result]


def list_active_tasks(client) -> list:
    """未完了タスク一覧を重力スコア付きで返す。"""
    with client._driver.session() as session:
        result = session.run(
            """
            MATCH (t:Node)
            WHERE t.type = 'タスク' AND t.status <> '完了'
            OPTIONAL MATCH (c:Node {type: '制約'})-[r:RELATED_TO]->(t)
            WHERE r.rel_type = '阻害する'
            RETURN t.id AS id,
                   t.label AS label,
                   t.status AS status,
                   t.context AS context,
                   count(c) AS constraint_count,
                   sum(coalesce(r.weight, 1.0)) AS gravity_score
            ORDER BY gravity_score DESC
            """
        )
        return [
            {
                "id": r["id"],
                "label": r["label"],
                "status": r["status"],
                "context": r["context"],
                "constraint_count": r["constraint_count"],
                "gravity_score": r["gravity_score"],
            }
            for r in result
        ]


if __name__ == "__main__":
    from neo4j_client import Neo4jClient

    client = Neo4jClient()
    print("\n=== 感情トレンド (不安) ===")
    trends = emotion_trend(client, "不安")
    for t in trends:
        print(f"  {t['label']}: active={t['active']}, trend={t['trend']}, history={len(t['history'])}件")

    print("\n=== 重力ヒートマップ ===")
    heatmap = gravity_heatmap(client)
    for h in heatmap[:5]:
        print(f"  [{h['constraint']['label']}] total_gravity={h['total_gravity']:.1f} → {[t['label'] for t in h['tasks']]}")

    print("\n=== アクティブなタスク ===")
    tasks = list_active_tasks(client)
    for t in tasks[:5]:
        print(f"  [{t['status']}] {t['label']} (重力スコア: {t['gravity_score']:.1f})")

    client.close()
