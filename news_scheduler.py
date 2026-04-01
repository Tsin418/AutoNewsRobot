from datetime import datetime, timedelta
import time


def get_next_slot_boundary(now, interval_minutes):
    """Return the next half-hour-like slot boundary after `now`."""
    base_minute = (now.minute // interval_minutes) * interval_minutes
    next_run_at = now.replace(minute=base_minute, second=0, microsecond=0)
    if next_run_at <= now:
        next_run_at += timedelta(minutes=interval_minutes)
    return next_run_at


def move_to_future_slot(next_run_at, now, interval_minutes):
    """Advance slot pointer until it is strictly greater than `now`."""
    while next_run_at <= now:
        next_run_at += timedelta(minutes=interval_minutes)
    return next_run_at


def run_scheduler_loop(
    *,
    tz,
    interval_minutes,
    poll_seconds,
    should_run_slot,
    on_slot,
    logger=print,
):
    """Loop forever and execute `on_slot(slot_time, now)` when a slot is due."""
    next_run_at = get_next_slot_boundary(now=datetime.now(tz), interval_minutes=interval_minutes)

    while True:
        try:
            now = datetime.now(tz)
            if now >= next_run_at:
                slot_time = next_run_at
                next_run_at = move_to_future_slot(next_run_at, now, interval_minutes)

                if should_run_slot(slot_time):
                    on_slot(slot_time, now)

            time.sleep(poll_seconds)

        except Exception as e:
            logger(f"后台循环发生报错: {e}")
            # Cool down before retrying the scheduler tick.
            time.sleep(max(30, poll_seconds * 6))
