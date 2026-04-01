import ssl
ssl._create_default_https_context = ssl._create_unverified_context

import sys
import socket as _socket
# Ensure stdout/stderr use UTF-8 so emoji and CJK characters don't crash on Windows
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except (AttributeError, OSError):
    pass

_builtin_print = print


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
import json
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
    LOCK_HOST,
    LOCK_PORT,
    MIDNIGHT_SLOT_HOUR,
    MIDNIGHT_SLOT_MINUTE,
    MORNING_SUMMARY_HOUR,
    MORNING_SUMMARY_MINUTE,
    NEWS_LOOKBACK_MINUTES,
    PANEWS_LIMIT,
    RUN_HOUR_END,
    RUN_HOUR_START,
    SCHEDULER_POLL_SECONDS,
    SLOT_INTERVAL_MINUTES,
)
from news_scraper import collect_news_batch
from news_scheduler import run_scheduler_loop

FEISHU_WEBHOOK = "https://open.feishu.cn/open-apis/bot/v2/hook/730fd294-c270-4e81-b94d-6c6768d9112d"
FEISHU_SECRET = "2JdFHxHgRvsiICu8fZX3Lh"

DAILY_FILE = "daily_articles.json"
STATE_FILE = "newsbot_state.json"

def load_daily_articles():
    if os.path.exists(DAILY_FILE):
        try:
            with open(DAILY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                now_tz = datetime.now(HKT_TZ)
                today_str = now_tz.strftime('%Y-%m-%d')
                if data.get("date") == today_str:
                    return data.get("articles", {"coindesk": [], "panews": []}), data.get("date")
        except:
            pass
    return {"coindesk": [], "panews": []}, None

def save_daily_articles(articles, date_str):
    with open(DAILY_FILE, "w", encoding="utf-8") as f:
        json.dump({"date": date_str, "articles": articles}, f, ensure_ascii=False)


def load_runtime_state():
    default = {
        "last_summary_sent_date": None,
        "last_morning_summary_date": None,
    }
    if not os.path.exists(STATE_FILE):
        return default
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return default
        default.update(data)
        return default
    except Exception:
        return default


def save_runtime_state(state):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False)
    except Exception as e:
        print(f"⚠️ 保存运行状态失败: {e}")


def reset_daily_articles(date_str):
    """Rotate daily article bucket to a specific date."""
    global daily_articles, daily_articles_date
    daily_articles = {"coindesk": [], "panews": []}
    daily_articles_date = date_str
    save_daily_articles(daily_articles, daily_articles_date)


def has_daily_articles():
    return bool(daily_articles.get("coindesk") or daily_articles.get("panews"))

history_titles = set()
daily_articles, daily_articles_date = load_daily_articles()
runtime_state = load_runtime_state()

def gen_sign(secret):
    timestamp = str(int(time.time()))
    string_to_sign = '{}\n{}'.format(timestamp, secret)
    # Feishu custom bot signature uses string_to_sign as HMAC key
    # (message is empty), then base64-encodes the digest.
    hmac_code = hmac.new(string_to_sign.encode("utf-8"), digestmod=hashlib.sha256).digest()
    sign = base64.b64encode(hmac_code).decode('utf-8')
    return timestamp, sign

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

        try:
            # Prefer signed query URL, and fallback to plain webhook URL.
            # Some network gateways and bot setups are picky about one style.
            urls = [
                f"{FEISHU_WEBHOOK}?timestamp={timestamp}&sign={quote_plus(sign)}",
                FEISHU_WEBHOOK,
            ]

            for target_url in urls:
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

def send_news(coindesk_list, panews_list, is_morning_summary=False):
    """Send one combined Feishu message with CoinDesk + PANews articles."""
    global daily_articles, daily_articles_date

    now_tz = datetime.now(HKT_TZ)
    today_str = now_tz.strftime('%Y-%m-%d')
    if daily_articles_date != today_str:
        # Daily rollover should be handled by summary compensation before scraping.
        print(f"⚠️ 检测到跨天({daily_articles_date} -> {today_str})，先重置为新日期缓存。")
        reset_daily_articles(today_str)

    if not coindesk_list and not panews_list:
        return False

    block_arr = []

    if coindesk_list:
        block_arr.append([{"tag": "text", "text": "📰 CoinDesk"}])
        for i, news in enumerate(coindesk_list, 1):
            block_arr.append([{"tag": "text", "text": f"{i}. {news['title']}\n{news['link']}\n"}])
            history_titles.add(news['title'])
            if not any(a['title'] == news['title'] for a in daily_articles["coindesk"]):
                daily_articles["coindesk"].append(news)

    if panews_list:
        block_arr.append([{"tag": "text", "text": "\n📰 PANews"}])
        for i, news in enumerate(panews_list, 1):
            block_arr.append([{"tag": "text", "text": f"{i}. {news['title']}\n{news['link']}\n"}])
            history_titles.add(news['title'])
            if not any(a['title'] == news['title'] for a in daily_articles["panews"]):
                daily_articles["panews"].append(news)

    save_daily_articles(daily_articles, daily_articles_date)

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


