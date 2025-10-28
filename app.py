import json
import time
import requests
from functools import lru_cache
from datetime import datetime
from flask import Flask, jsonify, render_template, send_from_directory, request
from requests.auth import HTTPBasicAuth

from src.get_weather import get_weather_data  # (기존)
from src.get_ai_summary import generate_ai_summary  # (신규)

app = Flask(__name__)

# ─────────────────────────────────────────────────────────────
# ESP 설정
# ─────────────────────────────────────────────────────────────
ESP_IP = '172.20.10.3'  # ESP에서 출력한 IP와 동일해야 함
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
AI_CACHE_TTL_SECONDS = 300  # 5분 (원하면 120~900 사이로 조절)
_ai_summary_cache = {
    "key": None,  # hour_key|snapshot_sig
    "at": 0.0,
    "data": None
}


def _snapshot_sig(snap: dict) -> str:
    """
    스냅샷 핵심 수치만 뽑아 '서명(signature)' 생성.
    숫자는 반올림해 소수점 미세 변화에 캐시가 깨지지 않도록 함.
    """

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
# Routes
# ─────────────────────────────────────────────────────────────
@app.route("/")
def home():
    """최초 렌더링 시 ESP에서 snapshot을 받아 index.html 렌더"""
    try:
        content = requests.get(f'http://{ESP_IP}/snapshot',
                               auth=HTTPBasicAuth(account, password),
                               timeout=1)
        data = content.json()
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
    """브라우저에서 호출하는 프록시: ESP의 /snapshot을 그대로 중계"""
    content = requests.get(f'http://{ESP_IP}/snapshot',
                           auth=HTTPBasicAuth(account, password),
                           timeout=0.5)
    return content.json()


@app.route("/api/weather")
def api_weather():
    """
    기상청 API → (hourly, daily, now) 구조를 반환.
    내부적으로 1시간 키(lru_cache)로 캐시하고, 실패 시 마지막 정상값 반환.
    """
    global _last_good_weather
    hour_key = datetime.now().strftime("%Y%m%d%H")
    try:
        hourly, daily, now = _cached_weather(hour_key)
        payload = {
            "now": now,
            "hourly": hourly,
            "daily": daily,
            "stale": False
        }
        _last_good_weather = payload
        return jsonify(payload)
    except Exception as e:
        app.logger.exception("weather api failed")
        if _last_good_weather:
            return jsonify({
                **_last_good_weather, "stale": True,
                "error": str(e)
            }), 200
        return jsonify({"error": str(e)}), 500


@app.route('/weathericons/<path:filename>')
def serve_icon(filename):
    """정적 아이콘 라우터(필요 시 경로 맞춰서 사용)"""
    return send_from_directory('static/Image/', filename)


@app.route("/ai-summary", methods=["GET"])
def ai_summary_route():
    force = request.args.get("force") == "1"

    try:
        content = requests.get(f"http://{ESP_IP}/snapshot",
                               auth=HTTPBasicAuth(account, password),
                               timeout=1)
        snapshot = content.json()
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
        return _ai_summary_cache["data"]

    loc = "서울시 마포구"
    result = generate_ai_summary(snapshot, weather, loc)

    _ai_summary_cache.update({"key": cache_key, "at": now_ts, "data": result})
    return result


# ─────────────────────────────────────────────────────────────
# 실행 포인트
# ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
