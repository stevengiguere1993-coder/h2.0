"use client";

/**
 * Admin locative → onglet « Baux » (Phil 2026-11-10).
 *
 * Un bail officiel du TAL (formulaire 53000BAIL) SANS fiche Kratos : rien n'est
 * rattaché à un immeuble, un locataire, un dossier de location ni à la
 * facturation ; le locateur nommé signe lui-même. « Nouveau bail » ouvre
 * directement l'écran complet du bail (Phil 2026-11-13 : le petit formulaire
 * d'avant redemandait les mêmes choses) : tous les champs, la vérification, la
 * génération (simulation ou réel, selon Paramètres), le PDF, la signature. Le
 * brouillon naît à la première vérification. Chaque personne se choisit dans le
 * carnet de la section ; une personne saisie à la main y entre d'elle-même.
 */

import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, Copy, FileSignature, FileText, Loader2, Plus, Settings, Trash2 } from "lucide-react";

import { useConfirm } from "@/components/confirm-dialog";
import {
  TalBailModal,
  libelleModeTal,
  ouvrirPdfDocument,
  type SignatureEtat,
  type TalTransmission
} from "@/components/immobilier/tal-bail-modal";
import { authedFetch } from "@/lib/auth";
import { BASE_TAL as BASE, type Contact, argent, dateFr, lireErreur, nombre } from "./commun";

type Etat = {
  connexion: { mode: string; pret_pour_reel: boolean; cle_configuree: boolean; url_configuree: boolean };
  compteur: { gratuits_restants: number; total_reel_depuis_le_debut: number };
  cout_tal: number;
  gratuits_total: number;
  /** Réglages du bail officiel ; « requis » = chemins des champs exigés avant l'envoi. */
  config?: { requis?: string };
};
type Item = TalTransmission & { signature: SignatureEtat | null };
function titreDe(t: Item): string {
  return (t.libelle || "").trim() || (t.adresse || "").trim() || `Bail n° ${t.id}`;
}

/** Où en est ce bail, en un mot. */
function etatDe(t: Item): { label: string; cls: string } {
  if (t.signe_le || t.signature?.statut === "complete") return { label: "Signé", cls: "badge-emerald" };
  if (t.statut === "transmise" && t.signature) {
    if (t.signature.statut === "envoye") return { label: `En signature ${t.signature.nb_signes}/${t.signature.nb_signataires}`, cls: "badge-violet" };
    if (["refuse", "expire", "annule"].includes(t.signature.statut)) return { label: "Signature interrompue", cls: "badge-rose" };
    return { label: "Signature à envoyer", cls: "badge-sky" };
  }
  if (t.statut === "transmise") return { label: "Généré", cls: "badge-emerald" };
  if (t.statut === "forme_creee") return { label: "Envoi à relancer", cls: "badge-amber" };
  if (t.statut === "echec") return { label: "Échec", cls: "badge-rose" };
  if (t.statut === "annulee") return { label: "Annulé", cls: "badge-neutral" };
  return { label: "Brouillon", cls: "badge-neutral" };
}

