const VIEW_NAMES = new Set(["map", "forecast", "guide"]);
export function viewFromHash(hash) {
  const key = hash.replace(/^#/, "");
  if (key === "grade-guide" || key === "charter-evidence") return "guide";
  return VIEW_NAMES.has(key) ? key : "map";
}
export function initNavigation({ onMapVisible }) {
  const $ = (id) => document.getElementById(id);
  const dialog = $("spot-dialog");
  let hasSelection = false;
  if (location.hash === "#spot" || location.hash === "#spots")
    history.replaceState(null, "", "#map");
  function applyView() {
    const view = viewFromHash(location.hash);
    document.body.dataset.view = view;
    for (const panel of document.querySelectorAll("[data-panel]"))
      panel.hidden = panel.dataset.panel !== view;
    for (const link of document.querySelectorAll("[data-nav]")) {
      if (link.dataset.nav === view) link.setAttribute("aria-current", "page");
      else link.removeAttribute("aria-current");
    }
    const sheet = location.hash === "#spot" && hasSelection;
    if (sheet && !dialog.open) {
      dialog.showModal();
      $("spot-dialog-body").scrollTop = 0;
    }
    if (!sheet && dialog.open) dialog.close();
    requestAnimationFrame(() => {
      if (view === "map") onMapVisible();
      if (["#grade-guide", "#charter-evidence"].includes(location.hash)) {
        const section = $(location.hash.slice(1));
        for (let node = section.parentElement; node; node = node.parentElement)
          if (node.tagName === "DETAILS") node.open = true;
        section.tabIndex = -1;
        section.focus({ preventScroll: true });
        section.scrollIntoView({ block: "start" });
      }
    });
  }
  function showView(view) {
    if (!VIEW_NAMES.has(view)) return;
    for (const d of document.querySelectorAll("dialog[open]")) d.close();
    location.hash = view;
    applyView();
  }
  function closeDetails() {
    history.replaceState(null, "", "#map");
    applyView();
  }
  function openDetails() {
    if (!hasSelection) return;
    if (location.hash !== "#spot")
      history.pushState({ skippercastSheet: true }, "", "#spot");
    applyView();
  }
  $("close-spot-dialog").addEventListener("click", closeDetails);
  $("show-selected-map").addEventListener("click", closeDetails);
  dialog.addEventListener("cancel", (e) => {
    e.preventDefault();
    closeDetails();
  });
  dialog.addEventListener("click", (e) => {
    if (e.target === dialog) {
      const r = dialog.getBoundingClientRect();
      if (
        e.clientX < r.left ||
        e.clientX > r.right ||
        e.clientY < r.top ||
        e.clientY > r.bottom
      )
        closeDetails();
    }
  });
  window.addEventListener("hashchange", applyView);
  window.addEventListener("popstate", applyView);
  applyView();
  return {
    showView,
    openDetails,
    setHasSelection(value) {
      hasSelection = value;
      if (!value && dialog.open) closeDetails();
    },
  };
}
