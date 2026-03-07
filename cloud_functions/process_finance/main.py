"""
main.py — Cloud Function エントリポイント：家計コンテキスト解析

GASからHTTPでPOSTされた FINCTXメールの本文を受け取り、
家計コンテキストを解析してfinance_context.jsonを更新する。
さらにfinance_analyzer.pyで分析レポートを生成。

処理フロー:
  1. リクエストから家計テキストを取得
  2. Geminiで収入・クレカ・固定費を解析
  3. Cloud Storageにfinance_context.jsonを保存
  4. finance_analyzer.pyで分析レポートを生成
  5. finance_report.jsonをCloud Storageに保存
  6. GitHubにも保存
"""
import os
import json
import re
from datetime import datetime

import functions_framework

import gcs_io
import finance_parser
import finance_analyzer


@functions_framework.http
def process_finance(request):
    """GASからHTTPで呼ばれる家計処理エントリポイント。"""

    if request.method == "OPTIONS":
        headers = {
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "POST",
            "Access-Control-Allow-Headers": "Content-Type",
            "Access-Control-Max-Age": "3600",
        }
        return ("", 204, headers)

    try:
        data = request.get_json(silent=True)
        if not data:
            return json.dumps({"error": "リクエストボディが空です"}), 400

        body = data.get("body", "")
        subject = data.get("subject", "")

        if not body:
            return json.dumps({"error": "メール本文が空です"}), 400

        print(f"💰 家計コンテキストを受信: 件名={subject}, 文字数={len(body)}")

        # ── Geminiで家計データを解析 ──
        print("🤖 Geminiで家計データを解析中...")
        ctx = finance_parser.parse_finctx_with_llm(body)

        if not ctx:
            return json.dumps({"error": "家計データの解析に失敗しました"}), 500

        print(f"✅ 解析完了: 月収={ctx.get('monthly_income', 0):,}円, クレカ={len(ctx.get('credit_cards', []))}枚")

        # ── Cloud Storageに保存 ──
        gcs_io.save_json_to_gcs("finance_context.json", ctx)

        # ── finance_analyzer.py で分析レポートを生成 ──
        print("📊 家計分析レポートを生成中...")
        try:
            # finance_analyzerはファイルパスでグラフを読むので、
            # Cloud Storageから一時ファイルとして取得
            graph_data = gcs_io.load_json_from_gcs("knowledge_graph.jsonld")
            role_def = gcs_io.load_text_from_gcs("role_definition.txt")

            # 一時ファイルに書き出して分析を実行
            import tempfile
            with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonld', delete=False, encoding='utf-8') as gf:
                json.dump(graph_data, gf, ensure_ascii=False)
                graph_tmp = gf.name

            with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as rf:
                rf.write(role_def)
                role_tmp = rf.name

            report = finance_analyzer.analyze(
                ctx=ctx,
                graph_file=graph_tmp,
                role_def_file=role_tmp
            )

            # 一時ファイルの削除
            os.unlink(graph_tmp)
            os.unlink(role_tmp)

            if report:
                gcs_io.save_json_to_gcs("finance_report.json", report)
                print("✅ 家計分析レポートを保存しました")

        except Exception as e:
            print(f"⚠️ 家計分析レポートの生成に失敗: {e}")
            report = None

        # ── GitHubにも保存 ──
        gcs_io.push_file_to_github(
            "finance_context.json",
            json.dumps(ctx, ensure_ascii=False, indent=2),
            f"Auto-sync: Finance context update [skip ci]"
        )

        if report:
            gcs_io.push_file_to_github(
                "finance_report.json",
                json.dumps(report, ensure_ascii=False, indent=2),
                f"Auto-sync: Finance report update [skip ci]"
            )

        result = {
            "status": "ok",
            "monthly_income": ctx.get("monthly_income", 0),
            "monthly_fixed_costs": ctx.get("monthly_fixed_costs", 0),
            "credit_cards": len(ctx.get("credit_cards", [])),
            "has_report": report is not None,
        }
        print(f"✅ 処理完了: {json.dumps(result, ensure_ascii=False)}")
        return json.dumps(result, ensure_ascii=False), 200

    except Exception as e:
        import traceback
        print(f"❌ エラー: {e}\n{traceback.format_exc()}")
        return json.dumps({"error": str(e)}), 500
