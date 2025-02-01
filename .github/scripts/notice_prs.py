import os
import requests
import json
import logging
from pathlib import Path
from typing import Any, Dict, List


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


def fetch_pull_requests(owner_name: str, repo_name: str) -> List[Dict[str, Any]]:
    api_url = f"https://api.github.com/repos/{owner_name}/{repo_name}/pulls"
    headers = {"Authorization": f"token {DEV_OPS_TOKEN}"}
    logging.info("Fetching Pull Requests from %s", api_url)

    try:
        response = requests.get(api_url, headers=headers)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        logging.error("Failed to fetch pull requests: %s", e)
        return []


def filter_prs_by_label(prs: List[Dict[str, Any]], label: str) -> List[Dict[str, Any]]:
    logging.info("Filtering PRs with label '%s'", label)
    filtered_prs = [
        {"html_url": pr["html_url"], "url": pr["url"]}
        for pr in prs
        if label in [l["name"] for l in pr.get("labels", [])] and not pr.get("draft", False)
    ]
    logging.info("Filtered %d PRs", len(filtered_prs))
    return filtered_prs


def categorize_prs_by_review_status(pr_url_datas: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    waiting_prs, complete_prs = [], []

    for pr_url_data in pr_url_datas:
        approved_reviewers_count = fetch_approved_reviewers_count(pr_url_data["url"])
        pr_url = pr_url_data["html_url"]

        if approved_reviewers_count < REVIEWER_COUNT_LIMIT:
            waiting_prs.append(
                {"pull_request_url": pr_url, "approved_reviewers_count": approved_reviewers_count}
            )
        else:
            complete_prs.append(
                {"pull_request_url": pr_url, "approved_reviewers_count": approved_reviewers_count}
            )

    logging.info("Categorized PRs: Waiting=%d, Complete=%d", len(waiting_prs), len(complete_prs))
    return {"waiting": waiting_prs, "complete": complete_prs}


def fetch_approved_reviewers_count(pr_url: str) -> int:
    api_url = f"{pr_url}/reviews"
    logging.info("Fetching reviews for PR: %s", pr_url)

    try:
        response = requests.get(api_url, headers={"Authorization": f"token {DEV_OPS_TOKEN}"})
        response.raise_for_status()
        reviews = response.json()

        # ユーザーIDで重複を排除
        approved_reviews = {
            review["user"]["id"]: review for review in reviews if review["state"] == "APPROVED"
        }

        # 重複を排除した承認者の数を返す
        return len(approved_reviews)
    except requests.exceptions.RequestException as e:
        logging.error("Failed to fetch reviews for PR %s: %s", pr_url, e)
        return 0


def format_pr_list(prs: List[Dict[str, Any]]) -> str:
    if not prs:
        return "なし"

    return "\n".join(f"- <{pr['pull_request_url']}> ( レビュー完了: {pr['approved_reviewers_count']}人 )" for pr in prs)


def send_slack_notification(waiting_prs: List[Dict[str, Any]], complete_prs: List[Dict[str, Any]], label: str, webhook_url: str):
    message = (
        f":page_facing_up: [{label}] - プルリクエストレビュー状況\n\n\n"
        "------------------------"
        f"*レビュー待ちのPR ( {len(waiting_prs)} 件 )*\n{format_pr_list(waiting_prs)}\n\n\n"
        f"*レビュー完了したPR ( {len(complete_prs)} 件 )*\n{format_pr_list(complete_prs)}"
    )

    payload = {"text": message}

    try:
        response = requests.post(webhook_url, json=payload, headers={"Content-Type": "application/json"})
        response.raise_for_status()
        logging.info("Notification sent successfully.")
    except requests.exceptions.RequestException as e:
        logging.error("Failed to send notification: %s", e)


def main():
    try:
        configs = load_configs()
    except Exception as e:
        logging.error("Failed to load config file: %s", e)
        return

    for config in configs:
        webhook_url = os.getenv(config.get("webhook_secret_name", ""))
        repo_name = config.get("repo_name")
        owner_name = config.get("owner_name")
        target_label = config.get("target_label")

        if not all([webhook_url, repo_name, owner_name, target_label]):
            logging.warning("Missing configuration for webhook_url, repo_name, owner_name, or target_label. Skipping...")
            continue

        all_pr_infos = fetch_pull_requests(owner_name, repo_name)
        if not all_pr_infos:
            logging.warning("No PRs found. Skipping...")
            continue

        pr_url_datas = filter_prs_by_label(all_pr_infos, target_label)
        categorized_prs = categorize_prs_by_review_status(pr_url_datas)

        send_slack_notification(categorized_prs["waiting"], categorized_prs["complete"], target_label, webhook_url)


if __name__ == "__main__":
    main()
