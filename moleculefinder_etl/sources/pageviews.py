"""Wikipedia pageviews as the free demand proxy for build order + popularity."""
from __future__ import annotations
import datetime as dt
import requests
from tenacity import retry, wait_exponential, stop_after_attempt
from ..config import WIKIMEDIA_PAGEVIEWS, USER_AGENT


@retry(wait=wait_exponential(min=1, max=20), stop=stop_after_attempt(3))
def monthly_average(article_title: str, months: int = 12) -> int:
    """Trailing-N-month average monthly pageviews for an en.wikipedia article."""
    end = dt.date.today().replace(day=1)
    start = (end - dt.timedelta(days=31 * months)).replace(day=1)
    title = article_title.replace(" ", "_")
    url = (f"{WIKIMEDIA_PAGEVIEWS}/en.wikipedia/all-access/user/"
           f"{title}/monthly/{start:%Y%m%d}/{end:%Y%m%d}")
    r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
    if r.status_code == 404:
        return 0
    r.raise_for_status()
    items = r.json().get("items", [])
    if not items:
        return 0
    return round(sum(i["views"] for i in items) / len(items))
