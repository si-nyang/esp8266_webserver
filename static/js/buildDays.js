// ===== helpers =====
(() => {
const K_WEEK = ["일", "월", "화", "수", "목", "금", "토"];

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

// 값 방어용 유틸
const toPct = (v) => {
  const n = Number.parseInt(v ?? "", 10);
  return Number.isFinite(n) ? n : null; // 없으면 null 반환 → "—%"로 표기
};
const toTemp = (v) => {
  const n = Number.parseInt(v ?? "", 10);
  return Number.isFinite(n) ? n : null; // 없으면 null → "—°"
};

// 서버 응답을 daily 오브젝트로 정규화
function normalizeDaily(input) {
  if (!input) return null;
  if (input.daily && typeof input.daily === "object") return input.daily; // /api/daily, /api/weather 공통
  return input;
}

// 아이콘 안전 Fallback
function pickIconSafe(sky, pty, hourGuess) {
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

// ===== main =====
function buildDaysFromDaily(dailyObj, isStale = false) {
  const root = document.querySelector(".days");
  const normalized = normalizeDaily(dailyObj);
  if (!root || !normalized || typeof normalized !== "object") return;

  const days = Object.entries(normalized)
    .map(([k, v]) => ({ key: k, dt: parseYMD(k), ...v }))
    .filter((d) => d.dt instanceof Date && !Number.isNaN(d.dt))
    .sort((a, b) => a.dt - b.dt);

  root.innerHTML = "";
  root.classList.toggle("is-stale", !!isStale);

  // (옵션) stale 배지
  if (isStale) {
    const badge = document.createElement("div");
    badge.className = "stale-badge";
    badge.textContent = "최근 데이터 표시 중";
    root.appendChild(badge);
  }

  const hourAM = 9;
  const hourPM = 15;

  days.forEach((d, idx) => {
    const title = labelTodayTomorrow(d.dt);
    const dateStr = formatDateMMDD(d.dt);

    const hasAM = d.AM && typeof d.AM === "object";
    const hasPM = d.PM && typeof d.PM === "object";

    // 아이콘 & 강수확률
    const amIcon = hasAM ? pickIconSafe(d.AM.SKY, d.AM.PTY, hourAM) : null;
    const pmIcon = hasPM ? pickIconSafe(d.PM.SKY, d.PM.PTY, hourPM) : null;
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
}

// ===== run =====
document.addEventListener("DOMContentLoaded", async () => {
  // 1) /api/daily 우선
  try {
    const r1 = await fetch("/api/daily", { cache: "no-store" });
    if (r1.ok) {
      const j1 = await r1.json();
      buildDaysFromDaily(j1.daily ?? j1, !!j1.stale);
      return;
    }
  } catch (e) {
    console.warn("fetch /api/daily failed:", e);
  }

  // 2) /api/weather 대체
  try {
    const r2 = await fetch("/api/weather", { cache: "no-store" });
    if (r2.ok) {
      const j2 = await r2.json();
      buildDaysFromDaily(j2.daily ?? j2, !!j2.stale);
    }
  } catch (e) {
    console.error("buildDays error:", e);
  }
});
})();
