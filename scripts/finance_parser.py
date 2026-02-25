#!/usr/bin/env python3
"""
finance_parser.py — FINCTXメール本文を解析して finance_context.json に保存する。

使い方:
  python3 scripts/finance_parser.py --body "メール本文テキスト"
  python3 scripts/finance_parser.py --file path/to/finctx.txt
  FINCTX_BODY="..." python3 scripts/finance_parser.py  # 環境変数からbody取得（推奨）

GitHub Actionsからは環境変数 FINCTX_BODY に本文をセットして実行する。
"""
import os
import re
import json
import argparse
from datetime import datetime


# ─── デフォルトファイルパス ──────────────────────────────────────────
OUTPUT_FILE = "finance_context.json"


def parse_section(lines: list[str], heading: str) -> list[str]:
    """指定の見出し以降の行を、次の見出しが来るまで返す。"""
    in_section = False
    result = []
    for line in lines:
        stripped = line.strip()
        if stripped == f"## {heading}":
            in_section = True
            continue
        if in_section:
            if stripped.startswith("## "):
                break
            if stripped and not stripped.startswith("#"):
                result.append(stripped)
    return result


def parse_income(lines: list[str]) -> dict:
    """## 収入 セクションを解析して { source: amount } の辞書と合計を返す。"""
    sources = {}
    for line in lines:
        m = re.match(r"([^:]+):\s*([\d,]+)", line)
        if m:
            name = m.group(1).strip()
            amount = int(m.group(2).replace(",", ""))
            sources[name] = amount
    total = sum(sources.values())
    return {"sources": sources, "total": total}


def parse_credit_cards(lines: list[str]) -> list[dict]:
    """## クレカ セクションを解析。書式: 名前: 銀行, 毎月N日"""
    cards = []
    for line in lines:
        m = re.match(r"([^:]+):\s*([^,]+),\s*毎月(\d+)日", line)
        if m:
            cards.append({
                "name": m.group(1).strip(),
                "bank": m.group(2).strip(),
                "due_day": int(m.group(3))
            })
    return cards


def parse_wishlist(lines: list[str]) -> list[dict]:
    """## 欲しいもの セクションを解析。書式: 名前: 金額, 優先度:高/中/低"""
    items = []
    for line in lines:
        m = re.match(r"([^:]+):\s*([\d,]+),\s*優先度[：:](高|中|低)", line)
        if m:
            items.append({
                "item": m.group(1).strip(),
                "cost": int(m.group(2).replace(",", "")),
                "priority": m.group(3)
            })
    return sorted(items, key=lambda x: {"高": 0, "中": 1, "低": 2}[x["priority"]])


def parse_family(lines: list[str]) -> dict:
    """## 家族 セクションを解析。"""
    children = []
    education_scenario = "public"
    for line in lines:
        # 子供: 名前: XXXX年生まれ, 公立想定
        m = re.match(r"子供[・・](.+):\s*(\d{4})年生まれ", line)
        if m:
            children.append({
                "name": m.group(1).strip(),
                "birth_year": int(m.group(2))
            })
        # 学費シナリオ
        m2 = re.match(r"学費シナリオ[：:]\s*(.+)", line)
        if m2:
            scenario_text = m2.group(1).strip()
            if "私立" in scenario_text:
                education_scenario = "private"
            else:
                education_scenario = "public"
    return {"children": children, "education_scenario": education_scenario}


def parse_fixed_costs(lines: list[str]) -> dict:
    """## 固定費 セクションを解析。"""
    costs = {}
    for line in lines:
        m = re.match(r"([^:]+):\s*([\d,]+)", line)
        if m:
            name = m.group(1).strip()
            amount = int(m.group(2).replace(",", ""))
            costs[name] = amount
    return {"breakdown": costs, "total": sum(costs.values())}


def parse_finctx(text: str) -> dict:
    """FINCTXテキスト全体を解析して辞書を返す。"""
    lines = text.splitlines()

    income_lines = parse_section(lines, "\u53ce\u5165")
    card_lines   = parse_section(lines, "\u30af\u30ec\u30ab")
    family_lines = parse_section(lines, "\u5bb6\u65cf")
    fixed_lines  = parse_section(lines, "\u56fa\u5b9a\u8cbb")

    income      = parse_income(income_lines)
    fixed_costs = parse_fixed_costs(fixed_lines)
    family      = parse_family(family_lines)

    monthly_surplus = income["total"] - fixed_costs["total"]

    return {
        "generated_at": datetime.now().isoformat(),
        "income": income,
        "credit_cards": parse_credit_cards(card_lines),
        "family": family,
        "fixed_costs": fixed_costs,
        "monthly_income": income["total"],
        "monthly_fixed_costs": fixed_costs["total"],
        "monthly_surplus_before_variable": monthly_surplus
    }


def main():
    parser = argparse.ArgumentParser(description="FINCTXテキストを finance_context.json に変換する")
    group = parser.add_mutually_exclusive_group(required=False)
    group.add_argument("--body", help="FINCTXメール本文（文字列）")
    group.add_argument("--file", help="FINCTXテキストファイルのパス")
    parser.add_argument("--output", default=OUTPUT_FILE, help="出力先JSONファイルのパス")
    args = parser.parse_args()

    # 優先順位: --file > --body > 環境変数 FINCTX_BODY
    if args.file:
        with open(args.file, "r", encoding="utf-8") as f:
            text = f.read()
    elif args.body:
        text = args.body
    else:
        text = os.environ.get("FINCTX_BODY", "")
        if not text:
            print("❌ 本文が見つかりません。--body / --file / 環境変数 FINCTX_BODY のいずれかを指定してください。")
            return

    result = parse_finctx(text)

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"✅ finance_context.json を出力しました: {args.output}")
    print(f"   月収合計: {result['monthly_income']:,}円")
    print(f"   固定費合計: {result['monthly_fixed_costs']:,}円")
    print(f"   クレカ: {len(result['credit_cards'])}枚")
    print(f"   ※欲しいもの は日記から自動抽出されます")


if __name__ == "__main__":
    main()
