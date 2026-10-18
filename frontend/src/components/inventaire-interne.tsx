"use client";

// INVENTAIRE INTERNE (Steven 2026-10-18) : le matériel qu'on garde en
// stock, sa quantité en main et son coût moyen. Une SORTIE vers un projet
// (ou un bon de travail) retire la quantité du stock et charge le projet
// par un achat « Inventaire interne » au coût moyen, hors taxes —
// refacturable comme le matériel (ligne « Matériaux » de la facture),
// jamais envoyé dans QuickBooks. Onglet « Inventaire » du catalogue de
// services ; la fenêtre de sortie sert aussi depuis l'onglet Achats d'un
// projet.

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ArrowRightFromLine,
  ClipboardCheck,
  History,
  Loader2,
  PackagePlus,
  Pencil,
  Plus,
  Search,
  Trash2,
  Undo2,
  X
} from "lucide-react";

import { authedFetch } from "@/lib/auth";
import { parseNombre } from "@/lib/nombre";
import { projectLabel, trierProjetsParAdresse } from "@/lib/project";
import { useConfirm } from "@/components/confirm-dialog";
import { SearchSelect } from "@/components/search-select";
import { Link } from "@/i18n/navigation";

export type InventaireArticle = {
  id: number;
  name: string;
  categorie: string | null;
  unit: string | null;
  quantite: number;
  cout_unitaire: number | null;
  valeur: number | null;
  notes: string | null;
  is_active: boolean;
  updated_at: string | null;
};

type Mouvement = {
  id: number;
  article_id: number;
  article_name: string;
  unit: string | null;
  type: "entree" | "ajustement" | "sortie";
  quantite: number;
  cout_unitaire: number | null;
  montant: number | null;
  project_id: number | null;
  project_name: string | null;
  project_address: string | null;
  achat_id: number | null;
  is_billable: boolean | null;
  refacturee: boolean;
  note: string | null;
  par: string | null;
  created_at: string;
};

export type SortieResult = {
  article: InventaireArticle;
  mouvement: Mouvement;
  achat_id: number;
  montant: number;
  is_billable: boolean;
};

type ProjetMini = { id: number; name: string; address?: string | null };
type BonMini = {
  id: number;
  reference: string;
  title: string;
  status: string;
  address?: string | null;
};

const TYPE_LABEL: Record<Mouvement["type"], string> = {
  entree: "Entrée",
  ajustement: "Compte",
  sortie: "Sortie"
};

const TYPE_BADGE: Record<Mouvement["type"], string> = {
  entree: "badge-emerald",
  ajustement: "badge-blue",
  sortie: "badge-amber"
};

function money(n: number | null | undefined, decimales = 2): string {
  if (n == null) return "—";
  return `${n.toLocaleString("fr-CA", {
    minimumFractionDigits: 2,
    maximumFractionDigits: decimales
  })} $`;
}

function qte(n: number, unit?: string | null): string {
  const s = n.toLocaleString("fr-CA", { maximumFractionDigits: 3 });
  return unit ? `${s} ${unit}` : s;
}

function fmtDateTime(iso: string): string {
  return new Date(iso).toLocaleString("fr-CA", {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit"
  });
}

async function readError(res: Response): Promise<string> {
  try {
    const j = (await res.json()) as { detail?: unknown };
    if (typeof j.detail === "string") return j.detail;
  } catch {
    /* ignore */
  }
  return `Erreur ${res.status}`;
}

/** Nombre saisi (virgule ou point) ; vide → null ; invalide → NaN. */
function saisie(v: string): number | null {
  if (!v.trim()) return null;
  return parseNombre(v);
}

// ───────────────────────────── Onglet ─────────────────────────────

