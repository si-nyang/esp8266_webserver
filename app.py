import json
import time
import threading
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests
from flask import Flask, jsonify, render_template, send_from_directory, request
from requests.auth import HTTPBasicAuth

from src.get_weather import get_weather_data  # ← (hourly, daily, now) 튜플 반환
from src.get_ai_summary import generate_ai_summary  # (신규)

app = Flask(__name__)
KST = ZoneInfo("Asia/Seoul")

# ─────────────────────────────────────────────────────────────
# ESP 설정
# ─────────────────────────────────────────────────────────────
# ESP_IP = '172.20.10.3'  # 핫스팟일 경우
ESP_IP = '125.189.93.101:80'  # 라우터 공인 IP + 포트
account = 'admin'
password = 'esp12f'

# ─────────────────────────────────────────────────────────────
# Weather 캐시 (엔드포인트별 TTL + 프리패치)
# ─────────────────────────────────────────────────────────────
# hourly/daily는 단기예보 기반(0200/2300 발표), now는 hourly/daily 조합
# 한 번의 get_weather_data() 호출로 모두 갱신함.
WEATHER_CACHE = {
    "now": {
        "t": 0.0,
        "value": {}
    },
    "hourly": {
        "t": 0.0,
        "value": []
    },
    "daily": {
        "t": 0.0,
        "value": {}
    },
}
# TTL 설정:
# - hourly/daily: 12시간 (0200 → 2300 또는 2300 → 0200 간격 11~13시간)
# - now: 1시간 (hourly/daily 기반으로 최신 상태 유지)
TTL_NOW_SEC = 1 * 3600
TTL_HOURLY_SEC = 12 * 3600
TTL_DAILY_SEC = 12 * 3600

_last_good_weather = None  # 마지막 정상 응답(전체 페이로드) 저장


def _set_weather_cache(hourly, daily, now):
    ts = time.time()
    WEATHER_CACHE["hourly"] = {"t": ts, "value": hourly}
    WEATHER_CACHE["daily"] = {"t": ts, "value": daily}
    WEATHER_CACHE["now"] = {"t": ts, "value": now}


def _update_now_cache(now):
    """now만 업데이트 (hourly/daily 기반 재계산 시 사용)"""
    WEATHER_CACHE["now"] = {"t": time.time(), "value": now}


def _weather_stale(key: str, ttl: int) -> bool:
    entry = WEATHER_CACHE.get(key)
    if not entry or entry["t"] == 0:
        return True
    return (time.time() - entry["t"]) > ttl


def refresh_weather_all():
    """한 번의 호출로 (hourly, daily, now) 업데이트. 실패 시 예외 throw."""
    hourly, daily, now = get_weather_data()
    _set_weather_cache(hourly, daily, now)
    # _last_good_weather 업데이트는 라우트에서 만들 때 같이 반영


def _recalc_now_from_cache():
    """
    캐시된 hourly/daily에서 now를 재계산 (API 호출 없이)
    hourly/daily가 없으면 예외 발생
    """
    from src.get_weather import pick_best_hour_key
    from datetime import datetime
    from zoneinfo import ZoneInfo
    
    hourly_data = WEATHER_CACHE["hourly"]["value"]
    daily_data = WEATHER_CACHE["daily"]["value"]
    
    if not hourly_data or not daily_data:
        raise ValueError("hourly or daily cache empty")
    
    now_kst = datetime.now(ZoneInfo("Asia/Seoul"))
    now_date = now_kst.strftime("%Y%m%d")
    now_hour = now_kst.strftime("%H00")
    preferred_key = now_date + now_hour
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
    
    now_obj["TMX"] = daily_data.get(now_date, {}).get("TMX")
    now_obj["TMN"] = daily_data.get(now_date, {}).get("TMN")
    
    _update_now_cache(now_obj)
    return now_obj


# ─────────────────────────────────────────────────────────────
# 프리패치 스케줄러 (5회/일)
# 단기예보 (hourly + daily-3d): 0200/2300 발표
# - 02:10 → 0200 발표본
# - 12:10 → 0200 유지 (점심 시간대 갱신)
# - 23:10 → 2300 발표본
# 중기예보 (daily-4d~): 0600/1800 발표
# - 06:10 → 0600 발표본
# - 18:10 → 1800 발표본
# ─────────────────────────────────────────────────────────────
_PREFETCH_SLOTS = [2, 6, 12, 18, 23]
_PREFETCH_MINUTE = 10  # 발표 후 10분 여유


