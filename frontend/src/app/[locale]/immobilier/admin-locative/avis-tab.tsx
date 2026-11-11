"use client";

/**
 * Admin locative → onglet « Avis de renouvellement » (Phil 2026-11-10).
 *
 * L'avis d'augmentation de loyer et de modification du bail (formulaire officiel
 * TAL-806) pour un bail HORS SYSTÈME : mêmes PDF, même envoi et même page de
 * réponse du locataire (accepter, refuser, quitter) que « Suivis annuels », mais
 * sans fiche Kratos. Les personnes se choisissent dans le carnet de la section.
 *
 * Deux règles tenues par le serveur : l'avis porte toujours la date du jour de
 * son envoi (elle ne se saisit pas) et un avis envoyé ne se modifie plus.
 * Rien ne part tout seul : chaque envoi est un geste, avec le destinataire
 * affiché avant de confirmer.
 */

import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, CalendarClock, Copy, FileText, Loader2, Pencil, Plus, RefreshCw, Send, Trash2 } from "lucide-react";

import { useConfirm } from "@/components/confirm-dialog";
import { ouvrirPdfDocument } from "@/components/immobilier/tal-bail-modal";
import { authedFetch } from "@/lib/auth";
import {
  BASE_ADMIN as BASE,
  Bloc,
  Champ,
  ChoisirContact,
  type Contact,
  Etoile,
  Fenetre,
  NoteCarnetVide,
  argent,
  dateFr,
  dateInstantFr,
  lireErreur,
  nombre
} from "./commun";

type FenetreLegale = { du: string; au: string; regle: string; etat: "avant" | "dans" | "apres" };

type Avis = {
  id: number;
  libelle: string | null;
  titre: string;
  adresse: string;
  locateur_nom: string | null;
  locateur_adresse: string | null;
  locateur_telephone: string | null;
  locateur_courriel: string | null;
  locataire_nom: string | null;
  locataire_courriel: string | null;
  logement_adresse: string | null;
  logement_numero: string | null;
  logement_ville: string | null;
  bail_date_debut: string | null;
  bail_date_fin: string | null;
  loyer_actuel: number | null;
  modif_mode: string | null;
  nouveau_loyer: number | null;
  hausse_montant: number | null;
  hausse_pct: number | null;
  nouvelle_date_debut: string | null;
  nouvelle_date_fin: string | null;
  autres_modifications: string | null;
  status: string;
  avis_envoye_le: string | null;
  reponse_le: string | null;
  refus_motif: string | null;
  echeance_reponse: string | null;
  document_id: number | null;
  envoye_a: string | null;
  fenetre: FenetreLegale | null;
  created_by_email: string | null;
  created_at: string | null;
  document?: { envoye_le: string | null; ouvert_le: string | null; signed_at: string | null; signed_by_name: string | null };
};

type F = {
  libelle: string;
  locateur_nom: string;
  locateur_adresse: string;
  locateur_telephone: string;
  locateur_courriel: string;
  locataire_nom: string;
  locataire_courriel: string;
  logement_adresse: string;
  logement_numero: string;
  logement_ville: string;
  bail_date_debut: string;
  bail_date_fin: string;
  loyer_actuel: string;
  modif_mode: string;
  nouveau_loyer: string;
  hausse_montant: string;
  hausse_pct: string;
  nouvelle_date_debut: string;
  nouvelle_date_fin: string;
  autres_modifications: string;
};

const F_VIDE: F = {
  libelle: "",
  locateur_nom: "",
  locateur_adresse: "",
  locateur_telephone: "",
  locateur_courriel: "",
  locataire_nom: "",
  locataire_courriel: "",
  logement_adresse: "",
  logement_numero: "",
  logement_ville: "",
  bail_date_debut: "",
  bail_date_fin: "",
  loyer_actuel: "",
  modif_mode: "nouveau_loyer",
  nouveau_loyer: "",
  hausse_montant: "",
  hausse_pct: "",
  nouvelle_date_debut: "",
  nouvelle_date_fin: "",
  autres_modifications: ""
};

function texteDe(n: number | null): string {
  return n == null ? "" : String(n).replace(".", ",");
}

