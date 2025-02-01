import os
import requests
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Tuple, Optional


# 事前準備
# 1. slack app を作成(通知したいチャンネル分作成する)
# 2. github で token を生成する
# 3. github の setting からシークレットを登録(webhookURL, token)


# ログの設定
logging.basicConfig(level=logging.INFO)

# 定数
CONFIG_FILE_PATH = ".github/scripts/config.json"
DEV_OPS_TOKEN = os.getenv("DEV_OPS_TOKEN")
REVIEWER_COUNT_LIMIT = 1


def load_configs(file_path: str = CONFIG_FILE_PATH) -> List[Dict[str, Any]]:
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {file_path}")

    try:
        with path.open("r", encoding="utf-8") as file:
            return json.load(file)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON format in {file_path}: {e}")


def fetch_pr_infos(owner_name: str, repo_name: str) -> List[Dict[str, Any]]:
    api_url = f"https://api.github.com/repos/{owner_name}/{repo_name}/pulls"
    headers = {"Authorization": f"token {DEV_OPS_TOKEN}"}
    save_to_file = "all_prs.json"
    logging.info("Fetching Pull Requests from %s", api_url)

    try:
        response = requests.get(api_url, headers=headers)
        response.raise_for_status()
        pr_infos = response.json()

        with open(save_to_file, "w", encoding="utf-8") as file:
            json.dump(pr_infos, file, indent=2)
        logging.info("PRデータを %s に保存しました", save_to_file)

        return pr_infos
    except requests.exceptions.RequestException as e:
        logging.error("PRの取得に失敗しました: %s", e)
        return []


def fetch_pr_url_datas(pr_infos: List[Dict[str, Any]], label: str) -> List[Dict[str, Any]]:
    logging.info("Filtering PRs with label '%s'.", label)

    pr_url_datas = []

    for pr_info in pr_infos:
        labels = [l["name"] for l in pr_info.get("labels", [])]
        is_draft = pr_info.get("draft", False)

        if label in labels and not is_draft:
            pr_url_data = {
                "html_url": pr_info["html_url"],
                "url": pr_info["url"],
            }
            pr_url_datas.append(pr_url_data)

    logging.info("Fetch completed.")
    return pr_url_datas


def filter_and_categorize_prs(pr_url_datas: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    logging.info("Filtering PRs with label '%s'...", label)
    headers={"Content-Type": "application/json"}
    waiting_prs = []
    complete_prs = []

    for pr_url_data in pr_url_datas:
        approved_reviews_count = fetch_pr_reviews(pr_url_data["url"], headers)

        pr_url = pr_url_data["html_url"]
        if len(reviewers) < REVIEWER_COUNT_LIMIT:
            waiting_prs.append(pr_url)
        else:
            complete_prs.append(pr_url)
  

    logging.info("Filtering completed. Waiting: %d, Complete: %d", len(waiting_prs), len(complete_prs))
    return waiting_prs, complete_prs


def fetch_pr_reviews(base_url: str, headers: Dict[str, str]) -> List[Dict[str, Any]]:
    api_url = f"{base_url}/reviews"
    logging.info("Fetching Pull Request reviews from %s", api_url)
    save_to_file = "pr_reviews.json"

    try:
        response = requests.get(api_url, headers=headers)
        response.raise_for_status()  # ステータスコードが200以外の場合、例外が発生

        pr_reviews = response.json()

        # 承認されたレビューの人数をカウント
        approved_reviews_count = len([review for review in pr_reviews if review["state"] == "APPROVED"])

        logging.info("取得したレビュー数: %d, 承認されたレビュー数: %d", len(pr_reviews), approved_reviews_count)

        return approved_reviews_count

    except requests.exceptions.RequestException as e:
        logging.error("PRレビューの取得に失敗しました: %s", e)
        return 0


def format_notification_message(prs: List[Dict[str, Any]]) -> str:
    if not prs:
        return ":tada: 該当するPRはありません！ :tada:"
    
    return "\n".join(f"- <{pr['html_url']}>  (レビュー完了: {pr['requested_reviewers_count']}人)" for pr in prs)


def send_notification(waiting_prs: List[Dict[str, Any]], complete_prs: List[Dict[str, Any]], label: str, webhook_url: str):
    message = (
        f":page_facing_up: [ {label} ] - プルリクエストレビュー状況\n\n\n"
        "------------------------\n"
        f"*レビュー待ちのPR  ( {len(waiting_prs)} 件 )*\n{format_notification_message(waiting_prs)}\n\n\n"
        f"*レビューが完了しているPR ( {len(complete_prs)} 件 )*\n{format_notification_message(complete_prs)}"
    )

    payload = {"text": message}

    try:
        response = requests.post(webhook_url, json=payload, headers={"Content-Type": "application/json"})
        response.raise_for_status()
        logging.info("メッセージが送信されました。")
    except requests.exceptions.RequestException as e:
        logging.error("送信に失敗しました: %s", e)


def main():
    try:
        configs = load_configs()
    except Exception as e:
        logging.error("設定ファイルの読み込みに失敗しました: %s", e)
        return

    for config in configs:
        webhook_url = os.getenv(config.get("webhook_secret_name", ""))
        repo_name = config.get("repo_name")
        owner_name = config.get("owner_name")
        target_label = config.get("target_label")

        if not webhook_url:
            logging.warning("webhook_urlが見つかりません。スキップします...")
            continue
        if not repo_name:
            logging.warning("repo_nameが見つかりません。スキップします...")
            continue
        if not owner_name:
            logging.warning("owner_nameが見つかりません。スキップします...")
            continue
        if not target_label:
            logging.warning("target_labelが見つかりません。スキップします...")
            continue

        base_url = f"https://api.github.com/repos/{owner_name}/{repo_name}/pulls"
        headers = {"Authorization": f"token {DEV_OPS_TOKEN}"}

        all_pr_infos = fetch_pr_infos(owner_name, repo_name)
        if not all_pr_infos:
            logging.warning("PRが取得できませんでした。スキップします...")
            continue

        pr_url_datas = fetch_pr_url_datas(all_pr_infos, target_label)

        send_notification(waiting_prs, complete_prs, target_label, webhook_url)


if __name__ == "__main__":
    main()



