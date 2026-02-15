import os
import json
import requests
from typing import Dict, Any, List

API_KEY = os.getenv("GOOGLE_API_KEY")
MASTER_PATH = "master_graph.json"
HTML_PATH = "index.html"
TARGET_DATE = "2026-02-14"
DIARY_ID = f"diary:{TARGET_DATE}"

ANALYSIS_SYSTEM_PROMPT = """
You are a professional Life Coach and Data Analyst.
Analyze the provided Knowledge Graph (JSON) of the user's diary AND the context from the Master Graph (Past Goals/Plans).
Provide a "Daily Feedback & Action Plan".

### Input Context
You will be provided with:
1. **Daily Graph**: The graph extracted from today's diary.
2. **Master Context**: Recent active goals and scheduled events from the past.

### Output Query
1. **Plan vs Actual Analysis**:
    - Compare today's actions (Daily Graph) with previously set `Scheduled` events or `Active` goals (Master Context).
    - Did the user follow through? If not, why? (Look for Barriers/Emotions).
2. **Meta-Cognition**:
    - Identify recurring patterns. Are there specific triggers for positive/negative sentiment?
3. **Context-Aware Advice**:
    - **Keep**: What went well today that should be continued?
    - **Problem**: What blocked progress? (e.g., "Overeating due to stress").
    - **Try**: Concrete advice for tomorrow. If there are `Scheduled` events for tomorrow, give specific advice for them.

### Output Format
Markdown format. Language: Japanese.
"""

def call_gemini_api(prompt: str, model: str = "gemini-2.0-flash", response_mime_type: str = "text/plain") -> str:
    if not API_KEY:
        raise ValueError("GOOGLE_API_KEY is not set.")
    
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    params = {"key": API_KEY}
    headers = {"Content-Type": "application/json"}
    
    data = {
        "contents": [{"parts": [{"text": prompt}]}],
         "generationConfig": {"response_mime_type": response_mime_type}
    }
    
    response = requests.post(url, headers=headers, json=data, params=params)
    if response.status_code != 200:
        raise Exception(f"API Error: {response.status_code} - {response.text}")
    
    try:
        return response.json()["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError):
        raise Exception(f"Unexpected API response format: {response.json()}")

def get_subgraph_for_diary(nodes, edges, diary_id):
    # Find nodes connected to the diary node + the diary node itself
    connected_node_ids = set()
    connected_node_ids.add(diary_id)
    
    # 1 Hop
    for e in edges:
        if e['source'] == diary_id:
            connected_node_ids.add(e['target'])
        elif e['target'] == diary_id:
            connected_node_ids.add(e['source'])
            
    # Also include nodes that share the same date in 'date' field or label (heuristic)
    for n in nodes:
        if n.get('date') == TARGET_DATE:
            connected_node_ids.add(n['id'])
            
    sub_nodes = [n for n in nodes if n['id'] in connected_node_ids]
    return {"nodes": sub_nodes, "edges": []} # Edges not strictly necessary for this context, but nodes are key

def generate_report():
    print(f"📂 Loading Master Graph: {MASTER_PATH}")
    with open(MASTER_PATH, "r", encoding="utf-8") as f:
        master_graph = json.load(f)
    
    nodes = master_graph.get("nodes", [])
    edges = master_graph.get("edges", [])
    
    # Check if diary node exists
    diary_node = next((n for n in nodes if n['id'] == DIARY_ID), None)
    if not diary_node:
        print(f"❌ Diary node {DIARY_ID} not found.")
        return

    # Extract Subgraph for 14th
    daily_graph = get_subgraph_for_diary(nodes, edges, DIARY_ID)
    print(f"Found {len(daily_graph['nodes'])} nodes for {TARGET_DATE}")
    
    # Generate Report
    prompt = f"""
    {ANALYSIS_SYSTEM_PROMPT}

    ### Target Date: {TARGET_DATE}

    ### Today's Graph Data (JSON)
    {json.dumps(daily_graph, ensure_ascii=False, indent=2)}
    """
    
    print("🔄 Generating Analysis Report...")
    try:
        report = call_gemini_api(prompt)
    except Exception as e:
        print(f"❌ API Error: {e}")
        return

    # Update Node
    diary_node['analysis_content'] = report
    print("✅ Report generated and attached to node.")
    
    # Save Master Graph
    with open(MASTER_PATH, "w", encoding="utf-8") as f:
        json.dump(master_graph, f, ensure_ascii=False, indent=2)
    print(f"✅ Master Graph saved to {MASTER_PATH}")
    
    # Update HTML
    update_html_visualization(HTML_PATH, master_graph)

def update_html_visualization(html_path: str, graph_data: Dict[str, Any]):
    try:
        with open(html_path, "r", encoding="utf-8") as f:
            html_content = f.read()
        
        start_marker = "// GRAPH_DATA_START"
        end_marker = "// GRAPH_DATA_END"
        
        start_idx = html_content.find(start_marker)
        end_idx = html_content.find(end_marker)
        
        if start_idx != -1 and end_idx != -1:
            new_block = f"{start_marker}\n    const GRAPH_DATA = {json.dumps(graph_data, ensure_ascii=False, indent=2)};\n    "
            new_html = html_content[:start_idx] + new_block + html_content[end_idx:]
            
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(new_html)
            print(f"✅ Visualization updated: {html_path}")
        else:
            print(f"⚠️ Markers not found in {html_path}.")

    except Exception as e:
        print(f"❌ Error updating HTML: {e}")

if __name__ == "__main__":
    generate_report()
