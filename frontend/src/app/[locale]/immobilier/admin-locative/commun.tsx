"use client";

/**
 * Admin locative (Phil 2026-11-10) — types et petits outils partagés par les
 * onglets : le carnet de contacts de cette section, le sélecteur « Choisir dans
 * le carnet », les formats de date et de montant.
 */

import { useMemo } from "react";

import { SearchSelect, type SearchSelectOption } from "@/components/search-select";

export const BASE_TAL = "/api/v1/immobilier/tal-bail";
export const BASE_ADMIN = "/api/v1/immobilier/admin-locative";

export type Contact = {
  id: number;
  nom: string;
  telephone: string | null;
  courriel: string | null;
  adresse: string | null;
  role: string | null;
  notes: string | null;
  actif: boolean;
  created_by_email: string | null;
  created_at: string | null;
  updated_at: string | null;
};

export type RoleContact = "locateur" | "locataire" | "caution";

export const ROLES: { value: RoleContact; label: string; pluriel: string }[] = [
  { value: "locateur", label: "Locateur", pluriel: "Locateurs" },
  { value: "locataire", label: "Locataire", pluriel: "Locataires" },
  { value: "caution", label: "Caution", pluriel: "Cautions" }
];

export function libelleRole(role: string | null | undefined): string {
  return ROLES.find((r) => r.value === role)?.label || "";
}

