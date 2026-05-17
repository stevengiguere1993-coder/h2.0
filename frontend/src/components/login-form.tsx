"use client";

import { useEffect, useState } from "react";
import {
  Briefcase,
  Building2,
  Code2,
  Loader2,
  MapPin,
  Monitor,
  Phone,
  Smartphone,
  Terminal,
  TrendingUp
} from "lucide-react";

import { useRouter } from "@/i18n/navigation";
import { authedFetch, getMe, getToken, login, setToken } from "@/lib/auth";

// Whitelist email autorisé à voir le bouton « Mode dev » sur le
// sélecteur de portail. Centralisé pour matcher /dev/page.tsx.
const DEV_ALLOWED_EMAILS = [
  "sgiguere@immohorizon.com",
  "philippe.meuser@immohorizon.com",
  "pmeuser@immohorizon.com"
];

// Volet « Téléphonie / Secrétaire d'appels » — en développement,
// visible pour l'instant uniquement par sgiguere@immohorizon.com.
// Étendre cette liste pour donner accès à d'autres comptes au fur
// et à mesure que le volet mûrit.
const TELEPHONIE_ALLOWED_EMAILS = [
  "sgiguere@immohorizon.com"
];

/**
 * After a successful login, we show a small picker asking the user
 * whether they want to go to the desktop portal (/app) or the mobile
 * employee app (/m). A `?next=` param from an auth-redirect takes
 * precedence so deep links keep working. We read the query string from
 * `window.location` on mount — avoiding next/navigation's
 * useSearchParams which forces a Suspense boundary on prerendered pages.
 */
