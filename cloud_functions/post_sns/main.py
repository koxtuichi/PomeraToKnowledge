"""
main.py — Cloud Function エントリポイント：SNS自動投稿

Cloud Schedulerから1時間おきに呼ばれ、
承認済みの投稿を最適時間帯にThreadsに投稿する。

処理フロー:
  1. 現在時刻が投稿に適した時間帯かチェック
  2. approved/ から投稿キューを取得
  3. Threads APIで投稿
  4. posted/ に移動
"""
import os
import json
from datetime import datetime, timezone, timedelta

import functions_framework
import requests

import gcs_io

# 日本時間 (UTC+9)
JST = timezone(timedelta(hours=9))

# 最適投稿時間帯（JST）
OPTIMAL_POSTING_HOURS = {
    # 平日
    0: [7, 12, 19],  # 月曜
    1: [7, 12, 19],  # 火曜
    2: [7, 12, 19],  # 水曜
    3: [7, 12, 19],  # 木曜
    4: [7, 12, 19],  # 金曜
    # 週末
    5: [10, 19],     # 土曜
    6: [10, 19],     # 日曜
}


@functions_framework.http
def post_sns(request):
    """Cloud Schedulerから定期呼び出しされるエントリポイント。"""

    if request.method == "OPTIONS":
        headers = {
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "POST, GET",
            "Access-Control-Allow-Headers": "Content-Type",
            "Access-Control-Max-Age": "3600",
        }
        return ("", 204, headers)

    try:
        now_jst = datetime.now(JST)
        current_hour = now_jst.hour
        current_weekday = now_jst.weekday()

        # 強制投稿モード（テスト用）
        data = request.get_json(silent=True) or {}
        force = data.get("force", False)

        if not force:
            # 最適時間帯チェック
            optimal_hours = OPTIMAL_POSTING_HOURS.get(current_weekday, [7, 12, 19])
            if current_hour not in optimal_hours:
                return json.dumps({
                    "status": "skipped",
                    "reason": f"現在 {current_hour}時 は投稿時間帯外です。次回: {optimal_hours}"
                }, ensure_ascii=False), 200

        # 承認済みキューを取得
        approved_files = gcs_io.list_gcs_files("sns_queue/approved/")
        if not approved_files:
            return json.dumps({
                "status": "no_posts",
                "message": "承認済みの投稿がありません"
            }, ensure_ascii=False), 200

        posted_results = []
        for file_path in approved_files:
            if not file_path.endswith(".json"):
                continue

            queue_id = file_path.split("/")[-1].replace(".json", "")
            item = gcs_io.load_json_from_gcs(file_path)
            if not item:
                continue

            # 1回の実行で1投稿だけにする（スパム防止）
            post_text = item.get("generated_post", "")
            if not post_text:
                continue

            # Threads APIで投稿
            threads_result = _post_to_threads(post_text)

            if threads_result:
                item["posted_at"] = datetime.now(JST).isoformat()
                item["threads_post_id"] = threads_result.get("id")

                # posted/ に移動
                gcs_io.save_json_to_gcs(f"sns_queue/posted/{queue_id}.json", item)
                gcs_io.delete_from_gcs(file_path)

                posted_results.append({
                    "queue_id": queue_id,
                    "threads_id": threads_result.get("id"),
                    "post_text": post_text[:50] + "..."
                })
                print(f"✅ Threads投稿完了: {queue_id}")

                # 1投稿で終了（連投防止）
                break
            else:
                print(f"⚠️ Threads投稿失敗: {queue_id}")

        result = {
            "status": "ok",
            "posted_count": len(posted_results),
            "posts": posted_results,
        }
        return json.dumps(result, ensure_ascii=False), 200

    except Exception as e:
        import traceback
        print(f"❌ エラー: {e}\n{traceback.format_exc()}")
        return json.dumps({"error": str(e)}), 500


def _post_to_threads(text: str) -> dict:
    """Threads APIでテキストを投稿する。"""
    access_token = os.environ.get("THREADS_ACCESS_TOKEN")
    user_id = os.environ.get("THREADS_USER_ID")

    if not access_token or not user_id:
        print("⚠️ THREADS_ACCESS_TOKEN または THREADS_USER_ID が未設定です")
        print("   投稿をシミュレーションモードで実行します")
        # シミュレーション: トークン未設定時はダミー結果を返す
        return {"id": f"sim_{datetime.now().strftime('%Y%m%d%H%M%S')}", "simulated": True}

    try:
        # auto_publish_text=true で1コールで投稿
        url = f"https://graph.threads.net/v1.0/{user_id}/threads"
        payload = {
            "media_type": "TEXT",
            "text": text,
            "auto_publish_text": "true",
            "access_token": access_token,
        }

        response = requests.post(url, data=payload, timeout=30)
        response.raise_for_status()
        result = response.json()
        print(f"✅ Threads API 投稿成功: {result}")
        return result

    except Exception as e:
        print(f"❌ Threads API エラー: {e}")
        return None
