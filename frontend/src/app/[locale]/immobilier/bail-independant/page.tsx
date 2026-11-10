"use client";

/**
 * Gestion immobilière → « Bail indépendant » (Phil 2026-11-10).
 *
 * « Une page… bail indépendant… je vais rentrer les informations dans un genre
 * de petit formulaire puis ça va créer le bail. Ça va être mon environnement
 * test et en même temps un environnement pour créer un bail pour un ami…
 * quelqu'un qui n'est pas dans mon système. »
 *
 * Un bail officiel du TAL (formulaire 53000BAIL) SANS fiche Kratos : rien n'est
 * rattaché à un immeuble, un locataire, un dossier de location ni à la
 * facturation ; le locateur nommé signe lui-même. Le petit formulaire crée un
 * brouillon (même remplissage que les baux de « Locations & nouveaux baux »),
 * puis l'écran complet du bail prend le relais : tous les champs, la
 * vérification, la génération (simulation ou réel, selon Paramètres), le PDF,
 * la signature.
 */

import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, Copy, FileSignature, FileText, Loader2, Plus, Settings, Trash2, X } from "lucide-react";

import { useConfirm } from "@/components/confirm-dialog";
import {
  TalBailModal,
  libelleModeTal,
  ouvrirPdfDocument,
  type SignatureEtat,
  type TalTransmission
} from "@/components/immobilier/tal-bail-modal";
import { Link } from "@/i18n/navigation";
import { authedFetch } from "@/lib/auth";
import { ImmobilierTopbar } from "../layout";

const BASE = "/api/v1/immobilier/tal-bail";

type Etat = {
  connexion: { mode: string; pret_pour_reel: boolean; cle_configuree: boolean; url_configuree: boolean };
  compteur: { gratuits_restants: number; total_reel_depuis_le_debut: number };
  cout_tal: number;
  gratuits_total: number;
};
type Item = TalTransmission & { signature: SignatureEtat | null };
type Personne = { nom: string; telephone: string; courriel: string; adresse: string };
type Essentiel = {
  libelle: string;
  locateur: Personne;
  locataires: Personne[];
  cautions: Personne[];
  adresse: string;
  appartement: string;
  ville: string;
  code_postal: string;
  nb_pieces: string;
  au_mois: boolean;
  date_debut: string;
  date_fin: string;
  loyer_mensuel: string;
  jour_echeance: string;
  chauffage_inclus: boolean;
  electricite_inclus: boolean;
  eau_chaude_inclus: boolean;
  internet_inclus: boolean;
};

const PERSONNE_VIDE: Personne = { nom: "", telephone: "", courriel: "", adresse: "" };
const ESSENTIEL_VIDE: Essentiel = {
  libelle: "",
  locateur: { ...PERSONNE_VIDE },
  locataires: [{ ...PERSONNE_VIDE }],
  cautions: [],
  adresse: "",
  appartement: "",
  ville: "",
  code_postal: "",
  nb_pieces: "",
  au_mois: false,
  date_debut: "",
  date_fin: "",
  loyer_mensuel: "",
  jour_echeance: "1",
  chauffage_inclus: false,
  electricite_inclus: false,
  eau_chaude_inclus: false,
  internet_inclus: false
};
const PIECES = ["1", "1.5", "2", "2.5", "3", "3.5", "4", "4.5", "5", "5.5", "6", "6.5", "7", "7.5"];

async function lireErreur(r: Response): Promise<string> {
  const t = await r.text();
  try {
    const d = (JSON.parse(t) as { detail?: unknown }).detail;
    if (typeof d === "string") return d;
    if (d && typeof d === "object" && typeof (d as { message?: unknown }).message === "string") return (d as { message: string }).message;
  } catch {
    /* texte brut */
  }
  return t.slice(0, 300) || `Erreur ${r.status}`;
}

function nombre(v: string): number | null {
  const n = Number(String(v).replace(",", ".").replace(/\s/g, ""));
  return v.trim() !== "" && Number.isFinite(n) ? n : null;
}

function dateFr(iso: string | null | undefined): string {
  if (!iso) return "";
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  if (!y || !m || !d) return iso;
  return new Date(y, m - 1, d).toLocaleDateString("fr-CA", { day: "numeric", month: "short", year: "numeric" });
}

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

