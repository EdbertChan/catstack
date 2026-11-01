"use strict";
(function () {
  const frame = document.getElementById("__FRAME_ID__");
  const SETTINGS_PATH = "__SETTINGS_PATH__";
  async function store() {
    if (!window.claude || !window.claude.use) return null;
    return await window.claude.use("db");
  }
  function reply(message) { if (frame.contentWindow) frame.contentWindow.postMessage(message, "*"); }
  window.addEventListener("message", async event => {
    if (event.source !== frame.contentWindow || !event.data) return;
    if (event.data.kind === "saveable-load-request") {
      try {
        const database = await store();
        if (!database) {
          console.warn("saved settings are unavailable: the database is not reachable from this page");
          reply({ kind: "saveable-unavailable" });
          return;
        }
        const found = await database.doc(SETTINGS_PATH).get();
        if (found.exists) reply({ kind: "saveable-loaded", saved: found.data().saved, savedAt: found.data().savedAt });
        else reply({ kind: "saveable-none" });
      } catch (error) {
        console.error("loading the saved settings failed:", error);
        reply({ kind: "saveable-load-failed", error: error.message || String(error) });
      }
    } else if (event.data.kind === "saveable-save") {
      try {
        const database = await store();
        if (!database) throw new Error("saving is not available here: sign in, or ask for edit access");
        await database.doc(SETTINGS_PATH).set({ saved: event.data.saved, savedAt: new Date().toISOString() });
        reply({ kind: "saveable-save-result", ok: true });
      } catch (error) {
        console.error("saving the settings failed:", error);
        reply({ kind: "saveable-save-result", ok: false, error: error.message || String(error) });
      }
    }
  });
})();
