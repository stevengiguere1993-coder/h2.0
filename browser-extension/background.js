// Service worker en background — relais entre les content scripts et
// l'API h2.0. Stocke la config (URL backend + API key) dans chrome.storage.
// Les content scripts ne peuvent pas faire de fetch cross-origin direct
// vers le backend (CORS), donc on passe par le service worker.
//
// Depuis la 1.2.0 (Phil 2026-09-28) : COLLECTE EN LOT — la page
// Immeubles MTL envoie une liste de matricules ; le worker les traite un
// par un dans UN onglet montreal.ca en arrière-plan (rythme humain,
// pause/reprise, chien de garde, arrêt automatique après plusieurs
// échecs de suite). L'état vit dans chrome.storage → survit aux
// rechargements de la page Kratos et aux réveils du worker.

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

// ============== COLLECTE EN LOT ==============

const BATCH_KEY = "h2_batch";
const WATCHDOG_ALARM = "h2_batch_watchdog";
const NEXT_ALARM = "h2_batch_next";
// Rythme humain entre deux propriétés (6 à 11 s) — montreal.ca est un
// service public, on ne le martèle pas.
const DELAY_MIN_MS = 6000;
const DELAY_MAX_MS = 11000;
// Une propriété qui n'aboutit pas en 75 s est comptée en échec.
const WATCHDOG_MS = 75000;
// Au-delà, on se met en pause : le site bloque probablement.
const MAX_ECHECS_CONSECUTIFS = 6;
const MATRICULE_RE = /^\d{4}-\d{2}-\d{4}-\d-\d{3}-\d{4}$/;

async function getBatch() {
  const d = await chrome.storage.local.get([BATCH_KEY]);
  return d[BATCH_KEY] || null;
}

async function setBatch(b) {
  await chrome.storage.local.set({ [BATCH_KEY]: b });
  return b;
}

function batchPublic(b) {
  if (!b) {
    return {
      status: "idle", total: 0, index: 0, ok: 0, fail: 0,
      failures: [], nbFailures: 0, current: null, raison: null, startedAt: null,
    };
  }
  return {
    status: b.status,
    total: b.matricules.length,
    index: b.index,
    ok: b.ok,
    fail: b.fail,
    failures: b.failures.slice(-50),
    nbFailures: b.failures.length,
    current: b.current,
    raison: b.raison || null,
    startedAt: b.startedAt || null,
  };
}

async function fermerOngletLot(b) {
  if (b && b.tabId) {
    try {
      await chrome.tabs.remove(b.tabId);
    } catch (_) {
      /* déjà fermé */
    }
  }
}

async function batchStart(matricules) {
  const propres = [];
  const vus = new Set();
  for (const m of matricules || []) {
    if (typeof m === "string" && MATRICULE_RE.test(m) && !vus.has(m)) {
      vus.add(m);
      propres.push(m);
    }
  }
  if (!propres.length) return { ok: false, error: "Aucun matricule valide." };
  const ancien = await getBatch();
  if (ancien) await fermerOngletLot(ancien);
  const b = {
    matricules: propres,
    index: 0,
    ok: 0,
    fail: 0,
    failures: [],
    consecutifs: 0,
    status: "running",
    current: null,
    enCours: false,
    tabId: null,
    raison: null,
    startedAt: Date.now(),
  };
  await setBatch(b);
  log("Lot démarré :", propres.length, "matricules");
  await batchNext();
  return { ok: true, state: batchPublic(await getBatch()) };
}

async function batchNext() {
  const b = await getBatch();
  if (!b || b.status !== "running" || b.enCours) return;
  if (b.index >= b.matricules.length) {
    b.status = "done";
    b.current = null;
    await setBatch(b);
    await fermerOngletLot(b);
    log("Lot terminé :", b.ok, "trouvés,", b.fail, "échecs");
    return;
  }
  const m = b.matricules[b.index];
  b.current = m;
  b.enCours = true;
  const url = `https://montreal.ca/role-evaluation-fonciere?h2matricule=${encodeURIComponent(m)}`;
  // UN seul onglet, réutilisé d'une propriété à l'autre.
  let tab = null;
  if (b.tabId) {
    try {
      tab = await chrome.tabs.get(b.tabId);
    } catch (_) {
      tab = null;
    }
  }
  if (tab) {
    await chrome.tabs.update(tab.id, { url, active: false });
  } else {
    tab = await chrome.tabs.create({ url, active: false });
    b.tabId = tab.id;
  }
  await setBatch(b);
  chrome.alarms.create(WATCHDOG_ALARM, { when: Date.now() + WATCHDOG_MS });
  log("Lot :", b.index + 1, "/", b.matricules.length, "→", m);
}

async function batchItemDone(matricule, ok, raison) {
  const b = await getBatch();
  if (!b || b.status !== "running" || b.current !== matricule) return;
  chrome.alarms.clear(WATCHDOG_ALARM);
  if (ok) {
    b.ok += 1;
    b.consecutifs = 0;
  } else {
    b.fail += 1;
    b.consecutifs += 1;
    b.failures.push(matricule);
    log("Échec", matricule, raison || "");
  }
  b.index += 1;
  b.current = null;
  b.enCours = false;
  if (!ok && b.consecutifs >= MAX_ECHECS_CONSECUTIFS) {
    b.status = "paused";
    b.raison =
      `${MAX_ECHECS_CONSECUTIFS} échecs de suite (${raison || "montreal.ca ne répond plus ?"}) ` +
      "— la collecte s'est mise en pause, reprends-la plus tard.";
    await setBatch(b);
    return;
  }
  await setBatch(b);
  const delay = DELAY_MIN_MS + Math.random() * (DELAY_MAX_MS - DELAY_MIN_MS);
  // setTimeout suffit tant que le worker reste éveillé ; l'alarme est
  // le filet si Chrome l'endort entre-temps (batchNext ignore un
  // doublon grâce à enCours).
  setTimeout(() => {
    batchNext();
  }, delay);
  chrome.alarms.create(NEXT_ALARM, { when: Date.now() + delay + 30000 });
}

