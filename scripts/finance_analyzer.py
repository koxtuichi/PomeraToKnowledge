#!/usr/bin/env python3
"""
finance_analyzer.py — finance_context.json を読み込み、
家計のリスク評価・教育費シミュレーション・購入タイミング分析を行い
finance_report.json に出力する。

使い方:
  python3 scripts/finance_analyzer.py
  python3 scripts/finance_analyzer.py --context finance_context.json --output finance_report.json
"""
import os
import json
import argparse
from datetime import datetime


# ─── デフォルトファイルパス ─────────────────────────────────────────
DEFAULT_GRAPH_FILE = "knowledge_graph.jsonld"


# ─── 定数 ──────────────────────────────────────────────────────────────

# 月ごとの変動費の目安（クレカ利用額）
# 実際のクレカ合計が分かれば上書きされる
DEFAULT_MONTHLY_VARIABLE_COST = 500_000

# 緊急予備費の目標倍数（固定費+変動費の何ヶ月分か）
EMERGENCY_FUND_MONTHS = 3

# 公立学校教育費マイルストーン（年齢, イベント名, 必要額）
EDUCATION_MILESTONES_PUBLIC = [
    (3,  "保育園・幼稚園入園準備",    100_000),
    (6,  "小学校入学準備",             300_000),
    (12, "中学校入学準備",             200_000),
    (15, "高校入学準備",               300_000),
    (18, "大学入学初年度費用",       2_000_000),
    (19, "大学2年",                    700_000),
    (20, "大学3年",                    700_000),
    (21, "大学4年",                    700_000),
]

# 私立学校教育費マイルストーン（参考）
EDUCATION_MILESTONES_PRIVATE = [
    (3,  "幼稚園入園準備",             150_000),
    (6,  "小学校入学準備",             500_000),
    (12, "中学校入学準備",             600_000),
    (15, "高校入学準備",               500_000),
    (18, "大学入学初年度費用",       2_500_000),
    (19, "大学2年",                  1_000_000),
    (20, "大学3年",                  1_000_000),
    (21, "大学4年",                  1_000_000),
]

RISK_LABELS = {"低": "🟢 低", "中": "🟡 中", "高": "🔴 高"}


def calc_education_timeline(children: list, scenario: str, current_year: int) -> list:
    """子供ごとに教育費マイルストーンを計算する。"""
    milestones = (
        EDUCATION_MILESTONES_PUBLIC
        if scenario != "private"
        else EDUCATION_MILESTONES_PRIVATE
    )
    timeline = []
    for child in children:
        birth_year = child.get("birth_year", current_year)
        for age, event, cost in milestones:
            target_year = birth_year + age
            years_until = target_year - current_year
            if years_until >= 0:
                monthly_saving = cost // max(years_until * 12, 1)
                timeline.append({
                    "child": child["name"],
                    "age": age,
                    "year": target_year,
                    "years_until": years_until,
                    "event": event,
                    "cost": cost,
                    "monthly_saving_needed": monthly_saving
                })
    # 年度順にソート
    timeline.sort(key=lambda x: x["year"])
    return timeline


def calc_total_monthly_saving_needed(timeline: list, current_year: int) -> int:
    """今すぐ必要な月間教育費積立合計を計算する。"""
    total = 0
    for m in timeline:
        if m["years_until"] > 0:
            total += m["monthly_saving_needed"]
    return total


