"use client";

// Plan d'achat d'un projet (principe batirarabais.ca, 2026-10-01) : pour
// chaque phase, quoi acheter MAINTENANT, quoi ATTENDRE et pourquoi (rabais
// et sa fin, plus bas prix connu sur 6 mois, date de la phase), et le plan
// « meilleur prix par ligne » par magasin comparé à « tout au même magasin ».

import { useEffect, useState } from "react";
import { CalendarClock, ChevronDown, ChevronRight, ExternalLink, Loader2, ShoppingCart, Tag } from "lucide-react";

import { authedFetch } from "@/lib/auth";

type PlanLigne = {
  ligne_id: number;
  materiau_id: number;
  materiau_name: string;
  quantity: number;
  unit: string | null;
  moment: "maintenant" | "attendre" | "sans_prix";
  raison: string;
  magasin_name: string | null;
  unit_price: number | null;
  total: number | null;
  regular_price: number | null;
  on_sale: boolean;
  sale_end: string | null;
  url: string | null;
  plus_bas: number | null;
  plus_bas_magasin: string | null;
  plus_bas_le: string | null;
  ecart_plus_bas: number | null;
  economie_rabais: number;
  verdict_ia: "bon_moment" | "attendre" | "neutre" | null;
  avis_ia: string | null;
  prix_cible_ia: number | null;
  analyse_ia_at: string | null;
};

const VERDICT_IA: Record<string, { label: string; cls: string }> = {
  bon_moment: { label: "IA : bon moment", cls: "border-emerald-500/40 bg-emerald-500/15 text-emerald-300" },
  attendre: { label: "IA : attendre", cls: "border-amber-500/40 bg-amber-500/15 text-amber-300" },
  neutre: { label: "IA : neutre", cls: "border-white/20 bg-white/10 text-white/70" }
};

type PlanPhase = {
  phase_id: number | null;
  name: string;
  start_date: string | null;
  jours_avant: number | null;
  acheter_avant: string | null;
  lignes: PlanLigne[];
  total_maintenant: number;
  total_attendre: number;
  nb_sans_prix: number;
};

type PlanMagasin = { magasin_id: number; magasin_name: string; nb_lignes: number; total: number; nb_manquantes: number };

type Plan = {
  phases: PlanPhase[];
  par_magasin: PlanMagasin[];
  total_meilleur: number;
  nb_magasins: number;
  un_seul_magasin: PlanMagasin | null;
  economie_vs_un_seul: number;
  nb_lignes: number;
  nb_maintenant: number;
  nb_attendre: number;
  nb_sans_prix: number;
  total_maintenant: number;
  total_attendre: number;
  economie_rabais: number;
};

function money(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return "—";
  return new Intl.NumberFormat("fr-CA", { style: "currency", currency: "CAD", minimumFractionDigits: 2 }).format(n);
}

function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso.length === 10 ? `${iso}T12:00:00` : iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("fr-CA", { day: "numeric", month: "short" });
}

const MOMENT: Record<PlanLigne["moment"], { label: string; cls: string }> = {
  maintenant: { label: "Acheter maintenant", cls: "bg-emerald-500/15 text-emerald-300 border-emerald-500/40" },
  attendre: { label: "Attendre", cls: "bg-amber-500/15 text-amber-300 border-amber-500/40" },
  sans_prix: { label: "Sans prix", cls: "bg-white/10 text-white/70 border-white/20" }
};

