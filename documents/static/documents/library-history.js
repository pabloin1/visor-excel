"use strict";

(() => {
  const dialog = document.querySelector("#library-history-dialog");
  if (!dialog || typeof dialog.showModal !== "function") return;

  const content = dialog.querySelector("[data-history-content]");
  const closeButton = dialog.querySelector(".library-history-close");
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  let activeTrigger = null;
  let closeTimer = null;

  const alignDialog = () => {
    if (!dialog.open || !activeTrigger) return;
    if (window.matchMedia("(max-width: 760px)").matches) {
      dialog.style.removeProperty("--library-history-top");
      return;
    }
    const card = activeTrigger.closest(".library-card").getBoundingClientRect();
    const height = dialog.getBoundingClientRect().height;
    const idealTop = card.top + (card.height - height) / 2;
    const top = Math.max(
      20,
      Math.min(idealTop, window.innerHeight - height - 20),
    );
    dialog.style.setProperty("--library-history-top", `${top}px`);
  };

  const closeDialog = () => {
    if (dialog.open) dialog.close();
  };

  const requestClose = () => {
    if (!dialog.open || dialog.classList.contains("is-closing")) return;
    if (reducedMotion.matches) {
      closeDialog();
      return;
    }
    dialog.classList.add("is-closing");
    closeTimer = window.setTimeout(closeDialog, 160);
  };

  document.querySelectorAll("[data-history-trigger]").forEach((link) => {
    link.addEventListener("click", (event) => {
      const template = document.getElementById(link.dataset.historyTemplate);
      if (!template) return;
      event.preventDefault();
      content.replaceChildren(template.content.cloneNode(true));
      activeTrigger = link;
      link.closest(".library-card")?.classList.add("is-history-open");
      dialog.showModal();
      alignDialog();
      closeButton.focus();
    });
  });

  closeButton.addEventListener("click", requestClose);
  dialog.addEventListener("cancel", (event) => {
    event.preventDefault();
    requestClose();
  });
  dialog.addEventListener("click", (event) => {
    if (event.target === dialog) requestClose();
  });
  window.addEventListener("resize", alignDialog);
  dialog.addEventListener("close", () => {
    window.clearTimeout(closeTimer);
    closeTimer = null;
    dialog.classList.remove("is-closing");
    activeTrigger
      ?.closest(".library-card")
      ?.classList.remove("is-history-open");
    activeTrigger?.focus({ preventScroll: true });
    activeTrigger = null;
    dialog.style.removeProperty("--library-history-top");
    content.replaceChildren();
  });
})();
