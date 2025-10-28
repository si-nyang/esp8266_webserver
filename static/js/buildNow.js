(function () {
  // ---- 유틸: 재시도 fetch ----
  async function fetchWithRetry(url, tries = 2) {
    let lastErr;
    for (let i = 0; i < tries; i++) {
      try {
        const res = await fetch(url, { cache: "no-cache" });
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

  async function buildNow() {
    // 엘리먼트 참조
    const weekdayEl = document.querySelector(".date-block .weekday");
    const dateEl = document.querySelector(".date-block .date");
    const iconEl = document.getElementById("hero-icon");

    const tempNowEl = document.querySelector(".weather-block .temp-now .value");
    const nowLabelEl = document.querySelector(
      ".weather-block .temp-now .label"
    );
    const tMaxEl = document.querySelector(".weather-block .temp-highlow .high");
    const tMinEl = document.querySelector(".weather-block .temp-highlow .low");

    if (!weekdayEl || !dateEl || !iconEl || !tempNowEl || !tMaxEl || !tMinEl) {
      // 필수 요소 없으면 중단
      return;
    }

    // 날짜 표시
    const nowLocal = new Date();
    const { weekday, dateText } = formatHeroDate(nowLocal);
    weekdayEl.textContent = weekday;
    dateEl.textContent = dateText;

    try {
      const data = await fetchWithRetry("/api/weather");
      if (data.error) throw new Error(data.error);

      const now = data.now || {};

      // 현재 온도
      const tNow = toInt(now.TMP);
      if (tNow !== null) tempNowEl.textContent = `${tNow}°`;
      if (nowLabelEl) nowLabelEl.textContent = "NOW";

      // 최고/최저: 우선 now.TMX/TMN 사용, 없으면 daily[오늘] 참조
      let tmx = toInt(now.TMX);
      let tmn = toInt(now.TMN);

      if ((tmx === null || tmn === null) && data.daily) {
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
      if (tmx !== null) tMaxEl.textContent = `${tmx}°`;
      if (tmn !== null) tMinEl.textContent = `${tmn}°`;

      // 아이콘: 전역 getIconPath(sky, pty, hour) 있으면 사용
      const hour = nowLocal.getHours();
      let iconSrc = "";
      if (typeof getIconPath === "function") {
        iconSrc = getIconPath(now.SKY, now.PTY, hour);
      } else {
        // 폴백(매핑 최소)
        const isDay = hour >= 6 && hour < 18;
        const baseDir = `/weathericons/${
          isDay ? "Weather_day" : "Weather_night"
        }`;
        const S = (now.SKY || "").trim();
        const P = (now.PTY || "").trim();
        let name = "overcast";
        if (P && P !== "없음") {
          const r = P.includes("비"),
            s = P.includes("눈");
          name =
            r && s
              ? "overcast_rain_and_snow"
              : s
              ? "overcast_snow"
              : "overcast_rain";
          if (S === "구름많음") {
            name =
              r && s
                ? "cloudy_rain_and_snow"
                : s
                ? "cloudy_snow"
                : "cloudy_rain";
          }
        } else {
          if (S === "맑음") name = "sunny";
          else if (S === "구름많음") name = "cloudy";
        }
        iconSrc = `${baseDir}/${name}.png`;
      }
      iconEl.src = iconSrc;
    } catch (e) {
      // 실패해도 초기 마크업은 유지
      console.warn("buildNow error:", e);
    }
  }

  document.addEventListener("DOMContentLoaded", buildNow);
  // 필요하면 주기적 업데이트
  // setInterval(buildNow, 60_000);
})();