export function ProjectPlanAchat({ projectId, refreshKey }: { projectId: number; refreshKey: unknown }) {
  const [plan, setPlan] = useState<Plan | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState(true);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      setLoading(true);
      try {
        const r = await authedFetch(`/api/v1/projects/${projectId}/materiaux/plan`);
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const p = (await r.json()) as Plan;
        if (!cancelled) {
          setPlan(p);
          setError(null);
        }
      } catch (e) {
        if (!cancelled) setError(`Plan d'achat indisponible : ${(e as Error).message}`);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [projectId, refreshKey]);

  if (loading && !plan) {
    return (
      <div className="flex items-center gap-2 text-xs text-white/60">
        <Loader2 className="h-3.5 w-3.5 animate-spin" /> Calcul du plan d&apos;achat…
      </div>
    );
  }
  if (error) return <p className="text-xs text-rose-300">{error}</p>;
  if (!plan || plan.nb_lignes === 0) return null;

  const seul = plan.un_seul_magasin;

  return (
    <section className="rounded-xl border border-brand-800 bg-brand-900/60">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full flex-wrap items-center gap-2 px-4 py-3 text-left"
        aria-expanded={open}
      >
        {open ? <ChevronDown className="h-4 w-4 text-white/60" /> : <ChevronRight className="h-4 w-4 text-white/60" />}
        <ShoppingCart className="h-4 w-4 text-accent-500" />
        <span className="text-sm font-semibold text-white">Plan d&apos;achat — quand et où acheter</span>
        <span className="text-xs text-white/60">
          {plan.nb_maintenant} à acheter maintenant ({money(plan.total_maintenant)})
          {plan.nb_attendre > 0 ? ` · ${plan.nb_attendre} à attendre (${money(plan.total_attendre)})` : ""}
          {plan.nb_sans_prix > 0 ? ` · ${plan.nb_sans_prix} sans prix` : ""}
        </span>
      </button>

      {open ? (
        <div className="space-y-4 border-t border-brand-800 px-4 py-3">
          <div className="grid gap-2 sm:grid-cols-2">
            <div className="rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-sm">
              <div className="text-[11px] uppercase tracking-wider text-emerald-300">Meilleur prix par ligne</div>
              <div className="font-mono text-lg font-semibold text-white">{money(plan.total_meilleur)}</div>
              <div className="text-xs text-white/70">
                {plan.nb_magasins} magasin{plan.nb_magasins > 1 ? "s" : ""} :{" "}
                {plan.par_magasin.map((m) => `${m.magasin_name} ${money(m.total)} (${m.nb_lignes})`).join(" · ")}
              </div>
            </div>
            <div className="rounded-lg border border-brand-800 bg-brand-950/40 px-3 py-2 text-sm">
              <div className="text-[11px] uppercase tracking-wider text-white/60">Tout au même magasin</div>
              {seul ? (
                <>
                  <div className="font-mono text-lg font-semibold text-white">
                    {money(seul.total)} <span className="text-sm font-normal text-white/70">chez {seul.magasin_name}</span>
                  </div>
                  <div className="text-xs text-white/70">
                    {seul.nb_manquantes > 0
                      ? `ne couvre pas ${seul.nb_manquantes} ligne${seul.nb_manquantes > 1 ? "s" : ""} (sans prix chez ce magasin)`
                      : plan.economie_vs_un_seul > 0.005
                        ? `un seul déplacement, mais ${money(plan.economie_vs_un_seul)} de plus que le meilleur prix par ligne`
                        : "même prix que le meilleur prix par ligne : un seul déplacement suffit"}
                  </div>
                </>
              ) : (
                <div className="text-xs text-white/70">Aucun magasin n&apos;a de prix pour ces lignes.</div>
              )}
            </div>
          </div>

          {plan.economie_rabais > 0.005 ? (
            <p className="flex items-center gap-2 text-xs text-rose-300">
              <Tag className="h-3.5 w-3.5" />
              Rabais en cours : {money(plan.economie_rabais)} d&apos;économie vs prix régulier si tu achètes avant la fin des soldes.
            </p>
          ) : null}

          {plan.phases.map((ph) => (
            <div key={ph.phase_id ?? "none"} className="rounded-lg border border-brand-800">
              <div className="flex flex-wrap items-center gap-2 border-b border-brand-800 bg-brand-950/40 px-3 py-2 text-sm">
                <CalendarClock className="h-4 w-4 text-white/60" />
                <span className="font-semibold text-white">{ph.name}</span>
                {ph.start_date ? (
                  <span className="text-xs text-white/70">
                    {ph.jours_avant != null && ph.jours_avant < 0
                      ? `commencée le ${fmtDate(ph.start_date)}`
                      : ph.jours_avant === 0
                        ? "commence aujourd'hui"
                        : `dans ${ph.jours_avant} j (${fmtDate(ph.start_date)})`}
                    {ph.acheter_avant && (ph.jours_avant ?? 0) > 3 ? ` · à acheter avant le ${fmtDate(ph.acheter_avant)}` : ""}
                  </span>
                ) : (
                  <span className="text-xs text-white/50">sans date — pose la date de la phase pour un conseil « attendre »</span>
                )}
                <span className="ml-auto text-xs text-white/70">
                  maintenant {money(ph.total_maintenant)}
                  {ph.total_attendre > 0 ? ` · attendre ${money(ph.total_attendre)}` : ""}
                  {ph.nb_sans_prix > 0 ? ` · ${ph.nb_sans_prix} sans prix` : ""}
                </span>
              </div>
              <ul className="divide-y divide-brand-800">
                {ph.lignes.map((l) => (
                  <li key={l.ligne_id} className="flex flex-wrap items-start gap-2 px-3 py-2 text-sm">
                    <span className={`mt-0.5 rounded border px-1.5 py-0.5 text-[10px] font-semibold ${MOMENT[l.moment].cls}`}>
                      {MOMENT[l.moment].label}
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-x-2 text-white">
                        <span className="font-medium">{l.materiau_name}</span>
                        <span className="text-xs text-white/60">
                          × {l.quantity}
                          {l.unit ? ` ${l.unit}` : ""}
                        </span>
                        {l.unit_price != null ? (
                          <span className="font-mono text-xs text-white/80">
                            {money(l.unit_price)}
                            {l.magasin_name ? ` chez ${l.magasin_name}` : ""} = {money(l.total)}
                          </span>
                        ) : null}
                        {l.url ? (
                          <a
                            href={l.url}
                            target="_blank"
                            rel="noreferrer"
                            className="text-white/50 hover:text-white"
                            title="Page produit"
                          >
                            <ExternalLink className="h-3 w-3" />
                          </a>
                        ) : null}
                      </div>
                      <div className="text-xs text-white/70">{l.raison}</div>
                      {l.verdict_ia ? (
                        <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-[11px] text-white/70">
                          <span className={`rounded border px-1.5 py-0.5 text-[10px] font-semibold ${(VERDICT_IA[l.verdict_ia] || VERDICT_IA.neutre).cls}`}>
                            {(VERDICT_IA[l.verdict_ia] || VERDICT_IA.neutre).label}
                          </span>
                          {!l.raison.startsWith("Avis IA") && l.avis_ia ? <span>{l.avis_ia}</span> : null}
                          {l.prix_cible_ia != null && !l.raison.includes("Prix à viser") ? (
                            <span>Prix à viser : {money(l.prix_cible_ia)}</span>
                          ) : null}
                          {l.analyse_ia_at ? <span className="text-white/45">(analyse du {fmtDate(l.analyse_ia_at)})</span> : null}
                        </div>
                      ) : null}
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          ))}

          <p className="text-[11px] text-white/50">
            « Attendre » = prix du jour à plus de 5 % au-dessus du plus bas vu en 6 mois et phase à plus de 14 jours,
            ou avis « attendre » de l&apos;IA (elle relit 6 mois de relevés chaque semaine, la nuit : cycles de rabais,
            tendance, prix à viser). Rabais en cours ou phase imminente l&apos;emportent. L&apos;alerte quotidienne te
            prévient dès qu&apos;un article passe en rabais. Prix hors taxes.
          </p>
        </div>
      ) : null}
    </section>
  );
}
