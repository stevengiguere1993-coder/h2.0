"use client";

/**
 * Page publique — Formulaire de demande de devis Dev Logiciel.
 *
 * URL : /[locale]/dev-logiciel/contact (FR par defaut, /en/... en anglais)
 * Pas d'authentification. Theme clair (slate-50), mobile-first.
 *
 * Au submit : POST /api/v1/public/devlog/contact
 *   - Cree un DevlogLead avec source="web_form", status="new"
 *   - Notifie les managers + envoie email de confirmation au prospect
 *
 * Champs : nom*, email*, entreprise, telephone, type de projet,
 * budget, description* (min 20), + honeypot `website` (cache).
 *
 * Vague 1 #7 du plan strategique Dev Logiciel.
 */

import { useState, FormEvent } from "react";
import { CheckCircle2, Loader2, XCircle } from "lucide-react";

const PROJECT_TYPES: Array<{ value: string; label: string }> = [
  { value: "web_app", label: "Site web ou application web" },
  { value: "mobile_app", label: "Application mobile" },
  { value: "automation", label: "Automatisation / Integration" },
  { value: "integration", label: "Integration de systemes" },
  { value: "consulting", label: "Conseil / Audit" },
  { value: "autre", label: "Autre" }
];

const BUDGET_RANGES: string[] = [
  "Moins de 5 000 $",
  "5 000 — 15 000 $",
  "15 000 — 50 000 $",
  "50 000 — 150 000 $",
  "Plus de 150 000 $",
  "A discuter"
];

type SubmitState = "idle" | "loading" | "success" | "error";