def _seconds_until_next_shortterm():
    now = datetime.now(KST)
    today_targets = [
        now.replace(hour=h, minute=_PREFETCH_MINUTE, second=0, microsecond=0)
        for h in _PREFETCH_SLOTS
    ]
    future = [t for t in today_targets if t > now]
    nxt = future[0] if future else today_targets[0] + timedelta(days=1)
    return max(1, int((nxt - now).total_seconds()))


def _prefetch_loop():
    """서버가 알아서 단기 주기에 맞춰 프리패치"""
    while True:
        try:
            refresh_weather_all()
            print("[prefetch] weather updated at", datetime.now(KST))
        except Exception as e:
            print("[prefetch] weather update failed:", e)
        time.sleep(_seconds_until_next_shortterm())


def start_prefetch_daemon():
    t = threading.Thread(target=_prefetch_loop, daemon=True)
    t.start()


# ─────────────────────────────────────────────────────────────
# AI Summary 캐시 (TTL + 값 서명) — 그대로 유지
# ─────────────────────────────────────────────────────────────
AI_CACHE_TTL_SECONDS = 300  # 5분
_ai_summary_cache = {
    "key": None,  # hour_key|snapshot_sig
    "at": 0.0,
    "data": None
}


def _snapshot_sig(snap: dict) -> str:

    def _num(v, nd=1):
        try:
            return round(float(v), nd)
        except Exception:
            return v

    core = {
        "t": _num(snap.get("Temperature"), 1),
        "h": _num(snap.get("Humidity"), 0),
        "p25": _num(snap.get("PM2_5"), 0),
        "p10": _num(snap.get("PM10"), 0),
        "g1": _num(snap.get("GammaAverage1m"), 2),
        "g10": _num(snap.get("GammaAverage10m"), 2),
    }
    return json.dumps(core, sort_keys=True)


# ─────────────────────────────────────────────────────────────
# ESP 프록시 helper (타임아웃/에러 처리 보강)
# ─────────────────────────────────────────────────────────────
def _esp_get(path: str, timeout=(2, 3)):
    url = f"http://{ESP_IP}{path}"
    return requests.get(url,
                        auth=HTTPBasicAuth(account, password),
                        timeout=timeout)


# ─────────────────────────────────────────────────────────────
# Global after_request (브라우저 캐시 금지)
# ─────────────────────────────────────────────────────────────
@app.after_request
def no_store(resp):
    resp.headers["Cache-Control"] = "no-store, max-age=0"
    return resp


# ─────────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────────
@app.route("/")
def home():
    """최초 렌더링 시 ESP에서 snapshot 받아 index.html 렌더"""
    try:
        r = _esp_get("/snapshot")
        r.raise_for_status()
        data = r.json()
    except Exception:
        data = {
            "Temperature": "--",
            "Humidity": "--",
            "PM2_5": "--",
            "PM10": "--",
            "GammaAverage1m": "--",
            "GammaAverage10m": "--"
        }
    return render_template("index.html", snapshot=data)


@app.route('/snapshot', methods=['GET'])
def getSnapshotHandler():
    """브라우저에서 호출하는 프록시: ESP의 /snapshot 중계"""
    try:
        r = _esp_get("/snapshot")
        r.raise_for_status()
        return jsonify(r.json()), 200
    except Exception:
        return jsonify({"error": "esp_unreachable"}), 502


@app.route("/api/weather")
def api_weather():
    """
    (hourly, daily, now) 묶음 반환.
    - hourly/daily가 stale이면 API 호출
    - now만 stale이면 hourly/daily에서 재계산 (API 호출 없음)
    - 강제 리프레시: ?force=1
    """
    global _last_good_weather
    force = request.args.get("force") == "1"

    if force:
        # 강제 새로고침 (API 호출)
        try:
            refresh_weather_all()
        except Exception:
            pass
    else:
        # hourly 또는 daily가 stale이면 API 호출
        if (_weather_stale("hourly", TTL_HOURLY_SEC)
                or _weather_stale("daily", TTL_DAILY_SEC)):
            try:
                refresh_weather_all()
            except Exception as e:
                # 실패 시 마지막 정상값이 있으면 stale로 반환
                if _last_good_weather:
                    payload = {
                        **_last_good_weather, "stale": True,
                        "error": "upstream_timeout"
                    }
                    return jsonify(payload), 200
                return jsonify({"error": "upstream_timeout"}), 502
        # now만 stale이면 캐시에서 재계산 (API 호출 없음)
        elif _weather_stale("now", TTL_NOW_SEC):
            try:
                _recalc_now_from_cache()
            except Exception:
                # 재계산 실패 시 현재 캐시 그대로 사용
                pass

    payload = {
        "now": WEATHER_CACHE["now"]["value"],
        "hourly": WEATHER_CACHE["hourly"]["value"],
        "daily": WEATHER_CACHE["daily"]["value"],
        "stale": False
    }
    _last_good_weather = payload
    return jsonify(payload), 200


