import requests
from datetime import datetime, timedelta, timezone
from collections import defaultdict
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import re, os
from dotenv import load_dotenv

load_dotenv()

AUTH_KEY = os.getenv("AUTH_KEY")
if not AUTH_KEY:
    raise RuntimeError("AUTH_KEY not found in environment. Check .env")

NX, NY = 59, 127  # 동네예보 격자 (마포구 연남동 기준)
REG_ID_A = "11B00000"  # 중기예보 육상(서울/인천/경기)
REG_ID_C = "11B10101"  # 중기예보 기온/단기 육상(서울)

SKY_MAP = {
    "1": "맑음",
    "2": "구름많음",
    "3": "구름많음",
    "4": "흐림",
    "DB01": "맑음",
    "DB02": "구름많음",
    "DB03": "구름많음",
    "DB04": "흐림",
    "B01": "맑음",
    "WB02": "구름많음",
    "WB03": "구름많음",
    "WB04": "흐림",
}
PTY_MAP = {
    "0": "없음",
    "1": "비",
    "4": "비",
    "2": "비/눈",
    "3": "눈",
    "WB00": "없음",
    "WB09": "비",
    "WB11": "비/눈",
    "WB13": "비/눈",
    "WB12": "눈",
}
KST = timezone(timedelta(hours=9))


def clean_st_value(v):
    if v is None:
        return None
    s = str(v)
    m = re.search(r"\d+", s)
    return m.group(0) if m else None


# ─────────────────────────────────────────────────────────────
# HTTP 세션 + 재시도/백오프
# ─────────────────────────────────────────────────────────────
_session = requests.Session()
_retries = Retry(
    total=4,
    connect=2,
    read=2,
    status=2,
    backoff_factor=0.8,
    status_forcelist=(408, 429, 500, 502, 503, 504),
    allowed_methods=("GET", "HEAD"),
    respect_retry_after_header=True,
    raise_on_status=False,
)
_adapter = HTTPAdapter(max_retries=_retries,
                       pool_connections=10,
                       pool_maxsize=20)
_session.mount("https://", _adapter)
_session.mount("http://", _adapter)
_session.headers.update({"User-Agent": "ESP-Dashboard/1.0 (+local)"})


def http_get(url, timeout=(3.05, 10.0)):
    return _session.get(url, timeout=timeout)


def get_base_hourly(now_kst):
    if now_kst.hour < 2:
        base_date = (now_kst - timedelta(days=1)).strftime("%Y%m%d")
        base_time = "2300"
    else:
        base_date = now_kst.strftime("%Y%m%d")
        base_time = "0200"
    return base_date, base_time


# ─────────────────────────────────────────────────────────────
# hourly
# ─────────────────────────────────────────────────────────────
def fetch_vilage_json(base_date_hourly, base_time_hourly):
    url = (
        "https://apihub.kma.go.kr/api/typ02/openApi/VilageFcstInfoService_2.0/getVilageFcst"
        f"?pageNo=1&numOfRows=2500&dataType=JSON"
        f"&base_date={base_date_hourly}&base_time={base_time_hourly}"
        f"&nx={NX}&ny={NY}&authKey={AUTH_KEY}")
    res = http_get(url, timeout=(5, 12))
    res.raise_for_status()
    data = res.json()
    return data["response"]["body"]["items"]["item"]


def build_hourly_data(items, now_kst_key, hours_ahead=16):
    if not items:
        return {}

    items = sorted(items, key=lambda x: (x["fcstDate"], x["fcstTime"]))

    def key_at(idx):
        return items[idx]["fcstDate"] + items[idx]["fcstTime"]

    total = len(items)
    i = 0
    while i < total and key_at(i) < now_kst_key:
        i += 1
    if i == total:
        i = max(0, total - hours_ahead)

    hourly_data = {}
    prev_key = None
    blocks_done = 0

    while i < total:
        it = items[i]
        fcst_key = it["fcstDate"] + it["fcstTime"]
        category = it["category"]

        if prev_key is None:
            prev_key = fcst_key
        elif fcst_key != prev_key:
            blocks_done += 1
            if blocks_done >= hours_ahead:
                break
            prev_key = fcst_key

        if category == "SKY":
            value = SKY_MAP.get(it["fcstValue"], it["fcstValue"])
        elif category == "PTY":
            value = PTY_MAP.get(it["fcstValue"], it["fcstValue"])
        elif category == "TMP":
            value = it["fcstValue"]
        else:
            i += 1
            continue

        hourly_data.setdefault(fcst_key, {})[category] = value
        i += 1

    return hourly_data


