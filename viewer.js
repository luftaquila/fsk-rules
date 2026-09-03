(() => {
  "use strict";

  const config = JSON.parse(document.getElementById("rules-config").textContent);
  const root = new URL("../../", window.location.href);
  const storage = {
    theme: "fsk-rules:theme"
  };

  const toc = document.getElementById("toc");
  const tocToggle = document.getElementById("toc-toggle");
  const desktopToc = matchMedia("(min-width: 1024px)");
  const syncTocAccessibility = () => {
    const visible = toc.classList.contains("open");
    toc.inert = !visible;
    toc.setAttribute("aria-hidden", String(!visible));
  };
  const openToc = () => {
    toc.classList.add("open");
    tocToggle.setAttribute("aria-expanded", "true");
    syncTocAccessibility();
  };
  const closeToc = () => {
    toc.classList.remove("open");
    tocToggle.setAttribute("aria-expanded", "false");
    syncTocAccessibility();
  };
  tocToggle.addEventListener("click", () => {
    const open = toc.classList.toggle("open");
    tocToggle.setAttribute("aria-expanded", String(open));
    syncTocAccessibility();
  });
  document.getElementById("toc-close").addEventListener("click", () => {
    closeToc();
    tocToggle.focus();
  });
  toc.addEventListener("click", event => {
    if (!desktopToc.matches && event.target.closest("a")) closeToc();
  });
  document.addEventListener("click", event => {
    if (!desktopToc.matches && toc.classList.contains("open") && !toc.contains(event.target) && !tocToggle.contains(event.target)) {
      closeToc();
    }
  });
  document.addEventListener("keydown", event => {
    if (event.key === "Escape" && toc.classList.contains("open")) {
      closeToc();
      tocToggle.focus();
    }
  });
  const syncTocMode = () => desktopToc.matches ? openToc() : closeToc();
  desktopToc.addEventListener("change", syncTocMode);
  syncTocMode();

  const themeButton = document.getElementById("theme-toggle");
  const savedTheme = localStorage.getItem(storage.theme);
  if (savedTheme === "dark" || (!savedTheme && matchMedia("(prefers-color-scheme: dark)").matches)) {
    document.documentElement.dataset.theme = "dark";
  }
  const themeIcons = {
    moon: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20.2 15.3A8.5 8.5 0 0 1 8.7 3.8 8.5 8.5 0 1 0 20.2 15.3Z"/></svg>',
    sun: '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="3.5"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>'
  };
  const updateThemeButton = () => {
    const dark = document.documentElement.dataset.theme === "dark";
    const label = dark ? "밝은 테마로 전환" : "어두운 테마로 전환";
    themeButton.innerHTML = dark ? themeIcons.sun : themeIcons.moon;
    themeButton.setAttribute("aria-label", label);
    themeButton.title = label;
  };
  updateThemeButton();
  themeButton.addEventListener("click", () => {
    const dark = document.documentElement.dataset.theme !== "dark";
    document.documentElement.dataset.theme = dark ? "dark" : "light";
    localStorage.setItem(storage.theme, dark ? "dark" : "light");
    updateThemeButton();
  });

  const backButton = document.getElementById("back-to-position");
  let previousPosition = null;
  document.querySelectorAll(".rules-content a[href^='#']").forEach(link => {
    link.addEventListener("click", event => {
      if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) {
        return;
      }
      let target;
      try {
        target = document.getElementById(decodeURIComponent(link.hash.slice(1)));
      } catch (_) {
        return;
      }
      if (!target || link.hash === location.hash) return;
      previousPosition = {
        scrollY: window.scrollY,
        source: link
      };
      backButton.hidden = false;
    });
  });
  backButton.addEventListener("click", () => {
    if (!previousPosition) return;
    const previous = previousPosition;
    previousPosition = null;
    backButton.hidden = true;
    window.addEventListener("popstate", () => {
      setTimeout(() => {
        window.scrollTo({ top: previous.scrollY, behavior: "smooth" });
        if (previous.source.isConnected) previous.source.focus({ preventScroll: true });
      }, 0);
    }, { once: true });
    history.back();
  });

  const tocLinks = [...toc.querySelectorAll("a[href^='#']")];
  const tocById = new Map(tocLinks.map(link => [decodeURIComponent(link.hash.slice(1)), link]));
  const observer = new IntersectionObserver(entries => {
    const visible = entries.filter(entry => entry.isIntersecting).sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)[0];
    if (!visible) return;
    tocLinks.forEach(link => link.classList.remove("active"));
    const active = tocById.get(visible.target.id);
    if (active) {
      active.classList.add("active");
      active.scrollIntoView({ block: "nearest" });
    }
  }, { rootMargin: "-72px 0px -75% 0px" });
  document.querySelectorAll("h1[id], h2[id]").forEach(heading => observer.observe(heading));

  const editionSelect = document.getElementById("edition-select");
  const documentSelect = document.getElementById("document-select");
  let manifestDocuments = [];
  const fillDocumentOptions = (edition, preferred) => {
    documentSelect.replaceChildren();
    const choices = manifestDocuments.filter(item => item.edition === edition);
    for (const item of choices) {
      documentSelect.add(new Option(item.short_title, item.document, false, item.document === preferred));
    }
    if (!documentSelect.value && choices[0]) documentSelect.value = choices[0].document;
  };
  const navigateToSelection = () => {
    const edition = Number(editionSelect.value);
    const documentId = documentSelect.value;
    location.href = new URL(`${edition}/${documentId}/`, root);
  };
  editionSelect.addEventListener("change", () => {
    fillDocumentOptions(Number(editionSelect.value), config.document);
    navigateToSelection();
  });
  documentSelect.addEventListener("change", navigateToSelection);

  fetch(new URL("rules-manifest.json", root)).then(response => {
    if (!response.ok) throw new Error("manifest");
    return response.json();
  }).then(manifest => {
    manifestDocuments = manifest.documents;
    const editions = [...new Set(manifest.documents.map(item => item.edition))].sort((a, b) => b - a);
    for (const edition of editions) {
      const option = new Option(`${edition}년`, edition, false, edition === config.edition);
      editionSelect.add(option);
    }
    const selectedEdition = Number(editionSelect.value || config.edition);
    fillDocumentOptions(selectedEdition, config.document);
  }).catch(() => {
    editionSelect.disabled = true;
    documentSelect.disabled = true;
  });
})();
