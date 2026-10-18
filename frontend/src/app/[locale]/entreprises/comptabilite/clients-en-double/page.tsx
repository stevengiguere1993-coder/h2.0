"use client";

/* Comptabilité → « Clients en double » (Steven 2026-10-18).

   Doublons de clients dans chaque QuickBooks connecté à Kratos (Horizon,
   autres pôles, INC). Intuit ne fusionne pas de clients par API : la
   fusion se fait dans QuickBooks en renommant le doublon au nom EXACT de
   la fiche gardée (bouton Copier, lien qui ouvre la bonne compagnie).
   Kratos désactive lui-même une fiche vide, puis remet ses liens sur la
   fiche gardée (« C'est fait », ou le webhook « Merge » d'Intuit) pour
   que le doublon ne revienne pas au prochain envoi. */

import { useCallback, useEffect, useId, useMemo, useState } from "react";
import {
  AlertTriangle,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Copy,
  ExternalLink,
  Loader2,
  RefreshCw
} from "lucide-react";

import { Link } from "@/i18n/navigation";
import { authedFetch } from "@/lib/auth";

// ── Réponses de /api/v1/qbo-doublons ────────────────────────────────

type Compagnie = {
  scope: string;
  realm_id: string;
  nom: string;
  environment: string;
  reconnexion_requise: boolean;
  ou_reconnecter: string | null;
  utilisee_par: string[];
};

type NonConnectee = { entreprise_id: number; nom: string; ou_connecter: string };

type SousClient = { id: string; nom: string; projet: boolean };

type RefKratos = {
  type: "client" | "immeuble" | "feuille_de_temps";
  id: number;
  nom: string;
  detail: string;
};

type Fiche = {
  id: string;
  nom: string;
  compagnie: string | null;
  personne: string | null;
  courriel: string | null;
  telephone: string | null;
  adresse: string | null;
  solde: number;
  actif: boolean;
  cree_le: string | null;
  sous_clients: SousClient[];
  kratos: RefKratos[];
  lien_qb: string;
};

type Groupe = { cle: string; raisons: string[]; fiches: Fiche[]; suggestion: string | null };

type Analyse = {
  scope: string;
  realm_id: string;
  clients_lus: number;
  groupes: Groupe[];
  a_verifier: Groupe[];
  clients: { id: string; nom: string }[];
  noms_kratos: {
    client_id: number;
    nom_kratos: string;
    nom_quickbooks: string;
    qbo_customer_id: string;
  }[];
};

type Apercu = {
  id: string;
  nom: string;
  actif: boolean;
  solde: number;
  compteurs: Record<string, number>;
  inconnus: string[];
  sous_clients: SousClient[];
  vide: boolean;
};

type Suivi = {
  source: { id: string; nom: string | null };
  cible: { id: string; nom: string };
  clients_kratos: string[];
  immeubles: string[];
  compagnies_feuille_de_temps: string[];
  factures_mensuelles: number;
  avertissements: string[];
  sens_inverse?: boolean;
  desactivee?: boolean;
};

const CARTE = { borderColor: "var(--qg-border)", backgroundColor: "var(--qg-card-bg)" };
const CLE_SCOPE = "kratos.doublons.scope";

// ── Helpers ─────────────────────────────────────────────────────────

async function lireErreur(r: Response, defaut: string): Promise<string> {
  try {
    const j = (await r.json()) as { detail?: unknown };
    if (typeof j.detail === "string") return j.detail;
  } catch {
    /* pas de JSON */
  }
  return defaut;
}

function argent(n: number): string {
  return n.toLocaleString("fr-CA", { style: "currency", currency: "CAD" });
}

function dateLisible(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(`${iso.slice(0, 10)}T12:00:00`);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleDateString("fr-CA", { year: "numeric", month: "short", day: "numeric" });
}

function pluriel(n: number, mot: string): string {
  return `${n} ${mot}${n > 1 ? "s" : ""}`;
}

// Libellés des compteurs de /apercu (au pluriel) ramenés au singulier pour 1.
const SINGULIERS: Record<string, string> = {
  factures: "facture",
  paiements: "paiement",
  "notes de crédit": "note de crédit",
  "reçus de vente": "reçu de vente",
  remboursements: "remboursement",
  soumissions: "soumission"
};