def assess_wishlist_risk(
    wishlist: list,
    monthly_income: int,
    monthly_fixed_costs: int,
    monthly_variable_estimate: int,
    monthly_education_saving: int,
    emergency_fund_target: int,
) -> list:
    """欲しいものリストに対してリスク評価を付ける。"""
    monthly_total = monthly_fixed_costs + monthly_variable_estimate + monthly_education_saving
    monthly_surplus = monthly_income - monthly_total

    results = []
    for item in wishlist:
        raw_cost = item["cost"]
        # LLMが文字列で返す場合・Noneの場合を安全に処理
        try:
            cost = int(raw_cost) if raw_cost is not None else None
        except (ValueError, TypeError):
            cost = None

        # costが不明な場合はRisk判定をスキップして「要確認」にする
        if cost is None:
            results.append({
                "item": item["item"],
                "cost": None,
                "priority": item["priority"],
                "risk": "中",
                "risk_label": "要確認",
                "reasons": ["金額が未設定のためリスク判定不可"],
                "months_to_save": None
            })
            continue

        risk = "低"
        reasons = []

        # 緊急予備費が不足しているか
        if emergency_fund_target <= 0:
            risk = "高"
            reasons.append("緊急予備費データなし（貯金額を設定してください）")
        elif cost > emergency_fund_target * 0.5:
            risk = "高"
            reasons.append(f"購入金額が緊急予備費の50%超（目標:{emergency_fund_target:,}円）")

        # 月次余剰で何ヶ月で貯まるか
        if monthly_surplus > 0:
            months_to_save = cost / monthly_surplus
            if months_to_save > 24:
                if risk == "低":
                    risk = "高"
                reasons.append(f"月余剰で貯めるのに{months_to_save:.0f}ヶ月かかる")
            elif months_to_save > 12:
                if risk == "低":
                    risk = "中"
                reasons.append(f"貯蓄期間の目安: 約{months_to_save:.0f}ヶ月")
            else:
                reasons.append(f"貯蓄期間の目安: 約{months_to_save:.0f}ヶ月")
        else:
            risk = "高"
            reasons.append("現状では月次赤字のため購入は困難")

        # 教育費積立への影響
        if monthly_surplus - cost / 12 < monthly_education_saving:
            if risk == "低":
                risk = "中"
            reasons.append("購入後は教育費積立に影響する可能性あり")

        results.append({
            "item": item["item"],
            "cost": cost,
            "priority": item["priority"],
            "risk": risk,
            "risk_label": RISK_LABELS.get(risk, risk),
            "reasons": reasons,
            "months_to_save": round(cost / monthly_surplus, 1) if monthly_surplus > 0 else None
        })
    return results


def load_wishlist_from_graph(graph_file: str) -> list:
    """ナレッジグラフから購入希望ノードを収集する。"""
    if not os.path.exists(graph_file):
        return []

    with open(graph_file, "r", encoding="utf-8") as f:
        graph = json.load(f)

    nodes = graph.get("nodes", [])
    wishlist = []
    for node in nodes:
        if node.get("type") == "購入希望" and node.get("status") != "購入済":
            raw_cost = node.get("cost")
            # LLMが文字列で返す場合も安全にint変換
            try:
                cost = int(raw_cost) if raw_cost is not None else None
            except (ValueError, TypeError):
                cost = None
            wishlist.append({
                "item":     node.get("label", node.get("id", "")),
                "cost":     cost,
                "priority": node.get("priority", "中"),
                "detail":   node.get("detail", ""),
                "first_seen": node.get("first_seen", ""),
                "last_seen":  node.get("last_seen", "")
            })

    # costが分からないものを後ろ、優先度順にソート
    priority_order = {"高": 0, "中": 1, "低": 2}
    wishlist.sort(key=lambda x: (priority_order.get(x["priority"], 1), x["cost"] is None))
    return wishlist


def build_credit_card_calendar(credit_cards: list) -> list:
    """クレカの引落日をカレンダー形式でまとめる。"""
    calendar = {}
    for card in credit_cards:
        day = card.get("due_day", 0)
        if day not in calendar:
            calendar[day] = []
        calendar[day].append({
            "name": card["name"],
            "bank": card.get("bank", "不明")
        })
    return [{"day": d, "cards": cards} for d, cards in sorted(calendar.items())]