def send_daily_summary(summary_date=None):
    """Send summary for buffered daily articles and clear only on success."""
    if not has_daily_articles():
        return True

    now_tz = datetime.now(HKT_TZ)
    if summary_date:
        try:
            summary_dt = datetime.strptime(summary_date, '%Y-%m-%d')
            title_date = summary_dt.strftime('%m-%d')
        except Exception:
            title_date = now_tz.strftime('%m-%d')
    else:
        title_date = now_tz.strftime('%m-%d')
    title = f"📅 每日资讯汇总 ({title_date})"
    
    block_arr = []
    
    if daily_articles["coindesk"]:
        block_arr.append([{"tag": "text", "text": "📰 CoinDesk 汇总"}])
        for i, news in enumerate(daily_articles["coindesk"], 1):
            block_arr.append([{"tag": "text", "text": f"{i}. {news['title']}\n{news['link']}\n"}])
            
    if daily_articles["panews"]:
        block_arr.append([{"tag": "text", "text": "\n📰 PANews 汇总"}])
        for i, news in enumerate(daily_articles["panews"], 1):
            block_arr.append([{"tag": "text", "text": f"{i}. {news['title']}\n{news['link']}\n"}])
            
    # To prevent Feishu message size limits, chunk block_arr to slices of 50
    chunk_size = 50
    all_sent = True
    for i in range(0, len(block_arr), chunk_size):
        chunk = block_arr[i:i + chunk_size]
        msg_title = title if i == 0 else f"{title} (续)"
        if not send_feishu_message(msg_title, chunk):
            all_sent = False
        time.sleep(1)

    if all_sent:
        reset_daily_articles(now_tz.strftime('%Y-%m-%d'))
    return all_sent


def try_send_pending_daily_summary(now_tz):
    """Compensate missed 00:00 summary before any new-day scraping."""
    global runtime_state

    today_str = now_tz.strftime('%Y-%m-%d')
    pending_date = daily_articles_date
    if not pending_date:
        reset_daily_articles(today_str)
        return True

    if pending_date < today_str:
        already_sent = runtime_state.get("last_summary_sent_date") == pending_date
        if already_sent:
            reset_daily_articles(today_str)
            return True

        if not has_daily_articles():
            reset_daily_articles(today_str)
            return True

        print(f"📅 检测到漏发汇总，准备补发 {pending_date} 的每日汇总...")
        if send_daily_summary(summary_date=pending_date):
            runtime_state["last_summary_sent_date"] = pending_date
            save_runtime_state(runtime_state)
            return True

        return False

    return True


def is_slot_aligned(minute, interval_minutes):
    return interval_minutes > 0 and (minute % interval_minutes == 0)


def should_send_now(is_morning_summary=False):
    """Allow pushes only on configured slot boundaries."""
    now_tz = datetime.now(HKT_TZ)
    # Morning summary is also bound to slot timing and keeps current behavior.
    if is_morning_summary:
        return is_slot_aligned(now_tz.minute, SLOT_INTERVAL_MINUTES)
    return is_slot_aligned(now_tz.minute, SLOT_INTERVAL_MINUTES)

def get_coindesk_hot_news(is_morning_summary=False, force_alert=False):
    if not should_send_now(is_morning_summary=is_morning_summary):
        now_tz = datetime.now(HKT_TZ)
        print(
            f"⏭️ 当前时间 {now_tz.strftime('%H:%M:%S')} 非整点槽位，"
            f"仅允许在每 {SLOT_INTERVAL_MINUTES} 分钟边界推送，跳过本次发送。"
        )
        return True

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

