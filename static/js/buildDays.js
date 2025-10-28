// ===== helpers =====
const K_WEEK = ["일", "월", "화", "수", "목", "금", "토"];

function parseYMD(key) {
  // 'YYYYMMDD' 또는 그 이상 길이여도 앞 8자리만 사용
  const y = +key.slice(0, 4),
    m = +key.slice(4, 6) - 1,
    d = +key.slice(6, 8);
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

// ===== main =====
function buildDaysFromDaily(dailyObj) {
  const root = document.querySelector(".days");
  if (!root || !dailyObj) return;

  // 정렬
  const days = Object.entries(dailyObj)
    .map(([k, v]) => ({ key: k, dt: parseYMD(k), ...v }))
    .sort((a, b) => a.dt - b.dt);

  root.innerHTML = "";

  days.forEach((d, idx) => {
    const title = labelTodayTomorrow(d.dt);
    const dateStr = formatDateMMDD(d.dt);

    const hasAM = !!d.AM;
    const hasPM = !!d.PM;

    // 오전/오후 있을 때만 생성
    let labelsHTML = "";
    let iconsHTML = "";
    let popsHTML = "";

    const hourAM = 9; // getIconPath 낮/밤 판정용 기준 시간
    const hourPM = 15;

    if (hasAM) {
      labelsHTML += `<div class="ap ap--am">오전</div>`;
      const amIcon = window.getIconPath(d.AM.SKY, d.AM.PTY, hourAM);
      iconsHTML += `<div class="icon icon--am"><img src="${amIcon}" alt="AM"></div>`;
      popsHTML += `<div class="pop pop--am">${Number(d.AM.ST || 0)}%</div>`;
    }
    if (hasPM) {
      labelsHTML += `<div class="ap ap--pm">오후</div>`;
      const pmIcon = window.getIconPath(d.PM.SKY, d.PM.PTY, hourPM);
      iconsHTML += `<div class="icon icon--pm"><img src="${pmIcon}" alt="PM"></div>`;
      popsHTML += `<div class="pop pop--pm">${Number(d.PM.ST || 0)}%</div>`;
    }

    const centerHTML = `
      <div class="center-grid" style="margin:0 auto">
        ${labelsHTML}
        ${iconsHTML}
        ${popsHTML}
      </div>
    `;

    const article = document.createElement("article");
    article.className = "daycard" + (idx === 0 ? " day--today" : "");
    article.innerHTML = `
      <div class="day-left">
        <div class="day-title">${title}</div>
        <div class="day-sub">${dateStr}</div>
      </div>
      <div class="day-center">${centerHTML}</div>
      <div class="day-right">
        <span class="lo">${Number(d.TMN)}°</span>
        <span class="slash">/</span>
        <span class="hi">${Number(d.TMX)}°</span>
      </div>
    `;
    root.appendChild(article);
  });
}

// ===== run (하나만 선택해서 쓰면 됨) =====
// 1) 서버가 /api/daily 로 내려주는 경우:
document.addEventListener("DOMContentLoaded", async () => {
  try {
    const res = await fetch("/api/daily", { cache: "no-cache" });
    if (res.ok) {
      const daily = await res.json();
      buildDaysFromDaily(daily);
      return;
    }
    // /api/daily 없으면 /api/weather 에 daily가 들어있는 경우 시도
    const res2 = await fetch("/api/weather", { cache: "no-cache" });
    if (res2.ok) {
      const data = await res2.json();
      if (data && data.daily) buildDaysFromDaily(data.daily);
    }
  } catch (e) {
    console.error("buildDays error:", e);
  }
});
