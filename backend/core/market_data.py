import os
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


SEARCH_API = "https://searchadapter.eastmoney.com/api/suggest/get"
SEARCH_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Referer": "https://quote.eastmoney.com/",
    "Accept": "application/json",
    "Accept-Encoding": "gzip, deflate, br",
}
SEARCH_TIMEOUT = 15

MARKET_CODE_MAP = {
    "0": "sz",
    "1": "sh",
    "105": "us",
    "116": "hk",
}


_RETRY = Retry(
    total=3,
    connect=3,
    read=3,
    backoff_factor=0.6,
    status_forcelist=(429, 500, 502, 503, 504),
    allowed_methods=frozenset(["GET", "HEAD"]),
    raise_on_status=False,
)


def _build_session() -> requests.Session:
    s = requests.Session()
    s.trust_env = os.getenv("EASTMONEY_USE_PROXY", "0") == "1"
    adapter = HTTPAdapter(max_retries=_RETRY, pool_connections=20, pool_maxsize=50)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    return s


_SESSION = _build_session()


def resolve_stock_match(field: str, query: str):
    query = (query or "").strip()
    if not query:
        return None

    try:
        response = _SESSION.get(
            SEARCH_API,
            params={
                "input": query,
                "type": "14",
                "token": "D43BF722C8E33BDC906FB84D85E326E8",
                "count": "10",
            },
            headers=SEARCH_HEADERS,
            timeout=SEARCH_TIMEOUT,
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError):
        return None
    rows = ((payload or {}).get("QuotationCodeTable") or {}).get("Data") or []
    normalized = [_normalize_search_row(row) for row in rows]
    normalized = [row for row in normalized if row["code"] and row["name"]]
    if not normalized:
        return None

    if field == "code":
        for row in normalized:
            if row["code"] == query:
                return row
    else:
        for row in normalized:
            if row["name"] == query:
                return row

    return normalized[0]


def _normalize_search_row(row: dict) -> dict:
    code = str(row.get("Code") or "").strip().upper()
    name = str(row.get("Name") or "").strip()
    market_code = str(row.get("MktNum") or "").strip()
    market = _market_from_mktnum(market_code)
    return {
        "code": code,
        "name": name,
        "market": market,
        "secid": f"{market_code}.{code}" if market_code and code else "",
    }


def _market_from_mktnum(value: str) -> str:
    return MARKET_CODE_MAP.get(value, "")
