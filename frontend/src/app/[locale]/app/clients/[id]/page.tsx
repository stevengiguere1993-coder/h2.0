"use client";

import { useEffect, useMemo, useState } from "react";
import { useParams, useRouter as useNextRouter } from "next/navigation";
import {
  ArrowLeft,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  ExternalLink,
  FileText,
  Image as ImageIcon,
  Loader2,
  Save,
  Trash2
} from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { AddressInput } from "@/components/address-input";
import { CallButton } from "@/components/call-button";
import { CommunicationsTimeline } from "@/components/communications-timeline";
import { MeasurementsPanel } from "@/components/measurements-panel";
import { SalesTasksPanel } from "@/components/sales-tasks-panel";
import { Link } from "@/i18n/navigation";
import { useAppLayout } from "../../layout";
import { authedFetch } from "@/lib/auth";
import { useConfirm } from "@/components/confirm-dialog";

type Client = {
  id: number;
  name: string;
  email: string | null;
  phone: string | null;
  address: string | null;
  notes: string | null;
  contact_request_id: number | null;
  qbo_customer_id: string | null;
  created_at: string;
  projects?: Array<{ id: number; name: string; status: string }>;
};

export default function ClientDetailPage() {
  const confirm = useConfirm();
  const { onOpenSidebar } = useAppLayout();
  const params = useParams<{ id: string }>();
  const id = Number(params.id);
  const router = useNextRouter();

  const [c, setC] = useState<Client | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [address, setAddress] = useState("");
  const [notes, setNotes] = useState("");

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const res = await authedFetch(`/api/v1/clients/${id}`);
        if (!res.ok) throw new Error(`http_${res.status}`);
        const data = (await res.json()) as Client;
        if (cancelled) return;
        setC(data);
        setName(data.name);
        setEmail(data.email || "");
        setPhone(data.phone || "");
        setAddress(data.address || "");
        setNotes(data.notes || "");
      } catch {
        if (!cancelled) setError("Client introuvable.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    if (id) load();
    return () => {
      cancelled = true;
    };
  }, [id]);

  const dirty = useMemo(() => {
    if (!c) return false;
    return (
      name !== c.name ||
      email !== (c.email || "") ||
      phone !== (c.phone || "") ||
      address !== (c.address || "") ||
      notes !== (c.notes || "")
    );
  }, [c, name, email, phone, address, notes]);

  async function saveAll() {
    if (!c) return;
    setSaving(true);
    setError(null);
    try {
      const payload = {
        name: name.trim(),
        email: email.trim() || null,
        phone: phone.trim() || null,
        address: address.trim() || null,
        notes: notes.trim() || null
      };
      const res = await authedFetch(`/api/v1/clients/${id}`, {
        method: "PUT",
        body: JSON.stringify(payload)
      });
      if (!res.ok) throw new Error();
      const updated = (await res.json()) as Client;
      setC(updated);
    } catch {
      setError("Sauvegarde échouée.");
    } finally {
      setSaving(false);
    }
  }

  async function onDelete() {
    if (!c) return;
    if (!(await confirm(`Supprimer définitivement « ${c.name} » et tous ses projets ?`)))
      return;
    setDeleting(true);
    try {
      const res = await authedFetch(`/api/v1/clients/${id}`, {
        method: "DELETE"
      });
      if (!res.ok) throw new Error();
      router.replace("/app/clients");
    } catch {
      setDeleting(false);
      setError("Suppression échouée.");
    }
  }

  return (
    <>
      <AppTopbar
        breadcrumbs={[{ label: "Construction", href: "/app" }, { label: "Clients" }]}
        onOpenSidebar={onOpenSidebar}
      />

      <div className="p-4 lg:p-6">
        <Link
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          href={"/app/clients" as any}
          className="inline-flex items-center text-sm text-white/70 hover:text-accent-500"
        >
          <ArrowLeft className="mr-1 h-4 w-4" /> Retour aux clients
        </Link>

        {loading ? (
          <div className="flex min-h-[40vh] items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-accent-500" />
          </div>
        ) : error && !c ? (
          <p className="mt-6 rounded-lg border border-rose-500/40 bg-rose-500/10 px-4 py-2 text-sm text-rose-300">
            {error}
          </p>
        ) : c ? (
          <>
            <header className="mt-6 flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
              <div>
                <h1 className="text-2xl font-bold text-white">{c.name}</h1>
                <p className="mt-1 text-xs text-white/50">
                  Client depuis le{" "}
                  {new Date(c.created_at).toLocaleDateString("fr-CA", {
                    day: "numeric",
                    month: "long",
                    year: "numeric"
                  })}
                  {c.contact_request_id ? (
                    <>
                      {" · "}
                      <Link
                        // eslint-disable-next-line @typescript-eslint/no-explicit-any
                        href={`/app/crm/${c.contact_request_id}` as any}
                        className="underline decoration-dotted hover:text-accent-500"
                      >
                        Converti d&apos;un prospect
                      </Link>
                    </>
                  ) : null}
                </p>
              </div>
              <div className="flex flex-wrap items-start gap-2">
                <QboPushButton client={c} onSynced={(qboId) =>
                  setC((prev) =>
                    prev ? { ...prev, qbo_customer_id: qboId } : prev
                  )
                } />
                <button
                  type="button"
                  onClick={onDelete}
                  disabled={deleting}
                  className="inline-flex items-center gap-2 self-start rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2.5 text-sm font-medium text-rose-300 hover:bg-rose-500/20"
                >
                  {deleting ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <Trash2 className="h-4 w-4" />
                  )}
                  Supprimer
                </button>
              </div>
            </header>

            {error ? (
              <p className="mt-4 rounded-lg border border-rose-500/40 bg-rose-500/10 px-4 py-2 text-sm text-rose-300">
                {error}
              </p>
            ) : null}

            <div className="mt-6 max-w-3xl">
              <ClientTabs
                client={c}
                name={name}
                setName={setName}
                email={email}
                setEmail={setEmail}
                phone={phone}
                setPhone={setPhone}
                address={address}
                setAddress={setAddress}
                notes={notes}
                setNotes={setNotes}
                saving={saving}
                dirty={dirty}
                onSave={saveAll}
              />
            </div>
          </>
        ) : null}
      </div>
    </>
  );
}

