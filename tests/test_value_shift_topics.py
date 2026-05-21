import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import llm_graph_builder


def diary(date, text):
    return {
        "id": f"日記:{date}",
        "label": f"{date}の日記",
        "type": "日記",
        "date": date,
        "detail": text,
    }


class TestValueShiftTopics(unittest.TestCase):
    def test_creative_keywords_ignore_single_character_noise(self):
        creative = next(
            item for item in llm_graph_builder.VALUE_SHIFT_DEFS
            if item["label"] == "創作・表現"
        )
        text = "本当に本業の学びを試した。"

        self.assertEqual(
            llm_graph_builder._count_value_shift_keywords(text, creative["keywords"]),
            0,
        )

    def test_ascii_keyword_requires_text_boundary(self):
        growth = next(
            item for item in llm_graph_builder.VALUE_SHIFT_DEFS
            if item["label"] == "探究・成長"
        )

        self.assertEqual(
            llm_graph_builder._count_value_shift_keywords("saitekiの作業", growth["keywords"]),
            0,
        )
        self.assertEqual(
            llm_graph_builder._count_value_shift_keywords("AI研究を進めた", growth["keywords"]),
            2,
        )

    def test_down_topic_keeps_display_evidence(self):
        graph = {
            "nodes": [
                diary("2026-04-01", "ブログ記事の原稿を執筆した。表現の方向性を考えた。"),
                diary("2026-04-02", "ポメラでブログの下書きを作り、記事として発信する準備をした。"),
                diary("2026-04-03", "小説のアイディアと執筆テーマを整理した。"),
                diary("2026-04-04", "動画と記事の表現を見直した。"),
                diary("2026-05-20", "体重と健康の記録を整理した。"),
                diary("2026-05-21", "支出と不安を見える形にして安心した。"),
            ],
            "edges": [],
            "metadata": {},
        }

        topics = llm_graph_builder.build_value_shift_topics(graph)
        creative = next(item for item in topics if item["category"] == "創作・表現")

        self.assertEqual(creative["direction"], "down")
        self.assertTrue(creative["recent_examples"])
        self.assertIn("控えめ", creative["recent_examples"][0]["summary"])


if __name__ == "__main__":
    unittest.main()
