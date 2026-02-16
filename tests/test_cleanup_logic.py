import unittest
import copy
from scripts.graph_cleanup_utils import merge_nodes_within_graph

class TestGraphCleanup(unittest.TestCase):
    
    def setUp(self):
        # Setup a sample mock graph
        self.mock_graph = {
            "nodes": [
                {
                    "id": "goal:keep_clean", 
                    "label": "Keep Clean", 
                    "weight": 10,
                    "tags": ["habit"],
                    "first_seen": "2026-02-01T10:00:00"
                },
                {
                    "id": "goal:clean_room", 
                    "label": "Clean Room", 
                    "weight": 5,
                    "tags": ["chore"],
                    "first_seen": "2026-02-02T10:00:00"
                },
                {
                    "id": "task:vacuum",
                    "label": "Vacuum",
                    "weight": 1
                }
            ],
            "edges": [
                # Edge to the target (should stay)
                {"source": "task:vacuum", "target": "goal:keep_clean", "label": "targets"},
                # Edge to the duplicate (should be remapped)
                {"source": "task:vacuum", "target": "goal:clean_room", "label": "targets"},
            ]
        }

    def test_merge_nodes(self):
        """Test that nodes are merged and duplicates removed."""
        target_id = "goal:keep_clean"
        source_ids = ["goal:clean_room"]
        
        # Execute Merge
        result_graph = merge_nodes_within_graph(self.mock_graph, target_id, source_ids)
        
        nodes = result_graph['nodes']
        edges = result_graph['edges']
        
        # 1. Verify Node Count
        self.assertEqual(len(nodes), 2) # Should be 2 (Target Goal + Task)
        
        # 2. Verify Target properties
        target_node = next(n for n in nodes if n['id'] == target_id)
        self.assertEqual(target_node['weight'], 15) # 10 + 5
        self.assertIn("habit", target_node['tags'])
        self.assertIn("chore", target_node['tags']) # Tags merged
        
        # 3. Verify Source Node Removed
        source_node_exists = any(n['id'] == "goal:clean_room" for n in nodes)
        self.assertFalse(source_node_exists)
        
        # 4. Verify Edges Remapped & Deduplicated
        # Original edges: Vacuum->KeepClean, Vacuum->CleanRoom
        # After remap: Vacuum->KeepClean, Vacuum->KeepClean (Duplicate)
        # The util handles deduplication, so we expect 1 edge if label/type match
        # Here labels match ("targets") so it should be 1 unique edge
        
        self.assertEqual(len(edges), 1)
        self.assertEqual(edges[0]['target'], target_id)
        self.assertEqual(edges[0]['source'], "task:vacuum")

if __name__ == '__main__':
    unittest.main()
