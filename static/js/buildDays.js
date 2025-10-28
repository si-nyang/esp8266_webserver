// ===== helpers =====
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
  const n = parseInt(v ?? 0, 10);
  return Number.isFinite(n) ? n : 0;
};
const toTemp = (v) => {
  const n = parseInt(v ?? 0, 10);
  return Number.isFinite(n) ? n : 0;
};

// 서버 응답을 daily 오브젝트로 정규화
function normalizeDaily(input) {
  if (!input) return null;
  // /api/daily → { daily: {...}, stale: false } 형태
  if (input.daily && typeof input.daily === "object") return input.daily;
  // /api/weather → { daily: {...}, ... } 형태
  if (input.daily) return input.daily;
  // 이미 daily 맵인 경우
  return input;
}

// ===== main =====
function buildDaysFromDaily(dailyObj) {
  const root = document.querySelector(".days");
  const normalized = normalizeDaily(dailyObj);
  if (!root || !normalized || typeof normalized !== "object") return;

  const days = Object.entries(normalized)
    .map(([k, v]) => ({ key: k, dt: parseYMD(k), ...v }))
    .sort((a, b) => a.dt - b.dt);

  root.innerHTML = "";

  days.forEach((d, idx) => {
    const title = labelTodayTomorrow(d.dt);
    const dateStr = formatDateMMDD(d.dt);

    const hasAM = d.AM && typeof d.AM === "object";
    const hasPM = d.PM && typeof d.PM === "object";

    let labelsHTML = "";
    let iconsHTML = "";
    let popsHTML = "";

    const hourAM = 9;  // 낮/밤 판정 기준
    const hourPM = 15;

    if (hasAM) {
      labelsHTML += `<div class="ap ap--am">오전</div>`;
      const amIcon = window.getIconPath(d.AM.SKY, d.AM.PTY, hourAM);
      iconsHTML += `<div class="icon icon--am"><img src="${amIcon}" alt="AM"></div>`;
      popsHTML += `<div class="pop pop--am">${toPct(d.AM.ST)}%</div>`;
    }
    if (hasPM) {
      labelsHTML += `<div class="ap ap--pm">오후</div>`;
      const pmIcon = window.getIconPath(d.PM.SKY, d.PM.PTY, hourPM);
      iconsHTML += `<div class="icon icon--pm"><img src="${pmIcon}" alt="PM"></div>`;
      popsHTML += `<div class="pop pop--pm">${toPct(d.PM.ST)}%</div>`;
    }

    // AM/PM 둘 다 없을 때 빈 자리라도 만들어 카드가 흔들리지 않게
    if (!hasAM && !hasPM) {
      labelsHTML = `<div class="ap ap--am">—</div>`;
      iconsHTML = `<div class="icon icon--am"><span style="opacity:.4">N/A</span></div>`;
      popsHTML = `<div class="pop pop--am">0%</div>`;
    }

    const centerHTML = `
      <div class="center-grid" style="margin:0 auto">
        ${labelsHTML}
        ${iconsHTML}
        ${popsHTML}
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
        <span class="lo">${lo}°</span>
        <span class="slash">/</span>
        <span class="hi">${hi}°</span>
      </div>
    `;
    root.appendChild(article);
  });
}

// ===== run =====
document.addEventListener("DOMContentLoaded", async () => {
  try {
    // 1) /api/daily 우선 시도
    const r1 = await fetch("/api/daily", { cache: "no-store" });
    if (r1.ok) {
      const j1 = await r1.json();
      buildDaysFromDaily(j1);
      return;
    }
  } catch (e) {
    console.warn("fetch /api/daily failed:", e);
  }

  // 2) /api/weather 대체 경로
  try {
    const r2 = await fetch("/api/weather", { cache: "no-store" });
    if (r2.ok) {
      const j2 = await r2.json();
      buildDaysFromDaily(j2);
    }
  } catch (e) {
    console.error("buildDays error:", e);
  }
});
