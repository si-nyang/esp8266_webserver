import requests
from datetime import datetime, timedelta, timezone
from collections import defaultdict
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import re, os

from dotenv import load_dotenv
load_dotenv()

AUTH_KEY = os.getenv("AUTH_KEY")
NX, NY = 59, 127 # 동네예보 단기예보: 격자 (기상청 기준: 서울 마포구 연남동)
REG_ID_A = "11B00000" # 중기예보 육상 조회: 예보구역코드(서울, 인천, 경기)
REG_ID_C = "11B10101" # 중기예보 기온 조회 & 단기예보 육상 조회: 예보구역코드(서울)

# SKY/PTY 코드 매핑
SKY_MAP = {"1": "맑음",    "2": "구름많음",    "3": "구름많음",    "4": "흐림",
           "DB01": "맑음", "DB02": "구름많음", "DB03": "구름많음", "DB04": "흐림",
           "B01": "맑음",  "WB02": "구름많음", "WB03": "구름많음", "WB04": "흐림"}  # 2, 3 -> 구름많고
PTY_MAP = {"0": "없음",    "1": "비", "4": "비", "2": "비/눈",                     "3": "눈",
           "WB00": "없음", "WB09": "비",        "WB11": "비/눈","WB13": "비/눈",   "WB12": "눈"}
KST = timezone(timedelta(hours=9))

def clean_st_value(v):
    """문자열에서 숫자만 추출해 문자열로 반환 ('비" 60' → '60')"""
    if v is None:
        return None
    s = str(v)
    m = re.search(r"\d+", s)
    return m.group(0) if m else None

_session = requests.Session()
_retries = Retry(
    total=None,             # 각 슬롯별로 개수 분리
    connect=4,              # 연결 실패 재시도
    read=4,                 # 응답 지연( ReadTimeout ) 재시도
    status=4,               # 5xx/429 등 재시도
    backoff_factor=0.8,     # 0.8, 1.6, 3.2, 6.4s ...
    status_forcelist=(408, 429, 500, 502, 503, 504),
    allowed_methods=("GET", "HEAD"),
    respect_retry_after_header=True,
    raise_on_status=False,
)
_adapter = HTTPAdapter(max_retries=_retries)
_session.mount("https://", _adapter)
_session.mount("http://", _adapter)

def http_get(url, timeout=(3, 7)):  # (connect 3초, read 7초)
    headers = {"User-Agent": "ESP-Dashboard/1.0 (+local)"}
    return _session.get(url, headers=headers, timeout=timeout)

# 조회용 base date, base time 설정
def get_base_hourly(now_kst):
    """
    현재 시각이 02시 이전이면 전날 2300 발표본을 사용.
    그 외에는 당일 0200 발표본 사용.
    """
    if now_kst.hour < 2:
        base_date = (now_kst - timedelta(days=1)).strftime("%Y%m%d")
        base_time = "2300"
    else:
        base_date = now_kst.strftime("%Y%m%d")
        base_time = "0200"

    return base_date, base_time


## hourly용 데이터 파싱
# 동네예보 - 단기예보
def fetch_vilage_json(base_date_hourly, base_time_hourly):
    """단기 예보 json data 가져오기"""
    url = (
        "https://apihub.kma.go.kr/api/typ02/openApi/VilageFcstInfoService_2.0/getVilageFcst"
        f"?pageNo=1"
        f"&numOfRows=2500"
        f"&dataType=JSON"
        f"&base_date={base_date_hourly}"
        f"&base_time={base_time_hourly}"
        f"&nx={NX}"
        f"&ny={NY}"
        f"&authKey={AUTH_KEY}"
    )
    res = http_get(url, timeout=(5, 15))
    res.raise_for_status()
    data = res.json()

    return data["response"]["body"]["items"]["item"]

# 동네예보 - 단기예보 -> tmp, pop, sky, pty
def build_hourly_data(items, now_kst, hours_ahead=16):
    """now_kst(YYYYMMDDHHMM)부터 최대 hours_ahead개의 시간대에 대해 SKY/PTY/TMP를 모아 반환
       fcst_key = fcstDate + fcstTime (예: '202510261500')
    """
    if not items:
        print("데이터 없음")
        return {}

    # 시각 기준 정렬
    items = sorted(items, key=lambda x: (x["fcstDate"], x["fcstTime"]))

    def key_at(idx):
        return items[idx]["fcstDate"] + items[idx]["fcstTime"]

    total = len(items)
    i = 0
    while i < total and key_at(i) < now_kst:
        i += 1

    if i == total:
        print("no data")
        return {}

    hourly_data = {}  # setdefault 방식 사용

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


## daily용 데이터 파싱
# 동네예보 - 단기예보 -> tmn, tmx
def build_daily_temp_in3day(items, base_time):
    """
    baseTime == base_time 인 TMN/TMX만 날짜별로 한 번씩 저장.
    return 예) {"20251026": {"TMN": 12, "TMX": 22}, ...}
    """
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
        # 하루에 한 번만 저장 (첫 값만 유지)
        if category not in daily_data[date_key]:
            daily_data[date_key][category] = value

    return dict(daily_data)

