"use strict";
(function () {
  const SETTINGS_PATH = "__SETTINGS_PATH__";
  const READY_FUNCTION = "__READY_FUNCTION__";
  const button = document.getElementById("saveable-button");
  const note = document.getElementById("saveable-note");
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
  async function store() {
    if (!window.claude || !window.claude.use) return null;
    return await window.claude.use("db");
  }
  async function applySaved(saved) {
    window.savedPageSettings = saved;
    await booted;
    await window.savedPage.apply(saved);
    if (window.savedPage.verify) window.savedPage.verify(saved);
  }
  async function load() {
    try {
      const database = await store();
      if (!database) { note.textContent = "Saved settings are not available in this view."; return; }
      const found = await database.doc(SETTINGS_PATH).get();
      if (!found.exists) { note.textContent = "No saved settings yet."; return; }
      await applySaved(found.data().saved);
      note.textContent = "Showing the settings saved " + String(found.data().savedAt || "").slice(0, 16).replace("T", " ") + " UTC.";
    } catch (error) {
      console.error("loading the saved settings failed:", error);
      note.textContent = "Could not load the saved settings: " + (error.message || error);
    }
  }
  button.addEventListener("click", async () => {
    button.disabled = true;
    note.textContent = "Saving...";
    try {
      const database = await store();
      if (!database) throw new Error("saving is not available here: sign in, or ask for edit access");
      await database.doc(SETTINGS_PATH).set({ saved: window.savedPage.snapshot(), savedAt: new Date().toISOString() });
      note.textContent = "Saved for everyone.";
    } catch (error) {
      console.error("saving the settings failed:", error);
      note.textContent = "Could not save: " + (error.message || error);
    }
    button.disabled = false;
  });
  load();
})();
