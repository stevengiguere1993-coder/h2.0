"use client";

/**
 * Modale « Nouveau locataire » — LE processus de création, partout
 * (retour Phil 2026-09-15 : « que ce soit le même processus, uniformisé »).
 * Utilisée par la page Locataires, par « Assigner un bail » (fiche
 * logement / locataire) et par « Lier un locataire » (Locations).
 *
 * - formulaire complet (retour Phil 2026-07-20) ;
 * - alerte anti-doublon (même courriel / téléphone), jamais bloquante ;
 * - documents déposés en même temps (bail, règlements, assurance…) —
 *   déposés ici (mode « deposer ») ou rendus au parent qui les dépose
 *   après avoir créé le bail (mode « differer »).
 */

import { useState } from "react";
import {
  AlertTriangle,
  ExternalLink,
  Loader2,
  UserCheck,
  X
} from "lucide-react";

import { Link } from "@/i18n/navigation";
import { authedFetch } from "@/lib/auth";
import type { FichierAImporter } from "@/components/immobilier/doc-types";
import {
  DocumentsAImporterZone,
  importerEnSerie,
  texteProgression,
  type ImportResultat
} from "@/components/immobilier/documents-a-importer";
import { importDocument } from "@/components/immobilier/tal-avis";

export type LocataireDoublon = {
  id: number;
  full_name: string;
  email?: string | null;
  phone?: string | null;
  motif: string;
  immeuble_id?: number | null;
  immeuble_name?: string | null;
  logement_id?: number | null;
  logement_numero?: string | null;
  bail_id?: number | null;
};

/** Ce que la modale rend au parent avec l'identifiant de la fiche. */
export type LocataireCreeInfo = {
  full_name: string;
  /** Documents choisis mais PAS déposés (mode « differer ») — le parent
   *  les dépose après avoir créé le bail (le « Bail » devient LE bail
   *  signé du dossier). Vide en mode « deposer ». */
  fichiers: FichierAImporter[];
};

