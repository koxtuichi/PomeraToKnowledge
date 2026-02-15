import json
import sys
import os

# Add scripts directory to path to import llm_graph_builder
sys.path.append(os.path.join(os.getcwd(), 'scripts'))
import llm_graph_builder

JSONLD_PATH = "knowledge_graph.jsonld"
HTML_PATH = "index.html"

def update():
    if not os.path.exists(JSONLD_PATH):
        print(f"Error: {JSONLD_PATH} not found.")
        return

    with open(JSONLD_PATH, "r", encoding="utf-8") as f:
        graph_data = json.load(f)

    llm_graph_builder.update_html_visualization(HTML_PATH, graph_data)
    print(f"Updated {HTML_PATH} with data from {JSONLD_PATH}")

if __name__ == "__main__":
    update()