# 단기예보 - 육상조회 -> sky, pty, st
def build_daily_sky_in3day(base_date):
    base_dt = datetime.strptime(base_date, "%Y%m%d")

    url = (
        "https://apihub.kma.go.kr/api/typ01/url/fct_afs_dl.php?"
        f"reg={REG_ID_C}"
        f"&disp=0"
        f"&authKey={AUTH_KEY}"
    )

    res = http_get(url, timeout=(5, 15))
    res.raise_for_status()

    want_dates = {(base_dt + timedelta(days=i)).strftime("%Y%m%d") for i in range(4)}
    daily_data = {}

    for line in res.text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        cols = line.split(maxsplit=16)
        if len(cols) < 16:
            continue

        TM_EF = cols[2]

        date_key, hhmm = TM_EF[:8], TM_EF[-4:]
        if date_key not in want_dates or hhmm not in ("0000", "1200"):
            continue

        part = "AM" if hhmm == "0000" else "PM"
        st, sky, pty = cols[13], cols[14], cols[15]

        daily_data.setdefault(date_key, {})
        if part not in daily_data[date_key]:  # 하루 한 번만
          daily_data[date_key][part] = {
              "SKY": SKY_MAP.get(sky, sky),  # ✅ 변수명 일치
              "PTY": PTY_MAP.get(pty, pty),
              "ST": clean_st_value(st),
          }

    return daily_data

# daily temp + sky
def merge_daily_temp_sky(daily_temp, daily_sky):
    merged = {}

    # 날짜 기준으로 합치기
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

# 중기예보 - 기온조회 -> tmn, tmx
def build_daily_temp_after3day(base_date):
    """
    중기예보 기온 조회 (5~8일차)
    가장 최근 데이터를 가져오므로 8일차 오후 데이터 유무 확인 필요
    """
    base_dt = datetime.strptime(base_date, "%Y%m%d")
    start_dt = base_dt + timedelta(days=4)  # 5일차부터 시작

    url = (
        "https://apihub.kma.go.kr/api/typ01/url/fct_afs_wc.php?"
        f"reg={REG_ID_C}"
        f"&disp=0"
        f"&authKey={AUTH_KEY}"
    )

    res = http_get(url, timeout=(5, 15))
    res.raise_for_status()

    # 4~8일차 날짜 집합
    want_dates = {(start_dt + timedelta(days=i)).strftime("%Y%m%d") for i in range(4)}
    daily_data = {}

    for line in res.text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        cols = line.split(maxsplit=8)
        if len(cols) < 8:
            continue

        TM_EF = cols[2]  # 발효시각 (YYYYMMDDHHMM)
        date_key = TM_EF[:8]
        if date_key not in want_dates :
            continue

        min_temp, max_temp = cols[6], cols[7]

        daily_data.setdefault(date_key, {})
        daily_data[date_key] = {
            "TMN": min_temp,
            "TMX": max_temp
        }

    return daily_data

# 중기예보 - 육상조회 -> sky, pty, st
def build_daily_sky_after3day(base_date):
    """
    가장 최근 데이터를 가져오므로 8일차 오후 데이터 유무 확인 필요
    """
    
    base_dt = datetime.strptime(base_date, "%Y%m%d")
    start_dt = base_dt + timedelta(days=4)  # 5일차부터 시작

    url = (
        "https://apihub.kma.go.kr/api/typ01/url/fct_afs_wl.php?"
        f"reg={REG_ID_A}"
        f"&disp=0"
        f"&authKey={AUTH_KEY}"
    )

    res = http_get(url, timeout=(5, 15))
    res.raise_for_status()

    want_dates = {(start_dt + timedelta(days=i)).strftime("%Y%m%d") for i in range(4)}
    daily_data = {}

    for line in res.text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        cols = line.split(maxsplit=10)
        if len(cols) < 10:
            continue

        TM_EF = cols[2]

        date_key, hhmm = TM_EF[:8], TM_EF[-4:]
        if date_key not in want_dates or hhmm not in ("0000", "1200"):
            continue

        part = "AM" if hhmm == "0000" else "PM"
        sky, pty, st = cols[6], cols[7], cols[10]

        daily_data.setdefault(date_key, {})
        if part not in daily_data[date_key]:  # 하루 한 번만
          daily_data[date_key][part] = {
              "SKY": SKY_MAP.get(sky, sky),
              "PTY": PTY_MAP.get(pty, pty),
              "ST": clean_st_value(st),
          }

    return daily_data

# hourly & daily & now data 반환
def get_weather_data():
    now_kst = datetime.now(KST)
    base_date, base_time = get_base_hourly(now_kst)

    vilage_data = fetch_vilage_json(base_date, base_time)

    ## hourly
    now_date = now_kst.strftime("%Y%m%d")
    now_hour = now_kst.strftime("%H00")
    hourly_data = build_hourly_data(vilage_data, now_date+now_hour)

    ## daily
    base_date = now_kst.strftime("%Y%m%d")
    # day1 ~ day4
    daily_temp_in3day = build_daily_temp_in3day(vilage_data, base_time)
    daily_sky_in3day = build_daily_sky_in3day(base_date)
    daily_in3day = merge_daily_temp_sky(daily_temp_in3day, daily_sky_in3day)
    # day5 ~ day8
    daily_temp_after3day = build_daily_temp_after3day(base_date)
    daily_sky_after3day = build_daily_sky_after3day(base_date)
    daily_after3day = merge_daily_temp_sky(daily_temp_after3day, daily_sky_after3day)
    # day1 ~ day 8
    daily_data = {**daily_in3day, **daily_after3day}

    ## now
    now_data = {
    "TMP": hourly_data[now_date + now_hour].get("TMP"),
    "SKY": hourly_data[now_date + now_hour].get("SKY"),
    "PTY": hourly_data[now_date + now_hour].get("PTY"),
    "TMX": daily_data.get(now_date, {}).get("TMX"),
    "TMN": daily_data.get(now_date, {}).get("TMN"),
    }

    print(hourly_data, daily_data, now_data)
    return hourly_data, daily_data, now_data