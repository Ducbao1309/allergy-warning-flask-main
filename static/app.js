document.addEventListener("DOMContentLoaded", () => {
  const toggle = document.querySelector(".nav-toggle");
  const nav = document.getElementById("primary-nav");
  if (toggle && nav) {
    toggle.addEventListener("click", () => {
      const isOpen = nav.classList.toggle("is-open");
      toggle.setAttribute("aria-expanded", String(isOpen));
      toggle.setAttribute("aria-label", isOpen ? "Đóng menu" : "Mở menu");
      toggle.textContent = isOpen ? "×" : "☰";
    });
  }

  const form = document.querySelector("[data-scan-form]");
  const input = document.getElementById("image");
  const preview = document.querySelector("[data-image-preview]");
  const fileName = document.querySelector("[data-file-name]");
  const submit = document.querySelector("[data-submit-button]");
  const loading = document.querySelector("[data-loading-message]");

  const showFile = (file) => {
    if (!file || !preview) return;
    const image = preview.querySelector("img");
    if (image) {
      if (image.dataset.objectUrl) URL.revokeObjectURL(image.dataset.objectUrl);
      const objectUrl = URL.createObjectURL(file);
      image.src = objectUrl;
      image.dataset.objectUrl = objectUrl;
    }
    if (fileName) fileName.textContent = file.name;
    preview.hidden = false;
  };

  if (input) input.addEventListener("change", () => showFile(input.files && input.files[0]));

  const dropArea = document.querySelector("[data-drop-area]");
  if (dropArea && input) {
    ["dragenter", "dragover"].forEach((eventName) => dropArea.addEventListener(eventName, (event) => {
      event.preventDefault();
      dropArea.classList.add("is-dragging");
    }));
    ["dragleave", "drop"].forEach((eventName) => dropArea.addEventListener(eventName, (event) => {
      event.preventDefault();
      dropArea.classList.remove("is-dragging");
    }));
    dropArea.addEventListener("drop", (event) => {
      const file = event.dataTransfer && event.dataTransfer.files && event.dataTransfer.files[0];
      if (!file) return;
      const transfer = new DataTransfer();
      transfer.items.add(file);
      input.files = transfer.files;
      showFile(file);
    });
  }

  if (form) form.addEventListener("submit", () => {
    if (submit) {
      submit.disabled = true;
      submit.textContent = "Đang phân tích…";
    }
    if (loading) loading.hidden = false;
  });

  document.querySelectorAll("form:not([data-scan-form])").forEach((otherForm) => {
    otherForm.addEventListener("submit", (event) => {
      const button = event.submitter || otherForm.querySelector("button[type='submit'], button:not([type])");
      if (button && !button.disabled) {
        button.disabled = true;
        button.dataset.originalLabel = button.textContent;
        button.textContent = "Đang xử lý…";
      }
      otherForm.setAttribute("aria-busy", "true");
    });
  });
});
