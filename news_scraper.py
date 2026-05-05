import io
import html
from html.parser import HTMLParser
import os
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
import zipfile
from urllib.parse import urljoin

import requests

from newsbot_config import (
    DRIVER_PAGE_LOAD_TIMEOUT,
    SCROLL_SLEEP_SECONDS,
)


COINDESK_RSS_URL = "https://www.coindesk.com/arc/outboundfeeds/rss/"
PANEWS_HOME_URL = "https://www.panewslab.com/zh"
PANEWS_RSS_URLS = (
    "https://rss.panewslab.com/",
    "https://rss.panewslab.com/zh",
    "https://rss.panewslab.com/zh.xml",
)
PANEWS_PAGE_URLS = (
    "https://www.panewslab.com/zh",
    "https://www.panewslab.com/zh/index.html",
    "https://t-www.panewslab.com/zh",
    "https://t-www.panewslab.com/zh/index.html",
)
PANEWS_ARTICLE_PATTERNS = (
    "/zh/articledetails/",
    "/zh/newsdetails/",
    "/zh/articles/",
    "/en/articledetails/",
    "/en/newsdetails/",
    "/en/articles/",
    "articledetails",
    "newsdetails",
)
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


class LinkTextParser(HTMLParser):
    """Small anchor extractor used as a dependency-free fallback parser."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []
        self._href_stack = []
        self._text_parts = []

    def handle_starttag(self, tag, attrs):
        if tag != "a":
            return
        href = dict(attrs).get("href")
        self._href_stack.append(href)
        self._text_parts.append([])

    def handle_data(self, data):
        if self._text_parts:
            self._text_parts[-1].append(data)

    def handle_endtag(self, tag):
        if tag != "a" or not self._href_stack:
            return
        href = self._href_stack.pop()
        parts = self._text_parts.pop()
        text = html.unescape(" ".join("".join(parts).split()))
        if href and text:
            self.links.append((text, href))


def _http_session():
    sess = requests.Session()
    sess.verify = False
    sess.headers.update(DEFAULT_HEADERS)
    return sess


def _append_unique(result, seen, title, link, history_titles, limit):
    title = " ".join(html.unescape(title or "").split())
    link = (link or "").strip()
    if not title or not link:
        return False
    if title in seen or title in history_titles:
        return False
    result.append({"title": title, "link": link})
    seen.add(title)
    return len(result) >= limit


def _scrape_coindesk_http(history_titles, limit=5, logger=print):
    logger("正在通过 CoinDesk RSS 获取新闻...")
    try:
        resp = _http_session().get(COINDESK_RSS_URL, timeout=20)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
    except Exception as e:
        logger(f"CoinDesk RSS 获取失败: {e}")
        return []

    result = []
    seen = set()
    for item in root.findall(".//item"):
        title = item.findtext("title")
        link = item.findtext("link") or item.findtext("guid")
        if _append_unique(result, seen, title, link, history_titles, limit):
            break

    logger(f"CoinDesk RSS 获取到 {len(result)} 条新文章")
    return result


def _scrape_panews_http(history_titles, limit=10, logger=print):
    logger("正在通过 PANews RSS/网页文本获取新闻...")
    session = _http_session()

    for url in PANEWS_RSS_URLS:
        try:
            resp = session.get(url, timeout=12)
            resp.raise_for_status()
            root = ET.fromstring(resp.content)
        except Exception as e:
            logger(f"PANews RSS 获取失败({url}): {e}")
            continue

        result = []
        seen = set()
        for item in root.findall(".//item") + root.findall(".//{http://www.w3.org/2005/Atom}entry"):
            title = item.findtext("title")
            link = item.findtext("link") or item.findtext("guid")
            if link is None:
                atom_link = item.find("{http://www.w3.org/2005/Atom}link")
                link = atom_link.get("href") if atom_link is not None else None
            if _append_unique(result, seen, title, link, history_titles, limit):
                break
        if result:
            logger(f"PANews RSS 获取到 {len(result)} 条新文章")
            return result

    html_text = None
    base_url = PANEWS_HOME_URL
    for url in PANEWS_PAGE_URLS:
        try:
            resp = session.get(url, timeout=12)
            resp.raise_for_status()
            html_text = resp.text
            base_url = url
            break
        except Exception as e:
            logger(f"PANews 网页获取失败({url}): {e}")

    if not html_text:
        return []

    parser = LinkTextParser()
    parser.feed(html_text)

    result = []
    seen = set()
    for title, href in parser.links:
        if not any(pattern in href for pattern in PANEWS_ARTICLE_PATTERNS):
            continue
        link = urljoin(base_url, href)
        if _append_unique(result, seen, title, link, history_titles, limit):
            break

    logger(f"PANews 网页文本获取到 {len(result)} 条新文章")
    return result


def get_or_download_chromedriver(chrome_version, logger=print):
    """Download chromedriver for current Chrome major version and cache it."""
    import platform

    is_win = sys.platform == "win32"
    exe_name = "chromedriver.exe" if is_win else "chromedriver"
    if is_win:
        pf_str = "win64"
    elif sys.platform == "darwin":
        pf_str = "mac-arm64" if platform.machine() == "arm64" else "mac-x64"
    else:
        pf_str = "linux64"

    cache_dir = os.path.join(os.path.expanduser("~"), ".wdm_custom", "chromedriver", str(chrome_version))
    cached_path = os.path.join(cache_dir, exe_name)
    if os.path.exists(cached_path):
        logger(f"使用缓存的 ChromeDriver: {cached_path}")
        return cached_path

    logger(f"正在下载 ChromeDriver {chrome_version}...")
    sess = requests.Session()
    sess.verify = False
    sess.headers["Connection"] = "close"

    full_ver = None
    try:
        r = sess.get(
            f"https://googlechromelabs.github.io/chrome-for-testing/LATEST_RELEASE_{chrome_version}",
            timeout=20,
        )
        if r.status_code == 200:
            full_ver = r.text.strip()
            logger(f"  ChromeDriver 版本: {full_ver}")
    except Exception as e:
        logger(f"  LATEST_RELEASE 接口失败: {e}")

    if not full_ver:
        try:
            r = sess.get(
                "https://googlechromelabs.github.io/chrome-for-testing/known-good-versions-with-downloads.json",
                timeout=30,
            )
            data = r.json()
            matching = [
                v for v in data.get("versions", [])
                if v["version"].startswith(str(chrome_version) + ".")
            ]
            if matching:
                entry = matching[-1]
                dl_items = entry.get("downloads", {}).get("chromedriver", [])
                dl_link = next((d["url"] for d in dl_items if d["platform"] == pf_str), None)
                if dl_link:
                    logger(f"  从 JSON 找到下载链接: {dl_link}")
                    r2 = sess.get(dl_link, timeout=60)
                    if r2.status_code == 200:
                        os.makedirs(cache_dir, exist_ok=True)
                        with zipfile.ZipFile(io.BytesIO(r2.content)) as z:
                            for name in z.namelist():
                                if name.endswith(f"/{exe_name}") or name == exe_name:
                                    with z.open(name) as src, open(cached_path, "wb") as dst:
                                        dst.write(src.read())
                                    if not is_win:
                                        import stat
                                        os.chmod(cached_path, os.stat(cached_path).st_mode | stat.S_IEXEC)
                                        subprocess.run(["xattr", "-d", "com.apple.quarantine", cached_path], stderr=subprocess.DEVNULL)
                                        subprocess.run(["codesign", "-s", "-", "--force", cached_path], stderr=subprocess.DEVNULL)
                                    logger(f"  已保存: {cached_path}")
                                    return cached_path
        except Exception as e:
            logger(f"  JSON 回退也失败: {e}")
        return None

    dl_url = f"https://storage.googleapis.com/chrome-for-testing-public/{full_ver}/{pf_str}/chromedriver-{pf_str}.zip"
    try:
        logger(f"  正在下载: {dl_url}")
        r = sess.get(dl_url, timeout=60)
        if r.status_code != 200:
            logger(f"  下载失败，状态码: {r.status_code}")
            return None
        os.makedirs(cache_dir, exist_ok=True)
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            for name in z.namelist():
                if name.endswith(f"/{exe_name}") or name == exe_name:
                    with z.open(name) as src, open(cached_path, "wb") as dst:
                        dst.write(src.read())
                    if not is_win:
                        import stat
                        os.chmod(cached_path, os.stat(cached_path).st_mode | stat.S_IEXEC)
                        subprocess.run(["xattr", "-d", "com.apple.quarantine", cached_path], stderr=subprocess.DEVNULL)
                        subprocess.run(["codesign", "-s", "-", "--force", cached_path], stderr=subprocess.DEVNULL)
                    logger(f"  ChromeDriver 已保存: {cached_path}")
                    return cached_path
        logger(f"  zip 中未找到 {exe_name}")
    except Exception as e:
        logger(f"  下载 zip 失败: {e}")
    return None


def get_chrome_major_version():
    """Detect installed Chrome major version."""
    try:
        import winreg
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            for path in (
                r"Software\Google\Chrome\BLBeacon",
                r"Software\Wow6432Node\Google\Chrome\BLBeacon",
            ):
                try:
                    key = winreg.OpenKey(hive, path)
                    ver, _ = winreg.QueryValueEx(key, "version")
                    winreg.CloseKey(key)
                    m = re.search(r"(\d+)\.", ver)
                    if m:
                        return int(m.group(1))
                except Exception:
                    continue
    except ImportError:
        pass

    def decode_output(raw):
        for enc in ("utf-8", "gbk", "gb2312", "latin-1"):
            try:
                return raw.decode(enc)
            except Exception:
                continue
        return raw.decode("utf-8", errors="ignore")

    candidates = [
        ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "--version"],
        ["google-chrome", "--version"],
        ["google-chrome-stable", "--version"],
        ["chromium-browser", "--version"],
        ["chromium", "--version"],
    ]
    try:
        import undetected_chromedriver as uc
        chrome_path = uc.find_chrome_executable()
        if chrome_path:
            candidates.insert(0, [chrome_path, "--version"])
    except Exception:
        pass

    for cmd in candidates:
        try:
            raw = subprocess.check_output(cmd, stderr=subprocess.DEVNULL, timeout=5)
            out = decode_output(raw)
            m = re.search(r"(\d+)\.", out)
            if m:
                return int(m.group(1))
        except Exception:
            continue

    return None


def _scrape_coindesk(driver, history_titles, limit=5, logger=print):
    from selenium.webdriver.common.by import By

    logger("正在访问 CoinDesk...")
    driver.set_page_load_timeout(DRIVER_PAGE_LOAD_TIMEOUT)
    try:
        driver.get("https://www.coindesk.com/")
    except Exception:
        pass
    logger(f"CoinDesk 页面标题: {driver.title}")
    driver.execute_script("window.scrollTo(0, 500);")
    time.sleep(SCROLL_SLEEP_SECONDS)

    items = driver.find_elements(
        By.CSS_SELECTOR,
        "a[class*='content-card-title'], h2[class*='title'], h3[class*='title'] a, "
        "a[href*='/markets/'], a[href*='/business/'], a[href*='/policy/']",
    )
    if not items:
        items = driver.find_elements(By.XPATH, "//a[contains(@class, 'title') or contains(@class, 'card')]")

    result = []
    seen = set()
    for item in items:
        try:
            title = item.text.strip()
            link = item.get_attribute("href")
            if title and link and title not in seen and title not in history_titles:
                result.append({"title": title, "link": link})
                seen.add(title)
            if len(result) >= limit:
                break
        except Exception:
            continue

    logger(f"CoinDesk 获取到 {len(result)} 条新文章")
    return result


def _scrape_panews(driver, history_titles, limit=10, logger=print):
    from selenium.webdriver.common.by import By

    logger("正在访问 PANews...")
    driver.set_page_load_timeout(DRIVER_PAGE_LOAD_TIMEOUT)
    try:
        driver.get("https://www.panewslab.com/zh/index.html")
    except Exception:
        pass
    logger(f"PANews 页面标题: {driver.title}")
    driver.execute_script("window.scrollTo(0, 800);")
    time.sleep(SCROLL_SLEEP_SECONDS)

    items = driver.find_elements(
        By.CSS_SELECTOR,
        "a[href*='articledetails'], a[href*='article'], "
        "h2 a, h3 a, .article-title a, .news-title a",
    )

    result = []
    seen = set()
    for item in items:
        try:
            title = item.text.strip()
            link = item.get_attribute("href")
            if not link:
                continue
            if not link.startswith("http"):
                link = "https://www.panewslab.com" + link
            if title and link and title not in seen and title not in history_titles:
                result.append({"title": title, "link": link})
                seen.add(title)
            if len(result) >= limit:
                break
        except Exception:
            continue

    logger(f"PANews 获取到 {len(result)} 条新文章")
    return result


def collect_news_batch(history_titles, coindesk_limit, panews_limit, logger=print):
    """Fetch latest CoinDesk/PANews items in one browser session."""
    coindesk_news = _scrape_coindesk_http(history_titles, limit=coindesk_limit, logger=logger)
    panews_news = _scrape_panews_http(history_titles, limit=panews_limit, logger=logger)
    if coindesk_news and panews_news:
        logger(f"\n合计: CoinDesk {len(coindesk_news)} 条 + PANews {len(panews_news)} 条")
        return {
            "ok": True,
            "coindesk": coindesk_news,
            "panews": panews_news,
            "error": None,
        }

    logger("部分来源未获取到新闻，尝试启动浏览器兜底抓取...")
    try:
        import undetected_chromedriver as uc
    except ImportError as e:
        return {
            "ok": False,
            "coindesk": [],
            "panews": [],
            "error": f"HTTP/RSS 未获取到新闻，且缺少浏览器抓取依赖: {e}",
        }

    options = uc.ChromeOptions()
    options.add_argument("--headless")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.page_load_strategy = "eager"

    driver = None
    try:
        chrome_ver = get_chrome_major_version()
        logger(f"检测到 Chrome 版本: {chrome_ver}")
        driver_path = get_or_download_chromedriver(chrome_ver, logger=logger) if chrome_ver else None
        if driver_path:
            driver = uc.Chrome(options=options, version_main=chrome_ver, driver_executable_path=driver_path)
        else:
            driver = uc.Chrome(options=options, version_main=chrome_ver)

        if not coindesk_news:
            coindesk_news = _scrape_coindesk(driver, history_titles, limit=coindesk_limit, logger=logger)
        if not panews_news:
            panews_news = _scrape_panews(driver, history_titles, limit=panews_limit, logger=logger)

        logger(f"\n合计: CoinDesk {len(coindesk_news)} 条 + PANews {len(panews_news)} 条")
        return {
            "ok": True,
            "coindesk": coindesk_news,
            "panews": panews_news,
            "error": None,
        }

    except Exception as e:
        return {
            "ok": False,
            "coindesk": [],
            "panews": [],
            "error": str(e),
        }

    finally:
        if driver:
            try:
                if hasattr(driver, "browser_pid") and driver.browser_pid:
                    try:
                        os.kill(driver.browser_pid, 15)
                    except Exception:
                        pass
                driver.quit()
            except Exception:
                pass
