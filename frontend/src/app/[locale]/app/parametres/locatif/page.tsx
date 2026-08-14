"use client";

/**
 * Paramètres → Gestion locative : DÉMARRAGE du pôle.
 *
 * Retour Phil 2026-07-27 : « je commence à utiliser le pôle pour vrai —
 * tout ce qui est avant le 1er juillet 2026 ne doit plus être vrai ».
 * Cette date est le point zéro de TOUT l'argent locatif : soldes des
 * locataires, historiques de paiements, revenus, mois facturables en
 * frais de gestion. Rien n'est supprimé : l'historique d'avant reste en
 * base, il est simplement ignoré — remettre la date en arrière le fait
 * réapparaître.
 *
 * Édition réservée manager+ (le PUT backend renvoie 403 sinon).
 */

import { useCallback, useEffect, useState } from "react";
import { Check, History, Landmark, Loader2, RefreshCw } from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { useAppLayout } from "../../layout";
import { authedFetch, hasMinRole } from "@/lib/auth";
import { useCurrentUser } from "@/hooks/use-current-user";
import { BoutonFilBancaire } from "@/components/immobilier/validation-bancaire";

const MOIS_FR = [
  "janvier", "février", "mars", "avril", "mai", "juin", "juillet",
  "août", "septembre", "octobre", "novembre", "décembre"
];

/** "2026-07-01" → "juillet 2026" */
function moisLabel(iso: string): string {
  const m = parseInt(iso.slice(5, 7), 10);
  if (!m || m < 1 || m > 12) return iso;
  return `${MOIS_FR[m - 1]} ${iso.slice(0, 4)}`;
}

