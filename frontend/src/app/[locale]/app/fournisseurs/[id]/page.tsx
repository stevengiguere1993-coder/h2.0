"use client";

import { useEffect, useMemo, useState } from "react";
import { useParams, useRouter as useNextRouter } from "next/navigation";
import { ArrowLeft, Loader2, Save, Trash2 } from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { EntityDriveSection } from "@/components/drive/EntityDriveSection";
import { Link } from "@/i18n/navigation";
import { useAppLayout } from "../../layout";
import { authedFetch } from "@/lib/auth";
import { useConfirm } from "@/components/confirm-dialog";

type Fournisseur = {
  id: number;
  name: string;
  contact_name: string | null;
  email: string | null;
  phone: string | null;
  category: string | null;
  website: string | null;
  address: string | null;
  active: boolean;
  notes: string | null;
  payment_terms_days: number | null;
  qbo_expense_account: string | null;
  qbo_vendor_id: string | null;
  created_at: string;
};

export default function FournisseurDetailPage() {
  const confirm = useConfirm();
  const { onOpenSidebar } = useAppLayout();
  const params = useParams<{ id: string }>();
  const id = Number(params.id);
  const router = useNextRouter();

  const [f, setF] = useState<Fournisseur | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [name, setName] = useState("");
  const [contactName, setContactName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [category, setCategory] = useState("");
  const [website, setWebsite] = useState("");
  const [address, setAddress] = useState("");
  const [active, setActive] = useState(true);
  const [notes, setNotes] = useState("");
  const [paymentTermsDays, setPaymentTermsDays] = useState("");
  const [qboExpenseAccount, setQboExpenseAccount] = useState("");

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const res = await authedFetch(`/api/v1/fournisseurs/${id}`);
        if (!res.ok) throw new Error(`http_${res.status}`);
        const data = (await res.json()) as Fournisseur;
        if (cancelled) return;
        setF(data);
        setName(data.name);
        setContactName(data.contact_name || "");
        setEmail(data.email || "");
        setPhone(data.phone || "");
        setCategory(data.category || "");
        setWebsite(data.website || "");
        setAddress(data.address || "");
        setActive(data.active);
        setNotes(data.notes || "");
        setPaymentTermsDays(
          data.payment_terms_days != null
            ? String(data.payment_terms_days)
            : ""
        );
        setQboExpenseAccount(data.qbo_expense_account || "");
      } catch {
        if (!cancelled) setError("Fournisseur introuvable.");
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
    if (!f) return false;
    return (
      name !== f.name ||
      contactName !== (f.contact_name || "") ||
      email !== (f.email || "") ||
      phone !== (f.phone || "") ||
      category !== (f.category || "") ||
      website !== (f.website || "") ||
      address !== (f.address || "") ||
      active !== f.active ||
      notes !== (f.notes || "") ||
      paymentTermsDays !==
        (f.payment_terms_days != null
          ? String(f.payment_terms_days)
          : "") ||
      qboExpenseAccount !== (f.qbo_expense_account || "")
    );
  }, [
    f,
    name,
    contactName,
    email,
    phone,
    category,
    website,
    address,
    active,
    notes,
    paymentTermsDays,
    qboExpenseAccount
  ]);

  async function saveAll() {
    if (!f) return;
    setSaving(true);
    setError(null);
    try {
      const ptd = paymentTermsDays.trim();
      const payload = {
        name: name.trim(),
        contact_name: contactName.trim() || null,
        email: email.trim() || null,
        phone: phone.trim() || null,
        category: category.trim() || null,
        website: website.trim() || null,
        address: address.trim() || null,
        active,
        notes: notes.trim() || null,
        payment_terms_days: ptd === "" ? null : Number(ptd),
        qbo_expense_account: qboExpenseAccount.trim() || null
      };
      const res = await authedFetch(`/api/v1/fournisseurs/${id}`, {
        method: "PATCH",
        body: JSON.stringify(payload)
      });
      if (!res.ok) throw new Error();
      setF((await res.json()) as Fournisseur);
    } catch {
      setError("Sauvegarde échouée.");
    } finally {
      setSaving(false);
    }
  }

  async function onDelete() {
    if (!f) return;
    if (!(await confirm(`Supprimer « ${f.name} » ?`))) return;
    setDeleting(true);
    try {
      const res = await authedFetch(`/api/v1/fournisseurs/${id}`, {
        method: "DELETE"
      });
      if (!res.ok && res.status !== 204) throw new Error();
      router.replace("/app/fournisseurs");
    } catch {
      setDeleting(false);
      setError("Suppression échouée.");
    }
  }

  return (
    <>
      <AppTopbar
        breadcrumbs={[{ label: "Ressources", href: "/app" }, { label: "Fournisseurs" }]}
        onOpenSidebar={onOpenSidebar}
      />

      <div className="p-4 lg:p-6">
        <Link
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          href={"/app/fournisseurs" as any}
          className="inline-flex items-center text-sm text-white/70 hover:text-accent-500"
        >
          <ArrowLeft className="mr-1 h-4 w-4" /> Retour aux fournisseurs
        </Link>

        {loading ? (
          <div className="flex min-h-[40vh] items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-accent-500" />
          </div>
        ) : error && !f ? (
          <p className="mt-6 rounded-lg border border-rose-500/40 bg-rose-500/10 px-4 py-2 text-sm text-rose-300">
            {error}
          </p>
        ) : f ? (
          <>
            <header className="mt-6 flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
              <h1 className="text-2xl font-bold text-white">{f.name}</h1>
              <div className="flex flex-wrap items-center gap-3">
                <label className="inline-flex items-center gap-2 text-sm text-white/70">
                  <input
                    type="checkbox"
                    checked={active}
                    onChange={(e) => setActive(e.target.checked)}
                  />
                  Actif
                </label>
                <button
                  type="button"
                  onClick={onDelete}
                  disabled={deleting}
                  className="inline-flex items-center gap-2 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2.5 text-sm font-medium text-rose-300 hover:bg-rose-500/20"
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

            <EntityDriveSection
              entityType="Fournisseur"
              entityId={f.id}
              pole="Construction"
              label="Fournisseur"
              route="/app/fournisseurs/[id]"
            />

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
                    <label htmlFor="fn" className="label">Nom</label>
                    <input
                      id="fn"
                      type="text"
                      value={name}
                      onChange={(e) => setName(e.target.value)}
                      className="input"
                    />
                  </div>
                  <div>
                    <label htmlFor="fc" className="label">Contact</label>
                    <input
                      id="fc"
                      type="text"
                      value={contactName}
                      onChange={(e) => setContactName(e.target.value)}
                      className="input"
                    />
                  </div>
                  <div>
                    <label htmlFor="fcat" className="label">Catégorie</label>
                    <input
                      id="fcat"
                      type="text"
                      value={category}
                      onChange={(e) => setCategory(e.target.value)}
                      className="input"
                    />
                  </div>
                  <div>
                    <label htmlFor="fe" className="label">Courriel</label>
                    <input
                      id="fe"
                      type="email"
                      value={email}
                      onChange={(e) => setEmail(e.target.value)}
                      className="input"
                    />
                  </div>
                  <div>
                    <label htmlFor="fp" className="label">Téléphone</label>
                    <input
                      id="fp"
                      type="tel"
                      value={phone}
                      onChange={(e) => setPhone(e.target.value)}
                      className="input"
                    />
                  </div>
                  <div className="sm:col-span-2">
                    <label htmlFor="fw" className="label">Site web</label>
                    <input
                      id="fw"
                      type="url"
                      value={website}
                      onChange={(e) => setWebsite(e.target.value)}
                      className="input"
                    />
                  </div>
                  <div className="sm:col-span-2">
                    <label htmlFor="fadr" className="label">
                      Adresse
                    </label>
                    <input
                      id="fadr"
                      type="text"
                      value={address}
                      onChange={(e) => setAddress(e.target.value)}
                      className="input"
                      placeholder="Importée de QuickBooks si disponible"
                    />
                  </div>
                </div>
              </section>

              <section className="rounded-xl border border-brand-800 bg-brand-900 p-5">
                <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
                  Conditions de paiement
                </h2>
                <label htmlFor="ptd" className="label mt-3">
                  Délai de paiement (jours)
                </label>
                <input
                  id="ptd"
                  type="number"
                  min={0}
                  max={365}
                  value={paymentTermsDays}
                  onChange={(e) => setPaymentTermsDays(e.target.value)}
                  placeholder="30"
                  className="input w-32"
                />
                <p className="mt-1 text-[11px] text-white/50">
                  Délai net après réception (ex. 30 pour net-30). Sert à
                  calculer l&apos;échéance de paiement des achats facturés
                  par ce fournisseur. Vide = 30 jours par défaut.
                </p>
              </section>

              <section className="rounded-xl border border-brand-800 bg-brand-900 p-5">
                <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
                  QuickBooks
                </h2>
                <label htmlFor="qboacc" className="label mt-3">
                  Compte de dépense par défaut
                </label>
                <input
                  id="qboacc"
                  type="text"
                  value={qboExpenseAccount}
                  onChange={(e) => setQboExpenseAccount(e.target.value)}
                  placeholder="Ex. Matériaux et fournitures"
                  className="input"
                />
                <p className="mt-1 text-[11px] text-white/50">
                  Nom EXACT (sensible aux accents et à la casse) du
                  compte du Plan comptable QuickBooks. Tous les achats
                  de ce fournisseur seront classés ici automatiquement.
                  Vide = compte par défaut global (Paramètres → Comptes
                  QuickBooks).
                </p>
              </section>

              <section className="rounded-xl border border-brand-800 bg-brand-900 p-5">
                <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
                  Notes internes
                </h2>
                <textarea
                  rows={4}
                  value={notes}
                  onChange={(e) => setNotes(e.target.value)}
                  placeholder="Rabais, historique, conditions de paiement…"
                  className="input mt-3"
                />
              </section>

              <button
                type="button"
                onClick={saveAll}
                disabled={saving || !dirty}
                className="btn-accent text-sm"
              >
                {saving ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    Sauvegarde…
                  </>
                ) : (
                  <>
                    <Save className="mr-2 h-4 w-4" />
                    {dirty ? "Sauvegarder" : "Aucun changement"}
                  </>
                )}
              </button>
            </div>
          </>
        ) : null}
      </div>
    </>
  );
}
