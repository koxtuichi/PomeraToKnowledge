import logging

def merge_nodes_within_graph(graph_data, target_id, source_ids):
    """
    Merges multiple source nodes into a single target node within the same graph.
    
    Args:
        graph_data (dict): The dictionary containing 'nodes' and 'edges' lists.
        target_id (str): The ID of the node to merge INTO. (Must exist or be one of the IDs).
        source_ids (list): List of IDs to merge FROM.
    
    Returns:
        dict: The modified graph_data.
    """
    nodes = {n['id']: n for n in graph_data.get('nodes', [])}
    edges = graph_data.get('edges', [])
    
    # Validation
    if target_id not in nodes:
        # If target_id is not in nodes, we can't merge into it.
        # However, for robustness, if target_id is in source_ids, we can handle it.
        pass
    
    target_node = nodes.get(target_id)
    if not target_node:
        print(f"Target node {target_id} not found in graph.")
        return graph_data

    # Filter source_ids to exclude target_id and non-existent nodes
    valid_source_ids = [sid for sid in source_ids if sid in nodes and sid != target_id]
    
    if not valid_source_ids:
        print("No valid source nodes to merge.")
        return graph_data
    
    print(f"Merging {len(valid_source_ids)} nodes into {target_id}...")

    # 1. Merge Properties (Tags, Weights, etc.)
    for sid in valid_source_ids:
        source_node = nodes[sid]
        
        # Merge tags (Unique union)
        current_tags = set(target_node.get('tags', []))
        source_tags = set(source_node.get('tags', []))
        target_node['tags'] = list(current_tags.union(source_tags))
        
        # Accumulate weight
        target_node['weight'] = target_node.get('weight', 1) + source_node.get('weight', 0)
        
        # Update timestamps (Min first_seen, Max last_seen)
        t_first = target_node.get('first_seen')
        s_first = source_node.get('first_seen')
        if s_first and (not t_first or s_first < t_first):
            target_node['first_seen'] = s_first
            
        t_last = target_node.get('last_seen')
        s_last = source_node.get('last_seen')
        if s_last and (not t_last or s_last > t_last):
            target_node['last_seen'] = s_last

        # Note: We keep target's Label/Detail/Status as the canonical one.

    # 2. Remap Edges
    # We need to iterate over a COPY or use strict indexing because we might modify
    remapped_count = 0
    for edge in edges:
        dirty = False
        if edge['source'] in valid_source_ids:
            # Check if self-loop would be created? (Not necessarily bad, but let's allow it for now)
            edge['source'] = target_id
            dirty = True
        
        if edge['target'] in valid_source_ids:
            edge['target'] = target_id
            dirty = True
            
        if dirty:
            remapped_count += 1
            
    print(f"Remapped {remapped_count} edges.")

    # 3. Remove Source Nodes
    graph_data['nodes'] = [n for n in graph_data['nodes'] if n['id'] not in valid_source_ids]
    
    print(f"Removed {len(valid_source_ids)} source nodes.")
    
    # 4. Remove Duplicate Edges (OPTIONAL but recommended)
    # After remapping, we might have multiple edges with same source-target-label
    unique_edges = []
    seen_edges = set()
    
    for edge in edges:
        # Create a signature for the edge
        sig = (edge['source'], edge['target'], edge.get('label', ''), edge.get('type', ''))
        if sig not in seen_edges:
            seen_edges.add(sig)
            unique_edges.append(edge)
            
    if len(edges) != len(unique_edges):
        print(f"Removed {len(edges) - len(unique_edges)} duplicate edges after merge.")
        graph_data['edges'] = unique_edges

    return graph_data
