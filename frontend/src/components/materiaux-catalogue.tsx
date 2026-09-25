"use client";

// Catalogue de MATÉRIAUX (retour 2026-09-25) : prix par magasin,
// meilleur prix, rabais et fin de rabais, import du fichier Excel.
// Onglet « Matériaux » du catalogue de services.

import { useEffect, useMemo, useRef, useState } from "react";
import {
  Check,
  Loader2,
  Pencil,
  Plus,
  Tag,
  Trash2,
  Upload,
  X
} from "lucide-react";

import { authedFetch } from "@/lib/auth";
import { useConfirm } from "@/components/confirm-dialog";

type Magasin = {
  id: number;
  name: string;
  website: string | null;
  color: string | null;
  is_active: boolean;
};

type Offre = {
  magasin_id: number;
  magasin_name: string;
  unit_price: number | null;
  regular_price: number | null;
  on_sale: boolean;
  sale_end: string | null;
  sale_active: boolean;
  url: string | null;
  sku: string | null;
  source: string;
  observed_at: string | null;
  note: string | null;
};

type Materiau = {
  id: number;
  name: string;
  categorie: string | null;
  unit: string | null;
  notes: string | null;
  is_active: boolean;
  offres: Offre[];
  best_price: number | null;
  best_magasin_id: number | null;
  best_magasin_name: string | null;
  best_is_archive: boolean;
};

function money(n: number | null | undefined): string {
  if (n == null) return "—";
  return `${n.toLocaleString("fr-CA", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  })} $`;
}

function fmtDate(iso: string | null): string {
  if (!iso) return "";
  return new Date(iso.length === 10 ? `${iso}T12:00:00` : iso).toLocaleDateString(
    "fr-CA",
    { day: "numeric", month: "short", year: "numeric" }
  );
}

async function readError(res: Response): Promise<string> {
  try {
    const j = (await res.json()) as { detail?: string };
    if (j.detail) return j.detail;
  } catch {
    /* ignore */
  }
  return `http_${res.status}`;
}

