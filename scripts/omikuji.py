"""Issue-driven omikuji. Python standard library only; no visitor code is executed."""

import json
import os
import re
import secrets
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent
START, END = "<!-- OMIKUJI:START -->", "<!-- OMIKUJI:END -->"
CONSENT = "- [x] ユーザー名と抽選結果が公開記録に残ることを確認して、おみくじを引きます。"
COMMENT_MARKER = "<!-- omikuji-result:v1 -->"
JST = timezone(timedelta(hours=9))
FORTUNES = [
    (10, "🌸 大吉", "デプロイ日和。温めていたアイデアを形にすると吉。"),
    (25, "☀️ 吉", "小さな改善が実を結ぶ日。いつもの一歩を大切に。"),
    (25, "🌿 中吉", "学びに追い風。知らなかった機能をひとつ試してみよう。"),
    (20, "🍀 小吉", "焦らず着実に。読みやすいコードが未来の自分を助けます。"),
    (15, "🌱 末吉", "今日まいた種はあとで芽吹く。下準備を楽しもう。"),
    (5, "☔ 凶", "今日は守りが吉。バックアップを取って、ひと休み。"),
]
TECH = ["Python", "TypeScript", "C#", "Git", "CSS", "SQL", "Unity", "Docker"]
CHALLENGES = [
    "READMEを1行だけ改善する", "気になった関数に説明を添える",
    "小さなバグをひとつ直す", "新しいショートカットをひとつ覚える",
    "誰かの作品の良いところを見つける", "作業を保存して、目と肩を休める",
    "明日の自分に作業メモを残す", "境界値のテストをひとつ考える",
]


def jst_date(timestamp):
    return datetime.fromisoformat(timestamp.replace("Z", "+00:00")).astimezone(JST).date().isoformat()


def eligible(issue):
    return (
        not issue.get("pull_request")
        and issue.get("state") == "open"
        and issue.get("title", "").startswith("[OMIKUJI]")
        and CONSENT in (issue.get("body") or "")
        and issue.get("user", {}).get("type") == "User"
    )


def draw(state, issue, randbelow=secrets.randbelow):
    """Persisted user ID + request's JST date gives one fortune per day."""
    number = str(issue["number"])
    if number in state["requests"]:
        return next(d for d in state["draws"] if d["key"] == state["requests"][number])
    date = jst_date(issue["created_at"])
    key = f'{issue["user"]["id"]}:{date}'
    result = next((d for d in state["draws"] if d["key"] == key), None)
    if result is None:
        ticket = randbelow(100)
        for weight, fortune, message in FORTUNES:
            if ticket < weight:
                break
            ticket -= weight
        result = {
            "key": key, "date": date, "login": issue["user"]["login"],
            "issue": issue["number"], "fortune": fortune, "message": message,
            "tech": TECH[randbelow(len(TECH))],
            "challenge": CHALLENGES[randbelow(len(CHALLENGES))],
        }
        state["draws"].append(result)
    state["requests"][number] = key
    return result


def render_readme(readme, state, repo):
    if readme.count(START) != 1 or readme.count(END) != 1 or readme.index(START) > readme.index(END):
        raise ValueError("README must contain exactly one ordered OMIKUJI marker pair")
    rows = ["| 参拝日（日本時間） | 参拝者 | 運勢 | お告げ |", "| --- | --- | --- | --- |"]
    for d in sorted(state["draws"], key=lambda d: (d["date"], d["issue"]), reverse=True)[:10]:
        # Only GitHub logins, never issue titles/bodies, enter rendered Markdown.
        login = d["login"]
        if not re.fullmatch(r"[A-Za-z0-9-]+", login):
            raise ValueError("Invalid GitHub login")
        rows.append(f'| {d["date"]} | [{login}](https://github.com/{login}) | {d["fortune"]} | [結果を見る](https://github.com/{repo}/issues/{d["issue"]}) |')
    content = "\n".join(rows) if state["draws"] else "まだ参拝者はいません。最初のおみくじを引いてみてください 🌸"
    before, after = readme.split(START)[0], readme.split(END)[1]
    return before + START + "\n" + content + "\n" + END + after


def comment(result):
    return (
        f'{COMMENT_MARKER}\n## ⛩️ {result["date"]} のおみくじ\n\n'
        f'### {result["fortune"]}\n\n{result["message"]}\n\n'
        f'**ラッキー技術：** {result["tech"]}\n\n'
        f'**今日の挑戦：** {result["challenge"]}\n\n'
        'ご参拝ありがとうございます。同じ日本時間の日付での再参拝は同じ運勢です。\n'
        'また明日、お待ちしています 🌸'
    )


class GitHub:
    def __init__(self, repo, token):
        self.base = f"https://api.github.com/repos/{repo}"
        self.token = token

    def request(self, path, method="GET", payload=None):
        request = Request(self.base + path, method=method, headers={
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json", "User-Agent": "profile-omikuji",
            "Content-Type": "application/json",
        }, data=None if payload is None else json.dumps(payload).encode())
        with urlopen(request, timeout=30) as response:
            return json.load(response)

    def pages(self, path):
        page = 1
        while True:
            batch = self.request(f'{path}{"&" if "?" in path else "?"}per_page=100&page={page}')
            yield from batch
            if len(batch) < 100:
                break
            page += 1


def process(api, state, readme, repo, persist):
    # Drain ALL open requests: concurrency replacement must not lose an issue.
    issues = sorted((i for i in api.pages("/issues?state=open&sort=created&direction=asc") if eligible(i)), key=lambda i: i["number"])
    if not issues:
        return
    for issue in issues:
        draw(state, issue)
    # Commit and push first. A retry uses the saved draws even if replying fails.
    persist(state, render_readme(readme, state, repo))
    for issue in issues:
        result = draw(state, issue)
        path = f'/issues/{issue["number"]}'
        existing = any(
            c.get("user", {}).get("login") == "github-actions[bot]"
            and c.get("body", "").startswith(COMMENT_MARKER)
            for c in api.pages(path + "/comments")
        )
        if not existing:
            api.request(path + "/comments", "POST", {"body": comment(result)})
        api.request(path, "PATCH", {"state": "closed", "state_reason": "completed"})
        print(f'Processed omikuji issue #{issue["number"]}')


def persist(state, readme):
    (ROOT / "data/omikuji.json").write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (ROOT / "README.md").write_text(readme, encoding="utf-8")

    def git(*args):
        return subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True, text=True).stdout

    git("config", "user.name", "github-actions[bot]")
    git("config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com")
    git("add", "--", "README.md", "data/omikuji.json")
    if git("diff", "--cached", "--name-only"):
        git("commit", "-m", "Update omikuji visitor records")
        # A concurrent human push fails safely; rerun the workflow against latest HEAD.
        git("push", "origin", "HEAD:refs/heads/" + os.environ["GITHUB_DEFAULT_BRANCH"])


def main():
    repo = os.environ["GITHUB_REPOSITORY"]
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        raise ValueError("Invalid repository")
    state = json.loads((ROOT / "data/omikuji.json").read_text(encoding="utf-8"))
    if state["version"] != 1:
        raise ValueError("Unsupported state version")
    process(GitHub(repo, os.environ["GH_TOKEN"]), state,
            (ROOT / "README.md").read_text(encoding="utf-8"), repo, persist)


if __name__ == "__main__":
    main()
