"use strict";

document.querySelectorAll("[data-version-drop]").forEach((card) => {
  const form = card.querySelector(".library-card-drop-form");
  const input = form.querySelector('input[type="file"]');
  const error = card.querySelector(".library-card-drop-error");
  let depth = 0;

  const hasFiles = (event) => Boolean(event.dataTransfer && (
    Array.from(event.dataTransfer.types || []).includes("Files") || event.dataTransfer.files?.length
  ));
  const reset = () => {
    depth = 0;
    card.classList.remove("is-drag-target");
  };

  card.addEventListener("dragenter", (event) => {
    if (!hasFiles(event) || card.classList.contains("is-uploading")) return;
    event.preventDefault();
    depth += 1;
    error.textContent = "";
    card.classList.add("is-drag-target");
  });
  card.addEventListener("dragover", (event) => {
    if (!hasFiles(event) || card.classList.contains("is-uploading")) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
  });
  card.addEventListener("dragleave", () => {
    depth = Math.max(0, depth - 1);
    if (!depth) reset();
  });
  card.addEventListener("drop", (event) => {
    if (!hasFiles(event)) return;
    event.preventDefault();
    reset();
    if (card.classList.contains("is-uploading")) return;
    const files = event.dataTransfer.files;
    if (files.length !== 1) {
      error.textContent = "Suelte un solo archivo Excel a la vez.";
      return;
    }
    const file = files[0];
    if (!/\.(xlsx|xls)$/i.test(file.name)) {
      error.textContent = "Seleccione un archivo Excel .xlsx o .xls.";
      return;
    }
    if (file.size > 50 * 1024 * 1024) {
      error.textContent = "El archivo supera el máximo de 50 MB.";
      return;
    }
    try {
      input.files = files;
    } catch (_error) {
      error.textContent = "Use el botón «Agregar versión» para seleccionar el archivo.";
      return;
    }
    card.classList.add("is-uploading");
    if (form.requestSubmit) form.requestSubmit();
    else form.submit();
  });
  window.addEventListener("dragend", reset);
  window.addEventListener("drop", reset);
});
