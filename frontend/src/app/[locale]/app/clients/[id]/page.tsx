"use client";

import { useEffect, useMemo, useState } from "react";
import { useParams, useRouter as useNextRouter } from "next/navigation";
import { ArrowLeft, Loader2, Save, Trash2 } from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { AddressInput } from "@/components/address-input";
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
                  {c.contact_request_id ? " · Converti d'un prospect" : ""}
                </p>
              </div>
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
            </header>

            {error ? (
              <p className="mt-4 rounded-lg border border-rose-500/40 bg-rose-500/10 px-4 py-2 text-sm text-rose-300">
                {error}
              </p>
            ) : null}

            <div className="mt-6 max-w-3xl space-y-6">
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
                    <input
                      id="c_phone"
                      type="tel"
                      value={phone}
                      onChange={(e) => setPhone(e.target.value)}
                      className="input"
                    />
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

              {c.projects && c.projects.length > 0 ? (
                <section className="rounded-xl border border-brand-800 bg-brand-900 p-5">
                  <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
                    Projets
                  </h2>
                  <ul className="mt-3 divide-y divide-brand-800 text-sm">
                    {c.projects.map((p) => (
                      <li key={p.id} className="py-2">
                        <Link
                          // eslint-disable-next-line @typescript-eslint/no-explicit-any
                          href={`/app/projets/${p.id}` as any}
                          className="flex items-center justify-between hover:text-accent-500"
                        >
                          <span className="text-white">{p.name}</span>
                          <span className="text-xs text-white/50">
                            {p.status}
                          </span>
                        </Link>
                      </li>
                    ))}
                  </ul>
                </section>
              ) : null}

              <button
                type="button"
                onClick={saveAll}
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

              <ClientDocuments clientId={c.id} />

              <MeasurementsPanel
                clientId={c.id}
                defaultAddress={c.address}
              />
              <SalesTasksPanel clientId={c.id} />
            </div>
          </>
        ) : null}
      </div>
    </>
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

function ClientDocuments({ clientId }: { clientId: number }) {
  const [soumissions, setSoumissions] = useState<Soumission[]>([]);
  const [factures, setFactures] = useState<Facture[]>([]);
  const [bons, setBons] = useState<BonTravail[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        const [sRes, fRes, bRes] = await Promise.all([
          authedFetch("/api/v1/soumissions?limit=500"),
          authedFetch("/api/v1/factures?limit=500"),
          authedFetch("/api/v1/bons-travail?limit=500")
        ]);
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
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [clientId]);

  const signedSoumissions = soumissions.filter(
    (s) => s.status === "accepted" || s.accepted_at
  );
  const signedBons = bons.filter(
    (b) => b.status === "signed" || b.accepted_at
  );

  function fmtMoney(n: number | string | null): string {
    const v = Number(n || 0);
    return new Intl.NumberFormat("fr-CA", {
      style: "currency",
      currency: "CAD",
      maximumFractionDigits: 2
    }).format(v);
  }

  return (
    <section className="rounded-xl border border-brand-800 bg-brand-900 p-5">
      <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
        Documents du client
      </h2>
      <p className="mt-1 text-xs text-white/60">
        Soumissions signées · contrats (bons de travail signés) · factures.
      </p>

      {loading ? (
        <div className="flex items-center justify-center py-6">
          <Loader2 className="h-5 w-5 animate-spin text-white/40" />
        </div>
      ) : (
        <div className="mt-4 space-y-5">
          <DocGroup
            title={`Soumissions signées (${signedSoumissions.length})`}
            empty="Aucune soumission acceptée."
          >
            {signedSoumissions.map((s) => (
              <Link
                key={s.id}
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
            ))}
          </DocGroup>

          <DocGroup
            title={`Contrats signés (${signedBons.length})`}
            empty="Aucun bon de travail signé."
          >
            {signedBons.map((b) => (
              <Link
                key={b.id}
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
            ))}
          </DocGroup>

          <DocGroup
            title={`Factures (${factures.length})`}
            empty="Aucune facture."
          >
            {factures.map((f) => (
              <Link
                key={f.id}
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
            ))}
          </DocGroup>
        </div>
      )}
    </section>
  );
}

function DocGroup({
  title,
  empty,
  children
}: {
  title: string;
  empty: string;
  children: React.ReactNode;
}) {
  const hasChildren = Array.isArray(children)
    ? children.length > 0
    : Boolean(children);
  return (
    <div>
      <p className="text-xs font-semibold uppercase tracking-wider text-white/60">
        {title}
      </p>
      {hasChildren ? (
        <div className="mt-2 space-y-1.5">{children}</div>
      ) : (
        <p className="mt-2 text-xs text-white/40">{empty}</p>
      )}
    </div>
  );
}
