"use client";

import { useEffect, useState } from "react";
import { Code2, Loader2, Trello, Users } from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { Link } from "@/i18n/navigation";
import { authedFetch } from "@/lib/auth";
import { useDevlogLayout } from "./layout";

type Lead = { id: number; status: string };
type Client = { id: number; status: string };

const PIPELINE_LABEL: Record<string, string> = {
  nouveau: "Nouveau",
  contacte: "Contacté",
  rdv: "Rendez-vous",
  presentation: "Présentation",
  soumission: "Soumission",
  gagne: "Gagné",
  perdu: "Perdu"
};

export default function DevlogHomePage() {
  const { onOpenSidebar } = useDevlogLayout();
  const [leads, setLeads] = useState<Lead[]>([]);
  const [clients, setClients] = useState<Client[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [lr, cr] = await Promise.all([
          authedFetch("/api/v1/devlog/leads"),
          authedFetch("/api/v1/devlog/clients")
        ]);
        if (cancelled) return;
        if (lr.ok) setLeads(await lr.json());
        if (cr.ok) setClients(await cr.json());
      } catch {
        /* ignore — affiche 0 */
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const openLeads = leads.filter(
    (l) => l.status !== "gagne" && l.status !== "perdu"
  ).length;
  const wonLeads = leads.filter((l) => l.status === "gagne").length;
  const activeClients = clients.filter((c) => c.status === "active").length;

  const byStatus = (s: string) => leads.filter((l) => l.status === s).length;

  return (
    <div className="min-h-screen bg-brand-950">
      <AppTopbar
        breadcrumbs={[{ label: "Développement logiciel" }]}
        onOpenSidebar={onOpenSidebar}
      />

      <div className="mx-auto max-w-5xl px-4 py-6 lg:px-6">
        <header className="flex items-center gap-3">
          <span className="flex h-12 w-12 items-center justify-center rounded-xl bg-blue-500/15 text-blue-400">
            <Code2 className="h-6 w-6" />
          </span>
          <div>
            <h1 className="text-xl font-bold text-white">
              Pôle Développement logiciel
            </h1>
            <p className="text-sm text-white/60">
              Pipeline du closer, clients et projets de développement.
            </p>
          </div>
        </header>

        {loading ? (
          <div className="mt-10 flex justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-blue-500" />
          </div>
        ) : (
          <>
            <div className="mt-6 grid gap-3 sm:grid-cols-3">
              <StatCard label="Leads actifs" value={openLeads} />
              <StatCard label="Leads gagnés" value={wonLeads} />
              <StatCard label="Clients actifs" value={activeClients} />
            </div>

            <div className="mt-6 grid gap-3 sm:grid-cols-2">
              <Link
                href={"/dev-logiciel/leads" as any}
                className="group flex items-center gap-4 rounded-2xl border border-brand-800 bg-brand-900 p-5 transition hover:border-blue-500 hover:bg-brand-800"
              >
                <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-blue-500/15 text-blue-400 group-hover:bg-blue-500 group-hover:text-white">
                  <Trello className="h-5 w-5" />
                </span>
                <div>
                  <span className="block font-bold text-white">
                    Pipeline (leads)
                  </span>
                  <span className="text-xs text-white/60">
                    Suivi kanban du closer.
                  </span>
                </div>
              </Link>
              <Link
                href={"/dev-logiciel/clients" as any}
                className="group flex items-center gap-4 rounded-2xl border border-brand-800 bg-brand-900 p-5 transition hover:border-blue-500 hover:bg-brand-800"
              >
                <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-blue-500/15 text-blue-400 group-hover:bg-blue-500 group-hover:text-white">
                  <Users className="h-5 w-5" />
                </span>
                <div>
                  <span className="block font-bold text-white">Clients</span>
                  <span className="text-xs text-white/60">
                    Les boîtes pour qui on développe.
                  </span>
                </div>
              </Link>
            </div>

            <div className="mt-6 rounded-2xl border border-brand-800 bg-brand-900 p-5">
              <h2 className="text-sm font-semibold text-white">
                Répartition du pipeline
              </h2>
              <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
                {Object.keys(PIPELINE_LABEL).map((s) => (
                  <div
                    key={s}
                    className="rounded-lg border border-brand-800 bg-brand-950 px-3 py-2"
                  >
                    <p className="text-[11px] uppercase tracking-wide text-white/50">
                      {PIPELINE_LABEL[s]}
                    </p>
                    <p className="text-lg font-bold text-white">
                      {byStatus(s)}
                    </p>
                  </div>
                ))}
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function StatCard({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-2xl border border-brand-800 bg-brand-900 p-5">
      <p className="text-xs uppercase tracking-wide text-white/50">{label}</p>
      <p className="mt-1 text-3xl font-bold text-white">{value}</p>
    </div>
  );
}
