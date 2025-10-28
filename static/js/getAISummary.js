// static/js/aiSummary.js
document.addEventListener("DOMContentLoaded", async () => {
  const box = document.querySelector(".ai-box");
  if (!box) return;

  const setPlaceholder = (msg = "요약 생성 중...") => {
    box.innerHTML = `<p class="placeholder">${msg}</p>`;
  };

  // 문자열 요약 렌더링 (줄바꿈 보존)
  const renderTextSummary = (text) => {
    const safe = String(text).trim();
    if (!safe) return setPlaceholder("요약을 불러오지 못했습니다.");
    // 줄바꿈을 <br>로 표시 (원하면 <pre>를 사용해도 됨)
    const html = safe
      .split(/\r?\n/)
      .map((line) => `<p class="ai-summary-text">${escapeHtml(line)}</p>`)
      .join("");
    box.innerHTML = html;
  };

  // JSON 요약 렌더링 (기존 구조 호환: summary + tips/indoor_tip/outdoor_tip)
  const renderJsonSummary = (data) => {
    const summary = data.summary || "";
    // tips 배열 우선 사용, 없으면 indoor/outdoor 필드 사용
    const tips = Array.isArray(data.tips) ? data.tips : [];
    const indoor = data.indoor_tip || (tips[0]?.text ?? "");
    const outdoor = data.outdoor_tip || (tips[1]?.text ?? "");

    const tipsHtml = [indoor, outdoor]
      .filter(Boolean)
      .map((t) => `<li>${escapeHtml(t)}</li>`)
      .join("");

    const summaryHtml = summary
      ? summary
          .split(/\r?\n/)
          .map((line) => `<p class="ai-summary-text">${escapeHtml(line)}</p>`)
          .join("")
      : `<p class="placeholder">요약을 불러오지 못했습니다.</p>`;

    box.innerHTML = `
      ${summaryHtml}
      ${tipsHtml ? `<ul class="ai-tips">${tipsHtml}</ul>` : ""}
    `;
  };

  // XSS 방지용 이스케이프
  const escapeHtml = (s) =>
    String(s)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");

  try {
    setPlaceholder();

    const res = await fetch("/ai-summary"); // same-origin
    if (!res.ok) throw new Error(`HTTP ${res.status}`);

    const ctype = (res.headers.get("content-type") || "").toLowerCase();

    if (ctype.includes("application/json")) {
      const data = await res.json();
      renderJsonSummary(data);
    } else {
      const text = await res.text(); // text/plain 또는 기타
      renderTextSummary(text);
    }
  } catch (err) {
    console.error("ai-summary fetch error:", err);
    setPlaceholder("요약을 불러오지 못했습니다.");
  }
});