async function batchPause() {
  const b = await getBatch();
  if (b && b.status === "running") {
    b.status = "paused";
    b.raison = null;
    await setBatch(b);
  }
  return { ok: true, state: batchPublic(await getBatch()) };
}

async function batchResume() {
  const b = await getBatch();
  if (b && b.status === "paused") {
    b.status = "running";
    b.raison = null;
    b.consecutifs = 0;
    b.enCours = false;
    b.current = null;
    await setBatch(b);
    await batchNext();
  }
  return { ok: true, state: batchPublic(await getBatch()) };
}

async function batchStop() {
  const b = await getBatch();
  if (b) await fermerOngletLot(b);
  chrome.alarms.clear(WATCHDOG_ALARM);
  chrome.alarms.clear(NEXT_ALARM);
  await chrome.storage.local.remove(BATCH_KEY);
  return { ok: true, state: batchPublic(null) };
}

async function batchRetryFailures() {
  const b = await getBatch();
  if (!b || !b.failures.length) {
    return { ok: false, error: "Aucun échec à réessayer.", state: batchPublic(b) };
  }
  const nb = {
    ...b,
    matricules: b.failures.slice(),
    index: 0,
    ok: 0,
    fail: 0,
    failures: [],
    consecutifs: 0,
    status: "running",
    current: null,
    enCours: false,
    raison: null,
    startedAt: Date.now(),
  };
  await setBatch(nb);
  await batchNext();
  return { ok: true, state: batchPublic(await getBatch()) };
}

chrome.alarms.onAlarm.addListener(async (alarm) => {
  if (alarm.name === WATCHDOG_ALARM) {
    const b = await getBatch();
    if (b && b.status === "running" && b.current) {
      log("Chien de garde : délai dépassé pour", b.current);
      await batchItemDone(b.current, false, "délai dépassé");
    }
  } else if (alarm.name === NEXT_ALARM) {
    const b = await getBatch();
    if (b && b.status === "running" && !b.enCours) await batchNext();
  }
});

// Réveil du worker (redémarrage de Chrome, mise à jour) : un lot en
// cours repart de la propriété courante.
async function reprendreSiBesoin() {
  const b = await getBatch();
  if (b && b.status === "running") {
    b.enCours = false;
    b.current = null;
    await setBatch(b);
    await batchNext();
  }
}
chrome.runtime.onStartup.addListener(reprendreSiBesoin);
chrome.runtime.onInstalled.addListener(reprendreSiBesoin);

// ============== MESSAGES ==============

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type === "POST_EVALWEB_DATA") {
    postJson("/api/v1/extension/evalweb-owners", message.payload)
      .then((resp) => {
        const m = message.payload && message.payload.matricule;
        if (m) batchItemDone(m, !!resp.ok, resp.ok ? null : resp.error);
        sendResponse(resp);
      });
    return true; // async response
  }
  if (message.type === "EVALWEB_NOT_FOUND") {
    batchItemDone(message.matricule, false, message.raison || "aucun résultat")
      .then(() => sendResponse({ ok: true }));
    return true;
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
  if (message.type === "OPEN_EVALWEB_BACKGROUND") {
    // Ouvre montreal.ca dans un onglet en arrière-plan (active=false
    // → le focus reste sur l'onglet h2.0). L'extension va piloter le
    // flow là-dedans, scraper, et fermer l'onglet à la fin.
    const url = `https://montreal.ca/role-evaluation-fonciere?h2matricule=${encodeURIComponent(message.matricule)}`;
    chrome.tabs.create({ url, active: false }, (tab) => {
      log("Onglet EvalWeb créé en background (id=" + tab.id + ")");
      sendResponse({ ok: true, tabId: tab.id });
    });
    return true;
  }
  if (message.type === "CLOSE_THIS_TAB") {
    // Le content script demande à fermer son propre onglet (après
    // POST réussi). En collecte en lot, l'onglet est réutilisé : on ne
    // le ferme pas.
    if (sender.tab && sender.tab.id) {
      getBatch().then((b) => {
        if (b && b.status === "running" && b.tabId === sender.tab.id) {
          sendResponse({ ok: true, garde: true });
          return;
        }
        log("Fermeture onglet " + sender.tab.id);
        chrome.tabs.remove(sender.tab.id, () => {
          sendResponse({ ok: true });
        });
      });
      return true;
    }
    sendResponse({ ok: false, error: "no tab id" });
    return false;
  }
  if (message.type === "BATCH_START") {
    batchStart(message.matricules).then(sendResponse);
    return true;
  }
  if (message.type === "BATCH_PAUSE") {
    batchPause().then(sendResponse);
    return true;
  }
  if (message.type === "BATCH_RESUME") {
    batchResume().then(sendResponse);
    return true;
  }
  if (message.type === "BATCH_STOP") {
    batchStop().then(sendResponse);
    return true;
  }
  if (message.type === "BATCH_RETRY") {
    batchRetryFailures().then(sendResponse);
    return true;
  }
  if (message.type === "BATCH_STATUS") {
    getBatch().then((b) => sendResponse({ ok: true, state: batchPublic(b) }));
    return true;
  }
});

log("Service worker démarré");
