// ===== helpers =====
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

// 응답 정규화: /api/weather → {hourly:{}, stale}, 혹은 hourly 그 자체
function normalizeHourly(payload) {
  if (!payload) return {};
  if (payload.hourly && typeof payload.hourly === "object") return payload.hourly;
  return payload;
}

// 레이블: offset=0이면 "현재", 날짜 바뀌면 "내일" 또는 요일, 그 외 "HH시"
function makeHourLabel(nowDate, nowHour, offset, targetDt) {
  if (offset === 0) return "현재";
  const isOtherDay =
    targetDt.getFullYear() !== nowDate.getFullYear() ||
    targetDt.getMonth() !== nowDate.getMonth() ||
    targetDt.getDate() !== nowDate.getDate();

  if (isOtherDay) {
    // 내일이면 "내일", 그 외엔 요일
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

// ===== main =====
(async function buildHourlyFromAPI(limit = 18) {
  const hourlyEl = document.getElementById("hourly");
  if (!hourlyEl) return;

  try {
    const payload = await fetchWithRetry("/api/weather");
    if (payload.error) throw new Error(payload.error);

    const hourly = normalizeHourly(payload);
    const stale = !!payload.stale;

    const entries = Object.entries(hourly)
      .map(([k, v]) => ({ key: k, dt: parseKeyToDate(k), ...v }))
      .sort((a, b) => a.dt - b.dt);

    if (!entries.length) {
      hourlyEl.textContent = "시간별 예보가 없습니다.";
      return;
    }

    // 현재 시각을 시 단위 내림
    const now = new Date();
    const nowFloor = new Date(now.getFullYear(), now.getMonth(), now.getDate(), now.getHours(), 0, 0, 0);

    // 현재 시각 이상인 첫 슬롯 찾기(없으면 마지막으로)
    let startIdx = entries.findIndex((r) => r.dt >= nowFloor);
    if (startIdx === -1) startIdx = entries.length - 1;

    const slice = entries.slice(startIdx, startIdx + Math.max(1, limit));

    // 렌더링
    hourlyEl.innerHTML = "";

    // (옵션) stale 배지
    if (stale) {
      const badge = document.createElement("div");
      badge.className = "stale-badge";
      badge.textContent = "최근 데이터 표시 중";
      hourlyEl.appendChild(badge);
    }

    slice.forEach((r, i) => {
      const iconFn = window.getIconPath || getIconPath; // 전역 보조
      const icon = iconFn(r.SKY, r.PTY, r.dt.getHours());
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
      img.src = icon;
      img.alt = "Weather icon";
      iconWrap.appendChild(img);

      const tempEl = document.createElement("div");
      tempEl.className = "temp";
      tempEl.textContent = temp === null ? "—" : `${temp}℃`;

      card.append(labelEl, iconWrap, tempEl);
      hourlyEl.appendChild(card);
    });

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
