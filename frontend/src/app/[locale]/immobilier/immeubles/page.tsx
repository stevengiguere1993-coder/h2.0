"use client";

import { useEffect, useState } from "react";
import {
  AlertTriangle,
  Building2,
  CheckCircle2,
  ClipboardPaste,
  Download,
  Loader2,
  Plus,
  Search,
  X
} from "lucide-react";

import { Link } from "@/i18n/navigation";
import { authedFetch, getToken } from "@/lib/auth";
import { ImmobilierTopbar, useImmobilierLayout } from "../layout";

type ImmeubleListItem = {
  id: number;
  name: string;
  address: string;
  city?: string | null;
  type: string;
  nb_logements?: number | null;
  cover_photo_url?: string | null;
  has_cover_photo?: boolean;
  is_active: boolean;
  nb_logements_actifs: number;
  nb_logements_occupes: number;
  revenu_mensuel: number;
  taux_occupation: number;
};

const TYPES = [
  { value: "residentiel", label: "Résidentiel" },
  { value: "commercial", label: "Commercial" },
  { value: "mixte", label: "Mixte" },
  { value: "unifamilial", label: "Unifamilial" },
  { value: "autre", label: "Autre" }
];

function fmtCurrency(n: number): string {
  return new Intl.NumberFormat("fr-CA", {
    style: "currency",
    currency: "CAD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  }).format(n);
}

export default function ImmeublesListPage() {
  const { currentEntrepriseId, entreprises } = useImmobilierLayout();
  const [list, setList] = useState<ImmeubleListItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [showImport, setShowImport] = useState(false);
  const [showPlex, setShowPlex] = useState(false);

  const currentEnt = entreprises.find((e) => e.id === currentEntrepriseId) || null;

  async function reload() {
    setError(null);
    try {
      const url =
        currentEntrepriseId != null
          ? `/api/v1/immobilier/immeubles?entreprise_id=${currentEntrepriseId}`
          : "/api/v1/immobilier/immeubles";
      const res = await authedFetch(url);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setList((await res.json()) as ImmeubleListItem[]);
    } catch (err) {
      setError((err as Error).message);
    }
  }

  useEffect(() => {
    setList(null); // évite d'afficher l'ancienne liste pendant le swap
    void reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentEntrepriseId]);

  const filtered = list
    ? list.filter((x) => {
        if (!search.trim()) return true;
        const q = search.toLowerCase();
        return (
          x.name.toLowerCase().includes(q) ||
          x.address.toLowerCase().includes(q) ||
          (x.city || "").toLowerCase().includes(q)
        );
      })
    : null;

  return (
    <>
      <ImmobilierTopbar
        breadcrumbs={[
          { label: "Gestion immobilière", href: "/immobilier" },
          { label: "Immeubles" }
        ]}
        rightSlot={
          <>
            <button
              type="button"
              onClick={() => setShowPlex(true)}
              className="inline-flex items-center gap-1.5 rounded-lg border border-violet-400/30 bg-violet-500/10 px-3 py-1.5 text-xs font-semibold text-violet-200 hover:bg-violet-500/20"
            >
              <ClipboardPaste className="h-3.5 w-3.5" />
              Importer PlexFlow
            </button>
            <button
              type="button"
              onClick={() => setShowImport(true)}
              className="inline-flex items-center gap-1.5 rounded-lg border border-white/15 bg-brand-900 px-3 py-1.5 text-xs font-semibold text-white/80 hover:border-accent-500 hover:text-accent-500"
            >
              <Download className="h-3.5 w-3.5" />
              Import matricule
            </button>
            <button
              type="button"
              onClick={() => setShowCreate(true)}
              disabled={currentEntrepriseId == null}
              title={
                currentEntrepriseId == null
                  ? "Sélectionne une entreprise dans la barre latérale d'abord"
                  : `Créer un immeuble pour ${currentEnt?.name}`
              }
              className="inline-flex items-center gap-1.5 rounded-lg border border-accent-400/30 bg-accent-500/10 px-3 py-1.5 text-xs font-semibold text-accent-500 hover:bg-accent-500/20 disabled:cursor-not-allowed disabled:opacity-50"
            >
              <Plus className="h-3.5 w-3.5" />
              Nouvel immeuble
            </button>
          </>
        }
      />

      <div className="p-4 lg:p-6">
        {currentEnt ? (
          <p className="mb-3 inline-flex items-center gap-2 rounded-full border border-sky-400/30 bg-sky-500/10 px-3 py-1 text-[11px] font-semibold text-sky-200">
            <Building2 className="h-3 w-3" />
            Suivi pour <strong className="text-white">{currentEnt.name}</strong> · les immeubles affichés sont ceux qu&apos;elle détient.
          </p>
        ) : (
          <p className="mb-3 inline-flex items-center gap-2 rounded-full border border-amber-400/30 bg-amber-500/10 px-3 py-1 text-[11px] font-semibold text-amber-200">
            <AlertTriangle className="h-3 w-3" />
            Aucune entreprise sélectionnée — sélectionne-en une dans la barre latérale pour pouvoir ajouter un immeuble.
          </p>
        )}

        <div className="mb-4 flex items-center gap-2">
          <div className="relative max-w-md flex-1">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-white/40" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Recherche par nom, adresse, ville…"
              className="input w-full pl-9"
            />
          </div>
          {filtered ? (
            <span className="text-xs text-white/50">
              {filtered.length} / {list?.length || 0}
            </span>
          ) : null}
        </div>

        {error ? (
          <p className="mb-4 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
            <AlertTriangle className="mr-1.5 inline h-3.5 w-3.5" />
            {error}
          </p>
        ) : null}

        {filtered === null ? (
          <div className="flex items-center gap-2 text-xs text-white/50">
            <Loader2 className="h-3.5 w-3.5 animate-spin" /> Chargement…
          </div>
        ) : filtered.length === 0 ? (
          <p className="rounded-lg border border-brand-800 bg-brand-900 px-4 py-3 text-sm text-white/60">
            Aucun immeuble {search ? "correspondant" : "dans le portefeuille"}.
          </p>
        ) : (
          <div className="overflow-hidden rounded-2xl border border-brand-800 bg-brand-900">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-brand-800 bg-brand-950 text-[10px] uppercase tracking-wider text-white/50">
                <tr>
                  <th className="px-4 py-2.5">Immeuble</th>
                  <th className="px-4 py-2.5">Type</th>
                  <th className="px-4 py-2.5 text-right">Logements</th>
                  <th className="px-4 py-2.5 text-right">Occupation</th>
                  <th className="px-4 py-2.5 text-right">Revenu/m</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-brand-800">
                {filtered.map((imm) => (
                  <tr key={imm.id} className="hover:bg-brand-950/50">
                    <td className="px-4 py-3">
                      <Link
                        // eslint-disable-next-line @typescript-eslint/no-explicit-any
                        href={`/immobilier/immeubles/${imm.id}` as any}
                        className="flex items-center gap-3"
                      >
                        <div className="h-10 w-10 flex-shrink-0 overflow-hidden rounded-lg bg-brand-950">
                          {imm.has_cover_photo || imm.cover_photo_url ? (
                            // eslint-disable-next-line @next/next/no-img-element
                            <img
                              src={
                                imm.has_cover_photo
                                  ? `/api/v1/immobilier/immeubles/${imm.id}/cover-photo?t=${getToken() || ""}`
                                  : (imm.cover_photo_url as string)
                              }
                              alt=""
                              className="h-full w-full object-cover"
                            />
                          ) : (
                            <div className="flex h-full w-full items-center justify-center text-white/30">
                              <Building2 className="h-5 w-5" />
                            </div>
                          )}
                        </div>
                        <div className="min-w-0">
                          <div className="truncate font-bold text-white">
                            {imm.name}
                          </div>
                          <div className="truncate text-[11px] text-white/50">
                            {imm.address}
                            {imm.city ? `, ${imm.city}` : ""}
                          </div>
                        </div>
                      </Link>
                    </td>
                    <td className="px-4 py-3 text-xs text-white/60">
                      {imm.type}
                    </td>
                    <td className="px-4 py-3 text-right font-mono text-xs">
                      {imm.nb_logements_actifs}
                    </td>
                    <td className="px-4 py-3 text-right font-mono text-xs">
                      <span
                        className={
                          imm.taux_occupation >= 0.9
                            ? "text-emerald-300"
                            : "text-amber-300"
                        }
                      >
                        {(imm.taux_occupation * 100).toFixed(0)}%
                      </span>
                    </td>
                    <td className="px-4 py-3 text-right font-mono text-xs text-white/80">
                      {fmtCurrency(imm.revenu_mensuel)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {showCreate ? (
        <CreateImmeubleModal
          entrepriseId={currentEntrepriseId}
          entrepriseName={currentEnt?.name || null}
          onClose={() => setShowCreate(false)}
          onSaved={() => {
            setShowCreate(false);
            void reload();
          }}
        />
      ) : null}

      {showImport ? (
        <ImportMatriculeModal
          onClose={() => setShowImport(false)}
          onSaved={() => {
            setShowImport(false);
            void reload();
          }}
        />
      ) : null}

      {showPlex ? (
        <ImportPlexflowModal
          entreprises={entreprises}
          onClose={() => setShowPlex(false)}
          onImported={() => void reload()}
        />
      ) : null}
    </>
  );
}

function ModalShell({
  title,
  onClose,
  children
}: {
  title: string;
  onClose: () => void;
  children: React.ReactNode;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/70 p-4 backdrop-blur-sm">
      <div className="my-8 w-full max-w-lg rounded-2xl border border-brand-800 bg-brand-950 shadow-2xl">
        <div className="flex items-center justify-between border-b border-brand-800 px-5 py-3">
          <h2 className="text-sm font-bold uppercase tracking-wider text-accent-500">
            {title}
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1.5 text-white/60 hover:bg-brand-900 hover:text-white"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="p-5">{children}</div>
      </div>
    </div>
  );
}

function CreateImmeubleModal({
  entrepriseId,
  entrepriseName,
  onClose,
  onSaved
}: {
  entrepriseId: number | null;
  entrepriseName: string | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [form, setForm] = useState({
    address: "",
    city: "",
    postal_code: "",
    type: "residentiel",
    annee_construction: "",
    nb_logements: "",
    purchase_price: ""
  });
  const [photoFile, setPhotoFile] = useState<File | null>(null);
  const [photoPreview, setPhotoPreview] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  function onPhotoChange(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0] || null;
    setPhotoFile(f);
    setPhotoPreview((prev) => {
      if (prev) URL.revokeObjectURL(prev);
      return f ? URL.createObjectURL(f) : null;
    });
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (entrepriseId == null) {
      setErr(
        "Sélectionne une entreprise propriétaire dans la barre latérale avant de créer un immeuble."
      );
      return;
    }
    setSaving(true);
    setErr(null);
    try {
      // Création de l'immeuble (sans nom — backend prend l'adresse).
      const body: Record<string, unknown> = {
        address: form.address.trim(),
        type: form.type,
        entreprise_id: entrepriseId // auto-rattache l'ownership 100%
      };
      if (form.city.trim()) body.city = form.city.trim();
      if (form.postal_code.trim()) body.postal_code = form.postal_code.trim();
      if (form.annee_construction)
        body.annee_construction = Number(form.annee_construction);
      if (form.nb_logements) body.nb_logements = Number(form.nb_logements);
      if (form.purchase_price)
        body.purchase_price = Number(form.purchase_price);

      const res = await authedFetch("/api/v1/immobilier/immeubles", {
        method: "POST",
        body: JSON.stringify(body)
      });
      if (!res.ok) {
        const t = await res.text();
        throw new Error(t.slice(0, 240) || `HTTP ${res.status}`);
      }
      const created = (await res.json()) as { id: number };

      // Upload photo (best-effort) si fournie.
      if (photoFile && created.id) {
        const fd = new FormData();
        fd.append("file", photoFile);
        const up = await authedFetch(
          `/api/v1/immobilier/immeubles/${created.id}/cover-photo`,
          { method: "POST", body: fd }
        );
        if (!up.ok) {
          const t = await up.text();
          throw new Error(
            `Immeuble créé mais upload photo échoué : ${t.slice(0, 200)}`
          );
        }
      }

      if (photoPreview) URL.revokeObjectURL(photoPreview);
      onSaved();
    } catch (e2) {
      setErr((e2 as Error).message);
    } finally {
      setSaving(false);
    }
  }

  function set<K extends keyof typeof form>(k: K, v: string) {
    setForm({ ...form, [k]: v });
  }

  return (
    <ModalShell title="Nouvel immeuble" onClose={onClose}>
      <form onSubmit={submit} className="grid gap-4">
        {entrepriseName ? (
          <p className="rounded-lg border border-sky-400/30 bg-sky-500/10 px-3 py-2 text-xs text-sky-200">
            Cet immeuble sera rattaché à <strong className="text-white">{entrepriseName}</strong> à 100 %. Tu pourras ajuster les parts plus tard depuis la fiche immeuble &gt; section Ownership.
          </p>
        ) : null}
        <div>
          <label className="label">Adresse</label>
          <input
            required
            value={form.address}
            onChange={(e) => set("address", e.target.value)}
            className="input"
            placeholder="1234 rue Notre-Dame Ouest"
          />
          <p className="mt-1 text-[10px] text-white/40">
            L&apos;immeuble est identifié par son adresse — pas besoin de nom.
          </p>
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <div>
            <label className="label">Ville</label>
            <input
              value={form.city}
              onChange={(e) => set("city", e.target.value)}
              className="input"
              placeholder="Montréal"
            />
          </div>
          <div>
            <label className="label">Code postal</label>
            <input
              value={form.postal_code}
              onChange={(e) => set("postal_code", e.target.value)}
              className="input font-mono"
              placeholder="H4C 1S9"
            />
          </div>
        </div>
        <div className="grid gap-3 sm:grid-cols-3">
          <div>
            <label className="label">Type</label>
            <select
              value={form.type}
              onChange={(e) => set("type", e.target.value)}
              className="input"
            >
              {TYPES.map((t) => (
                <option key={t.value} value={t.value}>
                  {t.label}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="label">Année</label>
            <input
              type="number"
              value={form.annee_construction}
              onChange={(e) => set("annee_construction", e.target.value)}
              className="input font-mono"
              min={1700}
              max={2100}
            />
          </div>
          <div>
            <label className="label">Nb logements</label>
            <input
              type="number"
              value={form.nb_logements}
              onChange={(e) => set("nb_logements", e.target.value)}
              className="input font-mono"
              min={0}
            />
          </div>
        </div>
        <div>
          <label className="label">Prix d&apos;achat (CAD, optionnel)</label>
          <input
            type="number"
            value={form.purchase_price}
            onChange={(e) => set("purchase_price", e.target.value)}
            className="input font-mono"
            min={0}
            step={1000}
          />
        </div>

        <div>
          <label className="label">Photo de couverture (optionnelle)</label>
          <div className="flex items-center gap-3">
            {photoPreview ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={photoPreview}
                alt="Aperçu"
                className="h-16 w-16 rounded-lg object-cover"
              />
            ) : (
              <div className="flex h-16 w-16 items-center justify-center rounded-lg border border-dashed border-brand-700 bg-brand-950 text-white/30">
                <Building2 className="h-6 w-6" />
              </div>
            )}
            <div className="flex-1">
              <input
                type="file"
                accept="image/jpeg,image/png,image/webp,image/heic,image/heif"
                onChange={onPhotoChange}
                className="block w-full text-xs text-white/70 file:mr-3 file:rounded-lg file:border-0 file:bg-accent-500/15 file:px-3 file:py-1.5 file:text-xs file:font-semibold file:text-accent-500 hover:file:bg-accent-500/25"
              />
              <p className="mt-1 text-[10px] text-white/40">
                JPG, PNG, WEBP ou HEIC, max 8 Mo.
              </p>
            </div>
          </div>
        </div>

        {err ? (
          <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
            <AlertTriangle className="mr-1.5 inline h-3.5 w-3.5" />
            {err}
          </p>
        ) : null}

        <div className="flex items-center justify-end gap-2 border-t border-brand-800 pt-4">
          <button
            type="button"
            onClick={onClose}
            className="btn-secondary text-sm"
          >
            Annuler
          </button>
          <button
            type="submit"
            disabled={saving || !form.address.trim()}
            className="btn-accent inline-flex items-center text-sm disabled:opacity-60"
          >
            {saving ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Création…
              </>
            ) : (
              "Créer"
            )}
          </button>
        </div>
      </form>
    </ModalShell>
  );
}

function ImportMatriculeModal({
  onClose,
  onSaved
}: {
  onClose: () => void;
  onSaved: () => void;
}) {
  const [matricule, setMatricule] = useState("");
  const [name, setName] = useState("");
  const [createLogements, setCreateLogements] = useState(true);
  const [importing, setImporting] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [result, setResult] = useState<{
    nb_logements_crees: number;
  } | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setImporting(true);
    setErr(null);
    setResult(null);
    try {
      const body: Record<string, unknown> = {
        matricule: matricule.trim(),
        create_logements: createLogements
      };
      if (name.trim()) body.name = name.trim();
      const res = await authedFetch(
        "/api/v1/immobilier/immeubles/import-matricule",
        {
          method: "POST",
          body: JSON.stringify(body)
        }
      );
      if (!res.ok) {
        const t = await res.text();
        throw new Error(t.slice(0, 240) || `HTTP ${res.status}`);
      }
      const data = (await res.json()) as { nb_logements_crees: number };
      setResult({ nb_logements_crees: data.nb_logements_crees });
      setTimeout(onSaved, 1200);
    } catch (e2) {
      setErr((e2 as Error).message);
    } finally {
      setImporting(false);
    }
  }

  return (
    <ModalShell title="Importer depuis matricule MAMH" onClose={onClose}>
      <form onSubmit={submit} className="grid gap-4">
        <p className="rounded-lg border border-sky-400/30 bg-sky-500/5 px-3 py-2 text-xs text-sky-200">
          Le matricule de 18 chiffres du rôle d&apos;évaluation. Récupère
          adresse, année, nb logements, superficies depuis la table déjà
          importée.
        </p>
        <div>
          <label className="label">Matricule</label>
          <input
            required
            value={matricule}
            onChange={(e) => setMatricule(e.target.value)}
            className="input font-mono"
            placeholder="9999-99-9999-9-999-9999"
          />
        </div>
        <div>
          <label className="label">Nom (optionnel)</label>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="input"
            placeholder="Auto-généré depuis l'adresse si vide"
          />
        </div>
        <label className="flex cursor-pointer items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={createLogements}
            onChange={(e) => setCreateLogements(e.target.checked)}
            className="h-4 w-4 accent-accent-500"
          />
          <span>
            Créer automatiquement les logements (Apt 1 à N selon nb_logements)
          </span>
        </label>

        {err ? (
          <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
            <AlertTriangle className="mr-1.5 inline h-3.5 w-3.5" />
            {err}
          </p>
        ) : null}

        {result ? (
          <p className="rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-300">
            <CheckCircle2 className="mr-1.5 inline h-3.5 w-3.5" />
            Immeuble créé avec {result.nb_logements_crees} logement
            {result.nb_logements_crees > 1 ? "s" : ""}.
          </p>
        ) : null}

        <div className="flex items-center justify-end gap-2 border-t border-brand-800 pt-4">
          <button
            type="button"
            onClick={onClose}
            className="btn-secondary text-sm"
          >
            Fermer
          </button>
          <button
            type="submit"
            disabled={importing || !matricule.trim()}
            className="btn-accent inline-flex items-center text-sm disabled:opacity-60"
          >
            {importing ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Import…
              </>
            ) : (
              <>
                <Download className="mr-2 h-4 w-4" />
                Importer
              </>
            )}
          </button>
        </div>
      </form>
    </ModalShell>
  );
}

// ─── Import « rent roll » PlexFlow (copier-coller) ──────────────────────

type PlexUnit = {
  numero: string;
  tenant: string | null;
  rent: number | null;
  status: string;
  will_create_lease: boolean;
  warnings: string[];
};
type PlexBuilding = {
  address: string;
  city: string | null;
  postal_code: string | null;
  nb_units: number;
  nb_leases: number;
  already_exists: boolean;
  units: PlexUnit[];
  warnings: string[];
};
type PlexCompany = {
  name: string;
  entreprise_id: number | null;
  matched: boolean;
  buildings: PlexBuilding[];
};
type PlexResult = {
  dry_run: boolean;
  companies: PlexCompany[];
  totals: Record<string, number>;
  created: {
    immeubles: number;
    logements: number;
    locataires: number;
    baux: number;
    buildings_skipped: number;
  } | null;
  warnings: string[];
};

function ImportPlexflowModal({
  entreprises,
  onClose,
  onImported
}: {
  entreprises: { id: number; name: string }[];
  onClose: () => void;
  onImported: () => void;
}) {
  const [raw, setRaw] = useState("");
  const [loading, setLoading] = useState(false);
  const [preview, setPreview] = useState<PlexResult | null>(null);
  const [committed, setCommitted] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  // Mapping manuel : nom de compagnie PlexFlow → entreprise_id Kratos.
  const [overrides, setOverrides] = useState<Record<string, number>>({});

  async function run(dryRun: boolean, ov: Record<string, number> = overrides) {
    setLoading(true);
    setErr(null);
    try {
      const res = await authedFetch("/api/v1/immobilier/import-plexflow", {
        method: "POST",
        body: JSON.stringify({
          raw_text: raw,
          dry_run: dryRun,
          company_overrides: ov
        })
      });
      if (res.status === 401)
        throw new Error("Session expirée — reconnecte-toi puis réessaie.");
      if (!res.ok)
        throw new Error((await res.text()).slice(0, 300) || `http_${res.status}`);
      const data = (await res.json()) as PlexResult;
      setPreview(data);
      if (!dryRun) {
        setCommitted(true);
        onImported();
      }
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setLoading(false);
    }
  }

  function mapCompany(companyName: string, entrepriseId: number) {
    const next = { ...overrides, [companyName]: entrepriseId };
    setOverrides(next);
    // Re-prévisualise pour rafraîchir le rattachement et les compteurs.
    void run(true, next);
  }

  const importable =
    !!preview &&
    preview.companies.some(
      (c) => c.matched && c.buildings.some((b) => !b.already_exists)
    );

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/70 p-4 backdrop-blur-sm">
      <div className="my-8 w-full max-w-3xl rounded-2xl border border-brand-800 bg-brand-950 shadow-2xl">
        <div className="flex items-center justify-between border-b border-brand-800 px-5 py-3">
          <h2 className="text-sm font-bold uppercase tracking-wider text-violet-300">
            Importer depuis PlexFlow
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1.5 text-white/60 hover:bg-brand-900 hover:text-white"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="space-y-4 p-5">
          {!committed ? (
            <>
              <p className="text-xs text-white/60">
                Copie une ou plusieurs fiches « Property » depuis PlexFlow et
                colle-les ici. Les compagnies sont rattachées par leur nom aux
                entreprises déjà créées dans Kratos. Prévisualise d&apos;abord,
                puis importe.
              </p>
              <textarea
                value={raw}
                onChange={(e) => setRaw(e.target.value)}
                rows={8}
                placeholder="Colle ici le texte copié depuis PlexFlow…"
                className="w-full rounded-lg border border-brand-800 bg-brand-900 px-3 py-2 font-mono text-xs text-white/90 outline-none focus:border-violet-300"
              />
            </>
          ) : null}

          {err ? (
            <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
              {err}
            </p>
          ) : null}

          {committed && preview?.created ? (
            <div className="rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-200">
              <p className="font-semibold">Import terminé ✅</p>
              <p className="mt-1 text-xs">
                {preview.created.immeubles} immeuble(s) ·{" "}
                {preview.created.logements} logement(s) ·{" "}
                {preview.created.locataires} locataire(s) ·{" "}
                {preview.created.baux} bail/baux créés.
                {preview.created.buildings_skipped > 0
                  ? ` ${preview.created.buildings_skipped} immeuble(s) déjà présent(s) ignoré(s).`
                  : ""}
              </p>
            </div>
          ) : null}

          {preview ? (
            <PlexPreview
              result={preview}
              entreprises={entreprises}
              onMap={mapCompany}
              busy={loading}
            />
          ) : null}
        </div>

        <div className="flex items-center justify-end gap-2 border-t border-brand-800 px-5 py-3">
          {committed ? (
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg bg-violet-500/20 px-4 py-2 text-xs font-semibold text-violet-100 hover:bg-violet-500/30"
            >
              Fermer
            </button>
          ) : (
            <>
              <button
                type="button"
                onClick={onClose}
                className="rounded-lg border border-white/15 px-4 py-2 text-xs font-semibold text-white/70 hover:text-white"
              >
                Annuler
              </button>
              <button
                type="button"
                onClick={() => void run(true)}
                disabled={loading || !raw.trim()}
                className="inline-flex items-center gap-1.5 rounded-lg border border-white/15 bg-brand-900 px-4 py-2 text-xs font-semibold text-white/80 hover:text-white disabled:opacity-50"
              >
                {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
                Prévisualiser
              </button>
              <button
                type="button"
                onClick={() => void run(false)}
                disabled={loading || !importable}
                title={
                  !importable
                    ? "Prévisualise d'abord ; au moins une compagnie doit être reconnue."
                    : "Créer les immeubles, logements, locataires et baux"
                }
                className="inline-flex items-center gap-1.5 rounded-lg border border-violet-400/30 bg-violet-500/15 px-4 py-2 text-xs font-semibold text-violet-100 hover:bg-violet-500/25 disabled:opacity-50"
              >
                {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
                Importer pour de vrai
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function PlexPreview({
  result,
  entreprises,
  onMap,
  busy
}: {
  result: PlexResult;
  entreprises: { id: number; name: string }[];
  onMap: (companyName: string, entrepriseId: number) => void;
  busy: boolean;
}) {
  const t = result.totals || {};
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2 text-[11px]">
        <span className="rounded-full bg-brand-900 px-2.5 py-1 text-white/70">
          {t.companies_matched ?? 0}/{t.companies ?? 0} compagnies reconnues
        </span>
        <span className="rounded-full bg-brand-900 px-2.5 py-1 text-white/70">
          {t.buildings ?? 0} immeubles
        </span>
        <span className="rounded-full bg-brand-900 px-2.5 py-1 text-white/70">
          {t.units ?? 0} logements
        </span>
        <span className="rounded-full bg-brand-900 px-2.5 py-1 text-white/70">
          {t.leases ?? 0} baux
        </span>
        {t.buildings_duplicate ? (
          <span className="rounded-full bg-amber-500/15 px-2.5 py-1 text-amber-200">
            {t.buildings_duplicate} déjà présent(s)
          </span>
        ) : null}
      </div>

      {result.warnings.length > 0 ? (
        <ul className="space-y-1 rounded-lg border border-amber-500/30 bg-amber-500/5 p-2 text-[11px] text-amber-200">
          {result.warnings.map((w, i) => (
            <li key={i} className="flex gap-1.5">
              <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" />
              {w}
            </li>
          ))}
        </ul>
      ) : null}

      <div className="space-y-2">
        {result.companies.map((c, ci) => (
          <div
            key={ci}
            className="rounded-lg border border-brand-800 bg-brand-900/40 p-3"
          >
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="text-sm font-semibold text-white">{c.name}</span>
              <div className="flex items-center gap-2">
                {c.matched ? (
                  <span className="badge badge-emerald">
                    <CheckCircle2 className="h-3 w-3" /> rattachée
                  </span>
                ) : (
                  <span className="badge badge-rose">
                    <AlertTriangle className="h-3 w-3" /> à rattacher
                  </span>
                )}
                {/* Mapping manuel : choisir l'entreprise Kratos (ex. quand
                    le nom diffère — « 9510-7520 » = BGV). */}
                <select
                  value={c.entreprise_id ?? ""}
                  disabled={busy}
                  onChange={(e) => onMap(c.name, Number(e.target.value))}
                  className="rounded-lg border border-brand-800 bg-brand-900 px-2 py-1 text-[11px] font-semibold text-white outline-none focus:border-violet-300 disabled:opacity-50"
                >
                  <option value="" disabled className="bg-brand-950 text-white">
                    — rattacher à —
                  </option>
                  {entreprises.map((e) => (
                    <option
                      key={e.id}
                      value={e.id}
                      className="bg-brand-950 text-white"
                    >
                      {e.name}
                    </option>
                  ))}
                </select>
              </div>
            </div>
            <div className="mt-2 space-y-1.5">
              {c.buildings.map((b, bi) => (
                <details key={bi} className="rounded-md bg-brand-950/50 px-2 py-1.5">
                  <summary className="cursor-pointer text-xs text-white/80">
                    <span className="font-medium text-white">{b.address}</span>
                    {b.city ? `, ${b.city}` : ""}{" "}
                    <span className="text-white/50">
                      — {b.nb_units} logements · {b.nb_leases} baux
                    </span>
                    {b.already_exists ? (
                      <span className="ml-1 rounded bg-amber-500/15 px-1.5 py-0.5 text-[10px] text-amber-200">
                        déjà importé
                      </span>
                    ) : null}
                  </summary>
                  {b.warnings.map((w, wi) => (
                    <p key={wi} className="mt-1 text-[10px] text-amber-300/90">
                      ⚠ {w}
                    </p>
                  ))}
                  <table className="mt-1.5 w-full text-[11px]">
                    <tbody className="divide-y divide-brand-800/60">
                      {b.units.map((u, ui) => (
                        <tr key={ui} className="text-white/70">
                          <td className="py-0.5 pr-2 font-mono">{u.numero}</td>
                          <td className="py-0.5 pr-2">{u.tenant || "—"}</td>
                          <td className="py-0.5 pr-2 text-right tabular-nums">
                            {u.rent ? fmtCurrency(u.rent) : "—"}
                          </td>
                          <td className="py-0.5 text-right">
                            <span
                              className={
                                u.status === "active"
                                  ? "text-emerald-300"
                                  : u.status === "vacant"
                                    ? "text-white/40"
                                    : "text-sky-300"
                              }
                            >
                              {u.status}
                            </span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </details>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
