// Content script qui tourne sur montreal.ca/role-evaluation-fonciere/*
//
// Deux modes :
// 1. SCRAPE : sur la fiche détaillée (étape 4), extrait les owners
//    et POST à h2.0
// 2. AUTOPILOT : si l'URL contient ?h2matricule=XXXX-XX-XXXX-...,
//    le matricule est mémorisé en sessionStorage, et l'extension
//    fait automatiquement les clics + remplissages pour parcourir
//    le flow 4 étapes jusqu'à la fiche détaillée. Le scrape se
//    déclenche ensuite automatiquement (mode 1).

(function () {
  "use strict";

  const log = (...args) => console.log("[h2.0 EvalWeb]", ...args);

  // Évite de scraper plusieurs fois la même page
  let lastSent = null;

  // ============== AUTOPILOT ==============

  const STORAGE_KEY = "h2_target_matricule";

  function readUrlMatricule() {
    try {
      const params = new URLSearchParams(window.location.search);
      const m = params.get("h2matricule");
      if (m && /^\d{4}-\d{2}-\d{4}-\d-\d{3}-\d{4}$/.test(m)) return m;
    } catch (_) {}
    return null;
  }

  function getTargetMatricule() {
    // Si l'URL contient un nouveau matricule, on l'enregistre.
    const fromUrl = readUrlMatricule();
    if (fromUrl) {
      sessionStorage.setItem(STORAGE_KEY, fromUrl);
      return fromUrl;
    }
    return sessionStorage.getItem(STORAGE_KEY);
  }

  function clearTarget() {
    sessionStorage.removeItem(STORAGE_KEY);
  }

  function decomposeMatricule(matricule) {
    const parts = matricule.split("-");
    if (parts.length !== 6) return null;
    const [division, sector, location, cav, building, local] = parts;
    if (
      division.length !== 4 ||
      sector.length !== 2 ||
      location.length !== 4 ||
      cav.length !== 1 ||
      building.length !== 3 ||
      local.length !== 4
    ) {
      return null;
    }
    return { division, sector, location, cav, building, local };
  }

  function delay(ms) {
    return new Promise(r => setTimeout(r, ms));
  }

  function humanish(low, high) {
    return low + Math.random() * (high - low);
  }

  // Set la valeur d'un input React-controlled : il faut utiliser
  // le setter natif puis dispatch un event pour que React enregistre.
  function setReactInputValue(input, value) {
    const setter = Object.getOwnPropertyDescriptor(
      window.HTMLInputElement.prototype, "value"
    ).set;
    setter.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.dispatchEvent(new Event("change", { bubbles: true }));
  }

  async function autopilotStep1HomeAndOptions(matricule) {
    // Page d'accueil : sélectionner « Par matricule » + cliquer Suivant
    log("Autopilot étape 1 : sélection 'Par matricule'");
    // Cherche label « Par matricule » → trouve le radio associé via for=
    const labels = Array.from(document.querySelectorAll("label"));
    const targetLabel = labels.find(l =>
      l.textContent.trim().toLowerCase().includes("par matricule")
    );
    if (!targetLabel) {
      log("Label 'Par matricule' introuvable — peut-être déjà passé");
      return false;
    }
    const forAttr = targetLabel.getAttribute("for");
    if (forAttr) {
      const radio = document.getElementById(forAttr);
      if (radio) radio.click();
    } else {
      targetLabel.click();
    }
    await delay(humanish(500, 900));

    // Cherche le bouton Suivant
    const buttons = Array.from(document.querySelectorAll("button"));
    const suivant = buttons.find(b =>
      (b.textContent || "").trim().toLowerCase() === "suivant"
    );
    if (suivant) {
      log("Click Suivant");
      suivant.click();
      return true;
    }
    log("Bouton Suivant introuvable");
    return false;
  }

  async function autopilotStep2FillForm(matricule) {
    // Page form 6 sous-champs
    const parts = decomposeMatricule(matricule);
    if (!parts) {
      log("Matricule invalide:", matricule);
      return false;
    }
    log("Autopilot étape 2 : remplissage form pour", matricule);

    const fields = [
      ["division", parts.division],
      ["sector", parts.sector],
      ["location", parts.location],
      ["cav", parts.cav],
      ["building", parts.building],
      ["local", parts.local],
    ];
    for (const [name, value] of fields) {
      const input = document.querySelector(`input[name="${name}"]`);
      if (!input) {
        log(`Input [name=${name}] introuvable`);
        return false;
      }
      input.focus();
      setReactInputValue(input, value);
      await delay(humanish(150, 350));
    }
    await delay(humanish(800, 1500));

    const buttons = Array.from(document.querySelectorAll("button"));
    const rechercher = buttons.find(b =>
      (b.textContent || "").trim().toLowerCase() === "rechercher"
    );
    if (rechercher) {
      log("Click Rechercher");
      rechercher.click();
      return true;
    }
    log("Bouton Rechercher introuvable");
    return false;
  }

  async function autopilotStep3ClickResult(matricule) {
    // Page liste : clique le lien qui contient le matricule
    log("Autopilot étape 3 : recherche du résultat dans la liste");
    const candidates = Array.from(
      document.querySelectorAll("a, button, [role='link']")
    );
    const target = candidates.find(el =>
      (el.textContent || "").includes(matricule)
    );
    if (target) {
      log("Click résultat:", matricule);
      target.click();
      return true;
    }
    log("Lien matricule dans la liste introuvable");
    return false;
  }

  async function tryAutopilot() {
    const matricule = getTargetMatricule();
    if (!matricule) return;
    const url = window.location.pathname;
    log("Autopilot actif pour", matricule, "sur", url);

    // Détermine l'étape selon l'URL
    if (url.endsWith("/role-evaluation-fonciere") ||
        url.endsWith("/role-evaluation-fonciere/")) {
      // Étape 1 : page d'accueil
      await delay(humanish(800, 1500));
      await autopilotStep1HomeAndOptions(matricule);
    } else if (url.includes("/role-evaluation-fonciere/matricule") &&
               !url.includes("/liste") && !url.includes("/resultat")) {
      // Étape 2 : page form
      await delay(humanish(800, 1500));
      await autopilotStep2FillForm(matricule);
    } else if (url.includes("/matricule/liste")) {
      // Étape 3 : page liste
      await delay(humanish(1000, 1800));
      await autopilotStep3ClickResult(matricule);
    } else if (url.includes("/resultat") || url.includes("/detail")) {
      // Étape 4 : fiche détaillée — laisse le scraper faire son boulot.
      // On clear le target (autopilot terminé)
      clearTarget();
    }
  }

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

    // Trouve l'index de la section Propriétaire — multi-format
    let propIdx = allText.indexOf("2. Propriétaire");
    if (propIdx < 0) propIdx = allText.indexOf("Propriétaire");
    if (propIdx < 0) {
      log("Section 'Propriétaire' introuvable dans le texte");
      return owners;
    }

    // Coupe avant la section suivante (3. Caractéristiques, etc.)
    let endIdx = allText.length;
    for (const stop of [
      "3. Caractéristiques",
      "Caractéristiques de l'unité",
      "Valeurs au rôle",
      "Répartition fiscale",
      "Compte de taxes",
      "4. Valeurs",
    ]) {
      const idx = allText.indexOf(stop, propIdx + 10);
      if (idx > 0 && idx < endIdx) endIdx = idx;
    }

    const section = allText.substring(propIdx, endIdx);
    log("Section Propriétaire (longueur " + section.length + "):", section.substring(0, 500));

    const lines = section
      .split("\n")
      .map(l => l.trim())
      .filter(l => l.length > 0);

    const labelMap = {
      "Nom": "name",
      "Statut": "statut",
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
      const stripped = line.replace(/:\s*$/, "").trim();
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
    log("Owners extraits:", owners);
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
  setTimeout(() => {
    tryAutopilot();
    tryScrape();
  }, 1500);

  // Re-tente si l'URL change (navigation SPA sans full reload)
  let lastUrl = window.location.href;
  setInterval(() => {
    if (window.location.href !== lastUrl) {
      lastUrl = window.location.href;
      lastSent = null;
      setTimeout(() => {
        tryAutopilot();
        tryScrape();
      }, 1500);
    }
  }, 1000);
})();
