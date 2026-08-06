"use client";

/* eSign — préparation et suivi d'un document.

   Brouillon  → éditeur : signataires (banque de contacts ou manuel),
                placement visuel des zones (signature, initiales, date
                auto, texte, case) sur les pages rendues en PNG,
                message courriel, envoi.
   Envoyé/…   → suivi : timeline par signataire (envoyé, ouvertures,
                SMS vérifié, signé/refusé + IP), journal d'événements,
                relance, annulation, téléchargement du PDF final. */

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState
} from "react";
import { useParams } from "next/navigation";
import { useRouter } from "@/i18n/navigation";
import {
  ArrowDown,
  ArrowUp,
  Ban,
  BellRing,
  CalendarCheck,
  CheckCircle2,
  CheckSquare,
  Download,
  Eye,
  FileText,
  LayoutTemplate,
  Loader2,
  Mail,
  Paperclip,
  PenLine,
  Plus,
  Search,
  Send,
  ShieldCheck,
  Signature as SignatureIcon,
  Trash2,
  Type,
  X,
  XCircle
} from "lucide-react";

import { authedFetch } from "@/lib/auth";
import { useConfirm } from "@/components/confirm-dialog";
import { EntreprisesTopbar, useEntreprisesLayout } from "../../layout";

/* ----------------------------- Types ----------------------------- */

type Signer = {
  id: number;
  contact_ref: string | null;
  order_index: number;
  first_name: string;
  last_name: string;
  email: string;
  phone: string | null;
  require_sms_auth: boolean;
  sms_verified_at: string | null;
  sent_at: string | null;
  opened_at: string | null;
  last_opened_at: string | null;
  open_count: number;
  signed_at: string | null;
  signed_ip: string | null;
  declined_at: string | null;
  decline_reason: string | null;
};

type FieldT = {
  id: number; // négatif = pas encore persisté
  signer_id: number;
  kind: string;
  page: number;
  x: number;
  y: number;
  w: number;
  h: number;
  required: boolean;
  label: string | null;
  value_text: string | null;
};

type EventT = {
  id: number;
  signer_id: number | null;
  type: string;
  ip: string | null;
  detail: string | null;
  created_at: string;
};

type Observer = {
  id: number;
  name: string;
  email: string;
};

type Attachment = {
  id: number;
  filename: string;
  size_bytes: number;
};

type DocDetail = {
  id: number;
  title: string;
  status: string;
  entreprise_id: number | null;
  entreprise_name: string | null;
  filename: string;
  page_count: number;
  use_signing_order: boolean;
  sent_at: string | null;
  completed_at: string | null;
  expires_at: string | null;
  reminder_days: number | null;
  created_at: string;
  updated_at: string | null;
  message: string | null;
  sha256: string | null;
  has_signed_pdf: boolean;
  signers: Signer[];
  fields: FieldT[];
  events: EventT[];
  observers: Observer[];
  attachments: Attachment[];
};

type UnifiedContact = {
  id: string;
  source: string;
  full_name: string;
  company: string | null;
  email: string | null;
  phone: string | null;
  kind: string;
};

/* --------------------------- Constantes --------------------------- */

const SIGNER_COLORS = [
  "#2563eb",
  "#059669",
  "#d97706",
  "#7c3aed",
  "#dc2626",
  "#0891b2",
  "#4d7c0f",
  "#be185d"
];

const KIND_META: Record<
  string,
  {
    label: string;
    icon: React.ComponentType<{ className?: string }>;
    w: number;
    h: number;
  }
> = {
  signature: { label: "Signature", icon: SignatureIcon, w: 0.22, h: 0.055 },
  initiales: { label: "Initiales", icon: PenLine, w: 0.08, h: 0.045 },
  date: { label: "Date (auto)", icon: CalendarCheck, w: 0.14, h: 0.035 },
  texte: { label: "Texte", icon: Type, w: 0.2, h: 0.035 },
  case: { label: "Case à cocher", icon: CheckSquare, w: 0.03, h: 0.023 }
};

const STATUS_LABEL: Record<string, string> = {
  brouillon: "Brouillon",
  envoye: "En attente de signatures",
  complete: "Signé par toutes les parties",
  refuse: "Refusé",
  annule: "Annulé",
  expire: "Expiré"
};

const STATUS_CLS: Record<string, string> = {
  brouillon: "badge-neutral",
  envoye: "badge-sky",
  complete: "badge-emerald",
  refuse: "badge-rose",
  annule: "badge-neutral",
  expire: "badge-amber"
};

const EVENT_LABELS: Record<string, string> = {
  cree: "Document créé",
  envoye: "Invitation envoyée",
  relance: "Relance envoyée",
  ouvert: "Document ouvert",
  sms_envoye: "Code SMS envoyé",
  sms_verifie: "Identité vérifiée par SMS",
  signe: "Document signé",
  refuse: "Signature refusée",
  complete: "Document complété",
  annule: "Document annulé",
  expire: "Lien de signature expiré"
};

function fmtDateTime(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("fr-CA", {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit"
  });
}

function signerColor(signers: Signer[], signerId: number): string {
  const idx = signers.findIndex((s) => s.id === signerId);
  return SIGNER_COLORS[(idx >= 0 ? idx : 0) % SIGNER_COLORS.length];
}

let tmpId = -1;

/* ============================= Page ============================= */

