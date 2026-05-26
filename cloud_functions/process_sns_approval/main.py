"""
main.py — Cloud Function エントリポイント：SNS承認処理

HTTPで承認通知を受け取り、
SNS投稿キューをpending→approvedに移動する。

処理フロー:
  1. リクエストからキューIDを取得（または全pendingを承認）
  2. Cloud Storageの pending/ から読込
  3. approved/ に移動（approved_atを記録）
  4. pending/ から削除
"""
import json
from datetime import datetime

import functions_framework

import gcs_io


@functions_framework.http
def process_sns_approval(request):
    """承認通知で呼ばれるエントリポイント。"""

    if request.method == "OPTIONS":
        headers = {
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "POST",
            "Access-Control-Allow-Headers": "Content-Type",
            "Access-Control-Max-Age": "3600",
        }
        return ("", 204, headers)

    try:
        data = request.get_json(silent=True) or {}

        # 特定のキューIDが指定された場合はそれだけ承認
        queue_id = data.get("queue_id")
        # 指定がなければ全pendingを承認
        approve_all = data.get("approve_all", False)

        approved_ids = []

        if queue_id:
            # 単一承認
            ok = _approve_item(queue_id)
            if ok:
                approved_ids.append(queue_id)
        elif approve_all:
            # 全件承認
            approved_ids = _approve_all_pending()
        else:
            # デフォルト: 全件承認
            approved_ids = _approve_all_pending()

        result = {
            "status": "ok",
            "approved_count": len(approved_ids),
            "approved_ids": approved_ids
        }
        print(f"✅ SNS承認完了: {json.dumps(result, ensure_ascii=False)}")
        return json.dumps(result, ensure_ascii=False), 200

    except Exception as e:
        import traceback
        print(f"❌ エラー: {e}\n{traceback.format_exc()}")
        return json.dumps({"error": str(e)}), 500


def _approve_item(queue_id: str) -> bool:
    """単一の投稿キューをpending→approvedに移動する。"""
    item = gcs_io.load_json_from_gcs(f"sns_queue/pending/{queue_id}.json")
    if not item:
        print(f"⚠️ キューID {queue_id} がpendingに見つかりません")
        return False

    item["approved_at"] = datetime.now().isoformat()

    # approvedに保存
    gcs_io.save_json_to_gcs(f"sns_queue/approved/{queue_id}.json", item)

    # pendingから削除
    gcs_io.delete_from_gcs(f"sns_queue/pending/{queue_id}.json")

    print(f"✅ {queue_id} を承認しました")
    return True


def _approve_all_pending() -> list:
    """全pendingアイテムを承認する。"""
    pending_files = gcs_io.list_gcs_files("sns_queue/pending/")
    approved_ids = []

    for file_path in pending_files:
        if not file_path.endswith(".json"):
            continue
        # ファイル名からキューIDを抽出
        queue_id = file_path.split("/")[-1].replace(".json", "")
        if _approve_item(queue_id):
            approved_ids.append(queue_id)

    return approved_ids
