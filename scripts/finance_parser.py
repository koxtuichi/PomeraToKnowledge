#!/usr/bin/env python3
"""
finance_parser.py — FINCTX自由形式テキストをGeminiで解析してfinance_context.jsonに保存する。

書式不問。LLMが収入・クレカ・固定費・家族情報を抽出する。

GitHub Actionsからは FINCTX_BODY 環境変数に本文をセットして実行:
  python scripts/finance_parser.py --output finance_context.json
"""
import os, re, json, argparse, time
import requests
from datetime import datetime

GEMINI_API_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
DEFAULT_MODEL = "gemini-2.0-flash"


def call_gemini(prompt: str) -> str:
    api_key = os.environ.get("GOOGLE_API_KEY", "")
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY が設定されていません")
    url = GEMINI_API_ENDPOINT.format(model=DEFAULT_MODEL)
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json"},
    }
    for attempt in range(3):
        try:
            resp = requests.post(f"{url}?key={api_key}", json=payload, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            return data["candidates"][0]["content"]["parts"][0]["text"]
        except Exception as e:
            print(f"   ⚠️ Gemini API 試行{attempt+1}回目失敗: {e}")
            time.sleep(2)
    raise RuntimeError("Gemini API が3回とも失敗しました")


def parse_finctx_with_llm(text: str) -> dict:
    prompt = f"""以下は家計コンテキストの自由形式テキストです。このテキストから家計情報を抽出してJSONで返してください。

テキスト:
---
{text}
---

以下のJSONスキーマで返してください（値が不明な場合は空配列・0・空文字にすること）:
{{
  "income": {{
    "sources": {{"収入源名": 月額数値（税抜き・整数）}},
    "total": 月収合計（整数）
  }},
  "credit_cards": [
    {{
      "name": "カード名",
      "bank": "引き落とし銀行名",
      "due_day": 引き落とし日（数値）
    }}
  ],
  "family": {{
    "children": [
      {{
        "name": "子供の名前",
        "birth_year": 生年（整数）,
        "birth_month": 生月（整数、不明なら1）
      }}
    ],
    "education_scenario": "public または private"
  }},
  "fixed_costs": {{
    "breakdown": {{"費目名": 月額数値（整数）}},
    "total": 固定費合計（整数）
  }}
}}

注意:
- 収入は税抜き金額を使うこと（消費税抜きと書かれていたらその数値をそのまま使う）
- クレカは引き落とし日が全角数字で書かれていても半角整数に変換すること
- JSONのみ返すこと（説明文不要）
"""
    raw = call_gemini(prompt)
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned)
        cleaned = re.sub(r'```\s*$', '', cleaned).strip()
    parsed = json.loads(cleaned)

    # monthly_income / monthly_fixed_costs をトップレベルにも追加
    income_total = parsed.get("income", {}).get("total", 0)
    fixed_total = parsed.get("fixed_costs", {}).get("total", 0)
    parsed["generated_at"] = datetime.now().isoformat()
    parsed["monthly_income"] = income_total
    parsed["monthly_fixed_costs"] = fixed_total
    parsed["monthly_surplus_before_variable"] = income_total - fixed_total
    return parsed


def main():
    parser = argparse.ArgumentParser(description="FINCTXテキストを finance_context.json に変換する（LLM使用）")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--body", help="FINCTXメール本文（文字列）")
    group.add_argument("--file", help="FINCTXテキストファイルのパス")
    parser.add_argument("--output", default="finance_context.json", help="出力先JSONファイルのパス")
    args = parser.parse_args()

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

    print("🤖 Gemini でFINCTXを解析中...")
    result = parse_finctx_with_llm(text)

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"✅ finance_context.json を出力しました: {args.output}")
    print(f"   月収合計: {result['monthly_income']:,}円")
    print(f"   固定費合計: {result['monthly_fixed_costs']:,}円")
    print(f"   クレカ: {len(result.get('credit_cards', []))}枚")
    print(f"   子供: {len(result.get('family', {}).get('children', []))}人")


if __name__ == "__main__":
    main()
