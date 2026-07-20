"use client";

import { useEffect, useState } from "react";
import {
  AlertTriangle,
  Loader2,
  Plus,
  Search,
  User,
  X
} from "lucide-react";

import { Link, useRouter } from "@/i18n/navigation";
import { authedFetch } from "@/lib/auth";
import { ImmobilierTopbar, useImmobilierLayout } from "../layout";

type Locataire = {
  id: number;
  full_name: string;
  email?: string | null;
  phone?: string | null;
  paiement_score?: number | null;
  employeur?: string | null;
  revenu_annuel?: number | null;
  // Bail actif → colonnes Immeuble / Appart cliquables (retour Phil).
  immeuble_id?: number | null;
  immeuble_name?: string | null;
  logement_id?: number | null;
  logement_numero?: string | null;
};

type ImmeubleLite = {
  id: number;
  name: string;
};

type BailLite = {
  id: number;
  locataire_id: number;
  status: string;
};

type ScoreFilter = "all" | "lt70" | "70_89" | "gte90";

const SCORE_FILTERS: { value: ScoreFilter; label: string }[] = [
  { value: "all", label: "Tous" },
  { value: "lt70", label: "Score < 70" },
  { value: "70_89", label: "70–89" },
  { value: "gte90", label: "≥ 90" }
];

