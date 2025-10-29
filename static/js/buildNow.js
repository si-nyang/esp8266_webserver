(function () {
  // ─────────────────────────────────────────────────────────
  // 설정: 클라이언트 캐시 TTL (ms). 단기예보 기반이니 10분이면 충분.
  // 서버는 3시간 단위로 프리패치하므로, 여기 값은 UI 빈도만 조절.
  const CLIENT_TTL_MS = 10 * 60 * 1000; // 10분

  // ── 내부 메모리 캐시 ──────────────────────────────────────
  const _cache = { weather: { at: 0, data: null } };

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
    const customFn =
      (typeof window !== "undefined" && window.getIconPath) ||
      (typeof getIconPath === "function" ? getIconPath : null);
    if (typeof customFn === "function") return customFn(sky, pty, hour);

    const isDay = hour >= 6 && hour < 18;
    const baseDir = `/weathericons/${isDay ? "Weather_day" : "Weather_night"}`;
    const S = (sky || "").trim();
    const P = (pty || "").trim();

    let name = "overcast";
    if (P && P !== "없음") {
      const r = P.includes("비"),
        s = P.includes("눈");
      name =
        r && s ? "overcast_rain_and_snow" : s ? "overcast_snow" : "overcast_rain";
      if (S === "구름많음") {
        name = r && s ? "cloudy_rain_and_snow" : s ? "cloudy_snow" : "cloudy_rain";
      }
    } else {
      if (S === "맑음") name = "sunny";
      else if (S === "구름많음") name = "cloudy";
      else name = "overcast";
    }
    return `${baseDir}/${name}.png`;
  }

  // ── 클라이언트 캐시되는 /api/weather 가져오기 ────────────
  async function getWeatherCached() {
    const now = Date.now();
    if (_cache.weather.data && now - _cache.weather.at < CLIENT_TTL_MS) {
      return _cache.weather.data;
    }
    const data = await fetchWithRetry("/api/weather");
    _cache.weather = { at: now, data };
    return data;
  }

  // ── UI 빌드: NOW 블럭 ────────────────────────────────────
  async function buildNow() {
    // 엘리먼트
    const weekdayEl = document.querySelector(".date-block .weekday");
    const dateEl = document.querySelector(".date-block .date");
    const iconEl = document.getElementById("hero-icon");

    const tempNowEl = document.querySelector(".weather-block .temp-now .value");
    const nowLabelEl = document.querySelector(".weather-block .temp-now .label");
    const tMaxEl = document.querySelector(".weather-block .temp-highlow .high");
    const tMinEl = document.querySelector(".weather-block .temp-highlow .low");
    const staleBadgeEl = document.querySelector(".weather-block .stale-badge"); // 선택
    const lastUpdatedEl = document.querySelector(".last-updated"); // 선택
    const weatherBlock = document.querySelector(".weather-block");

    // 필수 요소 확인
    if (!weekdayEl || !dateEl || !iconEl || !tempNowEl || !tMaxEl || !tMinEl) return;

    // 날짜 표시
    const nowLocal = new Date();
    const { weekday, dateText } = formatHeroDate(nowLocal);
    weekdayEl.textContent = weekday;
    dateEl.textContent = dateText;

    try {
      const data = await getWeatherCached();
      if (data.error) throw new Error(data.error);

      // stale 뱃지 / 클래스
      const isStale = !!data.stale;
      if (staleBadgeEl) staleBadgeEl.style.display = isStale ? "" : "none";
      if (weatherBlock) {
        weatherBlock.classList.toggle("is-stale", isStale);
      }

      const nowObj = data.now || {};
      // 현재 온도
      const tNow = toInt(nowObj.TMP);
      tempNowEl.textContent = tNow !== null ? `${tNow}°` : "--";
      if (nowLabelEl) nowLabelEl.textContent = "NOW";

      // 최고/최저: now.TMX/TMN 우선, 없으면 daily[오늘] 보강
      let tmx = toInt(nowObj.TMX);
      let tmn = toInt(nowObj.TMN);

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

      // 아이콘 (이미지 에러 시 fallback)
      const hour = nowLocal.getHours();
      const src = pickIcon(nowObj.SKY, nowObj.PTY, hour);
      iconEl.onerror = () => {
        iconEl.onerror = null;
        iconEl.src = `/weathericons/${hour >= 6 && hour < 18 ? "Weather_day" : "Weather_night"}/overcast.png`;
      };
      iconEl.src = src;

      // 마지막 갱신 표기(선택)
      if (lastUpdatedEl) {
        const ts = new Date(_cache.weather.at);
        const hh = String(ts.getHours()).padStart(2, "0");
        const mm = String(ts.getMinutes()).padStart(2, "0");
        lastUpdatedEl.textContent = isStale ? `Stale · ${hh}:${mm}` : `Updated · ${hh}:${mm}`;
      }
    } catch (e) {
      console.warn("buildNow error:", e);
      if (nowLabelEl) nowLabelEl.textContent = "NOW";
      tempNowEl.textContent = "--";
      tMaxEl.textContent = "--";
      tMinEl.textContent = "--";
      if (staleBadgeEl) staleBadgeEl.style.display = "none";
      if (weatherBlock) weatherBlock.classList.remove("is-stale");
    }
  }

  document.addEventListener("DOMContentLoaded", buildNow);

  // 필요 시 주기적 업데이트(클라이언트 TTL과 비슷하게)
  setInterval(buildNow, CLIENT_TTL_MS);
})();
