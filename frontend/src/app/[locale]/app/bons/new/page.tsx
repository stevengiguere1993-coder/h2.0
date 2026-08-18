"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter as useNextRouter } from "next/navigation";
import {
  ArrowLeft,
  Building2,
  HardHat,
  Loader2,
  UserRound,
  Wrench
} from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { Link } from "@/i18n/navigation";
import { useAppLayout } from "../../layout";
import { authedFetch } from "@/lib/auth";
import { fetchAllPages } from "@/lib/fetch-all";

type Entreprise = { id: number; name: string };
type Immeuble = { id: number; name: string; address: string };
type Logement = { id: number; numero: string };
type SousTraitant = { id: number; full_name: string };
type User = { id: number; email: string; full_name?: string | null };
type ClientT = { id: number; name: string; address: string | null };

export default function NewBonPage() {
  const { onOpenSidebar } = useAppLayout();
  const router = useNextRouter();

  // Rattachement : une de NOS compagnies (immeuble → appartement) OU un
  // CLIENT (travaux chez lui, facturés à son nom).
  const [rattachement, setRattachement] = useState<
    "compagnie" | "client"
  >("compagnie");
  const [entrepriseId, setEntrepriseId] = useState("");
  const [immeubleId, setImmeubleId] = useState("");
  const [logementId, setLogementId] = useState("");
  const [clientId, setClientId] = useState("");
  const [clientAddress, setClientAddress] = useState("");
  // Exécutant.
  const [executantType, setExecutantType] = useState("nos_hommes");
  const [sousTraitantId, setSousTraitantId] = useState("");
  const [sousTraitantSearch, setSousTraitantSearch] = useState("");
  const [sousTraitantOpen, setSousTraitantOpen] = useState(false);
  // Méta.
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [assigneeId, setAssigneeId] = useState("");
  const [margePct, setMargePct] = useState("10");
  const [photos, setPhotos] = useState<File[]>([]);

  const [entreprises, setEntreprises] = useState<Entreprise[]>([]);
  const [clients, setClients] = useState<ClientT[]>([]);
  const [immeubles, setImmeubles] = useState<Immeuble[]>([]);
  const [logements, setLogements] = useState<Logement[]>([]);
  const [sousTraitants, setSousTraitants] = useState<SousTraitant[]>([]);
  const [users, setUsers] = useState<User[]>([]);
  const [loadingImm, setLoadingImm] = useState(false);
  const [loadingLog, setLoadingLog] = useState(false);

  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Catalogues fixes au montage.
  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const [eRes, sRes, uRes, dRes, cl] = await Promise.all([
          authedFetch("/api/v1/entreprises?limit=500"),
          authedFetch("/api/v1/sous-traitants?limit=500"),
          authedFetch("/api/v1/users"),
          authedFetch("/api/v1/construction/bon-defaults"),
          fetchAllPages<ClientT>("/api/v1/clients").catch(
            () => [] as ClientT[]
          )
        ]);
        if (cancelled) return;
        if (eRes.ok) setEntreprises((await eRes.json()) as Entreprise[]);
        if (sRes.ok) setSousTraitants((await sRes.json()) as SousTraitant[]);
        if (uRes.ok) setUsers((await uRes.json()) as User[]);
        cl.sort((a, b) => a.name.localeCompare(b.name, "fr"));
        setClients(cl);
        // Marge par défaut configurable (Paramètres → Bons de travail) —
        // pré-remplit le champ ; retombe sur "10" si absent/indispo.
        if (dRes.ok) {
          const d = (await dRes.json()) as {
            default_marge_pct: number | null;
          };
          if (d.default_marge_pct != null) {
            setMargePct(String(d.default_marge_pct));
          }
        }
      } catch {
        /* ignore */
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, []);

  // Immeubles de la compagnie sélectionnée.
  useEffect(() => {
    setImmeubleId("");
    setLogementId("");
    setImmeubles([]);
    setLogements([]);
    if (!entrepriseId) return;
    let cancelled = false;
    setLoadingImm(true);
    (async () => {
      try {
        // Endpoint des BONS (volet construction OU immobilier) — et non
        // /immobilier/immeubles, qui exige le volet immobilier : un
        // gestionnaire Construction voyait « Aucun immeuble » (403
        // silencieux). Retour Phil 2026-07-20.
        const res = await authedFetch(
          `/api/v1/bons/refs/immeubles?entreprise_id=${entrepriseId}`
        );
        if (!cancelled && res.ok)
          setImmeubles((await res.json()) as Immeuble[]);
      } catch {
        /* ignore */
      } finally {
        if (!cancelled) setLoadingImm(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [entrepriseId]);

  // Appartements de l'immeuble sélectionné.
  useEffect(() => {
    setLogementId("");
    setLogements([]);
    if (!immeubleId) return;
    let cancelled = false;
    setLoadingLog(true);
    (async () => {
      try {
        const res = await authedFetch(
          `/api/v1/bons/refs/immeubles/${immeubleId}/logements`
        );
        if (!cancelled && res.ok)
          setLogements((await res.json()) as Logement[]);
      } catch {
        /* ignore */
      } finally {
        if (!cancelled) setLoadingLog(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [immeubleId]);

  const selectedImmeuble = useMemo(
    () => immeubles.find((i) => String(i.id) === immeubleId) || null,
    [immeubles, immeubleId]
  );

  // Choisir un client pré-remplit l'adresse des travaux avec la sienne
  // (modifiable — le chantier peut être ailleurs).
  function onPickClient(id: string) {
    setClientId(id);
    const c = clients.find((x) => String(x.id) === id);
    if (c?.address && !clientAddress.trim()) {
      setClientAddress(c.address);
    }
  }

  function buildAddress(): string | undefined {
    if (!selectedImmeuble) return undefined;
    const base = selectedImmeuble.address || selectedImmeuble.name;
    if (logementId) {
      const lg = logements.find((l) => String(l.id) === logementId);
      return lg ? `${base} · App ${lg.numero}` : base;
    }
    return `${base} · Communs / immeuble entier`;
  }

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    if (rattachement === "compagnie") {
      if (!entrepriseId) {
        setError("Choisis la compagnie propriétaire.");
        return;
      }
      if (!immeubleId) {
        setError("Choisis l'immeuble concerné.");
        return;
      }
    } else if (!clientId) {
      setError("Choisis le client.");
      return;
    }
    if (!title.trim()) {
      setError("Le titre du travail est requis.");
      return;
    }
    if (executantType === "sous_traitant" && !sousTraitantId) {
      setError("Choisis le sous-traitant.");
      return;
    }
    setSubmitting(true);
    try {
      const payload: Record<string, unknown> = {
        title: title.trim(),
        kind: "interne",
        // Bon interne : aucune signature client.
        requires_signature: false,
        origin: "construction",
        executant_type: executantType,
        bon_type: "temps_materiel",
        marge_pct: margePct ? Number(margePct) : 0
      };
      if (rattachement === "compagnie") {
        payload.owner_entreprise_id = Number(entrepriseId);
        payload.immeuble_id = Number(immeubleId);
        if (logementId) payload.logement_id = Number(logementId);
        const addr = buildAddress();
        if (addr) payload.address = addr;
      } else {
        // Bon rattaché à un CLIENT : sa facture partira à son nom (le
        // client suit sur le projet lié puis la facture).
        payload.client_id = Number(clientId);
        if (clientAddress.trim()) payload.address = clientAddress.trim();
      }
      if (executantType === "sous_traitant")
        payload.sous_traitant_id = Number(sousTraitantId);
      if (description.trim()) payload.description = description.trim();
      if (assigneeId) payload.assignee_user_id = Number(assigneeId);

      const res = await authedFetch("/api/v1/bons-travail", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      if (!res.ok) {
        const txt = await res.text();
        throw new Error(txt.slice(0, 240) || `http_${res.status}`);
      }
      const created = (await res.json()) as { id: number };
      // Photos (optionnelles) — attachées au bon après création.
      for (const f of photos) {
        try {
          const fd = new FormData();
          fd.append("file", f);
          await authedFetch(
            `/api/v1/immobilier/bons-travail/${created.id}/photos`,
            { method: "POST", body: fd }
          );
        } catch {
          /* une photo qui échoue ne bloque pas la création */
        }
      }
      router.replace(`/app/bons/${created.id}`);
    } catch (err) {
      setError((err as Error).message);
      setSubmitting(false);
    }
  }

  return (
    <>
      <AppTopbar
        breadcrumbs={[
          { label: "Construction", href: "/app" },
          { label: "Bons de travail", href: "/app/bons" },
          { label: "Nouveau" }
        ]}
        onOpenSidebar={onOpenSidebar}
      />

      <div className="p-4 lg:p-6">
        <Link
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          href={"/app/bons" as any}
          className="inline-flex items-center text-sm text-white/70 hover:text-accent-500"
        >
          <ArrowLeft className="mr-1 h-4 w-4" /> Retour aux bons
        </Link>

        <h1 className="mt-6 text-2xl font-bold text-white">
          Nouveau bon de travail
        </h1>
        <p className="mt-1 text-sm text-white/60">
          Entretien d&apos;un de nos immeubles ou travaux chez un
          client. La référence est générée automatiquement.
        </p>

        <form onSubmit={onSubmit} className="mt-6 max-w-2xl space-y-6">
          {/* ── Rattachement ───────────────────────────────────────── */}
          <fieldset className="rounded-xl border border-brand-800 bg-brand-900/40 p-4">
            <legend className="px-2 text-sm font-semibold text-white">
              Rattachement
            </legend>
            <div className="space-y-4">
              {/* Nos immeubles OU un client */}
              <div className="grid gap-2 sm:grid-cols-2">
                <button
                  type="button"
                  onClick={() => setRattachement("compagnie")}
                  className={`flex items-center gap-2 rounded-xl border p-3 text-left transition ${
                    rattachement === "compagnie"
                      ? "border-accent-500 bg-brand-900"
                      : "border-brand-800 bg-brand-900/60 hover:border-brand-700"
                  }`}
                >
                  <Building2 className="h-5 w-5 text-emerald-300" />
                  <span>
                    <span className="block text-sm font-semibold text-white">
                      Compagnie propriétaire
                    </span>
                    <span className="block text-[11px] text-white/50">
                      entretien d&apos;un de nos immeubles
                    </span>
                  </span>
                </button>
                <button
                  type="button"
                  onClick={() => setRattachement("client")}
                  className={`flex items-center gap-2 rounded-xl border p-3 text-left transition ${
                    rattachement === "client"
                      ? "border-accent-500 bg-brand-900"
                      : "border-brand-800 bg-brand-900/60 hover:border-brand-700"
                  }`}
                >
                  <UserRound className="h-5 w-5 text-sky-300" />
                  <span>
                    <span className="block text-sm font-semibold text-white">
                      Client
                    </span>
                    <span className="block text-[11px] text-white/50">
                      travaux facturés à un client
                    </span>
                  </span>
                </button>
              </div>

              {rattachement === "client" ? (
                <>
                  <div>
                    <label htmlFor="client" className="label">
                      Client <span className="text-rose-400">*</span>
                    </label>
                    <select
                      id="client"
                      value={clientId}
                      onChange={(e) => onPickClient(e.target.value)}
                      className="input"
                    >
                      <option value="">
                        {clients.length === 0
                          ? "Chargement…"
                          : "— Choisir —"}
                      </option>
                      {clients.map((c) => (
                        <option key={c.id} value={String(c.id)}>
                          {c.name}
                        </option>
                      ))}
                    </select>
                    <p className="mt-1 text-xs text-white/50">
                      La facture du bon partira à son nom.
                    </p>
                  </div>
                  <div>
                    <label htmlFor="client-adresse" className="label">
                      Adresse des travaux
                    </label>
                    <input
                      id="client-adresse"
                      value={clientAddress}
                      onChange={(e) => setClientAddress(e.target.value)}
                      placeholder="Ex. 1647, Rue Desautels, Montréal, QC"
                      className="input"
                    />
                    <p className="mt-1 text-xs text-white/50">
                      Pré-remplie avec l&apos;adresse du client —
                      modifiable si le chantier est ailleurs. Incluez la
                      ville (elle sort sur la facture).
                    </p>
                  </div>
                </>
              ) : (
                <>
              <div>
                <label htmlFor="entreprise" className="label">
                  Compagnie propriétaire{" "}
                  <span className="text-rose-400">*</span>
                </label>
                <select
                  id="entreprise"
                  value={entrepriseId}
                  onChange={(e) => setEntrepriseId(e.target.value)}
                  className="input"
                >
                  <option value="">— Choisir —</option>
                  {entreprises.map((c) => (
                    <option key={c.id} value={String(c.id)}>
                      {c.name}
                    </option>
                  ))}
                </select>
              </div>

              <div className="grid gap-4 sm:grid-cols-2">
                <div>
                  <label htmlFor="immeuble" className="label">
                    Immeuble <span className="text-rose-400">*</span>
                  </label>
                  <select
                    id="immeuble"
                    value={immeubleId}
                    onChange={(e) => setImmeubleId(e.target.value)}
                    className="input"
                    disabled={!entrepriseId || loadingImm}
                    required
                  >
                    <option value="">
                      {loadingImm
                        ? "Chargement…"
                        : !entrepriseId
                          ? "Choisis d'abord une compagnie"
                          : immeubles.length === 0
                            ? "Aucun immeuble"
                            : "— Choisir —"}
                    </option>
                    {immeubles.map((i) => (
                      <option key={i.id} value={String(i.id)}>
                        {i.name}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label htmlFor="logement" className="label">
                    Appartement
                  </label>
                  <select
                    id="logement"
                    value={logementId}
                    onChange={(e) => setLogementId(e.target.value)}
                    className="input"
                    disabled={!immeubleId || loadingLog}
                  >
                    <option value="">
                      {loadingLog
                        ? "Chargement…"
                        : "Communs / immeuble entier"}
                    </option>
                    {logements.map((l) => (
                      <option key={l.id} value={String(l.id)}>
                        App {l.numero}
                      </option>
                    ))}
                  </select>
                  <p className="mt-1 text-xs text-white/50">
                    Laisse vide pour les communs ou l&apos;immeuble entier.
                  </p>
                </div>
              </div>
                </>
              )}
            </div>
          </fieldset>

          {/* ── Exécutant ─────────────────────────────────────────── */}
          <fieldset className="rounded-xl border border-brand-800 bg-brand-900/40 p-4">
            <legend className="px-2 text-sm font-semibold text-white">
              Exécutant
            </legend>
            <div className="grid gap-2 sm:grid-cols-2">
              <button
                type="button"
                onClick={() => setExecutantType("nos_hommes")}
                className={`flex items-center gap-2 rounded-xl border p-3 text-left transition ${
                  executantType === "nos_hommes"
                    ? "border-accent-500 bg-brand-900"
                    : "border-brand-800 bg-brand-900/60 hover:border-brand-700"
                }`}
              >
                <Wrench className="h-5 w-5 text-sky-300" />
                <p className="text-sm font-semibold text-white">
                  Nos hommes à tout faire
                </p>
              </button>
              <button
                type="button"
                onClick={() => setExecutantType("sous_traitant")}
                className={`flex items-center gap-2 rounded-xl border p-3 text-left transition ${
                  executantType === "sous_traitant"
                    ? "border-accent-500 bg-brand-900"
                    : "border-brand-800 bg-brand-900/60 hover:border-brand-700"
                }`}
              >
                <HardHat className="h-5 w-5 text-orange-300" />
                <p className="text-sm font-semibold text-white">
                  Sous-traitant
                </p>
              </button>
            </div>
            {executantType === "sous_traitant" ? (
              <div className="mt-4">
                <label htmlFor="sous_traitant" className="label">
                  Quel sous-traitant ?{" "}
                  <span className="text-rose-400">*</span>
                </label>
                {(() => {
                  const q = sousTraitantSearch.trim().toLowerCase();
                  const filtered = q
                    ? sousTraitants.filter((s) =>
                        s.full_name.toLowerCase().includes(q)
                      )
                    : sousTraitants;
                  const selected = sousTraitants.find(
                    (s) => String(s.id) === sousTraitantId
                  );
                  return (
                    <div className="relative">
                      <input
                        id="sous_traitant"
                        type="text"
                        autoComplete="off"
                        value={
                          sousTraitantOpen
                            ? sousTraitantSearch
                            : selected?.full_name || ""
                        }
                        onChange={(e) => {
                          setSousTraitantSearch(e.target.value);
                          setSousTraitantOpen(true);
                        }}
                        onFocus={() => {
                          setSousTraitantOpen(true);
                          setSousTraitantSearch("");
                        }}
                        onBlur={() =>
                          setTimeout(() => setSousTraitantOpen(false), 150)
                        }
                        placeholder="Écrire le nom du sous-traitant…"
                        className="input"
                      />
                      {sousTraitantOpen ? (
                        <div className="absolute z-20 mt-1 max-h-56 w-full overflow-auto rounded-lg border border-brand-700 bg-brand-900 shadow-card">
                          {filtered.length === 0 ? (
                            <p className="px-3 py-2 text-sm text-white/40">
                              Aucun sous-traitant trouvé.
                            </p>
                          ) : (
                            filtered.map((s) => (
                              <button
                                key={s.id}
                                type="button"
                                onMouseDown={(e) => e.preventDefault()}
                                onClick={() => {
                                  setSousTraitantId(String(s.id));
                                  setSousTraitantOpen(false);
                                  setSousTraitantSearch("");
                                }}
                                className={`flex w-full items-center px-3 py-2 text-left text-sm hover:bg-brand-800 ${
                                  String(s.id) === sousTraitantId
                                    ? "text-accent-500"
                                    : "text-white/80"
                                }`}
                              >
                                {s.full_name}
                              </button>
                            ))
                          )}
                        </div>
                      ) : null}
                    </div>
                  );
                })()}
              </div>
            ) : null}
          </fieldset>

          {/* ── Travail ───────────────────────────────────────────── */}
          <div>
            <label htmlFor="title" className="label">
              Titre du travail <span className="text-rose-400">*</span>
            </label>
            <input
              id="title"
              type="text"
              required
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="Ex. Réparation de la toiture — fuite côté cour"
              className="input"
            />
          </div>

          <div>
            <label htmlFor="description" className="label">
              Description
            </label>
            <textarea
              id="description"
              rows={4}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Détails du travail à faire…"
              className="input"
            />
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label htmlFor="assignee" className="label">
                Responsable / gestionnaire
              </label>
              <select
                id="assignee"
                value={assigneeId}
                onChange={(e) => setAssigneeId(e.target.value)}
                className="input"
              >
                <option value="">— Non assigné —</option>
                {users.map((u) => (
                  <option key={u.id} value={String(u.id)}>
                    {u.full_name || u.email}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label htmlFor="marge" className="label">
                Marge par défaut (%)
              </label>
              <input
                id="marge"
                type="number"
                step="0.5"
                min="0"
                value={margePct}
                onChange={(e) => setMargePct(e.target.value)}
                className="input"
              />
              <p className="mt-1 text-xs text-white/50">
                Appliquée sur la refacturation (modifiable par ligne).
              </p>
            </div>
          </div>

          <div>
            <label className="label">Photos (optionnel)</label>
            <input
              type="file"
              accept="image/*,application/pdf"
              multiple
              onChange={(e) =>
                setPhotos(e.target.files ? Array.from(e.target.files) : [])
              }
              className="block w-full text-sm text-white/70 file:mr-3 file:rounded-lg file:border-0 file:bg-accent-500 file:px-3 file:py-2 file:text-sm file:font-semibold file:text-brand-950 hover:file:bg-accent-400"
            />
            {photos.length > 0 ? (
              <p className="mt-1 text-xs text-white/50">
                {photos.length} fichier{photos.length > 1 ? "s" : ""} sélectionné
                {photos.length > 1 ? "s" : ""}.
              </p>
            ) : null}
          </div>

          {error ? <p className="text-sm text-rose-400">{error}</p> : null}

          <div className="flex items-center gap-3">
            <button
              type="submit"
              disabled={submitting}
              className="btn-accent btn-sm"
            >
              {submitting ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" /> Création…
                </>
              ) : (
                "Créer le bon"
              )}
            </button>
            <Link
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              href={"/app/bons" as any}
              className="btn-secondary btn-sm"
            >
              Annuler
            </Link>
          </div>
        </form>
      </div>
    </>
  );
}
