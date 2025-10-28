// eventListener 사용 x
(function () {
  const $time = document.getElementById("now-time");
  const $date = document.getElementById("now-date");
  // const $loc = document.getElementById("loc-text");

  // 시간/날짜
  function updateClock() {
    const now = new Date();

    const hh = String(now.getHours()).padStart(2, "0");
    const mm = String(now.getMinutes()).padStart(2, "0");
    const ss = String(now.getSeconds()).padStart(2, "0");
    if ($time) $time.textContent = `${hh}:${mm}:${ss}`; // -> 14:32:05

    const formatted_date = new Intl.DateTimeFormat("en-US", {
      weekday: "long",
      month: "long",
      day: "numeric",
      year: "numeric",
    }).format(now);
    if ($date) $date.textContent = formatted_date; // Sunday, 5 december, 2021
  }

  updateClock();
  setInterval(updateClock, 1000); // 1초마다 갱신

  // 위치
  // async function updateLocation() {
  //   if (!navigator.geolocation) {
  //     if ($loc) $loc.textContent = "위치 정보 사용 불가";
  //     return;
  //   }

  //   try {
  //     const pos = await new Promise((res, rej) =>
  //       navigator.geolocation.getCurrentPosition(res, rej, { timeout: 5000 })
  //     );
  //     const { latitude, longitude } = pos.coords;

  //     const url = `https://nominatim.openstreetmap.org/reverse?format=json&lat=${latitude}&lon=${longitude}`;
  //     const res = await fetch(url);
  //     const data = await res.json();

  //     console.log(data);

  //     const city = data.address.city;
  //     const town =
  //       data.address.town || data.address.village || data.address.borough;

  //     if ($loc) {
  //       if (city && town) $loc.textContent = `${city}, ${town}`;
  //       else if (city) $loc.textContent = city;
  //       else if (town) $loc.textContent = town;
  //       else
  //         $loc.textContent = `${latitude.toFixed(3)}, ${longitude.toFixed(3)}`;
  //     }
  //   } catch (e) {
  //     if ($loc) $loc.textContent = "위치 접근 거부됨";
  //   }
  // }

  // updateLocation();
})();
