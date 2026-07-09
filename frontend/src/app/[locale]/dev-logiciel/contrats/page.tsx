"use client";

import { useEffect, useMemo, useState } from "react";
import {
  CheckCircle2,
  Copy,
  ExternalLink,
  FileSignature,
  Loader2,
  Plus,
  Send,
  Trash2,
  Wallet,
  X
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { AppTopbar } from "@/components/app-topbar";
import { useConfirm } from "@/components/confirm-dialog";
import { authedFetch } from "@/lib/auth";
import { useDevlogLayout } from "../layout";

type Contract = {
  id: number;
  title: string;
  body: string | null;
  status: string;
  soumission_id: number | null;
  client_id: number | null;
  project_id: number | null;
  signature_token: string | null;
  sent_at: string | null;
  signed_at: string | null;
  signed_name: string | null;
  deposit_required_cents: number | null;
  deposit_paid_at: string | null;
  deposit_paid_amount_cents: number | null;
  created_at: string;
};

type Project = {
  id: number;
  name: string;
  status: string;
  started_at: string | null;
};

type RefItem = { id: number; name: string };
type SoumRef = { id: number; title: string };
type ProjectRef = { id: number; name: string; started_at?: string | null };

type Column = {
  id: string;
  label: string;
  dot: string;
};

// Colonnes du kanban — alignees sur les statuts backend
// (DevlogContract.status : brouillon | envoye | signe | annule).
const COLUMNS: Column[] = [
  { id: "brouillon", label: "Brouillon", dot: "bg-white/40" },
  { id: "envoye", label: "Envoyé", dot: "bg-blue-400" },
  { id: "signe", label: "Signé", dot: "bg-emerald-400" },
  { id: "annule", label: "Annulé/Refusé", dot: "bg-rose-500" }
];

const STATUS_OPTIONS = COLUMNS.map((c) => ({ key: c.id, label: c.label }));

type Draft = {
  title: string;
  body: string;
  status: string;
  soumission_id: string;
  client_id: string;
  project_id: string;
};

const EMPTY_DRAFT: Draft = {
  title: "",
  body: "",
  status: "brouillon",
  soumission_id: "",
  client_id: "",
  project_id: ""
};

const DEFAULT_TEMPLATE = `# Contrat de développement logiciel

**Entre** : Horizon Dév. logiciel
**Et** : [Nom du client]

## 1. Objet
Le présent contrat porte sur la livraison du projet décrit dans la soumission acceptée.

## 2. Livrables
[Détailler les livrables]

## 3. Échéancier
- Démarrage : [date]
- Livraison : [date]

## 4. Tarification
[Détails de la soumission acceptée]

## 5. Conditions de paiement
- Dépôt : 30 % à la signature
- Solde : à la livraison

## 6. Propriété intellectuelle
[Clauses standard]

## 7. Confidentialité
Les parties s'engagent à respecter la confidentialité des informations échangées.

Signé par les parties.`;

/** Extrait un montant TTC depuis le body Markdown (cherche
 *  "Frais de mise en oeuvre ... : X $") — best-effort pour
 *  afficher un prix sur la carte kanban. */
function extractAmount(body: string | null): number | null {
  if (!body) return null;
  // Cherche un nombre format "X XXX.XX" ou "X,XXX.XX" apres "Frais de mise en oeuvre"
  const re = /[Ff]rais de mise en [oô]euvre[^:]*:\s*([\d\s,.]+)\s*\$/;
  const m = body.match(re);
  if (!m) return null;
  const raw = m[1].replace(/\s/g, "").replace(/,/g, "");
  const v = Number(raw);
  return Number.isFinite(v) && v > 0 ? v : null;
}

function fmtMoney(n: number | null): string {
  if (n == null) return "—";
  return new Intl.NumberFormat("fr-CA", {
    style: "currency",
    currency: "CAD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  }).format(n);
}

export default function DevlogContractsPage() {
  const { onOpenSidebar } = useDevlogLayout();
  const confirm = useConfirm();
  const router = useRouter();
  const [items, setItems] = useState<Contract[]>([]);
  const [clients, setClients] = useState<RefItem[]>([]);
  const [projects, setProjects] = useState<ProjectRef[]>([]);
  const [soumissions, setSoumissions] = useState<SoumRef[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");

  const [editing, setEditing] = useState<number | "new" | null>(null);
  const [draft, setDraft] = useState<Draft>(EMPTY_DRAFT);
  const [saving, setSaving] = useState(false);
  const [linkCopied, setLinkCopied] = useState<number | null>(null);

  // Modal "marquer dépôt payé" — id du contrat ciblé + montant saisi (en $).
  const [depositTarget, setDepositTarget] = useState<Contract | null>(null);
  const [depositAmount, setDepositAmount] = useState("");
  const [depositSaving, setDepositSaving] = useState(false);

  // Drag-and-drop state — identique au pattern soumissions kanban.
  const [dragging, setDragging] = useState<number | null>(null);
  const [hoverCol, setHoverCol] = useState<string | null>(null);

  async function loadAll() {
    try {
      const [cr, clr, pr, sr] = await Promise.all([
        authedFetch("/api/v1/devlog/contracts"),
        authedFetch("/api/v1/devlog/clients"),
        authedFetch("/api/v1/devlog/projects"),
        authedFetch("/api/v1/devlog/soumissions")
      ]);
      if (!cr.ok) throw new Error("Chargement impossible");
      setItems(await cr.json());
      if (clr.ok) setClients(await clr.json());
      if (pr.ok) setProjects(await pr.json());
      if (sr.ok) setSoumissions(await sr.json());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erreur");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadAll();
  }, []);

  const clientName = useMemo(
    () => new Map(clients.map((c) => [c.id, c.name])),
    [clients]
  );

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return items.filter((c) =>
      q
        ? `${c.title} ${c.signed_name || ""}`
            .toLowerCase()
            .includes(q)
        : true
    );
  }, [items, search]);

  // Regroupement par colonne. Tout statut inconnu retombe sur "brouillon".
  const byColumn = useMemo(() => {
    const map: Record<string, Contract[]> = Object.fromEntries(
      COLUMNS.map((c) => [c.id, [] as Contract[]])
    );
    for (const c of filtered) {
      const target = COLUMNS.find((col) => col.id === c.status)
        ? c.status
        : "brouillon";
      map[target].push(c);
    }
    return map;
  }, [filtered]);

  /** Deplace un contrat vers un nouveau statut via PATCH (idempotent).
   *  Update optimiste avec rollback en cas d'erreur. */
  async function moveContract(id: number, newStatus: string) {
    const prev = items;
    setItems((xs) =>
      xs.map((x) => (x.id === id ? { ...x, status: newStatus } : x))
    );
    try {
      const res = await authedFetch(`/api/v1/devlog/contracts/${id}`, {
        method: "PATCH",
        body: JSON.stringify({ status: newStatus })
      });
      if (!res.ok) throw new Error();
    } catch {
      setItems(prev);
      setError(
        "Mise à jour du statut impossible (contrat signé verrouillé ?)."
      );
    }
  }

  function openNew() {
    setDraft({ ...EMPTY_DRAFT, body: DEFAULT_TEMPLATE });
    setEditing("new");
  }

  // openEdit retiré (mai 2026 #496) — l'ouverture d'un contrat existant
  // navigue désormais vers la page complète /dev-logiciel/contrats/[id]
  // au lieu du drawer latéral (UX cohérente avec les autres entités
  // du pôle : soumissions, projets, factures).

  async function saveDraft() {
    if (!draft.title.trim()) return;
    setSaving(true);
    try {
      const payload = {
        title: draft.title.trim(),
        body: draft.body.trim() || null,
        status: draft.status,
        soumission_id: draft.soumission_id ? Number(draft.soumission_id) : null,
        client_id: draft.client_id ? Number(draft.client_id) : null,
        project_id: draft.project_id ? Number(draft.project_id) : null
      };
      const r =
        editing === "new"
          ? await authedFetch("/api/v1/devlog/contracts", {
              method: "POST",
              body: JSON.stringify(payload)
            })
          : await authedFetch(`/api/v1/devlog/contracts/${editing}`, {
              method: "PATCH",
              body: JSON.stringify(payload)
            });
      if (!r.ok) throw new Error();
      setEditing(null);
      await loadAll();
    } catch {
      setError("Enregistrement impossible (le contrat est peut-être signé).");
    } finally {
      setSaving(false);
    }
  }

  async function sendContract(id: number) {
    const ok = await confirm({
      title: "Générer le lien de signature ?",
      description:
        "Un lien public sera créé. Tu pourras le copier et l'envoyer au client par courriel. Le contrat passera en « Envoyé ».",
      confirmLabel: "Générer"
    });
    if (!ok) return;
    try {
      const r = await authedFetch(`/api/v1/devlog/contracts/${id}/send`, {
        method: "POST"
      });
      if (!r.ok) throw new Error();
      await loadAll();
    } catch {
      setError("Génération du lien impossible");
    }
  }

  /** Ouvre la modal de saisie du dépôt. Pré-remplit avec le dépôt
   *  requis si disponible, sinon avec la moitié du montant détecté
   *  dans le body du contrat (heuristique : 50 % du forfait initial). */
  function openDepositModal(c: Contract) {
    setDepositTarget(c);
    if (c.deposit_paid_amount_cents != null) {
      setDepositAmount((c.deposit_paid_amount_cents / 100).toFixed(2));
    } else if (c.deposit_required_cents != null) {
      setDepositAmount((c.deposit_required_cents / 100).toFixed(2));
    } else {
      const amt = extractAmount(c.body);
      setDepositAmount(amt != null ? (amt / 2).toFixed(2) : "");
    }
  }

  async function saveDepositPayment() {
    if (!depositTarget) return;
    const dollars = Number(depositAmount.replace(",", "."));
    if (!Number.isFinite(dollars) || dollars < 0) {
      setError("Montant invalide");
      return;
    }
    const amount_cents = Math.round(dollars * 100);
    setDepositSaving(true);
    try {
      const r = await authedFetch(
        `/api/v1/devlog/contracts/${depositTarget.id}/mark-deposit-paid`,
        {
          method: "POST",
          body: JSON.stringify({ amount_cents })
        }
      );
      if (!r.ok) throw new Error();
      setDepositTarget(null);
      setDepositAmount("");
      await loadAll();
    } catch {
      setError("Marquage du dépôt impossible");
    } finally {
      setDepositSaving(false);
    }
  }

  async function copyLink(c: Contract) {
    if (!c.signature_token) return;
    const url = `${window.location.origin}/sign-devlog/${c.signature_token}`;
    try {
      await navigator.clipboard.writeText(url);
      setLinkCopied(c.id);
      setTimeout(() => setLinkCopied(null), 2000);
    } catch {
      window.prompt("Copie ce lien :", url);
    }
  }

  async function deleteItem(id: number) {
    const ok = await confirm({
      title: "Supprimer ce contrat ?",
      description: "Cette action est irréversible.",
      confirmLabel: "Supprimer",
      destructive: true
    });
    if (!ok) return;
    try {
      const r = await authedFetch(`/api/v1/devlog/contracts/${id}`, {
        method: "DELETE"
      });
      if (!r.ok) throw new Error();
      setEditing(null);
      setItems((xs) => xs.filter((c) => c.id !== id));
    } catch {
      setError("Suppression impossible");
    }
  }

  return (
    <div className="min-h-screen bg-brand-950">
      <AppTopbar
        breadcrumbs={[
          { label: "Développement logiciel", href: "/dev-logiciel" as any },
          { label: "Contrats" }
        ]}
        onOpenSidebar={onOpenSidebar}
        searchPlaceholder="Chercher un contrat…"
        onSearch={setSearch}
        rightSlot={
          <button
            type="button"
            onClick={openNew}
            className="inline-flex items-center gap-1.5 rounded-lg bg-accent-500 px-3 py-1.5 text-sm font-semibold text-white hover:bg-accent-400"
          >
            <Plus className="h-4 w-4" />
            Nouveau contrat
          </button>
        }
      />

      <div className="p-4 lg:p-6">
        {error ? (
          <div className="mb-3 flex items-start justify-between gap-2 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">
            <span>{error}</span>
            <button type="button" onClick={() => setError(null)}>
              <X className="h-4 w-4" />
            </button>
          </div>
        ) : null}

        {loading ? (
          <div className="mt-10 flex justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-accent-500" />
          </div>
        ) : items.length === 0 ? (
          <p className="mt-10 text-center text-sm text-white/40">
            Aucun contrat. Clique sur « Nouveau contrat ».
          </p>
        ) : (
          <div className="flex gap-4 overflow-x-auto pb-4">
            {COLUMNS.map((col) => {
              const cards = byColumn[col.id] || [];
              const isHover = hoverCol === col.id;
              return (
                <div
                  key={col.id}
                  onDragOver={(e) => {
                    e.preventDefault();
                    setHoverCol(col.id);
                  }}
                  onDragLeave={() =>
                    setHoverCol((h) => (h === col.id ? null : h))
                  }
                  onDrop={() => {
                    if (dragging == null) return;
                    const item = items.find((c) => c.id === dragging);
                    if (item && item.status !== col.id)
                      void moveContract(dragging, col.id);
                    setDragging(null);
                    setHoverCol(null);
                  }}
                  className={`flex w-80 min-w-[320px] flex-shrink-0 flex-col rounded-xl border bg-brand-900/60 ${
                    isHover
                      ? "border-accent-500 bg-brand-900"
                      : "border-brand-800"
                  }`}
                >
                  <div className="flex items-center justify-between border-b border-brand-800 px-4 py-3">
                    <div className="flex items-center gap-2">
                      <span className={`h-2 w-2 rounded-full ${col.dot}`} />
                      <h2 className="text-sm font-semibold text-white">
                        {col.label}
                      </h2>
                      <span className="rounded-md bg-brand-950 px-2 py-0.5 text-xs font-semibold text-white/70">
                        {cards.length}
                      </span>
                    </div>
                    <span className="text-xs font-semibold text-emerald-300">
                      {fmtMoney(
                        cards.reduce(
                          (sum, c) => sum + (extractAmount(c.body) || 0),
                          0
                        )
                      )}
                    </span>
                  </div>

                  <div className="flex-1 space-y-3 p-3">
                    {cards.length === 0 ? (
                      <p className="py-8 text-center text-xs text-white/40">
                        Aucun contrat
                      </p>
                    ) : (
                      cards.map((c) => {
                        const proj = c.project_id
                          ? projects.find((p) => p.id === c.project_id) ??
                            null
                          : null;
                        return (
                          <ContractCard
                            key={c.id}
                            contract={c}
                            clientName={
                              c.client_id
                                ? clientName.get(c.client_id) ?? null
                                : null
                            }
                            amount={extractAmount(c.body)}
                            project={proj}
                            dragging={dragging === c.id}
                            linkCopied={linkCopied === c.id}
                            onDragStart={() => setDragging(c.id)}
                            onDragEnd={() => {
                              setDragging(null);
                              setHoverCol(null);
                            }}
                            onOpen={() =>
                              router.push(
                                `/dev-logiciel/contrats/${c.id}` as any
                              )
                            }
                            onSend={() => void sendContract(c.id)}
                            onCopyLink={() => void copyLink(c)}
                            onMarkDeposit={() => openDepositModal(c)}
                          />
                        );
                      })
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {editing != null ? (
        <Drawer
          isNew={editing === "new"}
          draft={draft}
          setDraft={setDraft}
          saving={saving}
          clients={clients}
          projects={projects}
          soumissions={soumissions}
          locked={
            typeof editing === "number" &&
            items.find((c) => c.id === editing)?.status === "signe"
          }
          onClose={() => setEditing(null)}
          onSave={saveDraft}
          onDelete={
            typeof editing === "number" ? () => deleteItem(editing) : undefined
          }
        />
      ) : null}

      {depositTarget != null ? (
        <DepositModal
          contract={depositTarget}
          amount={depositAmount}
          saving={depositSaving}
          onAmountChange={setDepositAmount}
          onClose={() => {
            setDepositTarget(null);
            setDepositAmount("");
          }}
          onSave={() => void saveDepositPayment()}
        />
      ) : null}
    </div>
  );
}

function DepositModal({
  contract,
  amount,
  saving,
  onAmountChange,
  onClose,
  onSave
}: {
  contract: Contract;
  amount: string;
  saving: boolean;
  onAmountChange: (v: string) => void;
  onClose: () => void;
  onSave: () => void;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <button
        type="button"
        aria-label="Fermer"
        onClick={onClose}
        className="absolute inset-0 bg-black/70 backdrop-blur-sm"
      />
      <div className="relative w-full max-w-md rounded-xl border border-brand-800 bg-brand-950 p-5">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-bold text-white">
            Marquer le dépôt payé
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1 text-white/50 hover:bg-brand-900 hover:text-white"
          >
            <X className="h-5 w-5" />
          </button>
        </div>
        <p className="mb-3 text-xs text-white/60">
          Contrat <strong className="text-white">{contract.title}</strong>.
          Saisis le montant exact reçu (en $ CA). Si le contrat est déjà
          signé, le projet sera démarré automatiquement.
        </p>
        <label className="mb-3 block">
          <span className="mb-1 block text-xs font-medium text-white/60">
            Montant reçu ($)
          </span>
          <input
            type="number"
            min="0"
            step="0.01"
            value={amount}
            onChange={(e) => onAmountChange(e.target.value)}
            className="input text-sm"
            placeholder="Ex. 2500.00"
            autoFocus
          />
        </label>
        <div className="flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-white/15 bg-white/5 px-3 py-1.5 text-sm font-semibold text-white/70 hover:bg-white/10"
          >
            Annuler
          </button>
          <button
            type="button"
            onClick={onSave}
            disabled={saving || !amount.trim()}
            className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-500 px-3 py-1.5 text-sm font-semibold text-white hover:bg-emerald-400 disabled:opacity-50"
          >
            {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
            Confirmer
          </button>
        </div>
      </div>
    </div>
  );
}

function ContractCard({
  contract: c,
  clientName,
  amount,
  project,
  dragging,
  linkCopied,
  onDragStart,
  onDragEnd,
  onOpen,
  onSend,
  onCopyLink,
  onMarkDeposit
}: {
  contract: Contract;
  clientName: string | null;
  amount: number | null;
  project: ProjectRef | null;
  dragging: boolean;
  linkCopied: boolean;
  onDragStart: () => void;
  onDragEnd: () => void;
  onOpen: () => void;
  onSend: () => void;
  onCopyLink: () => void;
  onMarkDeposit: () => void;
}) {
  const depositPaid = c.deposit_paid_at != null;
  const projectStarted = project?.started_at != null;
  return (
    <div
      draggable
      onDragStart={onDragStart}
      onDragEnd={onDragEnd}
      className={`group relative cursor-grab rounded-lg border border-brand-800 bg-brand-950 p-3 transition hover:border-accent-500 active:cursor-grabbing ${
        dragging ? "opacity-40" : ""
      }`}
    >
      <button
        type="button"
        onClick={(e) => {
          e.preventDefault();
          e.stopPropagation();
          onOpen();
        }}
        className="block w-full text-left"
      >
        <div className="flex items-start gap-2">
          <span className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-lg bg-accent-500/15 text-accent-500">
            <FileSignature className="h-4 w-4" />
          </span>
          <div className="min-w-0 flex-1">
            <p className="line-clamp-2 text-sm font-semibold text-white">
              {c.title}
            </p>
            {clientName ? (
              <p className="mt-0.5 truncate text-xs font-medium text-white/70">
                {clientName}
              </p>
            ) : (
              <p className="mt-0.5 truncate text-xs italic text-white/40">
                Sans client
              </p>
            )}
          </div>
        </div>

        {amount != null ? (
          <p className="mt-2 text-sm font-bold text-white">
            {fmtMoney(amount)}
            <span className="ml-1.5 text-[10px] font-semibold uppercase tracking-wider text-white/40">
              TTC
            </span>
          </p>
        ) : null}

        {/* Trace de signature ou d'envoi */}
        {c.status === "signe" && c.signed_at ? (
          <p className="mt-1.5 text-[11px] text-emerald-300">
            Signé le{" "}
            {new Date(c.signed_at).toLocaleDateString("fr-CA")}
            {c.signed_name ? ` par ${c.signed_name}` : ""}
          </p>
        ) : c.status === "envoye" && c.sent_at ? (
          <p className="mt-1.5 text-[11px] text-blue-300">
            Envoyé le {new Date(c.sent_at).toLocaleDateString("fr-CA")}
          </p>
        ) : (
          <p className="mt-1.5 text-[11px] text-white/40">
            Créé le {new Date(c.created_at).toLocaleDateString("fr-CA")}
          </p>
        )}

        {/* Badge dépôt — visible sur la colonne "signé". */}
        {c.status === "signe" ? (
          <p
            className={`mt-1 text-[11px] ${
              depositPaid ? "text-emerald-300" : "text-amber-300"
            }`}
          >
            {depositPaid
              ? `💰 Dépôt payé${
                  c.deposit_paid_amount_cents != null
                    ? " — " + fmtMoney(c.deposit_paid_amount_cents / 100)
                    : ""
                }`
              : "⏳ Dépôt à recevoir"}
          </p>
        ) : null}

        {/* Bandeau projet démarré */}
        {projectStarted && project?.started_at ? (
          <p className="mt-1 rounded-md bg-emerald-500/15 px-2 py-1 text-[11px] font-semibold text-emerald-300">
            Projet démarré le{" "}
            {new Date(project.started_at).toLocaleDateString("fr-CA")}
          </p>
        ) : null}
      </button>

      {/* Actions rapides — visibles sous la carte. */}
      <div className="mt-2 flex items-center gap-1.5 border-t border-brand-800 pt-2">
        {c.status === "brouillon" ? (
          <button
            type="button"
            onClick={(e) => {
              e.preventDefault();
              e.stopPropagation();
              onSend();
            }}
            title="Générer le lien de signature"
            className="inline-flex items-center gap-1 rounded-md border border-blue-500/40 bg-blue-500/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-blue-200 hover:brightness-110"
          >
            <Send className="h-3 w-3" /> Envoyer
          </button>
        ) : null}
        {c.signature_token ? (
          <button
            type="button"
            onClick={(e) => {
              e.preventDefault();
              e.stopPropagation();
              onCopyLink();
            }}
            title="Copier le lien de signature"
            className="inline-flex items-center gap-1 rounded-md border border-white/15 bg-white/5 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-white/70 hover:bg-white/10"
          >
            {linkCopied ? (
              <>
                <CheckCircle2 className="h-3 w-3 text-emerald-300" /> Copié
              </>
            ) : (
              <>
                <Copy className="h-3 w-3" /> Lien
              </>
            )}
          </button>
        ) : null}
        {!depositPaid ? (
          <button
            type="button"
            onClick={(e) => {
              e.preventDefault();
              e.stopPropagation();
              onMarkDeposit();
            }}
            title="Marquer le dépôt comme reçu"
            className="inline-flex items-center gap-1 rounded-md border border-amber-500/40 bg-amber-500/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-amber-200 hover:brightness-110"
          >
            <Wallet className="h-3 w-3" /> Dépôt
          </button>
        ) : null}
        {project ? (
          <Link
            href={`/fr/app/dev-logiciel/projets/${project.id}` as any}
            onClick={(e) => e.stopPropagation()}
            title="Ouvrir le projet"
            className="inline-flex items-center gap-1 rounded-md border border-emerald-500/40 bg-emerald-500/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-emerald-200 hover:brightness-110"
          >
            <ExternalLink className="h-3 w-3" /> Projet
          </Link>
        ) : null}
        <button
          type="button"
          onClick={(e) => {
            e.preventDefault();
            e.stopPropagation();
            onOpen();
          }}
          className="ml-auto inline-flex items-center rounded-md border border-white/15 bg-white/5 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-white/70 hover:bg-white/10"
        >
          Voir
        </button>
      </div>
    </div>
  );
}

function Drawer({
  isNew,
  draft,
  setDraft,
  saving,
  clients,
  projects,
  soumissions,
  locked,
  onClose,
  onSave,
  onDelete
}: {
  isNew: boolean;
  draft: Draft;
  setDraft: (d: Draft) => void;
  saving: boolean;
  clients: RefItem[];
  projects: ProjectRef[];
  soumissions: SoumRef[];
  locked?: boolean;
  onClose: () => void;
  onSave: () => void;
  onDelete?: () => void;
}) {
  const set = (k: keyof Draft, v: string) => setDraft({ ...draft, [k]: v });
  const inputCls = "input text-sm";

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <button
        type="button"
        aria-label="Fermer"
        onClick={onClose}
        className="absolute inset-0 bg-black/70 backdrop-blur-sm"
      />
      <div className="relative flex h-full w-full max-w-2xl flex-col border-l border-brand-800 bg-brand-950">
        <div className="flex items-center justify-between border-b border-brand-800 px-4 py-3">
          <h2 className="text-sm font-bold text-white">
            {isNew ? "Nouveau contrat" : locked ? "Contrat signé (lecture seule)" : "Modifier le contrat"}
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1 text-white/50 hover:bg-brand-900 hover:text-white"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="flex-1 space-y-3 overflow-y-auto px-4 py-4">
          <Field label="Titre *">
            <input
              value={draft.title}
              onChange={(e) => set("title", e.target.value)}
              disabled={locked}
              className={inputCls}
            />
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Client">
              <select
                value={draft.client_id}
                onChange={(e) => set("client_id", e.target.value)}
                disabled={locked}
                className={inputCls}
              >
                <option value="">—</option>
                {clients.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Statut">
              <select
                value={draft.status}
                onChange={(e) => set("status", e.target.value)}
                disabled={locked}
                className={inputCls}
              >
                {STATUS_OPTIONS.map((s) => (
                  <option key={s.key} value={s.key}>
                    {s.label}
                  </option>
                ))}
              </select>
            </Field>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Projet">
              <select
                value={draft.project_id}
                onChange={(e) => set("project_id", e.target.value)}
                disabled={locked}
                className={inputCls}
              >
                <option value="">—</option>
                {projects.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Soumission liée">
              <select
                value={draft.soumission_id}
                onChange={(e) => set("soumission_id", e.target.value)}
                disabled={locked}
                className={inputCls}
              >
                <option value="">—</option>
                {soumissions.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.title}
                  </option>
                ))}
              </select>
            </Field>
          </div>
          <Field label="Contenu du contrat (Markdown)">
            <textarea
              value={draft.body}
              onChange={(e) => set("body", e.target.value)}
              disabled={locked}
              rows={18}
              className={inputCls}
              placeholder="# Contrat..."
            />
          </Field>
        </div>

        <div className="flex items-center gap-2 border-t border-brand-800 px-4 py-3">
          <button
            type="button"
            onClick={onSave}
            disabled={saving || !draft.title.trim() || locked}
            className="inline-flex flex-1 items-center justify-center gap-1.5 rounded-lg bg-accent-500 px-3 py-2 text-sm font-semibold text-white hover:bg-accent-400 disabled:opacity-50"
          >
            {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
            Enregistrer
          </button>
          {onDelete ? (
            <button
              type="button"
              onClick={onDelete}
              title="Supprimer"
              className="rounded-lg border border-rose-500/40 bg-rose-500/10 p-2 text-rose-300 hover:bg-rose-500/20"
            >
              <Trash2 className="h-4 w-4" />
            </button>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function Field({
  label,
  children
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-white/60">
        {label}
      </span>
      {children}
    </label>
  );
}
