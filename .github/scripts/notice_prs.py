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
    def __init__(self, owner_name: str, repo_name: str, target_label: str, webhook_url: str):
        self.owner_name = owner_name
        self.repo_name = repo_name
        self.target_label = target_label
        self.webhook_url = webhook_url
        self._validate()

    def _validate(self):
        if not all([self.owner_name, self.repo_name, self.target_label, self.webhook_url]):
            raise ValueError("All Config fields must be non-empty")

class PullRequest:
    def __init__(self, assignee_id: int, url: str, html_url: str, is_draft: bool, label_names: List[str]):
        self.assignee_id = assignee_id
        self.url = url
        self.html_url = html_url
        self.is_draft = is_draft
        self.label_names = label_names
        self._validate()

    def _validate(self):
        if not all([self.url, self.html_url, self.label_names]) or self.is_draft is None:
            raise ValueError("Invalid PullRequest data")

class ReviewResult:
    def __init__(self, pull_request_url: str, reviewed_count: int, approved_count: int, commented_count: int):
        self.pull_request_url = pull_request_url
        self.reviewed_count = reviewed_count
        self.approved_count = approved_count
        self.commented_count = commented_count
        self._validate()

    def _validate(self):
        if not self.pull_request_url or self.reviewed_count < 0 or self.approved_count < 0 or self.commented_count < 0:
            raise ValueError("Invalid ReviewResult data")


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
            return [
                Config(
                    owner_name = config_json["owner_name"],
                    repo_name = config_json["repo_name"],
                    target_label = config_json["target_label"],
                    webhook_url = os.getenv(config_json["webhook_secret_name"], "")
                )
                for config_json in config_json_list
            ]
    except (json.JSONDecodeError, TypeError) as e:
        raise ValueError(f"Invalid config file format: {e}")


def get_pull_request_list(owner_name: str, repo_name: str) -> List[PullRequest]:
    api_url = f"https://api.github.com/repos/{owner_name}/{repo_name}/pulls"
    headers = {"Authorization": f"token {DEV_OPS_TOKEN}"}
    logging.info("Fetching PRs from %s", api_url)
    try:
        response = requests.get(api_url, headers=headers)
        response.raise_for_status()
        return [
            PullRequest(
                assignee_id=pr["assignee"]["id"],
                url=pr["url"],
                html_url=pr["html_url"],
                is_draft=pr.get("draft", False),
                label_names=[label["name"] for label in pr.get("labels", [])]
            )
            for pr in response.json()
        ]
    except requests.RequestException as e:
        logging.error("Failed to fetch PRs: %s", e, exc_info=True)
        raise


def filter_pull_request(pull_request_list: List[PullRequest], label: str) -> List[PullRequest]:
    return [pr for pr in pull_request_list if label in pr.label_names and not pr.is_draft]


def get_review_result(pull_request_list: List[PullRequest]) -> Dict[str, List[ReviewResult]]:
    waiting_prs, complete_prs = [], []
    for pr in pull_request_list:
        review_result = get_review_counts(pr)
        if review_result.reviewed_count == 0:
            waiting_prs.append(review_result)
        else:
            complete_prs.append(review_result)
    return {REVIEW_STATUS_WAITING: waiting_prs, REVIEW_STATUS_COMPLETE: complete_prs}


def get_review_counts(pr: PullRequest) -> ReviewResult:
    api_url = f"{pr.url}/reviews"
    headers = {"Authorization": f"token {DEV_OPS_TOKEN}"}
    try:
        response = requests.get(api_url, headers=headers)
        response.raise_for_status()
        
        reviews = response.json()
        latest_review_state = {}

        for review in reviews:
            user_id = review["user"]["id"]
            if user_id == pr.assignee_id:
                continue
            latest_review_state[user_id] = review["state"]

        approved_users = {user_id for user_id, state in latest_review_state.items() if state == "APPROVED"}
        commented_users = {user_id for user_id, state in latest_review_state.items() if state == "COMMENTED"}

        return ReviewResult(pr.html_url, len(latest_review_state), len(approved_users), len(commented_users))
    except requests.RequestException as e:
        logging.error("Failed to fetch reviews: %s", e)
        raise


def format_notification_message(review_results: List[ReviewResult]) -> str:
    if not review_results:
        return "なし"

    return "\n".join(f"- <{review_result.pull_request_url}> ( approve: {review_result.approved_count}人, comment: {review_result.commented_count}人 )" for review_result in review_results)


def send_slack_notification(waiting_prs: List[ReviewResult], complete_prs: List[ReviewResult], label: str, webhook_url: str):
    logging.info("Sending notification to Slack")
    message = (
        f":page_facing_up: [{label}] プルリクエストレビュー状況\n\n"
        "------------------------\n"
        f"*未レビューPR ( {len(waiting_prs)} 件 )*\n{format_notification_message(waiting_prs)}\n\n\n"
        f"*レビュー中PR ( {len(complete_prs)} 件 )*\n{format_notification_message(complete_prs)}"
    )
    payload = {"text": message}

    try:
        response = requests.post(webhook_url, json=payload, headers={"Content-Type": "application/json"})
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        logging.error("Failed to send notification: %s", e)


def main():
    try:
        for config in load_configs():
            pr_list = get_pull_request_list(config.owner_name, config.repo_name)
            filtered_prs = filter_pull_request(pr_list, config.target_label)
            review_result = get_review_result(filtered_prs)
            send_slack_notification(
                waiting_prs = review_result[REVIEW_STATUS_WAITING],
                complete_prs = review_result[REVIEW_STATUS_COMPLETE],
                label = config.target_label,
                webhook_url = config.webhook_url
            )
    except Exception as e:
        logging.error("An error occurred: %s", e, exc_info=True)

if __name__ == "__main__":
    main()
