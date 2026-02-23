import unittest
from datetime import datetime, timezone, timedelta
from scripts.graph_merger import apply_weight_decay, _days_since

def _make_node(node_id, label, ntype, weight, last_seen=None):
    n = {"id": node_id, "label": label, "type": ntype, "weight": weight}
    if last_seen:
        n["last_seen"] = last_seen
    return n

def _make_edge(source, target, etype, weight, last_seen=None):
    e = {"source": source, "target": target, "type": etype, "weight": weight}
    if last_seen:
        e["last_seen"] = last_seen
    return e

class TestDaysSince(unittest.TestCase):
    def test_zero_for_today(self):
        now_str = datetime.now(tz=timezone.utc).isoformat()
        self.assertEqual(_days_since(now_str), 0)

    def test_days_count(self):
        past = (datetime.now(tz=timezone.utc) - timedelta(days=5)).isoformat()
        self.assertEqual(_days_since(past), 5)

    def test_invalid_returns_zero(self):
        self.assertEqual(_days_since("not-a-date"), 0)


class TestApplyWeightDecay(unittest.TestCase):

    def _yesterday(self):
        return (datetime.now(tz=timezone.utc) - timedelta(days=1)).isoformat()

    def _days_ago(self, n):
        return (datetime.now(tz=timezone.utc) - timedelta(days=n)).isoformat()

    def test_absent_node_decays(self):
        """今回登場しないノードは0.05だけ減衰する。"""
        node = _make_node("task:A", "テストA", "タスク", 1.0, self._yesterday())
        master = {"nodes": [node], "edges": []}
        apply_weight_decay(master, set(), set())
        self.assertAlmostEqual(master["nodes"][0]["weight"], 0.95, places=3)

    def test_present_node_not_decayed(self):
        """今回登場したノードは減衰しない。"""
        node = _make_node("task:B", "テストB", "タスク", 1.0, self._yesterday())
        master = {"nodes": [node], "edges": []}
        apply_weight_decay(master, {"task:B"}, set())
        self.assertAlmostEqual(master["nodes"][0]["weight"], 1.0, places=3)

    def test_weight_floor(self):
        """weightが下限0.1を下回らない。"""
        node = _make_node("task:C", "テストC", "タスク", 0.1, self._yesterday())
        master = {"nodes": [node], "edges": []}
        apply_weight_decay(master, set(), set())
        self.assertGreaterEqual(master["nodes"][0]["weight"], 0.1)

    def test_diary_node_not_decayed(self):
        """日記型ノードは対象外。"""
        node = _make_node("日記:20260201", "2月1日の日記", "日記", 1.0, self._yesterday())
        master = {"nodes": [node], "edges": []}
        apply_weight_decay(master, set(), set())
        self.assertAlmostEqual(master["nodes"][0]["weight"], 1.0, places=3)

    def test_retroactive_decay_multiple_days(self):
        """5日前のノードは5日分まとめて減衰する。"""
        node = _make_node("task:D", "テストD", "タスク", 2.0, self._days_ago(5))
        master = {"nodes": [node], "edges": []}
        apply_weight_decay(master, set(), set())
        expected = max(0.1, round(2.0 - 0.05 * 5, 4))
        self.assertAlmostEqual(master["nodes"][0]["weight"], expected, places=3)

    def test_edge_decay(self):
        """未登場エッジも同様に減衰する。"""
        edge = _make_edge("task:A", "goal:X", "阻害する", 1.0, self._yesterday())
        master = {"nodes": [], "edges": [edge]}
        apply_weight_decay(master, set(), set())
        self.assertAlmostEqual(master["edges"][0]["weight"], 0.95, places=3)

    def test_present_edge_not_decayed(self):
        """今回登場したエッジは減衰しない。"""
        edge = _make_edge("task:A", "goal:X", "阻害する", 1.0, self._yesterday())
        master = {"nodes": [], "edges": [edge]}
        daily_edge_keys = {"task:A|goal:X|阻害する"}
        apply_weight_decay(master, set(), daily_edge_keys)
        self.assertAlmostEqual(master["edges"][0]["weight"], 1.0, places=3)


if __name__ == "__main__":
    unittest.main()
