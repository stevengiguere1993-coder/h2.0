/**
 * Appels d'API des documents locatifs — import d'une pièce au dossier et
 * dépôt du bail signé. Module SANS composant pour être importable
 * partout (tal-avis, fin-bail, assigner-bail, locations, transfert…).
 */

import { authedFetch } from "@/lib/auth";
import type { BailDocument } from "@/components/immobilier/tal-avis";

/** Téléverse un document au dossier (bouton « Importer »). */
export async function importDocument(opts: {
  file: File;
  type?: string;
  titre?: string;
  bailId?: number;
  locataireId?: number;
  logementId?: number;
  immeubleId?: number;
  /** Rattache la pièce à un dossier TAL (bail/locataire déduits). */
  talDossierId?: number;
}): Promise<BailDocument> {
  const fd = new FormData();
  fd.append("file", opts.file);
  fd.append("type", opts.type || "autre");
  if (opts.titre) fd.append("titre", opts.titre);
  if (opts.bailId != null) fd.append("bail_id", String(opts.bailId));
  if (opts.locataireId != null)
    fd.append("locataire_id", String(opts.locataireId));
  if (opts.logementId != null)
    fd.append("logement_id", String(opts.logementId));
  if (opts.immeubleId != null)
    fd.append("immeuble_id", String(opts.immeubleId));
  if (opts.talDossierId != null)
    fd.append("tal_dossier_id", String(opts.talDossierId));
  const r = await authedFetch("/api/v1/immobilier/documents/import", {
    method: "POST",
    body: fd
  });
  const d = await r.json().catch(() => null);
  if (!r.ok) {
    throw new Error((d && (d.detail || d.message)) || `Erreur ${r.status}`);
  }
  return d as BailDocument;
}

/**
 * Téléverse LE bail signé d'un bail (POST /baux/{id}/document) : pose
 * `bail.document_id`, active un bail « proposé », referme le dossier de
 * relocation et recale le logement. ⚠️ Jamais `/documents/import` pour
 * ce cas — là, un « bail » n'est qu'une pièce au dossier.
 */
export async function uploadBailDocument(opts: {
  bailId: number;
  file: File;
  /** AAAA-MM-JJ — entrée en vigueur (titre « Bail signé … »). */
  dateEntree?: string;
  /** true = marque le bail « au mois » (chambres). */
  auMois?: boolean;
}): Promise<BailDocument> {
  const fd = new FormData();
  fd.append("file", opts.file);
  if (opts.dateEntree) fd.append("date_entree", opts.dateEntree);
  // Coché seulement : on n'écrase pas un réglage existant quand la case
  // reste vide.
  if (opts.auMois) fd.append("au_mois", "true");
  const r = await authedFetch(
    `/api/v1/immobilier/baux/${opts.bailId}/document`,
    { method: "POST", body: fd }
  );
  const d = await r.json().catch(() => null);
  if (!r.ok) {
    throw new Error((d && (d.detail || d.message)) || `Erreur ${r.status}`);
  }
  return d as BailDocument;
}