export default function LocatairesPage() {
  const router = useRouter();
  const { currentEntrepriseId } = useImmobilierLayout();
  const [list, setList] = useState<Locataire[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [scoreFilter, setScoreFilter] = useState<ScoreFilter>("all");
  const [showCreate, setShowCreate] = useState(false);
  const [immeubles, setImmeubles] = useState<ImmeubleLite[]>([]);
  const [immeubleFilter, setImmeubleFilter] = useState<number | "all">("all");
  // Locataires ayant un bail ACTIF dans l'immeuble choisi (null = pas chargé).
  const [immeubleLocataireIds, setImmeubleLocataireIds] =
    useState<Set<number> | null>(null);
  const [loadingImmeuble, setLoadingImmeuble] = useState(false);

  async function reload() {
    setError(null);
    try {
      const url = search.trim()
        ? `/api/v1/immobilier/locataires?search=${encodeURIComponent(search.trim())}`
        : "/api/v1/immobilier/locataires";
      const res = await authedFetch(url);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setList((await res.json()) as Locataire[]);
    } catch (err) {
      setError((err as Error).message);
    }
  }

  useEffect(() => {
    const t = setTimeout(reload, 250);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search]);

  // Liste des immeubles pour le filtre (entreprise active du layout).
  useEffect(() => {
    let cancelled = false;
    setImmeubleFilter("all");
    void (async () => {
      try {
        const url =
          currentEntrepriseId != null
            ? `/api/v1/immobilier/immeubles?entreprise_id=${currentEntrepriseId}`
            : "/api/v1/immobilier/immeubles";
        const res = await authedFetch(url);
        if (res.ok && !cancelled)
          setImmeubles((await res.json()) as ImmeubleLite[]);
      } catch {
        // Filtre non bloquant — le select reste vide.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [currentEntrepriseId]);

  // Immeuble choisi → baux de l'immeuble → Set des locataire_id (baux actifs).
  useEffect(() => {
    if (immeubleFilter === "all") {
      setImmeubleLocataireIds(null);
      setLoadingImmeuble(false);
      return;
    }
    let cancelled = false;
    setLoadingImmeuble(true);
    setImmeubleLocataireIds(null);
    void (async () => {
      try {
        const res = await authedFetch(
          `/api/v1/immobilier/immeubles/${immeubleFilter}/baux`
        );
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const baux = (await res.json()) as BailLite[];
        if (cancelled) return;
        setImmeubleLocataireIds(
          new Set(
            baux
              .filter((b) => b.status === "actif")
              .map((b) => b.locataire_id)
          )
        );
      } catch (err) {
        if (!cancelled) setError((err as Error).message);
      } finally {
        if (!cancelled) setLoadingImmeuble(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [immeubleFilter]);

  // Filtres client-side sur les rows chargées : immeuble (via baux actifs)
  // puis score de paiement. Pendant le fetch des baux (ids null), on ne
  // filtre pas encore — le loader discret indique le chargement.
  const filtered =
    list === null
      ? null
      : list.filter((l) => {
          if (
            immeubleFilter !== "all" &&
            immeubleLocataireIds !== null &&
            !immeubleLocataireIds.has(l.id)
          )
            return false;
          if (scoreFilter === "all") return true;
          if (l.paiement_score == null) return false;
          if (scoreFilter === "lt70") return l.paiement_score < 70;
          if (scoreFilter === "70_89")
            return l.paiement_score >= 70 && l.paiement_score < 90;
          return l.paiement_score >= 90;
        });

  return (
    <>
      <ImmobilierTopbar
        breadcrumbs={[
          { label: "Gestion immobilière", href: "/immobilier" },
          { label: "Locataires" }
        ]}
        rightSlot={
          <button
            type="button"
            onClick={() => setShowCreate(true)}
            className="btn-outline-accent btn-sm"
          >
            <Plus className="h-3.5 w-3.5" />
            Nouveau locataire
          </button>
        }
      />

      <div className="p-4 pb-28 lg:p-6 lg:pb-28">
        <div className="mb-4 flex flex-wrap items-center gap-2">
          <div className="relative max-w-md flex-1">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-white/40" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Recherche par nom…"
              className="input w-full pl-9"
            />
          </div>
          <select
            value={immeubleFilter === "all" ? "all" : String(immeubleFilter)}
            onChange={(e) =>
              setImmeubleFilter(
                e.target.value === "all" ? "all" : Number(e.target.value)
              )
            }
            className="input w-auto max-w-[220px] text-sm"
            aria-label="Filtrer par immeuble"
          >
            <option value="all">Tous les immeubles</option>
            {immeubles.map((imm) => (
              <option key={imm.id} value={imm.id}>
                {imm.name}
              </option>
            ))}
          </select>
          {loadingImmeuble ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin text-white/40" />
          ) : null}
          {SCORE_FILTERS.map((f) => (
            <FilterPill
              key={f.value}
              label={f.label}
              active={scoreFilter === f.value}
              onClick={() => setScoreFilter(f.value)}
            />
          ))}
          {filtered && list ? (
            <span className="text-xs text-white/50">
              {filtered.length} / {list.length}
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
          <Loading />
        ) : filtered.length === 0 ? (
          <p className="rounded-lg border border-brand-800 bg-brand-900 px-4 py-3 text-sm text-white/60">
            Aucun locataire{" "}
            {search || scoreFilter !== "all" || immeubleFilter !== "all"
              ? "correspondant"
              : "enregistré"}.
          </p>
        ) : (
          <div className="overflow-hidden rounded-2xl border border-brand-800 bg-brand-900">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-brand-800 bg-brand-950 text-[10px] uppercase tracking-wider text-white/50">
                <tr>
                  <th className="px-4 py-2.5">Nom</th>
                  <th className="px-4 py-2.5">Immeuble</th>
                  <th className="px-4 py-2.5">Appart</th>
                  <th className="px-4 py-2.5">Contact</th>
                  <th className="px-4 py-2.5">Employeur</th>
                  <th className="px-4 py-2.5 text-right">Revenu/an</th>
                  <th className="px-4 py-2.5 text-right">Score paiement</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-brand-800">
                {filtered.map((l) => (
                  <tr key={l.id} className="group hover:bg-brand-950/50">
                    <td className="px-4 py-3">
                      <Link
                        // eslint-disable-next-line @typescript-eslint/no-explicit-any
                        href={`/immobilier/locataires/${l.id}` as any}
                        className="flex items-center gap-3"
                      >
                        <div className="flex h-8 w-8 items-center justify-center rounded-full bg-accent-500/15 text-accent-500">
                          <User className="h-4 w-4" />
                        </div>
                        <span className="font-bold text-white group-hover:text-accent-500">
                          {l.full_name}
                        </span>
                      </Link>
                    </td>
                    <td className="px-4 py-3 text-xs">
                      {l.immeuble_id ? (
                        <Link
                          // eslint-disable-next-line @typescript-eslint/no-explicit-any
                          href={`/immobilier/immeubles/${l.immeuble_id}` as any}
                          className="font-medium text-accent-500 hover:underline"
                        >
                          {l.immeuble_name || `Immeuble #${l.immeuble_id}`}
                        </Link>
                      ) : (
                        <span className="text-white/40">—</span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-xs">
                      {l.logement_id ? (
                        <Link
                          // eslint-disable-next-line @typescript-eslint/no-explicit-any
                          href={`/immobilier/logements/${l.logement_id}` as any}
                          className="font-mono font-medium text-accent-500 hover:underline"
                        >
                          {l.logement_numero || `#${l.logement_id}`}
                        </Link>
                      ) : (
                        <span className="text-white/40">—</span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-xs text-white/60">
                      <div>{l.email || "—"}</div>
                      <div className="font-mono text-white/40">
                        {l.phone || "—"}
                      </div>
                    </td>
                    <td className="px-4 py-3 text-xs text-white/60">
                      {l.employeur || "—"}
                    </td>
                    <td className="px-4 py-3 text-right font-mono text-xs text-white/70">
                      {l.revenu_annuel
                        ? new Intl.NumberFormat("fr-CA", {
                            style: "currency",
                            currency: "CAD",
                            minimumFractionDigits: 2,
                            maximumFractionDigits: 2
                          }).format(l.revenu_annuel)
                        : "—"}
                    </td>
                    <td className="px-4 py-3 text-right font-mono text-xs">
                      {l.paiement_score != null ? (
                        <span
                          className={
                            l.paiement_score >= 90
                              ? "text-emerald-300"
                              : l.paiement_score >= 70
                              ? "text-amber-300"
                              : "text-rose-300"
                          }
                        >
                          {l.paiement_score}
                        </span>
                      ) : (
                        <span className="text-white/40">—</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {showCreate ? (
        <CreateLocataireModal
          onClose={() => setShowCreate(false)}
          onSaved={(createdId) => {
            setShowCreate(false);
            // Ouvrir directement le hub du locataire créé (retour Phil).
            router.push(`/immobilier/locataires/${createdId}` as any);
          }}
        />
      ) : null}
    </>
  );
}

function CreateLocataireModal({
  onClose,
  onSaved
}: {
  onClose: () => void;
  onSaved: (createdId: number) => void;
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

  async function submit(e: React.FormEvent) {
    e.preventDefault();
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
      onSaved(created.id);
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
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/70 p-4 backdrop-blur-sm">
      <div className="my-8 w-full max-w-lg rounded-2xl border border-brand-800 bg-brand-950 shadow-2xl">
        <div className="flex items-center justify-between border-b border-brand-800 px-5 py-3">
          <h2 className="text-sm font-bold uppercase tracking-wider text-accent-500">
            Nouveau locataire
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

          {err ? (
            <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
              <AlertTriangle className="mr-1.5 inline h-3.5 w-3.5" />
              {err}
            </p>
          ) : null}

          <div className="flex items-center justify-end gap-2 border-t border-brand-800 pt-4">
            <button type="button" onClick={onClose} className="btn-secondary text-sm">
              Annuler
            </button>
            <button
              type="submit"
              disabled={saving || !form.full_name.trim()}
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
      </div>
    </div>
  );
}

function Loading() {
  return (
    <p className="text-xs text-white/50">
      <Loader2 className="mr-1 inline h-3 w-3 animate-spin" /> Chargement…
    </p>
  );
}

function FilterPill({
  label,
  active,
  onClick
}: {
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`rounded-full px-3 py-1 text-xs font-semibold transition ${
        active
          ? "bg-brand-900 text-white"
          : "border border-white/10 bg-brand-950 text-white/60 hover:text-white"
      }`}
    >
      {label}
    </button>
  );
}