function versF(a: Avis): F {
  return {
    libelle: a.libelle || "",
    locateur_nom: a.locateur_nom || "",
    locateur_adresse: a.locateur_adresse || "",
    locateur_telephone: a.locateur_telephone || "",
    locateur_courriel: a.locateur_courriel || "",
    locataire_nom: a.locataire_nom || "",
    locataire_courriel: a.locataire_courriel || "",
    logement_adresse: a.logement_adresse || "",
    logement_numero: a.logement_numero || "",
    logement_ville: a.logement_ville || "",
    bail_date_debut: a.bail_date_debut || "",
    bail_date_fin: a.bail_date_fin || "",
    loyer_actuel: texteDe(a.loyer_actuel),
    modif_mode: a.modif_mode || "",
    nouveau_loyer: texteDe(a.nouveau_loyer),
    hausse_montant: texteDe(a.hausse_montant),
    hausse_pct: texteDe(a.hausse_pct),
    nouvelle_date_debut: a.nouvelle_date_debut || "",
    nouvelle_date_fin: a.nouvelle_date_fin || "",
    autres_modifications: a.autres_modifications || ""
  };
}

function isoDe(d: Date): string {
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

/** Reconduction d'un an : du lendemain de la fin du bail au même jour un an plus tard. */
function reconduction(finIso: string): { debut: string; fin: string } | null {
  const [y, m, d] = finIso.split("-").map(Number);
  if (!y || !m || !d) return null;
  const debut = new Date(y, m - 1, d + 1);
  const fin = new Date(debut.getFullYear() + 1, debut.getMonth(), debut.getDate() - 1);
  return { debut: isoDe(debut), fin: isoDe(fin) };
}

/** Même jour, un mois plus tard (délai de réponse et délai de recours). */
function plusUnMois(iso: string | null): string {
  if (!iso) return "";
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  if (!y || !m || !d) return "";
  const dernier = new Date(y, m + 1, 0).getDate();
  return isoDe(new Date(y, m, Math.min(d, dernier)));
}

function titreDe(a: Avis): string {
  return (a.libelle || "").trim() || a.adresse || `Avis n° ${a.id}`;
}

function modificationDe(a: Avis): string {
  const morceaux: string[] = [];
  if (a.modif_mode === "nouveau_loyer" && a.nouveau_loyer != null) {
    morceaux.push(a.loyer_actuel != null ? `loyer de ${argent(a.loyer_actuel)} à ${argent(a.nouveau_loyer)}` : `nouveau loyer de ${argent(a.nouveau_loyer)}`);
  } else if (a.modif_mode === "hausse_montant" && a.hausse_montant != null) {
    morceaux.push(`hausse de ${argent(a.hausse_montant)} par mois`);
  } else if (a.modif_mode === "hausse_pct" && a.hausse_pct != null) {
    morceaux.push(`hausse de ${texteDe(a.hausse_pct)} %`);
  }
  if ((a.autres_modifications || "").trim()) morceaux.push("autre modification au bail");
  return morceaux.join(" · ") || "aucune modification indiquée";
}

function etatDe(a: Avis): { label: string; cls: string } {
  switch (a.status) {
    case "propose":
      return { label: "Envoyé, réponse attendue", cls: "badge-sky" };
    case "accepte":
      return { label: "Accepté", cls: "badge-emerald" };
    case "repute_accepte":
      return { label: "Réputé accepté", cls: "badge-emerald" };
    case "refuse":
      return { label: "Refusé", cls: "badge-rose" };
    case "depart":
      return { label: "Quitte le logement", cls: "badge-amber" };
    case "annule":
      return { label: "Annulé", cls: "badge-neutral" };
    default:
      return { label: "Brouillon", cls: "badge-neutral" };
  }
}

/** Où en est l'avis, en une phrase : quand l'envoyer, puis la réponse du locataire. */
function Suivi({ a }: { a: Avis }) {
  const f = a.fenetre;
  if (a.status === "brouillon") {
    if (!f) return <p className="mt-0.5 text-xs text-white/45">Indique la fin du bail pour connaître la période où l&apos;avis doit être donné.</p>;
    if (f.etat === "dans") {
      return (
        <p className="mt-0.5 text-xs text-emerald-300">
          À envoyer d&apos;ici le {dateFr(f.au)} ({f.regle}).
        </p>
      );
    }
    if (f.etat === "avant") {
      return (
        <p className="mt-0.5 text-xs text-white/55">
          À envoyer entre le {dateFr(f.du)} et le {dateFr(f.au)} ({f.regle}).
        </p>
      );
    }
    return (
      <p className="mt-0.5 text-xs text-amber-300">
        Délai légal dépassé depuis le {dateFr(f.au)} ({f.regle}).
      </p>
    );
  }
  if (a.status === "propose") {
    return (
      <p className="mt-0.5 text-xs text-white/55">
        Envoyé le {dateFr(a.avis_envoye_le)} à {a.envoye_a || "—"}. Réponse attendue au plus tard le {dateFr(a.echeance_reponse)} ; sans
        réponse, l&apos;avis est réputé accepté.{" "}
        {a.document?.ouvert_le ? `Ouvert par le locataire le ${dateInstantFr(a.document.ouvert_le)}.` : "Pas encore ouvert par le locataire."}
        {f && f.etat !== "dans" ? ` Envoyé hors de la période prévue par la loi (${f.regle}).` : ""}
      </p>
    );
  }
  if (a.status === "accepte") {
    return (
      <p className="mt-0.5 text-xs text-white/55">
        Accepté le {dateFr(a.reponse_le)}
        {a.document?.signed_by_name ? ` par ${a.document.signed_by_name}` : ""}. La réponse signée est dans le PDF.
      </p>
    );
  }
  if (a.status === "repute_accepte") {
    return (
      <p className="mt-0.5 text-xs text-white/55">
        Aucune réponse au {dateFr(a.reponse_le)} : l&apos;avis envoyé le {dateFr(a.avis_envoye_le)} est réputé accepté (art. 1945 du Code civil).
      </p>
    );
  }
  if (a.status === "refuse") {
    const limite = plusUnMois(a.reponse_le);
    return (
      <p className="mt-0.5 text-xs text-white/55">
        Refusé le {dateFr(a.reponse_le)}
        {a.refus_motif ? ` — « ${a.refus_motif} »` : ""}. Le locateur a un mois{limite ? `, soit jusqu'au ${dateFr(limite)},` : ""} pour demander
        au TAL de fixer le loyer ; sinon le bail se renouvelle aux conditions actuelles (art. 1947 du Code civil).
      </p>
    );
  }
  if (a.status === "depart") {
    return (
      <p className="mt-0.5 text-xs text-white/55">
        Le locataire a répondu le {dateFr(a.reponse_le)} qu&apos;il quitte le logement à la fin du bail
        {a.bail_date_fin ? `, le ${dateFr(a.bail_date_fin)}` : ""}.
      </p>
    );
  }
  return <p className="mt-0.5 text-xs text-white/45">Annulé. Le lien envoyé au locataire ne fonctionne plus.</p>;
}

export function AvisTab({ contacts, onCarnetChange }: { contacts: Contact[]; onCarnetChange: () => void }) {
  const confirm = useConfirm();
  const [items, setItems] = useState<Avis[]>([]);
  const [aujourdHui, setAujourdHui] = useState("");
  const [charge, setCharge] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [annules, setAnnules] = useState(false);
  const [edition, setEdition] = useState<{ avis: Avis | null; modele: Avis | null } | null>(null);
  const [envoi, setEnvoi] = useState<Avis | null>(null);
  const [busy, setBusy] = useState<number | null>(null);

  const charger = useCallback(async () => {
    try {
      const r = await authedFetch(`${BASE}/avis${annules ? "?inclure_annules=true" : ""}`);
      if (!r.ok) throw new Error(await lireErreur(r));
      const d = (await r.json()) as { items: Avis[]; aujourd_hui: string };
      setItems(d.items);
      setAujourdHui(d.aujourd_hui);
      setErr(null);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setCharge(false);
    }
  }, [annules]);

  useEffect(() => {
    void charger();
  }, [charger]);

  async function annuler(a: Avis) {
    const envoye = a.status === "propose";
    const ok = await confirm({
      title: `Annuler « ${titreDe(a)} » ?`,
      description: envoye
        ? "Cet avis est déjà parti : le lien de réponse du locataire cessera de fonctionner. Préviens-le si un nouvel avis suit."
        : "Le brouillon sort de la liste. Rien n'a été envoyé.",
      confirmLabel: "Annuler cet avis",
      destructive: true
    });
    if (!ok) return;
    setBusy(a.id);
    setErr(null);
    setInfo(null);
    try {
      const r = await authedFetch(`${BASE}/avis/${a.id}/annuler`, { method: "POST" });
      if (!r.ok) throw new Error(await lireErreur(r));
      await charger();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  return (
    <>
      {edition ? (
        <AvisForm
          avis={edition.avis}
          modele={edition.modele}
          contacts={contacts}
          onClose={() => setEdition(null)}
          onSaved={(a, voirPdf) => {
            setEdition(null);
            setInfo(null);
            void charger();
            onCarnetChange();
            if (voirPdf && a.document_id) void ouvrirPdfDocument(a.document_id).catch((x) => setErr((x as Error).message));
          }}
        />
      ) : null}
      {envoi ? (
        <EnvoyerAvis
          avis={envoi}
          aujourdHui={aujourdHui}
          onClose={() => setEnvoi(null)}
          onEnvoye={(a, premier) => {
            setEnvoi(null);
            setInfo(
              premier
                ? `Avis envoyé à ${a.envoye_a}. Le locataire a jusqu'au ${dateFr(a.echeance_reponse)} pour répondre.`
                : `Lien de réponse renvoyé à ${a.envoye_a}. L'avis garde sa date du ${dateFr(a.avis_envoye_le)}.`
            );
            void charger();
          }}
        />
      ) : null}

      <div>
        <div className="flex flex-wrap items-start gap-3">
          <div className="min-w-0 flex-1">
            <p className="max-w-3xl text-sm text-white/60">
              L&apos;avis d&apos;augmentation de loyer et de modification du bail, sur le formulaire officiel du TAL, pour un bail qui n&apos;est
              pas dans Kratos. Le locataire reçoit un lien et répond en ligne : il accepte, il refuse ou il annonce son départ. L&apos;avis
              porte la date du jour de son envoi et ne se modifie plus une fois parti.
            </p>
          </div>
          <button type="button" onClick={() => void charger()} className="btn-secondary btn-sm" title="Relire les réponses des locataires">
            <RefreshCw className="h-4 w-4" /> Actualiser
          </button>
          <button type="button" onClick={() => setEdition({ avis: null, modele: null })} className="btn-accent btn-sm">
            <Plus className="h-4 w-4" /> Nouvel avis
          </button>
        </div>

        {info ? (
          <p className="mt-4 rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-200">{info}</p>
        ) : null}
        {err ? <p className="mt-4 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-200">{err}</p> : null}

        <section className="mt-4 rounded-xl border border-brand-800 bg-brand-900">
          <div className="flex flex-wrap items-center gap-3 border-b border-brand-800 px-4 py-3">
            <h2 className="text-xs font-semibold uppercase tracking-wider text-accent-500">Avis de renouvellement ({items.length})</h2>
            <label className="ml-auto inline-flex items-center gap-1.5 text-xs text-white/60">
              <input type="checkbox" checked={annules} onChange={(ev) => setAnnules(ev.target.checked)} />
              Afficher les avis annulés
            </label>
          </div>
          {charge ? (
            <div className="flex items-center gap-2 px-4 py-10 text-sm text-white/50">
              <Loader2 className="h-4 w-4 animate-spin" /> Chargement…
            </div>
          ) : items.length === 0 ? (
            <div className="px-4 py-10 text-center">
              <p className="text-sm text-white/60">Aucun avis pour l&apos;instant.</p>
              <button type="button" onClick={() => setEdition({ avis: null, modele: null })} className="btn-outline-accent btn-sm mt-3">
                <Plus className="h-4 w-4" /> Préparer le premier
              </button>
            </div>
          ) : (
            <ul className="divide-y divide-brand-800">
              {items.map((a) => {
                const e = etatDe(a);
                const brouillon = a.status === "brouillon";
                const envoye = a.status === "propose";
                return (
                  <li key={a.id} className="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3">
                    <div className="min-w-[240px] flex-1">
                      <p className="truncate text-sm font-semibold text-white">{titreDe(a)}</p>
                      <p className="mt-0.5 truncate text-xs text-white/55">
                        {a.libelle && a.adresse ? `${a.adresse} · ` : ""}
                        {a.locateur_nom || "locateur à saisir"} → {a.locataire_nom || "locataire à saisir"} · {modificationDe(a)}
                      </p>
                      <Suivi a={a} />
                    </div>
                    <span className={`badge ${e.cls}`}>{e.label}</span>
                    <div className="flex flex-wrap items-center gap-1">
                      {a.document_id ? (
                        <button
                          type="button"
                          className="btn-ghost btn-xs"
                          title={brouillon ? "Aperçu du PDF. La date de l'avis sera celle du jour de l'envoi." : "Voir le PDF de l'avis"}
                          onClick={() => void ouvrirPdfDocument(a.document_id as number).catch((x) => setErr((x as Error).message))}
                        >
                          <FileText className="h-3.5 w-3.5" /> PDF
                        </button>
                      ) : null}
                      {brouillon ? (
                        <button type="button" className="btn-ghost btn-xs" onClick={() => setEdition({ avis: a, modele: null })}>
                          <Pencil className="h-3.5 w-3.5" /> Modifier
                        </button>
                      ) : null}
                      {brouillon || envoye ? (
                        <button type="button" className="btn-outline-accent btn-xs" onClick={() => setEnvoi(a)}>
                          <Send className="h-3.5 w-3.5" /> {brouillon ? "Envoyer" : "Renvoyer le lien"}
                        </button>
                      ) : null}
                      <button
                        type="button"
                        className="btn-ghost btn-xs"
                        title="Nouveau brouillon avec les mêmes personnes et le même logement"
                        onClick={() => setEdition({ avis: null, modele: a })}
                      >
                        <Copy className="h-3.5 w-3.5" /> Dupliquer
                      </button>
                      {brouillon || envoye ? (
                        <button
                          type="button"
                          className="btn-ghost btn-xs text-rose-300"
                          title="Annuler cet avis"
                          disabled={busy === a.id}
                          onClick={() => void annuler(a)}
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
          Périodes prévues par la loi pour donner l&apos;avis : de 6 à 3 mois avant la fin d&apos;un bail de 12 mois ou plus, de 2 à 1 mois
          avant la fin d&apos;un bail plus court ou avant la modification d&apos;un bail à durée indéterminée. Le locataire a un mois pour
          répondre. Ces repères sont affichés à titre indicatif, rien n&apos;est bloqué.
        </p>
      </div>
    </>
  );
}

// ─── Formulaire de l'avis ──────────────────────────────────────────────

function AvisForm({
  avis,
  modele,
  contacts,
  onClose,
  onSaved
}: {
  avis: Avis | null;
  modele: Avis | null;
  contacts: Contact[];
  onClose: () => void;
  onSaved: (a: Avis, voirPdf: boolean) => void;
}) {
  const [f, setF] = useState<F>(() => {
    if (avis) return versF(avis);
    if (modele) return { ...versF(modele), libelle: `${titreDe(modele)} (copie)`.slice(0, 255) };
    return F_VIDE;
  });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const poser = <K extends keyof F>(k: K, v: F[K]) => setF((x) => ({ ...x, [k]: v }));

  /** Changer la fin du bail recale la nouvelle période tant qu'elle n'a pas été choisie à la main. */
  function poserFinBail(v: string) {
    setF((x) => {
      const avant = x.bail_date_fin ? reconduction(x.bail_date_fin) : null;
      const vide = !x.nouvelle_date_debut && !x.nouvelle_date_fin;
      const auto = vide || (avant !== null && x.nouvelle_date_debut === avant.debut && x.nouvelle_date_fin === avant.fin);
      const apres = v ? reconduction(v) : null;
      return {
        ...x,
        bail_date_fin: v,
        ...(auto ? { nouvelle_date_debut: apres?.debut || "", nouvelle_date_fin: apres?.fin || "" } : {})
      };
    });
  }

  async function enregistrer(voirPdf: boolean) {
    setBusy(true);
    setErr(null);
    try {
      const txt = (v: string) => v.trim() || null;
      const corps = {
        libelle: txt(f.libelle),
        locateur_nom: txt(f.locateur_nom),
        locateur_adresse: txt(f.locateur_adresse),
        locateur_telephone: txt(f.locateur_telephone),
        locateur_courriel: txt(f.locateur_courriel),
        locataire_nom: txt(f.locataire_nom),
        locataire_courriel: txt(f.locataire_courriel),
        logement_adresse: txt(f.logement_adresse),
        logement_numero: txt(f.logement_numero),
        logement_ville: txt(f.logement_ville),
        bail_date_debut: f.bail_date_debut || null,
        bail_date_fin: f.bail_date_fin || null,
        loyer_actuel: nombre(f.loyer_actuel),
        modif_mode: f.modif_mode || null,
        nouveau_loyer: f.modif_mode === "nouveau_loyer" ? nombre(f.nouveau_loyer) : null,
        hausse_montant: f.modif_mode === "hausse_montant" ? nombre(f.hausse_montant) : null,
        hausse_pct: f.modif_mode === "hausse_pct" ? nombre(f.hausse_pct) : null,
        nouvelle_date_debut: f.nouvelle_date_debut || null,
        nouvelle_date_fin: f.nouvelle_date_fin || null,
        autres_modifications: txt(f.autres_modifications)
      };
      const r = await authedFetch(avis ? `${BASE}/avis/${avis.id}` : `${BASE}/avis`, {
        method: avis ? "PATCH" : "POST",
        body: JSON.stringify(corps)
      });
      if (!r.ok) throw new Error(await lireErreur(r));
      onSaved((await r.json()) as Avis, voirPdf);
    } catch (x) {
      setErr((x as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Fenetre
      large
      titre={avis ? "Modifier l'avis" : "Nouvel avis de renouvellement"}
      sousTitre="Formulaire officiel du TAL : avis d'augmentation de loyer et de modification d'une autre condition du bail."
      icone={<CalendarClock className="h-4 w-4" />}
      onClose={onClose}
      pied={
        <>
          <p className="text-[11px] text-white/45">
            <Etoile /> Obligatoire pour envoyer l&apos;avis. Il portera la date du jour de son envoi. Rien ne part à cette étape : on
            enregistre le brouillon.
          </p>
          <button type="button" onClick={onClose} className="btn-secondary btn-sm ml-auto" disabled={busy}>
            Fermer
          </button>
          <button type="button" onClick={() => void enregistrer(true)} className="btn-secondary btn-sm disabled:opacity-60" disabled={busy}>
            <FileText className="h-4 w-4" /> Enregistrer et voir le PDF
          </button>
          <button type="button" onClick={() => void enregistrer(false)} className="btn-accent btn-sm disabled:opacity-60" disabled={busy}>
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : null} Enregistrer
          </button>
        </>
      }
    >
      <NoteCarnetVide contacts={contacts} />
      <Champ label="Nom de cet avis (pour toi, n'apparaît pas sur l'avis)">
        <input className="input" value={f.libelle} onChange={(ev) => poser("libelle", ev.target.value)} placeholder="Ex. Renouvellement de Marc 2027" maxLength={255} />
      </Champ>

      <Bloc titre="Locateur" note="La personne ou la compagnie qui donne l'avis.">
        <ChoisirContact
          contacts={contacts}
          role="locateur"
          className="mb-2 sm:max-w-sm"
          onChoisir={(c) =>
            setF((x) => ({
              ...x,
              locateur_nom: c.nom,
              locateur_adresse: c.adresse || "",
              locateur_telephone: c.telephone || "",
              locateur_courriel: c.courriel || ""
            }))
          }
        />
        <div className="grid gap-2 sm:grid-cols-3">
          <Champ label="Nom" requis>
            <input className="input" value={f.locateur_nom} onChange={(ev) => poser("locateur_nom", ev.target.value)} />
          </Champ>
          <Champ label="Téléphone">
            <input className="input" value={f.locateur_telephone} onChange={(ev) => poser("locateur_telephone", ev.target.value)} placeholder="514-555-0100" />
          </Champ>
          <Champ label="Courriel">
            <input className="input" type="email" value={f.locateur_courriel} onChange={(ev) => poser("locateur_courriel", ev.target.value)} />
          </Champ>
          <Champ label="Adresse du locateur" className="sm:col-span-3">
            <input className="input" value={f.locateur_adresse} onChange={(ev) => poser("locateur_adresse", ev.target.value)} />
          </Champ>
        </div>
      </Bloc>

      <Bloc titre="Locataire" note="S'il y a plusieurs locataires au bail, prépare un avis pour chacun avec le bouton Dupliquer.">
        <ChoisirContact
          contacts={contacts}
          role="locataire"
          className="mb-2 sm:max-w-sm"
          onChoisir={(c) => setF((x) => ({ ...x, locataire_nom: c.nom, locataire_courriel: c.courriel || "" }))}
        />
        <div className="grid gap-2 sm:grid-cols-2">
          <Champ label="Nom" requis>
            <input className="input" value={f.locataire_nom} onChange={(ev) => poser("locataire_nom", ev.target.value)} />
          </Champ>
          <Champ label="Courriel (l'avis y sera envoyé)" requis>
            <input className="input" type="email" value={f.locataire_courriel} onChange={(ev) => poser("locataire_courriel", ev.target.value)} />
          </Champ>
        </div>
      </Bloc>

      <Bloc titre="Logement loué">
        <div className="grid gap-2 sm:grid-cols-4">
          <Champ label="Numéro et rue" className="sm:col-span-2" requis>
            <input className="input" value={f.logement_adresse} onChange={(ev) => poser("logement_adresse", ev.target.value)} placeholder="4521 rue Saint-Denis" />
          </Champ>
          <Champ label="Appartement">
            <input className="input" value={f.logement_numero} onChange={(ev) => poser("logement_numero", ev.target.value)} />
          </Champ>
          <Champ label="Ville">
            <input className="input" value={f.logement_ville} onChange={(ev) => poser("logement_ville", ev.target.value)} />
          </Champ>
        </div>
      </Bloc>

      <Bloc titre="Bail en cours">
        <div className="grid gap-2 sm:grid-cols-3">
          <Champ label="Début">
            <input className="input" type="date" value={f.bail_date_debut} onChange={(ev) => poser("bail_date_debut", ev.target.value)} />
          </Champ>
          <Champ label="Fin">
            <input className="input" type="date" value={f.bail_date_fin} onChange={(ev) => poserFinBail(ev.target.value)} />
          </Champ>
          <Champ label="Loyer actuel ($ par mois)">
            <input className="input" inputMode="decimal" value={f.loyer_actuel} onChange={(ev) => poser("loyer_actuel", ev.target.value)} placeholder="1450" />
          </Champ>
        </div>
      </Bloc>

      <Bloc titre="Modification proposée">
        <div className="grid gap-2 sm:grid-cols-2">
          <Champ label="Forme de la hausse">
            <select className="input" value={f.modif_mode} onChange={(ev) => poser("modif_mode", ev.target.value)}>
              <option value="nouveau_loyer">Nouveau loyer ($ par mois)</option>
              <option value="hausse_montant">Hausse en dollars (+ $ par mois)</option>
              <option value="hausse_pct">Hausse en pourcentage (%)</option>
              <option value="">Aucune hausse de loyer</option>
            </select>
          </Champ>
          {f.modif_mode === "nouveau_loyer" ? (
            <Champ label="Nouveau loyer mensuel ($)" requis>
              <input className="input" inputMode="decimal" value={f.nouveau_loyer} onChange={(ev) => poser("nouveau_loyer", ev.target.value)} placeholder="1495" />
            </Champ>
          ) : f.modif_mode === "hausse_montant" ? (
            <Champ label="Montant de la hausse ($ par mois)" requis>
              <input className="input" inputMode="decimal" value={f.hausse_montant} onChange={(ev) => poser("hausse_montant", ev.target.value)} placeholder="45" />
            </Champ>
          ) : f.modif_mode === "hausse_pct" ? (
            <Champ label="Pourcentage de la hausse (%)" requis>
              <input className="input" inputMode="decimal" value={f.hausse_pct} onChange={(ev) => poser("hausse_pct", ev.target.value)} placeholder="3" />
            </Champ>
          ) : (
            <span />
          )}
          <Champ label="Bail renouvelé du">
            <input className="input" type="date" value={f.nouvelle_date_debut} onChange={(ev) => poser("nouvelle_date_debut", ev.target.value)} />
          </Champ>
          <Champ label="au">
            <input className="input" type="date" value={f.nouvelle_date_fin} onChange={(ev) => poser("nouvelle_date_fin", ev.target.value)} />
          </Champ>
          <Champ label="Autres modifications au bail (facultatif)" className="sm:col-span-2">
            <textarea
              className="input min-h-[72px]"
              value={f.autres_modifications}
              onChange={(ev) => poser("autres_modifications", ev.target.value)}
              maxLength={4000}
              placeholder="Ex. Le stationnement n'est plus inclus dans le loyer."
            />
          </Champ>
        </div>
        <p className="mt-2 text-[11px] text-white/45">
          La nouvelle période se remplit d&apos;elle-même : un an à compter du lendemain de la fin du bail. Tu peux la changer.
        </p>
      </Bloc>

      {err ? <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">{err}</p> : null}
    </Fenetre>
  );
}

// ─── Envoi : destinataire affiché, geste confirmé ──────────────────────

function EnvoyerAvis({
  avis,
  aujourdHui,
  onClose,
  onEnvoye
}: {
  avis: Avis;
  aujourdHui: string;
  onClose: () => void;
  onEnvoye: (a: Avis, premier: boolean) => void;
}) {
  const renvoi = avis.status === "propose";
  const [courriel, setCourriel] = useState(avis.envoye_a || avis.locataire_courriel || "");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const f = avis.fenetre;

  async function envoyer() {
    setBusy(true);
    setErr(null);
    try {
      const r = await authedFetch(`${BASE}/avis/${avis.id}/envoyer`, {
        method: "POST",
        body: JSON.stringify({ courriel: courriel.trim() || null })
      });
      if (!r.ok) throw new Error(await lireErreur(r));
      onEnvoye((await r.json()) as Avis, !renvoi);
    } catch (x) {
      setErr((x as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Fenetre
      titre={renvoi ? "Renvoyer le lien de réponse" : "Envoyer l'avis au locataire"}
      sousTitre={titreDe(avis)}
      icone={<Send className="h-4 w-4" />}
      onClose={onClose}
      pied={
        <>
          <button type="button" onClick={onClose} className="btn-secondary btn-sm ml-auto" disabled={busy}>
            Ne rien envoyer
          </button>
          <button type="button" onClick={() => void envoyer()} className="btn-accent btn-sm disabled:opacity-60" disabled={busy || !courriel.trim()}>
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
            {renvoi ? "Renvoyer le lien" : "Envoyer l'avis"}
          </button>
        </>
      }
    >
      <p className="text-sm text-white/70">
        {renvoi
          ? `Le même avis repart, toujours daté du ${dateFr(avis.avis_envoye_le)}. Le délai de réponse ne change pas : le ${dateFr(avis.echeance_reponse)}.`
          : `${avis.locataire_nom || "Le locataire"} reçoit un courriel ${avis.locateur_nom ? `de la part de ${avis.locateur_nom}` : "de la part du locateur"}, avec un lien pour lire l'avis et répondre en ligne : accepter, refuser la modification ou annoncer son départ.`}
      </p>
      <Champ label="Courriel du locataire pour cet envoi">
        <input className="input" type="email" value={courriel} onChange={(ev) => setCourriel(ev.target.value)} placeholder="locataire@exemple.com" />
      </Champ>
      {!renvoi ? (
        <ul className="list-disc space-y-1 pl-5 text-xs text-white/60">
          <li>L&apos;avis sera daté d&apos;aujourd&apos;hui{aujourdHui ? `, le ${dateFr(aujourdHui)}` : ""}.</li>
          <li>Une fois parti, il ne se modifie plus. Pour le corriger, il faut l&apos;annuler et en préparer un nouveau.</li>
          <li>Le locataire a un mois pour répondre. Sans réponse, l&apos;avis est réputé accepté.</li>
        </ul>
      ) : null}
      {!renvoi && f && f.etat !== "dans" ? (
        <p className="flex items-start gap-2 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span>
            Aujourd&apos;hui est en dehors de la période prévue par la loi pour cet avis : du {dateFr(f.du)} au {dateFr(f.au)} ({f.regle}).
            L&apos;envoi reste possible, à toi de juger.
          </span>
        </p>
      ) : null}
      {err ? <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">{err}</p> : null}
    </Fenetre>
  );
}
