"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  AlertCircle,
  ChevronDown,
  ChevronRight,
  ExternalLink,
  FileText,
  FolderOpen,
  Landmark,
  Link2,
  Loader2,
  MapPin,
  RefreshCw,
  School,
  ShieldCheck
} from "lucide-react";

import { EntityDriveSection } from "@/components/drive/EntityDriveSection";
import { Link } from "@/i18n/navigation";
import { authedFetch } from "@/lib/auth";

/**
 * <ImmeubleDocumentsDrive> — documents Drive d'un immeuble (Steven,
 * 2026-11-13 : « certificat de localisation, taxes scolaires, taxes
 * municipales, assurance, toutes autres documents reçus »).
 *
 * Autonome (seule prop : immeubleId, ses propres lectures) et sans marge
 * de page : le conteneur hôte espace. Lit
 * GET /api/v1/immobilier/immeubles/{id}/drive :
 *  - dossier relié → documents clés (toujours affichés, même vides) puis
 *    les autres catégories, chacune repliable ;
 *  - pas de dossier mais un candidat certain → relié d'office ;
 *  - sinon → liste des dossiers candidats à relier d'un clic.
 * En dessous, l'explorateur Drive complet (dépôt, aperçu, sous-dossiers).
 */

type DocDrive = {
  id: string;
  nom: string;
  mime_type?: string | null;
  taille?: number | null;
  modifie_le?: string | null;
  url?: string | null;
  dossier?: string | null;
  annee?: number | null;
};

type Categorie = {
  cle: string;
  libelle: string;
  cle_document: boolean;
  nombre: number;
  documents: DocDrive[];
};

type Candidat = {
  id: string;
  nom: string;
  url?: string | null;
  parent_nom?: string | null;
  score: number;
  sous_proprietaire: boolean;
};

type Reponse = {
  immeuble_id: number;
  dossier: { id: string; nom?: string | null; url: string } | null;
  candidats: Candidat[];
  suggestion: Candidat | null;
  categories: Categorie[];
  nombre_fichiers?: number;
  tronque?: boolean;
  lu_le?: string;
};

type Erreur = { message: string; code?: string | null; ou?: string | null };

const ICONES: Record<string, typeof FileText> = {
  certificat_localisation: MapPin,
  taxes_municipales: Landmark,
  taxes_scolaires: School,
  assurance: ShieldCheck
};

function fmtDate(iso?: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleDateString("fr-CA", {
    year: "numeric",
    month: "short",
    day: "numeric"
  });
}

async function lireErreur(res: Response): Promise<Erreur> {
  try {
    const j = await res.json();
    const d = j?.detail;
    if (d && typeof d === "object") {
      return {
        message: String(d.message || `Erreur ${res.status}`),
        code: d.code ?? null,
        ou: d.ou ?? null
      };
    }
    return { message: typeof d === "string" ? d : `Erreur ${res.status}` };
  } catch {
    return { message: `Erreur ${res.status}` };
  }
}

function LigneDocument({ doc }: { doc: DocDrive }) {
  return (
    <li className="flex items-start gap-2 py-1.5">
      <FileText className="mt-0.5 h-3.5 w-3.5 shrink-0 text-white/50" />
      <div className="min-w-0 flex-1">
        <a
          href={doc.url ?? undefined}
          target="_blank"
          rel="noreferrer"
          className="block truncate text-sm text-white hover:text-accent-500 hover:underline"
          title={doc.nom}
        >
          {doc.nom}
        </a>
        <span className="block truncate text-xs text-white/60">
          {[doc.annee ? String(doc.annee) : null, fmtDate(doc.modifie_le), doc.dossier]
            .filter(Boolean)
            .join(" · ")}
        </span>
      </div>
    </li>
  );
}

function CarteCle({ cat }: { cat: Categorie }) {
  const [ouvert, setOuvert] = useState(false);
  const Icone = ICONES[cat.cle] ?? FileText;
  const dernier = cat.documents[0];
  const autres = cat.documents.slice(1);
  return (
    <div className="rounded-xl border border-brand-700 bg-brand-950 p-3">
      <div className="flex items-center gap-2">
        <Icone className="h-4 w-4 text-accent-500" />
        <h3 className="text-sm font-semibold text-white">{cat.libelle}</h3>
        <span className="ml-auto text-xs text-white/60">
          {cat.nombre ? `${cat.nombre} doc.` : ""}
        </span>
      </div>
      {dernier ? (
        <>
          <a
            href={dernier.url ?? undefined}
            target="_blank"
            rel="noreferrer"
            className="mt-2 flex items-center gap-1.5 text-sm font-medium text-white hover:text-accent-500"
            title={dernier.nom}
          >
            <span className="truncate">{dernier.nom}</span>
            <ExternalLink className="h-3.5 w-3.5 shrink-0" />
          </a>
          <p className="mt-0.5 truncate text-xs text-white/60">
            {[
              dernier.annee ? `Année ${dernier.annee}` : null,
              dernier.modifie_le ? `modifié le ${fmtDate(dernier.modifie_le)}` : null
            ]
              .filter(Boolean)
              .join(" · ")}
          </p>
          {autres.length ? (
            <>
              <button
                type="button"
                onClick={() => setOuvert((v) => !v)}
                className="mt-2 inline-flex items-center gap-1 text-xs font-medium text-white/70 hover:text-white"
              >
                {ouvert ? (
                  <ChevronDown className="h-3.5 w-3.5" />
                ) : (
                  <ChevronRight className="h-3.5 w-3.5" />
                )}
                {autres.length} autre{autres.length > 1 ? "s" : ""}
              </button>
              {ouvert ? (
                <ul className="mt-1 divide-y divide-brand-800">
                  {autres.map((d) => (
                    <LigneDocument key={d.id} doc={d} />
                  ))}
                </ul>
              ) : null}
            </>
          ) : null}
        </>
      ) : (
        <p className="mt-2 text-sm text-amber-300">
          Aucun document repéré dans le dossier Drive.
        </p>
      )}
    </div>
  );
}