export function BauxTab({
  onCarnetChange,
  onOuvrirConnexion
}: {
  /** Le carnet se lit maintenant dans l'écran du bail ; la page le garde pour ses autres onglets. */
  contacts?: Contact[];
  onCarnetChange: () => void;
  /** Ouvre l'onglet « Connexion au TAL » (mode, adresse, clé). */
  onOuvrirConnexion: () => void;
}) {
  const confirm = useConfirm();
  const [etat, setEtat] = useState<Etat | null>(null);
  const [items, setItems] = useState<Item[]>([]);
  const [charge, setCharge] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [nouveau, setNouveau] = useState(false);
  const [ouvert, setOuvert] = useState<Item | null>(null);
  const [busy, setBusy] = useState<number | null>(null);

  const charger = useCallback(async () => {
    try {
      const [re, rl] = await Promise.all([authedFetch(`${BASE}/etat`), authedFetch(`${BASE}/independants`)]);
      if (!re.ok) throw new Error(await lireErreur(re));
      if (!rl.ok) throw new Error(await lireErreur(rl));
      setEtat((await re.json()) as Etat);
      setItems(((await rl.json()) as { items: Item[] }).items);
      setErr(null);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setCharge(false);
    }
  }, []);

  useEffect(() => {
    void charger();
  }, [charger]);

  async function dupliquer(t: Item) {
    setBusy(t.id);
    setErr(null);
    try {
      const r = await authedFetch(`${BASE}/independants`, {
        method: "POST",
        body: JSON.stringify({ source_id: t.id, libelle: `${titreDe(t)} (copie)`.slice(0, 255) })
      });
      if (!r.ok) throw new Error(await lireErreur(r));
      const cree = (await r.json()) as Item;
      await charger();
      setOuvert({ ...cree, signature: null });
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function annuler(t: Item) {
    const ok = await confirm({
      title: `Annuler « ${titreDe(t)} » ?`,
      description: "Le brouillon sort de la liste. Rien n'a été envoyé au TAL, rien n'est facturé.",
      confirmLabel: "Annuler ce bail",
      destructive: true
    });
    if (!ok) return;
    setBusy(t.id);
    setErr(null);
    try {
      const r = await authedFetch(`${BASE}/transmissions/${t.id}/annuler`, { method: "POST" });
      if (!r.ok) throw new Error(await lireErreur(r));
      await charger();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  const reel = etat?.connexion.mode === "reel";
  const pasPret = reel && !etat?.connexion.pret_pour_reel;

  return (
    <>
      {nouveau ? (
        <TalBailModal
          nouveauIndependant
          titre="Nouveau bail"
          onClose={() => {
            setNouveau(false);
            void charger();
            onCarnetChange();
          }}
          onDone={() => void charger()}
        />
      ) : null}
      {ouvert ? (
        <TalBailModal
          transmissionId={ouvert.id}
          titre={titreDe(ouvert)}
          onClose={() => {
            setOuvert(null);
            void charger();
            onCarnetChange();
          }}
          onDone={() => void charger()}
        />
      ) : null}

      <div>
        <div className="flex flex-wrap items-start gap-3">
          <div className="min-w-0 flex-1">
            <p className="max-w-3xl text-sm text-white/60">
              Un bail officiel du Tribunal administratif du logement pour quelqu&apos;un qui n&apos;est pas dans Kratos : un
              essai, ou le bail d&apos;un proche. Rien n&apos;est rattaché à un immeuble, à un locataire ni à la facturation,
              et le locateur nommé au bail signe lui-même.
            </p>
          </div>
          <button type="button" onClick={() => setNouveau(true)} className="btn-accent btn-sm">
            <Plus className="h-4 w-4" /> Nouveau bail
          </button>
        </div>

        {/* Mode et compteur */}
        {etat ? (
          <div className="mt-4 grid gap-3 sm:grid-cols-3">
            <div className={`rounded-xl border p-3 ${reel ? "border-amber-500/40 bg-amber-500/10" : "border-brand-800 bg-brand-900"}`}>
              <p className="text-[11px] font-semibold uppercase tracking-wider text-white/50">Mode</p>
              <p className="mt-0.5 text-sm font-bold text-white">{reel ? "Réel" : "Simulation"}</p>
              <p className="mt-0.5 text-xs text-white/60">
                {reel
                  ? `Chaque bail généré est facturé ${etat.cout_tal.toFixed(2).replace(".", ",")} $ + taxes par le TAL.`
                  : "Aucun appel au TAL : PDF marqué « SIMULATION », 0 $."}
              </p>
              {pasPret ? (
                <p className="mt-1 flex items-center gap-1 text-xs text-amber-200">
                  <AlertTriangle className="h-3.5 w-3.5" /> {etat.connexion.cle_configuree ? "Adresse de l'API manquante." : "Clé de l'API manquante."}
                </p>
              ) : null}
            </div>
            <div className="rounded-xl border border-brand-800 bg-brand-900 p-3">
              <p className="text-[11px] font-semibold uppercase tracking-wider text-white/50">Baux gratuits restants</p>
              <p className="mt-0.5 text-sm font-bold text-white">
                {etat.compteur.gratuits_restants} sur {etat.gratuits_total}
              </p>
              <p className="mt-0.5 text-xs text-white/60">
                {etat.compteur.total_reel_depuis_le_debut} bail(s) officiel(s) généré(s) depuis le début. Une erreur avant la
                réception du PDF ne consomme rien.
              </p>
            </div>
            <div className="rounded-xl border border-brand-800 bg-brand-900 p-3">
              <p className="text-[11px] font-semibold uppercase tracking-wider text-white/50">Connexion au TAL</p>
              <p className="mt-0.5 text-xs text-white/60">
                {etat.connexion.cle_configuree ? "Clé de l'API enregistrée." : "Aucune clé de l'API enregistrée."}{" "}
                {etat.connexion.url_configuree ? "Adresse de l'API enregistrée." : "Adresse de l'API à saisir."}
              </p>
              <button type="button" onClick={onOuvrirConnexion} className="btn-secondary btn-xs mt-2 inline-flex">
                <Settings className="h-3.5 w-3.5" /> Mode, adresse et clé de l&apos;API
              </button>
            </div>
          </div>
        ) : null}

        {err ? (
          <p className="mt-4 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-200">{err}</p>
        ) : null}

        {/* Liste */}
        <section className="mt-4 rounded-xl border border-brand-800 bg-brand-900">
          <h2 className="border-b border-brand-800 px-4 py-3 text-xs font-semibold uppercase tracking-wider text-accent-500">
            Baux indépendants ({items.length})
          </h2>
          {charge ? (
            <div className="flex items-center gap-2 px-4 py-10 text-sm text-white/50">
              <Loader2 className="h-4 w-4 animate-spin" /> Chargement…
            </div>
          ) : items.length === 0 ? (
            <div className="px-4 py-10 text-center">
              <p className="text-sm text-white/60">Aucun bail indépendant pour l&apos;instant.</p>
              <button type="button" onClick={() => setNouveau(true)} className="btn-outline-accent btn-sm mt-3">
                <Plus className="h-4 w-4" /> Créer le premier
              </button>
            </div>
          ) : (
            <ul className="divide-y divide-brand-800">
              {items.map((t) => {
                const e = etatDe(t);
                const p = t.parties;
                const ouvrable = t.statut !== "annulee";
                return (
                  <li key={t.id} className="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3">
                    <button
                      type="button"
                      disabled={!ouvrable}
                      onClick={() => setOuvert(t)}
                      className="min-w-[220px] flex-1 text-left disabled:cursor-default"
                    >
                      <p className="truncate text-sm font-semibold text-white">{titreDe(t)}</p>
                      <p className="mt-0.5 truncate text-xs text-white/55">
                        {t.libelle && t.adresse ? `${t.adresse} · ` : ""}
                        {p?.locateurs.length ? p.locateurs.join(", ") : "locateur à saisir"} →{" "}
                        {p?.locataires.length ? p.locataires.join(", ") : "locataire à saisir"}
                        {p?.loyer ? ` · ${nombre(p.loyer) !== null ? argent(nombre(p.loyer)) : `${p.loyer} $`}` : ""}
                        {p?.date_debut ? ` · dès le ${dateFr(p.date_debut)}` : ""}
                      </p>
                      {t.erreur && t.statut !== "transmise" ? (
                        <p className="mt-0.5 truncate text-xs text-rose-300" title={t.erreur}>
                          {t.erreur}
                        </p>
                      ) : null}
                    </button>
                    <span className={`badge ${e.cls}`}>{e.label}</span>
                    {t.statut === "transmise" ? (
                      <span className={`badge ${t.mode === "reel" ? "badge-amber" : "badge-neutral"}`}>{libelleModeTal(t.mode)}</span>
                    ) : null}
                    <span className="text-xs text-white/40">{dateFr(t.genere_le || t.created_at)}</span>
                    <div className="flex items-center gap-1">
                      {t.document_id ? (
                        <button
                          type="button"
                          className="btn-ghost btn-xs"
                          title="Voir le PDF du bail"
                          onClick={() => void ouvrirPdfDocument(t.document_id as number).catch((x) => setErr((x as Error).message))}
                        >
                          <FileText className="h-3.5 w-3.5" /> PDF
                        </button>
                      ) : null}
                      {t.document_signe_id ? (
                        <button
                          type="button"
                          className="btn-ghost btn-xs"
                          title="Voir le PDF signé"
                          onClick={() => void ouvrirPdfDocument(t.document_signe_id as number).catch((x) => setErr((x as Error).message))}
                        >
                          <FileSignature className="h-3.5 w-3.5" /> Signé
                        </button>
                      ) : null}
                      <button
                        type="button"
                        className="btn-ghost btn-xs"
                        title="Nouveau brouillon avec le même formulaire"
                        disabled={busy === t.id}
                        onClick={() => void dupliquer(t)}
                      >
                        <Copy className="h-3.5 w-3.5" /> Dupliquer
                      </button>
                      {t.statut === "brouillon" || t.statut === "echec" ? (
                        <button
                          type="button"
                          className="btn-ghost btn-xs text-rose-300"
                          title="Annuler ce brouillon"
                          disabled={busy === t.id}
                          onClick={() => void annuler(t)}
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      ) : null}
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </section>

        <p className="mt-3 max-w-3xl text-xs text-white/40">
          Le contrat avec le TAL exige qu&apos;un bail généré réponde à un besoin réel et immédiat de signature : pas de
          génération d&apos;avance ni en lot. Le PDF du TAL est archivé tel quel, jamais modifié.
        </p>
      </div>
    </>
  );
}
