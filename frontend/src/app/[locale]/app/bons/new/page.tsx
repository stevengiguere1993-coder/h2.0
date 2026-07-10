"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter as useNextRouter } from "next/navigation";
import { ArrowLeft, HardHat, Loader2, Wrench } from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { Link } from "@/i18n/navigation";
import { useAppLayout } from "../../layout";
import { authedFetch } from "@/lib/auth";

type Entreprise = { id: number; name: string };
type Immeuble = { id: number; name: string; address: string };
type Logement = { id: number; numero: string };
type SousTraitant = { id: number; full_name: string };
type User = { id: number; email: string; full_name?: string | null };

export default function NewBonPage() {
  const { onOpenSidebar } = useAppLayout();
  const router = useNextRouter();

  // Rattachement : compagnie → immeuble → appartement.
  const [entrepriseId, setEntrepriseId] = useState("");
  const [immeubleId, setImmeubleId] = useState("");
  const [logementId, setLogementId] = useState("");
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
        const [eRes, sRes, uRes] = await Promise.all([
          authedFetch("/api/v1/entreprises?limit=500"),
          authedFetch("/api/v1/sous-traitants?limit=500"),
          authedFetch("/api/v1/users")
        ]);
        if (cancelled) return;
        if (eRes.ok) setEntreprises((await eRes.json()) as Entreprise[]);
        if (sRes.ok) setSousTraitants((await sRes.json()) as SousTraitant[]);
        if (uRes.ok) setUsers((await uRes.json()) as User[]);
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
        const res = await authedFetch(
          `/api/v1/immobilier/immeubles?entreprise_id=${entrepriseId}`
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
          `/api/v1/immobilier/immeubles/${immeubleId}/logements`
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
    if (!entrepriseId) {
      setError("Choisis la compagnie propriétaire.");
      return;
    }
    if (!immeubleId) {
      setError("Choisis l'immeuble concerné.");
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
        owner_entreprise_id: Number(entrepriseId),
        immeuble_id: Number(immeubleId),
        executant_type: executantType,
        bon_type: "temps_materiel",
        marge_pct: margePct ? Number(margePct) : 0
      };
      if (logementId) payload.logement_id = Number(logementId);
      if (executantType === "sous_traitant")
        payload.sous_traitant_id = Number(sousTraitantId);
      if (description.trim()) payload.description = description.trim();
      if (assigneeId) payload.assignee_user_id = Number(assigneeId);
      const addr = buildAddress();
      if (addr) payload.address = addr;

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
          Entretien d&apos;un de nos immeubles. La référence est générée
          automatiquement.
        </p>

        <form onSubmit={onSubmit} className="mt-6 max-w-2xl space-y-6">
          {/* ── Rattachement ───────────────────────────────────────── */}
          <fieldset className="rounded-xl border border-brand-800 bg-brand-900/40 p-4">
            <legend className="px-2 text-sm font-semibold text-white">
              Rattachement
            </legend>
            <div className="space-y-4">
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
                  required
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