export default function LocatifDemarragePage() {
  const { onOpenSidebar } = useAppLayout();
  const { user: me } = useCurrentUser();
  const canEdit = hasMinRole(me, "manager");

  const [valeur, setValeur] = useState<string | null>(null);
  const [enregistre, setEnregistre] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  // Fenêtres des suivis annuels (renouvellement / assurance / relevé 31).
  type Suivis = {
    renouvellement_mois_avant: number;
    assurance_bascule_mois: number;
    releve31_bascule_mois: number;
    assurance_inclut_au_mois: boolean;
  };
  const [suivis, setSuivis] = useState<Suivis | null>(null);
  const [suivisEnr, setSuivisEnr] = useState<Suivis | null>(null);
  const [busy2, setBusy2] = useState(false);
  const [msg2, setMsg2] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await authedFetch("/api/v1/immobilier/demarrage");
      if (!res.ok) throw new Error();
      const d = (await res.json()) as { date: string };
      setValeur(d.date);
      setEnregistre(d.date);
    } catch {
      setErr("Chargement du réglage impossible.");
      setValeur("");
    }
    try {
      const res = await authedFetch("/api/v1/immobilier/suivis-config");
      if (res.ok) {
        const s = (await res.json()) as Suivis;
        setSuivis(s);
        setSuivisEnr(s);
      }
    } catch {
      /* défauts backend appliqués */
    }
  }, []);

  async function saveSuivis() {
    if (!suivis) return;
    setBusy2(true);
    setMsg2(null);
    try {
      const res = await authedFetch("/api/v1/immobilier/suivis-config", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(suivis)
      });
      if (res.status === 403) {
        setMsg2("Réservé aux gestionnaires.");
        return;
      }
      if (!res.ok) throw new Error();
      const s = (await res.json()) as Suivis;
      setSuivis(s);
      setSuivisEnr(s);
      setMsg2("Fenêtres des suivis enregistrées.");
    } catch {
      setMsg2("Enregistrement impossible.");
    } finally {
      setBusy2(false);
    }
  }

  useEffect(() => {
    void load();
  }, [load]);

  async function save() {
    if (!valeur) return;
    setBusy(true);
    setMsg(null);
    setErr(null);
    try {
      const res = await authedFetch("/api/v1/immobilier/demarrage", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ date: valeur })
      });
      if (res.status === 403) {
        setErr("Réservé aux gestionnaires.");
        return;
      }
      if (!res.ok) throw new Error();
      const d = (await res.json()) as { date: string };
      setValeur(d.date);
      setEnregistre(d.date);
      setMsg(
        `Enregistré : la gestion locative démarre en ${moisLabel(d.date)}. ` +
          "Les soldes, historiques et mois facturables repartent de là."
      );
    } catch {
      setErr("Enregistrement impossible.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <AppTopbar
        breadcrumbs={[
          { label: "Construction", href: "/app" },
          { label: "Paramètres", href: "/app/parametres" },
          { label: "Gestion locative" }
        ]}
        onOpenSidebar={onOpenSidebar}
      />

      <div className="p-4 pb-28 lg:p-6 lg:pb-28">
        <h1 className="flex items-center gap-2 text-2xl font-bold text-white">
          <History className="h-6 w-6 text-accent-500" />
          Gestion locative — démarrage
        </h1>
        <p className="mt-1 max-w-2xl text-sm text-white/60">
          Point de départ de tout l&apos;argent du pôle. Un locataire qui
          traînait des mois impayés <strong>avant</strong> cette date repart à
          0 $ : seuls les loyers, frais et paiements de ce mois-là et des
          suivants comptent.
        </p>

        {err ? (
          <p className="mt-4 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">
            {err}
          </p>
        ) : null}
        {msg ? (
          <p className="mt-4 rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-300">
            {msg}
          </p>
        ) : null}

        <div className="mt-4 max-w-2xl rounded-2xl border border-brand-800 bg-brand-900 p-5">
          {valeur === null ? (
            <div className="flex items-center justify-center py-10 text-white/40">
              <Loader2 className="h-5 w-5 animate-spin" />
            </div>
          ) : (
            <>
              <label className="block text-xs font-medium uppercase tracking-wide text-white/50">
                La gestion locative démarre le
              </label>
              <div className="mt-2 flex flex-wrap items-center gap-3">
                <input
                  type="date"
                  value={valeur}
                  disabled={!canEdit}
                  onChange={(e) => setValeur(e.target.value)}
                  className="rounded-lg border border-brand-800 bg-brand-950 px-3 py-2 text-sm text-white focus:border-accent-500 focus:outline-none disabled:opacity-60"
                />
                {enregistre ? (
                  <span className="badge badge-neutral">
                    actuellement : {moisLabel(enregistre)}
                  </span>
                ) : null}
              </div>
              <p className="mt-2 text-xs text-white/45">
                La date est ramenée au 1er du mois choisi.
              </p>

              <ul className="mt-4 space-y-1.5 text-sm text-white/60">
                <li>
                  • Soldes des locataires et retards : calculés à partir de
                  cette date.
                </li>
                <li>
                  • Historiques de paiements (fiche locataire, bail, état de
                  compte PDF) : rien d&apos;avant n&apos;est affiché.
                </li>
                <li>
                  • Facturation des frais de gestion : les mois antérieurs ne
                  sont plus proposés ni facturables.
                </li>
                <li>
                  • Revenus et cashflow réel des immeubles : comptés depuis
                  cette date.
                </li>
              </ul>

              <p className="mt-4 rounded-lg border border-brand-800 bg-brand-950/60 px-3 py-2 text-xs text-white/55">
                Rien n&apos;est supprimé : l&apos;historique d&apos;avant reste
                stocké. Remettre la date en arrière le fait réapparaître
                partout.
              </p>

              {!canEdit ? (
                <p className="mt-3 text-xs text-white/50">
                  Lecture seule — la modification est réservée aux
                  gestionnaires.
                </p>
              ) : (
                <button
                  type="button"
                  onClick={() => void save()}
                  disabled={busy || !valeur || valeur === enregistre}
                  className="btn-accent btn-sm mt-4 disabled:opacity-50"
                >
                  {busy ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <Check className="h-4 w-4" />
                  )}
                  Enregistrer
                </button>
              )}
            </>
          )}
        </div>

        {/* ── Suivis annuels : fenêtres réglables ── */}
        <h2 className="mt-8 flex items-center gap-2 text-xl font-bold text-white">
          <History className="h-5 w-5 text-accent-500" />
          Suivis annuels — quand agir
        </h2>
        <p className="mt-1 max-w-2xl text-sm text-white/60">
          À partir de quel moment un renouvellement passe « à envoyer », une
          assurance « à reconfirmer » et un relevé 31 « à produire ». Tout est
          réglable ici.
        </p>

        <div className="mt-4 max-w-2xl rounded-2xl border border-brand-800 bg-brand-900 p-5">
          {suivis === null ? (
            <div className="flex items-center justify-center py-10 text-white/40">
              <Loader2 className="h-5 w-5 animate-spin" />
            </div>
          ) : (
            <>
              <div className="space-y-4">
                <div>
                  <label className="block text-xs font-medium uppercase tracking-wide text-white/50">
                    Renouvellement de bail — « à envoyer » à partir de
                  </label>
                  <div className="mt-2 flex items-center gap-2">
                    <select
                      value={suivis.renouvellement_mois_avant}
                      disabled={!canEdit}
                      onChange={(e) =>
                        setSuivis({
                          ...suivis,
                          renouvellement_mois_avant: parseInt(
                            e.target.value,
                            10
                          )
                        })
                      }
                      className="rounded-lg border border-brand-800 bg-brand-950 px-3 py-2 text-sm text-white focus:border-accent-500 focus:outline-none disabled:opacity-60"
                    >
                      {Array.from({ length: 12 }, (_, i) => i + 1).map((n) => (
                        <option key={n} value={n}>
                          {n} mois
                        </option>
                      ))}
                    </select>
                    <span className="text-sm text-white/50">
                      avant la fin du bail
                    </span>
                  </div>
                  <p className="mt-1 text-xs text-white/40">
                    L&apos;avis de modification TAL se transmet entre 6 et 3
                    mois avant la fin.
                  </p>
                </div>

                <div>
                  <label className="block text-xs font-medium uppercase tracking-wide text-white/50">
                    Assurance — reconfirmation annuelle à partir de
                  </label>
                  <select
                    value={suivis.assurance_bascule_mois}
                    disabled={!canEdit}
                    onChange={(e) =>
                      setSuivis({
                        ...suivis,
                        assurance_bascule_mois: parseInt(e.target.value, 10)
                      })
                    }
                    className="mt-2 rounded-lg border border-brand-800 bg-brand-950 px-3 py-2 text-sm text-white focus:border-accent-500 focus:outline-none disabled:opacity-60"
                  >
                    {MOIS_FR.map((m, i) => (
                      <option key={i} value={i + 1} className="capitalize">
                        {m}
                      </option>
                    ))}
                  </select>
                  <p className="mt-1 text-xs text-white/40">
                    Toute preuve confirmée avant cette bascule repasse « à
                    reconfirmer ».
                  </p>
                  <label className="mt-2 flex cursor-pointer items-start gap-2">
                    <input
                      type="checkbox"
                      checked={suivis.assurance_inclut_au_mois}
                      disabled={!canEdit}
                      onChange={(e) =>
                        setSuivis({
                          ...suivis,
                          assurance_inclut_au_mois: e.target.checked
                        })
                      }
                      className="mt-0.5 h-4 w-4 accent-[var(--accent-500,#f59e0b)]"
                    />
                    <span className="text-xs text-white/60">
                      Inclure les <strong>baux au mois</strong> (chambres)
                      dans le suivi des assurances — décoché, on n&apos;exige
                      rien des chambreurs.
                    </span>
                  </label>
                </div>

                <div>
                  <label className="block text-xs font-medium uppercase tracking-wide text-white/50">
                    Relevé 31 — année précédente affichée jusqu&apos;en
                  </label>
                  <select
                    value={suivis.releve31_bascule_mois}
                    disabled={!canEdit}
                    onChange={(e) =>
                      setSuivis({
                        ...suivis,
                        releve31_bascule_mois: parseInt(e.target.value, 10)
                      })
                    }
                    className="mt-2 rounded-lg border border-brand-800 bg-brand-950 px-3 py-2 text-sm text-white focus:border-accent-500 focus:outline-none disabled:opacity-60"
                  >
                    {MOIS_FR.map((m, i) => (
                      <option key={i} value={i + 1} className="capitalize">
                        {m}
                      </option>
                    ))}
                  </select>
                  <p className="mt-1 text-xs text-white/40">
                    Jusqu&apos;à ce mois inclus, la liste par défaut = relevés
                    de l&apos;année précédente (échéance légale : fin février).
                  </p>
                </div>
              </div>

              {msg2 ? (
                <p className="mt-4 text-xs text-white/60">{msg2}</p>
              ) : null}

              {!canEdit ? (
                <p className="mt-3 text-xs text-white/50">
                  Lecture seule — modification réservée aux gestionnaires.
                </p>
              ) : (
                <button
                  type="button"
                  onClick={() => void saveSuivis()}
                  disabled={
                    busy2 ||
                    JSON.stringify(suivis) === JSON.stringify(suivisEnr)
                  }
                  className="btn-accent btn-sm mt-4 disabled:opacity-50"
                >
                  {busy2 ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <Check className="h-4 w-4" />
                  )}
                  Enregistrer
                </button>
              )}
            </>
          )}
        </div>

        {/* ── Validation bancaire (QuickBooks) ── */}
        <ValidationBancaireSection canEdit={canEdit} />
      </div>
    </>
  );
}

