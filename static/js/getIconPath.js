// static/js/getIconPath.js
window.getIconPath = function (sky, pty, hour) {
  const isDay = hour >= 6 && hour < 18;
  const baseDir = `/weathericons/${isDay ? "Weather_day" : "Weather_night"}`;

  const S = (sky || "").trim();
  const P = (pty || "").trim();

  let name;

  if (P && P !== "없음") {
    const isRain = P.includes("비");
    const isSnow = P.includes("눈");
    const isMixed = isRain && isSnow;

    if (isMixed)
      name =
        S === "구름많음" ? "cloudy_rain_and_snow" : "overcast_rain_and_snow";
    else if (isSnow) name = S === "구름많음" ? "cloudy_snow" : "overcast_snow";
    else if (isRain) name = S === "구름많음" ? "cloudy_rain" : "overcast_rain";
    else name = S === "구름많음" ? "cloudy_rain" : "overcast_rain";
  } else {
    if (S === "맑음") name = "sunny";
    else if (S === "구름많음") name = "cloudy";
    else name = "overcast";
  }

  return `${baseDir}/${name}.png`;
};