function SectionCategorie({ cat }: { cat: Categorie }) {
  const [ouvert, setOuvert] = useState(false);
  return (
    <div className="rounded-xl border border-brand-700 bg-brand-950">
      <button
        type="button"
        onClick={() => setOuvert((v) => !v)}
        className="flex w-full items-center gap-2 px-3 py-2.5 text-left"
      >
        {ouvert ? (
          <ChevronDown className="h-4 w-4 text-white/60" />
        ) : (
          <ChevronRight className="h-4 w-4 text-white/60" />
        )}
        <span className="text-sm font-semibold text-white">{cat.libelle}</span>
        <span className="ml-auto text-xs text-white/60">{cat.nombre}</span>
      </button>
      {ouvert ? (
        <ul className="divide-y divide-brand-800 border-t border-brand-800 px-3">
          {cat.documents.map((d) => (
            <LigneDocument key={d.id} doc={d} />
          ))}
        </ul>
      ) : null}
    </div>
  );
}

export function ImmeubleDocumentsDrive({ immeubleId }: { immeubleId: number }) {
  const [data, setData] = useState<Reponse | null>(null);
  const [erreur, setErreur] = useState<Erreur | null>(null);
  const [chargement, setChargement] = useState(true);
  const [occupe, setOccupe] = useState<string | null>(null);
  const [cleExplorateur, setCleExplorateur] = useState(0);
  const autoTente = useRef(false);

  const charger = useCallback(
    async (rafraichir = false) => {
      if (!Number.isFinite(immeubleId) || immeubleId <= 0) return;
      setChargement(true);
      setErreur(null);
      try {
        const res = await authedFetch(
          `/api/v1/immobilier/immeubles/${immeubleId}/drive${rafraichir ? "?rafraichir=true" : ""}`
        );
        if (!res.ok) {
          setErreur(await lireErreur(res));
          setData(null);
          return;
        }
        setData((await res.json()) as Reponse);
      } catch (e) {
        setErreur({ message: (e as Error)?.message || "Erreur réseau" });
      } finally {
        setChargement(false);
      }
    },
    [immeubleId]
  );

  useEffect(() => {
    autoTente.current = false;
    void charger();
  }, [charger]);

  const relier = useCallback(
    async (corps: { auto?: boolean; dossier_id?: string; dossier_nom?: string }) => {
      setOccupe(corps.dossier_id ?? "auto");
      try {
        const res = await authedFetch(
          `/api/v1/immobilier/immeubles/${immeubleId}/drive/relier`,
          { method: "POST", body: JSON.stringify(corps) }
        );
        if (!res.ok) {
          setErreur(await lireErreur(res));
          return;
        }
        setCleExplorateur((k) => k + 1);
        await charger();
      } finally {
        setOccupe(null);
      }
    },
    [immeubleId, charger]
  );

  // Un seul dossier correspond avec certitude → relié d'office (une fois).
  useEffect(() => {
    if (data && !data.dossier && data.suggestion && !autoTente.current) {
      autoTente.current = true;
      void relier({ auto: true });
    }
  }, [data, relier]);

  const onLinkChange = useCallback(
    (folderId: string | null) => {
      if (folderId && folderId === data?.dossier?.id) return;
      void charger();
    },
    [charger, data?.dossier?.id]
  );

  if (erreur?.code === "reserve_gestionnaires") {
    return (
      <p className="rounded-xl border border-brand-700 bg-brand-950 p-4 text-sm text-white/70">
        {erreur.message}
      </p>
    );
  }

  const cles = (data?.categories ?? []).filter((c) => c.cle_document);
  const autres = (data?.categories ?? []).filter((c) => !c.cle_document);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <FolderOpen className="h-5 w-5 text-accent-500" />
        <h2 className="text-base font-semibold text-white">Documents de l&apos;immeuble</h2>
        {data?.dossier ? (
          <a
            href={data.dossier.url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 text-xs font-medium text-white/70 hover:text-accent-500"
          >
            {data.dossier.nom || "Dossier Drive"}
            <ExternalLink className="h-3 w-3" />
          </a>
        ) : null}
        <button
          type="button"
          onClick={() => void charger(true)}
          disabled={chargement}
          className="btn-secondary btn-xs ml-auto disabled:opacity-50"
          title="Relire le dossier Drive"
        >
          {chargement ? (
            <Loader2 className="mr-1 h-3 w-3 animate-spin" />
          ) : (
            <RefreshCw className="mr-1 h-3 w-3" />
          )}
          Actualiser
        </button>
      </div>

      {erreur ? (
        <div className="flex items-start gap-2 rounded-xl border border-rose-500/40 bg-rose-500/10 p-3 text-sm text-rose-300">
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
          <span>
            {erreur.message}
            {erreur.code === "drive_non_connecte" ? (
              <>
                {" "}
                <Link
                  // eslint-disable-next-line @typescript-eslint/no-explicit-any
                  href={"/parametres/drive" as any}
                  className="font-semibold underline"
                >
                  Connecter Google Drive
                </Link>
              </>
            ) : null}
          </span>
        </div>
      ) : null}

      {chargement && !data ? (
        <div className="flex items-center gap-2 text-sm text-white/60">
          <Loader2 className="h-4 w-4 animate-spin" /> Lecture du dossier Drive…
        </div>
      ) : null}

      {data && !data.dossier ? (
        <div className="rounded-xl border border-brand-700 bg-brand-950 p-4">
          {occupe === "auto" ? (
            <p className="flex items-center gap-2 text-sm text-white/70">
              <Loader2 className="h-4 w-4 animate-spin" /> Dossier trouvé, liaison en cours…
            </p>
          ) : data.candidats.length ? (
            <>
              <p className="text-sm text-white/80">
                Plusieurs dossiers Drive peuvent correspondre à cet immeuble. Choisis le bon :
              </p>
              <ul className="mt-2 divide-y divide-brand-800">
                {data.candidats.map((c) => (
                  <li key={c.id} className="flex flex-wrap items-center gap-2 py-2">
                    <FolderOpen className="h-4 w-4 text-white/60" />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-medium text-white">{c.nom}</span>
                      <span className="block truncate text-xs text-white/60">
                        {[c.parent_nom, c.sous_proprietaire ? "compagnie propriétaire" : null]
                          .filter(Boolean)
                          .join(" · ")}
                      </span>
                    </span>
                    {c.url ? (
                      <a
                        href={c.url}
                        target="_blank"
                        rel="noreferrer"
                        className="btn-secondary btn-xs"
                      >
                        <ExternalLink className="mr-1 h-3 w-3" /> Voir
                      </a>
                    ) : null}
                    <button
                      type="button"
                      disabled={!!occupe}
                      onClick={() => void relier({ dossier_id: c.id, dossier_nom: c.nom })}
                      className="btn-accent btn-xs disabled:opacity-50"
                    >
                      {occupe === c.id ? (
                        <Loader2 className="mr-1 h-3 w-3 animate-spin" />
                      ) : (
                        <Link2 className="mr-1 h-3 w-3" />
                      )}
                      Relier
                    </button>
                  </li>
                ))}
              </ul>
            </>
          ) : (
            <p className="text-sm text-white/80">
              Aucun dossier Drive n&apos;a été trouvé automatiquement pour cette adresse (il est
              cherché sous « Immeuble » dans le dossier de chaque compagnie). Relie-le à la main
              ci-dessous.
            </p>
          )}
        </div>
      ) : null}

      {data?.dossier ? (
        <>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            {cles.map((c) => (
              <CarteCle key={c.cle} cat={c} />
            ))}
          </div>
          {autres.length ? (
            <div className="space-y-2">
              <h3 className="text-xs font-semibold uppercase tracking-wider text-white/60">
                Autres documents reçus
              </h3>
              {autres.map((c) => (
                <SectionCategorie key={c.cle} cat={c} />
              ))}
            </div>
          ) : null}
          <p className="text-xs text-white/60">
            {data.nombre_fichiers ?? 0} fichier{(data.nombre_fichiers ?? 0) > 1 ? "s" : ""} lu
            {(data.nombre_fichiers ?? 0) > 1 ? "s" : ""} dans le dossier
            {data.tronque ? " (dossier très volumineux : la liste est partielle)" : ""}. Classement
            selon le nom du fichier, sinon son sous-dossier.
          </p>
        </>
      ) : null}

      <EntityDriveSection
        key={cleExplorateur}
        entityType="Immeuble"
        entityId={immeubleId}
        title="Tout le dossier Drive"
        toujoursActif
        onLinkChange={onLinkChange}
      />
    </div>
  );
}
