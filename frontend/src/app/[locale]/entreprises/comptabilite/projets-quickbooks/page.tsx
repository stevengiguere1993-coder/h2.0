"use client";

/* Comptabilité → « Projets QB » (Steven 2026-10-14).

   Kratos crée un SOUS-CLIENT QuickBooks pour chaque projet, mais Intuit
   ne laisse pas le convertir en PROJET (onglet Projets de QB) par API sans
   palier partenaire Silver — « nous ne serons pas en silver ». La
   conversion se fait donc dans QuickBooks : par l'extension Chrome
   Horizon sur la page Projets (elle lit cette liste et coche les bons
   sous-clients), ou à la main. Kratos constate ensuite par l'API que le
   sous-client est devenu un projet et raye la ligne (bouton « Vérifier »,
   passage de nuit, compte rendu de l'extension). */

import { useCallback, useEffect, useState } from "react";
import {
  AlertTriangle,
  Check,
  CheckCircle2,
  Copy,
  ExternalLink,
  EyeOff,
  Loader2,
  Puzzle,
  RefreshCw,
  RotateCcw
} from "lucide-react";

import { Link } from "@/i18n/navigation";
import { authedFetch } from "@/lib/auth";

// ── Réponses de /api/v1/qbo-conversions ─────────────────────────────

type Etat = "a_convertir" | "convertie" | "ignoree";

type Ligne = {
  project_id: number;
  projet: string;
  kind: string;
  client: string | null;
  sous_client: string;
  sous_client_complet: string;
  etat: Etat;
  detail: string | null;
  convertie_le: string | null;
  cree_le: string | null;
};

type Liste = {
  quickbooks: {
    connectee: boolean;
    company_name: string;
    realm_id: string | null;
    environment: string;
    lien_projets: string;
  };
  a_convertir: Ligne[];
  converties: Ligne[];
  ignorees: Ligne[];
};

type Bilan = { verifies: number; converties: number[]; restantes: number[] };

//: Même zip que Prospection → Rôles fonciers ; version = manifest.json
//: (tests/test_extension_zip.py). La conversion des sous-clients demande
//: la 1.3.0 (content-qbo.js).
const EXTENSION_VERSION = "1.3.1";
const EXTENSION_MIN = "1.3.0";
const EXTENSION_ZIP = "/telechargements/extension-horizon-h2.zip";

const CARTE = { borderColor: "var(--qg-border)", backgroundColor: "var(--qg-card-bg)" };

// ── Extension (sonde + configuration poussée) ────────────────────────

type ExtStatut = "inconnue" | "absente" | "ancienne" | "configuree" | "non_configuree";

function versionAuMoins(v: string, min: string): boolean {
  const a = v.split(".").map((x) => parseInt(x, 10) || 0);
  const b = min.split(".").map((x) => parseInt(x, 10) || 0);
  for (let i = 0; i < Math.max(a.length, b.length); i++) {
    const d = (a[i] || 0) - (b[i] || 0);
    if (d !== 0) return d > 0;
  }
  return true;
}

/** Attend UNE réponse de l'extension (content-h20.js) à un message. */
function demanderExtension<T>(
  envoi: Record<string, unknown>,
  typeReponse: string,
  delaiMs: number
): Promise<T | null> {
  return new Promise((resolve) => {
    if (typeof window === "undefined") return resolve(null);
    let fini = false;
    const onMsg = (ev: MessageEvent) => {
      if (ev.source !== window) return;
      const m = ev.data as { type?: string } | null;
      if (m?.type === typeReponse) {
        fini = true;
        window.removeEventListener("message", onMsg);
        resolve(m as T);
      }
    };
    window.addEventListener("message", onMsg);
    window.postMessage(envoi, window.location.origin);
    setTimeout(() => {
      if (!fini) {
        window.removeEventListener("message", onMsg);
        resolve(null);
      }
    }, delaiMs);
  });
}

