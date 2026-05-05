import ssl
ssl._create_default_https_context = ssl._create_unverified_context

import builtins
import sys
# Ensure stdout/stderr use UTF-8 so emoji and CJK characters don't crash on Windows
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except (AttributeError, OSError):
    pass

_builtin_print = builtins.print


def _safe_print(*args, **kwargs):
    """Print safely even when console encoding cannot represent emoji/CJK."""
    try:
        _builtin_print(*args, **kwargs)
    except UnicodeEncodeError:
        stream = kwargs.get('file', sys.stdout)
        encoding = getattr(stream, 'encoding', None) or 'utf-8'
        safe_args = []
        for arg in args:
            text = str(arg)
            try:
                text = text.encode(encoding, errors='replace').decode(encoding, errors='replace')
            except Exception:
                text = text.encode('ascii', errors='replace').decode('ascii')
            safe_args.append(text)
        _builtin_print(*safe_args, **kwargs)


# Keep using print(...) everywhere but make output robust across mixed encodings.
print = _safe_print

from datetime import datetime, timedelta
import time
import requests
import hmac
import hashlib
import base64
import os
import urllib3
urllib3.disable_warnings()
from urllib.parse import quote_plus
# Python 3.12+ removed distutils; patch it from setuptools if needed
try:
    import setuptools._distutils
    sys.modules.setdefault('distutils', setuptools._distutils)
    try:
        import setuptools._distutils.version
        sys.modules.setdefault('distutils.version', setuptools._distutils.version)
    except ImportError:
        pass
except ImportError:
    pass

from newsbot_config import (
    COINDESK_LIMIT,
    FEISHU_REQUEST_TIMEOUT_SECONDS,
    FEISHU_RETRIES,
    FEISHU_RETRY_BACKOFF_BASE_SECONDS,
    HKT_TZ,
    NEWS_LOOKBACK_MINUTES,
    PANEWS_LIMIT,
)
from news_scraper import collect_news_batch

DEFAULT_FEISHU_WEBHOOK = "https://open.feishu.cn/open-apis/bot/v2/hook/730fd294-c270-4e81-b94d-6c6768d9112d"
DEFAULT_FEISHU_SECRET = "2JdFHxHgRvsiICu8fZX3Lh"


def env_or_default(name, default):
    value = os.getenv(name, "").strip()
    if value.startswith("${") and value.endswith("}"):
        value = value[2:-1].strip()
    return value or default


FEISHU_WEBHOOK = env_or_default("FEISHU_WEBHOOK", DEFAULT_FEISHU_WEBHOOK)
FEISHU_SECRET = env_or_default("FEISHU_SECRET", DEFAULT_FEISHU_SECRET)

history_titles = set()

def gen_sign(secret):
    timestamp = str(int(time.time()))
    string_to_sign = '{}\n{}'.format(timestamp, secret)
    # Feishu custom bot signature uses string_to_sign as HMAC key
    # (message is empty), then base64-encodes the digest.
    hmac_code = hmac.new(string_to_sign.encode("utf-8"), digestmod=hashlib.sha256).digest()
    sign = base64.b64encode(hmac_code).decode('utf-8')
    return timestamp, sign


def build_feishu_urls(timestamp, sign):
    # Prefer signed query URL, and fallback to plain webhook URL.
    # Some network gateways and bot setups are picky about one style.
    return [
        f"{FEISHU_WEBHOOK}?timestamp={timestamp}&sign={quote_plus(sign)}",
        FEISHU_WEBHOOK,
    ]


def send_feishu_message(title, block_arr, retries=FEISHU_RETRIES):
    if not block_arr:
        return True

    last_error = None
    for attempt in range(1, retries + 1):
        timestamp, sign = gen_sign(FEISHU_SECRET)
        payload = {
            "timestamp": timestamp, "sign": sign, "msg_type": "post",
            "content": {"post": {"zh_cn": {"title": title, "content": block_arr}}}
        }

        for target_url in build_feishu_urls(timestamp, sign):
            try:
                res = requests.post(
                    target_url,
                    json=payload,
                    timeout=FEISHU_REQUEST_TIMEOUT_SECONDS,
                    verify=False,
                )
                res.raise_for_status()

                # Feishu can return HTTP 200 with non-zero business error code.
                data = res.json()
                if isinstance(data, dict) and data.get("code", 0) != 0:
                    raise RuntimeError(f"Feishu业务错误 code={data.get('code')} msg={data.get('msg')}")

                print("✅ 成功推送到飞书！")
                return True
            except Exception as e:
                last_error = e
                print(f"❌ 推送飞书失败(第 {attempt}/{retries} 次): {e}")

        if attempt < retries:
            time.sleep(attempt * FEISHU_RETRY_BACKOFF_BASE_SECONDS)

    print(f"❌ 推送飞书最终失败: {last_error}")
    return False