export function MateriauxCatalogue() {
  const confirm = useConfirm();
  const [items, setItems] = useState<Materiau[]>([]);
  const [magasins, setMagasins] = useState<Magasin[]>([]);
  const [categories, setCategories] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [cat, setCat] = useState("");
  const [magFilter, setMagFilter] = useState("");
  const [editing, setEditing] = useState<number | null>(null);
  const [priceEdit, setPriceEdit] = useState<{
    materiauId: number;
    magasinId: number;
  } | null>(null);
  const [importing, setImporting] = useState(false);
  const fileRef = useRef<HTMLInputElement | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      if (q.trim()) params.set("q", q.trim());
      if (cat) params.set("categorie", cat);
      if (magFilter) params.set("magasin_id", magFilter);
      const [mr, gr, cr] = await Promise.all([
        authedFetch(`/api/v1/materiaux?${params.toString()}`),
        authedFetch("/api/v1/magasins"),
        authedFetch("/api/v1/materiaux/categories")
      ]);
      if (!mr.ok) throw new Error(await readError(mr));
      setItems((await mr.json()) as Materiau[]);
      if (gr.ok) setMagasins((await gr.json()) as Magasin[]);
      if (cr.ok) setCategories((await cr.json()) as string[]);
    } catch (e) {
      setError(`Chargement du catalogue échoué : ${(e as Error).message}`);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    const t = setTimeout(() => {
      void load();
    }, 250);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q, cat, magFilter]);

  const activeMagasins = useMemo(
    () => magasins.filter((m) => m.is_active),
    [magasins]
  );

  function replaceItem(updated: Materiau) {
    setItems((prev) => prev.map((m) => (m.id === updated.id ? updated : m)));
  }

  async function addMateriau() {
    const name = window.prompt("Nom du matériau (ex. Gypse léger 1/2\")");
    if (!name || !name.trim()) return;
    const res = await authedFetch("/api/v1/materiaux", {
      method: "POST",
      body: JSON.stringify({ name: name.trim(), categorie: cat || null })
    });
    if (!res.ok) {
      setError(`Création échouée : ${await readError(res)}`);
      return;
    }
    const created = (await res.json()) as Materiau;
    setItems((prev) =>
      prev.some((m) => m.id === created.id)
        ? prev.map((m) => (m.id === created.id ? created : m))
        : [created, ...prev]
    );
    setEditing(created.id);
  }

  async function addMagasin() {
    const name = window.prompt("Nom du magasin (ex. BMR)");
    if (!name || !name.trim()) return;
    const res = await authedFetch("/api/v1/magasins", {
      method: "POST",
      body: JSON.stringify({ name: name.trim() })
    });
    if (!res.ok) {
      setError(`Ajout du magasin échoué : ${await readError(res)}`);
      return;
    }
    const gr = await authedFetch("/api/v1/magasins");
    if (gr.ok) setMagasins((await gr.json()) as Magasin[]);
  }

  async function removeMateriau(m: Materiau) {
    const ok = await confirm({
      title: `Retirer « ${m.name} » du catalogue ?`,
      description: "Le matériau est désactivé, ses prix restent en historique.",
      confirmLabel: "Retirer",
      destructive: true
    });
    if (!ok) return;
    const res = await authedFetch(`/api/v1/materiaux/${m.id}`, {
      method: "DELETE"
    });
    if (!res.ok) {
      setError(`Retrait échoué : ${await readError(res)}`);
      return;
    }
    setItems((prev) => prev.filter((x) => x.id !== m.id));
  }

  async function importFile(file: File) {
    setImporting(true);
    setError(null);
    setNotice(null);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const res = await authedFetch("/api/v1/materiaux/import-xlsx", {
        method: "POST",
        body: fd
      });
      if (!res.ok) throw new Error(await readError(res));
      const s = (await res.json()) as Record<string, number>;
      setNotice(
        `Import terminé : ${s.lignes} lignes lues, ${s.materiaux_crees} matériaux et ${s.magasins_crees} magasins créés, ${s.offres_creees} prix ajoutés, ${s.offres_mises_a_jour} mis à jour, ${s.offres_conservees_manuel} prix saisis à la main conservés.`
      );
      await load();
    } catch (e) {
      setError(`Import échoué : ${(e as Error).message}`);
    } finally {
      setImporting(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <input
          type="search"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Rechercher un matériau…"
          className="input w-full sm:w-64"
        />
        <select
          value={cat}
          onChange={(e) => setCat(e.target.value)}
          className="input w-auto"
        >
          <option value="">Toutes les catégories</option>
          {categories.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
        <select
          value={magFilter}
          onChange={(e) => setMagFilter(e.target.value)}
          className="input w-auto"
        >
          <option value="">Tous les magasins</option>
          {activeMagasins.map((m) => (
            <option key={m.id} value={String(m.id)}>
              {m.name}
            </option>
          ))}
        </select>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <button type="button" onClick={addMagasin} className="btn-secondary btn-sm">
            <Plus className="mr-1 h-3.5 w-3.5" /> Magasin
          </button>
          <input
            ref={fileRef}
            type="file"
            accept=".xlsx,.xlsm"
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) void importFile(f);
            }}
          />
          <button
            type="button"
            onClick={() => fileRef.current?.click()}
            disabled={importing}
            className="btn-secondary btn-sm disabled:opacity-60"
            title="Importer un classeur Excel (colonnes MATÉRIAUX / DÉTAILLANT / PRIX UNITAIRE, ou magasins en colonnes)"
          >
            {importing ? (
              <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />
            ) : (
              <Upload className="mr-1 h-3.5 w-3.5" />
            )}
            Importer Excel
          </button>
          <button type="button" onClick={addMateriau} className="btn-accent btn-sm">
            <Plus className="mr-1 h-3.5 w-3.5" /> Matériau
          </button>
        </div>
      </div>

      {error ? (
        <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-4 py-2 text-sm text-rose-300">
          {error}
        </p>
      ) : null}
      {notice ? (
        <p className="rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-4 py-2 text-sm text-emerald-300">
          {notice}
        </p>
      ) : null}

      <p className="text-xs text-white/60">
        Meilleur prix en vert. Un prix marqué « archive » vient du fichier
        historique, sans date : à vérifier avant d'acheter. Clique un
        magasin pour poser le prix du jour, le rabais et sa date de fin.
      </p>

      {loading ? (
        <div className="flex items-center justify-center py-10">
          <Loader2 className="h-5 w-5 animate-spin text-white/40" />
        </div>
      ) : items.length === 0 ? (
        <p className="rounded-xl border border-brand-800 bg-brand-900 px-4 py-8 text-center text-sm text-white/50">
          Aucun matériau. Importe ton fichier Excel ou ajoute un matériau.
        </p>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-brand-800 bg-brand-900">
          <table className="w-full text-sm">
            <thead className="border-b border-brand-800 text-xs uppercase tracking-wider text-white/50">
              <tr>
                <th className="px-3 py-2 text-left">Matériau</th>
                <th className="px-3 py-2 text-left">Meilleur prix</th>
                <th className="px-3 py-2 text-left">Prix par magasin</th>
                <th className="px-3 py-2 text-right"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-brand-800">
              {items.map((m) => (
                <MateriauRow
                  key={m.id}
                  m={m}
                  magasins={activeMagasins}
                  editing={editing === m.id}
                  onEdit={() => setEditing(editing === m.id ? null : m.id)}
                  onSaved={(u) => {
                    replaceItem(u);
                    setEditing(null);
                  }}
                  onRemove={() => removeMateriau(m)}
                  priceEdit={
                    priceEdit && priceEdit.materiauId === m.id
                      ? priceEdit.magasinId
                      : null
                  }
                  onPriceEdit={(magasinId) =>
                    setPriceEdit(
                      magasinId == null ? null : { materiauId: m.id, magasinId }
                    )
                  }
                  onError={setError}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function MateriauRow({
  m,
  magasins,
  editing,
  onEdit,
  onSaved,
  onRemove,
  priceEdit,
  onPriceEdit,
  onError
}: {
  m: Materiau;
  magasins: Magasin[];
  editing: boolean;
  onEdit: () => void;
  onSaved: (u: Materiau) => void;
  onRemove: () => void;
  priceEdit: number | null;
  onPriceEdit: (magasinId: number | null) => void;
  onError: (msg: string) => void;
}) {
  const [name, setName] = useState(m.name);
  const [categorie, setCategorie] = useState(m.categorie || "");
  const [unit, setUnit] = useState(m.unit || "");
  const [saving, setSaving] = useState(false);

  async function save() {
    setSaving(true);
    try {
      const res = await authedFetch(`/api/v1/materiaux/${m.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          name: name.trim() || m.name,
          categorie: categorie.trim() || null,
          unit: unit.trim() || null
        })
      });
      if (!res.ok) throw new Error(await readError(res));
      onSaved((await res.json()) as Materiau);
    } catch (e) {
      onError(`Enregistrement échoué : ${(e as Error).message}`);
    } finally {
      setSaving(false);
    }
  }

  const offresByMag = new Map(m.offres.map((o) => [o.magasin_id, o]));

  return (
    <tr className="align-top">
      <td className="px-3 py-2">
        {editing ? (
          <div className="flex flex-col gap-1">
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="input"
              placeholder="Nom"
            />
            <div className="flex gap-1">
              <input
                value={categorie}
                onChange={(e) => setCategorie(e.target.value)}
                className="input"
                placeholder="Catégorie"
              />
              <input
                value={unit}
                onChange={(e) => setUnit(e.target.value)}
                className="input w-24"
                placeholder="Unité"
              />
            </div>
            <div className="flex gap-1">
              <button
                type="button"
                onClick={save}
                disabled={saving}
                className="btn-accent btn-sm"
              >
                {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />}
                Enregistrer
              </button>
              <button type="button" onClick={onEdit} className="btn-secondary btn-sm">
                Annuler
              </button>
            </div>
          </div>
        ) : (
          <>
            <p className="font-semibold text-white">{m.name}</p>
            <p className="text-xs text-white/50">
              {[m.categorie, m.unit ? `/ ${m.unit}` : null]
                .filter(Boolean)
                .join(" ")}
            </p>
          </>
        )}
      </td>
      <td className="px-3 py-2 whitespace-nowrap">
        {m.best_price != null ? (
          <>
            <p className="font-mono font-semibold text-emerald-300">
              {money(m.best_price)}
            </p>
            <p className="text-xs text-white/60">
              {m.best_magasin_name}
              {m.best_is_archive ? (
                <span className="ml-1 rounded bg-amber-500/15 px-1 text-[10px] font-semibold text-amber-300">
                  archive
                </span>
              ) : null}
            </p>
          </>
        ) : (
          <span className="text-xs text-white/40">aucun prix</span>
        )}
      </td>
      <td className="px-3 py-2">
        <div className="flex flex-wrap gap-1.5">
          {magasins.map((g) => {
            const o = offresByMag.get(g.id);
            const isBest = m.best_magasin_id === g.id && m.best_price != null;
            const open = priceEdit === g.id;
            return (
              <div key={g.id} className="relative">
                <button
                  type="button"
                  onClick={() => onPriceEdit(open ? null : g.id)}
                  title={
                    o
                      ? `${g.name} · ${o.source}${o.observed_at ? ` · vu le ${fmtDate(o.observed_at)}` : " · sans date"}${o.note ? ` · ${o.note}` : ""}`
                      : `${g.name} : poser un prix`
                  }
                  className={`rounded-md border px-2 py-1 text-left text-xs transition ${
                    isBest
                      ? "border-emerald-500/60 bg-emerald-500/10 text-emerald-200"
                      : o && o.unit_price != null
                        ? "border-brand-700 bg-brand-950 text-white/85 hover:border-accent-500"
                        : "border-dashed border-brand-700 text-white/40 hover:border-accent-500 hover:text-white/70"
                  }`}
                >
                  <span className="font-semibold">{g.name}</span>{" "}
                  {o && o.unit_price != null ? (
                    <span className="font-mono">{money(o.unit_price)}</span>
                  ) : (
                    <span>—</span>
                  )}
                  {o?.sale_active ? (
                    <span className="ml-1 inline-flex items-center gap-0.5 rounded bg-rose-500/20 px-1 text-[10px] font-semibold text-rose-300">
                      <Tag className="h-2.5 w-2.5" />
                      rabais{o.sale_end ? ` → ${fmtDate(o.sale_end)}` : ""}
                    </span>
                  ) : null}
                  {o && o.source === "import" && !o.observed_at ? (
                    <span className="ml-1 text-[10px] text-amber-300">archive</span>
                  ) : null}
                </button>
                {open ? (
                  <OffreEditor
                    materiauId={m.id}
                    magasin={g}
                    offre={o || null}
                    onClose={() => onPriceEdit(null)}
                    onSaved={(u) => {
                      onSaved(u);
                      onPriceEdit(null);
                    }}
                    onError={onError}
                  />
                ) : null}
              </div>
            );
          })}
        </div>
      </td>
      <td className="px-3 py-2 text-right whitespace-nowrap">
        <button
          type="button"
          onClick={onEdit}
          className="rounded p-1 text-white/50 hover:text-white"
          title="Modifier"
        >
          <Pencil className="h-4 w-4" />
        </button>
        <button
          type="button"
          onClick={onRemove}
          className="rounded p-1 text-white/50 hover:text-rose-300"
          title="Retirer du catalogue"
        >
          <Trash2 className="h-4 w-4" />
        </button>
      </td>
    </tr>
  );
}

function OffreEditor({
  materiauId,
  magasin,
  offre,
  onClose,
  onSaved,
  onError
}: {
  materiauId: number;
  magasin: Magasin;
  offre: Offre | null;
  onClose: () => void;
  onSaved: (u: Materiau) => void;
  onError: (msg: string) => void;
}) {
  const [price, setPrice] = useState(
    offre?.unit_price != null ? String(offre.unit_price) : ""
  );
  const [regular, setRegular] = useState(
    offre?.regular_price != null ? String(offre.regular_price) : ""
  );
  const [onSale, setOnSale] = useState(Boolean(offre?.on_sale));
  const [saleEnd, setSaleEnd] = useState(offre?.sale_end || "");
  const [url, setUrl] = useState(offre?.url || "");
  const [note, setNote] = useState(offre?.note || "");
  const [busy, setBusy] = useState(false);

  async function save() {
    setBusy(true);
    try {
      const res = await authedFetch(
        `/api/v1/materiaux/${materiauId}/offres/${magasin.id}`,
        {
          method: "PUT",
          body: JSON.stringify({
            unit_price: price.trim() === "" ? null : Number(price),
            regular_price: regular.trim() === "" ? null : Number(regular),
            on_sale: onSale,
            sale_end: onSale && saleEnd ? saleEnd : null,
            url: url.trim() || null,
            note: note.trim() || null
          })
        }
      );
      if (!res.ok) throw new Error(await readError(res));
      onSaved((await res.json()) as Materiau);
    } catch (e) {
      onError(`Prix non enregistré : ${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    setBusy(true);
    try {
      const res = await authedFetch(
        `/api/v1/materiaux/${materiauId}/offres/${magasin.id}`,
        { method: "DELETE" }
      );
      if (!res.ok) throw new Error(await readError(res));
      onSaved((await res.json()) as Materiau);
    } catch (e) {
      onError(`Suppression échouée : ${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="absolute left-0 top-full z-20 mt-1 w-72 rounded-lg border border-brand-700 bg-brand-900 p-3 shadow-xl">
      <div className="mb-2 flex items-center justify-between">
        <p className="text-sm font-semibold text-white">{magasin.name}</p>
        <button type="button" onClick={onClose} className="text-white/50 hover:text-white">
          <X className="h-4 w-4" />
        </button>
      </div>
      <div className="grid grid-cols-2 gap-2 text-xs text-white/70">
        <label>
          Prix du jour ($)
          <input
            type="number"
            step="0.01"
            min="0"
            value={price}
            onChange={(e) => setPrice(e.target.value)}
            className="input mt-1"
            autoFocus
          />
        </label>
        <label>
          Prix régulier ($)
          <input
            type="number"
            step="0.01"
            min="0"
            value={regular}
            onChange={(e) => setRegular(e.target.value)}
            className="input mt-1"
          />
        </label>
        <label className="col-span-2 flex items-center gap-2 text-white/80">
          <input
            type="checkbox"
            checked={onSale}
            onChange={(e) => setOnSale(e.target.checked)}
          />
          En rabais
        </label>
        {onSale ? (
          <label className="col-span-2">
            Fin du rabais
            <input
              type="date"
              value={saleEnd}
              onChange={(e) => setSaleEnd(e.target.value)}
              className="input mt-1"
            />
          </label>
        ) : null}
        <label className="col-span-2">
          Lien produit
          <input
            type="url"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            className="input mt-1"
            placeholder="https://…"
          />
        </label>
        <label className="col-span-2">
          Note
          <input
            value={note}
            onChange={(e) => setNote(e.target.value)}
            className="input mt-1"
          />
        </label>
      </div>
      {offre?.observed_at ? (
        <p className="mt-2 text-[11px] text-white/50">
          Dernière vérification : {fmtDate(offre.observed_at)} ({offre.source})
        </p>
      ) : offre ? (
        <p className="mt-2 text-[11px] text-amber-300">
          Prix d'archive sans date — à vérifier.
        </p>
      ) : null}
      <div className="mt-3 flex items-center justify-between">
        {offre ? (
          <button
            type="button"
            onClick={remove}
            disabled={busy}
            className="text-xs text-rose-300 hover:underline"
          >
            Retirer ce magasin
          </button>
        ) : (
          <span />
        )}
        <button
          type="button"
          onClick={save}
          disabled={busy}
          className="btn-accent btn-sm"
        >
          {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />}
          Enregistrer
        </button>
      </div>
    </div>
  );
}
