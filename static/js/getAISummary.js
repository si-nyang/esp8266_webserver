// static/js/aiSummary.js
document.addEventListener("DOMContentLoaded", async () => {
  const box = document.querySelector(".ai-box");
  if (!box) return;

  box.innerHTML = `<p class="placeholder">요약 생성 중...</p>`;

  try {
    const res = await fetch("/ai-summary");
    const data = await res.json();

    const summary = data.summary || "요약을 불러오지 못했습니다.";
    const indoor = data.indoor_tip || "";
    const outdoor = data.outdoor_tip || "";

    box.innerHTML = `
      <p class="ai-summary-text">${summary}</p>
      <ul class="ai-tips">
        <li>${indoor}</li>
        <li>${outdoor}</li>
      </ul>
    `;
  } catch (err) {
    console.error(err);
    box.innerHTML = `<p class="placeholder">요약을 불러오지 못했습니다.</p>`;
  }
});