// ─── Validation bancaire (QuickBooks) — 2e validation des loyers ───────
// L'adjointe publie les encaissements au compte « Loyer à remettre -
// {immeuble} » dans QuickBooks ; Kratos les LIT (lecture seule, aucune
// écriture) et pose ✓✓ « Validé banque » dans le suivi des loyers. Ici :
// activer la feature, régler l'alerte « sans trace après N jours »,
// découvrir les comptes, confirmer le ou LES immeubles suggérés (un
// compte peut couvrir plusieurs immeubles — ou tous : fiducie),
// synchroniser (avec le rapport détaillé) et ouvrir le fil bancaire.

type CompteLoyer = {
  id: number;
  qbo_account_id: string;
  qbo_account_name: string;
  immeuble_ids: number[];
  tous_les_immeubles: boolean;
  suggestion_immeuble_ids: number[];
  suggestion_tous: boolean;
  suggestion_score: number | null;
  actif: boolean;
  derniere_synchro_le: string | null;
};

type ValidationConfig = {
  active: boolean;
  alerte_jours: number;
  comptes: CompteLoyer[];
  immeubles: { id: number; name: string }[];
};

type SyncCompteDetail = {
  compte_id: number;
  compte_nom: string;
  lues: number;
  importees: number;
  mises_a_jour: number;
  ignorees: number;
  raisons: {
    sortie_argent: number;
    montant_nul: number;
    deja_importee: number;
    type_non_reconnu: number;
  };
  types_non_reconnus: string[];
  erreur: string | null;
};

