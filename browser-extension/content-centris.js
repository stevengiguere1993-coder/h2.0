// Content script qui tourne sur centris.ca
// Détecte les fiches d'annonce (pages /fr/.../{mls_id}-...) et extrait
// les détails : prix, adresse, revenus bruts, nb logements, etc.

(function () {
  "use strict";

  const log = (...args) => console.log("[h2.0 Centris]", ...args);
  let lastSent = null;

  function isListingDetailPage() {
    // Les pages détail ont un MLS dans l'URL : /fr/.../{mls_id}-{slug}
    const m = window.location.pathname.match(/\/(\d{8})(?:-|$)/);
    return !!m;
  }

  function extractMlsId() {
    const m = window.location.pathname.match(/\/(\d{8})(?:-|$)/);
    return m ? m[1] : null;
  }

  function getText(selectors) {
    if (typeof selectors === "string") selectors = [selectors];
    for (const sel of selectors) {
      const el = document.querySelector(sel);
      if (el && el.textContent.trim()) return el.textContent.trim();
    }
    return null;
  }

  function parseNumber(text) {
    if (!text) return null;
    // Enlève espaces, $, virgules, garde les digits + .
    const clean = text.replace(/[\s$,]/g, "").replace(/,/g, ".");
    const n = parseFloat(clean);
    return isNaN(n) ? null : n;
  }

  function extractListing() {
    // Centris change régulièrement la structure DOM, on utilise les
    // attributs data-* / itemprop quand possible + fallback sélecteurs
    // textuels.
    const listing = {
      mls_id: extractMlsId(),
      url: window.location.href,
      address: getText([
        'h2[itemprop="address"]',
        ".address",
        "h2.text-left",
      ]),
      price: parseNumber(getText([
        '.price [itemprop="price"]',
        ".price-container",
        ".price",
      ])),
      category: getText([
        ".category",
        '[itemprop="category"]',
      ]),
    };

    // Détails financiers et physiques — itère sur les paires label/valeur
    const detailSections = document.querySelectorAll(
      ".carac-container, .description-container, .financial-details, .characteristics"
    );
    for (const section of detailSections) {
      const labels = section.querySelectorAll(
        ".carac-title, dt, strong, .financial-details-table-yearly-amount > .legend"
      );
      for (const label of labels) {
        const labelText = (label.textContent || "").trim();
        const valueEl =
          label.nextElementSibling ||
          label.parentElement.querySelector(".carac-value, dd, .value");
        const valueText = valueEl ? (valueEl.textContent || "").trim() : "";
        if (!labelText || !valueText) continue;
        mapDetailField(listing, labelText, valueText);
      }
    }

    // Description / remarques courtier
    const description = getText([
      "#description-text",
      ".description-text",
      '[itemprop="description"]',
    ]);
    if (description) listing.description = description.substring(0, 3000);

    // Courtier
    listing.broker_name = getText([
      ".broker-info .name",
      ".broker-name",
      ".broker h3",
    ]);
    listing.broker_phone = getText([
      ".broker-info .phone",
      ".broker-phone",
      'a[href^="tel:"]',
    ]);

    return listing;
  }

  function mapDetailField(listing, label, value) {
    const lower = label.toLowerCase();
    if (lower.includes("revenus bruts")) {
      listing.gross_revenue = parseNumber(value);
    } else if (lower.includes("nombre d'unités") || lower.includes("nb d'unités")) {
      listing.nb_units = parseInt(value.replace(/\D/g, ""), 10) || null;
    } else if (lower.includes("année de construction")) {
      const year = parseInt(value.replace(/\D/g, "").substring(0, 4), 10);
      if (year > 1800 && year < 2100) listing.year_built = year;
    } else if (lower.includes("superficie habitable")) {
      listing.living_area = parseNumber(value);
    } else if (lower.includes("superficie du terrain")) {
      listing.lot_area = parseNumber(value);
    } else if (lower.includes("évaluation municipale")) {
      listing.municipal_assessment = parseNumber(value);
    } else if (lower.includes("taxes municipales")) {
      listing.municipal_taxes = parseNumber(value);
    } else if (lower.includes("taxes scolaires")) {
      listing.school_taxes = parseNumber(value);
    } else if (lower.includes("matricule")) {
      const m = value.match(/(\d{4}-\d{2}-\d{4}-\d-\d{3}-\d{4})/);
      if (m) listing.matricule = m[1];
    }
  }

  async function sendToBackend(listing) {
    const hash = JSON.stringify(listing);
    if (hash === lastSent) return;
    lastSent = hash;

    log("Envoi backend :", listing);
    try {
      const response = await chrome.runtime.sendMessage({
        type: "POST_CENTRIS_LISTING",
        payload: listing,
      });
      log("Backend response :", response);
      showToast(
        response && response.ok
          ? `✅ Annonce ${listing.mls_id} envoyée à h2.0`
          : `⚠️ Échec : ${response && response.error || "erreur"}`
      );
    } catch (exc) {
      log("Erreur sendMessage :", exc);
    }
  }

  function showToast(message) {
    const existing = document.getElementById("h20-toast");
    if (existing) existing.remove();
    const toast = document.createElement("div");
    toast.id = "h20-toast";
    toast.textContent = message;
    toast.style.cssText = `
      position: fixed; top: 20px; right: 20px; z-index: 99999;
      background: #2c5530; color: white; padding: 12px 20px;
      border-radius: 8px; font-family: sans-serif; font-size: 14px;
      box-shadow: 0 4px 12px rgba(0,0,0,0.3); max-width: 320px;
    `;
    document.body.appendChild(toast);
    setTimeout(() => toast.remove(), 5000);
  }

  function tryScrape() {
    if (!isListingDetailPage()) return;
    const listing = extractListing();
    if (!listing.mls_id || !listing.address) {
      log("Listing incomplet, skip");
      return;
    }
    sendToBackend(listing);
  }

  // Centris est SSR + hydratation — laisse 2s pour que tout soit là
  setTimeout(tryScrape, 2000);

  // SPA navigation
  let lastUrl = window.location.href;
  setInterval(() => {
    if (window.location.href !== lastUrl) {
      lastUrl = window.location.href;
      lastSent = null;
      setTimeout(tryScrape, 2000);
    }
  }, 1500);
})();