async function configurerExtension(): Promise<ExtStatut> {
  const pong = await demanderExtension<{ version?: string }>(
    { type: "h2_extension_ping" },
    "h2_extension_pong",
    1200
  );
  if (!pong) {
    // ≤ 1.2.x répond encore à h2_batch_status : installée mais trop vieille.
    const vieille = await demanderExtension({ type: "h2_batch_status" }, "h2_batch_state", 1200);
    return vieille ? "ancienne" : "absente";
  }
  if (!versionAuMoins(pong.version || "0", EXTENSION_MIN)) return "ancienne";
  try {
    const r = await authedFetch("/api/v1/extension/config");
    if (!r.ok) return "non_configuree";
    const d = (await r.json()) as { backend_url: string | null; api_key: string | null };
    if (!d.backend_url || !d.api_key) return "non_configuree";
    const ack = await demanderExtension<{ ok?: boolean }>(
      { type: "h2_extension_config", backendUrl: d.backend_url, apiKey: d.api_key },
      "h2_extension_config_ack",
      1500
    );
    return ack?.ok ? "configuree" : "non_configuree";
  } catch {
    return "non_configuree";
  }
}

// ── Helpers ─────────────────────────────────────────────────────────

function dateLisible(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleDateString("fr-CA", { year: "numeric", month: "short", day: "numeric" });
}

async function lireErreur(r: Response, defaut: string): Promise<string> {
  try {
    const j = (await r.json()) as { detail?: unknown };
    if (typeof j.detail === "string") return j.detail;
  } catch {
    /* pas de JSON */
  }
  return defaut;
}

// ── Page ─────────────────────────────────────────────────────────────