export async function lireErreur(r: Response): Promise<string> {
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

export function nombre(v: string): number | null {
  // « 1 250,75 $ » se lit 1250.75 : espaces et signe de dollar retirés, virgule lue comme un point.
  const n = Number(String(v).replace(/[\s$]/g, "").replace(",", "."));
  return v.trim() !== "" && Number.isFinite(n) ? n : null;
}

export function dateFr(iso: string | null | undefined): string {
  if (!iso) return "";
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  if (!y || !m || !d) return iso;
  return new Date(y, m - 1, d).toLocaleDateString("fr-CA", { day: "numeric", month: "short", year: "numeric" });
}

/** Date d'un instant du serveur (horodatage), lue à l'heure du navigateur. */
export function dateInstantFr(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return dateFr(iso);
  return d.toLocaleDateString("fr-CA", { day: "numeric", month: "short", year: "numeric" });
}

/** Montant en dollars : « 1 450 $ », « 2,99 $ » (les cents seulement s'il y en a). */
export function argent(n: number | null | undefined, toujoursCents = false): string {
  if (n == null || !Number.isFinite(n)) return "—";
  const cents = toujoursCents || !Number.isInteger(n);
  return `${n.toLocaleString("fr-CA", { minimumFractionDigits: cents ? 2 : 0, maximumFractionDigits: 2 })} $`;
}

export function sansAccents(s: string): string {
  return s
    .normalize("NFKD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase();
}

/** Nom court d'un utilisateur à partir de son courriel (« philippe.meuser@… » → « Philippe Meuser »). */
export function nomDepuisCourriel(courriel: string | null | undefined): string {
  const local = (courriel || "").split("@")[0];
  if (!local) return "—";
  return local
    .split(/[._-]+/)
    .filter(Boolean)
    .map((m) => m.charAt(0).toUpperCase() + m.slice(1))
    .join(" ");
}

// ─── Mise en forme partagée ────────────────────────────────────────────

/** Petite étoile rouge d'un champ obligatoire. */
export function Etoile() {
  return (
    <span className="ml-0.5 font-bold text-rose-400" title="Obligatoire">
      *
    </span>
  );
}

/** Tant que le carnet est vide, le sélecteur de contacts n'a rien à proposer : on le dit. */
export function NoteCarnetVide({ contacts }: { contacts: Contact[] }) {
  if (contacts.some((c) => c.actif)) return null;
  return (
    <p className="rounded-lg border border-brand-800 bg-brand-900/60 px-3 py-2 text-[11px] text-white/55">
      Le carnet de contacts est encore vide. Les personnes que tu inscris ici y entrent toutes seules : la prochaine fois, une
      liste « Choisir dans le carnet » apparaîtra au-dessus de chaque nom.
    </p>
  );
}

export function Champ({
  label,
  children,
  className = "",
  requis = false
}: {
  label: string;
  children: React.ReactNode;
  className?: string;
  /** Champ obligatoire : une petite étoile rouge suit le libellé. */
  requis?: boolean;
}) {
  return (
    <label className={`flex flex-col gap-1 text-xs text-white/60 ${className}`}>
      <span>
        {label}
        {requis ? <Etoile /> : null}
      </span>
      {children}
    </label>
  );
}

export function Bloc({ titre, note, children }: { titre: string; note?: string; children: React.ReactNode }) {
  return (
    <fieldset className="rounded-xl border border-brand-800 bg-brand-900/60 p-3">
      <legend className="px-1 text-[11px] font-semibold uppercase tracking-wider text-accent-500">{titre}</legend>
      {note ? <p className="mb-2 text-[11px] text-white/45">{note}</p> : null}
      {children}
    </fieldset>
  );
}

/** Fenêtre posée par-dessus la page (clic à côté = fermer). */
export function Fenetre({
  titre,
  sousTitre,
  icone,
  onClose,
  large = false,
  children,
  pied
}: {
  titre: string;
  sousTitre?: string;
  icone?: React.ReactNode;
  onClose: () => void;
  large?: boolean;
  children: React.ReactNode;
  pied?: React.ReactNode;
}) {
  return (
    <div className="fixed inset-0 z-[55] flex items-start justify-center overflow-y-auto bg-black/70 p-4 backdrop-blur-sm" onClick={onClose}>
      <div
        className={`my-6 w-full ${large ? "max-w-3xl" : "max-w-lg"} rounded-2xl border border-brand-800 bg-brand-950 shadow-2xl`}
        onClick={(ev) => ev.stopPropagation()}
      >
        <div className="flex items-center justify-between gap-2 border-b border-brand-800 px-5 py-3">
          <div>
            <h2 className="flex items-center gap-2 text-sm font-bold uppercase tracking-wider text-accent-500">
              {icone} {titre}
            </h2>
            {sousTitre ? <p className="text-xs text-white/55">{sousTitre}</p> : null}
          </div>
          <button type="button" onClick={onClose} className="btn-ghost btn-xs" aria-label="Fermer">
            ✕
          </button>
        </div>
        <div className="space-y-3 px-5 py-4">{children}</div>
        {pied ? <div className="flex flex-wrap items-center gap-2 border-t border-brand-800 px-5 py-3">{pied}</div> : null}
      </div>
    </div>
  );
}

// ─── Choisir une personne déjà au carnet ───────────────────────────────

/**
 * « Une fois une personne créée, je peux venir la sélectionner la fois
 * d'après » : liste du carnet avec recherche pendant la frappe. Choisir une
 * personne remplit les champs ; on peut ensuite les corriger à la main.
 * N'affiche rien tant que le carnet est vide.
 */
export function ChoisirContact({
  contacts,
  role,
  onChoisir,
  className
}: {
  contacts: Contact[];
  role?: RoleContact;
  onChoisir: (c: Contact) => void;
  className?: string;
}) {
  const options = useMemo<SearchSelectOption[]>(() => {
    const rang = (c: Contact) => (role && c.role === role ? 0 : 1);
    const duRole = ROLES.find((r) => r.value === role)?.pluriel;
    return contacts
      .filter((c) => c.actif)
      .sort((a, b) => rang(a) - rang(b) || sansAccents(a.nom).localeCompare(sansAccents(b.nom)))
      .map((c) => ({
        value: String(c.id),
        label: [c.nom, c.courriel, c.telephone].filter(Boolean).join(" · "),
        group: role ? (c.role === role ? `${duRole} du carnet` : "Autres contacts") : undefined
      }));
  }, [contacts, role]);

  if (options.length === 0) return null;
  return (
    <SearchSelect
      value=""
      onChange={(v) => {
        const c = contacts.find((x) => String(x.id) === v);
        if (c) onChoisir(c);
      }}
      options={options}
      placeholder="Choisir dans le carnet…"
      className={className}
    />
  );
}
