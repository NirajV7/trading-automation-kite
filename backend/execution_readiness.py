from datetime import datetime, time as datetime_time
from zoneinfo import ZoneInfo

from market_data_guard import newest_live_tick_age_seconds

IST = ZoneInfo("Asia/Kolkata")
MARKET_OPEN = datetime_time(9, 15)
ORB_READY_TIME = datetime_time(9, 30)
RADAR_READY_TIME = datetime_time(9, 35)
MARKET_CLOSE = datetime_time(15, 30)
DEFAULT_STALE_THRESHOLD_SECONDS = 15

WAITING_FOR_MARKET_OPEN = "WAITING_FOR_MARKET_OPEN"
WARMING_UP = "WARMING_UP"
ORB_BUILDING = "ORB_BUILDING"
READY = "READY"
BLOCKED_STALE_DATA = "BLOCKED_STALE_DATA"


def now_ist():
    return datetime.now(IST)


def _coerce_ist(dt):
    if dt is None:
        return now_ist()
    if dt.tzinfo is None:
        return dt.replace(tzinfo=IST)
    return dt.astimezone(IST)


def is_market_day(dt=None):
    return _coerce_ist(dt).weekday() < 5


def is_before_open(dt=None):
    current = _coerce_ist(dt)
    return not is_market_day(current) or current.time() < MARKET_OPEN


def is_warmup_window(dt=None):
    current = _coerce_ist(dt)
    return is_market_day(current) and MARKET_OPEN <= current.time() < ORB_READY_TIME


def is_orb_window(dt=None):
    current = _coerce_ist(dt)
    return is_market_day(current) and ORB_READY_TIME <= current.time() <= MARKET_CLOSE


def is_radar_window(dt=None):
    current = _coerce_ist(dt)
    return is_market_day(current) and RADAR_READY_TIME <= current.time() <= MARKET_CLOSE


def assess_execution_readiness(
    *,
    dry_run=False,
    orb_count=0,
    snapshot=None,
    stale_threshold_seconds=DEFAULT_STALE_THRESHOLD_SECONDS,
    current_time=None,
):
    if dry_run:
        return {
            "ready": True,
            "orb_ready": True,
            "radar_ready": True,
            "status": READY,
            "reason": "Dry-run mode bypasses live market readiness gate.",
            "tick_age_seconds": 0.0,
            "orb_count": orb_count,
        }

    current = _coerce_ist(current_time)
    if is_before_open(current):
        return {
            "ready": False,
            "orb_ready": False,
            "radar_ready": False,
            "status": WAITING_FOR_MARKET_OPEN,
            "reason": "Market is not open yet. Engine parked safely.",
            "tick_age_seconds": None,
            "orb_count": orb_count,
        }

    tick_age = newest_live_tick_age_seconds(snapshot=snapshot)
    threshold = float(stale_threshold_seconds)

    if is_warmup_window(current):
        fresh = tick_age is not None and tick_age <= threshold
        return {
            "ready": False,
            "orb_ready": False,
            "radar_ready": False,
            "status": WARMING_UP,
            "reason": "Market warming up; ORB waits until 09:30 and Radar waits until 09:35.",
            "tick_age_seconds": tick_age,
            "tick_fresh": fresh,
            "orb_count": orb_count,
        }

    if not is_orb_window(current):
        return {
            "ready": False,
            "orb_ready": False,
            "radar_ready": False,
            "status": WAITING_FOR_MARKET_OPEN,
            "reason": "Market session is closed. Engine parked safely.",
            "tick_age_seconds": tick_age,
            "orb_count": orb_count,
        }

    if tick_age is None or tick_age > threshold:
        return {
            "ready": False,
            "orb_ready": False,
            "radar_ready": False,
            "status": BLOCKED_STALE_DATA,
            "reason": "Live market data stale during market window.",
            "tick_age_seconds": tick_age,
            "orb_count": orb_count,
        }

    if int(orb_count or 0) <= 0:
        return {
            "ready": False,
            "orb_ready": False,
            "radar_ready": is_radar_window(current),
            "status": ORB_BUILDING,
            "reason": "Waiting for 09:15 ORB candle; Radar waits until 09:35.",
            "tick_age_seconds": tick_age,
            "orb_count": orb_count,
        }

    if not is_radar_window(current):
        return {
            "ready": False,
            "orb_ready": True,
            "radar_ready": False,
            "status": WARMING_UP,
            "reason": "ORB ready; Radar waits until 09:35 for cleaner confirmation.",
            "tick_age_seconds": tick_age,
            "orb_count": orb_count,
        }

    return {
        "ready": True,
        "orb_ready": True,
        "radar_ready": True,
        "status": READY,
        "reason": "Fresh ticks, Radar, and ORB ranges ready.",
        "tick_age_seconds": tick_age,
        "orb_count": orb_count,
    }