def add_to_startup():
    try:
        import platform
        if platform.system() == "Windows":
            startup = os.path.join(os.getenv('APPDATA'), r'Microsoft\Windows\Start Menu\Programs\Startup')
            target_vbs = os.path.join(os.path.dirname(os.path.abspath(__file__)), "【双击运行】一键启动后台Bots.vbs")
            bat_path = os.path.join(startup, "CryptoNewsBotAutoStart.bat")
            # Use UTF-16 so CMD can safely parse non-GBK path characters.
            with open(bat_path, "w", encoding="utf-16") as f:
                f.write(
                    '@echo off\n'
                    'set PYTHONUTF8=\n'
                    'set PYTHONIOENCODING=\n'
                    'set PYTHONUTF8=1\n'
                    'set PYTHONIOENCODING=utf-8\n'
                    f'cd /d "{os.path.dirname(os.path.abspath(__file__))}"\n'
                    f'start "" "{target_vbs}"\n'
                )
            print("✅ 成功创建开机自启脚本于:", bat_path)
    except Exception as e:
        print(f"⚠️ 添加开机自启失败: {e}")

if __name__ == '__main__':
    add_to_startup()
    
    # Single-instance lock: prevent multiple bot processes from running simultaneously
    _lock_sock = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
    _SO_EXCL = getattr(_socket, 'SO_EXCLUSIVEADDRUSE', None)
    if _SO_EXCL is not None:
        _lock_sock.setsockopt(_socket.SOL_SOCKET, _SO_EXCL, 1)
    else:
        _lock_sock.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEADDR, 0)
    try:
        _lock_sock.bind((LOCK_HOST, LOCK_PORT))
    except OSError:
        print("⚠️ 另一个 newsbot 实例正在运行，退出。")
        sys.exit(0)

    print("🔥 CoinDesk 新闻机器人启动... 正在后台监测中")
    
    # 启动时先发送一条机器人启动的飞书提示
    send_feishu_message("🤖 新闻监控启动", [[{"tag": "text", "text": "✅ 后台监控服务已经成功运行，即将开始首次抓取。"}]])
    
    _now = datetime.now(HKT_TZ)

    if not try_send_pending_daily_summary(_now):
        print("⚠️ 启动时补偿每日汇总失败，将在下一个定时槽继续重试。")

    if is_slot_aligned(_now.minute, SLOT_INTERVAL_MINUTES):
        print("🚀 启动时处于时间槽边界，执行首次抓取...")
        get_coindesk_hot_news()
    else:
        print("🕒 启动时不在时间槽边界，等待下一个 :00/:30 槽位后再抓取。")

    def _should_run_slot(slot_time):
        in_daytime = RUN_HOUR_START <= slot_time.hour <= RUN_HOUR_END
        is_midnight_slot = (
            slot_time.hour == MIDNIGHT_SLOT_HOUR and
            slot_time.minute == MIDNIGHT_SLOT_MINUTE
        )
        return in_daytime or is_midnight_slot

    def _on_slot(slot_time, now):
        current_slot = f"{slot_time.day:02}-{slot_time.hour:02}:{slot_time.minute:02}"
        print(f"\n[{now.strftime('%Y-%m-%d %H:%M:%S')}] ⏰ 触发定时任务 ({current_slot})...")

        if not try_send_pending_daily_summary(now):
            print("⚠️ 每日汇总补偿发送失败，本轮新闻抓取跳过，等待下个时间槽重试。")
            return

        today_str = now.strftime('%Y-%m-%d')
        is_morning = (
            slot_time.hour == MORNING_SUMMARY_HOUR and
            slot_time.minute == MORNING_SUMMARY_MINUTE and
            runtime_state.get("last_morning_summary_date") != today_str
        )

        success = get_coindesk_hot_news(is_morning_summary=is_morning, force_alert=True)
        if success and is_morning:
            runtime_state["last_morning_summary_date"] = today_str
            save_runtime_state(runtime_state)

        if not success:
            print("❌ 本次任务发生报错...")

    # next slot is managed by scheduler module; parameters can be tuned in newsbot_config.py
    run_scheduler_loop(
        tz=HKT_TZ,
        interval_minutes=SLOT_INTERVAL_MINUTES,
        poll_seconds=SCHEDULER_POLL_SECONDS,
        should_run_slot=_should_run_slot,
        on_slot=_on_slot,
        logger=print,
    )
