import os
import sys
import importlib
# Ensure project root is on sys.path when running tests directly
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import newsbot


class DummyResponse:
    def __init__(self, status_code=200, data=None):
        self.status_code = status_code
        self._data = data or {"code": 0, "msg": "success"}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception(f"HTTP {self.status_code}")

    def json(self):
        return self._data


captured = {}


def dummy_post(url, json=None, timeout=None, verify=None):
    captured.setdefault("urls", []).append(url)
    captured['url'] = url
    captured['json'] = json
    captured['timeout'] = timeout
    captured['verify'] = verify
    return DummyResponse(200)


def test_send_feishu_message_posts_signed_payload(monkeypatch):
    captured.clear()
    monkeypatch.setattr(newsbot.requests, "post", dummy_post)

    ok = newsbot.send_feishu_message(
        "单元测试: 签名与发送",
        [[{"tag": "text", "text": "测试内容"}]],
        retries=1,
    )

    assert ok is True
    assert "timestamp=" in captured["url"]
    assert "sign=" in captured["url"]
    assert captured["json"]["msg_type"] == "post"
    assert captured["timeout"] == newsbot.FEISHU_REQUEST_TIMEOUT_SECONDS
    assert captured["verify"] is False


def test_empty_feishu_env_uses_defaults(monkeypatch):
    monkeypatch.setenv("FEISHU_WEBHOOK", "")
    monkeypatch.setenv("FEISHU_SECRET", "")

    reloaded = importlib.reload(newsbot)
    try:
        assert reloaded.FEISHU_WEBHOOK == reloaded.DEFAULT_FEISHU_WEBHOOK
        assert reloaded.FEISHU_SECRET == reloaded.DEFAULT_FEISHU_SECRET
    finally:
        monkeypatch.delenv("FEISHU_WEBHOOK", raising=False)
        monkeypatch.delenv("FEISHU_SECRET", raising=False)
        importlib.reload(newsbot)


def test_send_feishu_message_falls_back_to_plain_webhook(monkeypatch):
    captured.clear()
    calls = {"count": 0}

    def flaky_post(url, json=None, timeout=None, verify=None):
        captured.setdefault("urls", []).append(url)
        calls["count"] += 1
        if calls["count"] == 1:
            return DummyResponse(200, {"code": 999, "msg": "signed url rejected"})
        return DummyResponse(200)

    monkeypatch.setattr(newsbot.requests, "post", flaky_post)

    ok = newsbot.send_feishu_message(
        "单元测试: URL 兜底",
        [[{"tag": "text", "text": "测试内容"}]],
        retries=1,
    )

    assert ok is True
    assert calls["count"] == 2
    assert "timestamp=" in captured["urls"][0]
    assert captured["urls"][1] == newsbot.FEISHU_WEBHOOK


def test_news_run_fetches_and_sends_once(monkeypatch):
    calls = {"collect": 0, "send": 0}

    def fake_collect_news_batch(**kwargs):
        calls["collect"] += 1
        return {
            "ok": True,
            "coindesk": [{"title": "CoinDesk test", "link": "https://example.com/c"}],
            "panews": [],
            "error": None,
        }

    def fake_send_news(coindesk_list, panews_list, is_morning_summary=False):
        calls["send"] += 1
        return bool(coindesk_list or panews_list)

    monkeypatch.setattr(newsbot, "collect_news_batch", fake_collect_news_batch)
    monkeypatch.setattr(newsbot, "send_news", fake_send_news)

    assert newsbot.get_coindesk_hot_news() is True
    assert calls == {"collect": 1, "send": 1}


def test_run_once_uses_one_shot_fetch(monkeypatch):
    calls = {"run": 0}

    def fake_get_coindesk_hot_news(is_morning_summary=False, force_alert=False):
        calls["run"] += 1
        assert is_morning_summary is False
        assert force_alert is True
        return True

    monkeypatch.setattr(newsbot, "get_coindesk_hot_news", fake_get_coindesk_hot_news)

    assert newsbot.run_once() is True
    assert calls["run"] == 1
