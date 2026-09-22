export const chartLayers = mode => mode === 'nautical' ? '0,1,2,3,4,5,6,7' : '0,1,2,6';
export function initChart(map, notify) {
  const street = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution:
      '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
  });
  const chart = L.tileLayer.wms(
    "https://gis.charttools.noaa.gov/arcgis/rest/services/MCS/NOAAChartDisplay/MapServer/exts/MaritimeChartService/WMSServer",
    {
      layers: chartLayers(document.getElementById('base-map').value),
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
  const choice=document.getElementById('base-map');
  const sync=()=>{if(choice.value==='nautical'||choice.value==='fishing'&&map.getZoom()>=10)chart.addTo(map);else map.removeLayer(chart);};
  map.on('zoomend',sync);sync();
  let failed = false;
  chart.on("tileerror", () => {
    if (!failed) {
      failed = true;
      notify(
        "NOAA chart tile unavailable. Choose Street map in Layers if the chart stays blank.",
      );
    }
  });
  document.getElementById("base-map").addEventListener("change", (e) => {
    if (e.target.value === "street") map.removeLayer(chart);
    else {
      chart.setParams({
        layers: chartLayers(e.target.value),
      });
      sync();
    }
  });
}
