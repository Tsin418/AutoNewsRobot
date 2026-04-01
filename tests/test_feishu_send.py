import os
import sys
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
    captured['url'] = url
    captured['json'] = json
    captured['timeout'] = timeout
    captured['verify'] = verify
    return DummyResponse(200)


def run_test():
    # Monkeypatch requests.post
    newsbot.requests_post_orig = newsbot.requests.post
    newsbot.requests.post = dummy_post

    try:
        ts, sign = newsbot.gen_sign(newsbot.FEISHU_SECRET)
        print('gen_sign -> timestamp:', ts, 'sign(len):', len(sign))

        ok = newsbot.send_feishu_message('单元测试: 签名与发送', [[{"tag": "text", "text": "测试内容"}]], retries=1)
        print('send_feishu_message returned:', ok)
        print('Captured POST URL:', captured.get('url'))
        print('Captured payload keys:', list(captured.get('json', {}).keys()))
    finally:
        newsbot.requests.post = newsbot.requests_post_orig


if __name__ == '__main__':
    run_test()
