import json
import os
from scripts.graph_cleanup_utils import merge_nodes_within_graph

GRAPH_FILE = "knowledge_graph.jsonld"

def main():
    print(f"Loading {GRAPH_FILE}...")
    with open(GRAPH_FILE, 'r', encoding='utf-8') as f:
        graph_data = json.load(f)

    # Define the merge plan
    # Target: goal:clean_pet_room_habit (Most weight/detail)
    target_id = "goal:clean_pet_room_habit"
    
    # Sources to merge into target
    source_ids = [
        "goal:clean_pet_room",       # Label: ペット部屋の清掃と維持
        "goal:keep_pet_room_clean"   # Label: ペット部屋を綺麗に保つ
    ]

    print(f"Target ID: {target_id}")
    print(f"Source IDs: {source_ids}")

    # Calculate pre-merge counts
    pre_node_count = len(graph_data.get('nodes', []))
    pre_edge_count = len(graph_data.get('edges', []))
    print(f"Pre-merge: {pre_node_count} nodes, {pre_edge_count} edges")

    # Execute Merge
    graph_data = merge_nodes_within_graph(graph_data, target_id, source_ids)

    # Calculate post-merge counts
    post_node_count = len(graph_data.get('nodes', []))
    post_edge_count = len(graph_data.get('edges', []))
    print(f"Post-merge: {post_node_count} nodes, {post_edge_count} edges")
    
    # Save
    print(f"Saving to {GRAPH_FILE}...")
    with open(GRAPH_FILE, 'w', encoding='utf-8') as f:
        json.dump(graph_data, f, indent=2, ensure_ascii=False)
        
    print("✅ Cleanup complete.")

if __name__ == "__main__":
    main()
