// Save-Data for the landing (FE-25 review): a visitor who asked the browser to
// save data (`navigator.connection.saveData`) gets the static shoreline only,
// never MapLibre, the basemap or the currents. Erasable syntax only:
// tests/test_landing.mjs imports this file by type stripping.

/** True when `nav` reports Save-Data on (Network Information API; absent in most browsers, which then load the map). */
export function saveData(nav: unknown): boolean {
  return (nav as {connection?: {saveData?: unknown} | null} | null | undefined)?.connection?.saveData === true;
}
