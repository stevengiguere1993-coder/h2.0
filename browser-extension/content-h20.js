// Content script qui tourne sur les pages h2.0 (frontend Render +
// localhost). Sert de bridge entre h2.0 et l'extension : quand h2.0
// fait window.postMessage({type: "h2_open_evalweb", matricule: ...}),
// on transmet à background.js qui ouvre montreal.ca dans un onglet
// en arrière-plan.

(function () {
  "use strict";

  const log = (...args) => console.log("[h2.0 Bridge]", ...args);

  // Marqueur que l'extension est installée — h2.0 peut le checker
  // pour savoir si elle peut compter sur le scraping auto.
  try {
    window.__h2_extension = "1.0.0";
  } catch (_) {}

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
    }
  });
})();
