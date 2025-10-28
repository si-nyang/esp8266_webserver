

# src/get_ai_summary.py
from typing import Dict, Any, Optional
from datetime import datetime, timezone, timedelta
from openai import OpenAI
import json, re, os

from dotenv import load_dotenv
load_dotenv()

# ─────────────────────────────────────────────────────────────
# OpenAI 클라이언트
# ─────────────────────────────────────────────────────────────
_client = OpenAI(api_key = os.getenv("OPENAI_API_KEY"))

# ─────────────────────────────────────────────────────────────
# 유틸
# ─────────────────────────────────────────────────────────────
def _fmt_val(v):
    """빈 값이면 '미측정'으로 통일"""
    return "미측정" if v in (None, "", "--") else v

# 한국 표준시
_KST = timezone(timedelta(hours=9))

def _today_key_kst() -> str:
    """KST 기준 YYYYMMDD 키 생성"""
    return datetime.now(_KST).strftime("%Y%m%d")

def _pick_pop_from_daily(daily: Dict[str, Any]) -> Optional[str]:
    """
    daily[YYYYMMDD]['AM' or 'PM']['ST']에서 오늘의 ST(강수/강설 확률 유사)를 선택
    현재 시간 <12면 AM, >=12면 PM 우선. 없으면 AM→PM 순으로 백업.
    """
    key = _today_key_kst()
    day = daily.get(key) or {}
    hour = datetime.now(_KST).hour
    slot = "AM" if hour < 12 else "PM"

    pop = ((day.get(slot) or {}).get("ST"))
    if pop in (None, "", "--"):
        pop = ((day.get("AM") or {}).get("ST")) or ((day.get("PM") or {}).get("ST"))
    return pop

def _safe_json_extract(s: str) -> Optional[dict]:
    """
    모델이 앞뒤로 텍스트를 덧붙여도 중괄호 블록만 뽑아 파싱.
    """
    try:
        # 1) 그대로 시도
        return json.loads(s)
    except Exception:
        pass
    try:
        # 2) 첫 JSON 객체만 추출
        m = re.search(r"\{.*\}", s, re.DOTALL)
        if m:
            return json.loads(m.group(0))
    except Exception:
        return None

def _validate_payload(d: dict) -> Optional[dict]:
    """
    {"summary": str, "tips":[{"category":"indoor","text":...},{"category":"outdoor","text":...}]}
    형식 확인 및 최소 보정
    """
    if not isinstance(d, dict):
        return None
    summary = d.get("summary")
    tips = d.get("tips")
    if not isinstance(summary, str):
        return None
    if not isinstance(tips, list):
        return None

    # 두 개로 제한/보정
    fixed = []
    for t in tips:
        if not isinstance(t, dict):
            continue
        cat = t.get("category")
        txt = t.get("text")
        if cat in ("indoor", "outdoor") and isinstance(txt, str) and txt.strip():
            fixed.append({"category": cat, "text": txt.strip()})
        if len(fixed) == 2:
            break

    if len(fixed) < 2:
        # 부족하면 채워넣기
        if not any(t.get("category") == "indoor" for t in fixed):
            fixed.append({"category": "indoor", "text": "실내 온·습도를 편안 범위로 유지해 보세요. (환기/가습/제습)"})
        if not any(t.get("category") == "outdoor" for t in fixed):
            fixed.append({"category": "outdoor", "text": "일교차와 강수 예보를 확인해 얇은 겉옷과 우산을 준비하세요."})
        fixed = fixed[:2]

    return {"summary": summary.strip(), "tips": fixed}

# ─────────────────────────────────────────────────────────────
# Prompt 빌더
# ─────────────────────────────────────────────────────────────
def _build_user_text(snapshot: Dict[str, Any], weather: Dict[str, Any], loc: str) -> str:
    temp      = _fmt_val(snapshot.get("Temperature"))
    humid     = _fmt_val(snapshot.get("Humidity"))
    pm25      = _fmt_val(snapshot.get("PM2_5"))
    pm10      = _fmt_val(snapshot.get("PM10"))
    gamma1m   = _fmt_val(snapshot.get("GammaAverage1m"))
    gamma10m  = _fmt_val(snapshot.get("GammaAverage10m"))

    now_wx = weather.get("now") or {}
    sky_now = _fmt_val(now_wx.get("SKY") or now_wx.get("desc"))
    tmx = _fmt_val(now_wx.get("TMX") or now_wx.get("tmx"))
    tmn = _fmt_val(now_wx.get("TMN") or now_wx.get("tmn"))

    daily_wx = weather.get("daily") or {}
    pop = _fmt_val(_pick_pop_from_daily(daily_wx))  # ✅ 오늘 AM/PM의 ST 선택

    # (옵션) now에 TMX/TMN이 비어있으면 daily에서 보정
    # today_key = _today_key_kst()
    # if tmx == "미측정":
    #     tmx = _fmt_val((daily_wx.get(today_key) or {}).get("TMX"))
    # if tmn == "미측정":
    #     tmn = _fmt_val((daily_wx.get(today_key) or {}).get("TMN"))

    return (
        f"[위치] {loc}\n"
        f"[실내] 온도 {temp}℃, 습도 {humid}%, PM2.5 {pm25} µg/m³, PM10 {pm10} µg/m³, "
        f"방사선 1m {gamma1m} µSv/h, 10m {gamma10m} µSv/h\n"
        f"[외부] 하늘상태 {sky_now}, 최고 {tmx}℃, 최저 {tmn}℃, 강수확률 {pop}%\n"
        "요청: 아래 JSON 스키마만 출력하라.\n"
        '{\n'
        '  "summary": "<한국어 120자 내 요약 1개>",\n'
        '  "tips": [\n'
        '    {"category":"indoor","text":"<실내 조언 1개>"},\n'
        '    {"category":"outdoor","text":"<외출/복장 조언 1개>"}\n'
        '  ]\n'
        '}\n'
        "규칙: 불필요한 문장/코드블록/설명/백틱 없이 JSON만 출력. 데이터가 '미측정'인 항목은 언급하지 말 것. 과장 금지, 이모지 ≤ 1개."
    )

# ─────────────────────────────────────────────────────────────
# 메인 진입 함수 (chat.completions 기반)
# ─────────────────────────────────────────────────────────────
def generate_ai_summary(snapshot: Dict[str, Any], weather: Dict[str, Any], loc: str = "서울") -> Dict[str, Any]:
    """
    snapshot + weather를 바탕으로
    {"summary": str, "tips":[{"category":"indoor","text":...},{"category":"outdoor","text":...}]} 반환
    (chat.completions 사용, 모델이 JSON만 출력하도록 강제 + 안전 파싱)
    """
    system = (
        "너는 IoT 실내환경 대시보드용 코멘트를 생성하는 도우미다. "
        "반드시 사용자가 요구한 JSON 형식만 출력한다."
    )
    user_text = _build_user_text(snapshot, weather, loc)

    fallback = {
        "summary": "데이터를 바탕으로 간단 요약을 준비 중이에요. 잠시 후 다시 시도해 주세요.",
        "tips": [
            {"category": "indoor",  "text": "실내 온·습도를 편안 범위로 유지해 보세요. (가벼운 환기/가습/제습)"},
            {"category": "outdoor", "text": "일교차와 강수 예보를 확인해 얇은 겉옷과 우산을 준비하세요."}
        ]
    }

    try:
        resp = _client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_text}
            ],
            temperature=0.3,
        )
        text = (resp.choices[0].message.content or "").strip()

        data = _safe_json_extract(text)
        data = _validate_payload(data) if data else None
        return data or fallback

    except Exception:
        return fallback
