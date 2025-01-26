
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
FILTERED_PRS_FILE_NAME = "filtered_prs.json"

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
            if len(pr.get("requested_reviewers", [])) < 2:
                waiting_prs.append(pr)
            else:
                complete_prs.append(pr)
    return waiting_prs, complete_prs

def check_mergeable_state(pr_url):
    max_retries = 5
    retry_delay = 5
    retries = 0

    while retries < max_retries:
        response = requests.get(pr_url, headers=HEADERS)
        if response.status_code != 200:
            print(f"Failed to fetch details for {pr_url}")
            return None

        pr_details = response.json()
        mergeable_state = pr_details.get("mergeable_state")
        if mergeable_state == "clean":
            return "mergeable"
        elif mergeable_state == "unknown":
            print(f"mergeable_state is unknown. Retrying in {retry_delay} seconds...")
            time.sleep(retry_delay)
            retries += 1
        else:
            return "pending"
    return "pending"

def send_notification(waiting_prs: List[str], complete_prs: List[str], webhook_url: str):
    # メッセージを整形
    waitingForReviewTitle = ":heavy_check_mark: レビュー待ちのPR"
    completeForReviewTitle = ":white_check_mark: レビューが完了しているPR"
    text = f"{waitingForReviewTitle}\n" + "\n".join(waiting_prs) + f"\n{completeForReviewTitle}\n" + "\n".join(complete_prs)

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
    # prs = fetch_prs()
    # filtered_prs = filter_prs_by_label(prs, TARGET_LABEL)

    # if not filtered_prs:
    #     print(f"No PRs found with label '{TARGET_LABEL}'.")
    #     exit(0)

    # mergeable_prs = []
    # pending_prs = []

    # print("Checking 'mergeable_state' for PRs...")
    # for pr in filtered_prs:
    #     pr_url = pr["url"]
    #     state = check_mergeable_state(pr_url)
    #     if state == "mergeable":
    #         mergeable_prs.append(pr["html_url"])
    #     elif state == "pending":
    #         pending_prs.append(pr["html_url"])

    # print("Mergeable PRs URLs:")
    # if mergeable_prs:
    #     print("\n".join(mergeable_prs))
    # else:
    #     print("No mergeable PRs found.")

    # print("Pending PRs (Not Ready for Merge) URLs:")
    # if pending_prs:
    #     print("\n".join(pending_prs))
    # else:
    #     print("No pending PRs found.")

if __name__ == "__main__":
    main()


# オブジェクトで取り扱いたい
# ドラフトはとりのぞく
# json のリストの分だけ繰り返したい
# mergeable が常にtrueになるので、マージ可能の判定にmergeable の利用はむずかしそう。/pulls/4/reviwersの人数が{指定人数}以上の場合にマージ可能と判断する

# 1. PR一覧を取得
# 2. ラベルが指定されたPRを取得
# 3. レビュアーが指定された人数以上のPRを取得
# 4. slack 通知ようの形に整形
