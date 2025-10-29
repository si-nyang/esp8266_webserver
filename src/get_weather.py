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

# ── 마포구 연남동 기준 격자/코드 ──────────────────────────────
NX, NY = 59, 127
REG_ID_A = "11B00000"  # 중기 육상(수도권)
REG_ID_C = "11B10101"  # 서울(중기 기온/단기 연계)

# ── 코드 매핑 ────────────────────────────────────────────────
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
    "2": "비/눈",
    "3": "눈",
    "4": "비",
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


# ─────────────────────────────────────────────────────────────
# ※ 변경 1) 단기예보 base_time 계산을 '8개 발표 슬롯' 기준으로 수정
#    (02,05,08,11,14,17,20,23 중 '현재 시각 이전의 가장 최근 슬롯')
# ─────────────────────────────────────────────────────────────
_SHORTTERM_SLOTS = [2, 5, 8, 11, 14, 17, 20, 23]


def get_base_hourly(now_kst: datetime):
    # 현재 시각 이전의 가장 최근 발표 기준시
    for h in reversed(_SHORTTERM_SLOTS):
        cand = now_kst.replace(hour=h, minute=0, second=0, microsecond=0)
        if cand <= now_kst:
            return cand.strftime("%Y%m%d"), f"{h:02d}00"
    # 자정~02:00 사이인 경우 전날 23:00
    prev_day = now_kst - timedelta(days=1)
    return prev_day.strftime("%Y%m%d"), "2300"


# ─────────────────────────────────────────────────────────────
# hourly
# ─────────────────────────────────────────────────────────────
def fetch_vilage_json(base_date_hourly, base_time_hourly):
    # KMA apihub typ02: authKey 파라미터 사용
    url = (
        "https://apihub.kma.go.kr/api/typ02/openApi/VilageFcstInfoService_2.0/getVilageFcst"
        f"?pageNo=1&numOfRows=2500&dataType=JSON"
        f"&base_date={base_date_hourly}&base_time={base_time_hourly}"
        f"&nx={NX}&ny={NY}&authKey={AUTH_KEY}")
    res = http_get(url, timeout=(5, 12))
    res.raise_for_status()
    data = res.json()
    return data["response"]["body"]["items"]["item"]


# ─────────────────────────────────────────────────────────────
# ※ 변경 2) hourly 빌드: '현재시각 이후 N시간'을 안정적으로 수집
#    - TMP/PTY/SKY만 모아 키(fcstDate+fcstTime)별 dict 구성
#    - now 기준 가장 가까운 슬롯부터 최대 hours_ahead까지
# ─────────────────────────────────────────────────────────────
def build_hourly_data(items, now_kst_key, hours_ahead=16):
    if not items:
        return {}

    items = sorted(items, key=lambda x: (x["fcstDate"], x["fcstTime"]))
    # fcst 키 목록(중복 제거 순서 유지)
    fcst_keys = []
    seen = set()
    for it in items:
        k = it["fcstDate"] + it["fcstTime"]
        if k not in seen:
            seen.add(k)
            fcst_keys.append(k)

    # now 이후의 시작 인덱스
    start_idx = 0
    for idx, k in enumerate(fcst_keys):
        if k >= now_kst_key:
            start_idx = idx
            break

    fcst_slice = fcst_keys[start_idx:start_idx + hours_ahead]
    wanted = set(fcst_slice)

    hourly_data = {}
    for it in items:
        k = it["fcstDate"] + it["fcstTime"]
        if k not in wanted:
            continue
        cat = it["category"]
        if cat == "SKY":
            val = SKY_MAP.get(it["fcstValue"], it["fcstValue"])
        elif cat == "PTY":
            val = PTY_MAP.get(it["fcstValue"], it["fcstValue"])
        elif cat == "TMP":
            val = it["fcstValue"]
        else:
            continue
        hourly_data.setdefault(k, {})[cat] = val

    return hourly_data


# ─────────────────────────────────────────────────────────────
# daily (day1~4: 단기 + 육상)
# ─────────────────────────────────────────────────────────────
def build_daily_temp_in3day(items, base_time):
    if not items:
        return {}
    daily_data = defaultdict(dict)
    for it in items:
        # 같은 base_time만 취함(발표 일관성)
        if it.get("baseTime") != base_time:
            continue
        category = it.get("category")
        if category not in ("TMN", "TMX"):
            continue
        date_key = it.get("fcstDate")
        if not date_key:
            continue
        value = it.get("fcstValue")
        # 값 덮어쓰기 방지(최초값 우선)
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
        # 같은 파트 중복 방지
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
    """선호키가 있으면 그걸, 없으면 현재 이후 첫 키 또는 마지막 키."""
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

    # (변경) 8개 슬롯 기준으로 base date/time 산출
    base_date, base_time = get_base_hourly(now_kst)

    # hourly
    try:
        vilage_data = fetch_vilage_json(base_date, base_time)
        now_date = now_kst.strftime("%Y%m%d")
        now_hour = now_kst.strftime("%H00")
        hourly_data = build_hourly_data(vilage_data, now_date + now_hour)
    except Exception:
        vilage_data = []  # 뒤에서 기온 1~3일 사용 가능하도록 기본값
        hourly_data = {}

    # daily (day1~4): 단기 기온 + 육상(AM/PM SKY/PTY/ST)
    try:
        daily_temp_in3day = build_daily_temp_in3day(vilage_data, base_time)
    except Exception:
        daily_temp_in3day = {}
    try:
        daily_sky_in3day = build_daily_sky_in3day(now_kst.strftime("%Y%m%d"))
    except Exception:
        daily_sky_in3day = {}
    daily_in3day = merge_daily_temp_sky(daily_temp_in3day, daily_sky_in3day) \
                   if (daily_temp_in3day or daily_sky_in3day) else {}

    # daily (day5~8): 중기 기온 + 육상(AM/PM)
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
    daily_after3day = merge_daily_temp_sky(daily_temp_after3day, daily_sky_after3day) \
                      if (daily_temp_after3day or daily_sky_after3day) else {}

    daily_data = {**daily_in3day, **daily_after3day}

    # now: 단기(hourly)에서 가장 가까운 슬롯 선택
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
        f"[weather] base={base_date} {base_time}, hourly={len(hourly_data)} slots, "
        f"daily={len(daily_data)} days, now_key={best_key}, now={now_obj}")
    return hourly_data, daily_data, now_obj
