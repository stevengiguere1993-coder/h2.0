// Popup pour configurer backend URL + API key

const $ = (id) => document.getElementById(id);

async function load() {
  const data = await chrome.storage.local.get(["backendUrl", "apiKey"]);
  $("backendUrl").value = data.backendUrl || "";
  $("apiKey").value = data.apiKey || "";
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
