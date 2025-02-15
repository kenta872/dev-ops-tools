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



class Config:
    def __init__(self,
                 owner_name: str,
                 repo_name: str,
                 target_label: str,
                 webhook_secret_name: str):
        # 空文字やNoneを防ぐバリデーション
        if not owner_name:
            raise ValueError("owner_name cannot be empty")
        if not repo_name:
            raise ValueError("repo_name cannot be empty")
        if not target_label:
            raise ValueError("target_label cannot be empty")
        if not webhook_secret_name:
            raise ValueError("webhook_secret_name cannot be empty")
        self.owner_name = owner_name
        self.repo_name = repo_name
        self.target_label = target_label
        self.webhook_secret_name = webhook_secret_name

class PullRequest:
    def __init__(self,
                 url: str,
                 html_url: str,
                 draft: bool,
                 label_names: list):
        # 空文字やNoneを防ぐバリデーション
        if not url:
            raise ValueError("url cannot be empty")
        if not html_url:
            raise ValueError("html_url cannot be empty")
        if draft is None:
            raise ValueError("draft cannot be None")
        if not label_names:
            raise ValueError("label_names cannot be empty")
        self.url = url
        self.html_url = html_url
        self.draft = draft
        self.label_names = label_names

def load_configs(file_path: str = CONFIG_FILE_PATH) -> List[Config]:
    logging.info("Loading config file: %s", file_path)
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {file_path}")
    try:
        with path.open("r", encoding="utf-8") as file:
            config_json_list = json.load(file)
            config_list = [
                Config(owner_name=config_json.get('owner_name', ''),
                       repo_name=config_json.get('repo_name', ''),
                       target_label=config_json.get('target_label', ''),
                       webhook_secret_name=os.getenv(config_json.get('webhook_secret_name', '')))
                for config_json in config_json_list
            ]
            return config_list
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON format in {file_path}: {e}")
    except TypeError as e:
        raise ValueError(f"Incorrect data format in {file_path}: {e}")


def fetch_pull_requests(owner_name: str, repo_name: str) -> List[PullRequest]:
    api_url = f"https://api.github.com/repos/{owner_name}/{repo_name}/pulls"
    headers = {"Authorization": f"token {DEV_OPS_TOKEN}"}
    logging.info("Fetching Pull Requests from %s", api_url)

    try:
        response = requests.get(api_url, headers=headers)
        response.raise_for_status()
        pull_requests = [
            PullRequest(
                url=pr_data.get("url", ""),
                html_url=pr_data.get("html_url", ""),
                draft=pr_data.get("draft", False),
                label_names=[label.get("name", "") for label in pr_data.get("labels", [])]
            )
            for pr_data in response.json()
        ]
        return pull_requests

    except requests.RequestException as e:
        logging.error("Failed to fetch pull requests: %s", e, exc_info=True)
        raise


def filter_pull_request(pull_request_list: List[PullRequest], label: str) -> List[PullRequest]:
    filtered_pulll_request_list = [
        {"html_url": pull_request.html_url, "url": pull_request.url}
        for pull_request in pull_request_list
        if label in [label_name for label_name in pull_request.label_names] and not pull_request.draft
    ]
    return filtered_pulll_request_list


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
        "------------------------\n"
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
        for config in configs:
            pull_request_list = fetch_pull_requests(config.owner_name, config.repo_name)
            if not pull_request_list:
                logging.warning("No PRs found. Skipping...")
                continue

            pr_url_datas = filter_pull_request(pull_request_list, config.target_label)
            logging.info("Fetched %d PRs", len(pr_url_datas))
            # categorized_prs = categorize_prs_by_review_status(pr_url_datas)

            # send_slack_notification(categorized_prs["waiting"], categorized_prs["complete"], target_label, webhook_url)

    except Exception as e:
        logging.error("An error occurred: %s", e, exc_info=True)
        return

if __name__ == "__main__":
    main()
