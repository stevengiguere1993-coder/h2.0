"use client";

// Comparatif SEMAINE PAR SEMAINE des matériaux d'un projet (principe
// batirarabais, 2026-10-01) : meilleur prix de chaque semaine tous
// magasins, plus bas de la période, tendance, avis IA par matériau, coût
// de la liste par semaine ; et l'avis de Gemini sur le meilleur moment
// pour acheter.

import { useEffect, useState } from "react";
import { ChevronDown, ChevronRight, LineChart, Loader2, Sparkles, TrendingDown, TrendingUp } from "lucide-react";

import { authedFetch } from "@/lib/auth";

type Cellule = { semaine: string; meilleur_prix: number | null; meilleur_magasin_id: number | null; rabais: boolean; par_magasin: Record<string, number> };
type LigneCmp = {
  ligne_id: number;
  materiau_name: string;
  quantity: number;
  unit: string | null;
  semaines: Cellule[];
  courant_prix: number | null;
  plus_bas_prix: number | null;
  plus_bas_magasin_id: number | null;
  plus_bas_semaine: string | null;
  tendance: "baisse" | "stable" | "hausse" | "inconnue";
  ecart_plus_bas: number | null;
  verdict_ia: "bon_moment" | "attendre" | "neutre" | null;
  avis_ia: string | null;
  prix_cible_ia: number | null;
};
type Comparatif = {
  semaines: string[];
  magasins: Array<{ id: number; name: string }>;
  lignes: LigneCmp[];
  totaux_semaine: Array<number | null>;
  couverture_semaine: number[];
  total_courant: number | null;
  meilleure_semaine: string | null;
  nb_lignes: number;
};
type Avis = {
  disponible: boolean;
  raison?: string | null;
  moment?: "maintenant" | "attendre" | "partiel" | null;
  semaine_conseillee?: string | null;
  resume?: string | null;
  acheter_maintenant?: string[];
  attendre?: string[];
  economie_estimee?: number | null;
  genere_le?: string | null;
};

function money(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return "—";
  return new Intl.NumberFormat("fr-CA", { style: "currency", currency: "CAD", minimumFractionDigits: 2 }).format(n);
}
function fmtSemaine(iso: string): string {
  const d = new Date(`${iso}T12:00:00`);
  return d.toLocaleDateString("fr-CA", { day: "numeric", month: "short" });
}
function abrev(name: string): string {
  const mots = name.trim().split(/\s+/);
  if (mots.length >= 2) return mots.map((m) => m[0]).join("").toUpperCase().slice(0, 3);
  return name.slice(0, 5);
}

const VERDICT: Record<string, { label: string; cls: string }> = {
  bon_moment: { label: "IA : bon moment", cls: "border-emerald-500/40 bg-emerald-500/15 text-emerald-300" },
  attendre: { label: "IA : attendre", cls: "border-amber-500/40 bg-amber-500/15 text-amber-300" },
  neutre: { label: "IA : neutre", cls: "border-white/20 bg-white/10 text-white/70" }
};
const MOMENT: Record<string, { label: string; cls: string }> = {
  maintenant: { label: "Acheter maintenant", cls: "border-emerald-500/40 bg-emerald-500/10 text-emerald-200" },
  attendre: { label: "Attendre", cls: "border-amber-500/40 bg-amber-500/10 text-amber-200" },
  partiel: { label: "Une partie maintenant, le reste plus tard", cls: "border-sky-500/40 bg-sky-500/10 text-sky-200" }
};