export function LoginForm() {
  const router = useRouter();
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [authed, setAuthed] = useState(false);
  const [nextUrl, setNextUrl] = useState<string | null>(null);
  const [userEmail, setUserEmail] = useState<string | null>(null);
  const [userVolets, setUserVolets] = useState<string[]>([]);
  const [userRole, setUserRole] = useState<string>("");
  const [pendingHelp, setPendingHelp] = useState(0);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const n = new URLSearchParams(window.location.search).get("next");
    if (n && n.startsWith("/")) setNextUrl(n);

    // Si l'utilisateur est déjà authentifié (a cliqué « Accueil du
    // portail » depuis une appli déjà ouverte), saute le formulaire
    // login et montre directement le sélecteur de portail.
    const existing = getToken();
    if (!existing) return;
    let cancelled = false;
    (async () => {
      try {
        const me = await getMe(existing);
        if (cancelled) return;
        if (me.must_change_password) return; // laisse le user voir le form
        // Employé construction (ou compte legacy sans volets_json) →
        // bypass picker, app mobile chantier directe. Un employé d'un
        // AUTRE volet (ex. prospection) doit voir le sélecteur de
        // portail pour atterrir sur SON volet — on ne le force pas
        // vers /m (qui est l'app chantier construction).
        if (me.role === "employee") {
          const v = Array.isArray(me.volets) ? me.volets : [];
          if (v.length === 0 || v.includes("construction")) {
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            router.replace("/m" as any);
            return;
          }
        }
        setUserEmail(me.email || null);
        setUserVolets(Array.isArray(me.volets) ? me.volets : []);
        setUserRole(me.role || "");
        setAuthed(true);
      } catch {
        // Token invalide → laisse le user voir le formulaire login
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [router]);

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    const fd = new FormData(e.currentTarget);
    const email = String(fd.get("email") || "");
    const password = String(fd.get("password") || "");
    const rememberMe = fd.get("remember_me") === "on";
    try {
      const result = await login(email, password, rememberMe);
      setToken(result.access_token);
      // If a ?next=... URL was provided (deep link), honor it directly.
      if (nextUrl) {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        router.replace(nextUrl as any);
        return;
      }
      // Employés construction → app mobile chantier directe. Employés
      // d'un autre volet (ex. prospection) + manager/owner → sélecteur
      // de portail pour choisir / atterrir sur leur volet.
      try {
        const me = await getMe(result.access_token);
        // First-login (or admin-triggered reset) — force the user
        // through the change-password screen before going anywhere.
        if (me.must_change_password) {
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          router.replace("/changer-mot-de-passe" as any);
          return;
        }
        if (me.role === "employee") {
          const v = Array.isArray(me.volets) ? me.volets : [];
          // Seul un employé construction (ou legacy sans volets) file
          // direct vers /m. Les autres voient le sélecteur de portail.
          if (v.length === 0 || v.includes("construction")) {
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            router.replace("/m" as any);
            return;
          }
        }
        // IMPORTANT : on hydrate volets + role AVANT setAuthed(true)
        // sinon le picker rend avec userRole="" et les pastilles
        // gated sur le rôle (Gestion d'entreprises, etc.) restent
        // cachées jusqu'au prochain refresh.
        setUserEmail(me.email || null);
        setUserVolets(Array.isArray(me.volets) ? me.volets : []);
        setUserRole(me.role || "");
      } catch {
        /* fall through to picker */
      }
      setAuthed(true);
    } catch (err) {
      const code = (err as Error & { code?: string }).code || "unknown";
      setError(
        code === "invalid_credentials"
          ? "Identifiants invalides."
          : "Erreur de connexion."
      );
    } finally {
      setSubmitting(false);
    }
  }

  // Fetch pending help requests count for the dev badge — visible
  // uniquement pour les emails whitelistés. Refresh toutes les 60s.
  useEffect(() => {
    if (!authed || !userEmail) return;
    const norm = userEmail.toLowerCase().trim();
    if (!DEV_ALLOWED_EMAILS.includes(norm)) return;
    let cancelled = false;
    async function fetchCount() {
      try {
        const res = await authedFetch(
          "/api/v1/help/reports?status_filter=pending"
        );
        if (!res.ok) return;
        const data = (await res.json()) as Array<unknown>;
        if (!cancelled) setPendingHelp(Array.isArray(data) ? data.length : 0);
      } catch {
        /* silent */
      }
    }
    void fetchCount();
    const t = setInterval(fetchCount, 60_000);
    return () => {
      cancelled = true;
      clearInterval(t);
    };
  }, [authed, userEmail]);

  if (authed) {
    const showDev =
      !!userEmail &&
      DEV_ALLOWED_EMAILS.includes(userEmail.toLowerCase().trim());
    // Filtre les pastilles de portail selon les volets accessibles.
    // Si la liste est vide (anciens comptes sans volets_json), on
    // affiche tout par sécurité (backward-compat).
    const has = (v: string) =>
      userVolets.length === 0 || userVolets.includes(v);
    // Comparaison de rôle insensible à la casse / espaces pour éviter
    // de cacher la pastille « Gestion d'entreprises » à cause d'un
    // « Owner » / « OWNER » / « owner  » qui ne matcherait pas
    // l'égalité stricte.
    const role = (userRole || "").toLowerCase().trim();
    const isOwner = role === "owner";
    const isAdminOrOwner = role === "owner" || role === "admin";
    const showTelephonie =
      !!userEmail &&
      TELEPHONIE_ALLOWED_EMAILS.includes(
        userEmail.toLowerCase().trim()
      );
    return (
      <div className="relative space-y-4">
        {showDev ? (
          <button
            type="button"
            onClick={() => {
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              router.replace("/dev" as any);
            }}
            className="absolute right-0 top-0 inline-flex items-center gap-1.5 rounded-full border border-amber-400/40 bg-amber-500/10 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wider text-amber-200 hover:bg-amber-500/20"
            title={
              pendingHelp > 0
                ? `${pendingHelp} demande(s) d'aide en attente`
                : "Outils internes (mode dev)"
            }
          >
            <Terminal className="h-3 w-3" />
            Mode dev
            {pendingHelp > 0 ? (
              <span className="ml-1 inline-flex h-4 min-w-[16px] items-center justify-center rounded-full bg-rose-500 px-1 text-[9px] font-bold text-white">
                {pendingHelp > 99 ? "99+" : pendingHelp}
              </span>
            ) : null}
          </button>
        ) : null}
        <header className="text-center">
          <p className="text-sm text-white/60">Bienvenue 👋</p>
          <h2 className="mt-1 text-xl font-bold text-white">
            Où veux-tu aller ?
          </h2>
        </header>

        <div className="grid gap-3">
          {has("construction") ? (
            <button
              type="button"
              onClick={() => {
                // eslint-disable-next-line @typescript-eslint/no-explicit-any
                router.replace("/app" as any);
              }}
              className="group flex items-center gap-4 rounded-2xl border border-brand-800 bg-brand-900 p-5 text-left transition hover:border-accent-500 hover:bg-brand-800"
            >
              <span className="flex h-12 w-12 items-center justify-center rounded-xl bg-accent-500/15 text-accent-500 group-hover:bg-accent-500 group-hover:text-brand-950">
                <Monitor className="h-6 w-6" />
              </span>
              <span className="flex-1">
                <span className="block text-base font-bold text-white">
                  Portail web
                </span>
                <span className="mt-0.5 block text-xs text-white/60">
                  Bureau / ordinateur — CRM, soumissions, factures, agenda,
                  finances.
                </span>
              </span>
            </button>
          ) : null}

          {has("construction") ? (
            <button
              type="button"
              onClick={() => {
                // eslint-disable-next-line @typescript-eslint/no-explicit-any
                router.replace("/m" as any);
              }}
              className="group flex items-center gap-4 rounded-2xl border border-brand-800 bg-brand-900 p-5 text-left transition hover:border-accent-500 hover:bg-brand-800"
            >
              <span className="flex h-12 w-12 items-center justify-center rounded-xl bg-blue-500/15 text-blue-400 group-hover:bg-blue-500 group-hover:text-white">
                <Smartphone className="h-6 w-6" />
              </span>
              <span className="flex-1">
                <span className="block text-base font-bold text-white">
                  Application mobile
                </span>
                <span className="mt-0.5 block text-xs text-white/60">
                  Employé sur chantier — poinçonner, agenda, intervention
                  avec photos.
                </span>
              </span>
            </button>
          ) : null}

          {has("prospection") ? (
            <button
              type="button"
              onClick={() => {
                // eslint-disable-next-line @typescript-eslint/no-explicit-any
                router.replace("/prospection" as any);
              }}
              className="group relative flex items-center gap-4 rounded-2xl border border-brand-800 bg-brand-900 p-5 text-left transition hover:border-accent-500 hover:bg-brand-800"
            >
              <span className="flex h-12 w-12 items-center justify-center rounded-xl bg-emerald-500/15 text-emerald-400 group-hover:bg-emerald-500 group-hover:text-brand-950">
                <MapPin className="h-6 w-6" />
              </span>
              <span className="flex-1">
                <span className="block text-base font-bold text-white">
                  Prospection
                </span>
                <span className="mt-0.5 block text-xs text-white/60">
                  Repérage d&apos;immeubles — drive-by, photos, lookup
                  propriétaire, campagnes de contact.
                </span>
              </span>
              <span className="absolute right-3 top-3 inline-flex items-center rounded-full border border-amber-500/40 bg-amber-500/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-amber-300">
                En développement
              </span>
            </button>
          ) : null}

          {/* Pôle Développement logiciel — visible pour tous les
              utilisateurs (nouveau pôle interne). */}
          <button
            type="button"
            onClick={() => {
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              router.replace("/dev-logiciel" as any);
            }}
            className="group relative flex items-center gap-4 rounded-2xl border border-brand-800 bg-brand-900 p-5 text-left transition hover:border-blue-400 hover:bg-brand-800"
          >
            <span className="flex h-12 w-12 items-center justify-center rounded-xl bg-blue-500/15 text-blue-400 group-hover:bg-blue-500 group-hover:text-white">
              <Code2 className="h-6 w-6" />
            </span>
            <span className="flex-1">
              <span className="block text-base font-bold text-white">
                Développement logiciel
              </span>
              <span className="mt-0.5 block text-xs text-white/60">
                Pipeline du closer, clients et projets de développement de
                plateformes.
              </span>
            </span>
            <span className="absolute right-3 top-3 inline-flex items-center rounded-full border border-amber-500/40 bg-amber-500/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-amber-300">
              En développement
            </span>
          </button>

          {has("entreprises") && isOwner ? (
            <button
              type="button"
              onClick={() => {
                // eslint-disable-next-line @typescript-eslint/no-explicit-any
                router.replace("/entreprises" as any);
              }}
              className="group relative flex items-center gap-4 rounded-2xl border border-brand-800 bg-brand-900 p-5 text-left transition hover:border-violet-400 hover:bg-brand-800"
            >
              <span className="flex h-12 w-12 items-center justify-center rounded-xl bg-violet-500/15 text-violet-300 group-hover:bg-violet-500 group-hover:text-white">
                <Briefcase className="h-6 w-6" />
              </span>
              <span className="flex-1">
                <span className="block text-base font-bold text-white">
                  Gestion d&apos;entreprises
                </span>
                <span className="mt-0.5 block text-xs text-white/60">
                  Tâches multi-entreprises, scoring, assignation, daily
                  pulse, suivi de projets.
                </span>
              </span>
              <span className="absolute right-3 top-3 inline-flex items-center rounded-full border border-amber-500/40 bg-amber-500/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-amber-300">
                En développement
              </span>
            </button>
          ) : null}

          {has("immobilier") ? (
            <button
              type="button"
              onClick={() => {
                // eslint-disable-next-line @typescript-eslint/no-explicit-any
                router.replace("/immobilier" as any);
              }}
              className="group relative flex items-center gap-4 rounded-2xl border border-brand-800 bg-brand-900 p-5 text-left transition hover:border-sky-400 hover:bg-brand-800"
            >
              <span className="flex h-12 w-12 items-center justify-center rounded-xl bg-sky-500/15 text-sky-300 group-hover:bg-sky-500 group-hover:text-white">
                <Building2 className="h-6 w-6" />
              </span>
              <span className="flex-1">
                <span className="block text-base font-bold text-white">
                  Gestion immobilière
                </span>
                <span className="mt-0.5 block text-xs text-white/60">
                  Immeubles, locataires, baux, refinancements,
                  valorisation, documents.
                </span>
              </span>
              <span className="absolute right-3 top-3 inline-flex items-center rounded-full border border-amber-500/40 bg-amber-500/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-amber-300">
                En développement
              </span>
            </button>
          ) : null}

          {has("investisseur") ? (
            <button
              type="button"
              onClick={() => {
                // eslint-disable-next-line @typescript-eslint/no-explicit-any
                router.replace("/investisseur" as any);
              }}
              className="group relative flex items-center gap-4 rounded-2xl border border-brand-800 bg-brand-900 p-5 text-left transition hover:border-emerald-400 hover:bg-brand-800"
            >
              <span className="flex h-12 w-12 items-center justify-center rounded-xl bg-emerald-500/15 text-emerald-300 group-hover:bg-emerald-500 group-hover:text-brand-950">
                <TrendingUp className="h-6 w-6" />
              </span>
              <span className="flex-1">
                <span className="block text-base font-bold text-white">
                  Investisseurs
                </span>
                <span className="mt-0.5 block text-xs text-white/60">
                  Portail investisseurs : capital, valeur live, projection
                  KPI, activité 30 jours.
                </span>
              </span>
              <span className="absolute right-3 top-3 inline-flex items-center rounded-full border border-amber-500/40 bg-amber-500/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-amber-300">
                En développement
              </span>
            </button>
          ) : null}

          {/* Téléphonie / Secrétaire d'appels — gated par email
              (sgiguere@immohorizon.com uniquement pour l'instant).
              Placée en FIN de liste car en développement. */}
          {showTelephonie ? (
            <button
              type="button"
              onClick={() => {
                // eslint-disable-next-line @typescript-eslint/no-explicit-any
                router.replace("/telephonie" as any);
              }}
              className="group relative flex items-center gap-4 rounded-2xl border border-brand-800 bg-brand-900 p-5 text-left transition hover:border-teal-400 hover:bg-brand-800"
            >
              <span className="flex h-12 w-12 items-center justify-center rounded-xl bg-teal-500/15 text-teal-300 group-hover:bg-teal-500 group-hover:text-white">
                <Phone className="h-6 w-6" />
              </span>
              <span className="flex-1">
                <span className="block text-base font-bold text-white">
                  Téléphonie
                </span>
                <span className="mt-0.5 block text-xs text-white/60">
                  Secrétaire IA d&apos;appels — numéro 514, qualifier
                  les leads entrants, filtrer les indésirables,
                  transférer au bon user.
                </span>
              </span>
              <span className="absolute right-3 top-3 inline-flex items-center rounded-full border border-amber-500/40 bg-amber-500/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-amber-300">
                En développement
              </span>
            </button>
          ) : null}
        </div>

        <p className="pt-1 text-center text-[11px] text-white/40">
          Astuce : sur mobile, tape « Ajouter à l&apos;écran d&apos;accueil »
          après avoir choisi l&apos;app pour l&apos;installer.
        </p>

        {/* Audit IA — visible owner / admin uniquement. Résume les
            PRs mergés pour qu'un partner reprenant le développement
            voit en un coup d'œil ce qui a été ajouté / modifié. */}
        {isAdminOrOwner ? (
          <ChangelogAudit />
        ) : null}
      </div>
    );
  }

  return (
    <form onSubmit={onSubmit} className="space-y-5" noValidate>
      <div>
        <label htmlFor="email" className="label">Courriel</label>
        <input id="email" name="email" type="email" required autoComplete="email" className="input" />
      </div>
      <div>
        <label htmlFor="password" className="label">Mot de passe</label>
        <input id="password" name="password" type="password" required autoComplete="current-password" className="input" />
      </div>
      <label className="flex cursor-pointer items-center gap-2 text-sm text-brand-700">
        <input
          type="checkbox"
          name="remember_me"
          className="h-4 w-4 accent-accent-500"
        />
        Rester connecté pendant 12 h
      </label>
      {error ? <p className="text-sm text-red-600">{error}</p> : null}
      <button type="submit" disabled={submitting} className="btn-primary w-full">
        {submitting ? (
          <>
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            Connexion…
          </>
        ) : (
          "Se connecter"
        )}
      </button>
    </form>
  );
}

// ─── Audit IA des changements ────────────────────────────────────
//
// Lit /api/v1/audit/changes (cache backend 30 min). Affiche un
// résumé thématique des PRs mergés sur la fenêtre choisie. Visible
// owner / admin uniquement (la garde est déjà dans <LoginForm>).

type ChangesTheme = { title: string; bullets: string[] };
type ChangesPR = {
  number: number;
  title: string;
  merged_at: string;
  url: string;
};
type ChangesAudit = {
  window: string;
  period_start: string;
  period_end: string;
  pr_count: number;
  headline: string;
  themes: ChangesTheme[];
  prs: ChangesPR[];
  model_used: string | null;
  provider: string | null;
  generated_at: string;
  restricted?: boolean;
};

const WINDOW_OPTIONS: Array<{ value: string; label: string }> = [
  { value: "24h", label: "24 h" },
  { value: "48h", label: "48 h" },
  { value: "7d", label: "7 jours" },
  { value: "30d", label: "30 jours" },
  { value: "90d", label: "90 jours" }
];

function ChangelogAudit() {
  const [auditWindow, setAuditWindow] = useState("7d");
  const [data, setData] = useState<ChangesAudit | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);

  async function load(force: boolean) {
    setLoading(true);
    setError(null);
    try {
      const url = `/api/v1/audit/changes?window=${encodeURIComponent(auditWindow)}${force ? "&force=true" : ""}`;
      const r = await authedFetch(url);
      if (!r.ok) {
        const t = await r.text().catch(() => "");
        throw new Error(`HTTP ${r.status}${t ? ` — ${t.slice(0, 200)}` : ""}`);
      }
      setData((await r.json()) as ChangesAudit);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (!open) return;
    void load(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, auditWindow]);

  if (data?.restricted) return null;

  return (
    <section className="mt-6 rounded-2xl border border-brand-800 bg-brand-900/40 p-4">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between text-left"
      >
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-wider text-accent-500">
            ✦ Audit IA — modifications du code
          </p>
          <p className="mt-1 text-xs text-white/60">
            Résumé des PRs mergés pour reprise de développement.
          </p>
        </div>
        <span className="ml-3 text-white/60">{open ? "▾" : "▸"}</span>
      </button>

      {open ? (
        <div className="mt-3">
          <div className="flex flex-wrap items-center gap-2">
            <label className="text-[11px] text-white/60">Fenêtre :</label>
            <select
              value={auditWindow}
              onChange={(e) => setAuditWindow(e.target.value)}
              className="rounded-md border border-brand-700 bg-brand-900 px-2 py-1 text-[11px] text-white focus:border-accent-500 focus:outline-none"
            >
              {WINDOW_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
            <button
              type="button"
              onClick={() => void load(true)}
              disabled={loading}
              className="rounded-md border border-brand-700 bg-brand-900 px-2 py-1 text-[10px] font-semibold text-white/60 hover:text-white disabled:opacity-50"
              title="Regénérer (vide le cache 30 min)"
            >
              {loading ? "…" : "Regénérer"}
            </button>
          </div>

          {error ? (
            <p className="mt-3 rounded-md border border-rose-500/40 bg-rose-500/10 px-2 py-1 text-[11px] text-rose-300">
              {error}
            </p>
          ) : null}

          {loading && !data ? (
            <p className="mt-3 text-xs text-white/50">Chargement…</p>
          ) : data ? (
            <div className="mt-3 space-y-3">
              <div>
                <p className="text-sm font-bold text-white">
                  {data.headline}
                </p>
                <p className="mt-0.5 text-[10px] text-white/40">
                  {data.pr_count} PR(s) mergé(s)
                  {data.provider ? ` · ${data.provider}` : ""}
                  {data.model_used ? ` · ${data.model_used}` : ""}
                  {data.generated_at
                    ? ` · ${new Date(data.generated_at).toLocaleString("fr-CA", {
                        dateStyle: "short",
                        timeStyle: "short"
                      })}`
                    : ""}
                </p>
              </div>

              {data.themes.length > 0 ? (
                <ul className="space-y-3">
                  {data.themes.map((th, i) => (
                    <li key={i}>
                      <p className="text-[11px] font-semibold uppercase tracking-wider text-white/70">
                        {th.title}
                      </p>
                      <ul className="mt-1 space-y-1">
                        {th.bullets.map((b, j) => (
                          <li
                            key={j}
                            className="flex items-start gap-2 text-[12px] text-white/75"
                          >
                            <span className="text-accent-500">•</span>
                            <span>{b}</span>
                          </li>
                        ))}
                      </ul>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-xs text-white/50">
                  Aucun changement sur cette période.
                </p>
              )}

              {data.prs.length > 0 ? (
                <details className="mt-2">
                  <summary className="cursor-pointer text-[10px] text-white/40 hover:text-white/70">
                    Voir les PRs bruts ({data.prs.length})
                  </summary>
                  <ul className="mt-2 space-y-1">
                    {data.prs.slice(0, 30).map((p) => (
                      <li
                        key={p.number}
                        className="text-[11px] text-white/55"
                      >
                        <a
                          href={p.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="hover:text-accent-500"
                        >
                          #{p.number}
                        </a>{" "}
                        {p.title}
                      </li>
                    ))}
                  </ul>
                </details>
              ) : null}
            </div>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