export default function DevlogContactPage() {
  const [state, setState] = useState<SubmitState>("idle");
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  // Champs du formulaire
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [company, setCompany] = useState("");
  const [phone, setPhone] = useState("");
  const [projectType, setProjectType] = useState("web_app");
  const [budgetRange, setBudgetRange] = useState("");
  const [description, setDescription] = useState("");
  // Honeypot — doit rester vide ; les bots remplissent les champs caches.
  const [website, setWebsite] = useState("");

  function validateClient(): string | null {
    if (!name.trim() || name.trim().length < 2) {
      return "Veuillez entrer votre nom complet.";
    }
    const emailOk = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim());
    if (!emailOk) {
      return "Veuillez entrer un courriel valide.";
    }
    if (description.trim().length < 20) {
      return "La description doit contenir au moins 20 caracteres.";
    }
    if (description.trim().length > 5000) {
      return "La description est trop longue (max 5000 caracteres).";
    }
    return null;
  }

  async function handleSubmit(evt: FormEvent<HTMLFormElement>) {
    evt.preventDefault();
    if (state === "loading") return;

    const clientErr = validateClient();
    if (clientErr) {
      setErrorMsg(clientErr);
      setState("error");
      return;
    }

    setState("loading");
    setErrorMsg(null);

    try {
      const res = await fetch("/api/v1/public/devlog/contact", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          name: name.trim(),
          email: email.trim(),
          company: company.trim() || null,
          phone: phone.trim() || null,
          project_type: projectType,
          description: description.trim(),
          budget_range: budgetRange || null,
          locale: "fr",
          website: website || null
        })
      });

      if (!res.ok) {
        const txt = await res.text();
        throw new Error(txt.slice(0, 200) || `HTTP ${res.status}`);
      }

      const data = (await res.json()) as { success: boolean };
      if (!data.success) throw new Error("submission_failed");
      setState("success");
    } catch (e) {
      setErrorMsg((e as Error).message || "Erreur inconnue.");
      setState("error");
    }
  }

  // ---------------------- Vue succes ----------------------
  if (state === "success") {
    return (
      <div className="min-h-screen bg-slate-50 px-4 py-12">
        <div className="mx-auto max-w-xl">
          <div className="rounded-2xl border border-emerald-200 bg-white p-8 text-center shadow-sm">
            <CheckCircle2 className="mx-auto h-12 w-12 text-emerald-500" />
            <h1 className="mt-4 text-2xl font-bold text-slate-900">
              Merci !
            </h1>
            <p className="mt-3 text-sm text-slate-700">
              Nous avons bien recu ta demande. Tu vas recevoir un courriel
              de confirmation et notre equipe te recontacte sous{" "}
              <strong>24 heures ouvrables</strong>.
            </p>
            <a
              href="https://immohorizon.com"
              className="mt-6 inline-block rounded-lg bg-emerald-600 px-5 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-emerald-700"
            >
              Retour au site
            </a>
          </div>
        </div>
      </div>
    );
  }

  // ---------------------- Vue formulaire ----------------------
  return (
    <div className="min-h-screen bg-slate-50 px-4 py-8">
      <div className="mx-auto max-w-2xl">
        <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm sm:p-8">
          {/* Header */}
          <div className="border-b border-slate-200 pb-5">
            <p className="text-xs font-semibold uppercase tracking-wider text-emerald-700">
              Horizon Services Immobiliers
            </p>
            <h1 className="mt-1 text-2xl font-bold text-slate-900 sm:text-3xl">
              Demande de devis — Developpement logiciel
            </h1>
            <p className="mt-2 text-sm text-slate-600">
              Site web, application, automatisation, integration... Decris
              ton projet et nous te recontactons sous 24 h ouvrables.
            </p>
          </div>

          {/* Erreur globale */}
          {state === "error" && errorMsg ? (
            <div className="mt-5 flex items-start gap-3 rounded-lg border border-rose-200 bg-rose-50 p-4 text-sm text-rose-900">
              <XCircle className="mt-0.5 h-5 w-5 flex-shrink-0 text-rose-500" />
              <div>
                <p className="font-semibold">Une erreur s&apos;est produite.</p>
                <p className="mt-0.5 text-rose-800">
                  Reessaie ou ecris-nous directement a{" "}
                  <a
                    href="mailto:info@immohorizon.com"
                    className="underline"
                  >
                    info@immohorizon.com
                  </a>
                  .
                </p>
                <p className="mt-1 text-xs text-rose-700">
                  Detail : {errorMsg}
                </p>
              </div>
            </div>
          ) : null}

          {/* Formulaire */}
          <form onSubmit={handleSubmit} className="mt-6 space-y-5">
            {/* Honeypot — cache visuellement, accessible aux bots */}
            <div
              style={{
                position: "absolute",
                left: "-9999px",
                top: "auto",
                width: "1px",
                height: "1px",
                overflow: "hidden"
              }}
              aria-hidden="true"
            >
              <label>
                Site web (ne pas remplir)
                <input
                  type="text"
                  name="website"
                  tabIndex={-1}
                  autoComplete="off"
                  value={website}
                  onChange={(e) => setWebsite(e.target.value)}
                />
              </label>
            </div>

            {/* Nom complet */}
            <label className="block">
              <span className="text-xs font-semibold uppercase tracking-wider text-slate-600">
                Nom complet <span className="text-rose-500">*</span>
              </span>
              <input
                type="text"
                required
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Prenom Nom"
                className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900 placeholder:text-slate-400 focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
              />
            </label>

            {/* Email */}
            <label className="block">
              <span className="text-xs font-semibold uppercase tracking-wider text-slate-600">
                Courriel <span className="text-rose-500">*</span>
              </span>
              <input
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="vous@exemple.com"
                className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900 placeholder:text-slate-400 focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
              />
            </label>

            <div className="grid grid-cols-1 gap-5 sm:grid-cols-2">
              {/* Entreprise */}
              <label className="block">
                <span className="text-xs font-semibold uppercase tracking-wider text-slate-600">
                  Entreprise
                </span>
                <input
                  type="text"
                  value={company}
                  onChange={(e) => setCompany(e.target.value)}
                  placeholder="Nom de votre entreprise"
                  className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900 placeholder:text-slate-400 focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
                />
              </label>

              {/* Telephone */}
              <label className="block">
                <span className="text-xs font-semibold uppercase tracking-wider text-slate-600">
                  Telephone
                </span>
                <input
                  type="tel"
                  value={phone}
                  onChange={(e) => setPhone(e.target.value)}
                  placeholder="(514) 555-1234"
                  className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900 placeholder:text-slate-400 focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
                />
              </label>
            </div>

            <div className="grid grid-cols-1 gap-5 sm:grid-cols-2">
              {/* Type de projet */}
              <label className="block">
                <span className="text-xs font-semibold uppercase tracking-wider text-slate-600">
                  Type de projet <span className="text-rose-500">*</span>
                </span>
                <select
                  required
                  value={projectType}
                  onChange={(e) => setProjectType(e.target.value)}
                  className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
                >
                  {PROJECT_TYPES.map((pt) => (
                    <option key={pt.value} value={pt.value}>
                      {pt.label}
                    </option>
                  ))}
                </select>
              </label>

              {/* Budget */}
              <label className="block">
                <span className="text-xs font-semibold uppercase tracking-wider text-slate-600">
                  Budget envisage
                </span>
                <select
                  value={budgetRange}
                  onChange={(e) => setBudgetRange(e.target.value)}
                  className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
                >
                  <option value="">Choisir...</option>
                  {BUDGET_RANGES.map((b) => (
                    <option key={b} value={b}>
                      {b}
                    </option>
                  ))}
                </select>
              </label>
            </div>

            {/* Description */}
            <label className="block">
              <span className="text-xs font-semibold uppercase tracking-wider text-slate-600">
                Description du projet <span className="text-rose-500">*</span>
              </span>
              <textarea
                required
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                rows={6}
                minLength={20}
                maxLength={5000}
                placeholder="Decris ton besoin : contexte, fonctionnalites souhaitees, echeancier, contraintes techniques..."
                className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900 placeholder:text-slate-400 focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
              />
              <p className="mt-1 text-xs text-slate-500">
                {description.trim().length} / 5000 caracteres (min 20)
              </p>
            </label>

            {/* Bouton submit */}
            <div className="pt-2">
              <button
                type="submit"
                disabled={state === "loading"}
                className="inline-flex w-full items-center justify-center gap-2 rounded-lg bg-emerald-600 px-5 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-emerald-700 disabled:cursor-not-allowed disabled:opacity-60 sm:w-auto"
              >
                {state === "loading" ? (
                  <>
                    <Loader2 className="h-4 w-4 animate-spin" />
                    Envoi en cours...
                  </>
                ) : (
                  "Envoyer ma demande"
                )}
              </button>
              <p className="mt-3 text-xs text-slate-500">
                En soumettant ce formulaire, tu acceptes que Horizon Services
                Immobiliers te recontacte au sujet de ton projet.
              </p>
            </div>
          </form>
        </div>

        <p className="mt-4 text-center text-xs text-slate-500">
          Horizon Services Immobiliers &mdash;{" "}
          <a href="https://immohorizon.com" className="underline">
            immohorizon.com
          </a>
        </p>
      </div>
    </div>
  );
}