// ---------------------------------------------------------------------------
// ClientTabs — navigation horizontale entre les sections de la fiche
// ---------------------------------------------------------------------------

type TabKey =
  | "infos"
  | "projets"
  | "communications"
  | "documents"
  | "mesures"
  | "suivi";

function ClientTabs({
  client,
  name,
  setName,
  email,
  setEmail,
  phone,
  setPhone,
  address,
  setAddress,
  notes,
  setNotes,
  saving,
  dirty,
  onSave
}: {
  client: Client;
  name: string;
  setName: (v: string) => void;
  email: string;
  setEmail: (v: string) => void;
  phone: string;
  setPhone: (v: string) => void;
  address: string;
  setAddress: (v: string) => void;
  notes: string;
  setNotes: (v: string) => void;
  saving: boolean;
  dirty: boolean;
  onSave: () => void;
}) {
  const [active, setActive] = useState<TabKey>(() => {
    if (typeof window === "undefined") return "infos";
    const hash = window.location.hash.replace("#", "") as TabKey;
    if (
      hash === "infos" ||
      hash === "projets" ||
      hash === "documents" ||
      hash === "mesures" ||
      hash === "suivi"
    ) {
      return hash;
    }
    return "infos";
  });

  function selectTab(k: TabKey) {
    setActive(k);
    if (typeof window !== "undefined") {
      window.history.replaceState(null, "", `#${k}`);
    }
  }

  const projectsCount = client.projects?.length || 0;

  const tabs: Array<{ key: TabKey; label: string; badge?: number }> = [
    { key: "infos", label: "Infos" },
    { key: "projets", label: "Projets", badge: projectsCount },
    { key: "communications", label: "Communications" },
    { key: "documents", label: "Documents" },
    { key: "mesures", label: "Mesures" },
    { key: "suivi", label: "Suivi commercial" }
  ];

  return (
    <>
      <div
        className="sticky top-0 z-20 -mx-4 mb-5 overflow-x-auto border-b border-brand-800 bg-brand-950/95 px-4 backdrop-blur lg:-mx-6 lg:px-6"
        role="tablist"
      >
        <div className="flex min-w-max gap-1">
          {tabs.map((t) => {
            const isActive = active === t.key;
            return (
              <button
                key={t.key}
                type="button"
                role="tab"
                aria-selected={isActive}
                onClick={() => selectTab(t.key)}
                className={`relative whitespace-nowrap px-4 py-3 text-sm transition ${
                  isActive
                    ? "font-semibold text-accent-500"
                    : "text-white/60 hover:text-white"
                }`}
              >
                {t.label}
                {t.badge && t.badge > 0 ? (
                  <span className="ml-1.5 inline-flex h-4 min-w-[16px] items-center justify-center rounded-full bg-accent-500/20 px-1 text-[10px] font-semibold text-accent-300">
                    {t.badge}
                  </span>
                ) : null}
                {isActive ? (
                  <span className="absolute inset-x-3 -bottom-px h-0.5 rounded-t bg-accent-500" />
                ) : null}
              </button>
            );
          })}
        </div>
      </div>

      {active === "infos" ? (
        <div className="space-y-6">
          <section className="rounded-xl border border-brand-800 bg-brand-900 p-5">
            <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
              Coordonnées
            </h2>
            <div className="mt-4 grid gap-4 sm:grid-cols-2">
              <div className="sm:col-span-2">
                <label htmlFor="c_name" className="label">Nom</label>
                <input
                  id="c_name"
                  type="text"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  className="input"
                />
              </div>
              <div>
                <label htmlFor="c_email" className="label">Courriel</label>
                <input
                  id="c_email"
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className="input"
                />
              </div>
              <div>
                <label htmlFor="c_phone" className="label">Téléphone</label>
                <div className="flex items-center gap-2">
                  <input
                    id="c_phone"
                    type="tel"
                    value={phone}
                    onChange={(e) => setPhone(e.target.value)}
                    className="input flex-1"
                  />
                  {phone ? (
                    <CallButton
                      variant="icon"
                      targetE164={phone}
                      entityType="client"
                      entityId={client.id}
                    />
                  ) : null}
                </div>
              </div>
              <div className="sm:col-span-2">
                <label htmlFor="c_address" className="label">Adresse</label>
                <AddressInput
                  id="c_address"
                  value={address}
                  onChange={setAddress}
                />
              </div>
            </div>
          </section>

          <section className="rounded-xl border border-brand-800 bg-brand-900 p-5">
            <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
              Notes internes
            </h2>
            <textarea
              rows={4}
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="Préférences, historique, personnes contact…"
              className="input mt-3"
            />
          </section>

          <button
            type="button"
            onClick={onSave}
            disabled={saving || !dirty}
            className="btn-accent text-sm"
          >
            {saving ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" /> Sauvegarde…
              </>
            ) : (
              <>
                <Save className="mr-2 h-4 w-4" />
                {dirty ? "Sauvegarder" : "Aucun changement"}
              </>
            )}
          </button>
        </div>
      ) : null}

      {active === "projets" ? (
        <section className="rounded-xl border border-brand-800 bg-brand-900 p-5">
          <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
            Projets
          </h2>
          {projectsCount === 0 ? (
            <p className="mt-3 text-sm text-white/50">
              Aucun projet pour ce client.
            </p>
          ) : (
            <ul className="mt-3 divide-y divide-brand-800 text-sm">
              {client.projects?.map((p) => (
                <li key={p.id} className="py-2">
                  <Link
                    // eslint-disable-next-line @typescript-eslint/no-explicit-any
                    href={`/app/projets/${p.id}` as any}
                    className="flex items-center justify-between hover:text-accent-500"
                  >
                    <span className="text-white">{p.name}</span>
                    <span className="text-xs text-white/50">{p.status}</span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </section>
      ) : null}

      {active === "documents" ? (
        <ClientDocuments
          clientId={client.id}
          contactRequestId={client.contact_request_id}
        />
      ) : null}

      {active === "mesures" ? (
        <MeasurementsPanel
          clientId={client.id}
          defaultAddress={client.address}
        />
      ) : null}

      {active === "communications" ? (
        <CommunicationsTimeline
          entityType="client"
          entityId={client.id}
          title="Appels & SMS"
          emptyHint="Aucun appel ni SMS lié à ce client pour le moment."
          replyToE164={client.phone || null}
        />
      ) : null}

      {active === "suivi" ? <SalesTasksPanel clientId={client.id} /> : null}
    </>
  );
}

// ---------------------------------------------------------------------------
// QuickBooks push — envoie le client vers la compagnie QBO connectée
// ---------------------------------------------------------------------------

function QboPushButton({
  client,
  onSynced
}: {
  client: Client;
  onSynced: (qboCustomerId: string) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [justSynced, setJustSynced] = useState(false);

  async function push() {
    setBusy(true);
    setErr(null);
    try {
      const res = await authedFetch(
        `/api/v1/clients/${client.id}/push-to-qbo`,
        { method: "POST" }
      );
      if (!res.ok) {
        const text = await res.text();
        throw new Error(
          text.slice(0, 240) || `http_${res.status}`
        );
      }
      const data = (await res.json()) as {
        qbo_customer_id: string;
        display_name: string;
        created: boolean;
      };
      onSynced(data.qbo_customer_id);
      setJustSynced(true);
      setTimeout(() => setJustSynced(false), 4000);
    } catch (e) {
      setErr(`Push QBO échoué : ${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  }

  if (client.qbo_customer_id) {
    return (
      <div className="flex flex-col items-start gap-1">
        <div className="inline-flex items-center gap-2 self-start rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-2.5 text-sm font-medium text-emerald-300">
          <CheckCircle2 className="h-4 w-4" />
          QB ✓ #{client.qbo_customer_id}
        </div>
        <button
          type="button"
          onClick={push}
          disabled={busy}
          className="text-[11px] text-white/50 underline decoration-dotted hover:text-accent-400 disabled:opacity-40"
        >
          {busy ? "Mise à jour…" : "Re-synchroniser"}
        </button>
        {err ? (
          <p className="text-[11px] text-rose-300">{err}</p>
        ) : null}
      </div>
    );
  }

  return (
    <div className="flex flex-col items-start gap-1">
      <button
        type="button"
        onClick={push}
        disabled={busy}
        className="inline-flex items-center gap-2 self-start rounded-lg border border-accent-500/40 bg-accent-500/10 px-3 py-2.5 text-sm font-medium text-accent-200 hover:bg-accent-500/20 disabled:opacity-50"
      >
        {busy ? (
          <Loader2 className="h-4 w-4 animate-spin" />
        ) : (
          <ExternalLink className="h-4 w-4" />
        )}
        Envoyer vers QuickBooks
      </button>
      {justSynced ? (
        <p className="text-[11px] text-emerald-300">
          Synchronisé avec QuickBooks.
        </p>
      ) : null}
      {err ? (
        <p className="text-[11px] text-rose-300">{err}</p>
      ) : null}
    </div>
  );
}

// ---------- Documents tied to the client ----------

type Soumission = {
  id: number;
  reference: string;
  title: string;
  status: string;
  total: number | string | null;
  accepted_at: string | null;
  signed_name: string | null;
  created_at: string;
};

type Facture = {
  id: number;
  reference: string;
  status: string;
  total: number | string | null;
  balance: number | string | null;
  issued_at: string | null;
  paid_at: string | null;
};

type BonTravail = {
  id: number;
  reference: string;
  title: string;
  status: string;
  client_id: number | null;
  accepted_at: string | null;
  signed_name: string | null;
};

type ProspectFile = {
  id: number;
  content_type: string;
  filename: string | null;
  created_at: string;
};

function DocSection({
  title,
  count,
  icon,
  defaultOpen = false,
  children
}: {
  title: string;
  count: number;
  icon: React.ReactNode;
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="overflow-hidden rounded-xl border border-brand-800 bg-brand-900">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-white/70 transition hover:bg-brand-950/40"
      >
        {open ? (
          <ChevronDown className="h-3.5 w-3.5 text-accent-500" />
        ) : (
          <ChevronRight className="h-3.5 w-3.5 text-white/40" />
        )}
        <span className="text-accent-500">{icon}</span>
        <span className="text-white">{title}</span>
        <span className="ml-auto rounded-full bg-white/10 px-2 py-0.5 text-[10px] text-white/70">
          {count}
        </span>
      </button>
      {open ? <div className="border-t border-brand-800 p-4">{children}</div> : null}
    </div>
  );
}

function ClientDocuments({
  clientId,
  contactRequestId
}: {
  clientId: number;
  contactRequestId: number | null;
}) {
  const [soumissions, setSoumissions] = useState<Soumission[]>([]);
  const [factures, setFactures] = useState<Facture[]>([]);
  const [bons, setBons] = useState<BonTravail[]>([]);
  const [prospectFiles, setProspectFiles] = useState<ProspectFile[]>([]);
  const [fileUrls, setFileUrls] = useState<Record<number, string>>({});
  const [loading, setLoading] = useState(true);
  // Documents archivés (PDF) — ex. contrat d'entreprise signé par les
  // deux parties, déposé automatiquement à la signature du client.
  const [archivedDocs, setArchivedDocs] = useState<
    Array<{
      id: number;
      name: string;
      source: string | null;
      soumission_id: number | null;
      created_at: string;
    }>
  >([]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        const baseCalls = [
          authedFetch("/api/v1/soumissions?limit=500"),
          authedFetch("/api/v1/factures?limit=500"),
          authedFetch("/api/v1/bons-travail?limit=500")
        ];
        // Seuls les clients convertis d'un prospect ont des photos /
        // PDF du formulaire public — inutile d'appeler sinon.
        if (contactRequestId) {
          baseCalls.push(
            authedFetch(`/api/v1/contact/${contactRequestId}/photos`)
          );
        }
        const [sRes, fRes, bRes, pRes] = await Promise.all(baseCalls);
        if (cancelled) return;
        if (sRes.ok) {
          const all = (await sRes.json()) as Array<
            Soumission & { client_id: number | null }
          >;
          setSoumissions(all.filter((x) => x.client_id === clientId));
        }
        if (fRes.ok) {
          const all = (await fRes.json()) as Array<
            Facture & { client_id: number | null }
          >;
          setFactures(all.filter((x) => x.client_id === clientId));
        }
        if (bRes.ok) {
          const all = (await bRes.json()) as BonTravail[];
          setBons(all.filter((x) => x.client_id === clientId));
        }
        if (pRes && pRes.ok) {
          setProspectFiles((await pRes.json()) as ProspectFile[]);
        }
        // PDF archivés de la fiche client (contrats signés…).
        const dRes = await authedFetch(
          `/api/v1/clients/${clientId}/documents`
        );
        if (dRes.ok && !cancelled) {
          setArchivedDocs(await dRes.json());
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [clientId, contactRequestId]);

  // Blob URLs for the prospect-era files (images + PDFs alike).
  useEffect(() => {
    if (!contactRequestId) return;
    let cancelled = false;
    (async () => {
      for (const f of prospectFiles) {
        if (fileUrls[f.id]) continue;
        const res = await authedFetch(
          `/api/v1/contact/${contactRequestId}/photos/${f.id}/image`
        );
        if (!res.ok) continue;
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        if (cancelled) {
          URL.revokeObjectURL(url);
          return;
        }
        setFileUrls((prev) => ({ ...prev, [f.id]: url }));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [prospectFiles, contactRequestId, fileUrls]);

  useEffect(() => {
    return () => {
      for (const u of Object.values(fileUrls)) URL.revokeObjectURL(u);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const signedSoumissions = soumissions.filter(
    (s) => s.status === "accepted" || s.accepted_at
  );
  const signedBons = bons.filter(
    (b) => b.status === "signed" || b.accepted_at
  );
  const prospectPhotos = prospectFiles.filter((f) =>
    f.content_type.startsWith("image/")
  );
  const prospectOther = prospectFiles.filter(
    (f) => !f.content_type.startsWith("image/")
  );

  function fmtMoney(n: number | string | null): string {
    const v = Number(n || 0);
    return new Intl.NumberFormat("fr-CA", {
      style: "currency",
      currency: "CAD",
      maximumFractionDigits: 2
    }).format(v);
  }

  async function downloadArchivedDoc(docId: number) {
    const res = await authedFetch(
      `/api/v1/clients/${clientId}/documents/${docId}/download`
    );
    if (!res.ok) return;
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    window.open(url, "_blank", "noopener,noreferrer");
    setTimeout(() => URL.revokeObjectURL(url), 60_000);
  }

  return (
    <section className="space-y-2">
      <div>
        <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
          Documents du client
        </h2>
        <p className="mt-1 text-xs text-white/60">
          Contrats signés · soumissions · factures
          {contactRequestId ? " · photos et documents du formulaire prospect" : ""}.
        </p>
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-6">
          <Loader2 className="h-5 w-5 animate-spin text-white/40" />
        </div>
      ) : (
        <>
          <DocSection
            title="Contrats signés (PDF archivés)"
            count={archivedDocs.length}
            icon={<FileText className="h-3.5 w-3.5" />}
            defaultOpen={archivedDocs.length > 0}
          >
            {archivedDocs.length === 0 ? (
              <p className="text-xs text-white/40">
                Aucun contrat signé archivé. Le PDF du contrat signé
                par les deux parties est déposé ici automatiquement
                lorsque le client signe en ligne.
              </p>
            ) : (
              <ul className="space-y-2">
                {archivedDocs.map((d) => (
                  <li key={d.id}>
                    <button
                      type="button"
                      onClick={() => void downloadArchivedDoc(d.id)}
                      className="flex w-full items-start justify-between gap-3 rounded-lg border border-emerald-500/20 bg-emerald-500/5 px-3 py-2 text-left text-sm hover:border-emerald-500/50"
                    >
                      <div className="min-w-0">
                        <p className="truncate font-semibold text-white">
                          {d.name}
                        </p>
                        <p className="text-[11px] text-white/50">
                          Archivé le{" "}
                          {new Date(d.created_at).toLocaleDateString(
                            "fr-CA"
                          )}
                          {d.source === "contract"
                            ? " · contrat signé"
                            : ""}
                        </p>
                      </div>
                      <span className="shrink-0 text-[11px] font-semibold text-emerald-300">
                        Ouvrir le PDF
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </DocSection>

          <DocSection
            title="Soumissions signées"
            count={signedSoumissions.length}
            icon={<FileText className="h-3.5 w-3.5" />}
            defaultOpen={signedSoumissions.length > 0}
          >
            {signedSoumissions.length === 0 ? (
              <p className="text-xs text-white/40">Aucune soumission acceptée.</p>
            ) : (
              <ul className="space-y-2">
                {signedSoumissions.map((s) => (
                  <li key={s.id}>
                    <Link
                      // eslint-disable-next-line @typescript-eslint/no-explicit-any
                      href={`/app/soumissions/${s.id}` as any}
                      className="flex items-start justify-between gap-3 rounded-lg border border-emerald-500/20 bg-emerald-500/5 px-3 py-2 text-sm hover:border-emerald-500/50"
                    >
                      <div className="min-w-0">
                        <p className="truncate font-semibold text-white">
                          {s.reference} — {s.title}
                        </p>
                        <p className="text-[11px] text-white/50">
                          Signée
                          {s.signed_name ? ` par ${s.signed_name}` : ""}
                          {s.accepted_at
                            ? ` le ${new Date(s.accepted_at).toLocaleDateString("fr-CA")}`
                            : ""}
                        </p>
                      </div>
                      <span className="shrink-0 text-sm font-semibold text-emerald-300">
                        {fmtMoney(s.total)}
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </DocSection>

          <DocSection
            title="Contrats signés"
            count={signedBons.length}
            icon={<FileText className="h-3.5 w-3.5" />}
            defaultOpen={signedBons.length > 0}
          >
            {signedBons.length === 0 ? (
              <p className="text-xs text-white/40">Aucun bon de travail signé.</p>
            ) : (
              <ul className="space-y-2">
                {signedBons.map((b) => (
                  <li key={b.id}>
                    <Link
                      // eslint-disable-next-line @typescript-eslint/no-explicit-any
                      href={`/app/bons/${b.id}` as any}
                      className="flex items-start justify-between gap-3 rounded-lg border border-sky-500/20 bg-sky-500/5 px-3 py-2 text-sm hover:border-sky-500/50"
                    >
                      <div className="min-w-0">
                        <p className="truncate font-semibold text-white">
                          {b.reference} — {b.title}
                        </p>
                        <p className="text-[11px] text-white/50">
                          Signé
                          {b.signed_name ? ` par ${b.signed_name}` : ""}
                          {b.accepted_at
                            ? ` le ${new Date(b.accepted_at).toLocaleDateString("fr-CA")}`
                            : ""}
                        </p>
                      </div>
                      <span className="shrink-0 rounded bg-sky-500/15 px-2 py-0.5 text-[10px] uppercase text-sky-300">
                        {b.status}
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </DocSection>

          <DocSection
            title="Factures"
            count={factures.length}
            icon={<FileText className="h-3.5 w-3.5" />}
            defaultOpen={false}
          >
            {factures.length === 0 ? (
              <p className="text-xs text-white/40">Aucune facture.</p>
            ) : (
              <ul className="space-y-2">
                {factures.map((f) => (
                  <li key={f.id}>
                    <Link
                      // eslint-disable-next-line @typescript-eslint/no-explicit-any
                      href={`/app/facturation/${f.id}` as any}
                      className="flex items-start justify-between gap-3 rounded-lg border border-brand-800 bg-brand-950 px-3 py-2 text-sm hover:border-accent-500/50"
                    >
                      <div className="min-w-0">
                        <p className="truncate font-semibold text-white">
                          {f.reference}
                        </p>
                        <p className="text-[11px] text-white/50">
                          {f.issued_at
                            ? `Émise le ${new Date(f.issued_at).toLocaleDateString("fr-CA")}`
                            : "Brouillon"}
                          {f.paid_at
                            ? ` · Payée le ${new Date(f.paid_at).toLocaleDateString("fr-CA")}`
                            : ""}
                        </p>
                      </div>
                      <div className="shrink-0 text-right">
                        <p className="text-sm font-semibold text-white">
                          {fmtMoney(f.total)}
                        </p>
                        <p
                          className={`text-[10px] uppercase ${
                            f.status === "paid"
                              ? "text-emerald-300"
                              : f.status === "overdue"
                              ? "text-rose-300"
                              : "text-white/50"
                          }`}
                        >
                          {f.status}
                        </p>
                      </div>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </DocSection>

          {contactRequestId ? (
            <>
              <DocSection
                title="Photos (du formulaire prospect)"
                count={prospectPhotos.length}
                icon={<ImageIcon className="h-3.5 w-3.5" />}
                defaultOpen={false}
              >
                {prospectPhotos.length === 0 ? (
                  <p className="text-xs text-white/40">Aucune photo.</p>
                ) : (
                  <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                    {prospectPhotos.map((p) => (
                      <li
                        key={p.id}
                        className="overflow-hidden rounded-xl border border-brand-800 bg-brand-900"
                      >
                        <a
                          href={fileUrls[p.id] || "#"}
                          target="_blank"
                          rel="noreferrer"
                          className="block aspect-video w-full overflow-hidden bg-black"
                        >
                          {fileUrls[p.id] ? (
                            // eslint-disable-next-line @next/next/no-img-element
                            <img
                              alt={p.filename || "Photo"}
                              src={fileUrls[p.id]}
                              className="h-full w-full object-cover"
                            />
                          ) : (
                            <div className="flex h-full items-center justify-center">
                              <Loader2 className="h-4 w-4 animate-spin text-white/40" />
                            </div>
                          )}
                        </a>
                        <p className="truncate p-2 text-[11px] text-white/60">
                          {p.filename || `photo-${p.id}`}
                        </p>
                      </li>
                    ))}
                  </ul>
                )}
              </DocSection>

              <DocSection
                title="Autres documents (du prospect)"
                count={prospectOther.length}
                icon={<FileText className="h-3.5 w-3.5" />}
                defaultOpen={false}
              >
                {prospectOther.length === 0 ? (
                  <p className="text-xs text-white/40">Aucun PDF ou document.</p>
                ) : (
                  <ul className="space-y-1.5">
                    {prospectOther.map((d) => (
                      <li key={d.id}>
                        <a
                          href={fileUrls[d.id] || "#"}
                          target="_blank"
                          rel="noreferrer"
                          download={d.filename || `document-${d.id}`}
                          className="flex items-center gap-2 rounded-lg border border-brand-800 bg-brand-950 px-3 py-2 text-sm text-white hover:border-accent-500"
                        >
                          <FileText className="h-4 w-4 shrink-0 text-accent-500" />
                          <div className="min-w-0">
                            <p className="truncate">
                              {d.filename || `document-${d.id}`}
                            </p>
                            <p className="text-[10px] text-white/40">
                              {d.content_type} ·{" "}
                              {new Date(d.created_at).toLocaleDateString("fr-CA")}
                            </p>
                          </div>
                        </a>
                      </li>
                    ))}
                  </ul>
                )}
              </DocSection>
            </>
          ) : null}
        </>
      )}
    </section>
  );
}