# ─────────────────────────────────────────────────────────────
# daily (day1~4: 단기 + 육상)
# ─────────────────────────────────────────────────────────────
def build_daily_temp_in3day(items, base_time):
    if not items:
        return {}
    daily_data = defaultdict(dict)
    for it in items:
        if it.get("baseTime") != base_time:
            continue
        category = it.get("category")
        if category not in ("TMN", "TMX"):
            continue
        date_key = it.get("fcstDate")
        if not date_key:
            continue
        value = it.get("fcstValue")
        if category not in daily_data[date_key]:
            daily_data[date_key][category] = value
    return dict(daily_data)


def build_daily_sky_in3day(base_date):
    base_dt = datetime.strptime(base_date, "%Y%m%d")
    url = f"https://apihub.kma.go.kr/api/typ01/url/fct_afs_dl.php?reg={REG_ID_C}&disp=0&authKey={AUTH_KEY}"
    res = http_get(url, timeout=(3.05, 20.0))
    res.raise_for_status()

    want_dates = {(base_dt + timedelta(days=i)).strftime("%Y%m%d")
                  for i in range(4)}
    daily_data = {}

    for raw in res.text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        cols = line.split()
        if len(cols) < 16:
            continue
        TM_EF = cols[2]
        if len(TM_EF) < 12:
            continue
        date_key, hhmm = TM_EF[:8], TM_EF[-4:]
        if date_key not in want_dates or hhmm not in ("0000", "1200"):
            continue

        part = "AM" if hhmm == "0000" else "PM"
        try:
            st, sky, pty = cols[13], cols[14], cols[15]
        except IndexError:
            continue

        daily_data.setdefault(date_key, {})
        if part not in daily_data[date_key]:
            daily_data[date_key][part] = {
                "SKY": SKY_MAP.get(sky, sky),
                "PTY": PTY_MAP.get(pty, pty),
                "ST": clean_st_value(st),
            }
    return daily_data


# ─────────────────────────────────────────────────────────────
# daily (day5~8: 중기 기온 + 육상)
# ─────────────────────────────────────────────────────────────
def merge_daily_temp_sky(daily_temp, daily_sky):
    merged = {}
    for date_key in sorted(set(daily_temp) | set(daily_sky)):
        temp_info = daily_temp.get(date_key, {})
        sky_info = daily_sky.get(date_key, {})
        merged[date_key] = {
            "TMN": temp_info.get("TMN"),
            "TMX": temp_info.get("TMX"),
            "AM": sky_info.get("AM"),
            "PM": sky_info.get("PM"),
        }
    return merged


def build_daily_temp_after3day(base_date):
    base_dt = datetime.strptime(base_date, "%Y%m%d")
    start_dt = base_dt + timedelta(days=4)  # 5일차부터
    url = f"https://apihub.kma.go.kr/api/typ01/url/fct_afs_wc.php?reg={REG_ID_C}&disp=0&authKey={AUTH_KEY}"
    res = http_get(url, timeout=(3.05, 20.0))
    res.raise_for_status()

    want_dates = {(start_dt + timedelta(days=i)).strftime("%Y%m%d")
                  for i in range(4)}
    daily_data = {}

    for raw in res.text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        cols = line.split()
        if len(cols) < 8:
            continue
        TM_EF = cols[2]
        if len(TM_EF) < 8:
            continue
        date_key = TM_EF[:8]
        if date_key not in want_dates:
            continue
        try:
            min_temp, max_temp = cols[6], cols[7]
        except IndexError:
            continue
        daily_data[date_key] = {"TMN": min_temp, "TMX": max_temp}
    return daily_data


