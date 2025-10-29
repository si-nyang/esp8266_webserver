(function () {
  // ===== 상수 =====
  const K_WEEK = ["일", "월", "화", "수", "목", "금", "토"];
  const HOUR_AM = 9;
  const HOUR_PM = 15;

  // ===== 헬퍼 함수 =====
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

  function parseYMD(key) {
    const y = +key.slice(0, 4), m = +key.slice(4, 6) - 1, d = +key.slice(6, 8);
    return new Date(y, m, d);
  }

  function formatDateMMDD(dt) {
    const mm = String(dt.getMonth() + 1).padStart(2, "0");
    const dd = String(dt.getDate()).padStart(2, "0");
    return `${mm}.${dd}.`;
  }

  function labelTodayTomorrow(dt) {
    const now = new Date();
    const a = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    const b = new Date(dt.getFullYear(), dt.getMonth(), dt.getDate());
    const diff = Math.round((b - a) / 86400000);
    if (diff === 0) return "오늘";
    if (diff === 1) return "내일";
    return K_WEEK[dt.getDay()];
  }

  const toPct = (v) => {
    const n = Number.parseInt(v ?? "", 10);
    return Number.isFinite(n) ? n : null;
  };

  const toTemp = (v) => {
    const n = Number.parseInt(v ?? "", 10);
    return Number.isFinite(n) ? n : null;
  };

  function normalizeDaily(input) {
    if (!input) return null;
    if (input.daily && typeof input.daily === "object") return input.daily;
    return input;
  }

  function pickIcon(sky, pty, hourGuess) {
    const fn =
      (typeof window !== "undefined" && typeof window.getIconPath === "function" && window.getIconPath) ||
      (typeof getIconPath === "function" ? getIconPath : null);
    if (fn) return fn(sky, pty, hourGuess);

    const isDay = hourGuess >= 6 && hourGuess < 18;
    const base = `/weathericons/${isDay ? "Weather_day" : "Weather_night"}`;
    const S = (sky || "").trim();
    const P = (pty || "").trim();
    let name = "overcast";
    if (P && P !== "없음") {
      const r = P.includes("비"), s = P.includes("눈");
      name = r && s ? "overcast_rain_and_snow" : s ? "overcast_snow" : "overcast_rain";
      if (S === "구름많음") name = r && s ? "cloudy_rain_and_snow" : s ? "cloudy_snow" : "cloudy_rain";
    } else {
      name = S === "맑음" ? "sunny" : S === "구름많음" ? "cloudy" : "overcast";
    }
    return `${base}/${name}.png`;
  }

  // ===== 메인 함수 =====
  async function buildDays() {
    const root = document.querySelector(".days");
    if (!root) return;

    try {
      let payload;
      try {
        payload = await fetchWithRetry("/api/daily");
      } catch (e) {
        console.warn("fetch /api/daily failed:", e);
        payload = await fetchWithRetry("/api/weather");
      }

      if (payload.error) throw new Error(payload.error);

      const normalized = normalizeDaily(payload.daily ?? payload);
      if (!normalized || typeof normalized !== "object") {
        root.textContent = "일별 예보가 없습니다.";
        return;
      }

      const days = Object.entries(normalized)
        .map(([k, v]) => ({ key: k, dt: parseYMD(k), ...v }))
        .filter((d) => d.dt instanceof Date && !Number.isNaN(d.dt))
        .sort((a, b) => a.dt - b.dt);

      const isStale = !!payload.stale;
      root.innerHTML = "";
      root.classList.toggle("is-stale", isStale);

      if (isStale) {
        const badge = document.createElement("div");
        badge.className = "stale-badge";
        badge.textContent = "최근 데이터 표시 중";
        root.appendChild(badge);
      }

      days.forEach((d, idx) => {
        const title = labelTodayTomorrow(d.dt);
        const dateStr = formatDateMMDD(d.dt);

        const hasAM = d.AM && typeof d.AM === "object";
        const hasPM = d.PM && typeof d.PM === "object";

        const amIcon = hasAM ? pickIcon(d.AM.SKY, d.AM.PTY, HOUR_AM) : null;
        const pmIcon = hasPM ? pickIcon(d.PM.SKY, d.PM.PTY, HOUR_PM) : null;
        const amPop = hasAM ? toPct(d.AM.ST) : null;
        const pmPop = hasPM ? toPct(d.PM.ST) : null;

        const centerHTML = `
          <div class="center-grid" style="margin:0 auto">
            <div class="ap ap--am">${hasAM ? "오전" : "—"}</div>
            <div class="ap ap--pm">${hasPM ? "오후" : "—"}</div>

            <div class="icon icon--am">
              ${hasAM ? `<img src="${amIcon}" alt="오전">` : `<span style="opacity:.4">N/A</span>`}
            </div>
            <div class="icon icon--pm">
              ${hasPM ? `<img src="${pmIcon}" alt="오후">` : `<span style="opacity:.4">N/A</span>`}
            </div>

            <div class="pop pop--am">${amPop === null ? "—%" : `${amPop}%`}</div>
            <div class="pop pop--pm">${pmPop === null ? "—%" : `${pmPop}%`}</div>
          </div>
        `;

        const lo = toTemp(d.TMN);
        const hi = toTemp(d.TMX);

        const article = document.createElement("article");
        article.className = "daycard" + (idx === 0 ? " day--today" : "");
        article.innerHTML = `
          <div class="day-left">
            <div class="day-title">${title}</div>
            <div class="day-sub">${dateStr}</div>
          </div>
          <div class="day-center">${centerHTML}</div>
          <div class="day-right">
            <span class="lo">${lo === null ? "—" : lo}°</span>
            <span class="slash">/</span>
            <span class="hi">${hi === null ? "—" : hi}°</span>
          </div>
        `;
        root.appendChild(article);
      });
    } catch (e) {
      console.error("buildDays error:", e);
      root.innerHTML = `<div style="padding:1rem;text-align:center">일별 예보 로드 실패: ${e.message}</div>`;
    }
  }

  // ===== 실행 =====
  document.addEventListener("DOMContentLoaded", buildDays);
})();
