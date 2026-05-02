"use client";

import { useEffect, useMemo, useState } from "react";
import {
  ArrowRight,
  CheckCircle2,
  Loader2,
  Sparkles,
  Target
} from "lucide-react";

import { Link } from "@/i18n/navigation";
import { authedFetch } from "@/lib/auth";
import { QGTopbar, useEntreprisesLayout } from "../layout";

type Entreprise = {
  id: number;
  name: string;
  color_accent: string;
};

type Vision = {
  id: number;
  entreprise_id: number;
  horizon_label: string;
  horizon_start: string;
  horizon_end: string;
  title: string;
  narrative: string;
  objectives: string[];
  key_actions: string[];
  generated_by_ai: boolean;
  approved_at: string | null;
  created_at: string;
  updated_at: string;
};

const HORIZONS: { key: string; label: string; days: number }[] = [
  { key: "7j", label: "7 jours", days: 7 },
  { key: "30j", label: "30 jours", days: 30 },
  { key: "90j", label: "90 jours", days: 90 },
  { key: "12m", label: "12 mois", days: 365 }
];

export default function VisionPage() {
  const { entreprises: layoutEnts } = useEntreprisesLayout();
  const [entreprises, setEntreprises] = useState<Entreprise[]>([]);
  const [selectedEnt, setSelectedEnt] = useState<number | null>(null);
  const [visions, setVisions] = useState<Vision[]>([]);
  const [loading, setLoading] = useState(true);
  const [generatingHorizon, setGeneratingHorizon] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Charge la liste des entreprises (utilisée pour le sélecteur).
  useEffect(() => {
    void (async () => {
      try {
        const r = await authedFetch("/api/v1/entreprises");
        if (r.ok) {
          const data = (await r.json()) as Entreprise[];
          setEntreprises(data);
          if (!selectedEnt && data.length > 0) {
            setSelectedEnt(data[0].id);
          }
        }
      } catch {
        /* silent */
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Charge les visions de l'entreprise sélectionnée
  useEffect(() => {
    if (!selectedEnt) {
      setVisions([]);
      setLoading(false);
      return;
    }
    let cancelled = false;
    void (async () => {
      setLoading(true);
      setError(null);
      try {
        const r = await authedFetch(
          `/api/v1/entreprises/${selectedEnt}/visions`
        );
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        if (!cancelled) {
          setVisions((await r.json()) as Vision[]);
        }
      } catch (err) {
        if (!cancelled) setError((err as Error).message);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [selectedEnt]);

  async function generate(horizon: string, force: boolean = false) {
    if (!selectedEnt) return;
    setGeneratingHorizon(horizon);
    setError(null);
    try {
      const r = await authedFetch(
        `/api/v1/entreprises/${selectedEnt}/visions/generate`,
        {
          method: "POST",
          body: JSON.stringify({ horizon, force })
        }
      );
      if (!r.ok) {
        const t = await r.text();
        throw new Error(t.slice(0, 200) || `HTTP ${r.status}`);
      }
      const v = (await r.json()) as Vision;
      // Remplace ou ajoute
      setVisions((prev) => {
        const without = prev.filter((p) => p.horizon_label !== v.horizon_label);
        return [v, ...without];
      });
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setGeneratingHorizon(null);
    }
  }

  const visionsByLabel = useMemo(() => {
    const m = new Map<string, Vision>();
    for (const v of visions) {
      // garde la plus récente par label
      const existing = m.get(v.horizon_label);
      if (!existing || v.created_at > existing.created_at) {
        m.set(v.horizon_label, v);
      }
    }
    return m;
  }, [visions]);

  const ents = entreprises.length > 0 ? entreprises : layoutEnts;

  return (
    <>
      <QGTopbar
        greeting={
          <>
            Vision{" "}
            <span
              className="italic"
              style={{
                color: "#d4ff3a",
                fontFamily: "var(--font-fraunces, Georgia, serif)"
              }}
            >
              stratégique
            </span>
          </>
        }
        subtitle="HORIZONS DE PLANIFICATION · 7J · 30J · 90J · 12M"
      />

      <div className="px-5 py-6 lg:px-8">
        {/* Sélecteur d'entreprise */}
        <div className="mb-6 flex flex-wrap items-center gap-3">
          <span className="text-[11px] uppercase tracking-wider text-[#66666e]">
            Entreprise
          </span>
          <select
            value={selectedEnt ?? ""}
            onChange={(e) =>
              setSelectedEnt(e.target.value ? Number(e.target.value) : null)
            }
            className="rounded-md px-3 py-1.5 text-[13px] focus:outline-none"
            style={{
              backgroundColor: "#15151a",
              color: "#f5f5f7",
              border: "1px solid #25252d"
            }}
          >
            {ents.length === 0 ? (
              <option value="">Aucune entreprise</option>
            ) : null}
            {ents.map((e) => (
              <option
                key={e.id}
                value={e.id}
                className="bg-[#15151a]"
              >
                {e.name}
              </option>
            ))}
          </select>
        </div>

        {error ? (
          <p className="mb-4 rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">
            {error}
          </p>
        ) : null}

        {/* Grille des horizons */}
        <div className="grid grid-cols-1 gap-5 lg:grid-cols-2 xl:grid-cols-4">
          {HORIZONS.map((h) => {
            const v = visionsByLabel.get(h.label) || null;
            const generating = generatingHorizon === h.key;
            return (
              <article
                key={h.key}
                className="flex flex-col rounded-xl"
                style={{
                  backgroundColor: "#15151a",
                  border: "1px solid #25252d"
                }}
              >
                <header
                  className="flex items-center justify-between px-4 py-3"
                  style={{ borderBottom: "1px solid #25252d" }}
                >
                  <span className="flex items-center gap-2">
                    <span
                      className="h-1.5 w-1.5 rounded-full"
                      style={{ backgroundColor: "#d4ff3a" }}
                    />
                    <h3
                      className="text-[14px] font-bold text-[#f5f5f7]"
                      style={{
                        fontFamily: "var(--font-fraunces, Georgia, serif)"
                      }}
                    >
                      {h.label}
                    </h3>
                  </span>
                  <span
                    className="text-[10px] uppercase tracking-wider text-[#66666e]"
                    style={{ fontFamily: "var(--font-mono, monospace)" }}
                  >
                    +{h.days}j
                  </span>
                </header>

                {loading ? (
                  <div className="flex flex-1 items-center justify-center px-4 py-12">
                    <Loader2 className="h-4 w-4 animate-spin text-[#66666e]" />
                  </div>
                ) : v ? (
                  <VisionCard v={v} />
                ) : (
                  <div className="flex flex-1 flex-col items-center justify-center gap-3 px-4 py-10 text-center">
                    <Target className="h-6 w-6 text-[#35353f]" />
                    <p className="text-[12px] text-[#66666e]">
                      Aucune vision pour cet horizon.
                    </p>
                  </div>
                )}

                <footer className="px-4 py-3" style={{ borderTop: "1px solid #25252d" }}>
                  <button
                    type="button"
                    onClick={() => generate(h.key, !!v)}
                    disabled={generating || !selectedEnt}
                    className="inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-[11px] font-bold transition disabled:opacity-50"
                    style={{
                      backgroundColor: v
                        ? "transparent"
                        : "rgba(212,255,58,0.12)",
                      border: v
                        ? "1px solid #25252d"
                        : "1px solid rgba(212,255,58,0.45)",
                      color: v ? "#a0a0a8" : "#d4ff3a"
                    }}
                  >
                    {generating ? (
                      <>
                        <Loader2 className="h-3 w-3 animate-spin" />
                        Génération…
                      </>
                    ) : (
                      <>
                        <Sparkles className="h-3 w-3" />
                        {v ? "Régénérer" : "Générer la vision"}
                      </>
                    )}
                  </button>
                </footer>
              </article>
            );
          })}
        </div>
      </div>
    </>
  );
}

function VisionCard({ v }: { v: Vision }) {
  return (
    <div className="flex flex-1 flex-col gap-3 p-4">
      <h4
        className="text-[14px] font-bold leading-snug text-[#f5f5f7]"
        style={{ fontFamily: "var(--font-fraunces, Georgia, serif)" }}
      >
        {v.title}
      </h4>
      <p className="text-[12px] leading-relaxed text-[#a0a0a8]">
        {v.narrative}
      </p>

      {v.objectives.length > 0 ? (
        <section className="mt-1">
          <p className="mb-1.5 text-[10px] font-bold uppercase tracking-wider text-[#66666e]">
            Objectifs
          </p>
          <ul className="space-y-1">
            {v.objectives.map((o, i) => (
              <li
                key={i}
                className="flex items-start gap-2 text-[11px] leading-snug text-[#f5f5f7]/85"
              >
                <CheckCircle2
                  className="mt-0.5 h-2.5 w-2.5 flex-shrink-0"
                  style={{ color: "#d4ff3a" }}
                />
                <span>{o}</span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {v.key_actions.length > 0 ? (
        <section className="mt-2">
          <p className="mb-1.5 text-[10px] font-bold uppercase tracking-wider text-[#66666e]">
            Actions clés
          </p>
          <ul className="space-y-1">
            {v.key_actions.map((a, i) => (
              <li
                key={i}
                className="flex items-start gap-2 text-[11px] leading-snug text-[#a0a0a8]"
              >
                <ArrowRight className="mt-0.5 h-2.5 w-2.5 flex-shrink-0 text-[#66666e]" />
                <span>{a}</span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <div className="mt-auto pt-2 text-[10px] text-[#66666e]">
        Générée{" "}
        {new Date(v.created_at).toLocaleDateString("fr-CA", {
          day: "numeric",
          month: "short"
        })}
        {" · valide jusqu'au "}
        {v.horizon_end}
      </div>
    </div>
  );
}