function compte(n: number, libelle: string): string {
  return `${n} ${n === 1 ? (SINGULIERS[libelle] ?? libelle) : libelle}`;
}

/** « Kratos suit sur « X » : 2 fiches clients, 1 immeuble… » */
function resumeSuivi(s: Suivi): string {
  const parts: string[] = [];
  if (s.clients_kratos.length) parts.push(pluriel(s.clients_kratos.length, "fiche client"));
  if (s.immeubles.length) parts.push(pluriel(s.immeubles.length, "immeuble"));
  if (s.compagnies_feuille_de_temps.length)
    parts.push(pluriel(s.compagnies_feuille_de_temps.length, "compagnie de la feuille de temps"));
  if (s.factures_mensuelles) parts.push(pluriel(s.factures_mensuelles, "facture mensuelle"));
  const debut = s.desactivee
    ? `« ${s.source.nom ?? s.source.id} » désactivée dans QuickBooks.`
    : s.sens_inverse
      ? `La fusion s'est faite vers « ${s.cible.nom} » : Kratos a suivi dans ce sens.`
      : "Fusion constatée dans QuickBooks.";
  return parts.length
    ? `${debut} Kratos relie maintenant à « ${s.cible.nom} » : ${parts.join(", ")}.`
    : `${debut} Rien dans Kratos ne pointait le doublon.`;
}

// ── Page ─────────────────────────────────────────────────────────────

