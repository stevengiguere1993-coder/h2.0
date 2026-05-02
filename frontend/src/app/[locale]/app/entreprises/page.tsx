"use client";

import { useEffect, useState } from "react";
import {
  Briefcase,
  Building2,
  ExternalLink,
  Loader2,
  Plus,
  Sparkles
} from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { Link } from "@/i18n/navigation";
import { authedFetch } from "@/lib/auth";
import { useAppLayout } from "../layout";

type Entreprise = {
  id: number;
  name: string;
  neq: string | null;
  type: string;
  color_accent: string;
  description: string | null;
  monday_board_id: string | null;
  monday_board_name: string | null;
  is_active: boolean;
};

const TYPE_LABELS: Record<string, string> = {
  gestion: "Gestion",
  construction: "Construction",
  immobilier: "Immobilier",
  autre: "Autre"
};

export default function EntreprisesListPage() {
  const { onOpenSidebar } = useAppLayout();
  const [items, setItems] = useState<Entreprise[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const res = await authedFetch("/api/v1/entreprises");
      if (!res.ok) {
        if (res.status === 403) {
          throw new Error(
            "Accès refusé — ton compte n'a pas le volet Gestion d'entreprises."
          );
        }
        throw new Error(`HTTP ${res.status}`);
      }
      const data = (await res.json()) as Entreprise[];
      setItems(data);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  const active = items.filter((e) => e.is_active);
  const inactive = items.filter((e) => !e.is_active);

  return (
    <>
      <AppTopbar
        breadcrumbs={[{ label: "Gestion d'entreprises" }]}
        onOpenSidebar={onOpenSidebar}
        rightSlot={
          <button
            type="button"
            onClick={() => setShowCreate(true)}
            className="btn-accent text-sm"
          >
            <Plus className="mr-1.5 h-4 w-4" />
            Nouvelle entreprise
          </button>
        }
      />

      <div className="p-4 lg:p-6">
        <header className="flex items-start gap-3">
          <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-violet-500/15 text-violet-300">
            <Briefcase className="h-5 w-5" />
          </span>
          <div>
            <h1 className="text-2xl font-bold text-white">
              Gestion d&apos;entreprises
            </h1>
            <p className="mt-1 text-sm text-white/60">
              Vue d&apos;ensemble des entités d&apos;affaire et de leurs
              tâches.
            </p>
          </div>
        </header>

        <div className="mt-3 inline-flex items-center gap-2 rounded-full border border-amber-500/40 bg-amber-500/10 px-3 py-1 text-[11px] font-semibold text-amber-200">
          <Sparkles className="h-3 w-3" />
          En développement — itération continue
        </div>

        {error ? (
          <p className="mt-6 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">
            {error}
          </p>
        ) : null}

        {loading ? (
          <div className="flex min-h-[40vh] items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-violet-300" />
          </div>
        ) : items.length === 0 ? (
          <EmptyState onCreate={() => setShowCreate(true)} />
        ) : (
          <div className="mt-6 space-y-8">
            <EntrepriseGrid items={active} />
            {inactive.length > 0 ? (
              <details className="text-sm text-white/60">
                <summary className="cursor-pointer hover:text-white">
                  {inactive.length} entreprise
                  {inactive.length > 1 ? "s" : ""} archivée
                  {inactive.length > 1 ? "s" : ""}
                </summary>
                <div className="mt-4 opacity-60">
                  <EntrepriseGrid items={inactive} />
                </div>
              </details>
            ) : null}
          </div>
        )}
      </div>

      {showCreate ? (
        <CreateEntrepriseModal
          onClose={() => setShowCreate(false)}
          onCreated={() => {
            setShowCreate(false);
            void load();
          }}
        />
      ) : null}
    </>
  );
}

function EntrepriseGrid({ items }: { items: Entreprise[] }) {
  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {items.map((e) => (
        <Link
          key={e.id}
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          href={`/app/entreprises/${e.id}` as any}
          className="group relative flex flex-col gap-3 rounded-2xl border border-brand-800 bg-brand-900 p-5 transition hover:-translate-y-0.5 hover:border-violet-500/40 hover:shadow-lg"
        >
          <span
            className="h-1 w-12 rounded-full"
            style={{ backgroundColor: e.color_accent }}
          />
          <div className="flex items-start justify-between gap-2">
            <h3 className="text-base font-bold text-white">{e.name}</h3>
            <span className="rounded-full border border-brand-700 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-white/60">
              {TYPE_LABELS[e.type] || e.type}
            </span>
          </div>
          {e.description ? (
            <p className="line-clamp-2 text-xs text-white/60">
              {e.description}
            </p>
          ) : null}
          <div className="mt-auto flex items-center gap-2 text-[10px] text-white/40">
            {e.neq ? <span>NEQ : {e.neq}</span> : null}
            {e.monday_board_id ? (
              <span className="inline-flex items-center gap-1 text-violet-300">
                <ExternalLink className="h-2.5 w-2.5" />
                Monday
              </span>
            ) : null}
          </div>
        </Link>
      ))}
    </div>
  );
}

