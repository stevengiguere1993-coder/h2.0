// Service worker en background — relais entre les content scripts et
// l'API h2.0. Stocke la config (URL backend + API key) dans chrome.storage.
// Les content scripts ne peuvent pas faire de fetch cross-origin direct
// vers le backend (CORS), donc on passe par le service worker.

const log = (...args) => console.log("[h2.0 BG]", ...args);

async function getConfig() {
  const data = await chrome.storage.local.get(["backendUrl", "apiKey"]);
  return {
    backendUrl: data.backendUrl || "",
    apiKey: data.apiKey || "",
  };
}

async function postJson(path, payload) {
  const { backendUrl, apiKey } = await getConfig();
  if (!backendUrl) {
    return { ok: false, error: "Backend URL non configurée (clique l'icône extension)" };
  }
  if (!apiKey) {
    return { ok: false, error: "API key non configurée" };
  }
  const url = `${backendUrl.replace(/\/+$/, "")}${path}`;
  log("POST", url);
  try {
    const resp = await fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Extension-Key": apiKey,
      },
      body: JSON.stringify(payload),
    });
    const text = await resp.text();
    if (!resp.ok) {
      log("Backend error", resp.status, text);
      return {
        ok: false,
        error: `HTTP ${resp.status}: ${text.substring(0, 200)}`,
      };
    }
    let json = null;
    try {
      json = JSON.parse(text);
    } catch (_) {
      json = { raw: text };
    }
    return { ok: true, data: json };
  } catch (exc) {
    log("Network error", exc);
    return { ok: false, error: `Erreur réseau : ${exc.message}` };
  }
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type === "POST_EVALWEB_DATA") {
    postJson("/api/v1/extension/evalweb-owners", message.payload)
      .then(sendResponse);
    return true; // async response
  }
  if (message.type === "POST_CENTRIS_LISTING") {
    postJson("/api/v1/extension/centris-listing", message.payload)
      .then(sendResponse);
    return true;
  }
  if (message.type === "TEST_CONNECTION") {
    postJson("/api/v1/extension/ping", {})
      .then(sendResponse);
    return true;
  }
});

log("Service worker démarré");
