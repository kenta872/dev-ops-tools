import os
import requests
import time
import json
from typing import List

# 設定ファイルのパス
CONFIG_FILE_PATH = ".github/scripts/config.json"
# 環境変数から値を取得
DEV_OPS_TOKEN = os.getenv("DEV_OPS_TOKEN")
# PR情報を格納するためのファイル名
ALL_PRS_FILE_NAME = "all_prs.json"
REVIEWER_COUNT_LIMIT=1

def load_configs():
    with open(CONFIG_FILE_PATH, "r") as file:
        return json.load(file)

def fetch_prs(base_url, base_headers):
    print("Fetching Pull Requests...")
    response = requests.get(base_url, headers=base_headers)
    if response.status_code != 200:
        print(f"Failed to fetch PRs: {response.status_code}")
        exit(1)

    prs = response.json()
    with open(ALL_PRS_FILE_NAME, "w") as file:
        json.dump(prs, file, indent=2)
    return prs

def filter_prs(prs, label):
    print(f"Filtering PRs with label '{label}'...")
    waiting_prs = []
    complete_prs = []
    for pr in prs:
        # ラベルとドラフト状態のフィルタリング
        if any(l["name"] == label for l in pr.get("labels", [])) and not pr.get("draft", True):
            # requested_reviewersが2件未満の場合はwaiting_prsに、それ以外はcomplete_prsに仕分け
            if len(pr.get("requested_reviewers", [])) < REVIEWER_COUNT_LIMIT:
                waiting_prs.append(pr["html_url"])
            else:
                complete_prs.append(pr["html_url"])
    return waiting_prs, complete_prs

def send_notification(waiting_prs: List[str], complete_prs: List[str], webhook_url: str):
    # メッセージを整形
    waitingForReviewTitle = ":eyes: レビュー待ちのPR"
    if waiting_prs:
        waitingPrsText = "\n".join(waiting_prs)
    else:
        waitingPrsText = ":tada: レビュー待ちのPRはありません ! :tada:"

    completeForReviewTitle = ":white_check_mark: レビューが完了しているPR"
    if complete_prs:
        completePrsText = "\n".join(waiting_prs)
    else:
        completePrsText = "マージ待ちのPRはありません !"
    text = f"{waitingForReviewTitle}\n{waitingPrsText}\n\n{completeForReviewTitle}\n{completePrsText}"
    # ペイロードを作成
    payload = {
        "text": text
    }

    # Slackに送信
    response = requests.post(webhook_url, json=payload, headers={'Content-type': 'application/json'})

    # 結果を確認
    if response.status_code == 200:
        print("メッセージが送信されました。")
    else:
        print(f"送信に失敗しました。ステータスコード: {response.status_code}, 内容: {response.text}")


def main():
    configs = load_configs()
    for config in configs:
        # 設定情報の読み込み
        webhook_url = os.getenv(config["webhook_secret_name"])
        repo_name = config["repo_name"]
        owner_name = config["owner_name"]
        target_label = config["target_label"]

        if webhook_url is None:
            print(f"webhook_url URL not found. Skipping...")
            continue
        if repo_name is None:
            print(f"repo_name URL not found. Skipping...")
            continue
        if owner_name is None:
            print(f"owner_name URL not found. Skipping...")
            continue
        if target_label is None:
            print(f"target_label URL not found. Skipping...")
            continue

        base_url = f"https://api.github.com/repos/{owner_name}/{repo_name}/pulls"
        headers = {"Authorization": f"token {DEV_OPS_TOKEN}"}
        all_prs = fetch_prs(base_url, headers)
        waiting_prs,complete_prs = filter_prs(all_prs, target_label)

        # 通知を送信
        send_notification(
            waiting_prs=waiting_prs,
            complete_prs=complete_prs,
            webhook_url=webhook_url
        )

if __name__ == "__main__":
    main()


# オブジェクトで取り扱いたい
# 事前準備
# 1. slack app を作成(通知したいチャンネル分作成する)
# 2. github で token を生成する
# 3. github の setting からシークレットを登録(webhookURL, token)