function EmptyState({ onCreate }: { onCreate: () => void }) {
  return (
    <div className="mx-auto mt-12 max-w-md rounded-2xl border border-dashed border-brand-800 bg-brand-900/40 p-10 text-center">
      <Building2 className="mx-auto h-10 w-10 text-violet-300" />
      <h2 className="mt-4 text-lg font-semibold text-white">
        Aucune entreprise
      </h2>
      <p className="mt-2 text-sm text-white/60">
        Crée une entreprise manuellement ou lance l&apos;import depuis
        Monday pour démarrer.
      </p>
      <button
        type="button"
        onClick={onCreate}
        className="btn-accent mt-6 inline-flex text-sm"
      >
        <Plus className="mr-1.5 h-4 w-4" />
        Nouvelle entreprise
      </button>
    </div>
  );
}

function CreateEntrepriseModal({
  onClose,
  onCreated
}: {
  onClose: () => void;
  onCreated: () => void;
}) {
  const [name, setName] = useState("");
  const [neq, setNeq] = useState("");
  const [type, setType] = useState("gestion");
  const [color, setColor] = useState("#7c3aed");
  const [desc, setDesc] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) {
      setErr("Le nom est requis.");
      return;
    }
    setBusy(true);
    setErr(null);
    try {
      const res = await authedFetch("/api/v1/entreprises", {
        method: "POST",
        body: JSON.stringify({
          name: name.trim(),
          neq: neq.trim() || null,
          type,
          color_accent: color,
          description: desc.trim() || null,
          is_active: true
        })
      });
      if (!res.ok) {
        const t = await res.text();
        throw new Error(t.slice(0, 200) || `HTTP ${res.status}`);
      }
      onCreated();
    } catch (e) {
      setErr((e as Error).message);
      setBusy(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4"
      onClick={() => (!busy ? onClose() : null)}
    >
      <form
        onSubmit={save}
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-lg rounded-2xl border border-brand-800 bg-brand-950 p-6 shadow-2xl"
      >
        <h3 className="text-lg font-bold text-white">
          Nouvelle entreprise
        </h3>

        <div className="mt-5 space-y-4">
          <div>
            <label htmlFor="e_name" className="label">
              Nom <span className="text-rose-400">*</span>
            </label>
            <input
              id="e_name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="input"
              required
              maxLength={255}
            />
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label htmlFor="e_type" className="label">Type</label>
              <select
                id="e_type"
                value={type}
                onChange={(e) => setType(e.target.value)}
                className="input"
              >
                <option value="gestion">Gestion</option>
                <option value="construction">Construction</option>
                <option value="immobilier">Immobilier</option>
                <option value="autre">Autre</option>
              </select>
            </div>
            <div>
              <label htmlFor="e_color" className="label">
                Couleur d&apos;accent
              </label>
              <div className="flex items-center gap-2">
                <input
                  id="e_color"
                  type="color"
                  value={color}
                  onChange={(e) => setColor(e.target.value)}
                  className="h-10 w-16 cursor-pointer rounded border border-brand-700 bg-brand-900"
                />
                <input
                  type="text"
                  value={color}
                  onChange={(e) => setColor(e.target.value)}
                  pattern="^#[0-9a-fA-F]{6}$"
                  className="input flex-1 font-mono text-sm"
                />
              </div>
            </div>
          </div>
          <div>
            <label htmlFor="e_neq" className="label">NEQ</label>
            <input
              id="e_neq"
              value={neq}
              onChange={(e) => setNeq(e.target.value)}
              className="input"
              maxLength={32}
              placeholder="Numéro d'entreprise du Québec"
            />
          </div>
          <div>
            <label htmlFor="e_desc" className="label">Description</label>
            <textarea
              id="e_desc"
              value={desc}
              onChange={(e) => setDesc(e.target.value)}
              rows={3}
              className="input"
            />
          </div>
        </div>

        {err ? (
          <p className="mt-3 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
            {err}
          </p>
        ) : null}

        <div className="mt-6 flex items-center justify-end gap-3">
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            className="btn-secondary text-sm"
          >
            Annuler
          </button>
          <button
            type="submit"
            disabled={busy}
            className="btn-accent text-sm disabled:opacity-60"
          >
            {busy ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Sauvegarde…
              </>
            ) : (
              "Créer"
            )}
          </button>
        </div>
      </form>
    </div>
  );
}
