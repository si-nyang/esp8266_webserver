import json
import time
import requests
from functools import lru_cache
from datetime import datetime
from flask import Flask, jsonify, render_template, send_from_directory, request
from requests.auth import HTTPBasicAuth

from src.get_weather import get_weather_data  # ← 분리된 모듈
from src.get_ai_summary import generate_ai_summary  # (신규)

app = Flask(__name__)

# ─────────────────────────────────────────────────────────────
# ESP 설정
# ─────────────────────────────────────────────────────────────
# ESP_IP = '172.20.10.3'  # 핫스팟일 경우
ESP_IP = '125.189.93.101:80'  # 라우터 공인 IP + 포트
account = 'admin'
password = 'esp12f'

# ─────────────────────────────────────────────────────────────
# Weather 캐시 (1시간 키)
# ─────────────────────────────────────────────────────────────
_last_good_weather = None  # 마지막 정상 응답 저장용


@lru_cache(maxsize=1)
def _cached_weather(hour_key: str):
    """
    hour_key는 캐시 키(YYYYMMDDHH)로만 사용.
    get_weather_data()는 (hourly, daily, now) 튜플을 반환해야 함.
    """
    return get_weather_data()


# ─────────────────────────────────────────────────────────────
# AI Summary 캐시 (TTL + 값 서명)
# ─────────────────────────────────────────────────────────────
AI_CACHE_TTL_SECONDS = 300  # 5분
_ai_summary_cache = {
    "key": None,  # hour_key|snapshot_sig
    "at": 0.0,
    "data": None
}


def _snapshot_sig(snap: dict) -> str:
    """스냅샷 핵심 수치만 뽑아 서명 생성."""

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
    """(connect, read) 타임아웃으로 ESP에 안전하게 요청"""
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
    기상청 API → (hourly, daily, now) 구조 반환.
    내부적으로 1시간 키(lru_cache)로 캐시하고, 실패 시 마지막 정상값 반환.
    강제 리프레시: ?force=1
    """
    global _last_good_weather
    hour_key = datetime.now().strftime("%Y%m%d%H")
    force = request.args.get("force") == "1"

    if force:
        _cached_weather.cache_clear()

    try:
        hourly, daily, now = _cached_weather(hour_key)
        payload = {
            "now": now,
            "hourly": hourly,
            "daily": daily,
            "stale": False
        }
        _last_good_weather = payload
        return jsonify(payload), 200
    except Exception:
        if _last_good_weather:
            return jsonify({
                **_last_good_weather, "stale": True,
                "error": "upstream_timeout"
            }), 200
        return jsonify({"error": "upstream_timeout"}), 502


@app.route("/api/daily", strict_slashes=False)
def api_daily():
    """일별 예보만 반환. 강제 리프레시: ?force=1"""
    global _last_good_weather
    hour_key = datetime.now().strftime("%Y%m%d%H")
    force = request.args.get("force") == "1"

    if force:
        _cached_weather.cache_clear()

    try:
        _, daily, _ = _cached_weather(hour_key)
        payload = {"daily": daily, "stale": False}
        if _last_good_weather:
            _last_good_weather["daily"] = daily
            _last_good_weather["stale"] = False
        return jsonify(payload), 200
    except Exception:
        if _last_good_weather and "daily" in _last_good_weather:
            return jsonify({
                "daily": _last_good_weather.get("daily", {}),
                "stale": True,
                "error": "upstream_timeout"
            }), 200
        return jsonify({"error": "upstream_timeout"}), 502


@app.route('/weathericons/<path:filename>')
def serve_icon(filename):
    """정적 아이콘 라우터"""
    return send_from_directory('static/Image/', filename)


@app.route("/ai-summary", methods=["GET"])
def ai_summary_route():
    force = request.args.get("force") == "1"

    try:
        r = _esp_get("/snapshot")
        r.raise_for_status()
        snapshot = r.json()
    except Exception:
        snapshot = {}

    hour_key = datetime.now().strftime("%Y%m%d%H")
    try:
        hourly, daily, now = _cached_weather(hour_key)
        weather = {"now": now, "hourly": hourly, "daily": daily}
    except Exception:
        weather = {"now": {}, "hourly": [], "daily": {}}

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
        "now": datetime.now().isoformat(timespec="seconds")
    })


# ─────────────────────────────────────────────────────────────
# 실행 포인트
# ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
