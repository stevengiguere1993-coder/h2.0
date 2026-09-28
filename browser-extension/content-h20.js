// Content script qui tourne sur les pages h2.0 (frontend Render +
// localhost). Sert de bridge entre h2.0 et l'extension : quand h2.0
// fait window.postMessage({type: "h2_open_evalweb", matricule: ...}),
// on transmet à background.js qui ouvre montreal.ca dans un onglet
// en arrière-plan. Depuis la 1.2.0 : messages h2_batch_* pour la
// COLLECTE EN LOT (démarrer, pause, reprise, arrêt, réessayer, état).

(function () {
  "use strict";

  const log = (...args) => console.log("[h2.0 Bridge]", ...args);

  // Marqueur que l'extension est installée — h2.0 peut le checker
  // pour savoir si elle peut compter sur le scraping auto (et sur la
  // collecte en lot à partir de 1.2.0).
  try {
    window.__h2_extension = "1.2.0";
  } catch (_) {}

  const BATCH_MESSAGES = {
    h2_batch_start: "BATCH_START",
    h2_batch_pause: "BATCH_PAUSE",
    h2_batch_resume: "BATCH_RESUME",
    h2_batch_stop: "BATCH_STOP",
    h2_batch_retry: "BATCH_RETRY",
    h2_batch_status: "BATCH_STATUS",
  };

  window.addEventListener("message", (event) => {
    // Ne traite que les messages venant de la même page (sécu)
    if (event.source !== window) return;
    const data = event.data;
    if (!data || typeof data !== "object") return;

    if (data.type === "h2_open_evalweb" && data.matricule) {
      log("Demande d'ouverture EvalWeb en arrière-plan:", data.matricule);
      chrome.runtime.sendMessage(
        {
          type: "OPEN_EVALWEB_BACKGROUND",
          matricule: data.matricule,
        },
        (response) => {
          // Renvoie un ack à h2.0
          window.postMessage(
            {
              type: "h2_open_evalweb_ack",
              matricule: data.matricule,
              ok: !!(response && response.ok),
            },
            "*"
          );
        }
      );
      return;
    }

    const type = BATCH_MESSAGES[data.type];
    if (type) {
      chrome.runtime.sendMessage(
        { type, matricules: data.matricules },
        (response) => {
          window.postMessage(
            {
              type: "h2_batch_state",
              state: (response && response.state) || null,
              error: (response && !response.ok && response.error) || null,
            },
            "*"
          );
        }
      );
    }
  });
})();
