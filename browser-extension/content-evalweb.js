// Content script qui tourne sur montreal.ca/role-evaluation-fonciere/*
// Détecte la page « Résultat détaillé » (étape 4 du flow) et extrait
// les owners de la section « 2. Propriétaire ».

(function () {
  "use strict";

  const log = (...args) => console.log("[h2.0 EvalWeb]", ...args);

  // Évite de scraper plusieurs fois la même page
  let lastSent = null;

  function isResultDetailPage() {
    // Sur la fiche détaillée, on a « 1. Identification de l'unité »
    // et « 2. Propriétaire » comme h2 dans le DOM.
    const headers = document.querySelectorAll("h1, h2, h3");
    for (const h of headers) {
      if (h.textContent.includes("Propriétaire") ||
          h.textContent.includes("Identification de l'unité")) {
        return true;
      }
    }
    return false;
  }

  function extractMatricule() {
    // Cherche « Numéro de matricule » suivi de la valeur (format XXXX-XX-XXXX-X-XXX-XXXX)
    const text = document.body.innerText;
    const m = text.match(/(\d{4}-\d{2}-\d{4}-\d-\d{3}-\d{4})/);
    return m ? m[1] : null;
  }

  function extractIdentification() {
    // Section « 1. Identification de l'unité d'évaluation »
    const result = {};
    const labels = {
      address: ["Adresse"],
      arrondissement: ["Arrondissement"],
      lot_number: ["Numéro de lot"],
      matricule: ["Numéro de matricule"],
      utilisation: ["Utilisation prédominante"],
      voisinage: ["Numéro d'unité de voisinage"],
      compte_foncier: ["Numéro de compte foncier"],
    };
    for (const [key, syns] of Object.entries(labels)) {
      for (const syn of syns) {
        const value = findValueAfterLabel(syn);
        if (value) {
          result[key] = value;
          break;
        }
      }
    }
    return result;
  }

  function findValueAfterLabel(label) {
    // Trouve un élément contenant exactement le label, puis récupère
    // l'élément suivant qui contient la valeur.
    const allElements = document.querySelectorAll("dt, strong, b, h3, h4, span, p");
    for (const el of allElements) {
      const text = (el.textContent || "").trim();
      if (text === label || text === label + " :" || text === label + ":") {
        // Cherche la valeur dans le sibling, le parent, ou un dd
        let next = el.nextElementSibling;
        while (next) {
          const value = (next.textContent || "").trim();
          if (value && value !== label) return value;
          next = next.nextElementSibling;
        }
        // Fallback : parent.nextElementSibling (cas dt/dd ou label/value)
        if (el.parentElement) {
          const pNext = el.parentElement.nextElementSibling;
          if (pNext) {
            const value = (pNext.textContent || "").trim();
            if (value && value !== label) return value;
          }
        }
      }
    }
    return null;
  }

  function extractOwners() {
    // Section « 2. Propriétaire » — peut contenir plusieurs proprios
    const owners = [];
    const allText = document.body.innerText;

    // Trouve l'index de la section Propriétaire
    const propIdx = allText.indexOf("2. Propriétaire");
    if (propIdx < 0) return owners;

    // Coupe avant la section suivante (3. Caractéristiques, etc.)
    let endIdx = allText.length;
    for (const stop of [
      "3. Caractéristiques",
      "Caractéristiques de l'unité",
      "Valeurs au rôle",
      "Répartition fiscale",
      "Compte de taxes",
    ]) {
      const idx = allText.indexOf(stop, propIdx);
      if (idx > 0 && idx < endIdx) endIdx = idx;
    }

    const section = allText.substring(propIdx, endIdx);
    const lines = section
      .split("\n")
      .map(l => l.trim())
      .filter(l => l.length > 0);

    const labelMap = {
      Nom: "name",
      Statut: "statut",
      "Statut aux fins d'imposition scolaire": "statut",
      "Adresse postale": "postal_address",
      "Date d'inscription": "inscription_date",
      "Date d'inscription au rôle": "inscription_date",
      "Conditions particulières": "conditions",
      "Conditions particulières d'inscription": "conditions",
    };

    let current = {};
    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      const stripped = line.replace(/:\s*$/, "");
      const key = labelMap[stripped] || labelMap[line];
      if (key) {
        const value = lines[i + 1] || "";
        if (key === "name" && current.name) {
          owners.push(current);
          current = {};
        }
        current[key] = value;
        i++;
      }
    }
    if (current.name) owners.push(current);
    return owners;
  }

  async function sendToBackend(payload) {
    // Hash simple pour éviter le double envoi (page stable)
    const hash = JSON.stringify(payload);
    if (hash === lastSent) {
      log("Déjà envoyé, skip");
      return;
    }
    lastSent = hash;

    log("Envoi backend :", payload);
    try {
      const response = await chrome.runtime.sendMessage({
        type: "POST_EVALWEB_DATA",
        payload,
      });
      log("Backend response :", response);
      showToast(
        response && response.ok
          ? `✅ ${payload.owners.length} proprio(s) envoyé(s) à h2.0`
          : `⚠️ Échec envoi : ${response && response.error || "erreur"}`
      );
    } catch (exc) {
      log("Erreur sendMessage :", exc);
      showToast("⚠️ Extension : erreur communication");
    }
  }

  function showToast(message) {
    const existing = document.getElementById("h20-toast");
    if (existing) existing.remove();

    const toast = document.createElement("div");
    toast.id = "h20-toast";
    toast.style.cssText = `
      position: fixed; top: 20px; right: 20px; z-index: 99999;
      background: #2c5530; color: white; padding: 16px 20px;
      border-radius: 8px; font-family: sans-serif; font-size: 14px;
      box-shadow: 0 4px 16px rgba(0,0,0,0.4); max-width: 360px;
      cursor: pointer; line-height: 1.4;
      border: 2px solid #1a3a1d;
    `;
    const msgDiv = document.createElement("div");
    msgDiv.textContent = message;
    msgDiv.style.fontWeight = "600";
    const hint = document.createElement("div");
    hint.textContent = "(clic pour fermer)";
    hint.style.cssText = "font-size:11px;opacity:.7;margin-top:6px;";
    toast.appendChild(msgDiv);
    toast.appendChild(hint);
    toast.addEventListener("click", () => toast.remove());
    document.body.appendChild(toast);
    // Plus long : 30s au lieu de 5s
    setTimeout(() => toast.remove(), 30000);
  }

  function tryScrape() {
    if (!isResultDetailPage()) return;
    const matricule = extractMatricule();
    if (!matricule) {
      log("Aucun matricule trouvé sur la page");
      return;
    }
    const owners = extractOwners();
    const identification = extractIdentification();
    if (owners.length === 0) {
      log("Aucun owner trouvé sur la page");
      return;
    }
    sendToBackend({
      matricule,
      owners,
      identification,
      url: window.location.href,
      scraped_at: new Date().toISOString(),
    });
  }

  // Tente le scrape une fois la page rendue (Next.js + React SPA)
  setTimeout(tryScrape, 1500);

  // Re-tente si l'URL change (navigation SPA sans full reload)
  let lastUrl = window.location.href;
  setInterval(() => {
    if (window.location.href !== lastUrl) {
      lastUrl = window.location.href;
      lastSent = null;
      setTimeout(tryScrape, 1500);
    }
  }, 1000);
})();
