"use client";

/**
 * Paramètres → Contrat de gestion.
 *
 * Éditeur du GABARIT PAR DÉFAUT du contrat de gestion immobilière —
 * s'applique à tous les immeubles. La personnalisation propre à un
 * immeuble (négociation) se fait dans l'onglet « Contrat de gestion »
 * de la fiche de l'immeuble.
 *
 * Édition réservée admin+ (le PUT backend renvoie 403 sinon).
 */

import { useCallback, useEffect, useState } from "react";
import { Check, FileSignature, Loader2 } from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { useAppLayout } from "../../layout";
import { authedFetch, hasMinRole } from "@/lib/auth";
import { useCurrentUser } from "@/hooks/use-current-user";

export default function ContratGestionSettingsPage() {
  const { onOpenSidebar } = useAppLayout();
  const { user: me } = useCurrentUser();
  const canEdit = hasMinRole(me, "admin");

  const [body, setBody] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await authedFetch("/api/v1/contrats-gestion/template");
      if (!res.ok) throw new Error();
      setBody(
        ((await res.json()) as { corps_markdown: string }).corps_markdown
      );
    } catch {
      setErr("Chargement du gabarit impossible.");
      setBody("");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function save() {
    if (body === null) return;
    setBusy(true);
    setMsg(null);
    setErr(null);
    try {
      const res = await authedFetch("/api/v1/contrats-gestion/template", {
        method: "PUT",
        body: JSON.stringify({ corps_markdown: body })
      });
      if (res.status === 403) {
        setErr("Réservé aux administrateurs.");
        return;
      }
      if (!res.ok) throw new Error();
      setMsg(
        "Gabarit par défaut enregistré. Les contrats déjà signés gardent leur version."
      );
    } catch {
      setErr("Enregistrement impossible.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <AppTopbar
        breadcrumbs={[
          { label: "Construction", href: "/app" },
          { label: "Paramètres", href: "/app/parametres" },
          { label: "Contrat de gestion" }
        ]}
        onOpenSidebar={onOpenSidebar}
      />

      <div className="p-4 pb-28 lg:p-6 lg:pb-28">
        <h1 className="flex items-center gap-2 text-2xl font-bold text-white">
          <FileSignature className="h-6 w-6 text-accent-500" />
          Contrat de gestion — modèle par défaut
        </h1>
        <p className="mt-1 max-w-2xl text-sm text-white/60">
          Ce texte est le modèle appliqué à <strong>tous les immeubles</strong>.
          Pour négocier des conditions différentes sur un immeuble précis,
          utilise « Personnaliser le texte pour cet immeuble » dans l&apos;onglet
          Contrat de gestion de la fiche de l&apos;immeuble. Les contrats déjà
          signés conservent leur version.
        </p>

        {err ? (
          <p className="mt-4 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">
            {err}
          </p>
        ) : null}
        {msg ? (
          <p className="mt-4 rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-300">
            {msg}
          </p>
        ) : null}

        <div className="mt-4 rounded-2xl border border-brand-800 bg-brand-900 p-5">
          <p className="text-xs text-white/50">
            Marqueurs disponibles (remplacés automatiquement par contrat) :{" "}
            <code className="text-white/70">
              {"{{COMPAGNIE}} {{SIEGE_SOCIAL}} {{REPRESENTANT}} {{TITRE}} {{IMMEUBLES}} {{DISTRICT}} {{COURRIEL}} {{LIEU}} {{DATE}}"}
            </code>
          </p>
          {body === null ? (
            <div className="flex items-center justify-center py-10 text-white/40">
              <Loader2 className="h-5 w-5 animate-spin" />
            </div>
          ) : (
            <textarea
              value={body}
              onChange={(e) => setBody(e.target.value)}
              rows={26}
              disabled={!canEdit}
              className="mt-3 w-full rounded-lg border border-brand-800 bg-brand-950 px-3 py-2 font-mono text-xs leading-relaxed text-white focus:border-accent-500 focus:outline-none disabled:opacity-60"
            />
          )}
          {!canEdit ? (
            <p className="mt-2 text-xs text-white/50">
              Lecture seule — l&apos;édition du modèle par défaut est réservée
              aux administrateurs.
            </p>
          ) : (
            <button
              type="button"
              onClick={() => void save()}
              disabled={busy || body === null}
              className="btn-accent btn-sm mt-4 disabled:opacity-50"
            >
              {busy ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Check className="h-4 w-4" />
              )}
              Enregistrer le modèle par défaut
            </button>
          )}
        </div>
      </div>
    </>
  );
}
