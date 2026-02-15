import json
import os

MASTER_PATH = "master_graph.json"
JSONLD_PATH = "knowledge_graph.jsonld"

def convert():
    if not os.path.exists(MASTER_PATH):
        print(f"Error: {MASTER_PATH} not found.")
        return

    with open(MASTER_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    jsonld_data = {
        "@context": {
            "nodes": { "@id": "http://schema.org/thing", "@container": "@set" },
            "edges": { "@id": "http://schema.org/link", "@container": "@set" }
        },
        "@type": "KnowledgeGraph",
        "nodes": data.get("nodes", []),
        "edges": data.get("edges", []),
        "metadata": data.get("metadata", {})
    }

    with open(JSONLD_PATH, "w", encoding="utf-8") as f:
        json.dump(jsonld_data, f, ensure_ascii=False, indent=2)
    
    print(f"Successfully converted {MASTER_PATH} to {JSONLD_PATH}")

if __name__ == "__main__":
    convert()
