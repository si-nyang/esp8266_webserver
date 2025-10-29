// ===== helpers =====
(() => {
const K_WEEK = ["일", "월", "화", "수", "목", "금", "토"];

function parseKeyToDate(k) {
  // 'YYYYMMDDHHMM' 기준, HHMM 없으면 0000으로 처리
  const y = +k.slice(0, 4),
    m = +k.slice(4, 6) - 1,
    d = +k.slice(6, 8);
  const H = +(k.slice(8, 10) || "00"),
    M = +(k.slice(10, 12) || "00");
  return new Date(y, m, d, H, M, 0, 0);
}

function normalizeHourly(payload) {
  if (!payload) return {};
  if (payload.hourly && typeof payload.hourly === "object") return payload.hourly;
  return payload;
}

// 레이블: offset=0 → "현재", 날짜 바뀌면 "내일" 또는 요일, 그 외 "HH시"
function makeHourLabel(nowDate, nowHour, offset, targetDt) {
  if (offset === 0) return "현재";
  const isOtherDay =
    targetDt.getFullYear() !== nowDate.getFullYear() ||
    targetDt.getMonth() !== nowDate.getMonth() ||
    targetDt.getDate() !== nowDate.getDate();

  if (isOtherDay) {
    const justDateA = new Date(nowDate.getFullYear(), nowDate.getMonth(), nowDate.getDate());
    const justDateB = new Date(targetDt.getFullYear(), targetDt.getMonth(), targetDt.getDate());
    const diff = Math.round((justDateB - justDateA) / 86400000);
    const lead = diff === 1 ? "내일 " : K_WEEK[targetDt.getDay()] + " ";
    return `${lead}${String(targetDt.getHours()).padStart(2, "0")}시`;
  }
  return `${String(targetDt.getHours()).padStart(2, "0")}시`;
}

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

// 안전 파서
const toCelsius = (v) => {
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
};

// 아이콘 선택 (전역 getIconPath 없을 때 fallback)
function pickIconSafe(sky, pty, hour) {
  const fn =
    (typeof window !== "undefined" && typeof window.getIconPath === "function" && window.getIconPath) ||
    (typeof getIconPath === "function" ? getIconPath : null);
  if (fn) return fn(sky, pty, hour);

  const isDay = hour >= 6 && hour < 18;
  const baseDir = `/weathericons/${isDay ? "Weather_day" : "Weather_night"}`;
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
  return `${baseDir}/${name}.png`;
}

// ===== main =====
(async function buildHourlyFromAPI(limit = 18) {
  const hourlyEl = document.getElementById("hourly");
  if (!hourlyEl) return;

  // limit 방어
  const MAX = 24;
  const count = Math.max(1, Math.min(limit || 18, MAX));

  try {
    const payload = await fetchWithRetry("/api/weather");
    if (payload.error) throw new Error(payload.error);

    const hourly = normalizeHourly(payload) || {};
    const stale = !!payload.stale;

    // payload.hourly가 객체 형태({key: {TMP,SKY,PTY}})라고 가정
    const entries = Object.entries(hourly)
      .map(([k, v]) => ({ key: k, dt: parseKeyToDate(k), ...v }))
      .filter((r) => r.dt instanceof Date && !isNaN(r.dt))
      .sort((a, b) => a.dt - b.dt);

    if (!entries.length) {
      hourlyEl.textContent = "시간별 예보가 없습니다.";
      return;
    }

    // 현재 시각(시 단위 내림)
    const now = new Date();
    const nowFloor = new Date(now.getFullYear(), now.getMonth(), now.getDate(), now.getHours(), 0, 0, 0);

    // 현재 시각 이상인 첫 슬롯 (없으면 마지막으로)
    let startIdx = entries.findIndex((r) => r.dt >= nowFloor);
    if (startIdx === -1) startIdx = entries.length - 1;

    const slice = entries.slice(startIdx, startIdx + count);

    // 렌더링 시작
    hourlyEl.innerHTML = "";
    hourlyEl.classList.toggle("is-stale", stale);

    // (옵션) stale 배지
    const oldBadge = hourlyEl.querySelector(".stale-badge");
    if (oldBadge) oldBadge.remove();
    if (stale) {
      const badge = document.createElement("div");
      badge.className = "stale-badge";
      badge.textContent = "최근 데이터 표시 중";
      hourlyEl.appendChild(badge);
    }

    // 카드들
    slice.forEach((r, i) => {
      const icon = pickIconSafe(r.SKY, r.PTY, r.dt.getHours());
      const label = makeHourLabel(nowFloor, now.getHours(), i, r.dt);
      const temp = toCelsius(r.TMP);
      const isNow = r.dt.getTime() === nowFloor.getTime();

      const card = document.createElement("div");
      card.className = "hour" + (isNow && i === 0 ? " hour--now" : "");
      if (isNow && i === 0) card.setAttribute("aria-current", "time");

      const labelEl = document.createElement("div");
      labelEl.className = "hour-label";
      labelEl.textContent = label;

      const iconWrap = document.createElement("div");
      iconWrap.className = "icon";
      const img = document.createElement("img");
      img.alt = "Weather icon";
      img.src = icon;
      img.onerror = () => {
        img.onerror = null;
        const dayDir = now.getHours() >= 6 && now.getHours() < 18 ? "Weather_day" : "Weather_night";
        img.src = `/weathericons/${dayDir}/overcast.png`;
      };
      iconWrap.appendChild(img);

      const tempEl = document.createElement("div");
      tempEl.className = "temp";
      tempEl.textContent = temp === null ? "—" : `${temp}℃`;

      card.append(labelEl, iconWrap, tempEl);
      hourlyEl.appendChild(card);
    });

    // 첫 카드로 스크롤 정렬
    hourlyEl.firstElementChild?.scrollIntoView({
      behavior: "auto",
      inline: "start",
      block: "nearest",
    });
  } catch (e) {
    hourlyEl.innerHTML = `
      <div class="hour" style="min-width:200px;text-align:center">
        <div class="hour-label">오류</div>
        <div class="temp" style="font-weight:400">${String(e.message || e)}</div>
      </div>
    `;
  }
})();
})();