type SyncRapport = {
  comptes: number;
  importees: number;
  mises_a_jour: number;
  ignorees: number;
  details: SyncCompteDetail[];
};

type SelectionCompte = {
  immeuble_ids: number[];
  tous: boolean;
  actif: boolean;
};

function ValidationBancaireSection({ canEdit }: { canEdit: boolean }) {
  const [cfg, setCfg] = useState<ValidationConfig | null>(null);
  const [active, setActive] = useState(false);
  const [jours, setJours] = useState(5);
  // Sélection locale par compte : immeubles cochés + case « tous » +
  // interrupteur.
  const [selections, setSelections] = useState<
    Record<number, SelectionCompte>
  >({});
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  // Rapport détaillé de la dernière synchro manuelle (bloc repliable).
  const [rapport, setRapport] = useState<SyncRapport | null>(null);

  const appliquer = useCallback((d: ValidationConfig) => {
    setCfg(d);
    setActive(d.active);
    setJours(d.alerte_jours);
    const sel: Record<number, SelectionCompte> = {};
    for (const c of d.comptes) {
      // Préremplissage : le confirmé, sinon la SUGGESTION (liste
      // d'immeubles, ou case « tous » pour un compte fiducie).
      const confirme = c.tous_les_immeubles || c.immeuble_ids.length > 0;
      sel[c.id] = confirme
        ? {
            immeuble_ids: c.immeuble_ids,
            tous: c.tous_les_immeubles,
            actif: c.actif
          }
        : {
            immeuble_ids: c.suggestion_immeuble_ids,
            tous: c.suggestion_tous,
            actif: c.actif
          };
    }
    setSelections(sel);
  }, []);

  const load = useCallback(async () => {
    try {
      const r = await authedFetch(
        "/api/v1/immobilier/validation-bancaire/config"
      );
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      appliquer((await r.json()) as ValidationConfig);
    } catch {
      setErr("Chargement de la validation bancaire impossible.");
    }
  }, [appliquer]);

  useEffect(() => {
    void load();
  }, [load]);

  async function saveReglages() {
    setBusy("reglages");
    setMsg(null);
    setErr(null);
    try {
      const r = await authedFetch(
        "/api/v1/immobilier/validation-bancaire/config",
        {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ active, alerte_jours: jours })
        }
      );
      if (r.status === 403) {
        setErr("Réservé aux gestionnaires.");
        return;
      }
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      appliquer((await r.json()) as ValidationConfig);
      setMsg(
        active
          ? "Validation bancaire activée — les pastilles ✓✓ apparaissent dans Paiements pour les immeubles mappés."
          : "Validation bancaire désactivée — aucune pastille n'est affichée."
      );
    } catch {
      setErr("Enregistrement impossible.");
    } finally {
      setBusy(null);
    }
  }

  async function decouvrir() {
    setBusy("decouvrir");
    setMsg(null);
    setErr(null);
    try {
      const r = await authedFetch(
        "/api/v1/immobilier/validation-bancaire/comptes/decouvrir",
        { method: "POST" }
      );
      if (!r.ok) {
        const t = await r.text();
        throw new Error(t.slice(0, 300) || `HTTP ${r.status}`);
      }
      const d = (await r.json()) as ValidationConfig;
      appliquer(d);
      setMsg(
        d.comptes.length > 0
          ? `${d.comptes.length} compte${d.comptes.length > 1 ? "s" : ""} « Loyer à remettre » trouvé${d.comptes.length > 1 ? "s" : ""} dans le plan comptable.`
          : "Aucun compte « Loyer à remettre - … » trouvé dans le plan comptable QuickBooks."
      );
    } catch (e) {
      setErr(`Découverte échouée : ${(e as Error).message}`);
    } finally {
      setBusy(null);
    }
  }

  async function saveCompte(c: CompteLoyer) {
    const sel = selections[c.id];
    if (!sel) return;
    setBusy(`compte-${c.id}`);
    setMsg(null);
    setErr(null);
    try {
      const r = await authedFetch(
        `/api/v1/immobilier/validation-bancaire/comptes/${c.id}`,
        {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            immeuble_ids: sel.tous ? [] : sel.immeuble_ids,
            tous_les_immeubles: sel.tous,
            actif: sel.actif
          })
        }
      );
      if (!r.ok) {
        const t = await r.text();
        throw new Error(t.slice(0, 300) || `HTTP ${r.status}`);
      }
      await load();
      setMsg(
        sel.tous
          ? `Compte « ${c.qbo_account_name} » relié à TOUS les immeubles internes.`
          : sel.immeuble_ids.length > 0
            ? `Compte « ${c.qbo_account_name} » relié à ${sel.immeuble_ids.length} immeuble${sel.immeuble_ids.length > 1 ? "s" : ""}.`
            : `Compte « ${c.qbo_account_name} » sans immeuble — il ne sera pas synchronisé.`
      );
    } catch (e) {
      setErr(`Enregistrement du compte échoué : ${(e as Error).message}`);
    } finally {
      setBusy(null);
    }
  }

  async function syncMaintenant() {
    setBusy("sync");
    setMsg(null);
    setErr(null);
    setRapport(null);
    try {
      const r = await authedFetch(
        "/api/v1/immobilier/validation-bancaire/sync",
        { method: "POST" }
      );
      if (!r.ok) {
        const t = await r.text();
        throw new Error(t.slice(0, 300) || `HTTP ${r.status}`);
      }
      const d = (await r.json()) as SyncRapport;
      await load();
      setRapport(d);
      setMsg(
        `Synchro terminée : ${d.comptes} compte${d.comptes > 1 ? "s" : ""} lu${d.comptes > 1 ? "s" : ""}, ${d.importees} transaction${d.importees > 1 ? "s" : ""} importée${d.importees > 1 ? "s" : ""}, ${d.mises_a_jour} mise${d.mises_a_jour > 1 ? "s" : ""} à jour, ${d.ignorees} ignorée${d.ignorees > 1 ? "s" : ""} — détail ci-dessous.`
      );
    } catch (e) {
      setErr(`Synchro échouée : ${(e as Error).message}`);
    } finally {
      setBusy(null);
    }
  }

  return (
    <>
      <h2 className="mt-8 flex items-center gap-2 text-xl font-bold text-white">
        <Landmark className="h-5 w-5 text-accent-500" />
        Validation bancaire (QuickBooks)
      </h2>
      <p className="mt-1 max-w-2xl text-sm text-white/60">
        2e validation des loyers : les encaissements que l&apos;adjointe
        publie dans QuickBooks (comptes « Loyer à remettre - immeuble »)
        sont lus — <strong>lecture seule</strong> — et croisés avec les
        paiements marqués dans Kratos. ✓✓ « Validé banque » quand la
        trace bancaire existe, ⚠ quand un loyer marqué payé n&apos;a
        toujours pas de trace après le délai choisi.
      </p>

      {err ? (
        <p className="mt-4 max-w-2xl rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">
          {err}
        </p>
      ) : null}
      {msg ? (
        <p className="mt-4 max-w-2xl rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-300">
          {msg}
        </p>
      ) : null}

      <div className="mt-4 max-w-3xl rounded-2xl border border-brand-800 bg-brand-900 p-5">
        {cfg === null ? (
          <div className="flex items-center justify-center py-10 text-white/40">
            <Loader2 className="h-5 w-5 animate-spin" />
          </div>
        ) : (
          <>
            {/* Interrupteur + délai d'alerte */}
            <div className="flex flex-wrap items-center gap-4">
              <label className="flex cursor-pointer items-center gap-2">
                <input
                  type="checkbox"
                  checked={active}
                  disabled={!canEdit}
                  onChange={(e) => setActive(e.target.checked)}
                  className="h-4 w-4 accent-[var(--accent-500,#f59e0b)]"
                />
                <span className="text-sm font-semibold text-white">
                  Activer la validation bancaire
                </span>
              </label>
              <div className="flex items-center gap-2 text-sm text-white/60">
                <span>⚠ « sans trace bancaire » après</span>
                <input
                  type="number"
                  min={1}
                  max={60}
                  value={jours}
                  disabled={!canEdit}
                  onChange={(e) =>
                    setJours(
                      Math.max(1, parseInt(e.target.value || "5", 10) || 5)
                    )
                  }
                  className="w-16 rounded-lg border border-brand-800 bg-brand-950 px-2 py-1 text-sm text-white focus:border-accent-500 focus:outline-none disabled:opacity-60"
                />
                <span>jours</span>
              </div>
              {canEdit ? (
                <button
                  type="button"
                  onClick={() => void saveReglages()}
                  disabled={busy === "reglages"}
                  className="btn-accent btn-sm disabled:opacity-50"
                >
                  {busy === "reglages" ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <Check className="h-4 w-4" />
                  )}
                  Enregistrer
                </button>
              ) : null}
            </div>
            <p className="mt-2 text-xs text-white/45">
              Tant que c&apos;est désactivé, rien ne change à l&apos;écran
              — aucune pastille, aucun encart. Les immeubles sans compte
              relié ne sont jamais affectés.
            </p>

            {/* Comptes découverts ↔ immeubles */}
            <div className="mt-5 flex flex-wrap items-center justify-between gap-2">
              <h3 className="text-xs font-semibold uppercase tracking-wider text-white/50">
                Comptes « Loyer à remettre » ↔ immeubles
              </h3>
              <div className="flex items-center gap-2">
                {canEdit ? (
                  <>
                    <button
                      type="button"
                      onClick={() => void decouvrir()}
                      disabled={busy === "decouvrir"}
                      title="Lit le plan comptable QuickBooks (lecture seule) et suggère le ou les immeubles de chaque compte"
                      className="inline-flex items-center gap-1.5 rounded-lg border border-white/15 bg-white/5 px-2.5 py-1 text-xs font-semibold text-white/70 transition hover:bg-white/10 disabled:opacity-50"
                    >
                      {busy === "decouvrir" ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      ) : (
                        <RefreshCw className="h-3.5 w-3.5" />
                      )}
                      Découvrir les comptes
                    </button>
                    <button
                      type="button"
                      onClick={() => void syncMaintenant()}
                      disabled={busy === "sync"}
                      title="Importe maintenant les transactions publiées des comptes reliés (90 derniers jours)"
                      className="inline-flex items-center gap-1.5 rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-2.5 py-1 text-xs font-semibold text-emerald-300 transition hover:bg-emerald-500/20 disabled:opacity-50"
                    >
                      {busy === "sync" ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      ) : (
                        <RefreshCw className="h-3.5 w-3.5" />
                      )}
                      Synchroniser maintenant
                    </button>
                  </>
                ) : null}
                <BoutonFilBancaire />
              </div>
            </div>

            {/* Rapport DÉTAILLÉ de la dernière synchro manuelle — parce
                que « 0 transaction importée » sans explication ne veut
                rien dire. Le cron loggue exactement la même chose. */}
            {rapport ? (
              <details
                className="mt-3 rounded-lg border border-brand-800 bg-brand-950/60"
                open
              >
                <summary className="cursor-pointer list-none px-3 py-2 text-xs font-semibold text-white/70 [&::-webkit-details-marker]:hidden">
                  Rapport de synchro — {rapport.importees} importée
                  {rapport.importees > 1 ? "s" : ""} ·{" "}
                  {rapport.mises_a_jour} mise
                  {rapport.mises_a_jour > 1 ? "s" : ""} à jour ·{" "}
                  {rapport.ignorees} ignorée
                  {rapport.ignorees > 1 ? "s" : ""}
                </summary>
                <ul className="space-y-1 border-t border-brand-800 px-3 py-2">
                  {rapport.details.map((d) => (
                    <li key={d.compte_id} className="text-xs text-white/60">
                      <span className="font-medium text-white/85">
                        {d.compte_nom}
                      </span>{" "}
                      : {d.lues} ligne{d.lues > 1 ? "s" : ""} lue
                      {d.lues > 1 ? "s" : ""}, {d.importees} importée
                      {d.importees > 1 ? "s" : ""}, {d.mises_a_jour} mise
                      {d.mises_a_jour > 1 ? "s" : ""} à jour,{" "}
                      {d.ignorees + d.raisons.deja_importee} ignorée
                      {d.ignorees + d.raisons.deja_importee > 1 ? "s" : ""}
                      {d.ignorees + d.raisons.deja_importee > 0 ? (
                        <span className="text-white/45">
                          {" ("}
                          {[
                            d.raisons.sortie_argent > 0
                              ? `${d.raisons.sortie_argent} sortie${d.raisons.sortie_argent > 1 ? "s" : ""} d'argent`
                              : null,
                            d.raisons.deja_importee > 0
                              ? `${d.raisons.deja_importee} déjà importée${d.raisons.deja_importee > 1 ? "s" : ""}`
                              : null,
                            d.raisons.montant_nul > 0
                              ? `${d.raisons.montant_nul} montant${d.raisons.montant_nul > 1 ? "s" : ""} nul${d.raisons.montant_nul > 1 ? "s" : ""}`
                              : null,
                            d.raisons.type_non_reconnu > 0
                              ? `${d.raisons.type_non_reconnu} type${d.raisons.type_non_reconnu > 1 ? "s" : ""} non reconnu${d.raisons.type_non_reconnu > 1 ? "s" : ""}${d.types_non_reconnus.length > 0 ? ` : ${d.types_non_reconnus.join(", ")}` : ""}`
                              : null
                          ]
                            .filter(Boolean)
                            .join(" · ")}
                          {")"}
                        </span>
                      ) : null}
                      {d.erreur ? (
                        <span className="text-rose-300">
                          {" "}
                          — erreur : {d.erreur}
                        </span>
                      ) : null}
                    </li>
                  ))}
                </ul>
              </details>
            ) : null}

            {cfg.comptes.length === 0 ? (
              <p className="mt-3 text-xs text-white/50">
                Aucun compte découvert pour l&apos;instant. Clique
                « Découvrir les comptes » — les comptes du plan comptable
                dont le nom contient « Loyer à remettre » apparaîtront
                ici avec le ou les immeubles suggérés.
              </p>
            ) : (
              <ul className="mt-3 space-y-2">
                {cfg.comptes.map((c) => {
                  const sel: SelectionCompte = selections[c.id] ?? {
                    immeuble_ids: c.immeuble_ids,
                    tous: c.tous_les_immeubles,
                    actif: c.actif
                  };
                  const confirme =
                    c.tous_les_immeubles || c.immeuble_ids.length > 0;
                  const suggere =
                    !confirme &&
                    (sel.tous || sel.immeuble_ids.length > 0) &&
                    (sel.tous === c.suggestion_tous &&
                      JSON.stringify([...sel.immeuble_ids].sort()) ===
                        JSON.stringify(
                          [...c.suggestion_immeuble_ids].sort()
                        ));
                  const modifie =
                    sel.tous !== c.tous_les_immeubles ||
                    sel.actif !== c.actif ||
                    JSON.stringify([...sel.immeuble_ids].sort()) !==
                      JSON.stringify([...c.immeuble_ids].sort());
                  const basculer = (id: number) => {
                    setSelections((s) => ({
                      ...s,
                      [c.id]: {
                        ...sel,
                        immeuble_ids: sel.immeuble_ids.includes(id)
                          ? sel.immeuble_ids.filter((x) => x !== id)
                          : [...sel.immeuble_ids, id]
                      }
                    }));
                  };
                  return (
                    <li
                      key={c.id}
                      className="rounded-lg border border-brand-800 bg-brand-950/60 px-3 py-2"
                    >
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-sm font-medium text-white">
                          {c.qbo_account_name}
                        </span>
                        {suggere ? (
                          <span
                            className="badge badge-amber"
                            title="Suggestion automatique d'après le nom du compte — à confirmer"
                          >
                            suggéré
                          </span>
                        ) : confirme ? (
                          <span
                            className="badge badge-emerald"
                            title={
                              c.tous_les_immeubles
                                ? "Relié à tous les immeubles internes"
                                : `Relié à ${c.immeuble_ids.length} immeuble${c.immeuble_ids.length > 1 ? "s" : ""}`
                            }
                          >
                            confirmé
                          </span>
                        ) : null}
                        <label className="flex cursor-pointer items-center gap-1.5 text-xs text-white/60">
                          <input
                            type="checkbox"
                            checked={sel.actif}
                            disabled={!canEdit}
                            onChange={(e) =>
                              setSelections((s) => ({
                                ...s,
                                [c.id]: { ...sel, actif: e.target.checked }
                              }))
                            }
                            className="h-3.5 w-3.5 accent-[var(--accent-500,#f59e0b)]"
                          />
                          actif
                        </label>
                        {c.derniere_synchro_le ? (
                          <span className="text-[10px] text-white/35">
                            synchro {c.derniere_synchro_le.slice(0, 10)}
                          </span>
                        ) : null}
                        {canEdit ? (
                          <button
                            type="button"
                            onClick={() => void saveCompte(c)}
                            disabled={busy === `compte-${c.id}` || !modifie}
                            className="ml-auto inline-flex items-center gap-1 rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-2.5 py-1 text-xs font-semibold text-emerald-300 transition hover:bg-emerald-500/20 disabled:opacity-40"
                          >
                            {busy === `compte-${c.id}` ? (
                              <Loader2 className="h-3 w-3 animate-spin" />
                            ) : (
                              <Check className="h-3 w-3" />
                            )}
                            Confirmer
                          </button>
                        ) : null}
                      </div>
                      {/* Case « tous » (compte fiducie) + sélection fine
                          en pastilles cochables — un compte QBO peut
                          couvrir PLUSIEURS immeubles. */}
                      <div className="mt-2 flex flex-wrap items-center gap-1.5">
                        <label
                          className="flex cursor-pointer items-center gap-1.5 rounded-full border border-brand-800 bg-brand-950 px-2.5 py-1 text-xs text-white/70"
                          title="Compte fourre-tout (ex. fiducie des virements Interac) : les encaissements peuvent venir de n'importe quel immeuble interne"
                        >
                          <input
                            type="checkbox"
                            checked={sel.tous}
                            disabled={!canEdit}
                            onChange={(e) =>
                              setSelections((s) => ({
                                ...s,
                                [c.id]: { ...sel, tous: e.target.checked }
                              }))
                            }
                            className="h-3.5 w-3.5 accent-[var(--accent-500,#f59e0b)]"
                          />
                          Tous les immeubles internes
                        </label>
                        {cfg.immeubles.map((i) => {
                          const coche = sel.immeuble_ids.includes(i.id);
                          return (
                            <button
                              key={i.id}
                              type="button"
                              disabled={!canEdit || sel.tous}
                              onClick={() => basculer(i.id)}
                              aria-pressed={coche}
                              className={`rounded-full border px-2.5 py-1 text-xs transition disabled:cursor-not-allowed disabled:opacity-40 ${
                                coche
                                  ? "border-emerald-500/50 bg-emerald-500/15 font-semibold text-emerald-300"
                                  : "border-brand-800 bg-brand-950 text-white/60 hover:bg-white/5"
                              }`}
                            >
                              {i.name}
                            </button>
                          );
                        })}
                      </div>
                    </li>
                  );
                })}
              </ul>
            )}

            <p className="mt-4 rounded-lg border border-brand-800 bg-brand-950/60 px-3 py-2 text-xs text-white/55">
              Kratos ne fait que LIRE QuickBooks — rien n&apos;est écrit
              dans la comptabilité. La synchro tourne aussi chaque nuit
              (fenêtre glissante de 90 jours). Les immeubles en gestion
              externe sont exclus : la perception y est déléguée.
            </p>

            {/* Aide : comment le mois d'un versement est déterminé. */}
            <div className="mt-3 rounded-lg border border-brand-800 bg-brand-950/60 px-3 py-2 text-xs text-white/55">
              <p className="font-semibold text-white/75">
                Comment le mois d&apos;un versement est déterminé
              </p>
              <p className="mt-1">
                La date de la transaction donne le mois. Si le montant ne
                colle pas à ce mois-là mais correspond à ce qui est dû le
                mois d&apos;avant ou d&apos;après, le versement est
                rattaché à ce mois — ex. un virement reçu le 31 juillet
                compte pour août si juillet est déjà réglé et que le
                montant correspond au dû d&apos;août. Un montant égal à
                plusieurs mois de retard consécutifs (ex. 2 × 650&nbsp;$
                = 1&nbsp;300&nbsp;$) couvre tous ces mois d&apos;un coup,
                en commençant par le plus ancien. En cas de doute (deux
                baux possibles), rien n&apos;est deviné : la transaction
                reste « à rapprocher » et tu choisis le bail toi-même.
              </p>
            </div>

            {!canEdit ? (
              <p className="mt-3 text-xs text-white/50">
                Lecture seule — modification réservée aux gestionnaires.
              </p>
            ) : null}
          </>
        )}
      </div>
    </>
  );
}
