const VIEW_NAMES = new Set(["map", "spots", "forecast", "guide"]);

export function viewFromHash(hash) {
  const key = hash.replace(/^#/, "");
  if (key === "grade-guide" || key === "charter-evidence") return "guide";
  return VIEW_NAMES.has(key) ? key : "map";
}

export function initNavigation({ onMapVisible }) {
  const $ = (id) => document.getElementById(id);
  const wide = window.matchMedia("(min-width:1200px)");
  const dialog = $("spot-dialog");
  const detail = $("detail");
  let hasSelection = false;
  // A reload has no selected-spot state to restore into a dialog.
  if (location.hash === "#spot") history.replaceState(null, "", "#map");

  function applyView() {
    const view = viewFromHash(location.hash);
    const changedView = document.body.dataset.view !== view;
    document.body.dataset.view = view;
    for (const panel of document.querySelectorAll("[data-panel]")) {
      panel.hidden =
        panel.dataset.panel !== view &&
        !(wide.matches && view === "map" && panel.dataset.panel === "spots");
    }
    $("desktop-detail").hidden = !wide.matches || view !== "map";
    for (const link of document.querySelectorAll("[data-nav]")) {
      if (link.dataset.nav === view) link.setAttribute("aria-current", "page");
      else link.removeAttribute("aria-current");
    }
    const wantsSheet =
      location.hash === "#spot" && hasSelection && !wide.matches;
    const leavingSheet = !wantsSheet && dialog.open;
    if (wantsSheet && !dialog.open) dialog.showModal();
    if (!wantsSheet && dialog.open) dialog.close();
    requestAnimationFrame(() => {
      if (view === "map") onMapVisible();
      if (
        location.hash === "#grade-guide" ||
        location.hash === "#charter-evidence"
      ) {
        const section = $(location.hash.slice(1));
        section.tabIndex = -1;
        section.focus({ preventScroll: true });
        section.scrollIntoView({ block: "start" });
      } else if (!wantsSheet && (changedView || leavingSheet)) {
        const destination =
          view === "map" && hasSelection
            ? $(wide.matches ? "desktop-detail" : "selected-preview")
            : $(`${view}-panel`);
        if (!destination.matches("button, a, [tabindex]"))
          destination.tabIndex = -1;
        destination.focus({ preventScroll: true });
      }
    });
  }

  function showView(view) {
    if (!VIEW_NAMES.has(view)) return;
    if (location.hash !== `#${view}`) location.hash = view;
    applyView();
  }

  function openDetails() {
    if (!hasSelection) return;
    if (wide.matches) {
      history.replaceState(null, "", "#map");
      applyView();
      $("desktop-detail").focus({ preventScroll: true });
    } else {
      history.pushState({ skippercastSheet: true }, "", "#spot");
      applyView();
      $("spot-dialog-body").scrollTop = 0;
    }
  }

  function closeDetails() {
    if (history.state?.skippercastSheet && location.hash === "#spot")
      history.back();
    else {
      history.replaceState(null, "", "#map");
      applyView();
    }
  }

  function syncLayout() {
    const host = wide.matches ? $("desktop-detail") : $("spot-dialog-body");
    host.append(detail);
    $("selected-preview").setAttribute(
      "aria-haspopup",
      wide.matches ? "false" : "dialog",
    );
    applyView();
  }

  $("selected-preview").addEventListener("click", openDetails);
  for (const link of document.querySelectorAll("[data-nav]")) {
    link.addEventListener("click", () => {
      if (link.dataset.nav !== "map")
        $(`${link.dataset.nav}-panel`).scrollTop = 0;
    });
  }
  $("close-spot-dialog").addEventListener("click", closeDetails);
  $("show-selected-map").addEventListener("click", closeDetails);
  dialog.addEventListener("cancel", (event) => {
    event.preventDefault();
    closeDetails();
  });
  window.addEventListener("hashchange", applyView);
  window.addEventListener("popstate", applyView);
  wide.addEventListener("change", syncLayout);
  syncLayout();
  return {
    showView,
    openDetails,
    setHasSelection(value) {
      hasSelection = value;
      $("selected-preview").hidden = !value;
      if (!value && dialog.open) closeDetails();
    },
  };
}
