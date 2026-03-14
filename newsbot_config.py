from datetime import timedelta, timezone

# Timezone and scheduler parameters
HKT_TZ = timezone(timedelta(hours=8))
SLOT_INTERVAL_MINUTES = 30
SCHEDULER_POLL_SECONDS = 5
RUN_HOUR_START = 9
RUN_HOUR_END = 23
MIDNIGHT_SLOT_HOUR = 0
MIDNIGHT_SLOT_MINUTE = 0

# Morning summary trigger
MORNING_SUMMARY_HOUR = 9
MORNING_SUMMARY_MINUTE = 0

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

# Single-instance lock
LOCK_HOST = "127.0.0.1"
LOCK_PORT = 47293
