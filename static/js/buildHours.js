function parseKeyToDate(k) {
  const y = +k.slice(0, 4),
    m = +k.slice(4, 6) - 1,
    d = +k.slice(6, 8);
  const H = +k.slice(8, 10),
    M = +k.slice(10, 12);
  return new Date(y, m, d, H, M, 0, 0);
}

function makeHourLabel(nowHour, offset, targetHour) {
  if (offset === 0) return "현재";
  const crossesMidnight = targetHour < nowHour;
  if (crossesMidnight && targetHour === 0) return "내일";
  return `${String(targetHour).padStart(2, "0")}시`;
}

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

(async function buildHourlyFromAPI(limit = 18) {
  const hourlyEl = document.getElementById("hourly");
  if (!hourlyEl) return;

  try {
    const data = await fetchWithRetry("/api/weather");
    if (data.error) throw new Error(data.error);

    const hourly = data.hourly || {};
    const entries = Object.entries(hourly)
      .map(([k, v]) => ({ key: k, dt: parseKeyToDate(k), ...v }))
      .sort((a, b) => a.dt - b.dt);

    if (!entries.length) return;

    // 🔹 현재 시각을 "시 단위로 내림"
    const now = new Date();
    const nowHour = now.getHours(); // ✅ 레이블 계산에 필요
    const nowFloor = new Date(
      now.getFullYear(),
      now.getMonth(),
      now.getDate(),
      nowHour,
      0,
      0,
      0
    );

    // 🔹 현재 슬롯(<= now)부터 보이도록
    let startIdx = entries.findIndex((r) => r.dt >= nowFloor);
    if (startIdx === -1) startIdx = entries.length - 1; // 모두 과거면 맨 마지막

    const slice = entries.slice(startIdx, startIdx + limit);

    hourlyEl.innerHTML = "";

    slice.forEach((r, i) => {
      const hour = r.dt.getHours();
      const label = makeHourLabel(nowHour, i, hour);
      const icon = getIconPath(r.SKY, r.PTY, hour);
      const isNow = i === 0;

      const card = document.createElement("div");
      card.className = "hour" + (isNow ? " hour--now" : "");
      if (isNow) card.setAttribute("aria-current", "time");

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
      tempEl.textContent = `${r.TMP}℃`;

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
        <div class="temp" style="font-weight:400">${String(
          e.message || e
        )}</div>
      </div>
    `;
  }
})();
