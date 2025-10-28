async function fetchSnapshot() {
  try {
    const res = await fetch("/snapshot"); // fetch는 비동기: 직렬 수행x -> await: data 받을 때까지 다른 이벤트 처리
    const data = await res.json();

    // html elemnet 가져오기 (id 사용)
    const humidity = document.getElementById("humidity-value");
    const temp = document.getElementById("temp-value");
    const gamma1m = document.getElementById("gamma1m-value");
    const gamma10m = document.getElementById("gamma10m-value");
    const pm2_5 = document.getElementById("pm2_5-value");
    const pm10 = document.getElementById("pm10-value");

    if (humidity) humidity.textContent = data.Humidity;
    if (temp) temp.textContent = data.Temperature;
    if (gamma1m) gamma1m.textContent = data.GammaAverage1m;
    if (gamma10m) gamma10m.textContent = data.GammaAverage10m;
    if (pm2_5) pm2_5.textContent = data.PM2_5;
    if (pm10) pm10.textContent = data.PM10;
  } catch (e) {
    console.warn("Fetch error:", e);
  }
}

// eventListener 사용 // time 기반이지만 연습용
// eventListener 주요 사용 = 사용자 기반 event 발생(click, submit 등)
document.addEventListener("DOMContentLoaded", () => {
  fetchSnapshot();
  setInterval(fetchSnapshot, 60000); // 60s마다 snapshot 가져와서 업데이트
});