@app.route("/api/daily", strict_slashes=False)
def api_daily():
    """
    일별 예보만 반환.
    - TTL 초과 시 동기 갱신 시도; 실패 시 마지막 정상 daily로 stale 반환.
    - 강제 리프레시: ?force=1
    """
    global _last_good_weather
    force = request.args.get("force") == "1"

    if force or _weather_stale("daily", TTL_DAILY_SEC):
        try:
            refresh_weather_all()
        except Exception:
            pass

    if _weather_stale("daily", TTL_DAILY_SEC):
        if _last_good_weather and "daily" in _last_good_weather:
            return jsonify({
                "daily": _last_good_weather.get("daily", {}),
                "stale": True,
                "error": "upstream_timeout"
            }), 200
        return jsonify({"error": "upstream_timeout"}), 502

    payload = {"daily": WEATHER_CACHE["daily"]["value"], "stale": False}
    # _last_good_weather도 동기화
    if _last_good_weather:
        _last_good_weather["daily"] = payload["daily"]
        _last_good_weather["stale"] = False
    return jsonify(payload), 200


@app.route("/weathericons/<path:filename>")
def serve_icon(filename):
    """정적 아이콘 라우터"""
    return send_from_directory('static/Image/', filename)


@app.route("/ai-summary", methods=["GET"])
def ai_summary_route():
    force = request.args.get("force") == "1"

    # 최신 스냅샷
    try:
        r = _esp_get("/snapshot")
        r.raise_for_status()
        snapshot = r.json()
    except Exception:
        snapshot = {}

    # 날씨(캐시에서 가져오거나 필요시 동기 갱신)
    try:
        # hourly 또는 daily가 stale이면 API 호출
        if (_weather_stale("hourly", TTL_HOURLY_SEC)
                or _weather_stale("daily", TTL_DAILY_SEC)):
            refresh_weather_all()
        # now만 stale이면 캐시에서 재계산 (API 호출 없음)
        elif _weather_stale("now", TTL_NOW_SEC):
            try:
                _recalc_now_from_cache()
            except Exception:
                pass
        weather = {
            "now": WEATHER_CACHE["now"]["value"],
            "hourly": WEATHER_CACHE["hourly"]["value"],
            "daily": WEATHER_CACHE["daily"]["value"],
        }
    except Exception:
        weather = {"now": {}, "hourly": [], "daily": {}}

    # AI 요약 캐시 키
    hour_key = datetime.now(KST).strftime("%Y%m%d%H")
    snap_key = _snapshot_sig(snapshot)
    cache_key = f"{hour_key}|{snap_key}"
    now_ts = time.time()

    if (not force and _ai_summary_cache["key"] == cache_key
            and (now_ts - _ai_summary_cache["at"]) <= AI_CACHE_TTL_SECONDS
            and _ai_summary_cache["data"] is not None):
        return jsonify(_ai_summary_cache["data"]), 200

    loc = "서울시 마포구"
    result = generate_ai_summary(snapshot, weather, loc)

    _ai_summary_cache.update({"key": cache_key, "at": now_ts, "data": result})
    return jsonify(result), 200


# 디버깅용 (선택)
@app.route("/__routes")
def __routes():
    return jsonify(sorted([str(r) for r in app.url_map.iter_rules()]))


@app.route("/api/ping")
def api_ping():
    return jsonify({
        "ok": True,
        "now": datetime.now(KST).isoformat(timespec="seconds")
    })


# ─────────────────────────────────────────────────────────────
# 실행 포인트
# ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    # 서버 부팅 시 1회 즉시 채움 + 프리패치 데몬 시작
    try:
        refresh_weather_all()
    except Exception as e:
        print("[boot] initial weather fetch failed:", e)
    start_prefetch_daemon()

    app.run(host="0.0.0.0", port=5000, debug=True)