export default function SignatureDocPage() {
  const params = useParams<{ id: string }>();
  const docId = Number(params.id);
  const router = useRouter();
  const confirm = useConfirm();
  const { entreprises } = useEntreprisesLayout();

  const [doc, setDoc] = useState<DocDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [banner, setBanner] = useState<string | null>(null);

  // Zones locales (éditeur) + auto-save.
  const [fields, setFields] = useState<FieldT[]>([]);
  const [saveState, setSaveState] = useState<"idle" | "saving" | "saved">(
    "idle"
  );
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const savePending = useRef<Promise<void> | null>(null);

  // Outil actif + signataire actif + zone sélectionnée.
  const [activeSignerId, setActiveSignerId] = useState<number | null>(null);
  const [activeTool, setActiveTool] = useState<string | null>(null);
  const [selectedFieldId, setSelectedFieldId] = useState<number | null>(null);

  // Images de pages (object URLs).
  const [pageUrls, setPageUrls] = useState<Record<number, string>>({});
  const pageUrlsRef = useRef<Record<number, string>>({});

  // Modal signataire.
  const [signerModal, setSignerModal] = useState(false);
  const [busySend, setBusySend] = useState(false);

  // V2 : observateurs / annexes / modèle.
  const [obsName, setObsName] = useState("");
  const [obsEmail, setObsEmail] = useState("");
  const [obsBusy, setObsBusy] = useState(false);
  const [attBusy, setAttBusy] = useState(false);
  const [tplBusy, setTplBusy] = useState(false);

  const isDraft = doc?.status === "brouillon";

  /* --------------------------- Chargement --------------------------- */

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await authedFetch(`/api/v1/esign/documents/${docId}`);
      if (!res.ok) throw new Error(`http_${res.status}`);
      const d = (await res.json()) as DocDetail;
      setDoc(d);
      setFields(d.fields);
      if (d.signers.length > 0) {
        setActiveSignerId((prev) =>
          prev && d.signers.some((s) => s.id === prev)
            ? prev
            : d.signers[0].id
        );
      }
    } catch {
      setError("Document introuvable ou chargement impossible.");
    } finally {
      setLoading(false);
    }
  }, [docId]);

  useEffect(() => {
    void load();
  }, [load]);

  // Rendu des pages en PNG (séquentiel, blob → objectURL).
  useEffect(() => {
    if (!doc) return;
    let cancelled = false;
    (async () => {
      for (let p = 1; p <= doc.page_count; p++) {
        if (cancelled || pageUrlsRef.current[p]) continue;
        try {
          const res = await authedFetch(
            `/api/v1/esign/documents/${doc.id}/pages/${p}`
          );
          if (!res.ok) continue;
          const blob = await res.blob();
          if (cancelled) return;
          const url = URL.createObjectURL(blob);
          pageUrlsRef.current = { ...pageUrlsRef.current, [p]: url };
          setPageUrls(pageUrlsRef.current);
        } catch {
          /* page suivante */
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [doc]);

  useEffect(
    () => () => {
      Object.values(pageUrlsRef.current).forEach((u) =>
        URL.revokeObjectURL(u)
      );
    },
    []
  );

  /* --------------------------- Sauvegarde zones --------------------------- */

  const persistFields = useCallback(
    async (list: FieldT[]) => {
      setSaveState("saving");
      const payload = list.map((f) => ({
        signer_id: f.signer_id,
        kind: f.kind,
        page: f.page,
        x: f.x,
        y: f.y,
        w: f.w,
        h: f.h,
        required: f.required,
        label: f.label || null
      }));
      const p = (async () => {
        try {
          const res = await authedFetch(
            `/api/v1/esign/documents/${docId}/fields`,
            { method: "PUT", body: JSON.stringify(payload) }
          );
          setSaveState(res.ok ? "saved" : "idle");
          if (!res.ok) {
            setBanner("Sauvegarde des zones échouée — réessayez.");
          }
        } catch {
          setSaveState("idle");
          setBanner("Sauvegarde des zones échouée — réessayez.");
        }
      })();
      savePending.current = p;
      await p;
    },
    [docId]
  );

  const scheduleSave = useCallback(
    (list: FieldT[]) => {
      if (saveTimer.current) clearTimeout(saveTimer.current);
      setSaveState("saving");
      saveTimer.current = setTimeout(() => void persistFields(list), 900);
    },
    [persistFields]
  );

  const flushSave = useCallback(async () => {
    if (saveTimer.current) {
      clearTimeout(saveTimer.current);
      saveTimer.current = null;
      await persistFields(fields);
    } else if (savePending.current) {
      await savePending.current;
    }
  }, [fields, persistFields]);

  function updateFields(next: FieldT[]) {
    setFields(next);
    scheduleSave(next);
  }

  /* --------------------------- Actions doc --------------------------- */

  async function patchDoc(body: Record<string, unknown>) {
    const res = await authedFetch(`/api/v1/esign/documents/${docId}`, {
      method: "PATCH",
      body: JSON.stringify(body)
    });
    if (res.ok) {
      const d = (await res.json()) as DocDetail;
      setDoc((prev) =>
        prev ? { ...d, fields: prev.fields, events: d.events } : d
      );
    }
  }

  async function sendDocument() {
    if (!doc) return;
    if (doc.signers.length === 0) {
      setBanner("Ajoutez au moins un signataire avant d'envoyer.");
      return;
    }
    const without = doc.signers.filter(
      (s) => !fields.some((f) => f.signer_id === s.id)
    );
    if (without.length > 0) {
      setBanner(
        `Aucune zone placée pour : ${without
          .map((s) => `${s.first_name} ${s.last_name}`)
          .join(", ")}.`
      );
      return;
    }
    if (
      !(await confirm({
        title: "Envoyer les invitations de signature ?",
        description:
          "Chaque signataire recevra un courriel avec son lien personnel. " +
          "Le document ne sera plus modifiable.",
        confirmLabel: "Envoyer"
      }))
    ) {
      return;
    }
    setBusySend(true);
    setBanner(null);
    try {
      await flushSave();
      const res = await authedFetch(
        `/api/v1/esign/documents/${docId}/send`,
        { method: "POST" }
      );
      const body = await res.json().catch(() => null);
      if (!res.ok) {
        setBanner(
          typeof body?.detail === "string"
            ? body.detail
            : "Envoi échoué — réessayez."
        );
        return;
      }
      if (body?.errors?.length) {
        setBanner(`Envoyé avec des erreurs : ${body.errors.join(" / ")}`);
      }
      await load();
    } finally {
      setBusySend(false);
    }
  }

  async function remind() {
    const res = await authedFetch(
      `/api/v1/esign/documents/${docId}/remind`,
      { method: "POST" }
    );
    const body = await res.json().catch(() => null);
    if (res.ok) {
      setBanner(
        `Relance envoyée à ${body?.sent ?? 0} signataire(s) en attente.`
      );
      await load();
    } else {
      setBanner(
        typeof body?.detail === "string" ? body.detail : "Relance échouée."
      );
    }
  }

  async function cancelDoc() {
    if (
      !(await confirm({
        title: "Annuler ce document ?",
        description:
          "Les liens de signature seront désactivés. Cette action est " +
          "irréversible.",
        confirmLabel: "Annuler le document",
        destructive: true
      }))
    ) {
      return;
    }
    const res = await authedFetch(
      `/api/v1/esign/documents/${docId}/cancel`,
      { method: "POST" }
    );
    if (res.ok) await load();
  }

  async function deleteDoc() {
    if (
      !(await confirm({
        title: "Supprimer ce document ?",
        description: "Le PDF et son historique seront supprimés.",
        confirmLabel: "Supprimer",
        destructive: true
      }))
    ) {
      return;
    }
    const res = await authedFetch(`/api/v1/esign/documents/${docId}`, {
      method: "DELETE"
    });
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    if (res.ok) router.push("/entreprises/signature" as any);
  }

  async function saveAsTemplate() {
    if (!doc) return;
    setTplBusy(true);
    setBanner(null);
    try {
      await flushSave();
      const res = await authedFetch(
        `/api/v1/esign/documents/${docId}/save-as-template`,
        { method: "POST", body: JSON.stringify({}) }
      );
      const body = await res.json().catch(() => null);
      if (!res.ok) {
        setBanner(
          typeof body?.detail === "string"
            ? body.detail
            : "Enregistrement du modèle échoué."
        );
        return;
      }
      setBanner(
        `Modèle « ${body?.title || doc.title} » enregistré — réutilisable ` +
          "depuis le bouton « Modèles » de la liste."
      );
    } finally {
      setTplBusy(false);
    }
  }

  async function addObserver(e: React.FormEvent) {
    e.preventDefault();
    if (!obsName.trim() || !obsEmail.trim()) return;
    setObsBusy(true);
    try {
      const res = await authedFetch(
        `/api/v1/esign/documents/${docId}/observers`,
        {
          method: "POST",
          body: JSON.stringify({
            name: obsName.trim(),
            email: obsEmail.trim()
          })
        }
      );
      if (res.ok) {
        setObsName("");
        setObsEmail("");
        await load();
      } else {
        const body = await res.json().catch(() => null);
        setBanner(
          typeof body?.detail === "string"
            ? body.detail
            : "Ajout de l'observateur échoué."
        );
      }
    } finally {
      setObsBusy(false);
    }
  }

  async function removeObserver(id: number) {
    const res = await authedFetch(`/api/v1/esign/observers/${id}`, {
      method: "DELETE"
    });
    if (res.ok) await load();
  }

  async function uploadAttachment(file: File) {
    setAttBusy(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const res = await authedFetch(
        `/api/v1/esign/documents/${docId}/attachments`,
        { method: "POST", body: fd }
      );
      if (res.ok) {
        await load();
      } else {
        const body = await res.json().catch(() => null);
        setBanner(
          typeof body?.detail === "string"
            ? body.detail
            : "Téléversement de l'annexe échoué."
        );
      }
    } finally {
      setAttBusy(false);
    }
  }

  async function removeAttachment(id: number) {
    const res = await authedFetch(`/api/v1/esign/attachments/${id}`, {
      method: "DELETE"
    });
    if (res.ok) await load();
  }

  async function openAttachment(id: number) {
    const res = await authedFetch(`/api/v1/esign/attachments/${id}/pdf`);
    if (!res.ok) return;
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    window.open(url, "_blank", "noopener");
    setTimeout(() => URL.revokeObjectURL(url), 60_000);
  }

  async function openPdf(path: "pdf" | "signed-pdf") {
    const res = await authedFetch(
      `/api/v1/esign/documents/${docId}/${path}`
    );
    if (!res.ok) return;
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    window.open(url, "_blank", "noopener");
    setTimeout(() => URL.revokeObjectURL(url), 60_000);
  }

  /* --------------------------- Signataires --------------------------- */

  async function removeSigner(s: Signer) {
    if (
      !(await confirm({
        title: `Retirer ${s.first_name} ${s.last_name} ?`,
        description: "Ses zones placées seront également retirées.",
        confirmLabel: "Retirer",
        destructive: true
      }))
    ) {
      return;
    }
    const res = await authedFetch(`/api/v1/esign/signers/${s.id}`, {
      method: "DELETE"
    });
    if (res.ok) {
      const next = fields.filter((f) => f.signer_id !== s.id);
      setFields(next);
      await load();
    }
  }

  async function moveSigner(s: Signer, dir: -1 | 1) {
    if (!doc) return;
    const ordered = [...doc.signers];
    const idx = ordered.findIndex((x) => x.id === s.id);
    const swap = idx + dir;
    if (swap < 0 || swap >= ordered.length) return;
    [ordered[idx], ordered[swap]] = [ordered[swap], ordered[idx]];
    await Promise.all(
      ordered.map((x, i) =>
        x.order_index === i
          ? Promise.resolve()
          : authedFetch(`/api/v1/esign/signers/${x.id}`, {
              method: "PATCH",
              body: JSON.stringify({ order_index: i })
            }).then(() => undefined)
      )
    );
    await load();
  }

  /* --------------------------- Rendu --------------------------- */

  if (loading) {
    return (
      <>
        <EntreprisesTopbar
          breadcrumbs={[
            { label: "Signature", href: "/entreprises/signature" },
            { label: "…" }
          ]}
        />
        <div className="flex items-center justify-center py-24">
          <Loader2 className="h-6 w-6 animate-spin text-accent-500" />
        </div>
      </>
    );
  }

  if (error || !doc) {
    return (
      <>
        <EntreprisesTopbar
          breadcrumbs={[
            { label: "Signature", href: "/entreprises/signature" },
            { label: "Erreur" }
          ]}
        />
        <div className="p-6">
          <div className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-4 py-3 text-sm text-rose-600">
            {error || "Document introuvable."}
          </div>
        </div>
      </>
    );
  }

  const selectedField =
    fields.find((f) => f.id === selectedFieldId) || null;

  return (
    <>
      <EntreprisesTopbar
        breadcrumbs={[
          { label: "Signature", href: "/entreprises/signature" },
          { label: doc.title }
        ]}
        rightSlot={
          <div className="flex items-center gap-2">
            {isDraft ? (
              <>
                <span className="hidden text-[11px] text-[var(--qg-text-soft)] sm:inline">
                  {saveState === "saving"
                    ? "Enregistrement…"
                    : saveState === "saved"
                    ? "Zones enregistrées ✓"
                    : ""}
                </span>
                <button
                  type="button"
                  onClick={() => void saveAsTemplate()}
                  disabled={tplBusy}
                  className="btn-secondary btn-sm inline-flex items-center gap-1.5"
                >
                  {tplBusy ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <LayoutTemplate className="h-3.5 w-3.5" />
                  )}
                  Enregistrer comme modèle
                </button>
                <button
                  type="button"
                  onClick={deleteDoc}
                  className="btn-outline-rose btn-sm inline-flex items-center gap-1.5"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                  Supprimer
                </button>
                <button
                  type="button"
                  onClick={sendDocument}
                  disabled={busySend}
                  className="btn-accent btn-sm inline-flex items-center gap-1.5"
                >
                  {busySend ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Send className="h-3.5 w-3.5" />
                  )}
                  Envoyer pour signature
                </button>
              </>
            ) : (
              <>
                <button
                  type="button"
                  onClick={() => void saveAsTemplate()}
                  disabled={tplBusy}
                  className="btn-secondary btn-sm inline-flex items-center gap-1.5"
                  title="Réutiliser ce document (PDF + zones) comme modèle"
                >
                  {tplBusy ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <LayoutTemplate className="h-3.5 w-3.5" />
                  )}
                  Modèle
                </button>
                <button
                  type="button"
                  onClick={() => void openPdf("pdf")}
                  className="btn-secondary btn-sm inline-flex items-center gap-1.5"
                >
                  <FileText className="h-3.5 w-3.5" />
                  Original
                </button>
                {doc.has_signed_pdf ? (
                  <button
                    type="button"
                    onClick={() => void openPdf("signed-pdf")}
                    className="btn-accent btn-sm inline-flex items-center gap-1.5"
                  >
                    <Download className="h-3.5 w-3.5" />
                    PDF signé
                  </button>
                ) : null}
                {doc.status === "envoye" ? (
                  <>
                    <button
                      type="button"
                      onClick={() => void remind()}
                      className="btn-secondary btn-sm inline-flex items-center gap-1.5"
                    >
                      <BellRing className="h-3.5 w-3.5" />
                      Relancer
                    </button>
                    <button
                      type="button"
                      onClick={() => void cancelDoc()}
                      className="btn-outline-rose btn-sm inline-flex items-center gap-1.5"
                    >
                      <Ban className="h-3.5 w-3.5" />
                      Annuler
                    </button>
                  </>
                ) : null}
                {doc.status === "annule" ? (
                  <button
                    type="button"
                    onClick={deleteDoc}
                    className="btn-outline-rose btn-sm inline-flex items-center gap-1.5"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                    Supprimer
                  </button>
                ) : null}
              </>
            )}
          </div>
        }
      />

      <div className="p-4 lg:p-6">
        {banner ? (
          <div className="mb-4 flex items-start justify-between gap-3 rounded-lg border border-amber-500/40 bg-amber-500/10 px-4 py-3 text-sm text-amber-700">
            <span>{banner}</span>
            <button
              type="button"
              onClick={() => setBanner(null)}
              className="shrink-0 text-amber-700 hover:opacity-70"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        ) : null}

        {/* En-tête document */}
        <div
          className="mb-4 rounded-2xl border p-4"
          style={{
            borderColor: "var(--qg-border)",
            backgroundColor: "var(--qg-card-bg)"
          }}
        >
          <div className="flex flex-wrap items-center gap-3">
            <span className={`badge ${STATUS_CLS[doc.status] || "badge-neutral"}`}>
              {STATUS_LABEL[doc.status] || doc.status}
            </span>
            {isDraft ? (
              <input
                defaultValue={doc.title}
                onBlur={(e) => {
                  const v = e.target.value.trim();
                  if (v && v !== doc.title) void patchDoc({ title: v });
                }}
                className="input min-w-0 flex-1 text-sm font-semibold"
              />
            ) : (
              <h2 className="min-w-0 flex-1 truncate text-base font-semibold text-[var(--qg-text)]">
                {doc.title}
              </h2>
            )}
            {isDraft ? (
              <select
                value={doc.entreprise_id ? String(doc.entreprise_id) : ""}
                onChange={(e) =>
                  void patchDoc({
                    entreprise_id: e.target.value
                      ? Number(e.target.value)
                      : 0
                  })
                }
                className="input text-xs"
              >
                <option value="">— Entreprise —</option>
                {entreprises.map((ent) => (
                  <option key={ent.id} value={String(ent.id)}>
                    {ent.name}
                  </option>
                ))}
              </select>
            ) : doc.entreprise_name ? (
              <span className="text-xs text-[var(--qg-text-muted)]">
                {doc.entreprise_name}
              </span>
            ) : null}
            <span className="text-xs text-[var(--qg-text-soft)]">
              {doc.filename} · {doc.page_count} page
              {doc.page_count > 1 ? "s" : ""}
            </span>
            {doc.expires_at ? (
              <span
                className={`text-xs ${
                  doc.status === "expire"
                    ? "font-medium text-amber-600"
                    : "text-[var(--qg-text-muted)]"
                }`}
              >
                ⏳ Expire le{" "}
                {new Date(doc.expires_at).toLocaleDateString("fr-CA", {
                  day: "numeric",
                  month: "short",
                  year: "numeric"
                })}
              </span>
            ) : null}
          </div>
        </div>

        <div className="grid grid-cols-1 gap-4 xl:grid-cols-[1fr_24rem]">
          {/* ---------- Colonne pages ---------- */}
          <div className="min-w-0 space-y-4">
            {Array.from({ length: doc.page_count }, (_, i) => i + 1).map(
              (p) => (
                <PageCanvas
                  key={p}
                  page={p}
                  imgUrl={pageUrls[p]}
                  fields={fields.filter((f) => f.page === p)}
                  signers={doc.signers}
                  editable={isDraft}
                  activeTool={activeTool}
                  selectedFieldId={selectedFieldId}
                  onPlace={(x, y) => {
                    if (!activeTool || !activeSignerId) return;
                    const meta = KIND_META[activeTool];
                    const nf: FieldT = {
                      id: tmpId--,
                      signer_id: activeSignerId,
                      kind: activeTool,
                      page: p,
                      x: Math.max(0, Math.min(x - meta.w / 2, 1 - meta.w)),
                      y: Math.max(0, Math.min(y - meta.h / 2, 1 - meta.h)),
                      w: meta.w,
                      h: meta.h,
                      required: true,
                      label: null,
                      value_text: null
                    };
                    updateFields([...fields, nf]);
                    setSelectedFieldId(nf.id);
                    setActiveTool(null);
                  }}
                  onSelect={setSelectedFieldId}
                  onChange={(f) =>
                    updateFields(fields.map((x) => (x.id === f.id ? f : x)))
                  }
                  onDelete={(id) => {
                    updateFields(fields.filter((x) => x.id !== id));
                    if (selectedFieldId === id) setSelectedFieldId(null);
                  }}
                />
              )
            )}
          </div>

          {/* ---------- Colonne latérale ---------- */}
          <div className="space-y-4">
            {/* Signataires */}
            <div
              className="rounded-2xl border p-4"
              style={{
                borderColor: "var(--qg-border)",
                backgroundColor: "var(--qg-card-bg)"
              }}
            >
              <div className="mb-3 flex items-center justify-between">
                <h3 className="text-xs font-semibold uppercase tracking-wider text-[var(--qg-text-soft)]">
                  Signataires
                </h3>
                {isDraft ? (
                  <button
                    type="button"
                    onClick={() => setSignerModal(true)}
                    className="btn-outline-accent btn-xs inline-flex items-center gap-1"
                  >
                    <Plus className="h-3 w-3" />
                    Ajouter
                  </button>
                ) : null}
              </div>

              {doc.signers.length === 0 ? (
                <p className="text-xs text-[var(--qg-text-muted)]">
                  Aucun signataire. Ajoutez-en depuis la banque de contacts
                  ou en les créant.
                </p>
              ) : (
                <ul className="space-y-2">
                  {doc.signers.map((s, i) => (
                    <li key={s.id}>
                      <SignerRow
                        s={s}
                        color={SIGNER_COLORS[i % SIGNER_COLORS.length]}
                        isDraft={isDraft}
                        useOrder={doc.use_signing_order}
                        active={activeSignerId === s.id}
                        onActivate={() => setActiveSignerId(s.id)}
                        onRemove={() => void removeSigner(s)}
                        onMoveUp={() => void moveSigner(s, -1)}
                        onMoveDown={() => void moveSigner(s, 1)}
                        fieldCount={
                          fields.filter((f) => f.signer_id === s.id).length
                        }
                      />
                    </li>
                  ))}
                </ul>
              )}

              {isDraft && doc.signers.length > 1 ? (
                <label className="mt-3 flex items-center gap-2 text-xs text-[var(--qg-text-muted)]">
                  <input
                    type="checkbox"
                    checked={doc.use_signing_order}
                    onChange={(e) =>
                      void patchDoc({ use_signing_order: e.target.checked })
                    }
                  />
                  Signature séquentielle (chacun son tour, dans l&apos;ordre)
                </label>
              ) : null}
            </div>

            {/* Palette de zones (brouillon) */}
            {isDraft ? (
              <div
                className="rounded-2xl border p-4"
                style={{
                  borderColor: "var(--qg-border)",
                  backgroundColor: "var(--qg-card-bg)"
                }}
              >
                <h3 className="mb-3 text-xs font-semibold uppercase tracking-wider text-[var(--qg-text-soft)]">
                  Zones à placer
                </h3>
                {!activeSignerId ? (
                  <p className="mb-2 text-xs text-amber-600">
                    Sélectionnez d&apos;abord un signataire.
                  </p>
                ) : null}
                <div className="grid grid-cols-2 gap-2">
                  {Object.entries(KIND_META).map(([kind, meta]) => {
                    const Icon = meta.icon;
                    const isActive = activeTool === kind;
                    return (
                      <button
                        key={kind}
                        type="button"
                        disabled={!activeSignerId}
                        onClick={() =>
                          setActiveTool(isActive ? null : kind)
                        }
                        className={`flex items-center gap-2 rounded-lg border px-2.5 py-2 text-xs font-medium transition disabled:opacity-40 ${
                          isActive
                            ? "border-[var(--qg-accent)] bg-[var(--qg-accent)] text-[var(--qg-accent-ink)]"
                            : "border-[var(--qg-border)] text-[var(--qg-text-muted)] hover:border-[var(--qg-accent)] hover:text-[var(--qg-text)]"
                        }`}
                      >
                        <Icon className="h-3.5 w-3.5" />
                        {meta.label}
                      </button>
                    );
                  })}
                </div>
                <p className="mt-2 text-[11px] leading-relaxed text-[var(--qg-text-soft)]">
                  Choisissez une zone puis cliquez sur la page à
                  l&apos;endroit voulu. Glissez pour déplacer, poignée en
                  bas à droite pour redimensionner.
                </p>

                {selectedField ? (
                  <div
                    className="mt-3 space-y-2 rounded-lg border p-3"
                    style={{ borderColor: "var(--qg-border)" }}
                  >
                    <p className="text-xs font-medium text-[var(--qg-text)]">
                      Zone sélectionnée :{" "}
                      {KIND_META[selectedField.kind]?.label ||
                        selectedField.kind}{" "}
                      · p.{selectedField.page}
                    </p>
                    {(selectedField.kind === "texte" ||
                      selectedField.kind === "case") && (
                      <input
                        value={selectedField.label || ""}
                        onChange={(e) =>
                          updateFields(
                            fields.map((f) =>
                              f.id === selectedField.id
                                ? { ...f, label: e.target.value }
                                : f
                            )
                          )
                        }
                        placeholder="Libellé (ex. : Titre / fonction)"
                        className="input w-full text-xs"
                      />
                    )}
                    <label className="flex items-center gap-2 text-xs text-[var(--qg-text-muted)]">
                      <input
                        type="checkbox"
                        checked={selectedField.required}
                        onChange={(e) =>
                          updateFields(
                            fields.map((f) =>
                              f.id === selectedField.id
                                ? { ...f, required: e.target.checked }
                                : f
                            )
                          )
                        }
                      />
                      Obligatoire
                    </label>
                    <button
                      type="button"
                      onClick={() => {
                        updateFields(
                          fields.filter((f) => f.id !== selectedField.id)
                        );
                        setSelectedFieldId(null);
                      }}
                      className="btn-outline-rose btn-xs inline-flex items-center gap-1"
                    >
                      <Trash2 className="h-3 w-3" />
                      Supprimer la zone
                    </button>
                  </div>
                ) : null}
              </div>
            ) : null}

            {/* Message courriel (brouillon) */}
            {isDraft ? (
              <div
                className="rounded-2xl border p-4"
                style={{
                  borderColor: "var(--qg-border)",
                  backgroundColor: "var(--qg-card-bg)"
                }}
              >
                <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-[var(--qg-text-soft)]">
                  Message du courriel (optionnel)
                </h3>
                <textarea
                  defaultValue={doc.message || ""}
                  onBlur={(e) => {
                    const v = e.target.value.trim();
                    if (v !== (doc.message || "")) {
                      void patchDoc({ message: v });
                    }
                  }}
                  rows={3}
                  placeholder="Ajouté au courriel d'invitation envoyé aux signataires…"
                  className="input w-full text-xs"
                />
              </div>
            ) : null}

            {/* Options d'envoi (brouillon) */}
            {isDraft ? (
              <div
                className="rounded-2xl border p-4"
                style={{
                  borderColor: "var(--qg-border)",
                  backgroundColor: "var(--qg-card-bg)"
                }}
              >
                <h3 className="mb-3 text-xs font-semibold uppercase tracking-wider text-[var(--qg-text-soft)]">
                  Options
                </h3>
                <div className="space-y-3">
                  <div>
                    <label className="label">
                      Date limite de signature (optionnel)
                    </label>
                    <input
                      type="date"
                      defaultValue={
                        doc.expires_at ? doc.expires_at.slice(0, 10) : ""
                      }
                      onChange={(e) =>
                        void patchDoc({ expires_on: e.target.value })
                      }
                      className="input w-full text-xs"
                    />
                    <p className="mt-1 text-[10px] text-[var(--qg-text-soft)]">
                      Passée cette date, les liens de signature sont
                      désactivés et le document passe en « Expiré ».
                    </p>
                  </div>
                  <div>
                    <label className="label">Rappels automatiques</label>
                    <select
                      value={String(doc.reminder_days ?? 0)}
                      onChange={(e) =>
                        void patchDoc({
                          reminder_days: Number(e.target.value)
                        })
                      }
                      className="input w-full text-xs"
                    >
                      <option value="0">Désactivés</option>
                      <option value="2">Après 2 jours sans action</option>
                      <option value="3">Après 3 jours sans action</option>
                      <option value="5">Après 5 jours sans action</option>
                      <option value="7">Après 7 jours sans action</option>
                      <option value="14">Après 14 jours sans action</option>
                    </select>
                    <p className="mt-1 text-[10px] text-[var(--qg-text-soft)]">
                      Relance courriel automatique des signataires en
                      attente (max 3 relances chacun).
                    </p>
                  </div>
                </div>
              </div>
            ) : null}

            {/* Observateurs en copie */}
            {(isDraft || doc.observers.length > 0) ? (
              <div
                className="rounded-2xl border p-4"
                style={{
                  borderColor: "var(--qg-border)",
                  backgroundColor: "var(--qg-card-bg)"
                }}
              >
                <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-[var(--qg-text-soft)]">
                  Observateurs en copie
                </h3>
                <p className="mb-2 text-[10px] text-[var(--qg-text-soft)]">
                  Ne signent pas — notifiés à l&apos;envoi et reçoivent le
                  PDF final.
                </p>
                {doc.observers.length > 0 ? (
                  <ul className="mb-2 space-y-1.5">
                    {doc.observers.map((o) => (
                      <li
                        key={o.id}
                        className="flex items-center justify-between gap-2 rounded-lg border px-2.5 py-1.5"
                        style={{ borderColor: "var(--qg-border)" }}
                      >
                        <div className="min-w-0">
                          <p className="truncate text-xs font-medium text-[var(--qg-text)]">
                            {o.name}
                          </p>
                          <p className="truncate text-[11px] text-[var(--qg-text-soft)]">
                            {o.email}
                          </p>
                        </div>
                        {isDraft ? (
                          <button
                            type="button"
                            onClick={() => void removeObserver(o.id)}
                            className="shrink-0 rounded p-1 text-[var(--qg-text-soft)] hover:text-rose-500"
                            aria-label="Retirer l'observateur"
                          >
                            <X className="h-3 w-3" />
                          </button>
                        ) : null}
                      </li>
                    ))}
                  </ul>
                ) : null}
                {isDraft ? (
                  <form onSubmit={addObserver} className="space-y-1.5">
                    <input
                      value={obsName}
                      onChange={(e) => setObsName(e.target.value)}
                      placeholder="Nom"
                      className="input w-full text-xs"
                    />
                    <div className="flex gap-1.5">
                      <input
                        type="email"
                        value={obsEmail}
                        onChange={(e) => setObsEmail(e.target.value)}
                        placeholder="Courriel"
                        className="input w-full text-xs"
                      />
                      <button
                        type="submit"
                        disabled={
                          obsBusy || !obsName.trim() || !obsEmail.trim()
                        }
                        className="btn-outline-accent btn-xs shrink-0"
                      >
                        {obsBusy ? (
                          <Loader2 className="h-3 w-3 animate-spin" />
                        ) : (
                          "Ajouter"
                        )}
                      </button>
                    </div>
                  </form>
                ) : null}
              </div>
            ) : null}

            {/* Annexes consultables */}
            {(isDraft || doc.attachments.length > 0) ? (
              <div
                className="rounded-2xl border p-4"
                style={{
                  borderColor: "var(--qg-border)",
                  backgroundColor: "var(--qg-card-bg)"
                }}
              >
                <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-[var(--qg-text-soft)]">
                  Annexes consultables
                </h3>
                <p className="mb-2 text-[10px] text-[var(--qg-text-soft)]">
                  PDF joints à titre informatif — visibles par les
                  signataires, non signés.
                </p>
                {doc.attachments.length > 0 ? (
                  <ul className="mb-2 space-y-1.5">
                    {doc.attachments.map((a) => (
                      <li
                        key={a.id}
                        className="flex items-center justify-between gap-2 rounded-lg border px-2.5 py-1.5"
                        style={{ borderColor: "var(--qg-border)" }}
                      >
                        <button
                          type="button"
                          onClick={() => void openAttachment(a.id)}
                          className="flex min-w-0 items-center gap-1.5 text-left"
                        >
                          <Paperclip className="h-3 w-3 shrink-0 text-[var(--qg-accent)]" />
                          <span className="truncate text-xs text-[var(--qg-text)] hover:underline">
                            {a.filename}
                          </span>
                          <span className="shrink-0 text-[10px] text-[var(--qg-text-soft)]">
                            {(a.size_bytes / 1024 / 1024).toFixed(1)} Mo
                          </span>
                        </button>
                        {isDraft ? (
                          <button
                            type="button"
                            onClick={() => void removeAttachment(a.id)}
                            className="shrink-0 rounded p-1 text-[var(--qg-text-soft)] hover:text-rose-500"
                            aria-label="Retirer l'annexe"
                          >
                            <X className="h-3 w-3" />
                          </button>
                        ) : null}
                      </li>
                    ))}
                  </ul>
                ) : null}
                {isDraft ? (
                  <label className="btn-outline-accent btn-xs inline-flex cursor-pointer items-center gap-1.5">
                    {attBusy ? (
                      <Loader2 className="h-3 w-3 animate-spin" />
                    ) : (
                      <Paperclip className="h-3 w-3" />
                    )}
                    Ajouter une annexe (PDF)
                    <input
                      type="file"
                      accept="application/pdf"
                      className="hidden"
                      disabled={attBusy}
                      onChange={(e) => {
                        const f = e.target.files?.[0];
                        if (f) void uploadAttachment(f);
                        e.target.value = "";
                      }}
                    />
                  </label>
                ) : null}
              </div>
            ) : null}

            {/* Suivi (documents envoyés / complétés / refusés) */}
            {!isDraft ? (
              <SuiviPanel doc={doc} />
            ) : null}
          </div>
        </div>
      </div>

      {signerModal ? (
        <AddSignerModal
          docId={doc.id}
          nextOrder={doc.signers.length}
          onClose={() => setSignerModal(false)}
          onAdded={async () => {
            setSignerModal(false);
            await load();
          }}
        />
      ) : null}
    </>
  );
}

/* ========================= Sous-composants ========================= */

function SignerRow({
  s,
  color,
  isDraft,
  useOrder,
  active,
  onActivate,
  onRemove,
  onMoveUp,
  onMoveDown,
  fieldCount
}: {
  s: Signer;
  color: string;
  isDraft: boolean;
  useOrder: boolean;
  active: boolean;
  onActivate: () => void;
  onRemove: () => void;
  onMoveUp: () => void;
  onMoveDown: () => void;
  fieldCount: number;
}) {
  return (
    <div
      onClick={isDraft ? onActivate : undefined}
      className={`rounded-lg border p-2.5 transition ${
        isDraft ? "cursor-pointer" : ""
      } ${active && isDraft ? "ring-1" : ""}`}
      style={{
        borderColor: active && isDraft ? color : "var(--qg-border)",
        // @ts-expect-error CSS var pour le ring
        "--tw-ring-color": color
      }}
    >
      <div className="flex items-center gap-2">
        <span
          className="h-2.5 w-2.5 shrink-0 rounded-full"
          style={{ backgroundColor: color }}
        />
        <div className="min-w-0 flex-1">
          <p className="truncate text-xs font-medium text-[var(--qg-text)]">
            {s.first_name} {s.last_name}
            {useOrder ? (
              <span className="ml-1.5 text-[10px] text-[var(--qg-text-soft)]">
                #{s.order_index + 1}
              </span>
            ) : null}
          </p>
          <p className="truncate text-[11px] text-[var(--qg-text-soft)]">
            {s.email}
          </p>
        </div>
        {s.require_sms_auth ? (
          <span title="Authentification par code SMS">
            <ShieldCheck className="h-3.5 w-3.5 shrink-0 text-emerald-600" />
          </span>
        ) : null}
        {isDraft ? (
          <div className="flex shrink-0 items-center gap-0.5">
            {useOrder ? (
              <>
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    onMoveUp();
                  }}
                  className="rounded p-1 text-[var(--qg-text-soft)] hover:text-[var(--qg-text)]"
                  aria-label="Monter"
                >
                  <ArrowUp className="h-3 w-3" />
                </button>
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    onMoveDown();
                  }}
                  className="rounded p-1 text-[var(--qg-text-soft)] hover:text-[var(--qg-text)]"
                  aria-label="Descendre"
                >
                  <ArrowDown className="h-3 w-3" />
                </button>
              </>
            ) : null}
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                onRemove();
              }}
              className="rounded p-1 text-[var(--qg-text-soft)] hover:text-rose-500"
              aria-label="Retirer"
            >
              <X className="h-3 w-3" />
            </button>
          </div>
        ) : null}
      </div>
      {isDraft ? (
        <p className="mt-1 pl-4 text-[10px] text-[var(--qg-text-soft)]">
          {fieldCount} zone{fieldCount > 1 ? "s" : ""} placée
          {fieldCount > 1 ? "s" : ""}
        </p>
      ) : null}
    </div>
  );
}

