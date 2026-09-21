export function initChart(map, notify) {
  const street = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution:
      '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
  });
  const chart = L.tileLayer.wms(
    "https://gis.charttools.noaa.gov/arcgis/rest/services/MCS/NOAAChartDisplay/MapServer/exts/MaritimeChartService/WMSServer",
    {
      layers: "0,1,2,3,4,5,6,7",
      format: "image/png",
      transparent: false,
      version: "1.3.0",
      maxZoom: 18,
      tileSize: 512,
      attribution:
        '<a href="https://www.nauticalcharts.noaa.gov/data/gis-data-and-services.html">NOAA ENC display</a> · planning only',
    },
  );
  street.addTo(map);
  chart.addTo(map);
  let failed = false;
  chart.on("tileerror", () => {
    if (!failed) {
      failed = true;
      notify(
        "NOAA chart tile unavailable. Choose Street map in Layers if the chart stays blank.",
      );
    }
  });
  document
    .getElementById("base-map")
    .addEventListener("change", (e) =>
      e.target.value === "nautical" ? chart.addTo(map) : map.removeLayer(chart),
    );
}
