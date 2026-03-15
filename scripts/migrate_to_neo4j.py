"""
migrate_to_neo4j.py
-------------------
knowledge_graph.jsonld の全ノード・エッジを Neo4j Aura Free へ一括移行する。
MERGE ベースの冪等実装のため、何度実行しても重複しない。
"""

import os
import sys
import json

# スクリプトのディレクトリをパスに追加
sys.path.insert(0, os.path.dirname(__file__))

from neo4j_client import Neo4jClient

GRAPH_FILE = os.path.join(
    os.path.dirname(__file__), "..", "knowledge_graph.jsonld"
)


def migrate(graph_path: str = GRAPH_FILE, dry_run: bool = False):
    print(f"📂 グラフファイルを読み込み中: {graph_path}")
    with open(graph_path, "r", encoding="utf-8") as f:
        graph = json.load(f)

    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])

    print(f"   ノード: {len(nodes)}件 / エッジ: {len(edges)}件")

    if dry_run:
        print("🔍 ドライランモード: Neo4jへの書き込みはスキップします。")
        return

    print("🔗 Neo4j Aura Free に接続中...")
    client = Neo4jClient()

    if not client.test_connection():
        print("❌ 接続失敗。処理を中断します。")
        return

    # ── ノード移行 ──
    print(f"\n📤 ノードを移行中 ({len(nodes)}件)...")
    node_count = client.upsert_node_batch_simple(nodes)
    print(f"   ✅ {node_count}件のノードを投入しました。")

    # ── エッジ移行 ──
    print(f"\n📤 エッジを移行中 ({len(edges)}件)...")
    edge_count = client.upsert_edge_batch_simple(edges)
    print(f"   ✅ {edge_count}件のエッジを投入しました。")

    # ── 検証 ──
    print("\n🔍 移行後のカウント検証...")
    neo4j_nodes = client.count_nodes()
    neo4j_edges = client.count_edges()
    print(f"   Neo4j ノード数: {neo4j_nodes} (期待値: {len(nodes)})")
    print(f"   Neo4j エッジ数: {neo4j_edges} (期待値: {len(edges)})")

    if neo4j_nodes == len(nodes):
        print("   ✅ ノード数一致")
    else:
        print(f"   ⚠️  ノード数に差異あり: {abs(neo4j_nodes - len(nodes))}件")

    if neo4j_edges == len(edges):
        print("   ✅ エッジ数一致")
    else:
        print(f"   ⚠️  エッジ数に差異あり: {abs(neo4j_edges - len(edges))}件")

    client.close()
    print("\n🎉 移行完了！")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="knowledge_graph.jsonld を Neo4j に移行する")
    parser.add_argument(
        "--graph", default=GRAPH_FILE, help="グラフJSONファイルのパス"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Neo4jへの書き込みをスキップして件数のみ確認"
    )
    args = parser.parse_args()
    migrate(args.graph, args.dry_run)