export function CreateLocataireModal({
  onClose,
  onSaved,
  documents = "deposer",
  titre = "Nouveau locataire",
  zIndexClass = "z-50"
}: {
  onClose: () => void;
  /** Fiche retenue : celle qu'on vient de créer, ou l'existante
   *  choisie dans l'alerte doublon (« Sélectionner »). */
  onSaved: (locataireId: number, info: LocataireCreeInfo) => void;
  /** « deposer » (défaut) : les documents sont déposés sur la fiche
   *  ici même. « differer » : la modale rend les fichiers au parent,
   *  qui les dépose après la création du bail (Assigner un bail,
   *  Locations) — un seul processus de création partout (retour Phil
   *  2026-09-15), sans perdre « le Bail devient le bail signé ». */
  documents?: "deposer" | "differer";
  titre?: string;
  /** Empilée au-dessus d'une autre modale : passer un z-index plus haut. */
  zIndexClass?: string;
}) {
  // Formulaire COMPLET dès la création (retour Phil 2026-07-20 : « je
  // veux pouvoir avoir toutes les infos dès la création »).
  const [form, setForm] = useState({
    full_name: "",
    email: "",
    phone: "",
    employeur: "",
    revenu_annuel: "",
    date_naissance: "",
    nas_last4: "",
    notes: ""
  });
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  // Alerte anti-doublon : on interroge le backend AVANT de créer. Elle
  // est purement informative — « Créer quand même » passe outre (vrais
  // homonymes, couple qui partage un courriel de ménage).
  const [doublons, setDoublons] = useState<LocataireDoublon[] | null>(null);
  const [verifDoublons, setVerifDoublons] = useState(false);
  // Documents déposés EN MÊME TEMPS que la fiche (retour Phil
  // 2026-09-09) : bail, règlements de l'immeuble, assurance… Chaque
  // fichier passe par /documents/import rattaché au LOCATAIRE — un
  // « Bail » reste une pièce du dossier tant qu'aucun bail n'existe ; il
  // se joint au bail plus tard (« Joindre le bail signé ») ou viendra
  // de la signature en ligne.
  const [fichiers, setFichiers] = useState<FichierAImporter[]>([]);
  const [progression, setProgression] = useState<{
    fait: number;
    total: number;
  } | null>(null);
  const [resultatsImport, setResultatsImport] = useState<
    ImportResultat[] | null
  >(null);
  // Fiche déjà créée (ou existante retenue) dont des documents ont
  // échoué : plus question de recréer — on réessaie ou on ouvre la fiche.
  const [ficheEnAttente, setFicheEnAttente] = useState<{
    id: number;
    nom: string;
  } | null>(null);
  const enCoursImport =
    progression != null && progression.fait < progression.total;

  /** Dépose `liste` sur la fiche puis sort (onSaved). Une erreur sur un
   *  fichier ne bloque ni les autres ni la fiche : elle s'affiche par
   *  ligne, et « Ouvrir la fiche » reste possible. */
  async function deposerPuisSortir(
    locataireId: number,
    liste: FichierAImporter[],
    nom: string
  ) {
    if (documents === "differer") {
      // Le parent dépose après avoir créé le bail.
      onSaved(locataireId, { full_name: nom, fichiers: liste });
      return;
    }
    if (liste.length === 0) {
      onSaved(locataireId, { full_name: nom, fichiers: [] });
      return;
    }
    const res = await importerEnSerie(
      liste,
      (f) => importDocument({ file: f.file, type: f.type, locataireId }),
      (fait, total) => setProgression({ fait, total })
    );
    // On garde les « Déposé » des passes précédentes (réessai partiel).
    setResultatsImport((prev) => [
      ...(prev || []).filter(
        (x) => !res.some((r) => r.fichier.key === x.fichier.key)
      ),
      ...res
    ]);
    const echecs = res.filter((r) => r.erreur).length;
    if (echecs === 0) {
      onSaved(locataireId, { full_name: nom, fichiers: [] });
      return;
    }
    setFicheEnAttente({ id: locataireId, nom });
    setErr(
      `La fiche est créée, mais ${echecs} document${echecs > 1 ? "s" : ""} ` +
        "n'ont pas pu être déposés — réessaie, ou ouvre la fiche et " +
        "importe-les depuis sa section Documents."
    );
  }

  async function reessayerEchecs() {
    if (ficheEnAttente == null) return;
    const rates = new Set(
      (resultatsImport || []).filter((r) => r.erreur).map((r) => r.fichier.key)
    );
    // Les échecs + les fichiers ajoutés depuis (jamais tentés).
    const liste = fichiers.filter(
      (f) =>
        rates.has(f.key) ||
        !(resultatsImport || []).some((r) => r.fichier.key === f.key)
    );
    if (liste.length === 0) {
      onSaved(ficheEnAttente.id, { full_name: ficheEnAttente.nom, fichiers: [] });
      return;
    }
    setSaving(true);
    setErr(null);
    try {
      await deposerPuisSortir(ficheEnAttente.id, liste, ficheEnAttente.nom);
    } catch (e2) {
      setErr((e2 as Error).message);
    } finally {
      setSaving(false);
    }
  }

  /** Fiche existante retenue dans l'alerte doublon : les documents
   *  choisis vont sur ELLE (même personne). */
  async function choisirExistante(d: LocataireDoublon) {
    setSaving(true);
    setErr(null);
    try {
      await deposerPuisSortir(d.id, fichiers, d.full_name);
    } catch (e2) {
      setErr((e2 as Error).message);
    } finally {
      setSaving(false);
    }
  }

  async function creer() {
    setSaving(true);
    setErr(null);
    try {
      const body: Record<string, unknown> = {
        full_name: form.full_name.trim()
      };
      if (form.email.trim()) body.email = form.email.trim();
      if (form.phone.trim()) body.phone = form.phone.trim();
      if (form.employeur.trim()) body.employeur = form.employeur.trim();
      if (form.revenu_annuel)
        body.revenu_annuel = Number(form.revenu_annuel);
      if (form.date_naissance) body.date_naissance = form.date_naissance;
      if (form.nas_last4.trim()) body.nas_last4 = form.nas_last4.trim();
      if (form.notes.trim()) body.notes = form.notes.trim();
      const res = await authedFetch("/api/v1/immobilier/locataires", {
        method: "POST",
        body: JSON.stringify(body)
      });
      if (!res.ok) {
        const t = await res.text();
        throw new Error(t.slice(0, 240) || `HTTP ${res.status}`);
      }
      const created = (await res.json()) as { id: number };
      await deposerPuisSortir(created.id, fichiers, form.full_name.trim());
    } catch (e2) {
      setErr((e2 as Error).message);
    } finally {
      setSaving(false);
    }
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    // Rien à comparer (ni courriel ni téléphone) → création directe.
    const email = form.email.trim();
    const phone = form.phone.trim();
    if (!email && !phone) {
      void creer();
      return;
    }
    setVerifDoublons(true);
    setErr(null);
    try {
      const p = new URLSearchParams();
      if (email) p.set("email", email);
      if (phone) p.set("phone", phone);
      const r = await authedFetch(
        `/api/v1/immobilier/locataires/doublons?${p.toString()}`
      );
      if (r.ok) {
        const trouves = (await r.json()) as LocataireDoublon[];
        if (trouves.length > 0) {
          setDoublons(trouves);
          return; // on montre l'alerte, on ne crée rien pour l'instant
        }
      }
      // Détection en panne = on ne bloque pas la saisie du staff.
    } catch {
      // idem : l'alerte est un confort, pas un verrou.
    } finally {
      setVerifDoublons(false);
    }
    void creer();
  }

  function set<K extends keyof typeof form>(k: K, v: string) {
    setForm({ ...form, [k]: v });
    // Une correction du courriel/téléphone invalide l'alerte affichée.
    if (k === "email" || k === "phone") setDoublons(null);
  }

  return (
    <div
      className={`fixed inset-0 ${zIndexClass} flex items-start justify-center overflow-y-auto bg-black/70 p-4 backdrop-blur-sm`}
      onClick={(e) => e.stopPropagation()}
    >
      <div className="my-8 w-full max-w-lg rounded-2xl border border-brand-800 bg-brand-950 shadow-2xl">
        <div className="flex items-center justify-between border-b border-brand-800 px-5 py-3">
          <h2 className="text-sm font-bold uppercase tracking-wider text-accent-500">
            {titre}
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="btn-ghost btn-xs"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        <form onSubmit={submit} className="grid gap-4 p-5">
          <div>
            <label className="label">Nom complet</label>
            <input
              required
              value={form.full_name}
              onChange={(e) => set("full_name", e.target.value)}
              className="input"
            />
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <label className="label">Email</label>
              <input
                type="email"
                value={form.email}
                onChange={(e) => set("email", e.target.value)}
                className="input"
              />
              {/* On ne BLOQUE pas : après l'achat d'un immeuble, on
                  saisit des locataires déjà en place dont on n'a pas
                  encore le courriel. Mais la conséquence doit être
                  visible tout de suite — sans courriel, aucun avis, aucun
                  relevé 31, aucune relance ne pourra partir vers cette
                  personne (2026-08-19). */}
              {!form.email.trim() ? (
                <p className="mt-1 text-[11px] text-amber-300/80">
                  Sans courriel, aucune communication ne pourra lui être
                  envoyée — ni avis, ni relevé 31, ni relance.
                </p>
              ) : null}
            </div>
            <div>
              <label className="label">Téléphone</label>
              <input
                value={form.phone}
                onChange={(e) => set("phone", e.target.value)}
                className="input font-mono"
              />
            </div>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <label className="label">Employeur</label>
              <input
                value={form.employeur}
                onChange={(e) => set("employeur", e.target.value)}
                className="input"
              />
            </div>
            <div>
              <label className="label">Revenu annuel (CAD)</label>
              <input
                type="number"
                value={form.revenu_annuel}
                onChange={(e) => set("revenu_annuel", e.target.value)}
                className="input font-mono"
                min={0}
                step={1000}
              />
            </div>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <label className="label">Date de naissance</label>
              <input
                type="date"
                value={form.date_naissance}
                onChange={(e) => set("date_naissance", e.target.value)}
                className="input"
              />
            </div>
            <div>
              <label className="label">NAS (4 derniers chiffres)</label>
              <input
                maxLength={4}
                inputMode="numeric"
                pattern="[0-9]*"
                value={form.nas_last4}
                onChange={(e) => set("nas_last4", e.target.value)}
                className="input font-mono"
              />
            </div>
          </div>
          <div>
            <label className="label">Notes</label>
            <textarea
              rows={3}
              value={form.notes}
              onChange={(e) => set("notes", e.target.value)}
              placeholder="ex. références, particularités, animaux…"
              className="input"
            />
          </div>

          <DocumentsAImporterZone
            fichiers={fichiers}
            onChange={setFichiers}
            disabled={saving}
            progression={progression}
            resultats={resultatsImport}
            aide={
              documents === "differer"
                ? "Bail, règlements de l'immeuble, assurance… déposés APRÈS la création du bail : le fichier « Bail » devient LE bail signé du dossier (le bail passe actif), les autres pièces sont classées au dossier du locataire et du bail."
                : "Bail, règlements de l'immeuble, assurance… déposés d'un coup sur la fiche. Le « Bail » reste une pièce du dossier tant qu'aucun bail n'existe : il se joint au bail plus tard (« Joindre le bail signé »), ou viendra de la signature en ligne."
            }
          />

          {err ? (
            <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
              <AlertTriangle className="mr-1.5 inline h-3.5 w-3.5" />
              {err}
            </p>
          ) : null}

          {/* Alerte DOUBLON — même courriel ou même téléphone qu'une
              fiche existante. Jamais bloquante : trois issues, dont
              « Créer quand même ». */}
          {doublons && doublons.length > 0 ? (
            <div className="rounded-xl border border-amber-500/50 bg-amber-500/10 p-3">
              <p className="flex items-start gap-2 text-xs font-semibold text-amber-200">
                <AlertTriangle className="mt-0.5 h-4 w-4 flex-shrink-0" />
                <span>
                  {doublons.length === 1
                    ? "Cette personne existe déjà"
                    : `${doublons.length} fiches existantes correspondent`}{" "}
                  <span className="font-normal text-amber-200/80">
                    — même coordonnée. Utilise la fiche existante plutôt
                    que d&apos;en créer une deuxième.
                  </span>
                </span>
              </p>
              <ul className="mt-2 space-y-2">
                {doublons.map((d) => (
                  <li
                    key={d.id}
                    className="rounded-lg border border-brand-800 bg-brand-950 px-3 py-2"
                  >
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <div className="min-w-0">
                        <p className="truncate text-sm font-bold text-white">
                          {d.full_name}
                        </p>
                        <p className="text-[11px] text-white/60">
                          {d.email || "pas de courriel"} ·{" "}
                          <span className="font-mono">
                            {d.phone || "pas de téléphone"}
                          </span>
                        </p>
                        <p className="text-[11px] text-white/45">
                          {d.logement_id
                            ? `${d.immeuble_name || "Immeuble"} · ${
                                d.logement_numero || ""
                              }`
                            : "Aucun bail actif"}{" "}
                          <span className="text-amber-300/80">
                            (même {d.motif})
                          </span>
                        </p>
                      </div>
                      <div className="flex flex-shrink-0 items-center gap-1.5">
                        <button
                          type="button"
                          onClick={() => void choisirExistante(d)}
                          disabled={saving}
                          className="btn-accent btn-xs inline-flex items-center gap-1 disabled:opacity-60"
                          title={
                            fichiers.length > 0
                              ? "Utiliser cette fiche (les documents choisis y seront déposés)"
                              : "Utiliser cette fiche au lieu d'en créer une nouvelle"
                          }
                        >
                          <UserCheck className="h-3 w-3" />
                          Sélectionner
                        </button>
                        <Link
                          // eslint-disable-next-line @typescript-eslint/no-explicit-any
                          href={`/immobilier/locataires/${d.id}` as any}
                          target="_blank"
                          className="btn-secondary btn-xs inline-flex items-center gap-1"
                          title="Ouvrir la fiche dans un nouvel onglet pour la modifier — le formulaire reste ouvert"
                        >
                          <ExternalLink className="h-3 w-3" />
                          Ouvrir
                        </Link>
                      </div>
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          <div className="flex items-center justify-end gap-2 border-t border-brand-800 pt-4">
            {ficheEnAttente != null ? (
              <>
                <button
                  type="button"
                  onClick={() =>
                    onSaved(ficheEnAttente.id, {
                      full_name: ficheEnAttente.nom,
                      fichiers: []
                    })
                  }
                  disabled={saving}
                  className="btn-secondary text-sm disabled:opacity-60"
                  title="La fiche existe : ouvre-la, les documents en échec pourront être importés depuis sa section Documents"
                >
                  Ouvrir la fiche
                </button>
                <button
                  type="button"
                  onClick={() => void reessayerEchecs()}
                  disabled={saving}
                  className="btn-accent inline-flex items-center text-sm disabled:opacity-60"
                >
                  {saving ? (
                    <>
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                      Import {texteProgression(progression)}…
                    </>
                  ) : (
                    "Réessayer les échecs"
                  )}
                </button>
              </>
            ) : null}
            {ficheEnAttente != null ? null : (
              <button type="button" onClick={onClose} className="btn-secondary text-sm">
                Annuler
              </button>
            )}
            {ficheEnAttente != null ? null : doublons && doublons.length > 0 ? (
              // Le staff garde le dernier mot : l'alerte informe, elle
              // n'interdit rien.
              <button
                type="button"
                onClick={() => void creer()}
                disabled={saving}
                className="btn-accent inline-flex items-center text-sm disabled:opacity-60"
              >
                {saving ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    {enCoursImport
                      ? `Import ${texteProgression(progression)}…`
                      : "Création…"}
                  </>
                ) : (
                  "Créer quand même"
                )}
              </button>
            ) : (
              <button
                type="submit"
                disabled={saving || verifDoublons || !form.full_name.trim()}
                className="btn-accent inline-flex items-center text-sm disabled:opacity-60"
              >
                {saving || verifDoublons ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    {verifDoublons
                      ? "Vérification…"
                      : enCoursImport
                        ? `Import ${texteProgression(progression)}…`
                        : "Création…"}
                  </>
                ) : fichiers.length > 0 ? (
                  documents === "differer"
                    ? `Créer (${fichiers.length} document${fichiers.length > 1 ? "s" : ""} avec le bail)`
                    : `Créer + ${fichiers.length} document${fichiers.length > 1 ? "s" : ""}`
                ) : (
                  "Créer"
                )}
              </button>
            )}
          </div>
        </form>
      </div>
    </div>
  );
}