def add_news_section(block_arr, source_name, news_list):
    if not news_list:
        return

    block_arr.append([{"tag": "text", "text": f"📰 {source_name}"}])
    for i, news in enumerate(news_list, 1):
        block_arr.append([{"tag": "text", "text": f"{i}. {news['title']}\n{news['link']}\n"}])
        history_titles.add(news["title"])


def send_news(coindesk_list, panews_list, is_morning_summary=False):
    """Send one combined Feishu message with CoinDesk + PANews articles."""
    now_tz = datetime.now(HKT_TZ)
    if not coindesk_list and not panews_list:
        return False

    block_arr = []
    add_news_section(block_arr, "CoinDesk", coindesk_list)
    add_news_section(block_arr, "PANews", panews_list)

    if len(history_titles) > 1000:
        history_titles.clear()

    if is_morning_summary:
        main_title = f"🌅 早间速递: 加密新闻 ({now_tz.strftime('%m-%d')} 00:00 - {now_tz.strftime('%H:%M')} 汇总)"
    else:
        start_str = (now_tz - timedelta(minutes=NEWS_LOOKBACK_MINUTES)).strftime('%H:%M')
        main_title = f"🔥 加密新闻速递 ({start_str} - {now_tz.strftime('%H:%M')} HKT)"

    return send_feishu_message(main_title, block_arr)

def send_error_alert(error_msg):
    # Keep only the first 2 lines to avoid dumping full stacktraces to Feishu
    short = '\n'.join(str(error_msg).split('\n')[:2])
    block_arr = [[{"tag": "text", "text": f"⚠️ 本次获取失败：{short}"}]]
    send_feishu_message("CoinDesk 新闻", block_arr)


def get_coindesk_hot_news(is_morning_summary=False, force_alert=False):
    batch = collect_news_batch(
        history_titles=history_titles,
        coindesk_limit=COINDESK_LIMIT,
        panews_limit=PANEWS_LIMIT,
        logger=print,
    )

    if not batch["ok"]:
        err = f"浏览器初始化或抓取失败: {batch['error']}"
        print(f"⚠️ 发生内部错误: {err}")
        if force_alert:
            err_msg = str(batch["error"]).split('\n')[0][:100]
            send_feishu_message("⚠️ 加密新闻抓取报错", [[{"tag": "text", "text": f"新闻抓取失败，原因: {err_msg}"}]])
        return False

    coindesk_news = batch["coindesk"]
    panews_news = batch["panews"]
    if coindesk_news or panews_news:
        return send_news(coindesk_news, panews_news, is_morning_summary)

    print("目前没有新鲜的热门文章，跳过本次播报。")
    now_tz = datetime.now(HKT_TZ)
    if is_morning_summary:
        main_title = f"🌅 早间速递: 加密新闻 ({now_tz.strftime('%m-%d')} 汇总)"
    else:
        start_str = (now_tz - timedelta(minutes=NEWS_LOOKBACK_MINUTES)).strftime('%H:%M')
        main_title = f"🔥 加密新闻速递 ({start_str} - {now_tz.strftime('%H:%M')} HKT)"
    block_arr = [[{"tag": "text", "text": "📭 没有获取到新的新闻 (或与上期内容重复)。"}]]
    return send_feishu_message(main_title, block_arr)


def run_once():
    print("🔥 加密新闻机器人开始执行一次抓取任务...")
    return get_coindesk_hot_news(is_morning_summary=False, force_alert=True)


if __name__ == '__main__':
    ok = run_once()
    sys.exit(0 if ok else 1)
