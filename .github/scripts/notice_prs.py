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


def fetch_prs(api_url: str, headers: Dict[str, str], save_to_file: Optional[str] = None) -> List[Dict[str, Any]]:
    logging.info("Fetching Pull Requests from %s", api_url)

    try:
        response = requests.get(api_url, headers=headers)
        response.raise_for_status()
        prs = response.json()

        if save_to_file:
            with open(save_to_file, "w", encoding="utf-8") as file:
                json.dump(prs, file, indent=2)
            logging.info("PRデータを %s に保存しました", save_to_file)

        return prs
    except requests.exceptions.RequestException as e:
        logging.error("PRの取得に失敗しました: %s", e)
        return []


def filter_and_categorize_prs(prs: List[Dict[str, Any]], label: str) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    logging.info("Filtering PRs with label '%s'...", label)

    waiting_prs = []
    complete_prs = []

    for pr in prs:
        labels = [l["name"] for l in pr.get("labels", [])]
        is_draft = pr.get("draft", True)
        reviewers = pr.get("requested_reviewers", [])

        if label in labels and not is_draft:
            pr_data = {
                "html_url": pr["html_url"],
                "requested_reviewers_count": len(reviewers),
            }
            if len(reviewers) < REVIEWER_COUNT_LIMIT:
                waiting_prs.append(pr_data)
            else:
                complete_prs.append(pr_data)

    logging.info("Filtering completed. Waiting: %d, Complete: %d", len(waiting_prs), len(complete_prs))
    return waiting_prs, complete_prs


def format_notification_message(prs: List[Dict[str, Any]]) -> str:
    if not prs:
        return ":tada: 該当するPRはありません！ :tada:"
    
    return "\n".join(f"- <{pr['html_url']}>  (レビュー完了: {pr['requested_reviewers_count']}人)" for pr in prs)


def send_notification(waiting_prs: List[Dict[str, Any]], complete_prs: List[Dict[str, Any]], label: str, webhook_url: str):
    message = (
        f":page_facing_up: [ {label} ] - プルリクエストレビュー状況\n\n\n"
        "------------------------\n"
        f"*レビュー待ちのPR*\n{format_notification_message(waiting_prs)} ( {waiting_prs.len} 件 )\n\n\n"
        f"*レビューが完了しているPR*\n{format_notification_message(complete_prs)}( {complete_prs.len} 件 )"
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

        all_prs = fetch_prs(base_url, headers, save_to_file="all_prs.json")
        if not all_prs:
            logging.warning("PRが取得できませんでした。スキップします...")
            continue

        waiting_prs, complete_prs = filter_and_categorize_prs(all_prs, target_label)

        send_notification(waiting_prs, complete_prs, target_label, webhook_url)


if __name__ == "__main__":
    main()