/* ---------- Timeline de suivi + journal ---------- */

function SuiviPanel({ doc }: { doc: DocDetail }) {
  return (
    <>
      <div
        className="rounded-2xl border p-4"
        style={{
          borderColor: "var(--qg-border)",
          backgroundColor: "var(--qg-card-bg)"
        }}
      >
        <h3 className="mb-3 text-xs font-semibold uppercase tracking-wider text-[var(--qg-text-soft)]">
          Avancement
        </h3>
        <ul className="space-y-3">
          {doc.signers.map((s) => (
            <li
              key={s.id}
              className="rounded-lg border p-3"
              style={{ borderColor: "var(--qg-border)" }}
            >
              <p className="text-xs font-semibold text-[var(--qg-text)]">
                {s.first_name} {s.last_name}
                {doc.use_signing_order ? (
                  <span className="ml-1.5 text-[10px] font-normal text-[var(--qg-text-soft)]">
                    #{s.order_index + 1}
                  </span>
                ) : null}
              </p>
              <p className="mb-2 truncate text-[11px] text-[var(--qg-text-soft)]">
                {s.email}
                {s.phone ? ` · ${s.phone}` : ""}
              </p>
              <ul className="space-y-1.5">
                <TimelineStep
                  done={!!s.sent_at}
                  icon={Mail}
                  label={
                    s.sent_at
                      ? `Invitation envoyée le ${fmtDateTime(s.sent_at)}`
                      : "Invitation pas encore envoyée (à son tour)"
                  }
                />
                <TimelineStep
                  done={!!s.opened_at}
                  icon={Eye}
                  label={
                    s.opened_at
                      ? `Ouvert ${s.open_count}× — 1re fois le ${fmtDateTime(
                          s.opened_at
                        )}`
                      : "Pas encore ouvert"
                  }
                />
                {s.require_sms_auth ? (
                  <TimelineStep
                    done={!!s.sms_verified_at}
                    icon={ShieldCheck}
                    label={
                      s.sms_verified_at
                        ? `Identité vérifiée par SMS le ${fmtDateTime(
                            s.sms_verified_at
                          )}`
                        : "Code SMS pas encore vérifié"
                    }
                  />
                ) : null}
                {s.declined_at ? (
                  <TimelineStep
                    done
                    danger
                    icon={XCircle}
                    label={`A refusé le ${fmtDateTime(s.declined_at)}${
                      s.decline_reason ? ` — « ${s.decline_reason} »` : ""
                    }`}
                  />
                ) : (
                  <TimelineStep
                    done={!!s.signed_at}
                    icon={CheckCircle2}
                    label={
                      s.signed_at
                        ? `Signé le ${fmtDateTime(s.signed_at)}${
                            s.signed_ip ? ` (IP ${s.signed_ip})` : ""
                          }`
                        : "Pas encore signé"
                    }
                  />
                )}
              </ul>
            </li>
          ))}
        </ul>
      </div>

      <div
        className="rounded-2xl border p-4"
        style={{
          borderColor: "var(--qg-border)",
          backgroundColor: "var(--qg-card-bg)"
        }}
      >
        <h3 className="mb-3 text-xs font-semibold uppercase tracking-wider text-[var(--qg-text-soft)]">
          Journal d&apos;événements
        </h3>
        {doc.events.length === 0 ? (
          <p className="text-xs text-[var(--qg-text-muted)]">
            Aucun événement.
          </p>
        ) : (
          <ul className="max-h-80 space-y-1.5 overflow-y-auto pr-1">
            {doc.events.map((e) => {
              const who = doc.signers.find((s) => s.id === e.signer_id);
              return (
                <li
                  key={e.id}
                  className="rounded border-l-2 py-1 pl-2 text-[11px] leading-snug"
                  style={{
                    borderColor:
                      e.type === "signe" || e.type === "complete"
                        ? "#059669"
                        : e.type === "refuse" || e.type === "annule"
                        ? "#e11d48"
                        : "var(--qg-border)"
                  }}
                >
                  <span className="font-medium text-[var(--qg-text)]">
                    {EVENT_LABELS[e.type] || e.type}
                  </span>
                  {who ? (
                    <span className="text-[var(--qg-text-muted)]">
                      {" "}
                      — {who.first_name} {who.last_name}
                    </span>
                  ) : null}
                  <br />
                  <span className="text-[var(--qg-text-soft)]">
                    {fmtDateTime(e.created_at)}
                    {e.ip ? ` · IP ${e.ip}` : ""}
                    {e.detail ? ` · ${e.detail}` : ""}
                  </span>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </>
  );
}

function TimelineStep({
  done,
  danger,
  icon: Icon,
  label
}: {
  done: boolean;
  danger?: boolean;
  icon: React.ComponentType<{ className?: string }>;
  label: string;
}) {
  return (
    <li className="flex items-start gap-2 text-[11px]">
      <Icon
        className={`mt-0.5 h-3.5 w-3.5 shrink-0 ${
          danger
            ? "text-rose-500"
            : done
            ? "text-emerald-600"
            : "text-[var(--qg-text-soft)]"
        }`}
      />
      <span
        className={
          danger
            ? "text-rose-600"
            : done
            ? "text-[var(--qg-text)]"
            : "text-[var(--qg-text-soft)]"
        }
      >
        {label}
      </span>
    </li>
  );
}

/* ---------- Rendu d'une page + zones ---------- */

function PageCanvas({
  page,
  imgUrl,
  fields,
  signers,
  editable,
  activeTool,
  selectedFieldId,
  onPlace,
  onSelect,
  onChange,
  onDelete
}: {
  page: number;
  imgUrl?: string;
  fields: FieldT[];
  signers: Signer[];
  editable: boolean;
  activeTool: string | null;
  selectedFieldId: number | null;
  onPlace: (x: number, y: number) => void;
  onSelect: (id: number | null) => void;
  onChange: (f: FieldT) => void;
  onDelete: (id: number) => void;
}) {
  const ref = useRef<HTMLDivElement | null>(null);
  const drag = useRef<{
    fieldId: number;
    mode: "move" | "resize";
    startX: number;
    startY: number;
    orig: FieldT;
    rect: DOMRect;
  } | null>(null);

  function pageClick(e: React.MouseEvent) {
    if (!editable) return;
    if (!activeTool) {
      onSelect(null);
      return;
    }
    const rect = ref.current?.getBoundingClientRect();
    if (!rect) return;
    onPlace(
      (e.clientX - rect.left) / rect.width,
      (e.clientY - rect.top) / rect.height
    );
  }

  function startDrag(
    e: React.PointerEvent,
    f: FieldT,
    mode: "move" | "resize"
  ) {
    if (!editable) return;
    e.stopPropagation();
    e.preventDefault();
    const rect = ref.current?.getBoundingClientRect();
    if (!rect) return;
    drag.current = {
      fieldId: f.id,
      mode,
      startX: e.clientX,
      startY: e.clientY,
      orig: { ...f },
      rect
    };
    (e.target as HTMLElement).setPointerCapture(e.pointerId);
    onSelect(f.id);
  }

  function moveDrag(e: React.PointerEvent) {
    const d = drag.current;
    if (!d) return;
    const dx = (e.clientX - d.startX) / d.rect.width;
    const dy = (e.clientY - d.startY) / d.rect.height;
    if (d.mode === "move") {
      onChange({
        ...d.orig,
        x: Math.max(0, Math.min(d.orig.x + dx, 1 - d.orig.w)),
        y: Math.max(0, Math.min(d.orig.y + dy, 1 - d.orig.h))
      });
    } else {
      onChange({
        ...d.orig,
        w: Math.max(0.02, Math.min(d.orig.w + dx, 1 - d.orig.x)),
        h: Math.max(0.012, Math.min(d.orig.h + dy, 1 - d.orig.y))
      });
    }
  }

  function endDrag() {
    drag.current = null;
  }

  return (
    <div
      className="overflow-hidden rounded-2xl border"
      style={{
        borderColor: "var(--qg-border)",
        backgroundColor: "var(--qg-card-bg)"
      }}
    >
      <div
        className="flex items-center justify-between border-b px-3 py-1.5"
        style={{ borderColor: "var(--qg-border-soft)" }}
      >
        <span className="text-[10px] uppercase tracking-wider text-[var(--qg-text-soft)]">
          Page {page}
        </span>
        {editable && activeTool ? (
          <span className="text-[10px] text-[var(--qg-accent)]">
            Cliquez pour placer : {KIND_META[activeTool]?.label}
          </span>
        ) : null}
      </div>
      <div
        ref={ref}
        onClick={pageClick}
        className={`relative w-full select-none ${
          editable && activeTool ? "cursor-crosshair" : ""
        }`}
        style={{ backgroundColor: "#ffffff" }}
      >
        {imgUrl ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={imgUrl}
            alt={`Page ${page}`}
            className="block w-full"
            draggable={false}
          />
        ) : (
          <div className="flex aspect-[8.5/11] w-full items-center justify-center">
            <Loader2 className="h-5 w-5 animate-spin text-slate-400" />
          </div>
        )}

        {fields.map((f) => {
          const color = signerColor(signers, f.signer_id);
          const signer = signers.find((s) => s.id === f.signer_id);
          const selected = selectedFieldId === f.id;
          const meta = KIND_META[f.kind];
          const Icon = meta?.icon || Type;
          return (
            <div
              key={f.id}
              onPointerDown={(e) => startDrag(e, f, "move")}
              onPointerMove={moveDrag}
              onPointerUp={endDrag}
              onPointerCancel={endDrag}
              onClick={(e) => e.stopPropagation()}
              className={`absolute flex items-center gap-1 overflow-hidden rounded border px-1 ${
                editable ? "cursor-move" : ""
              }`}
              style={{
                left: `${f.x * 100}%`,
                top: `${f.y * 100}%`,
                width: `${f.w * 100}%`,
                height: `${f.h * 100}%`,
                borderColor: color,
                borderWidth: selected ? 2 : 1,
                backgroundColor: `${color}22`,
                touchAction: "none"
              }}
              title={`${meta?.label || f.kind} — ${
                signer ? `${signer.first_name} ${signer.last_name}` : ""
              }`}
            >
              {f.value_text || (!editable && signer?.signed_at &&
              (f.kind === "signature" || f.kind === "initiales")) ? (
                <span
                  className="truncate text-[10px] font-medium"
                  style={{ color: "#111827" }}
                >
                  {f.value_text || "✓ Signé"}
                </span>
              ) : (
                <>
                  <span className="shrink-0" style={{ color }}>
                    <Icon className="h-3 w-3" />
                  </span>
                  <span
                    className="truncate text-[9px] font-medium"
                    style={{ color }}
                  >
                    {f.label || meta?.label || f.kind}
                    {signer ? ` · ${signer.first_name}` : ""}
                  </span>
                </>
              )}
              {editable && selected ? (
                <>
                  <button
                    type="button"
                    onPointerDown={(e) => e.stopPropagation()}
                    onClick={(e) => {
                      e.stopPropagation();
                      onDelete(f.id);
                    }}
                    className="absolute -right-0 -top-0 flex h-4 w-4 items-center justify-center rounded-bl bg-rose-600 text-white"
                    aria-label="Supprimer la zone"
                  >
                    <X className="h-2.5 w-2.5" />
                  </button>
                  <div
                    onPointerDown={(e) => {
                      startDrag(e, f, "resize");
                    }}
                    onPointerMove={moveDrag}
                    onPointerUp={endDrag}
                    className="absolute bottom-0 right-0 h-3 w-3 cursor-nwse-resize"
                    style={{ backgroundColor: color }}
                  />
                </>
              ) : null}
            </div>
          );
        })}
      </div>
    </div>
  );
}

/* ---------- Modal ajout de signataire ---------- */

function AddSignerModal({
  docId,
  nextOrder,
  onClose,
  onAdded
}: {
  docId: number;
  nextOrder: number;
  onClose: () => void;
  onAdded: () => void | Promise<void>;
}) {
  const [tab, setTab] = useState<"banque" | "manuel">("banque");
  const [contacts, setContacts] = useState<UnifiedContact[]>([]);
  const [contactsLoading, setContactsLoading] = useState(false);
  const [search, setSearch] = useState("");

  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [smsAuth, setSmsAuth] = useState(false);
  const [contactRef, setContactRef] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (tab !== "banque" || contacts.length > 0) return;
    setContactsLoading(true);
    authedFetch("/api/v1/contacts/all")
      .then(async (res) => {
        if (res.ok) setContacts((await res.json()) as UnifiedContact[]);
      })
      .catch(() => undefined)
      .finally(() => setContactsLoading(false));
  }, [tab, contacts.length]);

  const filteredContacts = useMemo(() => {
    const needle = search.trim().toLowerCase();
    const base = contacts.filter((c) => c.email);
    if (!needle) return base.slice(0, 30);
    return base
      .filter((c) =>
        `${c.full_name} ${c.company || ""} ${c.email || ""}`
          .toLowerCase()
          .includes(needle)
      )
      .slice(0, 30);
  }, [contacts, search]);

  function pickContact(c: UnifiedContact) {
    const parts = c.full_name.trim().split(/\s+/);
    setFirstName(parts[0] || "");
    setLastName(parts.slice(1).join(" ") || parts[0] || "");
    setEmail(c.email || "");
    setPhone(c.phone || "");
    setContactRef(c.id);
    setTab("manuel");
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    if (smsAuth && !phone.trim()) {
      setErr("Numéro de téléphone requis pour l'authentification SMS.");
      return;
    }
    setBusy(true);
    try {
      const res = await authedFetch(
        `/api/v1/esign/documents/${docId}/signers`,
        {
          method: "POST",
          body: JSON.stringify({
            first_name: firstName.trim(),
            last_name: lastName.trim(),
            email: email.trim(),
            phone: phone.trim() || null,
            require_sms_auth: smsAuth,
            order_index: nextOrder,
            contact_ref: contactRef
          })
        }
      );
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        throw new Error(
          typeof body?.detail === "string"
            ? body.detail
            : `Erreur HTTP ${res.status}`
        );
      }
      await onAdded();
    } catch (e2) {
      setErr(e2 instanceof Error ? e2.message : "Ajout échoué.");
      setBusy(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      onClick={() => !busy && onClose()}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-md rounded-2xl border border-brand-800 bg-brand-900 p-5"
      >
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-white">
            Ajouter un signataire
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="btn-ghost btn-xs"
            disabled={busy}
          >
            ✕
          </button>
        </div>

        <div className="mb-3 flex gap-1">
          {(
            [
              ["banque", "Banque de contacts"],
              ["manuel", "Créer / modifier"]
            ] as const
          ).map(([key, label]) => (
            <button
              key={key}
              type="button"
              onClick={() => setTab(key)}
              className={`rounded-lg px-3 py-1.5 text-xs font-medium ${
                tab === key
                  ? "bg-accent-500 text-brand-950"
                  : "text-white/60 hover:bg-white/5 hover:text-white"
              }`}
            >
              {label}
            </button>
          ))}
        </div>

        {tab === "banque" ? (
          <div>
            <div className="relative mb-2">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-white/40" />
              <input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Rechercher un contact…"
                className="input w-full pl-8 text-xs"
                autoFocus
              />
            </div>
            <div className="max-h-64 space-y-1 overflow-y-auto">
              {contactsLoading ? (
                <div className="flex justify-center py-6">
                  <Loader2 className="h-4 w-4 animate-spin text-accent-500" />
                </div>
              ) : filteredContacts.length === 0 ? (
                <p className="py-6 text-center text-xs text-white/50">
                  Aucun contact avec courriel trouvé.
                </p>
              ) : (
                filteredContacts.map((c) => (
                  <button
                    key={c.id}
                    type="button"
                    onClick={() => pickContact(c)}
                    className="flex w-full items-center justify-between gap-2 rounded-lg border border-brand-800 px-3 py-2 text-left hover:border-accent-500/60"
                  >
                    <span className="min-w-0">
                      <span className="block truncate text-xs font-medium text-white">
                        {c.full_name}
                        {c.company ? (
                          <span className="text-white/50">
                            {" "}
                            · {c.company}
                          </span>
                        ) : null}
                      </span>
                      <span className="block truncate text-[11px] text-white/50">
                        {c.email}
                        {c.phone ? ` · ${c.phone}` : ""}
                      </span>
                    </span>
                    <Plus className="h-3.5 w-3.5 shrink-0 text-accent-500" />
                  </button>
                ))
              )}
            </div>
          </div>
        ) : (
          <form onSubmit={submit} className="space-y-3">
            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className="label">Prénom</label>
                <input
                  value={firstName}
                  onChange={(e) => setFirstName(e.target.value)}
                  required
                  className="input w-full text-xs"
                />
              </div>
              <div>
                <label className="label">Nom</label>
                <input
                  value={lastName}
                  onChange={(e) => setLastName(e.target.value)}
                  required
                  className="input w-full text-xs"
                />
              </div>
            </div>
            <div>
              <label className="label">Courriel</label>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                className="input w-full text-xs"
              />
            </div>
            <div>
              <label className="label">
                Téléphone {smsAuth ? "(requis)" : "(optionnel)"}
              </label>
              <input
                type="tel"
                value={phone}
                onChange={(e) => setPhone(e.target.value)}
                placeholder="+1 514 555 0123"
                className="input w-full text-xs"
              />
            </div>
            <label className="flex items-start gap-2 text-xs text-white/70">
              <input
                type="checkbox"
                checked={smsAuth}
                onChange={(e) => setSmsAuth(e.target.checked)}
                className="mt-0.5"
              />
              <span>
                Signature authentifiée par SMS — un code de validation sera
                envoyé à ce numéro et devra être saisi avant de signer.
              </span>
            </label>
            {err ? <p className="text-xs text-rose-400">{err}</p> : null}
            <div className="flex justify-end gap-2 pt-1">
              <button
                type="button"
                onClick={onClose}
                className="btn-secondary btn-sm"
                disabled={busy}
              >
                Annuler
              </button>
              <button
                type="submit"
                disabled={busy}
                className="btn-accent btn-sm inline-flex items-center gap-1.5"
              >
                {busy ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : null}
                Ajouter
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