def build_daily_sky_after3day(base_date):
    base_dt = datetime.strptime(base_date, "%Y%m%d")
    start_dt = base_dt + timedelta(days=4)  # 5일차부터
    url = f"https://apihub.kma.go.kr/api/typ01/url/fct_afs_wl.php?reg={REG_ID_A}&disp=0&authKey={AUTH_KEY}"
    res = http_get(url, timeout=(3.05, 20.0))
    res.raise_for_status()

    want_dates = {(start_dt + timedelta(days=i)).strftime("%Y%m%d")
                  for i in range(4)}
    daily_data = {}

    for raw in res.text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        cols = line.split()
        if len(cols) < 11:
            continue
        TM_EF = cols[2]
        if len(TM_EF) < 12:
            continue
        date_key, hhmm = TM_EF[:8], TM_EF[-4:]
        if date_key not in want_dates or hhmm not in ("0000", "1200"):
            continue

        part = "AM" if hhmm == "0000" else "PM"
        try:
            sky, pty, st = cols[6], cols[7], cols[10]
        except IndexError:
            continue

        daily_data.setdefault(date_key, {})
        if part not in daily_data[date_key]:
            daily_data[date_key] = {
                **daily_data[date_key],
                part: {
                    "SKY": SKY_MAP.get(sky, sky),
                    "PTY": PTY_MAP.get(pty, pty),
                    "ST": clean_st_value(st),
                },
            }
    return daily_data


# ─────────────────────────────────────────────────────────────
# 보조
# ─────────────────────────────────────────────────────────────
def pick_best_hour_key(hourly_data, preferred_key):
    if preferred_key in hourly_data:
        return preferred_key
    if not hourly_data:
        return None
    keys = sorted(hourly_data.keys())
    for k in keys:
        if k >= preferred_key:
            return k
    return keys[-1]


# ─────────────────────────────────────────────────────────────
# public API
# ─────────────────────────────────────────────────────────────
def get_weather_data():
    now_kst = datetime.now(KST)
    base_date, base_time = get_base_hourly(now_kst)

    # hourly
    try:
        vilage_data = fetch_vilage_json(base_date, base_time)
        now_date = now_kst.strftime("%Y%m%d")
        now_hour = now_kst.strftime("%H00")
        hourly_data = build_hourly_data(vilage_data, now_date + now_hour)
    except Exception:
        hourly_data = {}

    # daily (day1~4)
    daily_in3day = {}
    try:
        daily_temp_in3day = build_daily_temp_in3day(
            vilage_data if 'vilage_data' in locals() else [], base_time)
    except Exception:
        daily_temp_in3day = {}
    try:
        daily_sky_in3day = build_daily_sky_in3day(now_kst.strftime("%Y%m%d"))
    except Exception:
        daily_sky_in3day = {}
    if daily_temp_in3day or daily_sky_in3day:
        daily_in3day = merge_daily_temp_sky(daily_temp_in3day,
                                            daily_sky_in3day)

    # daily (day5~8)
    daily_after3day = {}
    try:
        daily_temp_after3day = build_daily_temp_after3day(
            now_kst.strftime("%Y%m%d"))
    except Exception:
        daily_temp_after3day = {}
    try:
        daily_sky_after3day = build_daily_sky_after3day(
            now_kst.strftime("%Y%m%d"))
    except Exception:
        daily_sky_after3day = {}
    if daily_temp_after3day or daily_sky_after3day:
        daily_after3day = merge_daily_temp_sky(daily_temp_after3day,
                                               daily_sky_after3day)

    daily_data = {**daily_in3day, **daily_after3day}

    # now
    preferred_key = now_kst.strftime("%Y%m%d%H00")
    best_key = pick_best_hour_key(hourly_data, preferred_key)

    now_obj = {}
    if best_key and best_key in hourly_data:
        now_obj["TMP"] = hourly_data[best_key].get("TMP")
        now_obj["SKY"] = hourly_data[best_key].get("SKY")
        now_obj["PTY"] = hourly_data[best_key].get("PTY")
    else:
        now_obj["TMP"] = None
        now_obj["SKY"] = None
        now_obj["PTY"] = None

    today_key = now_kst.strftime("%Y%m%d")
    now_obj["TMX"] = daily_data.get(today_key, {}).get("TMX")
    now_obj["TMN"] = daily_data.get(today_key, {}).get("TMN")

    print(
        f"[weather] hourly={len(hourly_data)} slots, daily={len(daily_data)} days, now_key={best_key}, now={now_obj}"
    )
    return hourly_data, daily_data, now_obj