export default function ProjetsQuickBooksPage() {
  const [liste, setListe] = useState<Liste | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);
  const [occupe, setOccupe] = useState<"verifier" | "ajouter" | null>(null);
  const [message, setMessage] = useState<{ texte: string; ton: "ok" | "info" | "erreur" } | null>(null);
  const [extStatut, setExtStatut] = useState<ExtStatut>("inconnue");
  const [voirConverties, setVoirConverties] = useState(false);
  const [voirIgnorees, setVoirIgnorees] = useState(false);

  const charger = useCallback(async () => {
    try {
      const r = await authedFetch("/api/v1/qbo-conversions");
      if (!r.ok) {
        setErreur(await lireErreur(r, `Lecture impossible (HTTP ${r.status})`));
        return;
      }
      setListe((await r.json()) as Liste);
      setErreur(null);
    } catch {
      setErreur("Serveur injoignable.");
    }
  }, []);

  useEffect(() => {
    void charger();
  }, [charger]);

  useEffect(() => {
    let actif = true;
    void configurerExtension().then((st) => {
      if (actif) setExtStatut(st);
    });
    return () => {
      actif = false;
    };
  }, []);

  async function verifier() {
    setOccupe("verifier");
    setMessage(null);
    try {
      const r = await authedFetch("/api/v1/qbo-conversions/verifier", { method: "POST" });
      if (!r.ok) {
        setMessage({ texte: await lireErreur(r, `Vérification impossible (HTTP ${r.status})`), ton: "erreur" });
        return;
      }
      const b = (await r.json()) as Bilan;
      const n = b.converties.length;
      setMessage({
        texte:
          b.verifies === 0
            ? "Rien à vérifier : aucun sous-client en attente."
            : n === 0
              ? `${b.verifies} sous-client${b.verifies > 1 ? "s" : ""} vérifié${b.verifies > 1 ? "s" : ""} : aucun n'est encore un projet dans QuickBooks.`
              : `${n} sous-client${n > 1 ? "s" : ""} devenu${n > 1 ? "s" : ""} projet${n > 1 ? "s" : ""} dans QuickBooks : rayé${n > 1 ? "s" : ""} de la liste.`,
        ton: n > 0 ? "ok" : "info"
      });
      await charger();
    } catch {
      setMessage({ texte: "Serveur injoignable.", ton: "erreur" });
    } finally {
      setOccupe(null);
    }
  }

  async function ajouterExistants() {
    setOccupe("ajouter");
    setMessage(null);
    try {
      const r = await authedFetch("/api/v1/qbo-conversions/ajouter-existants", { method: "POST" });
      if (!r.ok) {
        setMessage({ texte: await lireErreur(r, `Ajout impossible (HTTP ${r.status})`), ton: "erreur" });
        return;
      }
      const b = (await r.json()) as { ajoutes: number; deja_converties: number };
      setMessage({
        texte: `${b.ajoutes} projet${b.ajoutes > 1 ? "s" : ""} existant${b.ajoutes > 1 ? "s" : ""} ajouté${b.ajoutes > 1 ? "s" : ""} à la liste ; ${b.deja_converties} déjà converti${b.deja_converties > 1 ? "s" : ""} dans QuickBooks.`,
        ton: b.ajoutes > 0 ? "ok" : "info"
      });
      await charger();
    } catch {
      setMessage({ texte: "Serveur injoignable.", ton: "erreur" });
    } finally {
      setOccupe(null);
    }
  }

  async function basculer(projectId: number, action: "ignorer" | "reprendre") {
    try {
      const r = await authedFetch(`/api/v1/qbo-conversions/${projectId}/${action}`, { method: "POST" });
      if (!r.ok) {
        setMessage({ texte: await lireErreur(r, `Action impossible (HTTP ${r.status})`), ton: "erreur" });
        return;
      }
      await charger();
    } catch {
      setMessage({ texte: "Serveur injoignable.", ton: "erreur" });
    }
  }

  const qb = liste?.quickbooks;
  const aConvertir = liste?.a_convertir ?? [];
  const extABesoin = extStatut === "absente" || extStatut === "ancienne";

  return (
    <div className="mx-auto max-w-4xl space-y-4 p-4 pb-24 lg:p-6">
      {/* Explication + actions */}
      <section className="rounded-2xl border p-4 sm:p-5" style={CARTE}>
        <h2 className="text-base font-semibold text-[var(--qg-text)]">
          Sous-clients à convertir en projet QuickBooks
        </h2>
        <p className="mt-1 text-sm text-[var(--qg-text-muted)]">
          Kratos crée le sous-client de chaque projet sous son client dans QuickBooks, mais
          QuickBooks ne permet pas de le transformer en projet par programme. La conversion se
          fait dans QuickBooks → Projets : l&apos;extension Chrome Horizon la fait à ta place quand
          cette page lui a donné la liste, sinon en quatre clics (étapes plus bas). Dès que le
          sous-client est devenu un projet, Kratos le raye d&apos;ici.
        </p>

        <div className="mt-4 flex flex-wrap items-center gap-2">
          {qb ? (
            <a
              href={qb.lien_projets}
              target="_blank"
              rel="noreferrer"
              className="btn-accent btn-sm inline-flex items-center gap-1.5"
              title={`Page Projets de QuickBooks (${qb.company_name})`}
            >
              Ouvrir Projets dans QuickBooks <ExternalLink className="h-3.5 w-3.5" />
            </a>
          ) : null}
          <button
            type="button"
            className="btn-secondary btn-sm inline-flex items-center gap-1.5"
            disabled={occupe !== null}
            onClick={() => void verifier()}
            title="Relit QuickBooks : les sous-clients devenus projets sont rayés"
          >
            {occupe === "verifier" ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <RefreshCw className="h-3.5 w-3.5" />
            )}
            Vérifier dans QuickBooks
          </button>
          <button
            type="button"
            className="btn-ghost btn-sm inline-flex items-center gap-1.5"
            disabled={occupe !== null}
            onClick={() => void ajouterExistants()}
            title="Les projets créés avant cette liste n'y sont pas : ceux dont le sous-client n'est pas encore un projet s'ajoutent ici"
          >
            {occupe === "ajouter" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
            Ajouter les projets existants
          </button>
        </div>

        {qb && !qb.connectee ? (
          <p className="mt-3 flex items-start gap-1.5 text-sm text-amber-300">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
            QuickBooks (Construction) n&apos;est pas connecté à Kratos : la vérification automatique
            attend la reconnexion (Paramètres → Comptabilité).
          </p>
        ) : null}

        {message ? (
          <p
            className={`mt-3 text-sm ${
              message.ton === "ok"
                ? "text-emerald-300"
                : message.ton === "erreur"
                  ? "text-rose-300"
                  : "text-[var(--qg-text)]"
            }`}
          >
            {message.texte}
          </p>
        ) : null}

        {/* Extension */}
        <div
          className="mt-4 flex flex-wrap items-center gap-2 rounded-xl border p-3"
          style={{ borderColor: "var(--qg-border)" }}
        >
          <Puzzle className="h-4 w-4 shrink-0 text-[var(--qg-text-muted)]" />
          <span className="text-sm text-[var(--qg-text)]">Extension Chrome Horizon</span>
          {extStatut === "configuree" ? (
            <span className="inline-flex items-center gap-1 text-xs text-emerald-300">
              <CheckCircle2 className="h-3.5 w-3.5" /> installée et configurée : ouvre QuickBooks →
              Projets, le panneau Horizon s&apos;y affiche
            </span>
          ) : extStatut === "ancienne" ? (
            <span className="text-xs text-amber-300">
              à mettre à jour (version {EXTENSION_VERSION} requise) : télécharge le zip et recharge
              l&apos;extension
            </span>
          ) : extStatut === "absente" ? (
            <span className="text-xs text-amber-300">non détectée dans ce navigateur</span>
          ) : extStatut === "non_configuree" ? (
            <span className="text-xs text-amber-300">
              installée, mais Kratos n&apos;a pas pu lui transmettre sa configuration : recharge
              cette page ; si ça persiste, la clé EXTENSION_API_KEY manque sur le serveur (Render)
            </span>
          ) : (
            <span className="text-xs text-[var(--qg-text-muted)]">détection…</span>
          )}
          <a
            href={EXTENSION_ZIP}
            download={`extension-horizon-h2-${EXTENSION_VERSION}.zip`}
            className={`ml-auto inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs font-medium transition ${
              extABesoin
                ? "border-amber-400/60 bg-amber-500/10 text-amber-300 hover:border-amber-300"
                : "border-[var(--qg-border)] text-[var(--qg-text)] hover:border-[var(--qg-accent)]"
            }`}
            title="Décompresse le zip → chrome://extensions → « Mode développeur » → « Charger l'extension non empaquetée » → dossier extension-horizon-h2 → recharge cette page (elle se configure toute seule)."
          >
            Télécharger l&apos;extension <span className="opacity-70">v{EXTENSION_VERSION}</span>
          </a>
        </div>
      </section>

      {/* À convertir */}
      <section className="rounded-2xl border p-4 sm:p-5" style={CARTE}>
        <h3 className="text-sm font-semibold text-[var(--qg-text)]">
          À convertir{liste ? ` (${aConvertir.length})` : ""}
        </h3>
        {erreur ? (
          <p className="mt-2 text-sm text-rose-300">{erreur}</p>
        ) : !liste ? (
          <div className="mt-2 flex items-center gap-2 text-sm text-[var(--qg-text-muted)]">
            <Loader2 className="h-4 w-4 animate-spin" /> Chargement…
          </div>
        ) : aConvertir.length === 0 ? (
          <p className="mt-2 text-sm text-[var(--qg-text-muted)]">
            Rien en attente : chaque nouveau projet lié à QuickBooks apparaîtra ici jusqu&apos;à sa
            conversion.
          </p>
        ) : (
          <ul className="mt-3 divide-y" style={{ borderColor: "var(--qg-border)" }}>
            {aConvertir.map((l) => (
              <LigneAConvertir key={l.project_id} ligne={l} onIgnorer={() => void basculer(l.project_id, "ignorer")} />
            ))}
          </ul>
        )}
      </section>

      {/* Étapes manuelles */}
      <section className="rounded-2xl border p-4 sm:p-5" style={CARTE}>
        <h3 className="text-sm font-semibold text-[var(--qg-text)]">Sans l&apos;extension : à la main dans QuickBooks</h3>
        <ol className="mt-2 list-decimal space-y-1 pl-5 text-sm text-[var(--qg-text)]">
          <li>Menu de gauche → <strong>Projets</strong>.</li>
          <li>
            Flèche du bouton <strong>« Nouveau projet ▾ »</strong> → <strong>« Convertir depuis un sous-client »</strong>.
          </li>
          <li>Cocher le sous-client (nom exact ci-dessus, bouton Copier) → <strong>Convertir</strong>.</li>
          <li>
            Revenir ici et cliquer <strong>Vérifier dans QuickBooks</strong> (sinon la vérification de nuit s&apos;en charge).
          </li>
        </ol>
        <p className="mt-2 text-xs text-[var(--qg-text-muted)]">
          Si le sous-client n&apos;est pas dans la liste de QuickBooks, ouvre sa fiche client : il doit avoir un
          seul client parent et « Facturer avec le client parent » coché.
        </p>
      </section>

      {/* Converties récentes */}
      {liste && liste.converties.length > 0 ? (
        <section className="rounded-2xl border p-4 sm:p-5" style={CARTE}>
          <button
            type="button"
            className="flex w-full items-center justify-between text-left text-sm font-semibold text-[var(--qg-text)]"
            onClick={() => setVoirConverties((v) => !v)}
          >
            <span>Converties récemment ({liste.converties.length})</span>
            <span className="text-xs font-normal text-[var(--qg-text-muted)]">{voirConverties ? "Masquer" : "Afficher"}</span>
          </button>
          {voirConverties ? (
            <ul className="mt-3 space-y-1 text-sm">
              {liste.converties.map((l) => (
                <li key={l.project_id} className="flex flex-wrap items-center gap-x-2 text-[var(--qg-text)]">
                  <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-emerald-300" />
                  <span className="font-medium">{l.sous_client_complet}</span>
                  <span className="text-xs text-[var(--qg-text-muted)]">
                    {l.convertie_le ? `constatée le ${dateLisible(l.convertie_le)}` : ""}
                  </span>
                  <LienProjet id={l.project_id} nom={l.projet} />
                </li>
              ))}
            </ul>
          ) : null}
        </section>
      ) : null}

      {/* Ignorées */}
      {liste && liste.ignorees.length > 0 ? (
        <section className="rounded-2xl border p-4 sm:p-5" style={CARTE}>
          <button
            type="button"
            className="flex w-full items-center justify-between text-left text-sm font-semibold text-[var(--qg-text)]"
            onClick={() => setVoirIgnorees((v) => !v)}
          >
            <span>Ignorées ({liste.ignorees.length})</span>
            <span className="text-xs font-normal text-[var(--qg-text-muted)]">{voirIgnorees ? "Masquer" : "Afficher"}</span>
          </button>
          {voirIgnorees ? (
            <ul className="mt-3 space-y-2 text-sm">
              {liste.ignorees.map((l) => (
                <li key={l.project_id} className="flex flex-wrap items-center gap-2 text-[var(--qg-text)]">
                  <span className="font-medium">{l.sous_client_complet}</span>
                  <LienProjet id={l.project_id} nom={l.projet} />
                  <button
                    type="button"
                    className="btn-ghost btn-xs inline-flex items-center gap-1"
                    onClick={() => void basculer(l.project_id, "reprendre")}
                  >
                    <RotateCcw className="h-3.5 w-3.5" /> Remettre dans la liste
                  </button>
                </li>
              ))}
            </ul>
          ) : null}
        </section>
      ) : null}
    </div>
  );
}

