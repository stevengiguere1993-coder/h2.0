"use client";

import { useCallback, useEffect, useState } from "react";
import { Loader2, MessageSquarePlus, Trash2 } from "lucide-react";

import { authedFetch } from "@/lib/auth";

/**
 * Consignes à Kratos (2026-11-13) — Steven : « que les tableaux, les
 * résumés et les bilans s'ajustent à travers le temps selon mes
 * différentes demandes de modifications ». Chaque demande est RETENUE
 * et redonnée à l'IA à chaque résumé, tableau et réponse suivants.
 *
 *   - <DemanderModification> : la boîte « demander une modification »,
 *     posée là où on regarde le résultat (tableau, résumé).
 *   - <RencontresConsignes>  : la liste, pour désactiver ou retirer.
 */

export type Portee = "tout" | "resumes" | "dossiers";

type Consigne = {
  id: number;
  portee: Portee;
  texte: string;
  actif: boolean;
  created_at: string | null;
};

const PORTEES: { cle: Portee; libelle: string }[] = [
  { cle: "tout", libelle: "Partout" },
  { cle: "resumes", libelle: "Résumés et rapports" },
  { cle: "dossiers", libelle: "Tableau des dossiers" }
];

function libellePortee(p: string): string {
  return PORTEES.find((x) => x.cle === p)?.libelle || p;
}

async function lireErreur(r: Response): Promise<string> {
  try {
    const j = (await r.json()) as { detail?: unknown };
    if (typeof j.detail === "string") return j.detail;
  } catch {
    /* corps non JSON */
  }
  return `HTTP ${r.status}`;
}

