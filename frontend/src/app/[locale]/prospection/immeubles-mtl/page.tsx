"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Building2,
  CheckCircle2,
  Download,
  ExternalLink,
  Eye,
  Loader2,
  MapPin,
  Plus,
  Puzzle,
  RefreshCw,
  Search,
  Users,
  X
} from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { telechargerExport } from "@/components/immobilier/bouton-export";
import { authedFetch } from "@/lib/auth";
import { useConfirm } from "@/components/confirm-dialog";
import { useProspectionLayout } from "../layout";

type Property = {
  matricule: string;
  civique_debut: string | null;
  nom_rue: string | null;
  suite_debut: string | null;
  municipalite: string | null;
  nombre_logement: number | null;
  annee_construction: number | null;
  code_utilisation: string | null;
  libelle_utilisation: string | null;
  superficie_terrain: number | null;
  superficie_batiment: number | null;
  full_address: string | null;
  already_lead: boolean;
  has_owner_data: boolean;
  owner_names: string[] | null;
  owner_inscription_dates: string[] | null;
  //: « HLM · Saint-Sulpice », « Coop · propriétaire »… ; null = pas connu
  //: comme logement social.
  logement_social: string | null;
  //: Années écoulées depuis l'inscription du 1er propriétaire au rôle.
  proprietaire_depuis_annees: number | null;
};

type UtilisationType = {
  code: string;
  libelle: string | null;
  count: number;
};

type OwnerCandidate = {
  neq: string;
  nom: string | null;
  statut: string | null;
  forme_juridique: string | null;
  adresse: string | null;
  ville: string | null;
  code_postal: string | null;
  telephone: string | null;
};

type ListResponse = {
  total: number;
  properties: Property[];
};

//: État de la collecte en lot, tel que l'extension le renvoie.
type BatchState = {
  status: "idle" | "running" | "paused" | "done";
  total: number;
  index: number;
  ok: number;
  fail: number;
  failures: string[];
  nbFailures?: number;
  current: string | null;
  raison?: string | null;
  startedAt?: number | null;
};

//: Extension Chrome « Horizon h2.0 Helper » (collecte des propriétaires
//: sur montreal.ca) — zip servi par Kratos (Phil 2026-09-30 : lien de
//: téléchargement en haut à droite). Version = browser-extension/
//: manifest.json (vérifié par tests/test_extension_zip.py).
const EXTENSION_VERSION = "1.2.1";
const EXTENSION_ZIP = "/telechargements/extension-horizon-h2.zip";

//: Détection de l'extension (Phil 2026-09-29 : « Backend URL non
//: configurée ») : le content script vit dans un monde ISOLÉ — la page ne
//: voit pas window.__h2_extension. On la sonde par message : elle répond
//: à h2_batch_status (≥ 1.2.0). Résultat mémorisé pour le bouton
//: « Récupérer (auto) » de la fiche propriétaire.
let extensionDetectee = false;

function sonderExtension(delaiMs = 1200): Promise<boolean> {
  return new Promise((resolve) => {
    if (typeof window === "undefined") return resolve(false);
    let fini = false;
    const onMsg = (ev: MessageEvent) => {
      if (ev.source !== window) return;
      const t = (ev.data as { type?: string } | null)?.type;
      if (t === "h2_batch_state") {
        fini = true;
        window.removeEventListener("message", onMsg);
        extensionDetectee = true;
        resolve(true);
      }
    };
    window.addEventListener("message", onMsg);
    window.postMessage({ type: "h2_batch_status" }, "*");
    setTimeout(() => {
      if (!fini) {
        window.removeEventListener("message", onMsg);
        resolve(false);
      }
    }, delaiMs);
  });
}

//: Pousse l'adresse du serveur + la clé à l'extension ; « configuree » si
//: elle accuse réception (≥ 1.2.1), « ancienne » si elle répond aux
//: messages mais pas à la configuration, « absente » sinon.
type ExtStatut = "inconnue" | "absente" | "ancienne" | "configuree";

async function configurerExtensionDepuisKratos(): Promise<ExtStatut> {
  if (!(await sonderExtension())) return "absente";
  try {
    const r = await authedFetch("/api/v1/extension/config");
    if (!r.ok) return "ancienne";
    const d = (await r.json()) as {
      backend_url: string | null;
      api_key: string | null;
    };
    if (!d.backend_url || !d.api_key) return "ancienne";
    const ok = await new Promise<boolean>((resolve) => {
      let fini = false;
      const onMsg = (ev: MessageEvent) => {
        if (ev.source !== window) return;
        const m = ev.data as { type?: string; ok?: boolean } | null;
        if (m?.type === "h2_extension_config_ack") {
          fini = true;
          window.removeEventListener("message", onMsg);
          resolve(!!m.ok);
        }
      };
      window.addEventListener("message", onMsg);
      window.postMessage(
        {
          type: "h2_extension_config",
          backendUrl: d.backend_url,
          apiKey: d.api_key
        },
        window.location.origin
      );
      setTimeout(() => {
        if (!fini) {
          window.removeEventListener("message", onMsg);
          resolve(false);
        }
      }, 1500);
    });
    return ok ? "configuree" : "ancienne";
  } catch {
    return "ancienne";
  }
}

