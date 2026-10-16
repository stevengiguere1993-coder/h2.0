// Popup de l'icône : état de la liaison avec Kratos + formulaire de
// dépannage (backend URL + API key). Depuis 1.2.1 la configuration vient
// d'une page Kratos (SET_CONFIG) ; depuis 1.3.1 le popup le dit clairement
// (Steven 2026-10-16).

const $ = (id) => document.getElementById(id);

async function load() {
  const data = await chrome.storage.local.get(["backendUrl", "apiKey"]);
  $("backendUrl").value = data.backendUrl || "";
  $("apiKey").value = data.apiKey || "";
  const etat = $("etat");
  if (data.backendUrl && data.apiKey) {
    etat.textContent = "Reliée à Kratos : " + data.backendUrl;
    etat.className = "status ok";
  } else {
    etat.textContent =
      "Pas encore reliée à Kratos : ouvre une page Kratos dans ce navigateur (voir ci-dessus), puis reviens ici.";
    etat.className = "status error";
  }
}

function showStatus(msg, ok) {
  const status = $("status");
  status.textContent = msg;
  status.className = "status " + (ok ? "ok" : "error");
}

async function save() {
  const backendUrl = $("backendUrl").value.trim();
  const apiKey = $("apiKey").value.trim();
  if (!backendUrl || !apiKey) {
    showStatus("Backend URL et API key requis", false);
    return;
  }
  await chrome.storage.local.set({ backendUrl, apiKey });
  showStatus("Configuration enregistrée", true);
}

async function test() {
  const response = await chrome.runtime.sendMessage({ type: "TEST_CONNECTION" });
  if (response && response.ok) {
    showStatus("✅ Connexion OK", true);
  } else {
    showStatus(
      `❌ ${(response && response.error) || "Erreur inconnue"}`,
      false
    );
  }
}

$("save").addEventListener("click", save);
$("test").addEventListener("click", test);

load();
