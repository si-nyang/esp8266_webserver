(function () {
  // ===== 헬퍼 함수 =====
  const setPlaceholder = (box, msg = "요약 생성 중...") => {
    box.innerHTML = `<p class="placeholder">${msg}</p>`;
  };

  const escapeHtml = (s) =>
    String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");

  const renderTextSummary = (box, text) => {
    const safe = String(text).trim();
    if (!safe) return setPlaceholder(box, "요약을 불러오지 못했습니다.");
    const html = safe
      .split(/\r?\n/)
      .map((line) => `<p class="ai-summary-text">${escapeHtml(line)}</p>`)
      .join("");
    box.innerHTML = html;
  };

  const renderJsonSummary = (box, data) => {
    const summary = data.summary || "";
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

  // ===== 메인 함수 =====
  async function loadAISummary() {
    const box = document.querySelector(".ai-box");
    if (!box) return;

    try {
      setPlaceholder(box);

      const res = await fetch("/ai-summary");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);

      const ctype = (res.headers.get("content-type") || "").toLowerCase();

      if (ctype.includes("application/json")) {
        const data = await res.json();
        if (typeof data === "string") {
          renderTextSummary(box, data);
        } else {
          renderJsonSummary(box, data);
        }
      } else {
        const text = await res.text();
        renderTextSummary(box, text);
      }
    } catch (err) {
      console.error("ai-summary fetch error:", err);
      setPlaceholder(box, "요약을 불러오지 못했습니다.");
    }
  }

  // ===== 실행 =====
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", loadAISummary);
  } else {
    loadAISummary();
  }
})();
