"use strict";
(function () {
  const READY_FUNCTION = "__READY_FUNCTION__";
  const button = document.getElementById("saveable-button");
  const note = document.getElementById("saveable-note");
  const hosted = window.parent !== window;
  const booted = new Promise(resolve => {
    if (window.savedPage.isReady && window.savedPage.isReady()) { resolve(); return; }
    const original = window[READY_FUNCTION];
    if (typeof original !== "function") throw new Error("the ready function " + READY_FUNCTION + " is not defined when the save script runs");
    window[READY_FUNCTION] = function (...args) {
      const result = original.apply(this, args);
      resolve();
      return result;
    };
  });
  async function applySaved(saved) {
    window.savedPageSettings = saved;
    await booted;
    await window.savedPage.apply(saved);
    if (window.savedPage.verify) window.savedPage.verify(saved);
  }
  window.addEventListener("message", event => {
    if (event.source !== window.parent || !event.data) return;
    const message = event.data;
    if (message.kind === "saveable-loaded" && message.saved) {
      applySaved(message.saved)
        .then(() => { note.textContent = "Showing the settings saved " + String(message.savedAt || "").slice(0, 16).replace("T", " ") + " UTC."; })
        .catch(error => { console.error("applying the saved settings failed:", error); note.textContent = "Could not apply the saved settings: " + error.message; });
    } else if (message.kind === "saveable-unavailable") {
      note.textContent = "Saved settings are not available in this view.";
    } else if (message.kind === "saveable-none") {
      note.textContent = "No saved settings yet.";
    } else if (message.kind === "saveable-load-failed") {
      note.textContent = "Could not load the saved settings: " + message.error;
    } else if (message.kind === "saveable-save-result") {
      button.disabled = false;
      note.textContent = message.ok ? "Saved for everyone." : "Could not save: " + message.error;
    }
  });
  button.addEventListener("click", () => {
    if (!hosted) { note.textContent = "Saving works only inside the shared page."; return; }
    button.disabled = true;
    note.textContent = "Saving...";
    window.parent.postMessage({ kind: "saveable-save", saved: window.savedPage.snapshot() }, "*");
  });
  if (hosted) window.parent.postMessage({ kind: "saveable-load-request" }, "*");
})();
