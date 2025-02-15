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
REVIEW_COMPLETE_LIMIT = 1
REVIEW_STATUS_WAITING = "WAITING"
REVIEW_STATUS_COMPLETE = "COMPLETE"


class Config:
    def __init__(self,
                 owner_name: str,
                 repo_name: str,
                 target_label: str,
                 webhook_url: str):
        # バリデーション
        if not owner_name:
            raise ValueError("owner_name cannot be empty")
        if not repo_name:
            raise ValueError("repo_name cannot be empty")
        if not target_label:
            raise ValueError("target_label cannot be empty")
        if not webhook_url:
            raise ValueError("webhook_url cannot be empty")
        self.owner_name = owner_name
        self.repo_name = repo_name
        self.target_label = target_label
        self.webhook_url = webhook_url

class PullRequest:
    def __init__(self,
                 url: str,
                 html_url: str,
                 isDraft: bool,
                 label_names: list):
        # バリデーション
        if not url:
            raise ValueError("url cannot be empty")
        if not html_url:
            raise ValueError("html_url cannot be empty")
        if isDraft is None:
            raise ValueError("isDraft cannot be None")
        if not label_names:
            raise ValueError("label_names cannot be empty")
        self.url = url
        self.html_url = html_url
        self.isDraft = isDraft
        self.label_names = label_names

class ReviewResult:
    def __init__(self,
                 pull_request_url: str,
                 approve_count: int):
        # バリデーション
        if not pull_request_url:
            raise ValueError("url cannot be empty")
        if approve_count < 0:
            raise ValueError("approve_count cannot be less than 0")
        self.pull_request_url = pull_request_url
        self.approve_count = approve_count


def load_configs(file_path: str = CONFIG_FILE_PATH) -> List[Config]:
    logging.info("Loading config file: %s", file_path)
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {file_path}")
    try:
        with path.open("r", encoding="utf-8") as file:
            config_json_list = json.load(file)
            # Config情報はリスト形式を想定しているため、リストでない場合はエラーを返す
            if not isinstance(config_json_list, list):
                raise TypeError("Config file must be a list of objects")
            config_list = [
                Config(
                    owner_name=config_json.get('owner_name', ''),
                    repo_name=config_json.get('repo_name', ''),
                    target_label=config_json.get('target_label', ''),
                    webhook_url=os.getenv(config_json.get('webhook_secret_name', ''))
                )
                for config_json in config_json_list
            ]
            return config_list
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON format in {file_path}: {e}")
    except TypeError as e:
        raise ValueError(f"Incorrect data format in {file_path}: {e}")


def get_pull_request_list(owner_name: str, repo_name: str) -> List[PullRequest]:
    api_url = f"https://api.github.com/repos/{owner_name}/{repo_name}/pulls"
    headers = {"Authorization": f"token {DEV_OPS_TOKEN}"}
    logging.info("Fetching Pull Requests from %s", api_url)

    try:
        response = requests.get(api_url, headers=headers)
        response.raise_for_status()
        pull_request_list = [
            PullRequest(
                url=response_json.get("url", ""),
                html_url=response_json.get("html_url", ""),
                isDraft=response_json.get("draft", False),
                label_names=[label.get("name", "") for label in response_json.get("labels", [])]
            )
            for response_json in response.json()
        ]
        return pull_request_list

    except requests.RequestException as e:
        logging.error("Failed to fetch pull requests: %s", e, exc_info=True)
        raise


def filter_pull_request(pull_request_list: List[PullRequest], label: str) -> List[PullRequest]:
    logging.info("Filtering PRs by label: %s", label)
    filtered_pull_request_list = [
        pull_request
        for pull_request in pull_request_list
        if (label in [label_name for label_name in pull_request.label_names]) and not pull_request.isDraft
    ]
    return filtered_pull_request_list


def get_review_result(pull_request_list: List[PullRequest]) -> Dict[str, List[ReviewResult]]:
    logging.info("Getting review results")
    waiting_prs, complete_prs = [], []

    for pull_request in pull_request_list:
        approve_count = get_approve_count(pull_request.url)
        review_result = ReviewResult(pull_request.html_url, approve_count)

        if approve_count < REVIEW_COMPLETE_LIMIT:
            waiting_prs.append(review_result )
        else:
            complete_prs.append(review_result)

    return {REVIEW_STATUS_WAITING: waiting_prs, REVIEW_STATUS_COMPLETE: complete_prs}


def get_approve_count(url: str) -> int:
    api_url = f"{url}/reviews"
    try:
        response = requests.get(api_url, headers={"Authorization": f"token {DEV_OPS_TOKEN}"})
        response.raise_for_status()
        response_json = response.json()

        # ユーザーIDで重複を排除
        approved_reviews = {
            review["user"]["id"]: review
            for review in response_json if review["state"] == "APPROVED"
        }

        # 重複を排除した承認者の数を返す
        return len(approved_reviews)
    except requests.RequestException as e:
        logging.error("Failed to fetch reviews for PR %s: %s", api_url, e)
        raise


def format_notification_message(review_results: List[ReviewResult]) -> str:
    if not review_results:
        return "なし"

    return "\n".join(f"- <{review_result.pull_request_url}> ( レビュー完了: {review_result.approve_count}人 )" for review_result in review_results)


def send_slack_notification(waiting_prs: List[ReviewResult], complete_prs: List[ReviewResult], label: str, webhook_url: str):
    logging.info("Sending notification to Slack")
    message = (
        f":page_facing_up: [{label}] プルリクエストレビュー状況\n\n"
        "------------------------\n"
        f"*レビュー待ちPR ( {len(waiting_prs)} 件 )*\n{format_notification_message(waiting_prs)}\n\n\n"
        f"*レビュー完了PR ( {len(complete_prs)} 件 )*\n{format_notification_message(complete_prs)}"
    )
    payload = {"text": message}

    try:
        response = requests.post(webhook_url, json=payload, headers={"Content-Type": "application/json"})
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        logging.error("Failed to send notification: %s", e)


def main():
    try:
        configs = load_configs()
        for config in configs:
            pull_request_list = get_pull_request_list(config.owner_name, config.repo_name)
            if not pull_request_list:
                logging.warning("No PRs found. Skipping...")
                continue

            filtered_pull_request_list = filter_pull_request(pull_request_list, config.target_label)
            review_result = get_review_result(filtered_pull_request_list)

            send_slack_notification(
                waiting_prs = review_result[REVIEW_STATUS_WAITING],
                complete_prs = review_result[REVIEW_STATUS_COMPLETE],
                label = config.target_label,
                webhook_url = config.webhook_url
            )

    except Exception as e:
        logging.error("An error occurred: %s", e, exc_info=True)
        return

if __name__ == "__main__":
    main()
