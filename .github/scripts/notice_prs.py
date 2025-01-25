
import os
import requests
import time
import json

# 設定ファイルのパス
CONFIG_FILE_PATH = ".github/scripts/config.json"

def load_config():
    with open(CONFIG_FILE_PATH, "r") as file:
        return json.load(file)

# 設定を読み込む
config = load_config()
REPO_NAME = config["repo_name"]
OWNER_NAME = config["owner_name"]
TARGET_LABEL = config["target_label"]

# 環境変数から値を取得
DEV_OPS_TOKEN = os.getenv("DEV_OPS_TOKEN")

# GitHub APIのベースURL
BASE_URL = f"https://api.github.com/repos/{OWNER_NAME}/{REPO_NAME}/pulls"
HEADERS = {"Authorization": f"token {DEV_OPS_TOKEN}"}



def fetch_prs():
    print("Fetching Pull Requests...")
    response = requests.get(BASE_URL, headers=HEADERS)
    if response.status_code != 200:
        print(f"Failed to fetch PRs: {response.status_code}")
        exit(1)

    prs = response.json()
    with open("all_prs.json", "w") as file:
        json.dump(prs, file, indent=2)
    return prs

def filter_prs_by_label(prs, label):
    print(f"Filtering PRs with label '{label}'...")
    filtered_prs = [
        pr for pr in prs
        if any(l["name"] == label for l in pr.get("labels", []))
    ]
    with open("target_label_prs_urls.json", "w") as file:
        json.dump([pr["html_url"] for pr in filtered_prs], file, indent=2)
    return filtered_prs

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

def main():
    prs = fetch_prs()
    filtered_prs = filter_prs_by_label(prs, TARGET_LABEL)

    if not filtered_prs:
        print(f"No PRs found with label '{TARGET_LABEL}'.")
        exit(0)

    mergeable_prs = []
    pending_prs = []

    print("Checking 'mergeable_state' for PRs...")
    for pr in filtered_prs:
        pr_url = pr["url"]
        state = check_mergeable_state(pr_url)
        if state == "mergeable":
            mergeable_prs.append(pr["html_url"])
        elif state == "pending":
            pending_prs.append(pr["html_url"])

    with open("mergeable_prs_urls.json", "w") as file:
        json.dump(mergeable_prs, file, indent=2)

    with open("pending_prs_urls.json", "w") as file:
        json.dump(pending_prs, file, indent=2)

    print("Mergeable PRs URLs:")
    if mergeable_prs:
        print("\n".join(mergeable_prs))
    else:
        print("No mergeable PRs found.")

    print("Pending PRs (Not Ready for Merge) URLs:")
    if pending_prs:
        print("\n".join(pending_prs))
    else:
        print("No pending PRs found.")

if __name__ == "__main__":
    main()
