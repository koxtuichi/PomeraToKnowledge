"""
export_neo4j_to_graphdata.py
-----------------------------
Neo4j Aura Free の全ノード・エッジを取り出して
graph_data.js の GRAPH_DATA 形式で書き出す。

使い方:
  python3 scripts/export_neo4j_to_graphdata.py
  python3 scripts/export_neo4j_to_graphdata.py --output /path/to/graph_data.js
"""

import os
import sys
import re
import json
import argparse
from datetime import datetime

# プロジェクトルート基準
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.join(SCRIPT_DIR, "..")
DEFAULT_OUTPUT = os.path.join(BASE_DIR, "graph_data.js")

# dotenv があれば .env を自動読み込み
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(BASE_DIR, ".env"))
except ImportError:
    # dotenv がない場合は .env を手動で読む
    env_path = os.path.join(BASE_DIR, ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

sys.path.insert(0, SCRIPT_DIR)
from neo4j_client import Neo4jClient


def write_graph_data_js(graph: dict, output_path: str) -> None:
    """graph_data.js に const GRAPH_DATA = {...}; 形式で書き出す。"""
    new_content = (
        "// GRAPH_DATA_START\n"
        f"const GRAPH_DATA = {json.dumps(graph, ensure_ascii=False, indent=2)};\n"
        "// GRAPH_DATA_END\n"
    )

    # 書き込み前に JSON として再パースして整合性チェック
    json.loads(
        re.search(r"const GRAPH_DATA = (\{.*\});", new_content, re.DOTALL).group(1)
    )

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(new_content)

    print(
        f"✅ graph_data.js を更新しました: "
        f"{len(graph['nodes'])} nodes, {len(graph['edges'])} edges"
    )
    print(f"   出力先: {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Neo4j → graph_data.js エクスポート"
    )
    parser.add_argument(
        "--output",
        default=DEFAULT_OUTPUT,
        help=f"出力先 (デフォルト: {DEFAULT_OUTPUT})",
    )
    args = parser.parse_args()

    print("🔗 Neo4j に接続中...")
    client = Neo4jClient()

    print(
        f"   ノード数: {client.count_nodes()}, エッジ数: {client.count_edges()}"
    )
    print("📤 グラフをエクスポート中...")

    graph = client.export_graph()
    client.close()

    write_graph_data_js(graph, args.output)
    print(f"⏱  エクスポート完了: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


if __name__ == "__main__":
    main()
