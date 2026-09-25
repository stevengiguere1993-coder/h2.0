"use client";

// Catalogue de MATÉRIAUX (retour 2026-09-25) : tableau comparatif à
// colonnes fixes (quincailleries principales : Home Depot, Canac, Rona,
// BMR, Patrick Morin), autres magasins repliés, matériaux groupés par
// catégorie, prix du jour relevés automatiquement depuis les liens
// produit, rabais et date de fin, import du fichier Excel.

import { useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  Check,
  ChevronDown,
  ChevronRight,
  Loader2,
  Pencil,
  Plus,
  RefreshCw,
  Settings2,
  Tag,
  Trash2,
  Upload,
  Wand2,
  X
} from "lucide-react";

import { authedFetch } from "@/lib/auth";
import { useConfirm } from "@/components/confirm-dialog";
import { Link } from "@/i18n/navigation";

type Magasin = {
  id: number;
  name: string;
  website: string | null;
  color: string | null;
  is_active: boolean;
  is_principal: boolean;
  position: number;
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
  fetch_checked_at?: string | null;
  fetch_error?: string | null;
  page_title?: string | null;
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

type RabaisListe = {
  ligne_id: number;
  project_id: number;
  project_name: string;
  materiau_name: string;
  quantity: number;
  unit: string | null;
  magasin_name: string;
  price: number;
  regular_price: number | null;
  sale_end: string | null;
  economie: number;
  url: string | null;
};

type ReleveInfo = {
  ok: boolean;
  price: number | null;
  regular_price: number | null;
  on_sale: boolean;
  sale_end: string | null;
  changed: boolean;
  method: string;
  error: string | null;
};

const SANS_CATEGORIE = "Sans catégorie";

function money(n: number | null | undefined): string {
  if (n == null) return "—";
  return `${n.toLocaleString("fr-CA", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  })} $`;
}

function fmtDate(iso: string | null | undefined): string {
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
  const [editing, setEditing] = useState<number | null>(null);
  const [priceEdit, setPriceEdit] = useState<{
    materiauId: number;
    magasinId: number;
  } | null>(null);
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const [importing, setImporting] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [classifying, setClassifying] = useState(false);
  const [storesOpen, setStoresOpen] = useState(false);
  const [releveEtat, setReleveEtat] = useState<{
    en_cours: boolean;
    termine_a: string | null;
    stats: Record<string, unknown> | null;
  } | null>(null);
  const fileRef = useRef<HTMLInputElement | null>(null);

  async function loadMagasins() {
    const gr = await authedFetch("/api/v1/magasins");
    if (gr.ok) setMagasins((await gr.json()) as Magasin[]);
  }

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      if (q.trim()) params.set("q", q.trim());
      if (cat) params.set("categorie", cat);
      const [mr, cr] = await Promise.all([
        authedFetch(`/api/v1/materiaux?${params.toString()}`),
        authedFetch("/api/v1/materiaux/categories")
      ]);
      if (!mr.ok) throw new Error(await readError(mr));
      setItems((await mr.json()) as Materiau[]);
      if (cr.ok) setCategories((await cr.json()) as string[]);
      await loadMagasins();
      void loadReleveEtat();
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
  }, [q, cat]);

  async function loadReleveEtat() {
    try {
      const r = await authedFetch("/api/v1/materiaux/prix/etat");
      if (r.ok) {
        const e = (await r.json()) as {
          en_cours: boolean;
          termine_a: string | null;
          stats: Record<string, unknown> | null;
        };
        setReleveEtat(e);
        return e;
      }
    } catch {
      /* ignore */
    }
    return null;
  }

  const principaux = useMemo(
    () =>
      magasins
        .filter((m) => m.is_active && m.is_principal)
        .sort((a, b) => a.position - b.position || a.name.localeCompare(b.name)),
    [magasins]
  );
  const principauxIds = useMemo(
    () => new Set(principaux.map((m) => m.id)),
    [principaux]
  );

  // Groupes par catégorie, dans l'ordre des catégories standard.
  const groups = useMemo(() => {
    const order = new Map<string, number>();
    categories.forEach((c, i) => order.set(c, i));
    const map = new Map<string, Materiau[]>();
    for (const m of items) {
      const key = m.categorie || SANS_CATEGORIE;
      const arr = map.get(key) || [];
      arr.push(m);
      map.set(key, arr);
    }
    return Array.from(map.entries()).sort(([a], [b]) => {
      if (a === SANS_CATEGORIE) return 1;
      if (b === SANS_CATEGORIE) return -1;
      const ia = order.has(a) ? (order.get(a) as number) : 999;
      const ib = order.has(b) ? (order.get(b) as number) : 999;
      return ia - ib || a.localeCompare(b);
    });
  }, [items, categories]);

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

  async function classifyAuto() {
    setClassifying(true);
    setError(null);
    setNotice(null);
    try {
      const res = await authedFetch("/api/v1/materiaux/categoriser-auto", {
        method: "POST"
      });
      if (!res.ok) throw new Error(await readError(res));
      const s = (await res.json()) as { examines: number; classes: number; sans_categorie: number };
      setNotice(
        `Classement automatique : ${s.classes} matériaux classés, ${s.sans_categorie} restent sans catégorie (à classer à la main).`
      );
      await load();
    } catch (e) {
      setError(`Classement échoué : ${(e as Error).message}`);
    } finally {
      setClassifying(false);
    }
  }

  async function refreshAllPrices() {
    if (refreshing) return;
    setRefreshing(true);
    setError(null);
    setNotice(null);
    try {
      const res = await authedFetch("/api/v1/materiaux/prix/relever-tout", {
        method: "POST",
        body: JSON.stringify({})
      });
      if (!res.ok) throw new Error(await readError(res));
      setNotice("Relevé des prix lancé : un magasin à la fois, ça peut prendre quelques minutes.");
      for (let i = 0; i < 120; i += 1) {
        await new Promise((r) => setTimeout(r, 5000));
        const e = await loadReleveEtat();
        if (e && !e.en_cours) {
          const st = (e.stats || {}) as Record<string, number | string>;
          setNotice(
            st.error
              ? `Relevé terminé avec une erreur : ${st.error}`
              : `Relevé terminé : ${st.offres ?? 0} offres avec lien, ${st.ok ?? 0} prix lus, ${st.changes ?? 0} changements, ${st.rabais ?? 0} en rabais, ${st.echecs ?? 0} échecs.`
          );
          await load();
          break;
        }
      }
    } catch (e) {
      setError(`Relevé non lancé : ${(e as Error).message}`);
    } finally {
      setRefreshing(false);
    }
  }

  function toggleGroup(key: string) {
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
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
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => setStoresOpen(true)}
            className="btn-secondary btn-sm"
            title="Choisir les magasins affichés en colonnes"
          >
            <Settings2 className="mr-1 h-3.5 w-3.5" /> Magasins
          </button>
          <button
            type="button"
            onClick={classifyAuto}
            disabled={classifying}
            className="btn-secondary btn-sm disabled:opacity-60"
            title="Classer par mots-clés les matériaux sans catégorie (bois, plomberie, électricité…)"
          >
            {classifying ? (
              <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />
            ) : (
              <Wand2 className="mr-1 h-3.5 w-3.5" />
            )}
            Classer
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
          <button
            type="button"
            onClick={refreshAllPrices}
            disabled={refreshing}
            className="btn-secondary btn-sm disabled:opacity-60"
            title="Relever aujourd'hui les prix de toutes les offres qui ont un lien produit"
          >
            {refreshing ? (
              <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />
            ) : (
              <RefreshCw className="mr-1 h-3.5 w-3.5" />
            )}
            Actualiser les prix
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
        Meilleur prix en vert. « archive » = prix du fichier historique,
        sans date, à vérifier avant d'acheter. Clique une case pour poser le
        prix du jour, le rabais et sa date de fin, ou coller le lien de la
        page produit : le prix est alors relevé chaque jour (prix régulier,
        rabais et date de fin compris).
        {releveEtat?.termine_a ? (
          <span className="ml-1 text-white/45">
            Dernier relevé automatique : {fmtDate(releveEtat.termine_a)}.
          </span>
        ) : null}
      </p>

      <RabaisListesPanel refreshKey={items} />

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
          <table className="w-full min-w-[900px] text-sm">
            <thead className="border-b border-brand-800 text-xs uppercase tracking-wider text-white/50">
              <tr>
                <th className="px-3 py-2 text-left">Matériau</th>
                {principaux.map((g) => (
                  <th key={g.id} className="px-2 py-2 text-center whitespace-nowrap">
                    {g.name}
                  </th>
                ))}
                <th className="px-2 py-2 text-left">Autres</th>
                <th className="px-2 py-2"></th>
              </tr>
            </thead>
            <tbody>
              {groups.map(([groupName, list]) => {
                const isCollapsed = collapsed.has(groupName);
                return (
                  <GroupRows
                    key={groupName}
                    name={groupName}
                    list={list}
                    collapsed={isCollapsed}
                    onToggle={() => toggleGroup(groupName)}
                    colSpan={principaux.length + 3}
                    principaux={principaux}
                    principauxIds={principauxIds}
                    magasins={magasins}
                    editing={editing}
                    onEdit={(id) => setEditing(editing === id ? null : id)}
                    onSaved={(u) => {
                      replaceItem(u);
                      setEditing(null);
                    }}
                    onRemove={removeMateriau}
                    priceEdit={priceEdit}
                    onPriceEdit={setPriceEdit}
                    onError={setError}
                    categories={categories}
                  />
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {storesOpen ? (
        <StoresPanel
          magasins={magasins}
          onClose={() => setStoresOpen(false)}
          onChanged={loadMagasins}
          onError={setError}
        />
      ) : null}
    </div>
  );
}

// Rabais du jour sur les matériaux encore à acheter des chantiers ouverts
// (ceux que l'alerte quotidienne signale aux gestionnaires).
function RabaisListesPanel({ refreshKey }: { refreshKey: unknown }) {
  const [rows, setRows] = useState<RabaisListe[]>([]);
  const [open, setOpen] = useState(true);
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      const res = await authedFetch("/api/v1/materiaux/rabais");
      if (res.ok && !cancelled) setRows((await res.json()) as RabaisListe[]);
    })();
    return () => {
      cancelled = true;
    };
  }, [refreshKey]);
  if (rows.length === 0) return null;
  const total = rows.reduce((a, r) => a + r.economie, 0);
  return (
    <div className="rounded-xl border border-rose-500/40 bg-rose-500/10">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 px-4 py-2 text-left text-sm font-semibold text-rose-300"
      >
        {open ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
        <Tag className="h-4 w-4" />
        {rows.length} rabais aujourd&apos;hui sur les listes d&apos;achats des chantiers
        {total > 0 ? ` — économie possible ≈ ${money(total)}` : ""}
      </button>
      {open ? (
        <ul className="divide-y divide-rose-500/20 border-t border-rose-500/20 text-sm">
          {rows.map((r) => (
            <li key={r.ligne_id} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-1.5">
              <Link
                href={`/app/projets/${r.project_id}#materiaux` as any}
                className="font-medium text-white hover:underline"
              >
                {r.project_name}
              </Link>
              <span className="text-white/85">
                {r.materiau_name} × {r.quantity}
                {r.unit ? ` ${r.unit}` : ""}
              </span>
              <span className="font-mono font-semibold text-rose-300">
                {money(r.price)}
                {r.regular_price != null ? (
                  <span className="ml-1 font-normal text-white/60 line-through">{money(r.regular_price)}</span>
                ) : null}
              </span>
              <span className="text-white/70">
                chez {r.magasin_name}
                {r.sale_end ? ` jusqu'au ${fmtDate(r.sale_end)}` : ""}
              </span>
              {r.economie > 0 ? (
                <span className="text-emerald-300">économie {money(r.economie)}</span>
              ) : null}
              {r.url ? (
                <a href={r.url} target="_blank" rel="noreferrer" className="text-sky-300 hover:underline">
                  page produit
                </a>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

function GroupRows({
  name,
  list,
  collapsed,
  onToggle,
  colSpan,
  principaux,
  principauxIds,
  magasins,
  editing,
  onEdit,
  onSaved,
  onRemove,
  priceEdit,
  onPriceEdit,
  onError,
  categories
}: {
  name: string;
  list: Materiau[];
  collapsed: boolean;
  onToggle: () => void;
  colSpan: number;
  principaux: Magasin[];
  principauxIds: Set<number>;
  magasins: Magasin[];
  editing: number | null;
  onEdit: (id: number) => void;
  onSaved: (u: Materiau) => void;
  onRemove: (m: Materiau) => void;
  priceEdit: { materiauId: number; magasinId: number } | null;
  onPriceEdit: (v: { materiauId: number; magasinId: number } | null) => void;
  onError: (msg: string) => void;
  categories: string[];
}) {
  return (
    <>
      <tr className="border-t border-brand-800 bg-brand-950/40">
        <td colSpan={colSpan} className="px-3 py-1.5">
          <button
            type="button"
            onClick={onToggle}
            className="flex items-center gap-1 text-xs font-semibold uppercase tracking-wider text-accent-500"
          >
            {collapsed ? (
              <ChevronRight className="h-3.5 w-3.5" />
            ) : (
              <ChevronDown className="h-3.5 w-3.5" />
            )}
            {name}
            <span className="ml-1 font-normal normal-case tracking-normal text-white/40">
              ({list.length})
            </span>
          </button>
        </td>
      </tr>
      {collapsed
        ? null
        : list.map((m) => (
            <MateriauRow
              key={m.id}
              m={m}
              principaux={principaux}
              principauxIds={principauxIds}
              magasins={magasins}
              editing={editing === m.id}
              onEdit={() => onEdit(m.id)}
              onSaved={onSaved}
              onRemove={() => onRemove(m)}
              priceEdit={
                priceEdit && priceEdit.materiauId === m.id ? priceEdit.magasinId : null
              }
              onPriceEdit={(magasinId) =>
                onPriceEdit(magasinId == null ? null : { materiauId: m.id, magasinId })
              }
              onError={onError}
              categories={categories}
            />
          ))}
    </>
  );
}

function PriceCell({
  m,
  g,
  o,
  open,
  onOpen,
  onSaved,
  onError
}: {
  m: Materiau;
  g: Magasin;
  o: Offre | undefined;
  open: boolean;
  onOpen: (open: boolean) => void;
  onSaved: (u: Materiau) => void;
  onError: (msg: string) => void;
}) {
  const isBest = m.best_magasin_id === g.id && m.best_price != null;
  const has = Boolean(o && o.unit_price != null);
  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => onOpen(!open)}
        title={
          o
            ? `${g.name} · ${o.source}${o.observed_at ? ` · vu le ${fmtDate(o.observed_at)}` : " · sans date"}${o.fetch_error ? ` · relevé échoué : ${o.fetch_error}` : ""}${o.note ? ` · ${o.note}` : ""}`
            : `${g.name} : poser un prix ou un lien`
        }
        className={`w-full rounded-md border px-2 py-1 text-center text-xs transition ${
          isBest
            ? "border-emerald-500/60 bg-emerald-500/10 text-emerald-200"
            : has
              ? "border-brand-700 bg-brand-950 text-white/85 hover:border-accent-500"
              : "border-dashed border-brand-800 text-white/30 hover:border-accent-500 hover:text-white/70"
        }`}
      >
        {has ? (
          <span className="font-mono font-semibold">{money(o!.unit_price)}</span>
        ) : o?.url ? (
          <span className="text-[10px]">lien posé</span>
        ) : (
          <span>—</span>
        )}
        {o?.sale_active ? (
          <span className="mt-0.5 block text-[10px] font-semibold text-rose-300">
            <Tag className="mr-0.5 inline h-2.5 w-2.5" />
            {o.regular_price != null ? `rég. ${money(o.regular_price)}` : "rabais"}
            {o.sale_end ? ` → ${fmtDate(o.sale_end)}` : ""}
          </span>
        ) : null}
        {o && has && o.source === "import" && !o.observed_at ? (
          <span className="block text-[10px] text-amber-300">archive</span>
        ) : null}
        {o?.fetch_error ? (
          <AlertTriangle className="ml-1 inline h-3 w-3 text-amber-300" aria-label={o.fetch_error} />
        ) : null}
      </button>
      {open ? (
        <OffreEditor
          materiauId={m.id}
          magasin={g}
          offre={o || null}
          onClose={() => onOpen(false)}
          onSaved={(u) => {
            onSaved(u);
            onOpen(false);
          }}
          onError={onError}
        />
      ) : null}
    </div>
  );
}

function MateriauRow({
  m,
  principaux,
  principauxIds,
  magasins,
  editing,
  onEdit,
  onSaved,
  onRemove,
  priceEdit,
  onPriceEdit,
  onError,
  categories
}: {
  m: Materiau;
  principaux: Magasin[];
  principauxIds: Set<number>;
  magasins: Magasin[];
  editing: boolean;
  onEdit: () => void;
  onSaved: (u: Materiau) => void;
  onRemove: () => void;
  priceEdit: number | null;
  onPriceEdit: (magasinId: number | null) => void;
  onError: (msg: string) => void;
  categories: string[];
}) {
  const [name, setName] = useState(m.name);
  const [categorie, setCategorie] = useState(m.categorie || "");
  const [unit, setUnit] = useState(m.unit || "");
  const [saving, setSaving] = useState(false);
  const [othersOpen, setOthersOpen] = useState(false);

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
  const autres = m.offres.filter((o) => !principauxIds.has(o.magasin_id));
  const autresMagasins = magasins.filter(
    (g) => g.is_active && !principauxIds.has(g.id)
  );

  return (
    <tr className="border-t border-brand-800/60 align-top hover:bg-brand-950/30">
      <td className="px-3 py-1.5">
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
                list={`cats-${m.id}`}
                value={categorie}
                onChange={(e) => setCategorie(e.target.value)}
                className="input"
                placeholder="Catégorie"
              />
              <datalist id={`cats-${m.id}`}>
                {categories.map((c) => (
                  <option key={c} value={c} />
                ))}
              </datalist>
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
                {saving ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Check className="h-3.5 w-3.5" />
                )}
                Enregistrer
              </button>
              <button type="button" onClick={onEdit} className="btn-secondary btn-sm">
                Annuler
              </button>
            </div>
          </div>
        ) : (
          <>
            <p className="font-medium text-white">{m.name}</p>
            {m.unit ? <p className="text-[11px] text-white/45">/ {m.unit}</p> : null}
          </>
        )}
      </td>
      {principaux.map((g) => (
        <td key={g.id} className="px-1.5 py-1.5 align-top">
          <PriceCell
            m={m}
            g={g}
            o={offresByMag.get(g.id)}
            open={priceEdit === g.id}
            onOpen={(open) => onPriceEdit(open ? g.id : null)}
            onSaved={onSaved}
            onError={onError}
          />
        </td>
      ))}
      <td className="px-2 py-1.5 align-top">
        {autres.length > 0 || othersOpen ? (
          <div className="flex flex-wrap gap-1">
            {(othersOpen ? autresMagasins : autresMagasins.filter((g) => offresByMag.has(g.id))).map(
              (g) => (
                <div key={g.id} className="min-w-[90px]">
                  <p className="text-[10px] text-white/50">{g.name}</p>
                  <PriceCell
                    m={m}
                    g={g}
                    o={offresByMag.get(g.id)}
                    open={priceEdit === g.id}
                    onOpen={(open) => onPriceEdit(open ? g.id : null)}
                    onSaved={onSaved}
                    onError={onError}
                  />
                </div>
              )
            )}
            <button
              type="button"
              onClick={() => setOthersOpen((v) => !v)}
              className="self-end text-[10px] text-white/40 hover:text-white/70"
            >
              {othersOpen ? "réduire" : "+ magasin"}
            </button>
          </div>
        ) : (
          <button
            type="button"
            onClick={() => setOthersOpen(true)}
            className="text-[10px] text-white/30 hover:text-white/70"
            title="Poser un prix chez un autre magasin"
          >
            + autre
          </button>
        )}
      </td>
      <td className="px-1 py-1.5 text-right whitespace-nowrap">
        <button
          type="button"
          onClick={onEdit}
          className="rounded p-1 text-white/50 hover:text-white"
          title="Modifier (nom, catégorie, unité)"
        >
          <Pencil className="h-3.5 w-3.5" />
        </button>
        <button
          type="button"
          onClick={onRemove}
          className="rounded p-1 text-white/50 hover:text-rose-300"
          title="Retirer du catalogue"
        >
          <Trash2 className="h-3.5 w-3.5" />
        </button>
      </td>
    </tr>
  );
}

function StoresPanel({
  magasins,
  onClose,
  onChanged,
  onError
}: {
  magasins: Magasin[];
  onClose: () => void;
  onChanged: () => Promise<void>;
  onError: (msg: string) => void;
}) {
  const [busy, setBusy] = useState<number | "new" | null>(null);
  const [newName, setNewName] = useState("");

  async function patch(id: number, body: Partial<Magasin>) {
    setBusy(id);
    try {
      const res = await authedFetch(`/api/v1/magasins/${id}`, {
        method: "PATCH",
        body: JSON.stringify(body)
      });
      if (!res.ok) throw new Error(await readError(res));
      await onChanged();
    } catch (e) {
      onError(`Magasin non modifié : ${(e as Error).message}`);
    } finally {
      setBusy(null);
    }
  }

  async function add() {
    if (!newName.trim()) return;
    setBusy("new");
    try {
      const res = await authedFetch("/api/v1/magasins", {
        method: "POST",
        body: JSON.stringify({ name: newName.trim() })
      });
      if (!res.ok) throw new Error(await readError(res));
      setNewName("");
      await onChanged();
    } catch (e) {
      onError(`Ajout du magasin échoué : ${(e as Error).message}`);
    } finally {
      setBusy(null);
    }
  }

  const sorted = [...magasins].sort(
    (a, b) =>
      Number(b.is_principal) - Number(a.is_principal) ||
      a.position - b.position ||
      a.name.localeCompare(b.name)
  );

  return (
    <div className="fixed inset-0 z-40 flex items-start justify-center bg-black/60 p-4 sm:items-center">
      <div className="w-full max-w-lg rounded-xl border border-brand-700 bg-brand-900 p-4 shadow-2xl">
        <div className="mb-3 flex items-center justify-between">
          <h3 className="text-sm font-semibold text-white">Magasins</h3>
          <button type="button" onClick={onClose} className="text-white/50 hover:text-white">
            <X className="h-4 w-4" />
          </button>
        </div>
        <p className="mb-3 text-xs text-white/60">
          Coche « colonne » pour les quincailleries à comparer côte à côte
          (ordre par le numéro). Les autres restent disponibles dans la
          colonne « Autres ». Décoche « actif » pour masquer un magasin.
        </p>
        <ul className="max-h-[50vh] divide-y divide-brand-800 overflow-y-auto text-sm">
          {sorted.map((g) => (
            <li key={g.id} className="flex items-center gap-3 py-1.5">
              <span className={`flex-1 ${g.is_active ? "text-white" : "text-white/40 line-through"}`}>
                {g.name}
              </span>
              <label className="flex items-center gap-1 text-xs text-white/70">
                <input
                  type="checkbox"
                  checked={g.is_principal}
                  disabled={busy === g.id}
                  onChange={(e) => patch(g.id, { is_principal: e.target.checked })}
                />
                colonne
              </label>
              <input
                type="number"
                min={0}
                max={99}
                value={g.position}
                disabled={busy === g.id || !g.is_principal}
                onChange={(e) => patch(g.id, { position: Number(e.target.value) || 0 })}
                className="input w-14 px-1 py-0.5 text-center text-xs"
                title="Ordre de la colonne"
              />
              <label className="flex items-center gap-1 text-xs text-white/70">
                <input
                  type="checkbox"
                  checked={g.is_active}
                  disabled={busy === g.id}
                  onChange={(e) => patch(g.id, { is_active: e.target.checked })}
                />
                actif
              </label>
            </li>
          ))}
        </ul>
        <div className="mt-3 flex gap-2">
          <input
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            placeholder="Nouveau magasin"
            className="input"
          />
          <button
            type="button"
            onClick={add}
            disabled={busy === "new" || !newName.trim()}
            className="btn-accent btn-sm whitespace-nowrap disabled:opacity-60"
          >
            <Plus className="h-3.5 w-3.5" /> Ajouter
          </button>
        </div>
      </div>
    </div>
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
  const [releve, setReleve] = useState<ReleveInfo | null>(null);

  function payload() {
    return {
      unit_price: price.trim() === "" ? null : Number(price),
      regular_price: regular.trim() === "" ? null : Number(regular),
      on_sale: onSale,
      sale_end: onSale && saleEnd ? saleEnd : null,
      url: url.trim() || null,
      note: note.trim() || null
    };
  }

  async function save() {
    setBusy(true);
    try {
      const res = await authedFetch(
        `/api/v1/materiaux/${materiauId}/offres/${magasin.id}`,
        { method: "PUT", body: JSON.stringify(payload()) }
      );
      if (!res.ok) throw new Error(await readError(res));
      onSaved((await res.json()) as Materiau);
    } catch (e) {
      onError(`Prix non enregistré : ${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  }

  async function relever() {
    setBusy(true);
    setReleve(null);
    try {
      if (url.trim() && url.trim() !== (offre?.url || "")) {
        const saveRes = await authedFetch(
          `/api/v1/materiaux/${materiauId}/offres/${magasin.id}`,
          { method: "PUT", body: JSON.stringify(payload()) }
        );
        if (!saveRes.ok) throw new Error(await readError(saveRes));
      }
      const res = await authedFetch(
        `/api/v1/materiaux/${materiauId}/offres/${magasin.id}/relever`,
        { method: "POST" }
      );
      if (!res.ok) throw new Error(await readError(res));
      const j = (await res.json()) as { materiau: Materiau; releve: ReleveInfo };
      setReleve(j.releve);
      if (j.releve.ok) {
        setPrice(j.releve.price != null ? String(j.releve.price) : "");
        setRegular(j.releve.regular_price != null ? String(j.releve.regular_price) : "");
        setOnSale(j.releve.on_sale);
        setSaleEnd(j.releve.sale_end || "");
        onSaved(j.materiau);
      }
    } catch (e) {
      setReleve({
        ok: false,
        price: null,
        regular_price: null,
        on_sale: false,
        sale_end: null,
        changed: false,
        method: "",
        error: (e as Error).message
      });
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
    <div className="absolute left-0 top-full z-30 mt-1 w-72 rounded-lg border border-brand-700 bg-brand-900 p-3 text-left shadow-xl">
      <div className="mb-2 flex items-center justify-between">
        <p className="text-sm font-semibold text-white">{magasin.name}</p>
        <button type="button" onClick={onClose} className="text-white/50 hover:text-white">
          <X className="h-4 w-4" />
        </button>
      </div>
      <div className="grid grid-cols-2 gap-2 text-xs text-white/70">
        <label className="col-span-2">
          Lien de la page produit
          <div className="mt-1 flex gap-1">
            <input
              type="url"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              className="input"
              placeholder="https://…"
              autoFocus={!offre?.unit_price}
            />
            <button
              type="button"
              onClick={relever}
              disabled={busy || !url.trim()}
              className="btn-secondary btn-sm whitespace-nowrap disabled:opacity-60"
              title="Lire le prix du jour sur la page produit"
            >
              <RefreshCw className={`h-3.5 w-3.5 ${busy ? "animate-spin" : ""}`} />
              Relever
            </button>
          </div>
        </label>
        {releve ? (
          <p
            className={`col-span-2 rounded px-2 py-1 text-[11px] ${
              releve.ok ? "bg-emerald-500/10 text-emerald-300" : "bg-rose-500/10 text-rose-300"
            }`}
          >
            {releve.ok
              ? `Lu sur la page : ${money(releve.price)}${
                  releve.on_sale
                    ? ` en rabais (régulier ${money(releve.regular_price)}${
                        releve.sale_end ? `, jusqu'au ${fmtDate(releve.sale_end)}` : ""
                      })`
                    : ""
                }${releve.changed ? " — enregistré" : " — inchangé"}`
              : `Relevé échoué : ${releve.error || "prix introuvable"}`}
          </p>
        ) : null}
        {offre?.page_title ? (
          <p className="col-span-2 text-[11px] text-white/50">Page : {offre.page_title}</p>
        ) : null}
        {offre?.fetch_error && !releve ? (
          <p className="col-span-2 text-[11px] text-amber-300">
            Dernier relevé automatique échoué : {offre.fetch_error}
          </p>
        ) : null}
        <label>
          Prix du jour ($)
          <input
            type="number"
            step="0.01"
            min="0"
            value={price}
            onChange={(e) => setPrice(e.target.value)}
            className="input mt-1"
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
          <input type="checkbox" checked={onSale} onChange={(e) => setOnSale(e.target.checked)} />
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
          Note
          <input value={note} onChange={(e) => setNote(e.target.value)} className="input mt-1" />
        </label>
      </div>
      {offre?.observed_at ? (
        <p className="mt-2 text-[11px] text-white/50">
          Dernière vérification : {fmtDate(offre.observed_at)} ({offre.source})
        </p>
      ) : offre?.unit_price != null ? (
        <p className="mt-2 text-[11px] text-amber-300">Prix d'archive sans date — à vérifier.</p>
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
        <button type="button" onClick={save} disabled={busy} className="btn-accent btn-sm">
          {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />}
          Enregistrer
        </button>
      </div>
    </div>
  );
}