export default function ImmeublesMtlPage() {
  const { onOpenSidebar } = useProspectionLayout();
  const [properties, setProperties] = useState<Property[]>([]);
  const [total, setTotal] = useState(0);
  //: Unités retirées par « Exclure les logements sociaux » (null = case
  //: décochée) — affiché à côté du total.
  const [sociauxExclus, setSociauxExclus] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Filtres
  //: Taille = champs min / max logements seulement (Phil 2026-09-29 :
  //: « enlève le préréglage, base-toi juste sur min et max »). 8 par défaut.
  const [minLogements, setMinLogements] = useState<string>("8");
  const [maxLogements, setMaxLogements] = useState<string>("");
  //: Valeurs APPLIQUÉES (débouncées) des champs numériques. Taper « 12 »
  //: envoyait une requête pour « 1 » puis une pour « 12 » ; la première
  //: (lente, ~900 k lignes) revenait APRÈS la seconde et écrasait le
  //: résultat — « 6 donne 329, 12 en donne plus » (Phil 2026-09-22).
  const [filtresNum, setFiltresNum] = useState({
    minLogements: "8",
    maxLogements: "",
    minAnnee: "",
    maxAnnee: ""
  });
  //: Numéro de la dernière requête lancée : une réponse plus vieille est
  //: ignorée, et la requête précédente est annulée.
  const reqSeq = useRef(0);
  const abortRef = useRef<AbortController | null>(null);
  const [minAnnee, setMinAnnee] = useState<string>("");
  const [maxAnnee, setMaxAnnee] = useState<string>("");
  const [rueSearch, setRueSearch] = useState<string>("");
  // Valeur debouncée envoyée à l'API — évite un fetch par keystroke
  // quand l'utilisateur tape un nom de rue.
  const [rueSearchDebounced, setRueSearchDebounced] = useState<string>("");
  //: Numéro de porte (Phil 2026-09-29 : « disons 1660 ») — les plages
  //: « 1660-1672 » du rôle sont reconnues côté serveur.
  const [civiqueSearch, setCiviqueSearch] = useState<string>("");
  const [civiqueDebounced, setCiviqueDebounced] = useState<string>("");
  //: « Propriétaire depuis au moins N ans » (Phil 2026-09-29) — seulement
  //: les propriétaires déjà collectés (date d'inscription au rôle).
  const [proprioMinAns, setProprioMinAns] = useState<string>("");
  const [proprioMinAnsDebounced, setProprioMinAnsDebounced] =
    useState<string>("");
  const [sortBy, setSortBy] = useState("nombre_logement_desc");
  const [distanceBand, setDistanceBand] = useState<
    "" | "mtl_only" | "under_30" | "30_to_40" | "40_to_50" | "over_50"
  >("mtl_only");
  const [arrondissement, setArrondissement] = useState<string>("");
  const [arrondissementsList, setArrondissementsList] = useState<
    Array<{ name: string; count: number }>
  >([]);
  //: Exclure HLM / coops / OBNL / SHDM (Phil 2026-09-28) — coché par défaut :
  //: on prospecte des immeubles à acheter, jamais du logement social.
  const [exclureSociaux, setExclureSociaux] = useState(true);
  //: Exclure RPA / CHSLD (codes 1541, 1543, 1549) — Phil 2026-09-29 :
  //: « des maisons pour personnes retraitées, ça ne m'intéresse pas ».
  const [exclureAines, setExclureAines] = useState(true);
  const [offset, setOffset] = useState(0);
  const limit = 100;

  // Filtre utilisation : liste des codes disponibles (chargée 1×) +
  // ensemble des codes cochés pour la requête.
  const [utilTypes, setUtilTypes] = useState<UtilisationType[]>([]);
  const [selectedCodes, setSelectedCodes] = useState<Set<string>>(
    new Set()
  );
  const [showUtilFilter, setShowUtilFilter] = useState(false);

  // Owner candidates modal
  const [ownerModalFor, setOwnerModalFor] = useState<Property | null>(
    null
  );
  const [streetViewFor, setStreetViewFor] = useState<Property | null>(
    null
  );

  //: Retire min / max logements : chercher une adresse précise ne doit
  //: pas être bloqué par la taille (le 2420 Pie-IX, 8 logements, était
  //: caché par un minimum de 20).
  function retirerTaille() {
    setMinLogements("");
    setMaxLogements("");
    setFiltresNum((f) => ({ ...f, minLogements: "", maxLogements: "" }));
    setOffset(0);
  }

  //: Filtres courants → paramètres d'API (partagés par la liste et
  //: l'export CSV, sans limit/offset).
  const paramsFiltres = useCallback(() => {
    const params = new URLSearchParams();
    if (filtresNum.minLogements)
      params.set("min_logements", filtresNum.minLogements);
    if (filtresNum.maxLogements)
      params.set("max_logements", filtresNum.maxLogements);
    if (filtresNum.minAnnee) params.set("min_annee", filtresNum.minAnnee);
    if (filtresNum.maxAnnee) params.set("max_annee", filtresNum.maxAnnee);
    if (rueSearchDebounced.trim())
      params.set("nom_rue_contains", rueSearchDebounced.trim());
    if (civiqueDebounced.trim())
      params.set("numero_civique", civiqueDebounced.trim());
    if (proprioMinAnsDebounced.trim())
      params.set("proprietaire_min_annees", proprioMinAnsDebounced.trim());
    for (const code of selectedCodes) params.append("codes_utilisation", code);
    if (distanceBand) params.set("distance_band", distanceBand);
    if (arrondissement) params.set("arrondissement", arrondissement);
    if (exclureSociaux) params.set("exclure_sociaux", "true");
    if (exclureAines) params.set("exclure_residences_aines", "true");
    return params;
  }, [
    filtresNum,
    rueSearchDebounced,
    civiqueDebounced,
    proprioMinAnsDebounced,
    selectedCodes,
    distanceBand,
    arrondissement,
    exclureSociaux,
    exclureAines
  ]);

  // ── Collecte en lot des propriétaires (Phil 2026-09-28) ──
  const confirm = useConfirm();
  const [batch, setBatch] = useState<BatchState | null>(null);
  const [batchBusy, setBatchBusy] = useState(false);
  const [batchMsg, setBatchMsg] = useState<string | null>(null);
  const [batchMasque, setBatchMasque] = useState(false);
  const batchStatutPrec = useRef<string>("idle");

  // Réponses de l'extension (pont content-h20.js).
  useEffect(() => {
    function onMsg(ev: MessageEvent) {
      if (ev.source !== window) return;
      const d = ev.data as { type?: string; state?: BatchState | null; error?: string | null };
      if (d?.type !== "h2_batch_state") return;
      if (d.state) setBatch(d.state);
      if (d.error) setBatchMsg(d.error);
    }
    window.addEventListener("message", onMsg);
    return () => window.removeEventListener("message", onMsg);
  }, []);

  //: Extension : détectée par message et configurée depuis Kratos au
  //: chargement (plus rien à saisir dans la fenêtre de l'icône).
  const [extStatut, setExtStatut] = useState<ExtStatut>("inconnue");
  const configurerExtension = useCallback(async (): Promise<ExtStatut> => {
    const st = await configurerExtensionDepuisKratos();
    setExtStatut(st);
    return st;
  }, []);

  useEffect(() => {
    // content-h20 s'annonce au « document_idle » : petit délai.
    const id = setTimeout(() => void configurerExtension(), 800);
    return () => clearTimeout(id);
  }, [configurerExtension]);

  // État demandé toutes les 3 s une fois l'extension détectée (local).
  useEffect(() => {
    if (extStatut !== "configuree" && extStatut !== "ancienne") return;
    window.postMessage({ type: "h2_batch_status" }, "*");
    const id = setInterval(
      () => window.postMessage({ type: "h2_batch_status" }, "*"),
      3000
    );
    return () => clearInterval(id);
  }, [extStatut]);

  function batchCmd(cmd: "pause" | "resume" | "stop" | "retry") {
    window.postMessage({ type: `h2_batch_${cmd}` }, "*");
  }

  async function lancerCollecte() {
    const st = await configurerExtension();
    if (st === "absente") {
      setBatchMsg(
        "Extension Horizon non détectée : installe-la (Paramètres → Outils), puis recharge cette page."
      );
      return;
    }
    if (st === "ancienne") {
      setBatchMsg(
        "Extension trop ancienne : installe la version 1.2.1 (elle se configure toute seule depuis Kratos), puis recharge cette page."
      );
      return;
    }
    setBatchBusy(true);
    setBatchMsg(null);
    try {
      const p = paramsFiltres();
      p.set("sans_proprietaire", "true");
      const r = await authedFetch(
        `/api/v1/prospection/mtl-properties/matricules?${p}`
      );
      if (!r.ok) throw new Error((await r.text()).slice(0, 200) || `HTTP ${r.status}`);
      const d = (await r.json()) as {
        matricules: string[];
        total: number;
        deja_connus: number;
        plafond: number;
        tronque: boolean;
      };
      if (d.matricules.length === 0) {
        setBatchMsg(
          `Rien à collecter : les ${d.total.toLocaleString("fr-CA")} propriétés du filtre ont déjà un propriétaire connu.`
        );
        return;
      }
      const heures = (d.matricules.length * 9) / 3600;
      const duree =
        heures < 1
          ? `${Math.max(1, Math.round(heures * 60))} min`
          : `${Math.round(heures * 10) / 10} h`;
      const ok = await confirm({
        title: `Collecter ${d.matricules.length.toLocaleString("fr-CA")} propriétaires ?`,
        description:
          `${d.total.toLocaleString("fr-CA")} propriétés dans le filtre, ${d.deja_connus.toLocaleString("fr-CA")} déjà connues. ` +
          `L'extension consulte montreal.ca une propriété à la fois dans un onglet en arrière-plan, environ ${duree} avec Chrome ouvert. ` +
          `Pause possible à tout moment.` +
          (d.tronque
            ? ` Plafond de ${d.plafond.toLocaleString("fr-CA")} par lot : relance ensuite pour la suite.`
            : ""),
        confirmLabel: "Lancer la collecte"
      });
      if (!ok) return;
      setBatchMasque(false);
      window.postMessage(
        { type: "h2_batch_start", matricules: d.matricules },
        "*"
      );
    } catch (e) {
      setBatchMsg(`Collecte : ${(e as Error).message}`);
    } finally {
      setBatchBusy(false);
    }
  }

  const [exporting, setExporting] = useState(false);
  async function exporterCsv() {
    setExporting(true);
    setError(null);
    try {
      const p = paramsFiltres();
      await telechargerExport(
        `/api/v1/prospection/mtl-properties/export.csv?${p}`,
        `kratos_roles-fonciers_${new Date().toISOString().slice(0, 10)}.csv`
      );
    } catch (e) {
      setError(`Export : ${(e as Error).message}`);
    } finally {
      setExporting(false);
    }
  }

  const load = useCallback(async () => {
    const seq = ++reqSeq.current;
    abortRef.current?.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      if (filtresNum.minLogements)
        params.set("min_logements", filtresNum.minLogements);
      if (filtresNum.maxLogements)
        params.set("max_logements", filtresNum.maxLogements);
      if (filtresNum.minAnnee) params.set("min_annee", filtresNum.minAnnee);
      if (filtresNum.maxAnnee) params.set("max_annee", filtresNum.maxAnnee);
      if (rueSearchDebounced.trim())
        params.set("nom_rue_contains", rueSearchDebounced.trim());
      if (civiqueDebounced.trim())
        params.set("numero_civique", civiqueDebounced.trim());
      if (proprioMinAnsDebounced.trim())
        params.set("proprietaire_min_annees", proprioMinAnsDebounced.trim());
      // codes_utilisation : multi-valeur, FastAPI accepte
      // ?codes_utilisation=A&codes_utilisation=B
      for (const code of selectedCodes) {
        params.append("codes_utilisation", code);
      }
      params.set("sort_by", sortBy);
      if (distanceBand) params.set("distance_band", distanceBand);
      if (arrondissement) params.set("arrondissement", arrondissement);
      if (exclureSociaux) params.set("exclure_sociaux", "true");
      if (exclureAines) params.set("exclure_residences_aines", "true");
      params.set("limit", String(limit));
      params.set("offset", String(offset));

      const res = await authedFetch(
        `/api/v1/prospection/mtl-properties?${params}`,
        { signal: ctrl.signal }
      );
      if (!res.ok) {
        const t = await res.text();
        throw new Error(t.slice(0, 200) || `HTTP ${res.status}`);
      }
      const data = (await res.json()) as ListResponse;
      // Une réponse d'une requête plus ancienne n'écrase jamais la
      // dernière (les filtres ont changé entre-temps).
      if (seq !== reqSeq.current) return;
      setProperties(data.properties);
      setTotal(data.total);
      setSociauxExclus(
        (data as { sociaux_exclus?: number | null }).sociaux_exclus ?? null
      );
    } catch (e) {
      if ((e as Error).name === "AbortError") return;
      if (seq !== reqSeq.current) return;
      setError((e as Error).message);
    } finally {
      if (seq === reqSeq.current) setLoading(false);
    }
  }, [
    filtresNum,
    rueSearchDebounced,
    civiqueDebounced,
    proprioMinAnsDebounced,
    selectedCodes,
    sortBy,
    distanceBand,
    arrondissement,
    exclureSociaux,
    exclureAines,
    offset
  ]);

  // Debounce 350 ms : on déclenche le fetch seulement après que
  // l'utilisateur arrête de taper. Évite une requête par keystroke
  // sur la table de ~1 M unités.
  useEffect(() => {
    const id = setTimeout(() => {
      setRueSearchDebounced(rueSearch);
      setCiviqueDebounced(civiqueSearch);
      setProprioMinAnsDebounced(proprioMinAns);
      setOffset(0);
    }, 350);
    return () => clearTimeout(id);
  }, [rueSearch, civiqueSearch, proprioMinAns]);

  // Même délai pour les bornes numériques : on interroge la table (~1 M
  // lignes) une fois la saisie terminée, pas à chaque chiffre.
  useEffect(() => {
    const id = setTimeout(() => {
      setFiltresNum((f) =>
        f.minLogements === minLogements &&
        f.maxLogements === maxLogements &&
        f.minAnnee === minAnnee &&
        f.maxAnnee === maxAnnee
          ? f
          : { minLogements, maxLogements, minAnnee, maxAnnee }
      );
    }, 350);
    return () => clearTimeout(id);
  }, [minLogements, maxLogements, minAnnee, maxAnnee]);

  // Charge la liste des arrondissements de Montréal une fois au mount.
  useEffect(() => {
    void (async () => {
      try {
        const r = await authedFetch(
          `/api/v1/prospection/mtl-properties/arrondissements`
        );
        if (!r.ok) return;
        setArrondissementsList(
          (await r.json()) as Array<{ name: string; count: number }>
        );
      } catch {
        /* ignore */
      }
    })();
  }, []);

  // Charge la liste des types d'utilisation UNE SEULE FOIS au montage.
  // Anciennement re-fetché à chaque changement de minLogements, mais
  // l'endpoint fait un GROUP BY sur 1M+ lignes — coûteux. La liste
  // complète des codes change rarement (~après import), pas à chaque
  // ajustement de filtre.
  useEffect(() => {
    void (async () => {
      try {
        const r = await authedFetch(
          `/api/v1/prospection/mtl-properties/utilisation-types`
        );
        if (!r.ok) return;
        setUtilTypes((await r.json()) as UtilisationType[]);
      } catch {
        /* ignore */
      }
    })();
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // Fin d'un lot → la liste se rafraîchit (propriétaires visibles).
  useEffect(() => {
    const st = batch?.status || "idle";
    if (st === "done" && batchStatutPrec.current !== "done") void load();
    batchStatutPrec.current = st;
  }, [batch?.status, load]);

  const filteredCount = properties.length;
  const totalPages = Math.ceil(total / limit);
  const currentPage = Math.floor(offset / limit) + 1;

  function fmtArea(n: number | null): string {
    if (n == null) return "—";
    return `${Math.round(n).toLocaleString("fr-CA")} m²`;
  }

  return (
    <>
      <AppTopbar
        breadcrumbs={[
          { label: "Prospection", href: "/prospection" },
          { label: "Rôles fonciers" }
        ]}
        onOpenSidebar={onOpenSidebar}
      />

      <div className="p-4 lg:p-6">
        <header className="flex flex-wrap items-center gap-3">
          <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-accent-500/15 text-accent-500">
            <Building2 className="h-5 w-5" />
          </span>
          <div className="flex-1 min-w-0">
            <h1 className="text-2xl font-bold text-white">
              Rôles fonciers
            </h1>
            <p className="text-sm text-white/60">
              Filtre les unités d&apos;évaluation pour identifier des
              cibles d&apos;acquisition. Identifie le proprio (REQ) et
              convertis en lead en 1 clic.
            </p>
          </div>
          <button
            type="button"
            onClick={() => void exporterCsv()}
            disabled={exporting}
            title={`Télécharge en CSV (Excel) les ${total.toLocaleString("fr-CA")} propriétés qui matchent les filtres — avec les propriétaires déjà identifiés. Sans filtre : tout le Québec (gros fichier).`}
            className="inline-flex items-center gap-1.5 rounded-lg border border-brand-700 bg-brand-950 px-3 py-2 text-sm font-medium text-white transition hover:border-accent-500 disabled:opacity-60"
          >
            {exporting ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Download className="h-4 w-4" />
            )}
            {exporting ? "Export en cours…" : "Exporter en CSV"}
          </button>
          <button
            type="button"
            onClick={() => void lancerCollecte()}
            disabled={batchBusy || batch?.status === "running"}
            title="L'extension Horizon consulte montreal.ca pour chaque propriété du filtre sans propriétaire connu, une à la fois, en arrière-plan"
            className="inline-flex items-center gap-1.5 rounded-lg border border-emerald-500/50 bg-emerald-500/10 px-3 py-2 text-sm font-medium text-emerald-200 transition hover:border-emerald-400 disabled:opacity-60"
          >
            {batchBusy ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Users className="h-4 w-4" />
            )}
            Collecter les propriétaires
          </button>
          {extStatut === "configuree" ? (
            <span
              className="text-[11px] text-emerald-300"
              title="Kratos a transmis à l'extension l'adresse du serveur et sa clé"
            >
              Extension configurée
            </span>
          ) : extStatut === "ancienne" ? (
            <span className="text-[11px] text-amber-300">
              Extension à mettre à jour ({EXTENSION_VERSION})
            </span>
          ) : extStatut === "absente" ? (
            <span className="text-[11px] text-amber-300">
              Extension non détectée
            </span>
          ) : null}
          <a
            href={EXTENSION_ZIP}
            download={`extension-horizon-h2-${EXTENSION_VERSION}.zip`}
            title={`Extension Chrome Horizon ${EXTENSION_VERSION} (collecte des propriétaires). Installation : décompresse le zip → chrome://extensions → active « Mode développeur » → « Charger l'extension non empaquetée » → choisis le dossier extension-horizon-h2 → recharge cette page (elle se configure toute seule).`}
            className={`inline-flex items-center gap-1.5 rounded-lg border px-3 py-2 text-sm font-medium transition ${
              extStatut === "absente" || extStatut === "ancienne"
                ? "border-amber-400/60 bg-amber-500/10 text-amber-200 hover:border-amber-300"
                : "border-brand-700 bg-brand-950 text-white hover:border-accent-500"
            }`}
          >
            <Puzzle className="h-4 w-4" />
            Extension Chrome
            <span className="text-[10px] text-white/50">
              v{EXTENSION_VERSION}
            </span>
          </a>
        </header>

        {/* Filtres */}
        <section className="mt-6 rounded-2xl border border-brand-800 bg-brand-900 p-4">
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <div>
              <label className="label">Min logements</label>
              <input
                type="number"
                min="0"
                value={minLogements}
                onChange={(e) => {
                  setMinLogements(e.target.value);
                  setOffset(0);
                }}
                className="input text-sm"
              />
            </div>
            <div>
              <label className="label">Max logements</label>
              <input
                type="number"
                min="0"
                value={maxLogements}
                onChange={(e) => {
                  setMaxLogements(e.target.value);
                  setOffset(0);
                }}
                className="input text-sm"
              />
            </div>
            <div>
              <label className="label">Année de construction min</label>
              <input
                type="number"
                min="1700"
                max="2100"
                value={minAnnee}
                onChange={(e) => {
                  setMinAnnee(e.target.value);
                  setOffset(0);
                }}
                className="input text-sm"
              />
            </div>
            <div>
              <label className="label">Année de construction max</label>
              <input
                type="number"
                min="1700"
                max="2100"
                value={maxAnnee}
                onChange={(e) => {
                  setMaxAnnee(e.target.value);
                  setOffset(0);
                }}
                className="input text-sm"
              />
            </div>
            <div>
              <label className="label">Numéro civique</label>
              <input
                type="text"
                inputMode="numeric"
                value={civiqueSearch}
                onChange={(e) => {
                  const v = e.target.value;
                  setCiviqueSearch(v);
                  // Chercher UNE adresse : la taille ne doit pas la cacher.
                  if (v.trim() && (minLogements || maxLogements)) retirerTaille();
                }}
                placeholder="Ex : 1660"
                className="input text-sm"
                title="Numéro de porte — les plages du rôle (1660-1672) sont reconnues. Retire le filtre de taille pour trouver l'immeuble peu importe son nombre de logements."
              />
            </div>
            <div className="lg:col-span-2">
              <label className="label">Rue (ou adresse complète)</label>
              <div className="relative">
                <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-white/40" />
                <input
                  type="search"
                  value={rueSearch}
                  onChange={(e) => {
                    const v = e.target.value;
                    setRueSearch(v);
                    // « 2420 Pie-IX » = une adresse précise : taille retirée.
                    if (
                      /^\s*\d+\s*[,\s]\s*\S/.test(v) &&
                      (minLogements || maxLogements)
                    )
                      retirerTaille();
                  }}
                  placeholder="Ex : Pie-IX, St-Clément, 2420 Pie-IX…"
                  className="input pl-8 text-sm"
                />
              </div>
            </div>
            <div>
              <label className="label">Trier par</label>
              <select
                value={sortBy}
                onChange={(e) => setSortBy(e.target.value)}
                className="input text-sm"
              >
                <option value="nombre_logement_desc">
                  # logements ↓
                </option>
                <option value="nombre_logement_asc">
                  # logements ↑
                </option>
                <option value="annee_construction_asc">
                  Année construction ↑ (plus ancien d&apos;abord)
                </option>
                <option value="annee_construction_desc">
                  Année construction ↓
                </option>
                <option value="superficie_terrain_desc">
                  Superficie terrain ↓
                </option>
                <option value="matricule_asc">Matricule</option>
              </select>
            </div>
            {/* Zone + arrondissement + logements sociaux : dans la boîte
                avec les autres filtres (Phil 2026-09-28). */}
            <div>
              <label className="label">Zone</label>
              <select
                value={distanceBand}
                onChange={(e) => {
                  setDistanceBand(
                    e.target.value as
                      | ""
                      | "mtl_only"
                      | "under_30"
                      | "30_to_40"
                      | "40_to_50"
                      | "over_50"
                  );
                  setOffset(0);
                }}
                className="input text-sm"
                title="Distance depuis le centre-ville de Montréal"
              >
                <option value="">Tout le Québec</option>
                <option value="mtl_only">Île de Montréal uniquement</option>
                <option value="under_30">≤ 30 km de MTL</option>
                <option value="30_to_40">30-40 km de MTL</option>
                <option value="40_to_50">40-50 km de MTL</option>
                <option value="over_50">&gt; 50 km de MTL</option>
              </select>
            </div>
            <div>
              <label className="label">Arrondissement (Montréal)</label>
              <select
                value={arrondissement}
                onChange={(e) => {
                  setArrondissement(e.target.value);
                  setOffset(0);
                }}
                className="input text-sm"
                disabled={arrondissementsList.length === 0}
                title={
                  arrondissementsList.length === 0
                    ? "Aucun arrondissement en base : relance l'import du rôle Ville de Montréal (Paramètres → Sources)"
                    : "Arrondissement de la Ville de Montréal (les villes liées se filtrent par la zone)"
                }
              >
                <option value="">
                  {arrondissementsList.length === 0
                    ? "Aucun arrondissement en base"
                    : "Tous les arrondissements"}
                </option>
                {arrondissementsList.map((a) => (
                  <option key={a.name} value={a.name}>
                    {a.name} ({a.count.toLocaleString("fr-CA")})
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="label">Propriétaire depuis au moins (ans)</label>
              <input
                type="number"
                min="0"
                max="100"
                value={proprioMinAns}
                onChange={(e) => setProprioMinAns(e.target.value)}
                placeholder="Ex : 5"
                className="input text-sm"
                title="Date d'inscription du propriétaire au rôle : connue seulement pour les immeubles dont le propriétaire a été collecté (bouton « Collecter les propriétaires »)."
              />
              <p className="mt-1 text-[10px] text-white/40">
                Propriétaires déjà collectés seulement.
              </p>
            </div>
            <div className="flex items-end">
              <label className="flex w-full cursor-pointer items-center gap-2 rounded-lg border border-brand-800 bg-brand-950/60 px-3 py-2 text-sm text-white/80">
                <input
                  type="checkbox"
                  checked={exclureSociaux}
                  onChange={(e) => {
                    setExclureSociaux(e.target.checked);
                    setOffset(0);
                  }}
                  className="h-4 w-4 accent-accent-500"
                />
                <span>
                  Exclure les logements sociaux
                  <span className="block text-[10px] text-white/40">
                    HLM, OMHM, SHDM, coops, OBNL
                  </span>
                </span>
              </label>
            </div>
            <div className="flex items-end">
              <label className="flex w-full cursor-pointer items-center gap-2 rounded-lg border border-brand-800 bg-brand-950/60 px-3 py-2 text-sm text-white/80">
                <input
                  type="checkbox"
                  checked={exclureAines}
                  onChange={(e) => {
                    setExclureAines(e.target.checked);
                    setOffset(0);
                  }}
                  className="h-4 w-4 accent-accent-500"
                />
                <span>
                  Exclure les résidences pour aînés
                  <span className="block text-[10px] text-white/40">
                    RPA et CHSLD (utilisation du rôle)
                  </span>
                </span>
              </label>
            </div>
          </div>

          {/* Filtre Type d'utilisation (collapse + checkboxes) */}
          <div className="mt-3 border-t border-brand-800 pt-3">
            <button
              type="button"
              onClick={() => setShowUtilFilter((v) => !v)}
              className="flex w-full items-center justify-between text-sm text-white/80 hover:text-accent-500"
            >
              <span className="font-medium">
                Type d&apos;utilisation
                {selectedCodes.size > 0 ? (
                  <span className="badge badge-neutral ml-2">
                    {selectedCodes.size} cochés
                  </span>
                ) : (
                  <span className="ml-2 text-xs text-white/40">
                    (tous)
                  </span>
                )}
              </span>
              <span className="text-xs text-white/50">
                {showUtilFilter ? "Replier ▲" : "Déplier ▼"}
              </span>
            </button>
            {/* Raccourcis (Phil 2026-09-29) — la colonne « Utilisation »
                de l'export vient du rôle : connue pour toutes les unités. */}
            <div className="mt-2 flex flex-wrap items-center gap-2 text-[11px]">
              <span className="text-white/50">Raccourcis :</span>
              {(
                [
                  ["Logement seulement", ["1000"]],
                  ["Tous les types", []]
                ] as Array<[string, string[]]>
              ).map(([label, codes]) => {
                const actif =
                  selectedCodes.size === codes.length &&
                  codes.every((c) => selectedCodes.has(c));
                return (
                  <button
                    key={label}
                    type="button"
                    onClick={() => {
                      setSelectedCodes(new Set(codes));
                      setOffset(0);
                    }}
                    className={`rounded-full px-3 py-1 ${
                      actif
                        ? "bg-accent-500/20 text-accent-300"
                        : "bg-brand-800 text-white/60 hover:text-white"
                    }`}
                  >
                    {label}
                  </button>
                );
              })}
            </div>

            {showUtilFilter ? (
              <div className="mt-3 space-y-2">
                {selectedCodes.size > 0 ? (
                  <button
                    type="button"
                    onClick={() => {
                      setSelectedCodes(new Set());
                      setOffset(0);
                    }}
                    className="text-[11px] text-rose-300 hover:text-rose-200"
                  >
                    × Effacer la sélection ({selectedCodes.size})
                  </button>
                ) : null}
                <div className="grid max-h-72 grid-cols-1 gap-1.5 overflow-y-auto rounded-md border border-brand-800 bg-brand-950 p-2 sm:grid-cols-2 lg:grid-cols-3">
                  {utilTypes.length === 0 ? (
                    <p className="col-span-full text-xs text-white/40">
                      Aucun type chargé. Vérifie que les données MTL
                      sont importées.
                    </p>
                  ) : (
                    utilTypes.map((t) => {
                      const checked = selectedCodes.has(t.code);
                      return (
                        <label
                          key={t.code}
                          className={`flex cursor-pointer items-center gap-2 rounded px-2 py-1 text-[11px] transition ${
                            checked
                              ? "bg-brand-900 text-white"
                              : "text-white/70 hover:bg-brand-900"
                          }`}
                        >
                          <input
                            type="checkbox"
                            checked={checked}
                            onChange={(e) => {
                              const next = new Set(selectedCodes);
                              if (e.target.checked) next.add(t.code);
                              else next.delete(t.code);
                              setSelectedCodes(next);
                              setOffset(0);
                            }}
                            className="h-3.5 w-3.5 rounded border-brand-700 bg-brand-900 text-accent-500 focus:ring-accent-500"
                          />
                          <span className="flex-1 truncate">
                            <span className="font-mono text-[10px] text-white/40">
                              {t.code}
                            </span>{" "}
                            {t.libelle || "(sans libellé)"}
                          </span>
                          <span className="shrink-0 text-[10px] text-white/40">
                            {t.count.toLocaleString("fr-CA")}
                          </span>
                        </label>
                      );
                    })
                  )}
                </div>
              </div>
            ) : null}
          </div>
        </section>

        {/* Stats + pagination */}
        <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
          <p className="text-xs text-white/60">
            {loading ? (
              <Loader2 className="inline h-3 w-3 animate-spin" />
            ) : (
              <>
                <span className="font-bold text-emerald-300">
                  {total.toLocaleString("fr-CA")}
                </span>{" "}
                propriété{total > 1 ? "s" : ""} matchent les filtres ·
                affichage {offset + 1}-{offset + filteredCount}
                {sociauxExclus != null ? (
                  <span className="text-white/50">
                    {" "}
                    · {sociauxExclus.toLocaleString("fr-CA")}{" "}
                    {sociauxExclus > 1
                      ? "logements sociaux exclus"
                      : "logement social exclu"}
                  </span>
                ) : null}
              </>
            )}
          </p>
          {totalPages > 1 ? (
            <div className="flex items-center gap-2 text-xs">
              <button
                type="button"
                disabled={offset === 0}
                onClick={() => setOffset(Math.max(0, offset - limit))}
                className="btn-secondary btn-xs disabled:opacity-30"
              >
                ← Précédent
              </button>
              <span className="text-white/50">
                Page {currentPage} / {totalPages}
              </span>
              <button
                type="button"
                disabled={offset + limit >= total}
                onClick={() => setOffset(offset + limit)}
                className="btn-secondary btn-xs disabled:opacity-30"
              >
                Suivant →
              </button>
            </div>
          ) : null}
        </div>

        {batchMsg ? (
          <p className="mb-3 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
            {batchMsg}
            <button
              type="button"
              onClick={() => setBatchMsg(null)}
              className="ml-2 underline hover:text-white"
            >
              fermer
            </button>
          </p>
        ) : null}
        {batch && batch.status !== "idle" && !batchMasque ? (
          <div className="fixed bottom-4 right-4 z-[900] w-[340px] rounded-xl border border-emerald-500/40 bg-brand-950/95 p-3 shadow-2xl backdrop-blur">
            <div className="flex items-center justify-between gap-2">
              <p className="text-[11px] font-semibold uppercase tracking-wider text-emerald-300">
                Collecte des propriétaires
                {batch.status === "running"
                  ? " · en cours"
                  : batch.status === "paused"
                    ? " · en pause"
                    : " · terminée"}
              </p>
              <button
                type="button"
                onClick={() => setBatchMasque(true)}
                className="text-[10px] text-white/50 hover:text-white"
                title="Masquer (la collecte continue)"
              >
                masquer
              </button>
            </div>
            <div className="mt-2 h-1.5 w-full overflow-hidden rounded bg-white/10">
              <div
                className="h-full bg-emerald-400 transition-all"
                style={{
                  width: `${batch.total > 0 ? Math.round((batch.index / batch.total) * 100) : 0}%`
                }}
              />
            </div>
            <p className="mt-1.5 font-mono text-[11px] text-white/80">
              {batch.index.toLocaleString("fr-CA")} / {batch.total.toLocaleString("fr-CA")} ·{" "}
              <span className="text-emerald-300">{batch.ok} trouvés</span> ·{" "}
              <span className={batch.fail > 0 ? "text-amber-300" : "text-white/50"}>
                {batch.fail} échecs
              </span>
            </p>
            {batch.current ? (
              <p className="mt-0.5 truncate font-mono text-[10px] text-white/40">
                en cours : {batch.current}
              </p>
            ) : null}
            {batch.raison ? (
              <p className="mt-1.5 rounded border border-amber-500/40 bg-amber-500/10 px-2 py-1 text-[10px] text-amber-200">
                {batch.raison}
              </p>
            ) : null}
            <div className="mt-2 flex flex-wrap items-center gap-1.5">
              {batch.status === "running" ? (
                <button type="button" onClick={() => batchCmd("pause")} className="btn-secondary btn-xs">
                  Pause
                </button>
              ) : null}
              {batch.status === "paused" ? (
                <button type="button" onClick={() => batchCmd("resume")} className="btn-accent btn-xs">
                  Reprendre
                </button>
              ) : null}
              {(batch.nbFailures ?? batch.failures.length) > 0 && batch.status !== "running" ? (
                <button
                  type="button"
                  onClick={() => batchCmd("retry")}
                  className="btn-secondary btn-xs"
                  title="Relance seulement les propriétés en échec"
                >
                  Réessayer les échecs ({batch.nbFailures ?? batch.failures.length})
                </button>
              ) : null}
              {batch.status === "done" ? (
                <button type="button" onClick={() => void load()} className="btn-secondary btn-xs">
                  Actualiser la liste
                </button>
              ) : null}
              <button
                type="button"
                onClick={() => batchCmd("stop")}
                className="btn-ghost btn-xs text-rose-300"
                title={batch.status === "done" ? "Effacer ce suivi" : "Arrêter la collecte (l'onglet montreal.ca se ferme)"}
              >
                {batch.status === "done" ? "Fermer" : "Arrêter"}
              </button>
            </div>
          </div>
        ) : null}
        {error ? (
          <p className="mt-3 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">
            {error}
            {error.includes("500") || error.includes("serveur") ? (
              <span className="mt-1 block text-xs text-rose-200">
                Le rôle Montréal n&apos;est peut-être pas encore importé
                en DB. Lance{" "}
                <code className="rounded bg-rose-500/20 px-1">
                  python -m scripts.import_montreal_roles
                </code>{" "}
                depuis le Render Shell.
              </span>
            ) : null}
          </p>
        ) : null}

        {/* Tableau */}
        <div className="mt-4 overflow-hidden rounded-xl border border-brand-800 bg-brand-900">
          {loading && properties.length === 0 ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="h-6 w-6 animate-spin text-accent-500" />
            </div>
          ) : properties.length === 0 ? (
            <div className="p-12 text-center">
              <Building2 className="mx-auto h-8 w-8 text-white/20" />
              <p className="mt-3 text-sm text-white/50">
                Aucune propriété ne correspond aux filtres.
              </p>
              {proprioMinAnsDebounced.trim() ? (
                <p className="mt-1 text-[11px] text-amber-300/80">
                  « Propriétaire depuis » ne garde que les immeubles dont le
                  propriétaire a déjà été collecté (bouton « Collecter les
                  propriétaires »).
                </p>
              ) : null}
              {filtresNum.minLogements || filtresNum.maxLogements || exclureSociaux ? (
                <div className="mt-2 flex flex-wrap items-center justify-center gap-2 text-[11px] text-white/60">
                  <span>
                    Un filtre peut cacher l&apos;immeuble cherché
                    {filtresNum.minLogements || filtresNum.maxLogements
                      ? ` (taille : ${filtresNum.minLogements || "0"} à ${
                          filtresNum.maxLogements || "∞"
                        } logements)`
                      : ""}
                    {exclureSociaux ? " · logements sociaux exclus" : ""}.
                  </span>
                  {filtresNum.minLogements || filtresNum.maxLogements ? (
                    <button
                      type="button"
                      onClick={() => retirerTaille()}
                      className="rounded-md border border-brand-700 px-2 py-1 text-white/80 hover:border-accent-500"
                    >
                      Retirer min / max logements
                    </button>
                  ) : null}
                </div>
              ) : null}
              <p className="mt-1 text-[11px] text-white/40">
                Si la table est vide, il faut d&apos;abord importer le
                rôle Montréal (voir Sources de données).
              </p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-brand-950/60 text-left text-[11px] uppercase tracking-wider text-white/50">
                  <tr>
                    <th className="px-3 py-2.5">Adresse</th>
                    <th className="px-3 py-2.5">Propriétaire</th>
                    <th className="px-3 py-2.5 text-right">
                      # logements
                    </th>
                    <th className="px-3 py-2.5 text-right">Construit en</th>
                    <th className="px-3 py-2.5 text-right">Terrain</th>
                    <th className="px-3 py-2.5">Utilisation</th>
                    <th className="px-3 py-2.5">Matricule</th>
                    <th className="px-3 py-2.5 text-right">Propriétaire depuis</th>
                    <th className="px-3 py-2.5">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-brand-800">
                  {properties.map((p) => (
                    <tr
                      key={p.matricule}
                      className="transition hover:bg-brand-800/40"
                    >
                      <td className="px-3 py-2.5 text-white/80">
                        <button
                          type="button"
                          onClick={() => setStreetViewFor(p)}
                          className="text-left hover:text-accent-500 hover:underline"
                          title="Ouvrir Street View"
                        >
                          {p.full_address || "—"}
                        </button>
                        {p.municipalite ? (
                          <div className="text-[10px] text-white/40">
                            {p.municipalite}
                          </div>
                        ) : null}
                        {p.logement_social ? (
                          <span
                            className="mt-0.5 inline-block rounded bg-rose-500/15 px-1.5 py-0.5 text-[10px] font-medium text-rose-300"
                            title="Logement social ou communautaire — exclu quand la case « Exclure les logements sociaux » est cochée"
                          >
                            Social · {p.logement_social}
                          </span>
                        ) : null}
                      </td>
                      <td className="px-3 py-2.5 max-w-[180px]">
                        {p.owner_names && p.owner_names.length > 0 ? (
                          <button
                            type="button"
                            onClick={() => setOwnerModalFor(p)}
                            className="text-left text-[11px] text-accent-500 hover:text-accent-400 hover:underline"
                            title="Voir les détails du propriétaire"
                          >
                            {p.owner_names.length === 1 ? (
                              <span className="line-clamp-2">
                                {p.owner_names[0]}
                              </span>
                            ) : (
                              <span>
                                <span className="line-clamp-1">
                                  {p.owner_names[0]}
                                </span>
                                <span className="text-[10px] text-white/40">
                                  +{p.owner_names.length - 1} autre
                                  {p.owner_names.length > 2 ? "s" : ""}
                                </span>
                              </span>
                            )}
                          </button>
                        ) : (
                          <span className="text-[11px] text-white/30">—</span>
                        )}
                      </td>
                      <td className="px-3 py-2.5 text-right tabular-nums font-bold text-emerald-300">
                        {p.nombre_logement ?? "—"}
                      </td>
                      <td className="px-3 py-2.5 text-right tabular-nums text-white/70">
                        {p.annee_construction ?? "—"}
                      </td>
                      <td className="px-3 py-2.5 text-right tabular-nums text-white/70">
                        {fmtArea(p.superficie_terrain)}
                      </td>
                      <td className="px-3 py-2.5 text-[11px] text-white/60">
                        {p.libelle_utilisation || "—"}
                      </td>
                      <td className="px-3 py-2.5 font-mono text-[10px] text-white/40">
                        {p.matricule}
                      </td>
                      <td className="px-3 py-2.5 text-right text-[11px] tabular-nums text-white/60">
                        {p.owner_inscription_dates &&
                        p.owner_inscription_dates[0] ? (
                          <span
                            title={`Inscrit au rôle le ${p.owner_inscription_dates[0]}`}
                          >
                            {p.proprietaire_depuis_annees != null ? (
                              <span className="font-medium text-white/80">
                                {p.proprietaire_depuis_annees === 0
                                  ? "moins d'un an"
                                  : `${p.proprietaire_depuis_annees} an${
                                      p.proprietaire_depuis_annees > 1 ? "s" : ""
                                    }`}
                              </span>
                            ) : null}
                            <span className="block text-[10px] text-white/40">
                              {p.owner_inscription_dates[0]}
                            </span>
                          </span>
                        ) : (
                          <span className="text-white/30">—</span>
                        )}
                      </td>
                      <td className="px-3 py-2.5">
                        <div className="flex flex-wrap gap-1">
                          <button
                            type="button"
                            onClick={() => setStreetViewFor(p)}
                            className="inline-flex items-center gap-1 rounded-md border border-amber-500/40 bg-amber-500/10 px-2 py-1 text-[10px] text-amber-300 hover:bg-amber-500/20"
                            title="Street View"
                          >
                            <Eye className="h-3 w-3" />
                            Voir
                          </button>
                          <button
                            type="button"
                            onClick={() => setOwnerModalFor(p)}
                            className={`inline-flex items-center gap-1 rounded-md border px-2 py-1 text-[10px] ${
                              p.has_owner_data
                                ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-300 hover:bg-emerald-500/20"
                                : "border-blue-500/40 bg-blue-500/10 text-blue-300 hover:bg-blue-500/20"
                            }`}
                            title={
                              p.has_owner_data
                                ? "Propriétaires déjà documentés — clic pour voir"
                                : "Documenter les propriétaires"
                            }
                          >
                            {p.has_owner_data ? (
                              <CheckCircle2 className="h-3 w-3" />
                            ) : (
                              <Users className="h-3 w-3" />
                            )}
                            Proprio
                          </button>
                          {p.already_lead ? (
                            <span className="inline-flex items-center gap-1 rounded-md border border-emerald-500/40 bg-emerald-500/10 px-2 py-1 text-[10px] text-emerald-300">
                              <CheckCircle2 className="h-3 w-3" />
                              Lead
                            </span>
                          ) : (
                            <ConvertButton property={p} />
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>

      {ownerModalFor ? (
        <OwnerCandidatesModal
          property={ownerModalFor}
          onClose={() => setOwnerModalFor(null)}
          onConverted={() => {
            setOwnerModalFor(null);
            void load();
          }}
        />
      ) : null}

      {streetViewFor ? (
        <StreetViewModal
          property={streetViewFor}
          onClose={() => setStreetViewFor(null)}
        />
      ) : null}
    </>
  );
}

function StreetViewModal({
  property,
  onClose
}: {
  property: Property;
  onClose: () => void;
}) {
  const fullAddr = property.full_address || "";
  // svembed = iframe Google Maps lite, pas besoin de clé API.
  // L'address suffit comme paramètre de recherche.
  const svSrc = `https://maps.google.com/maps?q=${encodeURIComponent(
    fullAddr + ", Montréal, QC"
  )}&layer=c&output=svembed`;
  const satSrc = `https://maps.google.com/maps?q=${encodeURIComponent(
    fullAddr + ", Montréal, QC"
  )}&t=k&z=19&output=embed`;
  const gmapsUrl = `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(
    fullAddr + ", Montréal, QC"
  )}`;

  return (
    <div
      onClick={onClose}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-4 backdrop-blur-sm"
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-4xl overflow-hidden rounded-2xl border border-brand-800 bg-brand-950"
      >
        <div className="flex items-start justify-between gap-3 border-b border-brand-800 bg-brand-900/50 px-5 py-3">
          <div>
            <h2 className="flex items-center gap-2 text-base font-bold text-white">
              <Eye className="h-5 w-5 text-amber-400" />
              {fullAddr}
            </h2>
            <p className="mt-0.5 text-[11px] text-white/50">
              Matricule {property.matricule} ·{" "}
              {property.nombre_logement ?? "?"} logements
              {property.annee_construction
                ? ` · ${property.annee_construction}`
                : ""}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="btn-ghost btn-xs"
            aria-label="Fermer"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="grid gap-2 p-3 sm:grid-cols-2">
          <div className="overflow-hidden rounded-lg border border-brand-800 bg-black">
            <p className="border-b border-brand-800 bg-brand-900/40 px-3 py-1.5 text-[11px] uppercase tracking-wider text-amber-300">
              Street View
            </p>
            <iframe
              src={svSrc}
              className="h-72 w-full"
              loading="lazy"
              referrerPolicy="no-referrer-when-downgrade"
              title="Street View"
            />
          </div>
          <div className="overflow-hidden rounded-lg border border-brand-800 bg-black">
            <p className="border-b border-brand-800 bg-brand-900/40 px-3 py-1.5 text-[11px] uppercase tracking-wider text-accent-500">
              Vue satellite
            </p>
            <iframe
              src={satSrc}
              className="h-72 w-full"
              loading="lazy"
              referrerPolicy="no-referrer-when-downgrade"
              title="Satellite"
            />
          </div>
        </div>

        <div className="flex flex-wrap items-center justify-end gap-2 border-t border-brand-800 bg-brand-900/30 px-5 py-3">
          <a
            href={gmapsUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="btn-secondary btn-sm"
          >
            <ExternalLink className="h-3 w-3" />
            Ouvrir dans Google Maps
          </a>
        </div>
      </div>
    </div>
  );
}

function ConvertButton({ property }: { property: Property }) {
  const [busy, setBusy] = useState(false);
  async function convert() {
    if (busy) return;
    setBusy(true);
    try {
      const res = await authedFetch(
        `/api/v1/prospection/mtl-properties/${encodeURIComponent(
          property.matricule
        )}/convert-to-lead`,
        { method: "POST" }
      );
      if (!res.ok) {
        const t = await res.text();
        alert(t.slice(0, 200) || `HTTP ${res.status}`);
        return;
      }
      const data = (await res.json()) as { lead_id: number };
      window.location.href = `/prospection/${data.lead_id}`;
    } finally {
      setBusy(false);
    }
  }
  return (
    <button
      type="button"
      onClick={convert}
      disabled={busy}
      className="inline-flex items-center gap-1 rounded-md border border-emerald-500/40 bg-emerald-500/10 px-2 py-1 text-[10px] text-emerald-300 hover:bg-emerald-500/20 disabled:opacity-50"
    >
      {busy ? (
        <Loader2 className="h-3 w-3 animate-spin" />
      ) : (
        <Plus className="h-3 w-3" />
      )}
      Ajouter
    </button>
  );
}

type EvalWebOwner = {
  name: string;
  statut: string | null;
  postal_address: string | null;
  inscription_date: string | null;
  conditions: string | null;
  // Champs ajoutés par l'enrichissement auto (REQ + Canada411)
  phone: string | null;
  phone_source: string | null;
  req_neq: string | null;
  req_status: string | null;
  req_forme_juridique: string | null;
  req_address: string | null;
  req_ville: string | null;
  req_code_postal: string | null;
  c411_address: string | null;
};

type EvalWebResponse = {
  matricule: string;
  owners: EvalWebOwner[];
  fetched_at: string | null;
  cached: boolean;
};

function OwnerCandidatesModal({
  property,
  onClose,
  onConverted
}: {
  property: Property;
  onClose: () => void;
  onConverted: () => void;
}) {
  const [candidates, setCandidates] = useState<OwnerCandidate[]>([]);
  const [loading, setLoading] = useState(true);
  const [converting, setConverting] = useState<string | null>(null);

  // EvalWeb (rôle) — fetch on demand
  const [evalLoading, setEvalLoading] = useState(false);
  const [evalData, setEvalData] = useState<EvalWebResponse | null>(null);
  const [evalError, setEvalError] = useState<string | null>(null);
  // Fallback collage manuel
  const [showPaste, setShowPaste] = useState(false);
  const [pasteText, setPasteText] = useState("");
  const [pasteSubmitting, setPasteSubmitting] = useState(false);

  async function submitPaste() {
    if (!pasteText.trim()) return;
    setPasteSubmitting(true);
    setEvalError(null);
    try {
      const r = await authedFetch(
        `/api/v1/prospection/mtl-properties/${encodeURIComponent(
          property.matricule
        )}/owner-evalweb-manual`,
        {
          method: "POST",
          body: JSON.stringify({ text: pasteText })
        }
      );
      if (!r.ok) {
        const err = await r.json().catch(() => ({}));
        throw new Error(err.detail || `HTTP ${r.status}`);
      }
      setEvalData((await r.json()) as EvalWebResponse);
      setShowPaste(false);
      setPasteText("");
    } catch (e) {
      setEvalError(e instanceof Error ? e.message : "Erreur");
    } finally {
      setPasteSubmitting(false);
    }
  }

  async function fetchEvalWeb(refresh = false) {
    setEvalLoading(true);
    setEvalError(null);
    try {
      const url =
        `/api/v1/prospection/mtl-properties/${encodeURIComponent(
          property.matricule
        )}/owner-evalweb` + (refresh ? "?refresh=true" : "");
      const r = await authedFetch(url);
      if (!r.ok) {
        // 502 = le scrape auto a échoué côté serveur (site EvalWeb
        // protégé / reCAPTCHA / VPS injoignable). Plutôt que d'afficher
        // une erreur 502 brute, on bascule directement sur le collage
        // manuel — c'est le chemin le plus fiable, en 1 clic.
        if (r.status === 502 || r.status === 503 || r.status === 504) {
          setShowPaste(true);
          setEvalError(
            "Le scrape automatique n'a pas abouti (site EvalWeb " +
              "protégé). Colle la section « Propriétaire » ci-dessous — " +
              "c'est la méthode la plus fiable."
          );
          return;
        }
        const err = await r.json().catch(() => ({}));
        throw new Error(err.detail || `HTTP ${r.status}`);
      }
      setEvalData((await r.json()) as EvalWebResponse);
    } catch (e) {
      setEvalError(e instanceof Error ? e.message : "Erreur");
    } finally {
      setEvalLoading(false);
    }
  }

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await authedFetch(
          `/api/v1/prospection/mtl-properties/${encodeURIComponent(
            property.matricule
          )}/owner-candidates`
        );
        if (!r.ok) throw new Error();
        const data = (await r.json()) as OwnerCandidate[];
        if (!cancelled) setCandidates(data);
      } catch {
        if (!cancelled) setCandidates([]);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();

    // Si on a déjà des données EvalWeb cachées pour cette propriété,
    // on les charge automatiquement (cache_only=true → pas de scrape).
    if (property.has_owner_data) {
      void (async () => {
        try {
          const r = await authedFetch(
            `/api/v1/prospection/mtl-properties/${encodeURIComponent(
              property.matricule
            )}/owner-evalweb?cache_only=true`
          );
          if (!r.ok) return;
          const data = (await r.json()) as EvalWebResponse;
          if (!cancelled && data.owners.length > 0) {
            setEvalData(data);
          }
        } catch {
          /* ignore */
        }
      })();
    }

    return () => {
      cancelled = true;
    };
  }, [property.matricule, property.has_owner_data]);

  // Polling de l'extension navigateur : si l'utilisateur a l'extension
  // Horizon installée et qu'il navigue sur la fiche montreal.ca de ce
  // matricule dans un autre onglet, les données arriveront en DB
  // (owners_json) via POST /api/v1/extension/evalweb-owners. On polle
  // toutes les 3s tant qu'on n'a pas de données affichées.
  useEffect(() => {
    if (evalData && evalData.owners.length > 0) return;
    let cancelled = false;
    const intervalId = setInterval(async () => {
      try {
        const r = await authedFetch(
          `/api/v1/prospection/mtl-properties/${encodeURIComponent(
            property.matricule
          )}/owner-evalweb?cache_only=true`
        );
        if (!r.ok) return;
        const data = (await r.json()) as EvalWebResponse;
        if (!cancelled && data.owners.length > 0) {
          setEvalData(data);
        }
      } catch {
        /* ignore */
      }
    }, 3000);
    return () => {
      cancelled = true;
      clearInterval(intervalId);
    };
  }, [property.matricule, evalData]);

  async function convertWithOwner(neq: string | null) {
    setConverting(neq || "no-neq");
    try {
      const params = new URLSearchParams();
      if (neq) params.set("owner_neq", neq);
      const res = await authedFetch(
        `/api/v1/prospection/mtl-properties/${encodeURIComponent(
          property.matricule
        )}/convert-to-lead?${params}`,
        { method: "POST" }
      );
      if (!res.ok) {
        const t = await res.text();
        alert(t.slice(0, 200));
        return;
      }
      const data = (await res.json()) as { lead_id: number };
      onConverted();
      window.location.href = `/prospection/${data.lead_id}`;
    } finally {
      setConverting(null);
    }
  }

  return (
    <div
      className="fixed inset-0 z-[1000] flex items-center justify-center bg-black/70 p-4"
      role="dialog"
      aria-modal="true"
    >
      <div className="flex max-h-[90vh] w-full max-w-2xl flex-col overflow-hidden rounded-2xl border border-brand-800 bg-brand-950">
        <header className="flex items-start justify-between gap-3 border-b border-brand-800 p-4">
          <div className="min-w-0">
            <h2 className="flex items-center gap-2 text-sm font-semibold text-white">
              <Users className="h-4 w-4 text-accent-500" />
              Propriétaires candidats
            </h2>
            <p className="mt-1 text-xs text-white/60">
              <MapPin className="mr-1 inline h-3 w-3" />
              {property.full_address}
              {property.municipalite ? ` · ${property.municipalite}` : ""}
            </p>
            <p className="mt-0.5 font-mono text-[10px] text-white/40">
              Matricule {property.matricule}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="btn-ghost btn-xs"
          >
            <X className="h-4 w-4" />
          </button>
        </header>

        <div className="flex-1 overflow-y-auto p-4">
          {/* EvalWeb (rôle d'évaluation MTL) — source primaire. */}
          <section className="mb-4 rounded-lg border border-emerald-500/30 bg-emerald-500/5 p-3">
            <div className="mb-2 flex items-center justify-between gap-2">
              <h3 className="text-[11px] font-semibold uppercase tracking-wider text-accent-500">
                Propriétaires au rôle (EvalWeb)
              </h3>
              <div className="flex items-center gap-1.5">
                <button
                  type="button"
                  onClick={() => {
                    // Demande à l'extension d'ouvrir montreal.ca dans
                    // un onglet en arrière-plan (focus reste ici), de
                    // piloter le flow 4 étapes, scraper, puis fermer
                    // l'onglet. Si l'extension n'est pas installée, on
                    // fallback sur window.open visible.
                    const matricule = property.matricule;
                    // Détectée par message au chargement de la page
                    // (le marqueur window.__h2_extension est invisible).
                    const hasExtension = extensionDetectee;
                    if (hasExtension) {
                      window.postMessage(
                        { type: "h2_open_evalweb", matricule },
                        "*"
                      );
                    } else {
                      const url = `https://montreal.ca/role-evaluation-fonciere?h2matricule=${encodeURIComponent(matricule)}`;
                      window.open(url, "_blank", "noopener");
                    }
                  }}
                  className="inline-flex items-center gap-1 rounded-md border border-emerald-400 bg-emerald-500/20 px-2 py-1 text-[10px] font-semibold text-emerald-200 hover:bg-emerald-500/30"
                  title="L'extension Horizon ouvre montreal.ca en arrière-plan, scrape, et envoie les données ici"
                >
                  <Search className="h-3 w-3" />
                  Récupérer (auto)
                </button>
                <button
                  type="button"
                  onClick={() => fetchEvalWeb(!!evalData)}
                  disabled={evalLoading}
                  className="inline-flex items-center gap-1 rounded-md border border-emerald-500/40 bg-emerald-500/10 px-2 py-1 text-[10px] text-emerald-300 hover:bg-emerald-500/20 disabled:opacity-50"
                  title="Tente le scraper VPS (peut être bloqué par reCAPTCHA)"
                >
                  {evalLoading ? (
                    <Loader2 className="h-3 w-3 animate-spin" />
                  ) : evalData ? (
                    <RefreshCw className="h-3 w-3" />
                  ) : (
                    <Search className="h-3 w-3" />
                  )}
                  {evalLoading
                    ? "…"
                    : evalData
                      ? "Rafraîchir"
                      : "VPS"}
                </button>
              </div>
            </div>

            {!evalData && !evalLoading && !evalError ? (
              <div className="space-y-2">
                <p className="text-[11px] text-white/50">
                  Clique <strong>« Récupérer (auto) »</strong> :
                  l&apos;extension Horizon ouvre montreal.ca dans un nouvel
                  onglet, navigue automatiquement jusqu&apos;à la fiche du
                  matricule, scrape les propriétaires et les renvoie ici
                  (~10-15 secondes). Cette modale se met à jour
                  automatiquement.
                </p>
                <p className="text-[10px] text-white/40">
                  Pas l&apos;extension ? Va dans{" "}
                  <a
                    href="/prospection/parametres/outils"
                    className="underline hover:text-white/60"
                  >
                    Paramètres → Outils
                  </a>{" "}
                  pour la télécharger (1 fois, ~2 min).
                </p>
              </div>
            ) : null}

            {evalError ? (
              <div className="rounded border border-rose-500/40 bg-rose-500/10 p-2 text-[11px] text-rose-300">
                <p>{evalError}</p>
                <button
                  type="button"
                  onClick={() => {
                    setShowPaste(true);
                    setEvalError(null);
                  }}
                  className="mt-2 inline-flex items-center gap-1 rounded border border-emerald-500/40 bg-emerald-500/10 px-2 py-1 text-[10px] text-emerald-300 hover:bg-emerald-500/20"
                >
                  Saisir manuellement →
                </button>
              </div>
            ) : null}

            {/* Fallback : collage manuel depuis EvalWeb */}
            {!evalData && (showPaste || evalError) ? (
              <div className="mt-2 rounded border border-emerald-700/40 bg-brand-900 p-2.5">
                <p className="text-[11px] font-semibold text-emerald-200">
                  Collage manuel depuis EvalWeb
                </p>
                <ol className="mt-1.5 list-decimal space-y-0.5 pl-4 text-[10px] text-white/60">
                  <li>
                    Ouvre EvalWeb pour cette propriété :{" "}
                    <a
                      href="https://montreal.ca/role-evaluation-fonciere"
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-accent-500 underline hover:text-accent-400"
                    >
                      ouvrir le site
                    </a>{" "}
                    et cherche le matricule{" "}
                    <code className="text-white/80">
                      {property.matricule}
                    </code>
                  </li>
                  <li>
                    Sélectionne tout le bloc « Propriétaire » (du label
                    « Nom » jusqu&apos;avant « Caractéristiques ») et
                    fais Ctrl+C
                  </li>
                  <li>Colle ci-dessous puis valide</li>
                </ol>
                <textarea
                  value={pasteText}
                  onChange={(e) => setPasteText(e.target.value)}
                  rows={6}
                  placeholder={
                    "Nom\nGEREMIA, ROBERTO (Emphytéote)\nStatut aux fins d'imposition scolaire\nPersonne physique\nAdresse postale\n450 CH DU GOLF, VERDUN QUEBEC, H3E 1A8\n…"
                  }
                  className="mt-2 w-full rounded border border-brand-800 bg-brand-950 p-2 font-mono text-[10px] text-white"
                />
                <div className="mt-2 flex items-center gap-2">
                  <button
                    type="button"
                    onClick={submitPaste}
                    disabled={
                      pasteSubmitting || !pasteText.trim()
                    }
                    className="btn-accent btn-sm disabled:opacity-50"
                  >
                    {pasteSubmitting ? (
                      <Loader2 className="h-3 w-3 animate-spin" />
                    ) : null}
                    Parser et sauvegarder
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setShowPaste(false);
                      setPasteText("");
                    }}
                    className="text-[11px] text-white/50 hover:text-white"
                  >
                    Annuler
                  </button>
                </div>
              </div>
            ) : null}

            {evalData ? (
              evalData.owners.length === 0 ? (
                <p className="text-[11px] text-white/50">
                  Aucun propriétaire trouvé pour ce matricule.
                </p>
              ) : (
                <ul className="space-y-2">
                  {evalData.owners.map((o, i) => (
                    <li
                      key={i}
                      className="rounded-md border border-brand-800 bg-brand-900 p-2.5"
                    >
                      <p className="text-sm font-semibold text-white">
                        {o.name}
                      </p>
                      <div className="mt-0.5 flex flex-wrap items-center gap-2 text-[10px] text-white/50">
                        {o.statut ? <span>{o.statut}</span> : null}
                        {o.req_neq ? (
                          <span className="badge badge-blue">
                            REQ : {o.req_neq}
                          </span>
                        ) : null}
                        {o.conditions ? (
                          <span className="badge badge-amber">
                            {o.conditions}
                          </span>
                        ) : null}
                      </div>
                      {o.postal_address ? (
                        <p className="mt-1 text-[11px] text-white/70">
                          <MapPin className="mr-1 inline h-3 w-3" />
                          {o.postal_address}
                        </p>
                      ) : null}
                      {/* Téléphone trouvé (REQ ou Canada411) */}
                      {o.phone ? (
                        <p className="mt-1 text-[11px] text-emerald-300">
                          📞{" "}
                          <a
                            href={`tel:${o.phone}`}
                            className="hover:text-emerald-200"
                          >
                            {o.phone}
                          </a>
                          <span className="ml-1 text-[10px] text-white/40">
                            ({o.phone_source === "req"
                              ? "REQ"
                              : o.phone_source === "canada411"
                                ? "Canada411"
                                : ""}
                            )
                          </span>
                        </p>
                      ) : null}
                      {/* Adresse REQ (siège social corp) */}
                      {o.req_address ? (
                        <p className="mt-0.5 text-[10px] text-blue-300/70">
                          Siège REQ : {o.req_address}
                          {o.req_ville ? `, ${o.req_ville}` : ""}
                          {o.req_code_postal
                            ? ` ${o.req_code_postal}`
                            : ""}
                        </p>
                      ) : null}
                      {o.inscription_date ? (
                        <p className="mt-0.5 text-[10px] text-white/40">
                          Inscrit au rôle : {o.inscription_date}
                        </p>
                      ) : null}
                    </li>
                  ))}
                </ul>
              )
            ) : null}

            {evalData?.fetched_at ? (
              <p className="mt-2 text-[10px] text-white/30">
                Récupéré le{" "}
                {new Date(evalData.fetched_at).toLocaleDateString(
                  "fr-CA"
                )}
                {evalData.cached ? " (cache)" : ""}
              </p>
            ) : null}
          </section>

          <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-blue-300">
            Corporations REQ candidates
          </h3>

          {loading ? (
            <div className="flex justify-center py-8">
              <Loader2 className="h-5 w-5 animate-spin text-accent-500" />
            </div>
          ) : candidates.length === 0 ? (
            <div className="rounded-md border border-amber-500/30 bg-amber-500/5 p-3 text-xs text-amber-200">
              Aucune corporation REQ avec adresse postale matchant cette
              propriété.
              <br />
              <span className="text-amber-200/60">
                Soit le proprio est un particulier (pas dans le REQ —
                voir la section EvalWeb ci-dessus), soit la corporation
                a une adresse différente.
              </span>
            </div>
          ) : (
            <ul className="space-y-2">
              {candidates.map((c) => (
                <li
                  key={c.neq}
                  className="rounded-md border border-brand-800 bg-brand-900 p-3"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0 flex-1">
                      <p className="font-medium text-white">
                        {c.nom || "(sans nom)"}
                      </p>
                      <p className="mt-0.5 font-mono text-[10px] text-white/40">
                        NEQ {c.neq}
                      </p>
                      <p className="mt-1 text-[11px] text-white/60">
                        {c.adresse}
                        {c.ville ? `, ${c.ville}` : ""}
                        {c.code_postal ? ` ${c.code_postal}` : ""}
                      </p>
                      {c.telephone ? (
                        <p className="mt-0.5 text-[11px] text-emerald-300">
                          📞 {c.telephone}
                        </p>
                      ) : null}
                      {c.statut ? (
                        <span className="badge badge-neutral mt-1">
                          {c.statut}
                        </span>
                      ) : null}
                    </div>
                    <button
                      type="button"
                      onClick={() => convertWithOwner(c.neq)}
                      disabled={converting !== null}
                      className="inline-flex shrink-0 items-center gap-1 rounded-md border border-emerald-500/40 bg-emerald-500/10 px-2.5 py-1.5 text-[11px] text-emerald-300 hover:bg-emerald-500/20 disabled:opacity-50"
                    >
                      {converting === c.neq ? (
                        <Loader2 className="h-3 w-3 animate-spin" />
                      ) : (
                        <Plus className="h-3 w-3" />
                      )}
                      Lead avec ce proprio
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>

        <footer className="flex items-center justify-between gap-2 border-t border-brand-800 p-3">
          <p className="text-[10px] text-white/40">
            Le matching se fait par adresse postale du siège REQ.
            Précision ~70-80 %.
          </p>
          <button
            type="button"
            onClick={() => convertWithOwner(null)}
            disabled={converting !== null || property.already_lead}
            className="btn-secondary btn-sm disabled:opacity-50"
          >
            {converting === "no-neq" ? (
              <Loader2 className="h-3 w-3 animate-spin" />
            ) : (
              <Plus className="h-3 w-3" />
            )}
            {evalData && evalData.owners.length > 0
              ? "Créer lead avec proprio EvalWeb"
              : "Créer lead sans proprio"}
          </button>
        </footer>
      </div>
    </div>
  );
}
