(() => {
  "use strict";
  if (localStorage.getItem("fsk-rules:theme") === "dark") {
    document.documentElement.dataset.theme = "dark";
  }
  if (!location.hash) return;

  fetch("rules-manifest.json")
    .then(response => response.json())
    .then(manifest => {
      const latest = manifest.documents.find(item =>
        item.edition === manifest.latest_edition && item.document === "formula-technical"
      );
      if (latest) location.replace(latest.web_path + location.hash);
    })
    .catch(() => {});
})();
