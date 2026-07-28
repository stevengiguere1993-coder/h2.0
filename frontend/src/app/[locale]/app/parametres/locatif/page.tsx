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
import { Check, History, Loader2 } from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { useAppLayout } from "../../layout";
import { authedFetch, hasMinRole } from "@/lib/auth";
import { useCurrentUser } from "@/hooks/use-current-user";

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
      </div>
    </>
  );
}
