from typing import Dict, Any, Optional
from datetime import datetime, timezone, timedelta
from openai import OpenAI
import os
from dotenv import load_dotenv

load_dotenv()
_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

_KST = timezone(timedelta(hours=9))


def _fmt_val(v):
    return "미측정" if v in (None, "", "--") else v


def _today_key_kst() -> str:
    return datetime.now(_KST).strftime("%Y%m%d")


def _pick_pop_from_daily(daily: Dict[str, Any]) -> Optional[str]:
    key = _today_key_kst()
    day = daily.get(key) or {}
    hour = datetime.now(_KST).hour
    slot = "AM" if hour < 12 else "PM"
    pop = ((day.get(slot) or {}).get("ST"))
    if pop in (None, "", "--"):
        pop = ((day.get("AM") or {}).get("ST")) or ((day.get("PM")
                                                     or {}).get("ST"))
    return pop


def _build_prompt(snapshot: Dict[str, Any], weather: Dict[str, Any],
                  loc: str) -> str:
    temp = _fmt_val(snapshot.get("Temperature"))
    humid = _fmt_val(snapshot.get("Humidity"))
    pm25 = _fmt_val(snapshot.get("PM2_5"))
    pm10 = _fmt_val(snapshot.get("PM10"))
    gamma1m = _fmt_val(snapshot.get("GammaAverage1m"))
    gamma10m = _fmt_val(snapshot.get("GammaAverage10m"))

    now_wx = weather.get("now") or {}
    sky_now = _fmt_val(now_wx.get("SKY") or now_wx.get("desc"))
    tmx = _fmt_val(now_wx.get("TMX") or now_wx.get("tmx"))
    tmn = _fmt_val(now_wx.get("TMN") or now_wx.get("tmn"))
    daily_wx = weather.get("daily") or {}
    pop = _fmt_val(_pick_pop_from_daily(daily_wx))

    # ⚠️ 위치 소개 문장 삭제(바이어스 제거). 데이터만 제공.
    return ("다음 데이터로 설명문을 작성하세요.\n"
            f"[실내] 온도 {temp}℃, 습도 {humid}%, 미세먼지 {pm25}/{pm10} µg/m³, "
            f"방사선 {gamma1m}/{gamma10m} µSv/h\n"
            f"[외부:{loc}] 하늘상태 {sky_now}, 최고 {tmx}℃, 최저 {tmn}℃, 강수확률 {pop}%\n\n"
            "요청:\n"
            "- 한국어 자연스러운 설명문 2~6문장, 각 문장은 줄바꿈(\\n)으로 구분.\n"
            "- 날씨, 건강, 옷차림, 공기질, 생활 조언 등을 자유롭게 포함해도 좋습니다.\n"
            "- 과장/이모지/불필요한 수식 없이 사실적이고 친절한 어조.\n"
            "- JSON/코드블록/따옴표 없이 순수 텍스트만 출력.")


def generate_ai_summary(snapshot: Dict[str, Any],
                        weather: Dict[str, Any],
                        loc: str = "서울시 마포구") -> str:
    system = ("너는 IoT 실내환경 대시보드의 설명문을 작성하는 한국어 도우미야. "
              "제공된 데이터를 근거로 최대 6문장 이내의 자연스러운 텍스트를 작성해야 한다.")
    user = _build_prompt(snapshot, weather, loc)

    try:
        resp = _client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{
                "role": "system",
                "content": system
            }, {
                "role": "user",
                "content": user
            }],
            temperature=0.5,  # 살짝 높여 다양성 확보
        )
        return (resp.choices[0].message.content or "").strip()
    except Exception as e:
        return f"요약 생성 중 오류가 발생했습니다: {e}"