export default function ClientsEnDoublePage() {
  const [compagnies, setCompagnies] = useState<Compagnie[] | null>(null);
  const [nonConnectees, setNonConnectees] = useState<NonConnectee[]>([]);
  const [scope, setScope] = useState<string | null>(null);
  const [analyse, setAnalyse] = useState<Analyse | null>(null);
  const [chargement, setChargement] = useState(false);
  const [erreur, setErreur] = useState<string | null>(null);
  const [voirAVerifier, setVoirAVerifier] = useState(false);

  useEffect(() => {
    let actif = true;
    void (async () => {
      try {
        const r = await authedFetch("/api/v1/qbo-doublons");
        if (!r.ok) {
          if (actif) setErreur(await lireErreur(r, `Lecture impossible (HTTP ${r.status})`));
          return;
        }
        const d = (await r.json()) as { compagnies: Compagnie[]; non_connectees: NonConnectee[] };
        if (!actif) return;
        setCompagnies(d.compagnies);
        setNonConnectees(d.non_connectees);
        let retenu: string | null = null;
        try {
          retenu = window.localStorage.getItem(CLE_SCOPE);
        } catch {
          /* stockage indisponible */
        }
        const choix = d.compagnies.find((c) => c.scope === retenu) ?? d.compagnies[0];
        setScope(choix ? choix.scope : null);
      } catch {
        if (actif) setErreur("Serveur injoignable.");
      }
    })();
    return () => {
      actif = false;
    };
  }, []);

  const analyser = useCallback(async (s: string) => {
    setChargement(true);
    setErreur(null);
    setAnalyse(null);
    try {
      const r = await authedFetch(`/api/v1/qbo-doublons/analyse?scope=${encodeURIComponent(s)}`);
      if (!r.ok) {
        setErreur(await lireErreur(r, `Analyse impossible (HTTP ${r.status})`));
        return;
      }
      setAnalyse((await r.json()) as Analyse);
    } catch {
      setErreur("Serveur injoignable.");
    } finally {
      setChargement(false);
    }
  }, []);

  useEffect(() => {
    if (!scope) return;
    try {
      window.localStorage.setItem(CLE_SCOPE, scope);
    } catch {
      /* stockage indisponible */
    }
    void analyser(scope);
  }, [scope, analyser]);

  const compagnie = compagnies?.find((c) => c.scope === scope) ?? null;

  return (
    <div className="mx-auto max-w-4xl space-y-4 p-4 pb-24 lg:p-6">
      {/* Explication + choix de la compagnie */}
      <section className="rounded-2xl border p-4 sm:p-5" style={CARTE}>
        <h2 className="text-base font-semibold text-[var(--qg-text)]">Clients en double dans QuickBooks</h2>
        <p className="mt-1 text-sm text-[var(--qg-text-muted)]">
          QuickBooks ne laisse aucun logiciel fusionner deux clients par programme. La fusion se fait dans
          QuickBooks : on renomme le doublon au nom exact de la fiche gardée, QuickBooks propose de fusionner
          et tout l&apos;historique passe sous une seule fiche, sans changer un montant. Ici, Kratos trouve les
          doublons, te donne le nom exact à coller, désactive lui-même une fiche vide et, une fois la fusion
          faite, remet ses propres liens sur la fiche gardée.
        </p>

        {compagnies === null && !erreur ? (
          <div className="mt-3 flex items-center gap-2 text-sm text-[var(--qg-text-muted)]">
            <Loader2 className="h-4 w-4 animate-spin" /> Chargement des compagnies…
          </div>
        ) : null}

        {compagnies && compagnies.length === 0 ? (
          <p className="mt-3 flex items-start gap-1.5 text-sm text-amber-300">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
            Aucun QuickBooks n&apos;est connecté à Kratos.
          </p>
        ) : null}

        {compagnies && compagnies.length > 0 ? (
          <div className="mt-4 flex flex-wrap items-center gap-2">
            {compagnies.map((c) => (
              <button
                key={c.scope}
                type="button"
                onClick={() => setScope(c.scope)}
                className={`rounded-xl border px-3 py-2 text-left text-sm transition ${
                  c.scope === scope
                    ? "border-[var(--qg-accent)] text-[var(--qg-text)]"
                    : "border-[var(--qg-border)] text-[var(--qg-text-muted)] hover:text-[var(--qg-text)]"
                }`}
                title={`Utilisée par : ${c.utilisee_par.join(", ")}`}
              >
                <span className="block font-medium">{c.nom}</span>
                <span className="block text-xs text-[var(--qg-text-muted)]">{c.utilisee_par.join(" · ")}</span>
              </button>
            ))}
            {scope ? (
              <button
                type="button"
                className="btn-ghost btn-sm inline-flex items-center gap-1.5"
                disabled={chargement}
                onClick={() => void analyser(scope)}
                title="Relire les clients de cette compagnie dans QuickBooks"
              >
                {chargement ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
                Relire QuickBooks
              </button>
            ) : null}
          </div>
        ) : null}

        {compagnie?.reconnexion_requise ? (
          <p className="mt-3 flex items-start gap-1.5 text-sm text-amber-300">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
            Ce QuickBooks demande une reconnexion : {compagnie.ou_reconnecter}.
          </p>
        ) : null}

        {nonConnectees.length > 0 ? (
          <details className="mt-3 text-sm">
            <summary className="cursor-pointer text-[var(--qg-text-muted)] hover:text-[var(--qg-text)]">
              {pluriel(nonConnectees.length, "entreprise")} sans QuickBooks connecté à Kratos
            </summary>
            <ul className="mt-2 space-y-1 pl-4 text-[var(--qg-text)]">
              {nonConnectees.map((e) => (
                <li key={e.entreprise_id}>
                  <span className="font-medium">{e.nom}</span>
                  <span className="text-xs text-[var(--qg-text-muted)]"> · à connecter : {e.ou_connecter}</span>
                </li>
              ))}
            </ul>
          </details>
        ) : null}
      </section>

      {erreur ? (
        <section className="rounded-2xl border p-4 sm:p-5" style={CARTE}>
          <p className="flex items-start gap-1.5 text-sm text-rose-300">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
            {erreur}
          </p>
        </section>
      ) : null}

      {chargement ? (
        <section className="rounded-2xl border p-4 sm:p-5" style={CARTE}>
          <div className="flex items-center gap-2 text-sm text-[var(--qg-text-muted)]">
            <Loader2 className="h-4 w-4 animate-spin" /> Lecture des clients dans QuickBooks…
          </div>
        </section>
      ) : null}

      {analyse && scope ? (
        <>
          {/* Doublons probables */}
          <section className="rounded-2xl border p-4 sm:p-5" style={CARTE}>
            <h3 className="text-sm font-semibold text-[var(--qg-text)]">
              Doublons probables ({analyse.groupes.length})
            </h3>
            <p className="mt-0.5 text-xs text-[var(--qg-text-muted)]">
              {pluriel(analyse.clients_lus, "client")} lus · même nom, même numéro d&apos;entreprise ou nom presque
              identique
            </p>
            {analyse.groupes.length === 0 ? (
              <p className="mt-2 text-sm text-[var(--qg-text-muted)]">Aucun doublon probable dans cette compagnie.</p>
            ) : (
              <div className="mt-3 space-y-3">
                {analyse.groupes.map((g) => (
                  <CarteGroupe key={g.cle} groupe={g} scope={scope} />
                ))}
              </div>
            )}
          </section>

          {/* À vérifier */}
          {analyse.a_verifier.length > 0 ? (
            <section className="rounded-2xl border p-4 sm:p-5" style={CARTE}>
              <button
                type="button"
                className="flex w-full items-center justify-between text-left text-sm font-semibold text-[var(--qg-text)]"
                onClick={() => setVoirAVerifier((v) => !v)}
              >
                <span>À vérifier : même courriel, téléphone ou adresse ({analyse.a_verifier.length})</span>
                <span className="text-xs font-normal text-[var(--qg-text-muted)]">
                  {voirAVerifier ? "Masquer" : "Afficher"}
                </span>
              </button>
              {voirAVerifier ? (
                <>
                  <p className="mt-1 text-xs text-[var(--qg-text-muted)]">
                    Souvent la même compagnie sous deux noms (le nom légal et celui de l&apos;immeuble), parfois deux
                    compagnies du même propriétaire : à toi de juger.
                  </p>
                  <div className="mt-3 space-y-3">
                    {analyse.a_verifier.map((g) => (
                      <CarteGroupe key={g.cle} groupe={g} scope={scope} />
                    ))}
                  </div>
                </>
              ) : null}
            </section>
          ) : null}

          <PaireManuelle scope={scope} clients={analyse.clients} />

          {analyse.noms_kratos.length > 0 ? <NomsKratos lignes={analyse.noms_kratos} /> : null}
        </>
      ) : null}
    </div>
  );
}

// ── Un groupe de doublons ───────────────────────────────────────────

function CarteGroupe({ groupe, scope, ouvert = false }: { groupe: Groupe; scope: string; ouvert?: boolean }) {
  const [deplie, setDeplie] = useState(ouvert);
  const [garde, setGarde] = useState<string>(groupe.suggestion ?? groupe.fiches[0]?.id ?? "");
  const [faits, setFaits] = useState<Record<string, Suivi>>({});
  // Nom du groupe de boutons radio : un même groupe peut s'afficher deux
  // fois (analyse et « Deux clients au choix »).
  const radio = useId();
  // Une fois une fusion faite, la fiche gardée ne change plus.
  const verrouille = Object.keys(faits).length > 0;

  const fiche = useMemo(() => groupe.fiches.find((f) => f.id === garde) ?? null, [groupe.fiches, garde]);
  const sources = groupe.fiches.filter((f) => f.id !== garde);
  const toutFait = sources.length > 0 && sources.every((f) => faits[f.id]);

  return (
    <div className="rounded-xl border p-3" style={{ borderColor: "var(--qg-border)" }}>
      <button
        type="button"
        className="flex w-full items-start gap-2 text-left"
        onClick={() => setDeplie((v) => !v)}
        aria-expanded={deplie}
      >
        {deplie ? (
          <ChevronDown className="mt-0.5 h-4 w-4 shrink-0 text-[var(--qg-text-muted)]" />
        ) : (
          <ChevronRight className="mt-0.5 h-4 w-4 shrink-0 text-[var(--qg-text-muted)]" />
        )}
        <span className="min-w-0 flex-1">
          <span className="block text-sm font-semibold text-[var(--qg-text)]">
            {groupe.fiches.map((f) => f.nom).join("  ·  ")}
          </span>
          <span className="mt-0.5 block text-xs text-[var(--qg-text-muted)]">{groupe.raisons.join(" · ")}</span>
        </span>
        {toutFait ? (
          <span className="inline-flex shrink-0 items-center gap-1 text-xs text-emerald-300">
            <CheckCircle2 className="h-3.5 w-3.5" /> réglé
          </span>
        ) : null}
      </button>

      {deplie ? (
        <div className="mt-3 space-y-3">
          <p className="text-xs text-[var(--qg-text-muted)]">Choisis la fiche à garder : son nom restera.</p>
          <ul className="space-y-2">
            {groupe.fiches.map((f) => (
              <LigneFiche
                key={f.id}
                fiche={f}
                gardee={f.id === garde}
                fait={Boolean(faits[f.id])}
                verrouille={verrouille}
                onGarder={() => setGarde(f.id)}
                nomGroupe={radio}
              />
            ))}
          </ul>

          {fiche && fiche.sous_clients.length > 0 ? (
            <p className="flex items-start gap-1.5 text-xs text-amber-300">
              <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              La fiche gardée a {pluriel(fiche.sous_clients.length, "sous-client")} ou projet(s) : si QuickBooks
              refuse la fusion, détache-les le temps de la fusion, puis rattache-les.
            </p>
          ) : null}

          {fiche
            ? sources.map((s) => (
                <EtapesFusion
                  key={`${s.id}-${fiche.id}`}
                  scope={scope}
                  source={s}
                  cible={fiche}
                  suivi={faits[s.id] ?? null}
                  onFait={(res) => setFaits((m) => ({ ...m, [s.id]: res }))}
                />
              ))
            : null}
        </div>
      ) : null}
    </div>
  );
}

function LigneFiche({
  fiche,
  gardee,
  fait,
  verrouille,
  onGarder,
  nomGroupe
}: {
  fiche: Fiche;
  gardee: boolean;
  fait: boolean;
  verrouille: boolean;
  onGarder: () => void;
  nomGroupe: string;
}) {
  const details = [
    fiche.compagnie && fiche.compagnie !== fiche.nom ? `compagnie : ${fiche.compagnie}` : null,
    fiche.personne,
    fiche.courriel,
    fiche.telephone,
    fiche.adresse
  ].filter(Boolean);
  return (
    <li
      className="rounded-lg border p-2.5"
      style={{
        borderColor: gardee ? "var(--qg-accent)" : "var(--qg-border)",
        backgroundColor: gardee ? "var(--qg-bg-alt)" : undefined
      }}
    >
      <div className="flex flex-wrap items-start gap-x-2 gap-y-1">
        <label className="flex min-w-0 flex-1 basis-full cursor-pointer items-start gap-2 sm:basis-0">
          <input
            type="radio"
            name={`garder-${nomGroupe}`}
            checked={gardee}
            onChange={onGarder}
            disabled={verrouille}
            className="mt-1"
          />
          <span className="min-w-0">
            <span className={`text-sm font-semibold text-[var(--qg-text)] ${fait ? "line-through" : ""}`}>
              {fiche.nom}
            </span>
            {gardee ? (
              <span className="ml-2 whitespace-nowrap text-xs font-medium text-[var(--qg-text)]">fiche gardée</span>
            ) : null}
          </span>
        </label>
        <div className="flex shrink-0 items-center gap-1 pl-6 sm:pl-0">
          <BoutonCopier texte={fiche.nom} quoi="le nom exact" />
          <a
            href={fiche.lien_qb}
            target="_blank"
            rel="noreferrer"
            className="btn-ghost btn-xs inline-flex shrink-0 items-center gap-1"
            title="Ouvrir cette fiche dans QuickBooks (la bonne compagnie)"
          >
            QuickBooks <ExternalLink className="h-3 w-3" />
          </a>
        </div>
      </div>
      <p className="mt-1 pl-6 text-xs text-[var(--qg-text-muted)]">
        {[`solde ${argent(fiche.solde)}`, fiche.cree_le ? `créée le ${dateLisible(fiche.cree_le)}` : null, ...details]
          .filter(Boolean)
          .join(" · ")}
      </p>
      {fiche.sous_clients.length > 0 ? (
        <p className="mt-1 pl-6 text-xs text-amber-300">
          Sous-clients et projets : {fiche.sous_clients.map((c) => `${c.nom}${c.projet ? " (projet)" : ""}`).join(", ")}
        </p>
      ) : null}
      {fiche.kratos.length > 0 ? (
        <p className="mt-1 pl-6 text-xs text-[var(--qg-text)]">
          Dans Kratos :{" "}
          {fiche.kratos.map((k, i) => (
            <span key={`${k.type}-${k.id}`}>
              {i > 0 ? ", " : ""}
              {k.type === "client" ? (
                <Link
                  // eslint-disable-next-line @typescript-eslint/no-explicit-any
                  href={`/app/clients/${k.id}` as any}
                  className="underline-offset-2 hover:underline"
                >
                  {k.nom}
                </Link>
              ) : (
                <span>{k.nom}</span>
              )}{" "}
              <span className="text-[var(--qg-text-muted)]">({k.detail})</span>
            </span>
          ))}
        </p>
      ) : null}
    </li>
  );
}

// ── Faire disparaître un doublon ────────────────────────────────────

function EtapesFusion({
  scope,
  source,
  cible,
  suivi,
  onFait
}: {
  scope: string;
  source: Fiche;
  cible: Fiche;
  suivi: Suivi | null;
  onFait: (s: Suivi) => void;
}) {
  const [apercu, setApercu] = useState<Apercu | null>(null);
  const [occupe, setOccupe] = useState<"fusion" | "desactiver" | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    if (suivi) return;
    let actif = true;
    void (async () => {
      try {
        const r = await authedFetch(
          `/api/v1/qbo-doublons/apercu?scope=${encodeURIComponent(scope)}&id=${encodeURIComponent(source.id)}`
        );
        if (r.ok && actif) setApercu((await r.json()) as Apercu);
      } catch {
        /* l'aperçu est un plus : les étapes restent */
      }
    })();
    return () => {
      actif = false;
    };
  }, [scope, source.id, suivi]);

  async function envoyer(action: "fusion" | "desactiver") {
    setOccupe(action);
    setMessage(null);
    try {
      const r = await authedFetch(`/api/v1/qbo-doublons/${action}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ scope, source_id: source.id, cible_id: cible.id, nom_source: source.nom })
      });
      if (!r.ok) {
        setMessage(await lireErreur(r, `Action impossible (HTTP ${r.status})`));
        return;
      }
      onFait((await r.json()) as Suivi);
    } catch {
      setMessage("Serveur injoignable.");
    } finally {
      setOccupe(null);
    }
  }

  if (suivi) {
    return (
      <div className="rounded-lg border p-3 text-sm" style={{ borderColor: "var(--qg-border)" }}>
        <p className="flex items-start gap-1.5 text-emerald-300">
          <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" />
          {resumeSuivi(suivi)}
        </p>
        {suivi.avertissements.map((a) => (
          <p key={a} className="mt-1 flex items-start gap-1.5 text-xs text-amber-300">
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            {a}
          </p>
        ))}
      </div>
    );
  }

  const porte = apercu
    ? Object.entries(apercu.compteurs)
        .filter(([, n]) => n > 0)
        .map(([lib, n]) => compte(n, lib))
    : [];
  const projets = source.sous_clients.filter((c) => c.projet);

  return (
    <div className="rounded-lg border p-3 text-sm" style={{ borderColor: "var(--qg-border)" }}>
      <p className="font-medium text-[var(--qg-text)]">
        Faire disparaître « {source.nom} » dans « {cible.nom} »
      </p>
      {apercu ? (
        <p className="mt-0.5 text-xs text-[var(--qg-text-muted)]">
          {apercu.vide
            ? "Elle ne porte aucune facture, paiement, crédit, reçu de vente ni soumission."
            : porte.length
              ? `Elle porte ${porte.join(", ")} : tout passera sous « ${cible.nom} ».`
              : "Elle porte des transactions que Kratos n'a pas pu toutes compter."}
        </p>
      ) : (
        <p className="mt-0.5 flex items-center gap-1.5 text-xs text-[var(--qg-text-muted)]">
          <Loader2 className="h-3 w-3 animate-spin" /> Ce qu&apos;elle porte…
        </p>
      )}

      {source.sous_clients.length > 0 ? (
        <p className="mt-2 flex items-start gap-1.5 text-xs text-amber-300">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          D&apos;abord, détache ses {pluriel(source.sous_clients.length, "sous-client")} (Modifier, décocher « Est un
          client rattaché ») : QuickBooks refuse la fusion sinon.
          {projets.length > 0
            ? ` Un projet ne change pas de client : recrée « ${projets.map((p) => p.nom).join(" », « ")} » sous la fiche gardée.`
            : ""}
        </p>
      ) : null}

      {apercu?.vide ? (
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <button
            type="button"
            className="btn-accent btn-sm inline-flex items-center gap-1.5"
            disabled={occupe !== null}
            onClick={() => void envoyer("desactiver")}
            title="Kratos rend cette fiche inactive dans QuickBooks, sans que tu l'ouvres"
          >
            {occupe === "desactiver" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
            Désactiver dans QuickBooks
          </button>
          <span className="text-xs text-[var(--qg-text-muted)]">ou fusionne-la dans QuickBooks :</span>
        </div>
      ) : null}

      <ol className="mt-2 list-decimal space-y-1.5 pl-5 text-[var(--qg-text)]">
        <li>
          <a href={source.lien_qb} target="_blank" rel="noreferrer" className="underline-offset-2 hover:underline">
            Ouvrir « {source.nom} » dans QuickBooks <ExternalLink className="inline h-3 w-3 align-[-1px]" />
          </a>
        </li>
        <li>
          <span>
            Modifier, puis remplace le nom d&apos;affichage par <strong>{cible.nom}</strong>
          </span>{" "}
          <BoutonCopier texte={cible.nom} quoi="le nom de la fiche gardée" />
        </li>
        <li>Enregistrer, puis Oui quand QuickBooks propose de fusionner.</li>
        <li>
          <button
            type="button"
            className="btn-secondary btn-sm inline-flex items-center gap-1.5"
            disabled={occupe !== null}
            onClick={() => void envoyer("fusion")}
            title="Kratos vérifie dans QuickBooks et remet ses liens sur la fiche gardée"
          >
            {occupe === "fusion" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />}
            C&apos;est fait
          </button>
        </li>
      </ol>

      {message ? <p className="mt-2 text-xs text-rose-300">{message}</p> : null}
    </div>
  );
}

// ── Deux clients choisis à la main ──────────────────────────────────

function PaireManuelle({ scope, clients }: { scope: string; clients: { id: string; nom: string }[] }) {
  const [a, setA] = useState("");
  const [b, setB] = useState("");
  const [groupe, setGroupe] = useState<Groupe | null>(null);
  const [occupe, setOccupe] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const parNom = useMemo(() => new Map(clients.map((c) => [c.nom, c.id])), [clients]);

  async function preparer() {
    const ia = parNom.get(a.trim());
    const ib = parNom.get(b.trim());
    if (!ia || !ib) {
      setMessage("Choisis deux clients de la liste (nom exact).");
      return;
    }
    if (ia === ib) {
      setMessage("Choisis deux clients différents.");
      return;
    }
    setOccupe(true);
    setMessage(null);
    setGroupe(null);
    try {
      const r = await authedFetch(
        `/api/v1/qbo-doublons/paire?scope=${encodeURIComponent(scope)}&ids=${encodeURIComponent(`${ia},${ib}`)}`
      );
      if (!r.ok) {
        setMessage(await lireErreur(r, `Lecture impossible (HTTP ${r.status})`));
        return;
      }
      setGroupe((await r.json()) as Groupe);
    } catch {
      setMessage("Serveur injoignable.");
    } finally {
      setOccupe(false);
    }
  }

  return (
    <section className="rounded-2xl border p-4 sm:p-5" style={CARTE}>
      <h3 className="text-sm font-semibold text-[var(--qg-text)]">Deux clients au choix</h3>
      <p className="mt-0.5 text-xs text-[var(--qg-text-muted)]">
        Pour un doublon que Kratos ne voit pas (rien en commun, comme le nom légal et le nom de l&apos;immeuble).
      </p>
      <datalist id={`clients-${scope}`}>
        {clients.map((c) => (
          <option key={c.id} value={c.nom} />
        ))}
      </datalist>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <input
          list={`clients-${scope}`}
          value={a}
          onChange={(e) => setA(e.target.value)}
          placeholder="Premier client"
          className="input min-w-0 flex-1 basis-48"
        />
        <input
          list={`clients-${scope}`}
          value={b}
          onChange={(e) => setB(e.target.value)}
          placeholder="Deuxième client"
          className="input min-w-0 flex-1 basis-48"
        />
        <button
          type="button"
          className="btn-secondary btn-sm inline-flex items-center gap-1.5"
          disabled={occupe || !a.trim() || !b.trim()}
          onClick={() => void preparer()}
        >
          {occupe ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
          Comparer
        </button>
      </div>
      {message ? <p className="mt-2 text-xs text-rose-300">{message}</p> : null}
      {groupe ? (
        <div className="mt-3">
          <CarteGroupe key={groupe.cle} groupe={groupe} scope={scope} ouvert />
        </div>
      ) : null}
    </section>
  );
}

// ── Noms Kratos différents de QuickBooks ────────────────────────────

function NomsKratos({ lignes }: { lignes: Analyse["noms_kratos"] }) {
  const [faits, setFaits] = useState<Record<number, string>>({});
  const [erreurs, setErreurs] = useState<Record<number, string>>({});
  const [voir, setVoir] = useState(false);

  async function aligner(clientId: number) {
    setErreurs((m) => ({ ...m, [clientId]: "" }));
    try {
      const r = await authedFetch(`/api/v1/qbo-doublons/clients-kratos/${clientId}/nom-quickbooks`, {
        method: "POST"
      });
      if (!r.ok) {
        const msg = await lireErreur(r, `Action impossible (HTTP ${r.status})`);
        setErreurs((m) => ({ ...m, [clientId]: msg }));
        return;
      }
      const d = (await r.json()) as { nom: string };
      setFaits((m) => ({ ...m, [clientId]: d.nom }));
    } catch {
      setErreurs((m) => ({ ...m, [clientId]: "Serveur injoignable." }));
    }
  }

  return (
    <section className="rounded-2xl border p-4 sm:p-5" style={CARTE}>
      <button
        type="button"
        className="flex w-full items-center justify-between text-left text-sm font-semibold text-[var(--qg-text)]"
        onClick={() => setVoir((v) => !v)}
      >
        <span>Fiches Kratos qui ne portent pas le nom QuickBooks ({lignes.length})</span>
        <span className="text-xs font-normal text-[var(--qg-text-muted)]">{voir ? "Masquer" : "Afficher"}</span>
      </button>
      {voir ? (
        <>
          <p className="mt-1 text-xs text-[var(--qg-text-muted)]">
            À chaque facture, Kratos retrouve le client QuickBooks par son nom : un nom différent peut recréer un
            doublon. « Prendre le nom QuickBooks » renomme la fiche Kratos, rien ne change dans QuickBooks.
          </p>
          <ul className="mt-3 divide-y divide-[var(--qg-border)]">
            {lignes.map((l) => (
              <li key={l.client_id} className="flex flex-wrap items-center justify-between gap-2 py-2 text-sm">
                <span className="min-w-0 text-[var(--qg-text)]">
                  <Link
                    // eslint-disable-next-line @typescript-eslint/no-explicit-any
                    href={`/app/clients/${l.client_id}` as any}
                    className="underline-offset-2 hover:underline"
                  >
                    {l.nom_kratos}
                  </Link>
                  <span className="text-[var(--qg-text-muted)]"> → </span>
                  <strong>{l.nom_quickbooks}</strong>
                </span>
                {faits[l.client_id] ? (
                  <span className="inline-flex items-center gap-1 text-xs text-emerald-300">
                    <CheckCircle2 className="h-3.5 w-3.5" /> renommée
                  </span>
                ) : (
                  <button
                    type="button"
                    className="btn-ghost btn-xs"
                    onClick={() => void aligner(l.client_id)}
                    title="La fiche Kratos prend le nom exact de QuickBooks"
                  >
                    Prendre le nom QuickBooks
                  </button>
                )}
                {erreurs[l.client_id] ? (
                  <span className="w-full text-xs text-rose-300">{erreurs[l.client_id]}</span>
                ) : null}
              </li>
            ))}
          </ul>
        </>
      ) : null}
    </section>
  );
}

// ── Petits composants ───────────────────────────────────────────────

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