export function DemanderModification({
  portee,
  exemple,
  libelleAppliquer,
  onAppliquer
}: {
  portee: Portee;
  exemple: string;
  /** Ce que fait le bouton après avoir retenu la consigne. */
  libelleAppliquer: string;
  /** Réapplique tout de suite (réanalyse, nouveau résumé…). */
  onAppliquer: () => Promise<void>;
}) {
  const [texte, setTexte] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function envoyer() {
    const t = texte.trim();
    if (t.length < 3) return;
    setBusy(true);
    setError(null);
    setMsg(null);
    try {
      const r = await authedFetch("/api/v1/rencontres/consignes", {
        method: "POST",
        body: JSON.stringify({ texte: t, portee })
      });
      if (!r.ok) throw new Error(await lireErreur(r));
      setTexte("");
      setMsg("Consigne retenue. Kratos l'applique maintenant…");
      await onAppliquer();
      setMsg(
        "Consigne retenue et appliquée. Elle servira aussi pour les prochaines rencontres."
      );
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
      className="rounded-xl border p-3"
      style={{
        borderColor: "var(--qg-border-soft)",
        backgroundColor: "var(--qg-bg-alt, transparent)"
      }}
    >
      <div className="flex items-center gap-2">
        <MessageSquarePlus className="h-4 w-4 text-accent-500" />
        <p className="text-sm font-semibold" style={{ color: "var(--qg-text)" }}>
          Demander une modification à Kratos
        </p>
      </div>
      <p className="mt-1 text-sm" style={{ color: "var(--qg-text-muted)" }}>
        Dis ce que tu veux changer. Kratos le retient et l&apos;applique
        aussi les prochaines fois.
      </p>
      <form
        className="mt-2 flex flex-col gap-2 sm:flex-row"
        onSubmit={(e) => {
          e.preventDefault();
          void envoyer();
        }}
      >
        <input
          className="input flex-1 text-base"
          value={texte}
          onChange={(e) => setTexte(e.target.value)}
          placeholder={exemple}
          maxLength={2000}
          aria-label="Modification demandée à Kratos"
        />
        <button
          type="submit"
          disabled={busy || texte.trim().length < 3}
          className="btn-accent inline-flex items-center justify-center gap-1.5 text-sm disabled:opacity-50"
        >
          {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
          {busy ? "En cours…" : libelleAppliquer}
        </button>
      </form>
      {msg ? (
        <p className="mt-2 text-sm" style={{ color: "var(--qg-text)" }} role="status">
          {msg}
        </p>
      ) : null}
      {error ? (
        <p className="mt-2 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">
          {error}
        </p>
      ) : null}
    </div>
  );
}

export function RencontresConsignes() {
  const [rows, setRows] = useState<Consigne[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [texte, setTexte] = useState("");
  const [portee, setPortee] = useState<Portee>("tout");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await authedFetch("/api/v1/rencontres/consignes");
      if (!r.ok) throw new Error(await lireErreur(r));
      const j = (await r.json()) as { consignes: Consigne[] };
      setRows(j.consignes);
      setError(null);
    } catch (e) {
      setError(`Chargement échoué : ${(e as Error).message}`);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function ajouter() {
    const t = texte.trim();
    if (t.length < 3) return;
    setBusy(true);
    try {
      const r = await authedFetch("/api/v1/rencontres/consignes", {
        method: "POST",
        body: JSON.stringify({ texte: t, portee })
      });
      if (!r.ok) throw new Error(await lireErreur(r));
      setTexte("");
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function basculer(c: Consigne) {
    const r = await authedFetch(`/api/v1/rencontres/consignes/${c.id}`, {
      method: "PATCH",
      body: JSON.stringify({ actif: !c.actif })
    });
    if (r.ok) await load();
    else setError(await lireErreur(r));
  }

  async function retirer(c: Consigne) {
    const r = await authedFetch(`/api/v1/rencontres/consignes/${c.id}`, {
      method: "DELETE"
    });
    if (r.ok) setRows((xs) => xs.filter((x) => x.id !== c.id));
    else setError(await lireErreur(r));
  }

  return (
    <div className="space-y-4">
      <section
        className="rounded-2xl border p-4"
        style={{
          borderColor: "var(--qg-border)",
          backgroundColor: "var(--qg-card-bg)"
        }}
      >
        <h2 className="text-base font-semibold" style={{ color: "var(--qg-text)" }}>
          Consignes à Kratos
        </h2>
        <p className="mt-1 text-sm" style={{ color: "var(--qg-text-muted)" }}>
          Tes demandes de modification. Kratos les relit avant chaque
          résumé, chaque mise à jour du tableau des dossiers et chaque
          réponse. La plus récente gagne si deux se contredisent.
        </p>
        <form
          className="mt-3 flex flex-col gap-2 lg:flex-row"
          onSubmit={(e) => {
            e.preventDefault();
            void ajouter();
          }}
        >
          <input
            className="input flex-1 text-base"
            value={texte}
            onChange={(e) => setTexte(e.target.value)}
            placeholder="ex. Regroupe les dossiers par immeuble, résumés en dix lignes au plus"
            maxLength={2000}
            aria-label="Nouvelle consigne"
          />
          <select
            className="input text-base lg:w-56"
            value={portee}
            onChange={(e) => setPortee(e.target.value as Portee)}
            aria-label="Où la consigne s'applique"
          >
            {PORTEES.map((p) => (
              <option key={p.cle} value={p.cle}>
                {p.libelle}
              </option>
            ))}
          </select>
          <button
            type="submit"
            disabled={busy || texte.trim().length < 3}
            className="btn-accent inline-flex items-center justify-center gap-1.5 text-sm disabled:opacity-50"
          >
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
            Ajouter
          </button>
        </form>
        {error ? (
          <p className="mt-2 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">
            {error}
          </p>
        ) : null}
      </section>

      {loading ? (
        <div className="flex justify-center py-8">
          <Loader2 className="h-6 w-6 animate-spin text-accent-500" />
        </div>
      ) : rows.length === 0 ? (
        <p className="text-sm" style={{ color: "var(--qg-text-muted)" }}>
          Aucune consigne pour l&apos;instant. Elles s&apos;ajoutent ici, ou
          depuis « Demander une modification » sous un résumé ou sous le
          tableau des dossiers.
        </p>
      ) : (
        <ul className="space-y-2">
          {rows.map((c) => (
            <li
              key={c.id}
              className="flex flex-col gap-2 rounded-xl border p-3 sm:flex-row sm:items-center"
              style={{
                borderColor: "var(--qg-border)",
                backgroundColor: "var(--qg-card-bg)"
              }}
            >
              <div className="min-w-0 flex-1">
                <p
                  className="text-sm"
                  style={{
                    color: c.actif ? "var(--qg-text)" : "var(--qg-text-muted)",
                    textDecoration: c.actif ? undefined : "line-through"
                  }}
                >
                  {c.texte}
                </p>
                <p className="mt-1 text-xs" style={{ color: "var(--qg-text-muted)" }}>
                  {libellePortee(c.portee)}
                  {c.created_at ? ` · ${c.created_at.slice(0, 10)}` : ""}
                  {c.actif ? "" : " · désactivée"}
                </p>
              </div>
              <div className="flex shrink-0 items-center gap-2">
                <button
                  type="button"
                  onClick={() => void basculer(c)}
                  className="btn-secondary btn-sm gap-1.5"
                >
                  {c.actif ? "Désactiver" : "Réactiver"}
                </button>
                <button
                  type="button"
                  onClick={() => void retirer(c)}
                  className="btn-ghost btn-xs"
                  aria-label="Supprimer la consigne"
                  title="Supprimer la consigne"
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
