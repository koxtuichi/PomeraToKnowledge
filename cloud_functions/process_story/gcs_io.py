"""
gcs_io.py — Cloud StorageとGitHub APIへのI/Oを提供するモジュール

既存スクリプトのファイルI/Oをこのモジュール経由に差し替えることで、
ローカルファイルシステムへの依存をなくす。
"""
import os
import json
import base64
from google.cloud import storage
import requests

GCS_BUCKET = os.environ.get("GCS_BUCKET", "pomera-knowledge-data")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPO = os.environ.get("GITHUB_REPO", "")  # owner/repo 形式


def _get_bucket():
    """Cloud Storageバケットを取得する。"""
    client = storage.Client()
    return client.bucket(GCS_BUCKET)


def load_json_from_gcs(path: str) -> dict:
    """Cloud StorageからJSONファイルを読み込む。"""
    bucket = _get_bucket()
    blob = bucket.blob(path)
    if not blob.exists():
        print(f"⚠️ GCS上に {path} が見つかりません。空のデータを返します。")
        return {}
    content = blob.download_as_text(encoding="utf-8")
    return json.loads(content)


def save_json_to_gcs(path: str, data: dict):
    """Cloud StorageにJSONファイルを保存する。"""
    bucket = _get_bucket()
    blob = bucket.blob(path)
    content = json.dumps(data, ensure_ascii=False, indent=2)
    blob.upload_from_string(content, content_type="application/json")
    print(f"✅ GCSに保存しました: gs://{GCS_BUCKET}/{path}")


def load_text_from_gcs(path: str) -> str:
    """Cloud Storageからテキストファイルを読み込む。"""
    bucket = _get_bucket()
    blob = bucket.blob(path)
    if not blob.exists():
        print(f"⚠️ GCS上に {path} が見つかりません。")
        return ""
    return blob.download_as_text(encoding="utf-8")


def save_text_to_gcs(path: str, text: str):
    """Cloud Storageにテキストファイルを保存する。"""
    bucket = _get_bucket()
    blob = bucket.blob(path)
    blob.upload_from_string(text, content_type="text/plain; charset=utf-8")
    print(f"✅ GCSに保存しました: gs://{GCS_BUCKET}/{path}")


def push_file_to_github(file_path: str, content: str, message: str):
    """GitHub APIでファイルを更新する。

    既存ファイルのshaを取得してから更新する。
    ファイルが存在しない場合は新規作成する。
    """
    if not GITHUB_TOKEN or not GITHUB_REPO:
        print("⚠️ GITHUB_TOKEN または GITHUB_REPO が未設定。GitHub pushをスキップ。")
        return False

    api_url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{file_path}"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }

    # 既存ファイルのshaを取得
    sha = None
    resp = requests.get(api_url, headers=headers)
    if resp.status_code == 200:
        sha = resp.json().get("sha")

    # ファイルを更新
    payload = {
        "message": message,
        "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
    }
    if sha:
        payload["sha"] = sha

    resp = requests.put(api_url, headers=headers, json=payload)
    if resp.status_code in (200, 201):
        print(f"✅ GitHubに pushしました: {file_path}")
        return True
    else:
        print(f"❌ GitHub push失敗: {resp.status_code} {resp.text[:200]}")
        return False


def generate_graph_data_js(graph_data: dict) -> str:
    """graph_data.jsの内容を生成する。"""
    return (
        "// GRAPH_DATA_START\n"
        f"const GRAPH_DATA = {json.dumps(graph_data, ensure_ascii=False, indent=2)};\n"
        "// GRAPH_DATA_END\n"
    )


def list_gcs_files(prefix: str) -> list:
    """Cloud Storageの指定プレフィックス以下のファイル一覧を取得する。"""
    bucket = _get_bucket()
    blobs = bucket.list_blobs(prefix=prefix)
    return [blob.name for blob in blobs if not blob.name.endswith("/")]


def delete_from_gcs(path: str):
    """Cloud Storageからファイルを削除する。"""
    bucket = _get_bucket()
    blob = bucket.blob(path)
    if blob.exists():
        blob.delete()
        print(f"🗑️ GCSから削除しました: gs://{GCS_BUCKET}/{path}")
    else:
        print(f"⚠️ 削除対象が見つかりません: gs://{GCS_BUCKET}/{path}")
