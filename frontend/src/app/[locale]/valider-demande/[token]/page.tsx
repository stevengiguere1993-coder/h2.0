"use client";

// Page publique (sans authentification) — le prospect valide les
// informations captées par la secrétaire IA Léa lors de son appel
// téléphonique, puis ajoute éventuellement des photos. Accédée via
// le lien tokenisé reçu par courriel après l'appel.
//
// Route : /[locale]/valider-demande/{token}

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import {
  CheckCircle2,
  Image as ImageIcon,
  Loader2,
  Save,
  Trash2,
  Upload
} from "lucide-react";

type PublicContact = {
  id: number;
  name: string;
  email: string;
  phone: string | null;
  address: string | null;
  project_type: string;
  budget_range: string | null;
  message: string;
  locale: string;
  intake_data: string | null;
  validated_at: string | null;
};

type Photo = {
  id: number;
  content_type: string;
  filename: string | null;
  created_at: string;
};

const PROJECT_TYPES: Record<string, string> = {
  cuisine: "Cuisine",
  salle_bain: "Salle de bain",
  multilogement: "Multilogement",
  renovation_complete: "Rénovation complète",
  autre: "Autre"
};

export default function ValidateRequestPage() {
  const params = useParams<{ token: string }>();
  const token = params.token;

  const [data, setData] = useState<PublicContact | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [address, setAddress] = useState("");
  const [projectType, setProjectType] = useState("autre");
  const [budgetRange, setBudgetRange] = useState("");
  const [message, setMessage] = useState("");

  const [photos, setPhotos] = useState<Photo[]>([]);
  const [uploadBusy, setUploadBusy] = useState(false);
  const [saveBusy, setSaveBusy] = useState(false);
  const [confirmBusy, setConfirmBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const r = await fetch(`/api/v1/contact/by-token/${token}`, {
        cache: "no-store"
      });
      if (!r.ok) throw new Error("not_found");
      const d = (await r.json()) as PublicContact;
      setData(d);
      setName(d.name);
      setEmail(d.email);
      setPhone(d.phone || "");
      setAddress(d.address || "");
      setProjectType(d.project_type);
      setBudgetRange(d.budget_range || "");
      setMessage(d.message);
      // Photos
      const pr = await fetch(`/api/v1/contact/by-token/${token}/photos`, {
        cache: "no-store"
      });
      if (pr.ok) setPhotos((await pr.json()) as Photo[]);
    } catch {
      setError(
        "Ce lien est introuvable ou a expiré. Si vous pensez qu'il y a une erreur, contactez-nous au 438 800 2979."
      );
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (token) load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  async function save() {
    setSaveBusy(true);
    setNotice(null);
    try {
      const r = await fetch(`/api/v1/contact/by-token/${token}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: name.trim(),
          email: email.trim(),
          phone: phone.trim() || null,
          address: address.trim() || null,
          project_type: projectType,
          budget_range: budgetRange.trim() || null,
          message: message.trim()
        })
      });
      if (!r.ok) throw new Error();
      const d = (await r.json()) as PublicContact;
      setData(d);
      setNotice("Modifications enregistrées.");
    } catch {
      setNotice("Échec de la sauvegarde. Réessayez.");
    } finally {
      setSaveBusy(false);
    }
  }

  async function uploadPhotos(files: FileList | null) {
    if (!files || files.length === 0) return;
    setUploadBusy(true);
    setNotice(null);
    try {
      for (const file of Array.from(files)) {
        const fd = new FormData();
        fd.append("file", file);
        const r = await fetch(
          `/api/v1/contact/by-token/${token}/photos`,
          { method: "POST", body: fd }
        );
        if (!r.ok) {
          const t = await r.text().catch(() => "");
          throw new Error(t.slice(0, 200));
        }
      }
      const pr = await fetch(
        `/api/v1/contact/by-token/${token}/photos`,
        { cache: "no-store" }
      );
      if (pr.ok) setPhotos((await pr.json()) as Photo[]);
      setNotice("Photos téléversées.");
    } catch (e) {
      setNotice(`Upload échoué : ${(e as Error).message}`);
    } finally {
      setUploadBusy(false);
    }
  }

  async function deletePhoto(id: number) {
    if (!confirm("Supprimer cette photo ?")) return;
    try {
      const r = await fetch(
        `/api/v1/contact/by-token/${token}/photos/${id}`,
        { method: "DELETE" }
      );
      if (!r.ok && r.status !== 204) throw new Error();
      setPhotos((xs) => xs.filter((p) => p.id !== id));
    } catch {
      setNotice("Suppression de photo échouée.");
    }
  }

  async function confirmRequest() {
    setConfirmBusy(true);
    setNotice(null);
    try {
      const r = await fetch(
        `/api/v1/contact/by-token/${token}/confirm`,
        { method: "POST" }
      );
      if (!r.ok) throw new Error();
      const d = (await r.json()) as PublicContact;
      setData(d);
      setNotice(
        "Merci ! Votre demande est confirmée. Nous vous rappellerons sous peu."
      );
    } catch {
      setNotice("Échec de la confirmation. Réessayez.");
    } finally {
      setConfirmBusy(false);
    }
  }

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-brand-950">
        <Loader2 className="h-8 w-8 animate-spin text-accent-500" />
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-brand-950 p-6">
        <div className="max-w-md rounded-2xl border border-rose-500/40 bg-rose-500/10 p-6 text-rose-200">
          <h1 className="text-lg font-bold">Lien indisponible</h1>
          <p className="mt-2 text-sm">{error}</p>
        </div>
      </div>
    );
  }

  const isValidated = !!data.validated_at;

  return (
    <div className="min-h-screen bg-brand-950 px-4 py-10">
      <div className="mx-auto max-w-2xl">
        <header className="mb-6 text-center">
          <p className="text-xs uppercase tracking-widest text-accent-500">
            Horizon Services Immobiliers
          </p>
          <h1 className="mt-2 text-2xl font-bold text-white">
            Validez votre demande de soumission
          </h1>
          <p className="mt-2 text-sm text-white/60">
            Voici les informations que nous avons captées lors de notre
            appel. Vérifiez-les, ajustez si besoin, et ajoutez des
            photos pour qu'on prépare un devis précis.
          </p>
        </header>

        {isValidated ? (
          <div className="mb-6 rounded-xl border border-emerald-500/40 bg-emerald-500/10 p-4 text-sm text-emerald-200">
            <div className="flex items-center gap-2">
              <CheckCircle2 className="h-5 w-5" />
              <strong>Demande confirmée</strong>
            </div>
            <p className="mt-1">
              Confirmée le{" "}
              {new Date(data.validated_at!).toLocaleString("fr-CA")}.
              Vous pouvez toujours modifier les infos ou ajouter des
              photos ci-dessous.
            </p>
          </div>
        ) : null}

        {notice ? (
          <div className="mb-4 rounded-lg border border-blue-500/30 bg-blue-500/10 px-4 py-2 text-sm text-blue-200">
            {notice}
          </div>
        ) : null}

        <section className="rounded-2xl border border-brand-800 bg-brand-900 p-5">
          <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
            Informations
          </h2>
          <div className="mt-4 grid gap-3 sm:grid-cols-2">
            <Field
              label="Votre nom"
              value={name}
              onChange={setName}
              required
            />
            <Field
              label="Courriel"
              value={email}
              onChange={setEmail}
              type="email"
              required
            />
            <Field
              label="Téléphone"
              value={phone}
              onChange={setPhone}
              type="tel"
            />
            <Field
              label="Adresse du projet"
              value={address}
              onChange={setAddress}
            />
            <label className="flex flex-col gap-1.5">
              <span className="text-[11px] font-semibold uppercase tracking-wider text-white/50">
                Type de travaux
              </span>
              <select
                value={projectType}
                onChange={(e) => setProjectType(e.target.value)}
                className="rounded-md border border-brand-800 bg-brand-950 px-3 py-2 text-sm text-white focus:border-accent-500 focus:outline-none"
              >
                {Object.entries(PROJECT_TYPES).map(([k, v]) => (
                  <option key={k} value={k}>
                    {v}
                  </option>
                ))}
              </select>
            </label>
            <Field
              label="Budget envisagé"
              value={budgetRange}
              onChange={setBudgetRange}
              placeholder="ex. 15 000 $ – 25 000 $"
            />
          </div>
          <label className="mt-3 flex flex-col gap-1.5">
            <span className="text-[11px] font-semibold uppercase tracking-wider text-white/50">
              Détails du projet
            </span>
            <textarea
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              rows={5}
              className="rounded-md border border-brand-800 bg-brand-950 px-3 py-2 text-sm text-white focus:border-accent-500 focus:outline-none"
            />
          </label>
          <div className="mt-4 flex justify-end">
            <button
              type="button"
              onClick={save}
              disabled={saveBusy}
              className="inline-flex items-center gap-2 rounded-lg bg-accent-500 px-4 py-2 text-sm font-semibold text-brand-950 transition hover:bg-accent-400 disabled:opacity-60"
            >
              {saveBusy ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Save className="h-4 w-4" />
              )}
              Enregistrer les modifications
            </button>
          </div>
        </section>

        <section className="mt-6 rounded-2xl border border-brand-800 bg-brand-900 p-5">
          <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
            Photos du projet
          </h2>
          <p className="mt-1 text-xs text-white/50">
            Plusieurs photos de l'espace concerné nous aident énormément
            à préparer un devis précis (avant travaux, dégâts, mesures,
            inspirations…).
          </p>

          <label className="mt-4 flex cursor-pointer items-center justify-center gap-2 rounded-lg border-2 border-dashed border-brand-700 bg-brand-950 px-4 py-6 text-sm text-white/70 transition hover:border-accent-500 hover:text-white">
            {uploadBusy ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" />
                Téléversement…
              </>
            ) : (
              <>
                <Upload className="h-4 w-4" />
                Téléverser des photos (JPG, PNG, HEIC)
              </>
            )}
            <input
              type="file"
              accept="image/*"
              multiple
              hidden
              onChange={(e) => uploadPhotos(e.target.files)}
              disabled={uploadBusy}
            />
          </label>

          {photos.length > 0 ? (
            <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-3">
              {photos.map((p) => (
                <div
                  key={p.id}
                  className="group relative overflow-hidden rounded-lg border border-brand-800 bg-brand-950"
                >
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={`/api/v1/contact/by-token/${token}/photos/${p.id}/image`}
                    alt={p.filename || `Photo ${p.id}`}
                    className="aspect-square w-full object-cover"
                  />
                  <button
                    type="button"
                    onClick={() => deletePhoto(p.id)}
                    className="absolute right-1 top-1 rounded-md bg-rose-500/90 p-1 text-white opacity-0 transition group-hover:opacity-100"
                    aria-label="Supprimer la photo"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              ))}
            </div>
          ) : (
            <p className="mt-4 flex items-center gap-2 text-xs text-white/40">
              <ImageIcon className="h-3.5 w-3.5" />
              Aucune photo ajoutée pour le moment.
            </p>
          )}
        </section>

        <section className="mt-6 rounded-2xl border border-accent-500/40 bg-accent-500/5 p-5 text-center">
          <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
            Confirmer ma demande
          </h2>
          <p className="mt-2 text-sm text-white/70">
            Une fois confirmée, nous vous rappellerons sous peu pour
            fixer un rendez-vous sur place et préparer votre devis.
          </p>
          <button
            type="button"
            onClick={confirmRequest}
            disabled={confirmBusy || isValidated}
            className="mt-4 inline-flex items-center gap-2 rounded-lg bg-accent-500 px-6 py-3 text-sm font-semibold text-brand-950 transition hover:bg-accent-400 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {confirmBusy ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <CheckCircle2 className="h-4 w-4" />
            )}
            {isValidated ? "Demande confirmée" : "Confirmer ma demande"}
          </button>
        </section>

        <footer className="mt-8 text-center text-[11px] text-white/30">
          Horizon Services Immobiliers · Montréal, Québec · 438 800 2979
        </footer>
      </div>
    </div>
  );
}

function Field({
  label,
  value,
  onChange,
  type = "text",
  placeholder,
  required
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  type?: string;
  placeholder?: string;
  required?: boolean;
}) {
  return (
    <label className="flex flex-col gap-1.5">
      <span className="text-[11px] font-semibold uppercase tracking-wider text-white/50">
        {label}
        {required ? <span className="ml-1 text-rose-400">*</span> : null}
      </span>
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="rounded-md border border-brand-800 bg-brand-950 px-3 py-2 text-sm text-white placeholder:text-white/30 focus:border-accent-500 focus:outline-none"
      />
    </label>
  );
}