export function ProjectComparatifHebdo({ projectId, refreshKey }: { projectId: number; refreshKey: unknown }) {
  const [cmp, setCmp] = useState<Comparatif | null>(null);
  const [semaines, setSemaines] = useState(8);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [avis, setAvis] = useState<Avis | null>(null);
  const [avisBusy, setAvisBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      setLoading(true);
      try {
        const r = await authedFetch(`/api/v1/projects/${projectId}/materiaux/comparatif?semaines=${semaines}`);
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const j = (await r.json()) as Comparatif;
        if (!cancelled) {
          setCmp(j);
          setError(null);
        }
      } catch (e) {
        if (!cancelled) setError(`Comparatif indisponible : ${(e as Error).message}`);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [projectId, refreshKey, semaines]);

  async function demanderAvis(force = false) {
    setAvisBusy(true);
    try {
      const r = await authedFetch(
        `/api/v1/projects/${projectId}/materiaux/comparatif/avis?semaines=${semaines}${force ? "&force=true" : ""}`,
        { method: "POST" }
      );
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      setAvis((await r.json()) as Avis);
    } catch (e) {
      setAvis({ disponible: false, raison: (e as Error).message });
    } finally {
      setAvisBusy(false);
    }
  }

  if (loading && !cmp) {
    return (
      <div className="flex items-center gap-2 text-xs text-white/60">
        <Loader2 className="h-3.5 w-3.5 animate-spin" /> Calcul du comparatif semaine par semaine…
      </div>
    );
  }
  if (error) return <p className="text-xs text-rose-300">{error}</p>;
  if (!cmp || cmp.nb_lignes === 0) return null;

  const magName = new Map(cmp.magasins.map((m) => [m.id, m.name]));
  const last = cmp.semaines.length - 1;

  return (
    <section className="rounded-xl border border-brand-800 bg-brand-900/60">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full flex-wrap items-center gap-2 px-4 py-3 text-left"
        aria-expanded={open}
      >
        {open ? <ChevronDown className="h-4 w-4 text-white/60" /> : <ChevronRight className="h-4 w-4 text-white/60" />}
        <LineChart className="h-4 w-4 text-accent-500" />
        <span className="text-sm font-semibold text-white">Comparatif semaine par semaine</span>
        <span className="text-xs text-white/60">
          liste au meilleur prix : {money(cmp.total_courant)} cette semaine
          {cmp.meilleure_semaine && cmp.meilleure_semaine !== cmp.semaines[last]
            ? ` · la moins chère était la semaine du ${fmtSemaine(cmp.meilleure_semaine)}`
            : cmp.meilleure_semaine
              ? " · c'est la semaine la moins chère de la période"
              : ""}
        </span>
      </button>

      {open ? (
        <div className="space-y-3 border-t border-brand-800 px-4 py-3">
          <div className="flex flex-wrap items-center gap-3">
            <label className="text-xs text-white/70">
              Période
              <select value={semaines} onChange={(e) => setSemaines(Number(e.target.value))} className="input ml-2 w-auto">
                <option value={4}>4 semaines</option>
                <option value={8}>8 semaines</option>
                <option value={12}>12 semaines</option>
                <option value={26}>26 semaines</option>
              </select>
            </label>
            <button
              type="button"
              onClick={() => void demanderAvis(false)}
              disabled={avisBusy}
              className="btn-accent btn-sm disabled:opacity-60"
              title="Gemini lit ce tableau et les dates des phases, puis conseille le moment d'achat"
            >
              {avisBusy ? <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" /> : <Sparkles className="mr-1 h-3.5 w-3.5" />}
              Avis IA : meilleur moment pour acheter
            </button>
          </div>

          {avis ? (
            avis.disponible ? (
              <div className={`rounded-lg border px-3 py-2 text-sm ${(MOMENT[avis.moment || "partiel"] || MOMENT.partiel).cls}`}>
                <p className="font-semibold">
                  {(MOMENT[avis.moment || "partiel"] || MOMENT.partiel).label}
                  {avis.semaine_conseillee ? ` · semaine du ${fmtSemaine(avis.semaine_conseillee)}` : ""}
                  {avis.economie_estimee ? ` · économie estimée ${money(avis.economie_estimee)}` : ""}
                </p>
                {avis.resume ? <p className="mt-1 text-white/90">{avis.resume}</p> : null}
                {(avis.acheter_maintenant?.length || avis.attendre?.length) ? (
                  <p className="mt-1 text-xs text-white/80">
                    {avis.acheter_maintenant?.length ? <>Maintenant : {avis.acheter_maintenant.join(", ")}. </> : null}
                    {avis.attendre?.length ? <>Attendre : {avis.attendre.join(", ")}.</> : null}
                  </p>
                ) : null}
                <button type="button" onClick={() => void demanderAvis(true)} className="mt-1 text-[11px] text-white/60 underline hover:text-white">
                  Redemander
                </button>
              </div>
            ) : (
              <p className="text-xs text-rose-300">Avis IA indisponible : {avis.raison || "erreur"}</p>
            )
          ) : null}

          <div className="overflow-x-auto">
            <table className="min-w-full text-xs">
              <thead>
                <tr className="text-left uppercase tracking-wider text-white/50">
                  <th className="sticky left-0 bg-brand-900 px-2 py-2">Matériau</th>
                  {cmp.semaines.map((w, i) => (
                    <th key={w} className={`px-2 py-2 text-right whitespace-nowrap ${i === last ? "text-white" : ""}`} title={`Semaine du ${w}`}>
                      {i === last ? "Cette sem." : fmtSemaine(w)}
                    </th>
                  ))}
                  <th className="px-2 py-2 text-right">Plus bas</th>
                  <th className="px-2 py-2">Tendance</th>
                  <th className="px-2 py-2">Avis IA</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-brand-800">
                {cmp.lignes.map((l) => (
                  <tr key={l.ligne_id}>
                    <td className="sticky left-0 bg-brand-900 px-2 py-1.5 font-medium text-white whitespace-nowrap">
                      {l.materiau_name}
                      <span className="ml-1 font-normal text-white/50">
                        × {l.quantity}
                        {l.unit ? ` ${l.unit}` : ""}
                      </span>
                    </td>
                    {l.semaines.map((c, i) => {
                      const isBas = c.meilleur_prix != null && l.plus_bas_prix != null && Math.abs(c.meilleur_prix - l.plus_bas_prix) < 0.005;
                      const tip = Object.entries(c.par_magasin)
                        .map(([mid, p]) => `${magName.get(Number(mid)) || mid} : ${money(p)}`)
                        .join("\n");
                      return (
                        <td
                          key={c.semaine}
                          title={tip || "aucun relevé cette semaine"}
                          className={`px-2 py-1.5 text-right font-mono whitespace-nowrap ${
                            c.meilleur_prix == null
                              ? "text-white/30"
                              : isBas
                                ? "font-semibold text-emerald-300"
                                : c.rabais
                                  ? "text-rose-300"
                                  : i === last
                                    ? "text-white"
                                    : "text-white/80"
                          }`}
                        >
                          {c.meilleur_prix == null ? "—" : money(c.meilleur_prix)}
                          {c.meilleur_magasin_id != null ? (
                            <span className="ml-1 text-[10px] text-white/50">{abrev(magName.get(c.meilleur_magasin_id) || "")}</span>
                          ) : null}
                          {c.rabais ? <span className="ml-0.5 text-[10px] text-rose-300" title="en rabais">R</span> : null}
                        </td>
                      );
                    })}
                    <td className="px-2 py-1.5 text-right font-mono text-emerald-300 whitespace-nowrap">
                      {money(l.plus_bas_prix)}
                      {l.ecart_plus_bas != null && l.ecart_plus_bas > 0.005 ? (
                        <span className="ml-1 text-[10px] text-amber-300">+{Math.round(l.ecart_plus_bas * 100)} % auj.</span>
                      ) : null}
                    </td>
                    <td className="px-2 py-1.5 whitespace-nowrap">
                      {l.tendance === "hausse" ? (
                        <span className="inline-flex items-center gap-1 text-rose-300"><TrendingUp className="h-3.5 w-3.5" /> hausse</span>
                      ) : l.tendance === "baisse" ? (
                        <span className="inline-flex items-center gap-1 text-emerald-300"><TrendingDown className="h-3.5 w-3.5" /> baisse</span>
                      ) : l.tendance === "stable" ? (
                        <span className="text-white/70">stable</span>
                      ) : (
                        <span className="text-white/40">peu de données</span>
                      )}
                    </td>
                    <td className="px-2 py-1.5">
                      {l.verdict_ia ? (
                        <span
                          className={`rounded border px-1.5 py-0.5 text-[10px] font-semibold ${(VERDICT[l.verdict_ia] || VERDICT.neutre).cls}`}
                          title={[l.avis_ia, l.prix_cible_ia != null ? `Prix à viser : ${money(l.prix_cible_ia)}` : null].filter(Boolean).join("\n")}
                        >
                          {(VERDICT[l.verdict_ia] || VERDICT.neutre).label}
                          {l.prix_cible_ia != null ? ` · viser ${money(l.prix_cible_ia)}` : ""}
                        </span>
                      ) : (
                        <span className="text-[10px] text-white/40">pas encore analysé</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr className="border-t border-brand-700 font-semibold text-white">
                  <td className="sticky left-0 bg-brand-900 px-2 py-2">Liste au meilleur prix</td>
                  {cmp.totaux_semaine.map((t, i) => (
                    <td
                      key={cmp.semaines[i]}
                      className={`px-2 py-2 text-right font-mono whitespace-nowrap ${
                        cmp.meilleure_semaine === cmp.semaines[i] ? "text-emerald-300" : t == null ? "text-white/30" : ""
                      }`}
                      title={`${cmp.couverture_semaine[i]} / ${cmp.nb_lignes} ligne(s) avec un prix`}
                    >
                      {money(t)}
                      {cmp.couverture_semaine[i] < cmp.nb_lignes && t != null ? (
                        <span className="ml-0.5 text-[10px] font-normal text-white/50">({cmp.couverture_semaine[i]}/{cmp.nb_lignes})</span>
                      ) : null}
                    </td>
                  ))}
                  <td colSpan={3} />
                </tr>
              </tfoot>
            </table>
          </div>
          <p className="text-[11px] text-white/50">
            Meilleur prix de la semaine tous magasins (survol : le prix de chaque magasin). Un prix relevé reste valable
            jusqu&apos;au relevé suivant ; R = en rabais ; en vert le plus bas de la période. L&apos;historique se construit avec
            les relevés quotidiens et le job de nuit hebdomadaire. Prix hors taxes.
          </p>
        </div>
      ) : null}
    </section>
  );
}
