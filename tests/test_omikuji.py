import copy
import unittest

from scripts import omikuji as o


def state():
    return {"version": 1, "draws": [], "requests": {}}


def issue(number=1, user_id=123, timestamp="2026-11-23T01:00:00Z"):
    return {"number": number, "title": "[OMIKUJI] 今日のおみくじ", "body": o.CONSENT,
            "state": "open", "created_at": timestamp,
            "user": {"id": user_id, "login": "visitor", "type": "User"}}


README = "unchanged before\n" + o.START + "\nplaceholder\n" + o.END + "\nunchanged after"


class FakeAPI:
    def __init__(self, issues):
        self.issues = issues
        self.comments = {}
        self.operations = []
        self.fail_close = False

    def pages(self, path):
        if path.startswith("/issues?"):
            return copy.deepcopy(self.issues)
        return self.comments.get(path, [])

    def request(self, path, method, payload):
        self.operations.append((method, path))
        if method == "POST":
            self.comments.setdefault(path, []).append({"user": {"login": "github-actions[bot]"}, **payload})
        elif method == "PATCH":
            if self.fail_close:
                raise RuntimeError("Simulated close failure")
            for item in self.issues:
                if path == f'/issues/{item["number"]}':
                    item.update(payload)


class OmikujiTests(unittest.TestCase):
    def test_japan_midnight(self):
        self.assertEqual(o.jst_date("2026-11-23T14:59:59Z"), "2026-11-23")
        self.assertEqual(o.jst_date("2026-11-23T15:00:00Z"), "2026-11-24")

    def test_weight_distribution(self):
        counts = {}
        for ticket in range(100):
            values = iter([ticket, 0, 0])
            result = o.draw(state(), issue(), lambda _: next(values))
            counts[result["fortune"]] = counts.get(result["fortune"], 0) + 1
        self.assertEqual(counts, {name: weight for weight, name, _ in o.FORTUNES})

    def test_same_day_uses_user_id_even_after_rename(self):
        data = state()
        first = o.draw(data, issue(), lambda _: 0)
        again = issue(2)
        again["user"]["login"] = "renamed-visitor"
        result = o.draw(data, again, lambda _: self.fail("Must not draw again"))
        self.assertEqual(result, first)
        self.assertEqual(len(data["draws"]), 1)
        self.assertEqual(len(data["requests"]), 2)

    def test_next_day_and_other_user_get_new_draws(self):
        data = state()
        for i in [issue(), issue(2, timestamp="2026-11-23T15:00:00Z"), issue(3, user_id=456)]:
            o.draw(data, i, lambda _: 0)
        self.assertEqual(len(data["draws"]), 3)

    def test_replay_never_redraws(self):
        data = state()
        first = o.draw(data, issue())
        self.assertEqual(o.draw(data, issue(), lambda _: self.fail("Redraw")), first)

    def test_only_opted_in_human_issues(self):
        self.assertTrue(o.eligible(issue()))
        for patch in [{"body": ""}, {"body": None}, {"title": "Bug"},
                      {"state": "closed"}, {"pull_request": {"url": "x"}},
                      {"user": {"type": "Bot"}}]:
            with self.subTest(patch=patch):
                self.assertFalse(o.eligible({**issue(), **patch}))

    def test_readme_preserved_and_recent_ten_only(self):
        data = state()
        for n in range(1, 13):
            o.draw(data, issue(n, user_id=n), lambda _: 0)
        result = o.render_readme(README, data, "owner/repo")
        self.assertTrue(result.startswith("unchanged before\n"))
        self.assertTrue(result.endswith("\nunchanged after"))
        self.assertEqual(result.count("[結果を見る]"), 10)
        self.assertNotIn("/issues/2)", result)
        self.assertLess(result.index("/issues/12)"), result.index("/issues/11)"))

    def test_missing_or_duplicate_markers_fail(self):
        for text in ["", README + o.START, o.END + o.START]:
            with self.assertRaises(ValueError):
                o.render_readme(text, state(), "owner/repo")

    def test_user_text_not_rendered(self):
        item = issue()
        item["title"] += " $(echo bad) <script>alert(1)</script>"
        item["body"] += "\n| injected | @everyone"
        data = state()
        result = o.draw(data, item)
        output = o.render_readme(README, data, "owner/repo") + o.comment(result)
        for value in ["<script>", "injected", "@everyone", "$("]:
            self.assertNotIn(value, output)

    def test_process_drains_all_open_requests_saves_before_reply(self):
        api, data = FakeAPI([issue(), issue(2, user_id=456), {**issue(3), "title": "Bug"}]), state()
        def save(data, text):
            self.assertEqual(len(data["draws"]), 2)
            self.assertEqual(api.operations, [])
            self.assertIn("/issues/2)", text)
        o.process(api, data, README, "owner/repo", save)
        self.assertEqual(len(api.operations), 4)
        self.assertEqual(api.issues[2]["state"], "open")

    def test_persist_failure_sends_no_reply(self):
        api = FakeAPI([issue()])
        def fail(*_):
            raise RuntimeError("Push rejected")
        with self.assertRaises(RuntimeError):
            o.process(api, state(), README, "owner/repo", fail)
        self.assertEqual(api.operations, [])

    def test_recovery_after_reply_before_close(self):
        api, data, saved = FakeAPI([issue()]), state(), []
        api.fail_close = True
        with self.assertRaises(RuntimeError):
            o.process(api, data, README, "owner/repo", lambda s, _: saved.append(copy.deepcopy(s)))
        api.fail_close = False
        o.process(api, saved[0], README, "owner/repo", lambda *_: None)
        self.assertEqual(sum(method == "POST" for method, _ in api.operations), 1)
        self.assertEqual(api.issues[0]["state"], "closed")
        self.assertEqual(len(saved[0]["draws"]), 1)

    def test_human_cannot_spoof_bot_result(self):
        api = FakeAPI([issue()])
        api.comments["/issues/1/comments"] = [{"user": {"login": "visitor"}, "body": o.COMMENT_MARKER}]
        o.process(api, state(), README, "owner/repo", lambda *_: None)
        self.assertEqual(sum(method == "POST" for method, _ in api.operations), 1)


if __name__ == "__main__":
    unittest.main()
