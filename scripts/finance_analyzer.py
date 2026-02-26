#!/usr/bin/env python3
"""
finance_analyzer.py — finance_context.json を読み込み、
家計の収支サマリー・ライフイベント予測・クレカカレンダーを生成し
finance_report.json に出力する。

使い方:
  python3 scripts/finance_analyzer.py
  python3 scripts/finance_analyzer.py --context finance_context.json --output finance_report.json
"""
import os
import json
import re
import argparse
import requests
from datetime import datetime


# ─── デフォルトファイルパス ─────────────────────────────────────────
DEFAULT_GRAPH_FILE   = "knowledge_graph.jsonld"
DEFAULT_ROLE_DEF     = "role_definition.txt"


# ─── 定数 ──────────────────────────────────────────────────────────────

# 月ごとの変動費の目安（クレカ利用額）
# 実際のクレカ合計が分かれば上書きされる
DEFAULT_MONTHLY_VARIABLE_COST = 500_000

# 緊急予備費の目標倍数（固定費+変動費の何ヶ月分か）
EMERGENCY_FUND_MONTHS = 3


# ─── Gemini API ────────────────────────────────────────────────────────

def call_gemini_api(prompt: str, model: str = "gemini-2.0-flash") -> str:
    """Gemini APIを呼び出してテキストを返す。"""
    api_key = os.environ.get("GOOGLE_API_KEY", "")
    if not api_key:
        raise ValueError("GOOGLE_API_KEY が環境変数に設定されていません")

    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent?key={api_key}"
    )
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.3,
            "responseMimeType": "application/json"
        }
    }
    resp = requests.post(url, json=payload, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    return data["candidates"][0]["content"]["parts"][0]["text"]


# ─── グラフ読み込み ────────────────────────────────────────────────────

def load_graph_nodes_by_type(graph_file: str, types: list) -> list:
    """ナレッジグラフから指定タイプのノードを全件取得する。"""
    if not os.path.exists(graph_file):
        return []
    with open(graph_file, "r", encoding="utf-8") as f:
        graph = json.load(f)
    nodes = graph.get("nodes", [])
    return [n for n in nodes if n.get("type") in types]


def _normalize_card_name(name: str) -> str:
    """全角英数字を半角に正規化してカード名の重複を防ぐ。"""
    import unicodedata
    return unicodedata.normalize("NFKC", name).strip()


def load_monthly_charges_from_graph(graph_file: str) -> dict:
    """ナレッジグラフから最新月の月次クレカ請求ノードを収集する。

    Returns:
        {カード名: 請求額} の辞書。最新月のデータのみ。
    """
    if not os.path.exists(graph_file):
        return {}

    with open(graph_file, "r", encoding="utf-8") as f:
        graph = json.load(f)

    nodes = graph.get("nodes", [])
    charge_nodes = [n for n in nodes if n.get("type") == "月次クレカ請求"]
    if not charge_nodes:
        return {}

    months = [n.get("month", "") for n in charge_nodes if n.get("month")]
    if not months:
        return {}
    latest_month = max(months)

    charges = {}
    for n in charge_nodes:
        if n.get("month") == latest_month:
            card_name = _normalize_card_name(n.get("card_name") or n.get("label", ""))
            try:
                amount = int(n.get("amount", 0))
            except (ValueError, TypeError):
                amount = 0
            if card_name and card_name not in charges:
                charges[card_name] = amount

    print(f"   📊 月次クレカ請求（{latest_month}）: {len(charges)}枚分 グラフから取得")
    return charges


def load_card_charges_by_month(graph_file: str, card_usage_map: dict = None) -> list:
    """ナレッジグラフから当月・翌月のカード別請求データを取得する。

    Args:
        graph_file: ナレッジグラフJSON-LDファイルのパス
        card_usage_map: {正規化カード名: 用途} の辞書

    Returns:
        [{"month": "2026-02", "cards": [{"name": "...", "amount": 1234, "usage": "..."}, ...], "total": 9999}, ...]
    """
    if not os.path.exists(graph_file):
        return []

    card_usage_map = card_usage_map or {}

    with open(graph_file, "r", encoding="utf-8") as f:
        graph = json.load(f)

    charge_nodes = [n for n in graph.get("nodes", []) if n.get("type") == "月次クレカ請求"]
    if not charge_nodes:
        return []

    # 月ごとに集計（カード名を正規化して重複排除）
    by_month = {}
    for n in charge_nodes:
        month = n.get("month", "")
        if not month:
            continue
        card_name = _normalize_card_name(n.get("card_name") or n.get("label", ""))
        try:
            amount = int(n.get("amount", 0))
        except (ValueError, TypeError):
            amount = 0
        if not card_name:
            continue
        if month not in by_month:
            by_month[month] = {}
        if card_name not in by_month[month]:
            by_month[month][card_name] = amount

    # 最新2ヶ月分をソートして返す
    sorted_months = sorted(by_month.keys(), reverse=True)[:2]
    sorted_months.sort()  # 古い順
    result = []
    for m in sorted_months:
        cards = by_month[m]
        card_list = sorted(
            [{"name": k, "amount": v, "usage": _find_card_usage(k, card_usage_map)} for k, v in cards.items()],
            key=lambda x: -x["amount"]
        )
        result.append({
            "month": m,
            "cards": card_list,
            "total": sum(c["amount"] for c in card_list),
        })
    return result


def _find_card_usage(card_name: str, card_usage_map: dict) -> str:
    """カード名から用途を検索する。部分一致で探す。"""
    if not card_usage_map:
        return None
    # 完全一致
    if card_name in card_usage_map:
        return card_usage_map[card_name]
    # 部分一致
    for k, v in card_usage_map.items():
        if k in card_name or card_name in k:
            return v
    return None


def load_monthly_income_from_graph(graph_file: str) -> dict:
    """ナレッジグラフから最新月の月次収入ノードを収集する。

    Returns:
        {"sources": {収入源: 金額}, "total": 合計, "month": 月} の辞書。
    """
    if not os.path.exists(graph_file):
        return {}

    with open(graph_file, "r", encoding="utf-8") as f:
        graph = json.load(f)

    nodes = graph.get("nodes", [])
    income_nodes = [n for n in nodes if n.get("type") == "月次収入"]
    if not income_nodes:
        return {}

    months = [n.get("month", "") for n in income_nodes if n.get("month")]
    if not months:
        return {}
    latest_month = max(months)

    sources = {}
    for n in income_nodes:
        if n.get("month") == latest_month:
            src = n.get("source") or n.get("label", "")
            try:
                amount = int(n.get("amount", 0))
            except (ValueError, TypeError):
                amount = 0
            if src:
                sources[src] = amount

    total = sum(sources.values())
    print(f"   💰 月次収入（{latest_month}）: {total:,}円 グラフから取得")
    return {"sources": sources, "total": total, "month": latest_month}


# ─── ライフイベント予測（LLM） ────────────────────────────────────────

def generate_life_events_forecast(
    ctx: dict,
    graph_file: str,
    role_def_file: str,
) -> list:
    """LLMを使ってライフイベント予測リストを生成する。

    Returns:
        ライフイベント辞書のリスト（months_until 昇順）。
    """
    # role_definition.txt を読み込む
    role_def_text = ""
    if os.path.exists(role_def_file):
        with open(role_def_file, "r", encoding="utf-8") as f:
            role_def_text = f.read()

    # ナレッジグラフから関連ノードを全件取得
    relevant_nodes = load_graph_nodes_by_type(
        graph_file,
        types=["人物", "購入希望", "日記"]
    )

    # 家族情報（子供の誕生年月）
    family = ctx.get("family", {})
    children = family.get("children", [])

    today = datetime.now()
    today_str = today.strftime("%Y年%m月%d日")
    current_year  = today.year
    current_month = today.month

    # プロンプト組み立て
    prompt = f"""あなたは家計アドバイザーです。以下の個人情報と日記データをもとに、
これから数ヶ月〜数年の間に発生しうる出費イベントを予測してください。

## 現在の日付
{today_str}

## 自己定義（role_definition.txt）
{role_def_text}

## 子供の情報（finance_context.jsonより）
{json.dumps(children, ensure_ascii=False, indent=2)}

## ナレッジグラフのノード（人物・購入希望・日記）
{json.dumps(relevant_nodes, ensure_ascii=False, indent=2)}

## 出力ルール
以下のJSON配列を出力してください。余計な説明は不要です。必ずJSONのみ出力してください。

出力例:
[
  {{
    "event": "蒼馬 1歳・歩行開始",
    "category": "育児",
    "timing": "2026年5月頃",
    "months_until": 3,
    "estimated_cost": 15000,
    "certainty": "高",
    "note": "ファーストシューズ・室内安全グッズなど"
  }},
  {{
    "event": "妻の誕生日",
    "category": "記念日",
    "timing": "2026年〇月頃",
    "months_until": 8,
    "estimated_cost": 20000,
    "certainty": "高",
    "note": "プレゼント・外食など"
  }}
]

## 予測の指針
- 子供の月齢に応じた育児用品の出費（歩行、トイレトレーニング、保育園準備など）
- 教育費マイルストーン（保育園・小学校・中学校・高校・大学）
- role_definition.txtに記載されている誕生日・記念日
- 日記ノードに書かれた仕事の変化・キャリアリスク（仕事の空白期間など）
- 購入希望ノードに記載されたほしいもの（購入希望:XXXが来たら「購入検討中」として計上）
- 住宅・車など大きな維持費の可能性
- certaintyは「高」（ほぼ確実）「中」（可能性が高い）「低」（あくまで可能性）の3段階
- months_untilは今日から何ヶ月後かの整数（概算でOK）
- estimated_costが不明な場合はnullにしてください
- 重複するイベントは統合してください
- 以下の順で並べてください：months_until の小さい順（近い将来から）
"""

    print("   🤖 Gemini でライフイベント予測を生成中...")
    raw = call_gemini_api(prompt)

    # JSONを安全にパース
    try:
        events = json.loads(raw)
        if isinstance(events, list):
            # months_until で昇順ソート
            events.sort(key=lambda x: x.get("months_until") if x.get("months_until") is not None else 9999)
            print(f"   ✅ ライフイベント予測: {len(events)}件")
            return events
    except json.JSONDecodeError:
        # コードブロックが含まれる場合を考慮して再試行
        try:
            match = re.search(r'\[.*\]', raw, re.DOTALL)
            if match:
                events = json.loads(match.group())
                events.sort(key=lambda x: x.get("months_until") if x.get("months_until") is not None else 9999)
                return events
        except Exception:
            pass

    print("   ⚠️  ライフイベント予測のパースに失敗しました")
    return []


# ─── クレカカレンダー ──────────────────────────────────────────────────

def build_credit_card_calendar(credit_cards: list) -> list:
    """クレカの引落日をカレンダー形式でまとめる。月次請求額も引き継ぐ。"""
    calendar = {}
    for card in credit_cards:
        day = card.get("due_day", 0)
        if day not in calendar:
            calendar[day] = {"cards": [], "total_charge": None}
        entry = {
            "name": card["name"],
            "bank": card.get("bank", "不明"),
        }
        charge = card.get("monthly_charge")
        if charge is not None:
            try:
                entry["monthly_charge"] = int(charge)
                if calendar[day]["total_charge"] is None:
                    calendar[day]["total_charge"] = 0
                calendar[day]["total_charge"] += int(charge)
            except (ValueError, TypeError):
                entry["monthly_charge"] = None
        else:
            entry["monthly_charge"] = None
        calendar[day]["cards"].append(entry)
    return [
        {"day": d, "cards": v["cards"], "total_charge": v["total_charge"]}
        for d, v in sorted(calendar.items())
    ]

# ─── 現金支出の収集 ──────────────────────────────────────────────────────

def load_cash_expenses_from_graph(graph_file: str) -> list:
    """ナレッジグラフから現金支出を収集する。

    以下のノードから現金支出を抽出する:
    - type=購入希望 で status=購入済 かつ detail に「現金」を含む
    - type=出来事 で detail に「現金」と「円」を含む

    Returns:
        [{"label": "漫画", "amount": 30000, "source": "購入希望"}, ...]
    """
    if not os.path.exists(graph_file):
        return []

    with open(graph_file, "r", encoding="utf-8") as f:
        graph = json.load(f)

    nodes = graph.get("nodes", [])
    cash_expenses = []

    for n in nodes:
        ntype = n.get("type", "")
        detail = str(n.get("detail", ""))
        label = n.get("label", "")

        if ntype == "購入希望" and n.get("status") == "購入済" and "現金" in detail:
            amount = _extract_amount(detail, n.get("cost"))
            if amount > 0:
                cash_expenses.append({"label": label, "amount": amount, "source": "購入希望"})

        elif ntype == "出来事" and "現金" in detail and "円" in detail:
            amount = _extract_amount(detail)
            if amount > 0:
                cash_expenses.append({"label": label, "amount": amount, "source": "出来事"})

    cash_expenses.sort(key=lambda x: -x["amount"])
    if cash_expenses:
        total = sum(e["amount"] for e in cash_expenses)
        print(f"   💵 現金支出: {len(cash_expenses)}件 合計{total:,}円")
    return cash_expenses


def _extract_amount(detail: str, fallback_cost=None) -> int:
    """テキストから金額を抽出する。"""
    # 「30,000円」「45000円」のようなパターン
    match = re.search(r'([0-9,]+)円', detail)
    if match:
        try:
            return int(match.group(1).replace(',', ''))
        except ValueError:
            pass
    # フォールバック
    if fallback_cost is not None:
        try:
            return int(fallback_cost)
        except (ValueError, TypeError):
            pass
    return 0


# ─── AIアドバイス生成 ──────────────────────────────────────────────────

def generate_spending_advice(
    ctx: dict,
    card_charges_by_month: list,
    cash_expenses: list,
    summary: dict,
) -> list:
    """Gemini APIで家計アドバイスを生成する。

    Returns:
        [{"icon": "💡", "title": "...", "detail": "...", "severity": "info"}, ...]
    """
    # カード用途マップを作成
    card_usage_info = []
    for card in ctx.get("credit_cards", []):
        name = card.get("name", "")
        usage = card.get("usage", "")
        if usage:
            card_usage_info.append(f"- {name}: {usage}")

    today_str = datetime.now().strftime("%Y年%m月%d日")

    prompt = f"""あなたは家計アドバイザーです。以下の家計データを分析して、具体的なアドバイスを生成してください。

## 現在の日付
{today_str}

## 収支サマリー
- 月収: {summary.get('monthly_income', 0):,}円
- 固定費: {summary.get('monthly_fixed_costs', 0):,}円
- クレカ利用額: {summary.get('monthly_variable_estimate', 0):,}円
- 現金支出合計: {summary.get('cash_total', 0):,}円
- 月次余剰: {summary.get('monthly_surplus', 0):,}円
- 貯蓄率: {summary.get('savings_rate_pct', 0)}%

## カード別請求明細
{json.dumps(card_charges_by_month, ensure_ascii=False, indent=2)}

## カードの用途
{chr(10).join(card_usage_info) if card_usage_info else '用途情報なし'}

## 現金支出
{json.dumps(cash_expenses, ensure_ascii=False, indent=2)}

## 固定費の内訳
{json.dumps(ctx.get('fixed_costs', {}), ensure_ascii=False, indent=2)}

## 出力ルール
以下のJSON配列を出力してください。3〜6件程度のアドバイスを生成してください。
JSONのみ出力し余計な説明はしないでください。

出力形式:
[
  {{
    "icon": "絵文字1文字",
    "title": "アドバイスのタイトル",
    "detail": "具体的な説明（2〜3文）",
    "severity": "warning / info / success のいずれか"
  }}
]

## アドバイスの指針
- 特定のカードの利用額が多い場合、そのカードの用途を踏まえて使いすぎかどうか分析する
- 現金支出が多い場合は指摘する
- 貯蓄率が低い場合は改善策を提案する
- 良い点があれば褒める（severity: success）
- 具体的な金額を使って説明する
- severity は warning（注意）/ info（情報）/ success（良い点）の3段階
- 日本語で、丁寧だが簡潔に書く
"""

    print("   🤖 Gemini で家計アドバイスを生成中...")
    raw = call_gemini_api(prompt)

    try:
        advice = json.loads(raw)
        if isinstance(advice, list):
            print(f"   ✅ 家計アドバイス: {len(advice)}件")
            return advice
    except json.JSONDecodeError:
        try:
            match = re.search(r'\[.*\]', raw, re.DOTALL)
            if match:
                return json.loads(match.group())
        except Exception:
            pass

    print("   ⚠️  家計アドバイスのパースに失敗しました")
    return []


# ─── メイン分析 ────────────────────────────────────────────────────────

def analyze(
    ctx: dict,
    graph_file: str = DEFAULT_GRAPH_FILE,
    role_def_file: str = DEFAULT_ROLE_DEF,
) -> dict:
    """家計データを分析してレポートを生成する。"""
    current_year = datetime.now().year

    monthly_income = ctx.get("monthly_income", 0)
    monthly_fixed  = ctx.get("monthly_fixed_costs", 0)
    credit_cards   = ctx.get("credit_cards", [])

    # カード用途マップを作成
    card_usage_map = {}
    for card in credit_cards:
        name = _normalize_card_name(card.get("name", ""))
        usage = card.get("usage")
        if name and usage:
            card_usage_map[name] = usage

    # 月次クレカ請求をグラフから取得
    graph_charges = load_monthly_charges_from_graph(graph_file)

    # 月次収入をグラフから取得（日記から抽出されたもの）
    graph_income = load_monthly_income_from_graph(graph_file)
    if graph_income.get("total", 0) > 0:
        monthly_income = graph_income["total"]
        income_month = graph_income.get("month", "")
        print(f"   ✅ 収入を日記データで上書き: {monthly_income:,}円 ({income_month})")

    # 変動費：グラフにクレカ請求の実績があればその合計を使う
    if graph_charges:
        monthly_variable_estimate = sum(graph_charges.values())
        variable_note = "クレカ実績合計（日記から取得）"
    else:
        monthly_variable_estimate = DEFAULT_MONTHLY_VARIABLE_COST
        variable_note = "変動費は暫定値です"

    # 現金支出をグラフから収集
    cash_expenses = load_cash_expenses_from_graph(graph_file)
    cash_total = sum(e["amount"] for e in cash_expenses)

    # 月次収支サマリー（現金支出も加味）
    total_spending = monthly_fixed + monthly_variable_estimate + cash_total
    monthly_surplus = monthly_income - total_spending
    savings_rate = round(monthly_surplus / monthly_income * 100, 1) if monthly_income > 0 else 0

    # クレカカレンダー（グラフの請求額でmonthly_chargeを補完）
    for card in credit_cards:
        card_name = card.get("name", "")
        if not card.get("monthly_charge") and graph_charges:
            for gname, amount in graph_charges.items():
                if gname in card_name or card_name in gname:
                    card["monthly_charge"] = amount
                    break
    cc_calendar = build_credit_card_calendar(credit_cards)

    # ライフイベント予測（LLM）
    life_events = generate_life_events_forecast(ctx, graph_file, role_def_file)

    # カード別請求明細（当月・翌月、用途付き）
    card_charges_by_month = load_card_charges_by_month(graph_file, card_usage_map)

    # サマリーデータを構築
    summary = {
        "monthly_income": monthly_income,
        "monthly_fixed_costs": monthly_fixed,
        "monthly_variable_estimate": monthly_variable_estimate,
        "cash_total": cash_total,
        "monthly_surplus": monthly_surplus,
        "savings_rate_pct": savings_rate,
        "note": variable_note,
        "income_from_diary": bool(graph_income.get("total")),
        "charges_from_diary": bool(graph_charges),
    }

    # AIアドバイス生成（LLM）
    spending_advice = generate_spending_advice(
        ctx, card_charges_by_month, cash_expenses, summary
    )

    return {
        "generated_at": datetime.now().isoformat(),
        "summary": summary,
        "credit_card_calendar": cc_calendar,
        "card_charges_by_month": card_charges_by_month,
        "cash_expenses": cash_expenses,
        "spending_advice": spending_advice,
        "life_events_forecast": life_events,
    }


def main():
    parser = argparse.ArgumentParser(description="家計コンテキストを分析してレポートを生成する")
    parser.add_argument("--context",  default="finance_context.json",  help="入力JSONファイル")
    parser.add_argument("--graph",    default=DEFAULT_GRAPH_FILE,      help="ナレッジグラフJSON-LDファイル")
    parser.add_argument("--role-def", default=DEFAULT_ROLE_DEF,        help="ロール定義テキストファイル")
    parser.add_argument("--output",   default="finance_report.json",   help="出力JSONファイル")
    args = parser.parse_args()

    if not os.path.exists(args.context):
        print(f"❌ {args.context} が見つかりません。")
        return

    with open(args.context, "r", encoding="utf-8") as f:
        ctx = json.load(f)

    role_def = getattr(args, "role_def", DEFAULT_ROLE_DEF)
    report = analyze(ctx, graph_file=args.graph, role_def_file=role_def)

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"✅ {args.output} を出力しました")
    print(f"   月収: {report['summary']['monthly_income']:,}円")
    print(f"   月次余剰（暫定）: {report['summary']['monthly_surplus']:,}円")
    print(f"   貯蓄率（暫定）: {report['summary']['savings_rate_pct']}%")
    print(f"   ライフイベント予測: {len(report.get('life_events_forecast', []))}件")


if __name__ == "__main__":
    main()
