(() => {
  "use strict";
  if (localStorage.getItem("fsk-rules:theme") === "dark") {
    document.documentElement.dataset.theme = "dark";
  }
  const choose = new URLSearchParams(location.search).get("choose") === "1";
  fetch("rules-manifest.json")
    .then(response => response.json())
    .then(manifest => {
      let target = null;
      if (location.hash) {
        const latest = manifest.documents.find(item =>
          item.edition === manifest.latest_edition && item.document === "formula-technical"
        );
        if (latest) target = latest.web_path + location.hash;
      } else if (!choose) {
        const saved = localStorage.getItem("fsk-rules:last-document");
        if (saved && manifest.documents.some(item => item.web_path === saved)) target = saved;
      }
      if (target) location.replace(target);
    })
    .catch(() => {});
})();