// ── Composants ───────────────────────────────────────────────────────

function LienProjet({ id, nom }: { id: number; nom: string }) {
  return (
    <Link
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      href={`/app/projets/${id}` as any}
      className="text-xs text-[var(--qg-text-muted)] underline-offset-2 hover:text-[var(--qg-text)] hover:underline"
      title="Fiche du projet dans Kratos"
    >
      projet « {nom} »
    </Link>
  );
}

function LigneAConvertir({ ligne, onIgnorer }: { ligne: Ligne; onIgnorer: () => void }) {
  return (
    <li className="flex flex-wrap items-start justify-between gap-2 py-3">
      <div className="min-w-0">
        <p className="flex flex-wrap items-center gap-1.5 text-sm text-[var(--qg-text)]">
          <span className="font-semibold">{ligne.sous_client}</span>
          <BoutonCopier texte={ligne.sous_client} quoi="le nom du sous-client" />
        </p>
        <p className="mt-0.5 text-xs text-[var(--qg-text-muted)]">
          {ligne.client ? `Client : ${ligne.client} · ` : ""}
          {ligne.kind === "bon_travail" ? "bon de travail · " : ""}
          {ligne.cree_le ? `créé le ${dateLisible(ligne.cree_le)} · ` : ""}
          <LienProjet id={ligne.project_id} nom={ligne.projet} />
        </p>
        {ligne.detail ? (
          <p className="mt-1 flex items-start gap-1 text-xs text-amber-300">
            <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" />
            {ligne.detail}
          </p>
        ) : null}
      </div>
      <button
        type="button"
        className="btn-ghost btn-xs inline-flex shrink-0 items-center gap-1"
        onClick={onIgnorer}
        title="Ne pas convertir ce sous-client (reste un simple sous-client)"
      >
        <EyeOff className="h-3.5 w-3.5" /> Ignorer
      </button>
    </li>
  );
}

function BoutonCopier({ texte, quoi }: { texte: string; quoi: string }) {
  const [fait, setFait] = useState(false);
  return (
    <button
      type="button"
      className="btn-ghost btn-xs inline-flex shrink-0 items-center gap-1"
      title={`Copier ${quoi}`}
      aria-label={`Copier ${quoi}`}
      onClick={() => {
        navigator.clipboard
          ?.writeText(texte)
          .then(() => {
            setFait(true);
            window.setTimeout(() => setFait(false), 1500);
          })
          .catch(() => {
            /* presse-papiers refusé : le texte reste sélectionnable */
          });
      }}
    >
      {fait ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
    </button>
  );
}
