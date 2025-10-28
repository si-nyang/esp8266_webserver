(function () {
  // ---- 유틸: 재시도 fetch ----
  async function fetchWithRetry(url, tries = 2) {
    let lastErr;
    for (let i = 0; i < tries; i++) {
      try {
        const res = await fetch(url, { cache: "no-store" });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return await res.json();
      } catch (e) {
        lastErr = e;
        await new Promise((r) => setTimeout(r, 400 * (i + 1)));
      }
    }
    throw lastErr;
  }

  // ---- 유틸: 날짜 포맷 (예: Sunday, 04 Aug, 2025) ----
  function formatHeroDate(d) {
    const weekday = d.toLocaleDateString("en-US", { weekday: "long" });
    const day = String(d.getDate()).padStart(2, "0");
    const mon = d.toLocaleDateString("en-US", { month: "short" });
    const year = d.getFullYear();
    return { weekday, dateText: `${day} ${mon}, ${year}` };
  }

  // ---- 숫자 안전 처리 ----
  const toInt = (v) => {
    const n = Number(v);
    return Number.isFinite(n) ? Math.round(n) : null;
  };

  // ---- 아이콘 경로 (전역 getIconPath 있으면 우선) ----
  function pickIcon(sky, pty, hour) {
    const fn = (window && window.getIconPath) || (typeof getIconPath === "function" ? getIconPath : null);
    if (fn) return fn(sky, pty, hour);

    const isDay = hour >= 6 && hour < 18;
    const baseDir = `/weathericons/${isDay ? "Weather_day" : "Weather_night"}`;
    const S = (sky || "").trim();
    const P = (pty || "").trim();

    let name = "overcast";
    if (P && P !== "없음") {
      const r = P.includes("비"), s = P.includes("눈");
      name =
        r && s ? "overcast_rain_and_snow"
        : s   ? "overcast_snow"
        :       "overcast_rain";
      if (S === "구름많음") {
        name =
          r && s ? "cloudy_rain_and_snow"
          : s   ? "cloudy_snow"
          :       "cloudy_rain";
      }
    } else {
      if (S === "맑음") name = "sunny";
      else if (S === "구름많음") name = "cloudy";
      else name = "overcast";
    }
    return `${baseDir}/${name}.png`;
  }

  async function buildNow() {
    // 엘리먼트
    const weekdayEl = document.querySelector(".date-block .weekday");
    const dateEl = document.querySelector(".date-block .date");
    const iconEl = document.getElementById("hero-icon");

    const tempNowEl = document.querySelector(".weather-block .temp-now .value");
    const nowLabelEl = document.querySelector(".weather-block .temp-now .label");
    const tMaxEl = document.querySelector(".weather-block .temp-highlow .high");
    const tMinEl = document.querySelector(".weather-block .temp-highlow .low");
    const staleBadgeEl = document.querySelector(".weather-block .stale-badge"); // 선택 요소

    // 필수 요소 확인
    if (!weekdayEl || !dateEl || !iconEl || !tempNowEl || !tMaxEl || !tMinEl) return;

    // 날짜 표시
    const nowLocal = new Date();
    const { weekday, dateText } = formatHeroDate(nowLocal);
    weekdayEl.textContent = weekday;
    dateEl.textContent = dateText;

    try {
      const data = await fetchWithRetry("/api/weather");
      if (data.error) throw new Error(data.error);

      // stale 뱃지 처리(선택)
      if (staleBadgeEl) staleBadgeEl.style.display = data.stale ? "" : "none";

      const now = data.now || {};

      // 현재 온도
      const tNow = toInt(now.TMP);
      tempNowEl.textContent = tNow !== null ? `${tNow}°` : "--";
      if (nowLabelEl) nowLabelEl.textContent = "NOW";

      // 최고/최저: now.TMX/TMN 우선, 없으면 daily[오늘] 탐색
      let tmx = toInt(now.TMX);
      let tmn = toInt(now.TMN);

      if ((tmx === null || tmn === null) && data.daily && typeof data.daily === "object") {
        const y = nowLocal.getFullYear();
        const m = String(nowLocal.getMonth() + 1).padStart(2, "0");
        const d = String(nowLocal.getDate()).padStart(2, "0");
        const key = `${y}${m}${d}`;
        const today = data.daily[key];
        if (today) {
          if (tmx === null) tmx = toInt(today.TMX);
          if (tmn === null) tmn = toInt(today.TMN);
        }
      }
      tMaxEl.textContent = tmx !== null ? `${tmx}°` : "--";
      tMinEl.textContent = tmn !== null ? `${tmn}°` : "--";

      // 아이콘
      const hour = nowLocal.getHours();
      iconEl.src = pickIcon(now.SKY, now.PTY, hour);
    } catch (e) {
      console.warn("buildNow error:", e);
      // 실패해도 초기 마크업 유지, 단 텍스트만 기본값으로
      if (nowLabelEl) nowLabelEl.textContent = "NOW";
      tempNowEl.textContent = "--";
      tMaxEl.textContent = "--";
      tMinEl.textContent = "--";
    }
  }

  document.addEventListener("DOMContentLoaded", buildNow);
  // 필요 시 주기적 업데이트
  // setInterval(buildNow, 60_000);
})();