export function InventaireInterne() {
  const confirm = useConfirm();
  const [articles, setArticles] = useState<InventaireArticle[]>([]);
  const [mouvements, setMouvements] = useState<Mouvement[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [flash, setFlash] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [categorie, setCategorie] = useState("");
  const [inactifs, setInactifs] = useState(false);
  const [filtreArticle, setFiltreArticle] = useState<InventaireArticle | null>(
    null
  );
  const [edition, setEdition] = useState<InventaireArticle | "nouveau" | null>(
    null
  );
  const [mouvement, setMouvement] = useState<{
    article: InventaireArticle;
    type: "entree" | "ajustement";
  } | null>(null);
  const [sortie, setSortie] = useState<InventaireArticle | null>(null);

  const charger = useCallback(async () => {
    setError(null);
    try {
      const params = new URLSearchParams({ actifs: inactifs ? "false" : "true" });
      const histo = new URLSearchParams({ limit: "100" });
      if (filtreArticle) histo.set("article_id", String(filtreArticle.id));
      const [aRes, mRes] = await Promise.all([
        authedFetch(`/api/v1/inventaire/articles?${params}`),
        authedFetch(`/api/v1/inventaire/mouvements?${histo}`)
      ]);
      if (!aRes.ok) throw new Error(await readError(aRes));
      setArticles((await aRes.json()) as InventaireArticle[]);
      setMouvements(mRes.ok ? ((await mRes.json()) as Mouvement[]) : []);
    } catch (e) {
      setError(`Chargement échoué : ${(e as Error).message}`);
    } finally {
      setLoading(false);
    }
  }, [inactifs, filtreArticle]);

  useEffect(() => {
    void charger();
  }, [charger]);

  const categories = useMemo(
    () =>
      Array.from(
        new Set(articles.map((a) => (a.categorie || "").trim()).filter(Boolean))
      ).sort((a, b) => a.localeCompare(b, "fr")),
    [articles]
  );

  const visibles = useMemo(() => {
    const t = q.trim().toLowerCase();
    return articles.filter(
      (a) =>
        (!categorie || (a.categorie || "") === categorie) &&
        (!t ||
          a.name.toLowerCase().includes(t) ||
          (a.categorie || "").toLowerCase().includes(t) ||
          (a.notes || "").toLowerCase().includes(t))
    );
  }, [articles, q, categorie]);

  const valeurTotale = useMemo(
    () => visibles.reduce((s, a) => s + (a.valeur || 0), 0),
    [visibles]
  );

  function afficher(message: string) {
    setFlash(message);
    setTimeout(() => setFlash(null), 6000);
  }

  async function supprimer(a: InventaireArticle) {
    const ok = await confirm({
      title: `Retirer « ${a.name} » de l'inventaire ?`,
      description:
        "Jamais sorti vers un projet : l'article est supprimé. Déjà chargé à un projet : il est désactivé et son historique reste.",
      confirmLabel: "Retirer",
      destructive: true
    });
    if (!ok) return;
    const res = await authedFetch(`/api/v1/inventaire/articles/${a.id}`, {
      method: "DELETE"
    });
    if (!res.ok) {
      setError(await readError(res));
      return;
    }
    const { action } = (await res.json()) as { action: string };
    afficher(
      action === "supprime"
        ? `« ${a.name} » supprimé.`
        : `« ${a.name} » désactivé (historique conservé).`
    );
    if (filtreArticle?.id === a.id) setFiltreArticle(null);
    await charger();
  }

  async function annuler(m: Mouvement) {
    const ok = await confirm({
      title: "Annuler cette sortie ?",
      description: `${qte(Math.abs(m.quantite), m.unit)} de « ${m.article_name} » retournent en stock et l'achat de ${money(m.montant)} est retiré du projet.`,
      confirmLabel: "Annuler la sortie",
      destructive: true
    });
    if (!ok) return;
    const res = await authedFetch(`/api/v1/inventaire/mouvements/${m.id}`, {
      method: "DELETE"
    });
    if (!res.ok) {
      setError(await readError(res));
      return;
    }
    afficher("Sortie annulée : la marchandise est de retour en stock.");
    await charger();
  }

  return (
    <div className="space-y-6">
      <p className="text-sm text-white/70">
        Le matériel gardé en stock. Une <strong>sortie</strong> vers un projet
        ou un bon de travail retire la quantité du stock et ajoute au projet un
        achat « Inventaire interne » au coût moyen, hors taxes : il compte dans
        le coût du projet et se refacture comme le matériel (ligne
        « Matériaux » de la facture), sans aller dans QuickBooks.
      </p>

      {error ? (
        <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-4 py-2 text-sm text-rose-300">
          {error}
        </p>
      ) : null}
      {flash ? (
        <p className="rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-4 py-2 text-sm text-emerald-300">
          {flash}
        </p>
      ) : null}

      <div className="flex flex-wrap items-center gap-2">
        <div className="relative min-w-[200px] flex-1">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-white/40" />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Chercher un article…"
            className="input w-full pl-8"
          />
        </div>
        <select
          value={categorie}
          onChange={(e) => setCategorie(e.target.value)}
          className="input w-auto"
        >
          <option value="">Toutes les catégories</option>
          {categories.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
        <label className="flex items-center gap-1.5 text-xs text-white/70">
          <input
            type="checkbox"
            checked={inactifs}
            onChange={(e) => setInactifs(e.target.checked)}
          />
          Afficher les désactivés
        </label>
        <button
          type="button"
          onClick={() => setEdition("nouveau")}
          className="btn-accent btn-sm"
        >
          <Plus className="h-3.5 w-3.5" /> Nouvel article
        </button>
      </div>

      {loading ? (
        <div className="flex min-h-[20vh] items-center justify-center">
          <Loader2 className="h-5 w-5 animate-spin text-accent-500" />
        </div>
      ) : visibles.length === 0 ? (
        <div className="empty-state">
          {articles.length === 0
            ? "Aucun article en inventaire. Ajoute ce que vous gardez en stock avec « Nouvel article »."
            : "Aucun article ne correspond à la recherche."}
        </div>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-brand-800 bg-brand-900">
          <table className="w-full min-w-[820px] text-sm">
            <thead className="border-b border-brand-800 bg-brand-950/50 text-left text-[11px] uppercase tracking-wider text-white/50">
              <tr>
                <th className="px-3 py-2">Article</th>
                <th className="px-3 py-2">Catégorie</th>
                <th className="px-3 py-2 text-right">En main</th>
                <th className="px-3 py-2 text-right">Coût moyen (HT)</th>
                <th className="px-3 py-2 text-right">Valeur</th>
                <th className="px-3 py-2 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-brand-800">
              {visibles.map((a) => (
                <tr key={a.id} className="hover:bg-brand-800/30">
                  <td className="px-3 py-2">
                    <span
                      className={
                        a.is_active
                          ? "font-semibold text-white"
                          : "font-semibold text-white/50 line-through"
                      }
                    >
                      {a.name}
                    </span>
                    {a.notes ? (
                      <span className="block text-[11px] text-white/60">
                        {a.notes}
                      </span>
                    ) : null}
                  </td>
                  <td className="px-3 py-2 text-white/70">
                    {a.categorie || "—"}
                  </td>
                  <td className="px-3 py-2 text-right">
                    {a.quantite <= 0 ? (
                      <span className="badge badge-amber">Épuisé</span>
                    ) : (
                      <span className="font-semibold text-white">
                        {qte(a.quantite, a.unit)}
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-right text-white/80">
                    {a.cout_unitaire == null ? (
                      <span className="text-amber-300">à indiquer</span>
                    ) : (
                      `${money(a.cout_unitaire, 4)}${a.unit ? ` / ${a.unit}` : ""}`
                    )}
                  </td>
                  <td className="px-3 py-2 text-right text-white/80">
                    {money(a.valeur)}
                  </td>
                  <td className="px-3 py-2">
                    <div className="flex items-center justify-end gap-1">
                      <button
                        type="button"
                        onClick={() => setSortie(a)}
                        disabled={!a.is_active || a.quantite <= 0}
                        className="btn-accent btn-sm whitespace-nowrap disabled:opacity-50"
                        title="Sortir vers un projet ou un bon de travail"
                      >
                        <ArrowRightFromLine className="h-3.5 w-3.5" /> Sortir
                      </button>
                      <button
                        type="button"
                        onClick={() => setMouvement({ article: a, type: "entree" })}
                        disabled={!a.is_active}
                        className="btn-secondary btn-sm disabled:opacity-50"
                        title="Ajouter au stock (achat, retour de chantier)"
                      >
                        <PackagePlus className="h-3.5 w-3.5" />
                      </button>
                      <button
                        type="button"
                        onClick={() => setMouvement({ article: a, type: "ajustement" })}
                        className="btn-secondary btn-sm"
                        title="Corriger d'après un compte"
                      >
                        <ClipboardCheck className="h-3.5 w-3.5" />
                      </button>
                      <button
                        type="button"
                        onClick={() => setFiltreArticle(a)}
                        className="btn-secondary btn-sm"
                        title="Historique de cet article"
                      >
                        <History className="h-3.5 w-3.5" />
                      </button>
                      <button
                        type="button"
                        onClick={() => setEdition(a)}
                        className="btn-secondary btn-sm"
                        title="Modifier"
                      >
                        <Pencil className="h-3.5 w-3.5" />
                      </button>
                      <button
                        type="button"
                        onClick={() => void supprimer(a)}
                        className="btn-secondary btn-sm"
                        title="Retirer de l'inventaire"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
            <tfoot className="border-t border-brand-800 text-sm">
              <tr>
                <td colSpan={4} className="px-3 py-2 text-right text-white/60">
                  Valeur du stock affiché (HT)
                </td>
                <td className="px-3 py-2 text-right font-semibold text-white">
                  {money(valeurTotale)}
                </td>
                <td />
              </tr>
            </tfoot>
          </table>
        </div>
      )}

      <section>
        <header className="mb-2 flex flex-wrap items-center justify-between gap-2">
          <h3 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
            Mouvements récents
            {filtreArticle ? ` — ${filtreArticle.name}` : ""}
          </h3>
          {filtreArticle ? (
            <button
              type="button"
              onClick={() => setFiltreArticle(null)}
              className="btn-secondary btn-sm"
            >
              <X className="h-3.5 w-3.5" /> Tous les articles
            </button>
          ) : null}
        </header>
        {mouvements.length === 0 ? (
          <div className="empty-state">Aucun mouvement pour l&apos;instant.</div>
        ) : (
          <div className="overflow-x-auto rounded-xl border border-brand-800 bg-brand-900">
            <table className="w-full min-w-[860px] text-sm">
              <thead className="border-b border-brand-800 bg-brand-950/50 text-left text-[11px] uppercase tracking-wider text-white/50">
                <tr>
                  <th className="px-3 py-2">Date</th>
                  <th className="px-3 py-2">Article</th>
                  <th className="px-3 py-2">Mouvement</th>
                  <th className="px-3 py-2 text-right">Quantité</th>
                  <th className="px-3 py-2 text-right">Montant (HT)</th>
                  <th className="px-3 py-2">Projet</th>
                  <th className="px-3 py-2">Par</th>
                  <th className="px-3 py-2" />
                </tr>
              </thead>
              <tbody className="divide-y divide-brand-800">
                {mouvements.map((m) => (
                  <tr key={m.id} className="hover:bg-brand-800/30">
                    <td className="whitespace-nowrap px-3 py-2 text-white/70">
                      {fmtDateTime(m.created_at)}
                    </td>
                    <td className="px-3 py-2 text-white">
                      {m.article_name}
                      {m.note ? (
                        <span className="block text-[11px] text-white/60">
                          {m.note}
                        </span>
                      ) : null}
                    </td>
                    <td className="px-3 py-2">
                      <span className={`badge ${TYPE_BADGE[m.type]}`}>
                        {TYPE_LABEL[m.type]}
                      </span>
                    </td>
                    <td className="whitespace-nowrap px-3 py-2 text-right font-semibold text-white">
                      {m.quantite > 0 ? "+" : ""}
                      {qte(m.quantite, m.unit)}
                    </td>
                    <td className="whitespace-nowrap px-3 py-2 text-right text-white/80">
                      {m.type === "ajustement" ? "—" : money(m.montant)}
                    </td>
                    <td className="px-3 py-2 text-white/80">
                      {m.project_id ? (
                        <Link
                          // eslint-disable-next-line @typescript-eslint/no-explicit-any
                          href={`/app/projets/${m.project_id}#achats` as any}
                          className="text-accent-400 hover:underline"
                        >
                          {projectLabel({
                            name: m.project_name,
                            address: m.project_address
                          })}
                        </Link>
                      ) : (
                        "—"
                      )}
                      {m.type === "sortie" && m.achat_id ? (
                        <span className="block text-[11px] text-white/60">
                          {m.refacturee
                            ? "Refacturé"
                            : m.is_billable
                              ? "À refacturer"
                              : "Coût du projet"}
                        </span>
                      ) : null}
                    </td>
                    <td className="px-3 py-2 text-xs text-white/60">
                      {m.par || "—"}
                    </td>
                    <td className="px-3 py-2 text-right">
                      {m.type === "sortie" && !m.refacturee ? (
                        <button
                          type="button"
                          onClick={() => void annuler(m)}
                          className="btn-secondary btn-sm whitespace-nowrap"
                          title="Remettre en stock et retirer l'achat du projet"
                        >
                          <Undo2 className="h-3.5 w-3.5" /> Annuler
                        </button>
                      ) : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {edition ? (
        <ArticleModal
          article={edition === "nouveau" ? null : edition}
          categories={categories}
          onClose={() => setEdition(null)}
          onSaved={(a, nouveau) => {
            setEdition(null);
            afficher(nouveau ? `« ${a.name} » ajouté.` : `« ${a.name} » mis à jour.`);
            void charger();
          }}
        />
      ) : null}
      {mouvement ? (
        <MouvementModal
          article={mouvement.article}
          type={mouvement.type}
          onClose={() => setMouvement(null)}
          onSaved={(a) => {
            setMouvement(null);
            afficher(`« ${a.name} » : ${qte(a.quantite, a.unit)} en main.`);
            void charger();
          }}
        />
      ) : null}
      {sortie ? (
        <SortieInventaireModal
          article={sortie}
          onClose={() => setSortie(null)}
          onDone={(r) => {
            setSortie(null);
            afficher(
              `${qte(Math.abs(r.mouvement.quantite), r.article.unit)} de « ${r.article.name} » chargés à ${projectLabel({
                name: r.mouvement.project_name,
                address: r.mouvement.project_address
              })} (${money(r.montant)}${r.is_billable ? ", à refacturer" : ""}).`
            );
            void charger();
          }}
        />
      ) : null}
    </div>
  );
}

// ───────────────────────────── Fenêtres ─────────────────────────────

function Fenetre({
  titre,
  onClose,
  children
}: {
  titre: string;
  onClose: () => void;
  children: React.ReactNode;
}) {
  return (
    <div className="fixed inset-0 z-40 flex items-start justify-center overflow-y-auto bg-black/60 p-4 sm:items-center">
      <div className="w-full max-w-lg rounded-xl border border-brand-700 bg-brand-900 p-4 shadow-2xl">
        <div className="mb-3 flex items-center justify-between gap-2">
          <h3 className="text-sm font-semibold text-white">{titre}</h3>
          <button
            type="button"
            onClick={onClose}
            className="text-white/60 hover:text-white"
            aria-label="Fermer"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

function ArticleModal({
  article,
  categories,
  onClose,
  onSaved
}: {
  article: InventaireArticle | null;
  categories: string[];
  onClose: () => void;
  onSaved: (a: InventaireArticle, nouveau: boolean) => void;
}) {
  const [name, setName] = useState(article?.name || "");
  const [categorie, setCategorie] = useState(article?.categorie || "");
  const [unit, setUnit] = useState(article?.unit || "");
  const [notes, setNotes] = useState(article?.notes || "");
  const [quantite, setQuantite] = useState("");
  const [cout, setCout] = useState(
    article?.cout_unitaire != null ? String(article.cout_unitaire).replace(".", ",") : ""
  );
  const [actif, setActif] = useState(article?.is_active ?? true);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function enregistrer() {
    setErr(null);
    const q = saisie(quantite);
    const c = saisie(cout);
    if (!name.trim()) return setErr("Le nom est requis.");
    if ((q != null && (Number.isNaN(q) || q < 0)) || (c != null && (Number.isNaN(c) || c < 0)))
      return setErr("Quantité ou coût invalide.");
    setBusy(true);
    try {
      const corps: Record<string, unknown> = {
        name: name.trim(),
        categorie: categorie.trim() || null,
        unit: unit.trim() || null,
        notes: notes.trim() || null
      };
      if (article) {
        corps.is_active = actif;
        if (c != null) corps.cout_unitaire = c;
      } else {
        if (q != null) corps.quantite = q;
        if (c != null) corps.cout_unitaire = c;
      }
      const res = await authedFetch(
        article ? `/api/v1/inventaire/articles/${article.id}` : "/api/v1/inventaire/articles",
        {
          method: article ? "PATCH" : "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(corps)
        }
      );
      if (!res.ok) throw new Error(await readError(res));
      onSaved((await res.json()) as InventaireArticle, !article);
    } catch (e) {
      setErr((e as Error).message);
      setBusy(false);
    }
  }

  return (
    <Fenetre titre={article ? `Modifier « ${article.name} »` : "Nouvel article"} onClose={onClose}>
      <div className="grid grid-cols-2 gap-3 text-xs text-white/70">
        <label className="col-span-2">
          Nom
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="input mt-1"
            placeholder="Vis à gypse 1 1/4 po"
            autoFocus
          />
        </label>
        <label>
          Catégorie
          <input
            value={categorie}
            onChange={(e) => setCategorie(e.target.value)}
            list="inventaire-categories"
            className="input mt-1"
            placeholder="Quincaillerie"
          />
          <datalist id="inventaire-categories">
            {categories.map((c) => (
              <option key={c} value={c} />
            ))}
          </datalist>
        </label>
        <label>
          Unité
          <input
            value={unit}
            onChange={(e) => setUnit(e.target.value)}
            className="input mt-1"
            placeholder="boîte, rouleau, pi…"
          />
        </label>
        {article ? null : (
          <label>
            Quantité en main
            <input
              value={quantite}
              onChange={(e) => setQuantite(e.target.value)}
              inputMode="decimal"
              className="input mt-1"
              placeholder="0"
            />
          </label>
        )}
        <label className={article ? "col-span-2" : ""}>
          {article ? "Coût moyen (HT) par unité" : "Coût unitaire (HT)"}
          <input
            value={cout}
            onChange={(e) => setCout(e.target.value)}
            inputMode="decimal"
            className="input mt-1"
            placeholder="0,00"
          />
        </label>
        {article ? (
          <p className="col-span-2 text-[11px] text-white/60">
            Corriger le coût moyen vaut pour les prochaines sorties ; les
            sorties passées gardent le montant chargé à leur projet.
          </p>
        ) : null}
        <label className="col-span-2">
          Notes
          <input
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            className="input mt-1"
            placeholder="Emplacement, fournisseur habituel…"
          />
        </label>
        {article ? (
          <label className="col-span-2 flex items-center gap-2 text-white/80">
            <input type="checkbox" checked={actif} onChange={(e) => setActif(e.target.checked)} />
            Article actif
          </label>
        ) : null}
      </div>
      {err ? <p className="mt-3 text-xs text-rose-300">{err}</p> : null}
      <div className="mt-4 flex justify-end gap-2">
        <button type="button" onClick={onClose} className="btn-secondary btn-sm">
          Annuler
        </button>
        <button
          type="button"
          onClick={() => void enregistrer()}
          disabled={busy}
          className="btn-accent btn-sm disabled:opacity-60"
        >
          {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
          Enregistrer
        </button>
      </div>
    </Fenetre>
  );
}

function MouvementModal({
  article,
  type,
  onClose,
  onSaved
}: {
  article: InventaireArticle;
  type: "entree" | "ajustement";
  onClose: () => void;
  onSaved: (a: InventaireArticle) => void;
}) {
  const [quantite, setQuantite] = useState(
    type === "ajustement" ? String(article.quantite).replace(".", ",") : ""
  );
  const [cout, setCout] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function enregistrer() {
    setErr(null);
    const q = saisie(quantite);
    const c = saisie(cout);
    if (q == null || Number.isNaN(q) || q < 0 || (type === "entree" && q <= 0))
      return setErr("Indique une quantité valide.");
    if (c != null && (Number.isNaN(c) || c < 0)) return setErr("Coût invalide.");
    setBusy(true);
    try {
      const corps: Record<string, unknown> = { quantite: q, note: note.trim() || null };
      if (type === "entree" && c != null) corps.cout_unitaire = c;
      const res = await authedFetch(
        `/api/v1/inventaire/articles/${article.id}/${type}`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(corps)
        }
      );
      if (!res.ok) throw new Error(await readError(res));
      onSaved((await res.json()) as InventaireArticle);
    } catch (e) {
      setErr((e as Error).message);
      setBusy(false);
    }
  }

  return (
    <Fenetre
      titre={
        type === "entree"
          ? `Ajouter au stock — ${article.name}`
          : `Compte — ${article.name}`
      }
      onClose={onClose}
    >
      <p className="mb-3 text-xs text-white/70">
        En main : <strong className="text-white">{qte(article.quantite, article.unit)}</strong>
        {article.cout_unitaire != null
          ? ` · coût moyen ${money(article.cout_unitaire, 4)}`
          : ""}
      </p>
      <div className="grid grid-cols-2 gap-3 text-xs text-white/70">
        <label className={type === "entree" ? "" : "col-span-2"}>
          {type === "entree" ? "Quantité ajoutée" : "Quantité comptée"}
          <input
            value={quantite}
            onChange={(e) => setQuantite(e.target.value)}
            inputMode="decimal"
            className="input mt-1"
            autoFocus
          />
        </label>
        {type === "entree" ? (
          <label>
            Prix payé (HT) par unité
            <input
              value={cout}
              onChange={(e) => setCout(e.target.value)}
              inputMode="decimal"
              className="input mt-1"
              placeholder="vide = coût moyen inchangé"
            />
          </label>
        ) : null}
        <label className="col-span-2">
          Note
          <input
            value={note}
            onChange={(e) => setNote(e.target.value)}
            className="input mt-1"
            placeholder={type === "entree" ? "Achat Canac, retour de chantier…" : "Compte du vendredi…"}
          />
        </label>
      </div>
      {type === "entree" ? (
        <p className="mt-2 text-[11px] text-white/60">
          Le coût moyen est recalculé avec le prix payé (moyenne pondérée).
        </p>
      ) : null}
      {err ? <p className="mt-3 text-xs text-rose-300">{err}</p> : null}
      <div className="mt-4 flex justify-end gap-2">
        <button type="button" onClick={onClose} className="btn-secondary btn-sm">
          Annuler
        </button>
        <button
          type="button"
          onClick={() => void enregistrer()}
          disabled={busy}
          className="btn-accent btn-sm disabled:opacity-60"
        >
          {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
          Enregistrer
        </button>
      </div>
    </Fenetre>
  );
}

/**
 * Sortie de l'inventaire vers un projet. Depuis l'onglet Inventaire,
 * l'article est connu et on choisit le projet ou le bon de travail ;
 * depuis l'onglet Achats d'un projet, le projet est connu et on choisit
 * l'article.
 */
export function SortieInventaireModal({
  article: articleFixe,
  projectId,
  onClose,
  onDone
}: {
  article?: InventaireArticle;
  projectId?: number;
  onClose: () => void;
  onDone: (r: SortieResult) => void;
}) {
  const [articles, setArticles] = useState<InventaireArticle[]>([]);
  const [articleId, setArticleId] = useState(articleFixe ? String(articleFixe.id) : "");
  const [cible, setCible] = useState<"projet" | "bon">("projet");
  const [projets, setProjets] = useState<ProjetMini[]>([]);
  const [bons, setBons] = useState<BonMini[]>([]);
  const [projetSel, setProjetSel] = useState("");
  const [bonSel, setBonSel] = useState("");
  const [quantite, setQuantite] = useState("");
  const [cout, setCout] = useState("");
  const [note, setNote] = useState("");
  const [refacturer, setRefacturer] = useState(false);
  // Case touchée à la main → choix explicite envoyé (verrouillé) ; sinon
  // la règle du projet s'applique côté serveur.
  const [refacturerChoisi, setRefacturerChoisi] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let annule = false;
    async function charger() {
      try {
        if (!articleFixe) {
          const r = await authedFetch("/api/v1/inventaire/articles");
          if (r.ok && !annule) setArticles((await r.json()) as InventaireArticle[]);
        }
        if (projectId == null) {
          const [pRes, bRes] = await Promise.all([
            authedFetch("/api/v1/projects?limit=500"),
            authedFetch("/api/v1/bons-travail?limit=500")
          ]);
          if (annule) return;
          if (pRes.ok) setProjets((await pRes.json()) as ProjetMini[]);
          if (bRes.ok)
            setBons(
              ((await bRes.json()) as BonMini[]).filter(
                (b) => b.status !== "cancelled" && b.status !== "facture"
              )
            );
        }
      } catch {
        /* listes vides : l'erreur se verra à l'envoi */
      }
    }
    void charger();
    return () => {
      annule = true;
    };
  }, [articleFixe, projectId]);

  const article =
    articleFixe || articles.find((a) => String(a.id) === articleId) || null;
  const projetCible =
    projectId != null
      ? projectId
      : cible === "projet" && projetSel
        ? Number(projetSel)
        : null;

  // « À refacturer » par défaut : règle du projet (contrat ou bon de
  // travail), tant que la case n'a pas été touchée.
  useEffect(() => {
    if (refacturerChoisi) return;
    if (projectId == null && cible === "bon") {
      setRefacturer(true);
      return;
    }
    if (projetCible == null) return;
    let annule = false;
    void (async () => {
      const r = await authedFetch(
        `/api/v1/inventaire/sortie-defaut?project_id=${projetCible}`
      );
      if (r.ok && !annule) setRefacturer(((await r.json()) as { is_billable: boolean }).is_billable);
    })();
    return () => {
      annule = true;
    };
  }, [projetCible, cible, projectId, refacturerChoisi]);

  const q = saisie(quantite);
  const c = saisie(cout);
  const coutApplique = c != null && !Number.isNaN(c) ? c : article?.cout_unitaire ?? null;
  const total =
    q != null && !Number.isNaN(q) && coutApplique != null
      ? Math.round(q * coutApplique * 100) / 100
      : null;

  async function envoyer() {
    setErr(null);
    if (!article) return setErr("Choisis un article.");
    if (q == null || Number.isNaN(q) || q <= 0) return setErr("Indique la quantité sortie.");
    if (q > article.quantite + 1e-9)
      return setErr(
        `Il reste seulement ${qte(article.quantite, article.unit)} en stock.`
      );
    if (c != null && (Number.isNaN(c) || c < 0)) return setErr("Coût invalide.");
    if (coutApplique == null) return setErr("Indique le coût unitaire (HT).");
    setBusy(true);
    try {
      let pid = projetCible;
      if (projectId == null && cible === "bon") {
        if (!bonSel) throw new Error("Choisis un bon de travail.");
        // Le bon porte ses coûts par son projet lié (garanti ici), comme
        // un achat saisi sur un bon.
        const bp = await authedFetch(
          `/api/v1/bons-travail/${Number(bonSel)}/ensure-project`,
          { method: "POST" }
        );
        if (!bp.ok) throw new Error("Projet du bon introuvable.");
        pid = ((await bp.json()) as { project_id: number }).project_id;
      }
      if (pid == null) throw new Error("Choisis un projet.");
      const corps: Record<string, unknown> = {
        project_id: pid,
        quantite: q,
        note: note.trim() || null
      };
      if (c != null) corps.cout_unitaire = c;
      if (refacturerChoisi) corps.is_billable = refacturer;
      const res = await authedFetch(
        `/api/v1/inventaire/articles/${article.id}/sortie`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(corps)
        }
      );
      if (!res.ok) throw new Error(await readError(res));
      onDone((await res.json()) as SortieResult);
    } catch (e) {
      setErr((e as Error).message);
      setBusy(false);
    }
  }

  return (
    <Fenetre
      titre={article && articleFixe ? `Sortir — ${article.name}` : "Sortir de l'inventaire"}
      onClose={onClose}
    >
      <div className="grid grid-cols-2 gap-3 text-xs text-white/70">
        {articleFixe ? null : (
          <div className="col-span-2">
            <span>Article</span>
            <div className="mt-1">
              <SearchSelect
                value={articleId}
                onChange={setArticleId}
                options={articles
                  .filter((a) => a.quantite > 0)
                  .map((a) => ({
                    value: String(a.id),
                    label: `${a.name} — ${qte(a.quantite, a.unit)} en main`,
                    group: a.categorie || "Sans catégorie"
                  }))}
                placeholder="Choisis ou tape pour chercher un article…"
              />
            </div>
            {articles.length > 0 && articles.every((a) => a.quantite <= 0) ? (
              <p className="mt-1 text-[11px] text-amber-300">
                Aucun article en stock.
              </p>
            ) : null}
          </div>
        )}
        {article ? (
          <p className="col-span-2">
            En main : <strong className="text-white">{qte(article.quantite, article.unit)}</strong>
            {article.cout_unitaire != null
              ? ` · coût moyen ${money(article.cout_unitaire, 4)}${article.unit ? ` / ${article.unit}` : ""}`
              : " · coût moyen à indiquer"}
          </p>
        ) : null}
        {projectId == null ? (
          <div className="col-span-2">
            <div className="mb-1 inline-flex rounded-md border border-brand-700 p-0.5">
              {(
                [
                  ["projet", "Projet"],
                  ["bon", "Bon de travail"]
                ] as const
              ).map(([val, lab]) => (
                <button
                  key={val}
                  type="button"
                  onClick={() => setCible(val)}
                  className={`rounded px-2.5 py-1 font-semibold transition ${
                    cible === val
                      ? "bg-accent-500 text-brand-950"
                      : "text-white/70 hover:bg-white/5"
                  }`}
                >
                  {lab}
                </button>
              ))}
            </div>
            {cible === "projet" ? (
              <SearchSelect
                value={projetSel}
                onChange={setProjetSel}
                options={trierProjetsParAdresse(projets).map((p) => ({
                  value: String(p.id),
                  label: projectLabel(p)
                }))}
                placeholder="Choisis ou tape pour chercher un projet…"
              />
            ) : (
              <SearchSelect
                value={bonSel}
                onChange={setBonSel}
                options={bons.map((b) => ({
                  value: String(b.id),
                  label: `${b.reference} — ${
                    (b.address || "").trim() ? `${(b.address || "").trim()} · ` : ""
                  }${b.title}`
                }))}
                placeholder="Choisis ou tape pour chercher un bon de travail…"
              />
            )}
          </div>
        ) : null}
        <label>
          Quantité{article?.unit ? ` (${article.unit})` : ""}
          <input
            value={quantite}
            onChange={(e) => setQuantite(e.target.value)}
            inputMode="decimal"
            className="input mt-1"
            autoFocus={Boolean(articleFixe)}
          />
        </label>
        <label>
          Coût unitaire (HT)
          <input
            value={cout}
            onChange={(e) => setCout(e.target.value)}
            inputMode="decimal"
            className="input mt-1"
            placeholder={
              article?.cout_unitaire != null
                ? `${money(article.cout_unitaire, 4)} (moyen)`
                : "requis"
            }
          />
        </label>
        <label className="col-span-2">
          Note
          <input
            value={note}
            onChange={(e) => setNote(e.target.value)}
            className="input mt-1"
            placeholder="Pour la salle de bain du 2e…"
          />
        </label>
        <label className="col-span-2 flex items-center gap-2 text-white/80">
          <input
            type="checkbox"
            checked={refacturer}
            onChange={(e) => {
              setRefacturer(e.target.checked);
              setRefacturerChoisi(true);
            }}
          />
          À refacturer au client (majoration du matériel)
        </label>
      </div>
      <p className="mt-3 rounded-md border border-brand-800 bg-brand-950 px-3 py-2 text-xs text-white/70">
        Chargé au projet :{" "}
        <strong className="text-white">{total != null ? money(total) : "—"}</strong>{" "}
        hors taxes, comme un achat « Inventaire interne » (hors QuickBooks).
      </p>
      {err ? <p className="mt-3 text-xs text-rose-300">{err}</p> : null}
      <div className="mt-4 flex justify-end gap-2">
        <button type="button" onClick={onClose} className="btn-secondary btn-sm">
          Annuler
        </button>
        <button
          type="button"
          onClick={() => void envoyer()}
          disabled={busy}
          className="btn-accent btn-sm disabled:opacity-60"
        >
          {busy ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <ArrowRightFromLine className="h-3.5 w-3.5" />
          )}
          Sortir et charger au projet
        </button>
      </div>
    </Fenetre>
  );
}