def analyze(ctx: dict, graph_file: str = DEFAULT_GRAPH_FILE) -> dict:
    """家計データを分析してレポートを生成する。"""
    current_year = datetime.now().year

    monthly_income = ctx.get("monthly_income", 0)
    monthly_fixed  = ctx.get("monthly_fixed_costs", 0)
    family         = ctx.get("family", {})
    credit_cards   = ctx.get("credit_cards", [])
    education_scenario = family.get("education_scenario", "public")
    children           = family.get("children", [])

    # 欲しいものはナレッジグラフから取得
    wishlist = load_wishlist_from_graph(graph_file)

    # 教育費タイムライン
    edu_timeline = calc_education_timeline(children, education_scenario, current_year)
    monthly_edu_saving = calc_total_monthly_saving_needed(edu_timeline, current_year)

    # 変動費の目安（月収 - 固定費 - 貯蓄余力）を暫定推定
    # 実際のクレカ利用額が分かれば差し替え
    monthly_variable_estimate = DEFAULT_MONTHLY_VARIABLE_COST

    # 緊急予備費の目標（固定費+変動費の3ヶ月分）
    monthly_total = monthly_fixed + monthly_variable_estimate
    emergency_fund_target = monthly_total * EMERGENCY_FUND_MONTHS

    # 月次収支サマリー
    monthly_surplus = monthly_income - monthly_fixed - monthly_variable_estimate - monthly_edu_saving
    savings_rate = round(monthly_surplus / monthly_income * 100, 1) if monthly_income > 0 else 0

    # リスク評価
    risk_assessed = assess_wishlist_risk(
        wishlist,
        monthly_income,
        monthly_fixed,
        monthly_variable_estimate,
        monthly_edu_saving,
        emergency_fund_target,
    )

    # クレカカレンダー
    cc_calendar = build_credit_card_calendar(credit_cards)

    # 次の教育費マイルストーン（直近3件）
    upcoming_milestones = edu_timeline[:3]

    return {
        "generated_at": datetime.now().isoformat(),
        "summary": {
            "monthly_income": monthly_income,
            "monthly_fixed_costs": monthly_fixed,
            "monthly_variable_estimate": monthly_variable_estimate,
            "monthly_education_saving": monthly_edu_saving,
            "monthly_surplus": monthly_surplus,
            "savings_rate_pct": savings_rate,
            "emergency_fund_target": emergency_fund_target,
            "note": "変動費は暫定値です。実際のクレカ合計と差し替えてください。"
        },
        "wishlist_risk": risk_assessed,
        "credit_card_calendar": cc_calendar,
        "education_timeline": edu_timeline,
        "upcoming_milestones": upcoming_milestones,
        "monthly_education_saving_needed": monthly_edu_saving,
        "education_scenario": education_scenario,
        "children": children
    }


def main():
    parser = argparse.ArgumentParser(description="家計コンテキストを分析してレポートを生成する")
    parser.add_argument("--context", default="finance_context.json", help="入力JSONファイル")
    parser.add_argument("--graph",   default=DEFAULT_GRAPH_FILE,     help="ナレッジグラフJSON-LDファイル")
    parser.add_argument("--output",  default="finance_report.json",  help="出力JSONファイル")
    args = parser.parse_args()

    if not os.path.exists(args.context):
        print(f"❌ {args.context} が見つかりません。先に finance_parser.py を実行してください。")
        return

    with open(args.context, "r", encoding="utf-8") as f:
        ctx = json.load(f)

    report = analyze(ctx, graph_file=args.graph)

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"✅ {args.output} を出力しました")
    print(f"   月収: {report['summary']['monthly_income']:,}円")
    print(f"   月次余剰（暫定）: {report['summary']['monthly_surplus']:,}円")
    print(f"   貯蓄率（暫定）: {report['summary']['savings_rate_pct']}%")
    print(f"   教育費積立 必要額/月: {report['monthly_education_saving_needed']:,}円")
    print(f"\n  欲しいもの リスク評価:")
    for item in report["wishlist_risk"]:
        print(f"   {item['risk_label']} {item['item']} ({item['cost']:,}円) — {', '.join(item['reasons'])}")


if __name__ == "__main__":
    main()
