"""Port of server/utils/marketHours.js.

Mon-Fri 09:15-15:30 IST. There is no exchange holiday calendar: on a holiday
Yahoo simply serves the last close, which is the behaviour the Express app has
and therefore the behaviour preserved here.

The Express version formats a Date through ``toLocaleString("en-US", {
timeZone: "Asia/Kolkata" })``. India has no daylight saving, so a fixed +05:30
offset is exactly equivalent and avoids depending on the ``tzdata`` package,
which is not installed on this machine.
"""

from datetime import datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))

MARKET_OPEN_MINUTES = 9 * 60 + 15  # 09:15
MARKET_CLOSE_MINUTES = 15 * 60 + 30  # 15:30


def is_market_open(now=None):
    """True between 09:15 and 15:30 IST on a weekday, inclusive at both ends.

    Compares whole minutes, exactly as the Express version does, so 15:30:59
    still counts as open.
    """
    moment = now or datetime.now(timezone.utc)
    ist_now = moment.astimezone(IST)

    if ist_now.weekday() >= 5:  # Saturday = 5, Sunday = 6
        return False

    total_minutes = ist_now.hour * 60 + ist_now.minute
    return MARKET_OPEN_MINUTES <= total_minutes <= MARKET_CLOSE_MINUTES
