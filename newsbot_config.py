from datetime import timedelta, timezone

# Timezone
HKT_TZ = timezone(timedelta(hours=8))

# Fetch and output parameters
COINDESK_LIMIT = 5
PANEWS_LIMIT = 10
NEWS_LOOKBACK_MINUTES = 30

# Selenium and scraping timing
DRIVER_PAGE_LOAD_TIMEOUT = 30
SCROLL_SLEEP_SECONDS = 3

# Reliability settings
FEISHU_REQUEST_TIMEOUT_SECONDS = 10
FEISHU_RETRY_TIMES = 3
FEISHU_RETRY_BACKOFF_BASE_SECONDS = 2
# Backward-compatible alias used by newsbot.py
FEISHU_RETRIES = FEISHU_RETRY_TIMES