export default function BailIndependantPage() {
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
      <ImmobilierTopbar breadcrumbs={[{ label: "Immobilier", href: "/immobilier" }, { label: "Bail indépendant" }]} />
      {nouveau ? (
        <NouveauBail
          onClose={() => setNouveau(false)}
          onCree={(t) => {
            setNouveau(false);
            void charger();
            setOuvert({ ...t, signature: null });
          }}
        />
      ) : null}
      {ouvert ? (
        <TalBailModal
          transmissionId={ouvert.id}
          titre={titreDe(ouvert)}
          onClose={() => {
            setOuvert(null);
            void charger();
          }}
          onDone={() => void charger()}
        />
      ) : null}

      <div className="p-4 pb-28 lg:p-6 lg:pb-28">
        <header className="flex flex-wrap items-start gap-3">
          <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-accent-500/15 text-accent-500">
            <FileSignature className="h-5 w-5" />
          </span>
          <div className="min-w-0 flex-1">
            <h1 className="text-2xl font-bold text-white">Bail indépendant</h1>
            <p className="mt-1 max-w-2xl text-sm text-white/60">
              Un bail officiel du Tribunal administratif du logement pour quelqu&apos;un qui n&apos;est pas dans Kratos : un
              essai, ou le bail d&apos;un proche. Rien n&apos;est rattaché à un immeuble, à un locataire ni à la facturation,
              et le locateur nommé au bail signe lui-même.
            </p>
          </div>
          <button type="button" onClick={() => setNouveau(true)} className="btn-accent btn-sm">
            <Plus className="h-4 w-4" /> Nouveau bail
          </button>
        </header>

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
              <p className="text-[11px] font-semibold uppercase tracking-wider text-white/50">Réglages</p>
              <p className="mt-0.5 text-xs text-white/60">Mode simulation ou réel, adresse de l&apos;API, clé (écriture seule, chiffrée).</p>
              <Link href={"/parametres/locatif" as never} className="btn-secondary btn-xs mt-2 inline-flex">
                <Settings className="h-3.5 w-3.5" /> Paramètres → Gestion locative
              </Link>
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
                        {p?.loyer ? ` · ${p.loyer} $` : ""}
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

// ─── Petit formulaire ──────────────────────────────────────────────────

function Champ({ label, children, className = "" }: { label: string; children: React.ReactNode; className?: string }) {
  return (
    <label className={`flex flex-col gap-1 text-xs text-white/60 ${className}`}>
      <span>{label}</span>
      {children}
    </label>
  );
}

function Bloc({ titre, note, children }: { titre: string; note?: string; children: React.ReactNode }) {
  return (
    <fieldset className="rounded-xl border border-brand-800 bg-brand-900/60 p-3">
      <legend className="px-1 text-[11px] font-semibold uppercase tracking-wider text-accent-500">{titre}</legend>
      {note ? <p className="mb-2 text-[11px] text-white/45">{note}</p> : null}
      {children}
    </fieldset>
  );
}

function NouveauBail({ onClose, onCree }: { onClose: () => void; onCree: (t: TalTransmission) => void }) {
  const [e, setE] = useState<Essentiel>(ESSENTIEL_VIDE);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const poser = <K extends keyof Essentiel>(k: K, v: Essentiel[K]) => setE((x) => ({ ...x, [k]: v }));
  const poserLocateur = (k: keyof Personne, v: string) => setE((x) => ({ ...x, locateur: { ...x.locateur, [k]: v } }));
  const poserListe = (liste: "locataires" | "cautions", i: number, k: keyof Personne, v: string) =>
    setE((x) => ({ ...x, [liste]: x[liste].map((p, j) => (j === i ? { ...p, [k]: v } : p)) }));
  const ajouter = (liste: "locataires" | "cautions") => setE((x) => ({ ...x, [liste]: [...x[liste], { ...PERSONNE_VIDE }] }));
  const retirer = (liste: "locataires" | "cautions", i: number) => setE((x) => ({ ...x, [liste]: x[liste].filter((_, j) => j !== i) }));

  async function creer() {
    setBusy(true);
    setErr(null);
    try {
      const propre = (p: Personne) => ({
        nom: p.nom.trim() || null,
        telephone: p.telephone.trim() || null,
        courriel: p.courriel.trim() || null,
        adresse: p.adresse.trim() || null
      });
      const r = await authedFetch(`${BASE}/independants`, {
        method: "POST",
        body: JSON.stringify({
          libelle: e.libelle.trim() || null,
          locateur: propre(e.locateur),
          locataires: e.locataires.filter((p) => p.nom.trim()).map(propre),
          cautions: e.cautions.filter((p) => p.nom.trim()).map(propre),
          adresse: e.adresse.trim() || null,
          appartement: e.appartement.trim() || null,
          ville: e.ville.trim() || null,
          code_postal: e.code_postal.trim() || null,
          nb_pieces: nombre(e.nb_pieces),
          au_mois: e.au_mois,
          date_debut: e.date_debut || null,
          date_fin: e.au_mois ? null : e.date_fin || null,
          loyer_mensuel: nombre(e.loyer_mensuel),
          jour_echeance: Math.min(31, Math.max(1, Math.round(nombre(e.jour_echeance) ?? 1))),
          chauffage_inclus: e.chauffage_inclus,
          electricite_inclus: e.electricite_inclus,
          eau_chaude_inclus: e.eau_chaude_inclus,
          internet_inclus: e.internet_inclus
        })
      });
      if (!r.ok) throw new Error(await lireErreur(r));
      onCree((await r.json()) as TalTransmission);
    } catch (x) {
      setErr((x as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="fixed inset-0 z-[55] flex items-start justify-center overflow-y-auto bg-black/70 p-4 backdrop-blur-sm" onClick={onClose}>
      <div className="my-6 w-full max-w-3xl rounded-2xl border border-brand-800 bg-brand-950 shadow-2xl" onClick={(ev) => ev.stopPropagation()}>
        <div className="flex items-center justify-between gap-2 border-b border-brand-800 px-5 py-3">
          <div>
            <h2 className="flex items-center gap-2 text-sm font-bold uppercase tracking-wider text-accent-500">
              <FileSignature className="h-4 w-4" /> Nouveau bail indépendant
            </h2>
            <p className="text-xs text-white/55">
              L&apos;essentiel ici ; tout le reste du formulaire officiel se revoit et se complète à l&apos;étape suivante, avant de générer.
            </p>
          </div>
          <button type="button" onClick={onClose} className="btn-ghost btn-xs">
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="space-y-3 px-5 py-4">
          <Champ label="Nom de ce bail (pour toi, n'apparaît pas au bail)">
            <input className="input" value={e.libelle} onChange={(ev) => poser("libelle", ev.target.value)} placeholder="Ex. Essai 1, Bail de Marc" maxLength={255} />
          </Champ>

          <Bloc titre="Locateur" note="La personne ou la compagnie qui loue. C'est elle qui signera le bail.">
            <div className="grid gap-2 sm:grid-cols-3">
              <Champ label="Nom">
                <input className="input" value={e.locateur.nom} onChange={(ev) => poserLocateur("nom", ev.target.value)} />
              </Champ>
              <Champ label="Téléphone">
                <input className="input" value={e.locateur.telephone} onChange={(ev) => poserLocateur("telephone", ev.target.value)} placeholder="514-555-0100" />
              </Champ>
              <Champ label="Courriel (pour la signature)">
                <input className="input" type="email" value={e.locateur.courriel} onChange={(ev) => poserLocateur("courriel", ev.target.value)} />
              </Champ>
              <Champ label="Adresse du locateur" className="sm:col-span-3">
                <input className="input" value={e.locateur.adresse} onChange={(ev) => poserLocateur("adresse", ev.target.value)} placeholder="12 rue des Érables, Laval (Québec) H7A 1B2" />
              </Champ>
            </div>
          </Bloc>

          <Bloc titre="Locataire(s)" note="Jusqu'à quatre. Chacun reçoit le bail à signer à son courriel.">
            <div className="space-y-2">
              {e.locataires.map((p, i) => (
                <div key={i} className="grid gap-2 sm:grid-cols-[1fr_150px_1fr_auto]">
                  <Champ label={i === 0 ? "Nom" : `Nom (locataire ${i + 1})`}>
                    <input className="input" value={p.nom} onChange={(ev) => poserListe("locataires", i, "nom", ev.target.value)} />
                  </Champ>
                  <Champ label="Téléphone">
                    <input className="input" value={p.telephone} onChange={(ev) => poserListe("locataires", i, "telephone", ev.target.value)} />
                  </Champ>
                  <Champ label="Courriel">
                    <input className="input" type="email" value={p.courriel} onChange={(ev) => poserListe("locataires", i, "courriel", ev.target.value)} />
                  </Champ>
                  {e.locataires.length > 1 ? (
                    <button type="button" className="btn-ghost btn-xs self-end text-rose-300" title="Retirer ce locataire" onClick={() => retirer("locataires", i)}>
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  ) : (
                    <span />
                  )}
                  {i === 0 ? (
                    <Champ label="Adresse actuelle du locataire (facultatif)" className="sm:col-span-4">
                      <input className="input" value={p.adresse} onChange={(ev) => poserListe("locataires", i, "adresse", ev.target.value)} />
                    </Champ>
                  ) : null}
                </div>
              ))}
            </div>
            <div className="mt-2 flex flex-wrap gap-2">
              {e.locataires.length < 4 ? (
                <button type="button" className="btn-secondary btn-xs" onClick={() => ajouter("locataires")}>
                  <Plus className="h-3.5 w-3.5" /> Ajouter un locataire
                </button>
              ) : null}
              {e.cautions.length < 2 ? (
                <button type="button" className="btn-secondary btn-xs" onClick={() => ajouter("cautions")}>
                  <Plus className="h-3.5 w-3.5" /> Ajouter une caution
                </button>
              ) : null}
            </div>
            {e.cautions.map((p, i) => (
              <div key={i} className="mt-2 grid gap-2 sm:grid-cols-[1fr_1fr_auto]">
                <Champ label={`Caution ${i + 1} — nom`}>
                  <input className="input" value={p.nom} onChange={(ev) => poserListe("cautions", i, "nom", ev.target.value)} />
                </Champ>
                <Champ label="Courriel">
                  <input className="input" type="email" value={p.courriel} onChange={(ev) => poserListe("cautions", i, "courriel", ev.target.value)} />
                </Champ>
                <button type="button" className="btn-ghost btn-xs self-end text-rose-300" title="Retirer cette caution" onClick={() => retirer("cautions", i)}>
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </div>
            ))}
          </Bloc>

          <Bloc titre="Logement loué">
            <div className="grid gap-2 sm:grid-cols-4">
              <Champ label="Numéro et rue" className="sm:col-span-2">
                <input className="input" value={e.adresse} onChange={(ev) => poser("adresse", ev.target.value)} placeholder="4521 rue Saint-Denis" />
              </Champ>
              <Champ label="Appartement">
                <input className="input" value={e.appartement} onChange={(ev) => poser("appartement", ev.target.value)} />
              </Champ>
              <Champ label="Nombre de pièces">
                <select className="input" value={e.nb_pieces} onChange={(ev) => poser("nb_pieces", ev.target.value)}>
                  <option value="">—</option>
                  {PIECES.map((p) => (
                    <option key={p} value={p}>
                      {p.replace(".5", " ½")}
                    </option>
                  ))}
                </select>
              </Champ>
              <Champ label="Ville" className="sm:col-span-2">
                <input className="input" value={e.ville} onChange={(ev) => poser("ville", ev.target.value)} />
              </Champ>
              <Champ label="Code postal">
                <input className="input" value={e.code_postal} onChange={(ev) => poser("code_postal", ev.target.value)} placeholder="H2J 2L4" />
              </Champ>
            </div>
          </Bloc>

          <Bloc titre="Durée et loyer">
            <div className="grid gap-2 sm:grid-cols-4">
              <Champ label="Type de bail">
                <select className="input" value={e.au_mois ? "indetermine" : "fixe"} onChange={(ev) => poser("au_mois", ev.target.value === "indetermine")}>
                  <option value="fixe">Durée fixe</option>
                  <option value="indetermine">Durée indéterminée</option>
                </select>
              </Champ>
              <Champ label="Début">
                <input className="input" type="date" value={e.date_debut} onChange={(ev) => poser("date_debut", ev.target.value)} />
              </Champ>
              {!e.au_mois ? (
                <Champ label="Fin">
                  <input className="input" type="date" value={e.date_fin} onChange={(ev) => poser("date_fin", ev.target.value)} />
                </Champ>
              ) : (
                <span />
              )}
              <span />
              <Champ label="Loyer par mois ($)">
                <input className="input" inputMode="decimal" value={e.loyer_mensuel} onChange={(ev) => poser("loyer_mensuel", ev.target.value)} placeholder="1450" />
              </Champ>
              <Champ label="Payable le (jour du mois)">
                <input className="input" inputMode="numeric" value={e.jour_echeance} onChange={(ev) => poser("jour_echeance", ev.target.value)} />
              </Champ>
            </div>
            <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-white/70">
              <span className="text-white/45">Inclus dans le loyer :</span>
              {(
                [
                  ["chauffage_inclus", "Chauffage"],
                  ["electricite_inclus", "Électricité"],
                  ["eau_chaude_inclus", "Eau chaude"],
                  ["internet_inclus", "Internet"]
                ] as [keyof Essentiel, string][]
              ).map(([k, label]) => (
                <label key={k} className="inline-flex items-center gap-1.5">
                  <input type="checkbox" checked={Boolean(e[k])} onChange={(ev) => poser(k, ev.target.checked as Essentiel[typeof k])} />
                  {label}
                </label>
              ))}
            </div>
          </Bloc>

          {err ? <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">{err}</p> : null}
        </div>

        <div className="flex flex-wrap items-center gap-2 border-t border-brand-800 px-5 py-3">
          <p className="text-[11px] text-white/45">Rien n&apos;est envoyé au TAL à cette étape : on crée seulement le brouillon.</p>
          <button type="button" onClick={onClose} className="btn-secondary btn-sm ml-auto" disabled={busy}>
            Fermer
          </button>
          <button type="button" onClick={() => void creer()} className="btn-accent btn-sm disabled:opacity-60" disabled={busy}>
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileText className="h-4 w-4" />} Créer le brouillon et continuer
          </button>
        </div>
      </div>
    </div>
  );
}
