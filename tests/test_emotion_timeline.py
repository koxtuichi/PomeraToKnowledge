import unittest
from datetime import datetime, timezone, timedelta

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from scripts.graph_merger import apply_emotion_decay, _calc_trend, EMOTION_DECAY_RATES


def _make_emotion_node(node_id, label, sentiment, category="その他", trigger=None, active_sentiment=None, emotion_history=None):
    node = {
        "id": node_id,
        "label": label,
        "type": "感情",
        "sentiment": sentiment,
        "emotion_category": category,
    }
    if trigger:
        node["trigger"] = trigger
    if active_sentiment is not None:
        node["active_sentiment"] = active_sentiment
    if emotion_history is not None:
        node["emotion_history"] = emotion_history
    return node


class TestCalcTrend(unittest.TestCase):
    def test_rising(self):
        history = [
            {"active_sentiment": 0.3},
            {"active_sentiment": 0.6},
            {"active_sentiment": 0.9},
        ]
        self.assertEqual(_calc_trend(history), "上昇")

    def test_falling(self):
        history = [
            {"active_sentiment": 0.9},
            {"active_sentiment": 0.6},
            {"active_sentiment": 0.3},
        ]
        self.assertEqual(_calc_trend(history), "下降")

    def test_stable(self):
        history = [
            {"active_sentiment": 0.5},
            {"active_sentiment": 0.52},
        ]
        self.assertEqual(_calc_trend(history), "安定")

    def test_single_entry(self):
        history = [{"active_sentiment": 0.8}]
        self.assertEqual(_calc_trend(history), "安定")

    def test_empty(self):
        self.assertEqual(_calc_trend([]), "安定")


class TestApplyEmotionDecay(unittest.TestCase):
    TODAY = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    YESTERDAY = (datetime.now(tz=timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")

    def test_mentioned_emotion_restores_active_sentiment(self):
        """今日言及された感情ノードは active_sentiment が sentiment 水準に戻る。"""
        node = _make_emotion_node("感情:達成感", "達成感", sentiment=0.9, active_sentiment=0.5)
        master = {"nodes": [node]}
        apply_emotion_decay(master, {"感情:達成感"}, self.TODAY)
        self.assertAlmostEqual(master["nodes"][0]["active_sentiment"], 0.9, places=4)

    def test_unmentioned_joy_decays_fast(self):
        """喜びノードが言及されない場合、高い係数で減衰する。"""
        node = _make_emotion_node("感情:喜び", "喜び", sentiment=1.0, category="喜び", active_sentiment=1.0)
        master = {"nodes": [node]}
        apply_emotion_decay(master, set(), self.TODAY)
        expected = round(1.0 * (1 - EMOTION_DECAY_RATES["喜び"]), 4)
        self.assertAlmostEqual(master["nodes"][0]["active_sentiment"], expected, places=4)

    def test_unmentioned_anxiety_decays_slow(self):
        """不安ノードが言及されない場合、低い係数で緩やかに減衰する。"""
        node = _make_emotion_node("感情:不安", "不安", sentiment=-0.8, category="不安", active_sentiment=-0.8)
        master = {"nodes": [node]}
        apply_emotion_decay(master, set(), self.TODAY)
        expected = round(-0.8 * (1 - EMOTION_DECAY_RATES["不安"]), 4)
        self.assertAlmostEqual(master["nodes"][0]["active_sentiment"], expected, places=4)

    def test_emotion_history_appended(self):
        """emotion_history に今日の記録が追記される。"""
        node = _make_emotion_node("感情:達成感", "達成感", sentiment=0.9, active_sentiment=0.9)
        node["emotion_history"] = []
        master = {"nodes": [node]}
        apply_emotion_decay(master, {"感情:達成感"}, self.TODAY)
        history = master["nodes"][0]["emotion_history"]
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["date"], self.TODAY)

    def test_emotion_history_no_duplicate(self):
        """同じ日付のレコードが重複して追記されない。"""
        existing_history = [{"date": self.TODAY, "sentiment": 0.9, "active_sentiment": 0.9, "trigger": None}]
        node = _make_emotion_node("感情:達成感", "達成感", sentiment=0.9, active_sentiment=0.9, emotion_history=existing_history)
        master = {"nodes": [node]}
        apply_emotion_decay(master, {"感情:達成感"}, self.TODAY)
        history = master["nodes"][0]["emotion_history"]
        self.assertEqual(len(history), 1)

    def test_peak_sentiment_updated(self):
        """peak_sentiment が履歴の最大値に更新される。"""
        history = [
            {"date": self.YESTERDAY, "sentiment": 0.5, "active_sentiment": 0.5, "trigger": None}
        ]
        node = _make_emotion_node("感情:達成感", "達成感", sentiment=0.9, active_sentiment=0.9, emotion_history=history)
        master = {"nodes": [node]}
        apply_emotion_decay(master, {"感情:達成感"}, self.TODAY)
        self.assertAlmostEqual(master["nodes"][0]["peak_sentiment"], 0.9, places=4)

    def test_trend_calculated(self):
        """trend が正しく計算される。"""
        history = [
            {"date": "2026-02-22", "sentiment": 0.3, "active_sentiment": 0.3, "trigger": None},
            {"date": "2026-02-23", "sentiment": 0.6, "active_sentiment": 0.6, "trigger": None},
        ]
        node = _make_emotion_node("感情:喜び", "喜び", sentiment=0.9, category="喜び", active_sentiment=0.9, emotion_history=history)
        master = {"nodes": [node]}
        apply_emotion_decay(master, {"感情:喜び"}, self.TODAY)
        self.assertEqual(master["nodes"][0]["trend"], "上昇")

    def test_non_emotion_nodes_not_affected(self):
        """感情ノード以外には apply_emotion_decay が影響を与えない。"""
        node = {"id": "タスク:A", "type": "タスク", "label": "テスト", "weight": 1.0}
        master = {"nodes": [node]}
        apply_emotion_decay(master, set(), self.TODAY)
        self.assertNotIn("active_sentiment", master["nodes"][0])


if __name__ == "__main__":
    unittest.main()
