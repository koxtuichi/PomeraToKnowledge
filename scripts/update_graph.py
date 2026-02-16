import os
import json
import google.generativeai as genai
from datetime import datetime

# 設定
GENAI_API_KEY = os.getenv("GEMINI_API_KEY")
GRAPH_FILE = "knowledge_graph.jsonld"
DIARY_INPUT = "diary_temp.txt"

def load_graph():
    if os.path.exists(GRAPH_FILE):
        with open(GRAPH_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "nodes": [],
        "edges": [],
        "metadata": {
            "schema_version": "2.0-antigravity",
            "description": "タスクの重力モデルに基づく知識グラフ"
        }
    }

def save_graph(graph):
    with open(GRAPH_FILE, "w", encoding="utf-8") as f:
        json.dump(graph, f, ensure_ascii=False, indent=2)

def generate_update(diary_text, current_graph):
    genai.configure(api_key=GENAI_API_KEY)
    model = genai.GenerativeModel("gemini-1.5-flash")

    # マスターグラフの状態を要約
    existing_tasks = [n for n in current_graph.get("nodes", []) if n.get("type") == "タスク"]
    existing_constraints = [n for n in current_graph.get("nodes", []) if n.get("type") == "制約"]

    context = "### 既存のタスク\n"
    for t in existing_tasks:
        context += f"- [{t.get('id')}] {t.get('label')}: {t.get('detail', '')}\n"
    context += "\n### 既知の制約\n"
    for c in existing_constraints:
        context += f"- [{c.get('id')}] {c.get('label')}: {c.get('detail', '')}\n"

    prompt = f"""
あなたはユーザーの「分身」を構築するためのナレッジエンジニアです。
日記の内容を解析し、知識グラフを更新するための新しいノードとエッジを抽出してください。

### 抽出するノードの種類
1. タスク: やるべきこと。既存タスクの状態変更も含む。
2. 制約: タスクを阻害する「重力」。時間不足、疲労、技術的課題、感情的ブレーキなど。
3. 知見: 将来の資産に繋がる教訓やアイデア。
4. 感情: 行動の原動力、または阻害要因となる感情。

### 関係性
- 阻害する: 制約 → タスク
- 原動力になる: 感情/知見 → タスク
- 一部である: 知見 → プロジェクト
- 言及する: 日記 → 各ノード
- 引き起こす: 出来事 → 感情/知見

{context}

### 今日の日記:
{diary_text}

### 出力形式:
以下のJSON形式で出力してください。label と detail は必ず日本語で。
{{
  "nodes": [...],
  "edges": [...]
}}
"""

    response = model.generate_content(prompt)
    content = response.text.replace("```json", "").replace("```", "").strip()
    return json.loads(content)

def main():
    if not os.path.exists(DIARY_INPUT):
        print("日記ファイルが見つかりません。")
        return

    with open(DIARY_INPUT, "r", encoding="utf-8") as f:
        diary_text = f.read()

    current_graph = load_graph()
    new_elements = generate_update(diary_text, current_graph)

    # ノードのマージ
    existing_ids = {n["id"] for n in current_graph.get("nodes", [])}
    for node in new_elements.get("nodes", []):
        if node["id"] in existing_ids:
            # 既存ノードを更新
            for i, existing in enumerate(current_graph["nodes"]):
                if existing["id"] == node["id"]:
                    existing.update(node)
                    existing["last_seen"] = datetime.now().isoformat()
                    break
        else:
            node["first_seen"] = datetime.now().isoformat()
            node["last_seen"] = datetime.now().isoformat()
            node["weight"] = 1
            current_graph["nodes"].append(node)

    # エッジのマージ
    existing_edges = {f"{e['source']}|{e['target']}|{e.get('type', '')}" for e in current_graph.get("edges", [])}
    for edge in new_elements.get("edges", []):
        key = f"{edge['source']}|{edge['target']}|{edge.get('type', '')}"
        if key not in existing_edges:
            edge["first_seen"] = datetime.now().isoformat()
            edge["weight"] = 1
            current_graph["edges"].append(edge)

    # メタデータ更新
    current_graph.setdefault("metadata", {})
    current_graph["metadata"]["last_updated"] = datetime.now().isoformat()
    current_graph["metadata"]["node_count"] = len(current_graph["nodes"])
    current_graph["metadata"]["edge_count"] = len(current_graph["edges"])

    save_graph(current_graph)
    print(f"グラフを更新しました: {datetime.now()}")

if __name__ == "__main__":
    main()