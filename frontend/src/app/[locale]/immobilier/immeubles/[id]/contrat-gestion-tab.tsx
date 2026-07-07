"use client";

/**
 * Onglet « Contrat de gestion » de la fiche immeuble.
 *
 * Permet de créer une convention de gestion (auto-remplie depuis
 * l'entreprise détentrice + l'immeuble), d'éditer les champs, de
 * l'envoyer pour signature en ligne au Mandant, de suivre l'ouverture
 * et la signature, et de récupérer le PDF signé. Le gabarit par défaut
 * du contrat est éditable en bas (réservé admin+).
 *
 * Backend : PR « Contrat de gestion — backend » (endpoints
 * /api/v1/contrats-gestion + /public/contrats-gestion).
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { marked } from "marked";
import {
  Check,
  ChevronDown,
  Copy,
  Eye,
  FileSignature,
  Loader2,
  Mail,
  Plus,
  Send,
  Settings2,
  Trash2
} from "lucide-react";

import { authedFetch } from "@/lib/auth";

type Contrat = {
  id: number;
  immeuble_id: number;
  entreprise_id: number | null;
  compagnie: string | null;
  siege_social: string | null;
  representant_nom: string | null;
  representant_titre: string | null;
  immeubles_adresses: string | null;
  district_judiciaire: string | null;
  mandant_courriel: string | null;
  lieu_signature: string | null;
  caution_requise: boolean;
  caution_nom: string | null;
  status: string;
  sent_at: string | null;
  opened_at: string | null;
  open_count: number;
  signed_at: string | null;
  signed_name: string | null;
  has_signed_pdf: boolean;
  sign_url: string | null;
  body_markdown?: string;
};

function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("fr-CA", {
    day: "numeric",
    month: "short",
    year: "numeric"
  });
}

function StatusBadge({ c }: { c: Contrat }) {
  const map: Record<string, { label: string; cls: string }> = {
    brouillon: { label: "Brouillon", cls: "bg-white/10 text-white/70" },
    envoye: { label: "Envoyé", cls: "bg-amber-500/15 text-amber-300" },
    signe: { label: "Signé", cls: "bg-emerald-500/15 text-emerald-300" }
  };
  const s = map[c.status] || map.brouillon;
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold ${s.cls}`}
    >
      {c.status === "signe" ? <Check className="h-3 w-3" /> : null}
      {s.label}
    </span>
  );
}

const FIELD_CLS =
  "mt-1 w-full rounded-lg border border-brand-800 bg-brand-950 px-3 py-2 text-sm text-white placeholder:text-white/30 focus:border-sky-500 focus:outline-none focus:ring-1 focus:ring-sky-500/40";
const LABEL_CLS =
  "text-[11px] font-semibold uppercase tracking-wider text-white/50";

export function ContratGestionTab({ immeubleId }: { immeubleId: number }) {
  const [list, setList] = useState<Contrat[] | null>(null);
  const [selected, setSelected] = useState<Contrat | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [showTemplate, setShowTemplate] = useState(false);
  const [showPreview, setShowPreview] = useState(false);

  const loadList = useCallback(async () => {
    setError(null);
    try {
      const res = await authedFetch(
        `/api/v1/contrats-gestion?immeuble_id=${immeubleId}`
      );
      if (!res.ok) throw new Error(`http_${res.status}`);
      setList((await res.json()) as Contrat[]);
    } catch {
      setError("Chargement des contrats impossible.");
      setList([]);
    }
  }, [immeubleId]);

  useEffect(() => {
    void loadList();
  }, [loadList]);

  function flash(msg: string) {
    setToast(msg);
    setTimeout(() => setToast(null), 2500);
  }

  async function createDraft() {
    setBusy(true);
    setError(null);
    try {
      const res = await authedFetch("/api/v1/contrats-gestion", {
        method: "POST",
        body: JSON.stringify({ immeuble_id: immeubleId })
      });
      if (!res.ok) throw new Error(`http_${res.status}`);
      const created = (await res.json()) as Contrat;
      setSelected(created);
      setShowPreview(false);
      await loadList();
    } catch {
      setError("Création impossible.");
    } finally {
      setBusy(false);
    }
  }

  async function openContract(id: number) {
    setBusy(true);
    setError(null);
    try {
      const res = await authedFetch(`/api/v1/contrats-gestion/${id}`);
      if (!res.ok) throw new Error(`http_${res.status}`);
      setSelected((await res.json()) as Contrat);
      setShowPreview(false);
    } catch {
      setError("Ouverture impossible.");
    } finally {
      setBusy(false);
    }
  }

  async function saveContract() {
    if (!selected) return;
    setBusy(true);
    setError(null);
    try {
      const payload = {
        compagnie: selected.compagnie,
        siege_social: selected.siege_social,
        representant_nom: selected.representant_nom,
        representant_titre: selected.representant_titre,
        immeubles_adresses: selected.immeubles_adresses,
        district_judiciaire: selected.district_judiciaire,
        mandant_courriel: selected.mandant_courriel,
        lieu_signature: selected.lieu_signature,
        caution_requise: selected.caution_requise,
        caution_nom: selected.caution_nom
      };
      const res = await authedFetch(
        `/api/v1/contrats-gestion/${selected.id}`,
        { method: "PATCH", body: JSON.stringify(payload) }
      );
      if (!res.ok) throw new Error(`http_${res.status}`);
      setSelected((await res.json()) as Contrat);
      await loadList();
      flash("Enregistré.");
    } catch {
      setError("Enregistrement impossible.");
    } finally {
      setBusy(false);
    }
  }

  async function sendContract() {
    if (!selected) return;
    if (!(selected.mandant_courriel || "").trim()) {
      setError("Renseignez le courriel du Mandant avant l'envoi.");
      return;
    }
    if (
      !window.confirm(
        `Envoyer la convention à ${selected.mandant_courriel} pour signature ?`
      )
    )
      return;
    setBusy(true);
    setError(null);
    try {
      // On enregistre d'abord les derniers champs, puis on envoie.
      await saveContract();
      const res = await authedFetch(
        `/api/v1/contrats-gestion/${selected.id}/send`,
        { method: "POST" }
      );
      if (!res.ok) {
        let msg = `Envoi impossible (${res.status}).`;
        try {
          const j = await res.json();
          if (j?.detail) msg = j.detail;
        } catch {
          /* ignore */
        }
        throw new Error(msg);
      }
      const updated = (await res.json()) as Contrat;
      setSelected((s) => (s ? { ...s, ...updated } : updated));
      await loadList();
      flash("Convention envoyée pour signature.");
    } catch (e) {
      setError((e as Error).message || "Envoi impossible.");
    } finally {
      setBusy(false);
    }
  }

  async function deleteContract(id: number) {
    if (!window.confirm("Supprimer ce contrat ?")) return;
    setBusy(true);
    try {
      const res = await authedFetch(`/api/v1/contrats-gestion/${id}`, {
        method: "DELETE"
      });
      if (!res.ok && res.status !== 204) throw new Error(`http_${res.status}`);
      if (selected?.id === id) setSelected(null);
      await loadList();
    } catch {
      setError("Suppression impossible.");
    } finally {
      setBusy(false);
    }
  }

  async function openPdf(path: string) {
    try {
      const res = await authedFetch(path);
      if (!res.ok) throw new Error();
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      window.open(url, "_blank");
      setTimeout(() => URL.revokeObjectURL(url), 60000);
    } catch {
      setError("Ouverture du PDF impossible.");
    }
  }

  function copyLink(url: string | null) {
    if (!url) return;
    void navigator.clipboard.writeText(url);
    flash("Lien copié.");
  }

  const previewHtml = useMemo(() => {
    if (!selected?.body_markdown) return "";
    marked.setOptions({ gfm: true, breaks: false, async: false });
    return marked.parse(selected.body_markdown) as string;
  }, [selected?.body_markdown]);

  function upd<K extends keyof Contrat>(key: K, value: Contrat[K]) {
    setSelected((s) => (s ? { ...s, [key]: value } : s));
  }

  // ─── Rendu ───────────────────────────────────────────────────────

  if (selected) {
    const signed = selected.status === "signe";
    return (
      <div className="space-y-5">
        <div className="flex items-center justify-between">
          <button
            type="button"
            onClick={() => setSelected(null)}
            className="text-sm text-white/60 hover:text-white"
          >
            ← Retour à la liste
          </button>
          <StatusBadge c={selected} />
        </div>

        {error ? (
          <p className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-sm text-rose-200">
            {error}
          </p>
        ) : null}
        {toast ? (
          <p className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-200">
            {toast}
          </p>
        ) : null}

        {signed ? (
          <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 p-4 text-sm text-emerald-100">
            Signé par <strong>{selected.signed_name}</strong> le{" "}
            {fmtDate(selected.signed_at)}.
          </div>
        ) : selected.status === "envoye" ? (
          <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-4 text-sm text-amber-100">
            Envoyé le {fmtDate(selected.sent_at)} à{" "}
            <strong>{selected.mandant_courriel}</strong>.{" "}
            {selected.open_count > 0
              ? `Ouvert ${selected.open_count} fois (dernière : ${fmtDate(
                  selected.opened_at
                )}).`
              : "Pas encore ouvert."}
          </div>
        ) : null}

        {/* Formulaire des champs variables */}
        <fieldset
          disabled={signed || busy}
          className="grid grid-cols-1 gap-4 sm:grid-cols-2"
        >
          <label className="sm:col-span-2">
            <span className={LABEL_CLS}>Compagnie détentrice (Mandant)</span>
            <input
              className={FIELD_CLS}
              value={selected.compagnie || ""}
              onChange={(e) => upd("compagnie", e.target.value)}
              placeholder="9999-8888 Québec inc."
            />
          </label>
          <label>
            <span className={LABEL_CLS}>Représentant</span>
            <input
              className={FIELD_CLS}
              value={selected.representant_nom || ""}
              onChange={(e) => upd("representant_nom", e.target.value)}
              placeholder="Prénom Nom"
            />
          </label>
          <label>
            <span className={LABEL_CLS}>Titre (ex. président)</span>
            <input
              className={FIELD_CLS}
              value={selected.representant_titre || ""}
              onChange={(e) => upd("representant_titre", e.target.value)}
              placeholder="président"
            />
          </label>
          <label className="sm:col-span-2">
            <span className={LABEL_CLS}>Adresse du siège social</span>
            <input
              className={FIELD_CLS}
              value={selected.siege_social || ""}
              onChange={(e) => upd("siege_social", e.target.value)}
              placeholder="123 Rue Exemple, Ville QC H0H 0H0"
            />
          </label>
          <label>
            <span className={LABEL_CLS}>Courriel du Mandant</span>
            <input
              type="email"
              className={FIELD_CLS}
              value={selected.mandant_courriel || ""}
              onChange={(e) => upd("mandant_courriel", e.target.value)}
              placeholder="proprio@example.com"
            />
          </label>
          <label>
            <span className={LABEL_CLS}>District judiciaire</span>
            <input
              className={FIELD_CLS}
              value={selected.district_judiciaire || ""}
              onChange={(e) => upd("district_judiciaire", e.target.value)}
              placeholder="Montréal"
            />
          </label>
          <label className="sm:col-span-2">
            <span className={LABEL_CLS}>
              Adresses des immeubles (une par ligne)
            </span>
            <textarea
              rows={3}
              className={FIELD_CLS}
              value={selected.immeubles_adresses || ""}
              onChange={(e) => upd("immeubles_adresses", e.target.value)}
              placeholder={"123 Rue A, Ville QC\n456 Rue B, Ville QC"}
            />
          </label>
          <label>
            <span className={LABEL_CLS}>Lieu de signature</span>
            <input
              className={FIELD_CLS}
              value={selected.lieu_signature || ""}
              onChange={(e) => upd("lieu_signature", e.target.value)}
              placeholder="Montréal"
            />
          </label>
          <div className="flex flex-col justify-end">
            <label className="flex cursor-pointer items-center gap-2 rounded-lg border border-brand-800 bg-brand-950 px-3 py-2">
              <input
                type="checkbox"
                checked={selected.caution_requise}
                onChange={(e) => upd("caution_requise", e.target.checked)}
                className="h-4 w-4 rounded border-brand-700 text-sky-500"
              />
              <span className="text-sm text-white/80">
                Exiger une caution solidaire
              </span>
            </label>
          </div>
        </fieldset>

        {/* Aperçu du contrat (texte rendu) */}
        <div className="rounded-lg border border-brand-800">
          <button
            type="button"
            onClick={() => setShowPreview((v) => !v)}
            className="flex w-full items-center justify-between px-4 py-2.5 text-sm font-medium text-white/80"
          >
            <span className="inline-flex items-center gap-2">
              <Eye className="h-4 w-4" /> Aperçu du contrat
            </span>
            <ChevronDown
              className={`h-4 w-4 transition ${showPreview ? "rotate-180" : ""}`}
            />
          </button>
          {showPreview ? (
            <div
              className="cg-prose max-h-[420px] overflow-y-auto border-t border-brand-800 bg-white px-5 py-4 text-sm text-slate-900"
              dangerouslySetInnerHTML={{ __html: previewHtml }}
            />
          ) : null}
        </div>

        {/* Actions */}
        <div className="flex flex-wrap items-center gap-2">
          {!signed ? (
            <button
              type="button"
              onClick={() => void saveContract()}
              disabled={busy}
              className="inline-flex items-center gap-2 rounded-lg bg-sky-600 px-4 py-2 text-sm font-semibold text-white hover:bg-sky-500 disabled:opacity-50"
            >
              {busy ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Check className="h-4 w-4" />
              )}
              Enregistrer
            </button>
          ) : null}
          <button
            type="button"
            onClick={() => void openPdf(`/api/v1/contrats-gestion/${selected.id}/pdf`)}
            className="inline-flex items-center gap-2 rounded-lg border border-brand-800 px-4 py-2 text-sm font-medium text-white/80 hover:text-white"
          >
            <Eye className="h-4 w-4" /> Aperçu PDF
          </button>
          {!signed ? (
            <button
              type="button"
              onClick={() => void sendContract()}
              disabled={busy}
              className="inline-flex items-center gap-2 rounded-lg bg-emerald-600 px-4 py-2 text-sm font-semibold text-white hover:bg-emerald-500 disabled:opacity-50"
            >
              <Send className="h-4 w-4" />
              {selected.status === "envoye" ? "Renvoyer" : "Envoyer pour signature"}
            </button>
          ) : null}
          {selected.sign_url && !signed ? (
            <button
              type="button"
              onClick={() => copyLink(selected.sign_url)}
              className="inline-flex items-center gap-2 rounded-lg border border-brand-800 px-4 py-2 text-sm font-medium text-white/80 hover:text-white"
            >
              <Copy className="h-4 w-4" /> Copier le lien
            </button>
          ) : null}
          {signed ? (
            <button
              type="button"
              onClick={() =>
                void openPdf(`/api/v1/contrats-gestion/${selected.id}/signed-pdf`)
              }
              className="inline-flex items-center gap-2 rounded-lg bg-emerald-600 px-4 py-2 text-sm font-semibold text-white hover:bg-emerald-500"
            >
              <FileSignature className="h-4 w-4" /> PDF signé
            </button>
          ) : null}
        </div>

        <style jsx global>{`
          .cg-prose h1 {
            font-size: 1.05rem;
            font-weight: 700;
            margin: 0 0 0.5rem;
            color: #0f172a;
          }
          .cg-prose h2 {
            font-size: 0.9rem;
            font-weight: 700;
            margin: 1rem 0 0.35rem;
            color: #92400e;
          }
          .cg-prose p {
            margin: 0 0 0.5rem;
            text-align: justify;
          }
          .cg-prose ul {
            margin: 0 0 0.5rem;
            padding-left: 1.1rem;
          }
          .cg-prose li {
            margin: 0.15rem 0;
          }
          .cg-prose strong {
            color: #0f172a;
          }
        `}</style>
      </div>
    );
  }

  // Liste
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="flex items-center gap-2 text-sm font-bold text-white">
            <FileSignature className="h-4 w-4 text-sky-400" /> Contrats de gestion
          </h3>
          <p className="mt-0.5 text-xs text-white/50">
            Envoi pour signature en ligne au propriétaire (Mandant) + suivi.
          </p>
        </div>
        <button
          type="button"
          onClick={() => void createDraft()}
          disabled={busy}
          className="inline-flex items-center gap-2 rounded-lg bg-sky-600 px-3 py-2 text-sm font-semibold text-white hover:bg-sky-500 disabled:opacity-50"
        >
          {busy ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Plus className="h-4 w-4" />
          )}
          Nouveau contrat
        </button>
      </div>

      {error ? (
        <p className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-sm text-rose-200">
          {error}
        </p>
      ) : null}
      {toast ? (
        <p className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-200">
          {toast}
        </p>
      ) : null}

      {list === null ? (
        <div className="flex items-center justify-center py-10 text-white/40">
          <Loader2 className="h-5 w-5 animate-spin" />
        </div>
      ) : list.length === 0 ? (
        <div className="rounded-lg border border-dashed border-brand-800 py-10 text-center text-sm text-white/50">
          Aucun contrat de gestion pour cet immeuble.
        </div>
      ) : (
        <div className="space-y-2">
          {list.map((c) => (
            <div
              key={c.id}
              className="flex items-center justify-between gap-3 rounded-lg border border-brand-800 bg-brand-950/60 px-4 py-3"
            >
              <button
                type="button"
                onClick={() => void openContract(c.id)}
                className="min-w-0 flex-1 text-left"
              >
                <div className="flex items-center gap-2">
                  <span className="truncate text-sm font-semibold text-white">
                    {c.compagnie || "Mandant à préciser"}
                  </span>
                  <StatusBadge c={c} />
                </div>
                <p className="mt-0.5 truncate text-xs text-white/50">
                  {c.mandant_courriel || "—"}
                  {c.status === "envoye" && c.open_count > 0
                    ? ` · Ouvert ${c.open_count}×`
                    : ""}
                  {c.status === "signe"
                    ? ` · Signé le ${fmtDate(c.signed_at)}`
                    : ""}
                </p>
              </button>
              <div className="flex items-center gap-1">
                {c.status === "envoye" && c.sign_url ? (
                  <button
                    type="button"
                    onClick={() => copyLink(c.sign_url)}
                    title="Copier le lien de signature"
                    className="rounded-md p-2 text-white/50 hover:bg-brand-900 hover:text-white"
                  >
                    <Mail className="h-4 w-4" />
                  </button>
                ) : null}
                {c.status !== "signe" ? (
                  <button
                    type="button"
                    onClick={() => void deleteContract(c.id)}
                    title="Supprimer"
                    className="rounded-md p-2 text-white/50 hover:bg-rose-900/40 hover:text-rose-300"
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                ) : null}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Gabarit par défaut (avancé) */}
      <TemplateEditor
        open={showTemplate}
        onToggle={() => setShowTemplate((v) => !v)}
      />
    </div>
  );
}

// ─── Éditeur du gabarit par défaut ────────────────────────────────

function TemplateEditor({
  open,
  onToggle
}: {
  open: boolean;
  onToggle: () => void;
}) {
  const [body, setBody] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  useEffect(() => {
    if (!open || body !== null) return;
    void (async () => {
      try {
        const res = await authedFetch("/api/v1/contrats-gestion/template");
        if (!res.ok) throw new Error();
        setBody(((await res.json()) as { corps_markdown: string }).corps_markdown);
      } catch {
        setBody("");
        setMsg("Chargement du gabarit impossible.");
      }
    })();
  }, [open, body]);

  async function save() {
    if (body === null) return;
    setBusy(true);
    setMsg(null);
    try {
      const res = await authedFetch("/api/v1/contrats-gestion/template", {
        method: "PUT",
        body: JSON.stringify({ corps_markdown: body })
      });
      if (res.status === 403) {
        setMsg("Réservé aux administrateurs.");
        return;
      }
      if (!res.ok) throw new Error();
      setMsg("Gabarit enregistré. Les contrats déjà signés gardent leur version.");
    } catch {
      setMsg("Enregistrement impossible.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mt-6 rounded-lg border border-brand-800">
      <button
        type="button"
        onClick={onToggle}
        className="flex w-full items-center justify-between px-4 py-2.5 text-sm font-medium text-white/70"
      >
        <span className="inline-flex items-center gap-2">
          <Settings2 className="h-4 w-4" /> Modèle du contrat par défaut
        </span>
        <ChevronDown className={`h-4 w-4 transition ${open ? "rotate-180" : ""}`} />
      </button>
      {open ? (
        <div className="space-y-3 border-t border-brand-800 p-4">
          <p className="text-xs text-white/50">
            Modifiable en tout temps. Marqueurs disponibles :{" "}
            <code className="text-white/70">
              {"{{COMPAGNIE}} {{SIEGE_SOCIAL}} {{REPRESENTANT}} {{TITRE}} {{IMMEUBLES}} {{DISTRICT}} {{COURRIEL}} {{LIEU}} {{DATE}}"}
            </code>
          </p>
          {body === null ? (
            <div className="flex items-center justify-center py-6 text-white/40">
              <Loader2 className="h-5 w-5 animate-spin" />
            </div>
          ) : (
            <textarea
              value={body}
              onChange={(e) => setBody(e.target.value)}
              rows={16}
              className="w-full rounded-lg border border-brand-800 bg-brand-950 px-3 py-2 font-mono text-xs leading-relaxed text-white focus:border-sky-500 focus:outline-none"
            />
          )}
          {msg ? <p className="text-xs text-white/70">{msg}</p> : null}
          <button
            type="button"
            onClick={() => void save()}
            disabled={busy || body === null}
            className="inline-flex items-center gap-2 rounded-lg bg-sky-600 px-4 py-2 text-sm font-semibold text-white hover:bg-sky-500 disabled:opacity-50"
          >
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}
            Enregistrer le modèle
          </button>
        </div>
      ) : null}
    </div>
  );
}
