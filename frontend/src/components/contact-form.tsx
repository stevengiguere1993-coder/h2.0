"use client";

import { useEffect, useRef, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { Loader2, MapPin } from "lucide-react";
import { z } from "zod";

import { submitContactRequest } from "@/lib/api";

const budgetKeys = [
  "unsure",
  "under_10k",
  "10_25",
  "25_50",
  "50_100",
  "over_100"
] as const;

const projectKeys = [
  "salle_bain",
  "cuisine",
  "multilogement",
  "renovation_complete",
  "autre"
] as const;

const schema = z.object({
  name: z.string().min(2).max(255),
  email: z.string().email(),
  phone: z.string().max(50).optional().or(z.literal("")),
  address: z.string().max(500).optional().or(z.literal("")),
  project_type: z.enum(projectKeys),
  budget_range: z.string().max(32).optional().or(z.literal("")),
  message: z.string().min(10).max(5000),
  gdpr_consent: z.literal(true),
  marketing_consent: z.boolean()
});

type FormState =
  | { status: "idle" }
  | { status: "submitting" }
  | { status: "success"; reference: string }
  | { status: "error"; code: string };

type PhotonProps = {
  name?: string;
  housenumber?: string;
  street?: string;
  city?: string;
  state?: string;
  postcode?: string;
  country?: string;
  countrycode?: string;
};

type PhotonFeature = { properties: PhotonProps };

function formatPhotonAddress(p: PhotonProps): string {
  const street =
    p.housenumber && p.street
      ? `${p.housenumber} ${p.street}`
      : p.street || p.name || "";
  const parts = [street, p.city, p.state, p.postcode].filter(Boolean);
  return parts.join(", ");
}

export function ContactForm({ source }: { source?: string }) {
  const t = useTranslations("contact");
  const locale = useLocale();
  const [state, setState] = useState<FormState>({ status: "idle" });
  const [formError, setFormError] = useState<string | null>(null);

  // Address autocomplete (Photon / OpenStreetMap, no API key required).
  const [address, setAddress] = useState("");
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [showSuggestions, setShowSuggestions] = useState(false);
  const [loadingAddr, setLoadingAddr] = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  function onAddressChange(e: React.ChangeEvent<HTMLInputElement>) {
    const v = e.target.value;
    setAddress(v);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (abortRef.current) abortRef.current.abort();
    if (v.trim().length < 3) {
      setSuggestions([]);
      setShowSuggestions(false);
      return;
    }
    debounceRef.current = setTimeout(async () => {
      setLoadingAddr(true);
      const controller = new AbortController();
      abortRef.current = controller;
      try {
        const url =
          `https://photon.komoot.io/api/?q=${encodeURIComponent(v)}` +
          `&limit=6&lang=${locale === "en" ? "en" : "fr"}` +
          `&lat=45.55&lon=-73.65`;
        const res = await fetch(url, { signal: controller.signal });
        const data = (await res.json()) as { features?: PhotonFeature[] };
        const canadian = (data.features || [])
          .filter((f) => (f.properties?.countrycode || "").toUpperCase() === "CA")
          .map((f) => formatPhotonAddress(f.properties))
          .filter((s, i, arr) => s && arr.indexOf(s) === i)
          .slice(0, 5);
        setSuggestions(canadian);
        setShowSuggestions(canadian.length > 0);
      } catch {
        /* aborted or network error — ignore */
      } finally {
        setLoadingAddr(false);
      }
    }, 250);
  }

  function pickSuggestion(v: string) {
    setAddress(v);
    setSuggestions([]);
    setShowSuggestions(false);
  }

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setFormError(null);
    const fd = new FormData(e.currentTarget);
    const raw = {
      name: String(fd.get("name") || ""),
      email: String(fd.get("email") || ""),
      phone: String(fd.get("phone") || ""),
      address: String(fd.get("address") || ""),
      project_type: String(fd.get("project_type") || "autre"),
      budget_range: String(fd.get("budget_range") || ""),
      message: String(fd.get("message") || ""),
      gdpr_consent: fd.get("gdpr_consent") === "on",
      marketing_consent: fd.get("marketing_consent") === "on"
    };

    const parsed = schema.safeParse(raw);
    if (!parsed.success) {
      setFormError(parsed.error.issues[0]?.message || "Invalid input");
      return;
    }

    setState({ status: "submitting" });
    try {
      const ack = await submitContactRequest({
        name: parsed.data.name,
        email: parsed.data.email,
        phone: parsed.data.phone || undefined,
        address: parsed.data.address || undefined,
        project_type: parsed.data.project_type,
        budget_range: parsed.data.budget_range || undefined,
        message: parsed.data.message,
        locale,
        source,
        gdpr_consent: parsed.data.gdpr_consent,
        marketing_consent: parsed.data.marketing_consent
      });
      setState({ status: "success", reference: ack.reference });
    } catch (err) {
      const code = (err as Error & { code?: string }).code || "unknown";
      setState({ status: "error", code });
    }
  }

  useEffect(() => {
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
      if (abortRef.current) abortRef.current.abort();
    };
  }, []);

  if (state.status === "success") {
    return (
      <div className="card border-green-700 bg-green-900/30 text-white">
        <p className="text-base font-semibold">
          {t("success", { reference: state.reference })}
        </p>
      </div>
    );
  }

  return (
    <form onSubmit={onSubmit} className="space-y-5" noValidate>
      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <label htmlFor="name" className="label">{t("fields.name")}</label>
          <input id="name" name="name" required className="input" autoComplete="name" />
        </div>
        <div>
          <label htmlFor="email" className="label">{t("fields.email")}</label>
          <input id="email" type="email" name="email" required className="input" autoComplete="email" />
        </div>
        <div>
          <label htmlFor="phone" className="label">{t("fields.phone")}</label>
          <input id="phone" name="phone" className="input" autoComplete="tel" />
        </div>
        <div className="relative">
          <label htmlFor="address" className="label">{t("fields.address")}</label>
          <input
            id="address"
            name="address"
            value={address}
            onChange={onAddressChange}
            onFocus={() => setShowSuggestions(suggestions.length > 0)}
            onBlur={() => setTimeout(() => setShowSuggestions(false), 150)}
            className="input"
            autoComplete="street-address"
            placeholder="123 rue Example, Montreal, QC"
          />
          {loadingAddr ? (
            <Loader2 className="absolute right-3 top-[2.2rem] h-4 w-4 animate-spin text-white/50" />
          ) : null}
          {showSuggestions && suggestions.length > 0 ? (
            <ul className="absolute z-10 mt-1 w-full overflow-hidden rounded-lg border border-brand-700 bg-brand-950 shadow-card">
              {suggestions.map((s, i) => (
                <li
                  key={`${s}-${i}`}
                  onMouseDown={(e) => {
                    e.preventDefault();
                    pickSuggestion(s);
                  }}
                  className="flex cursor-pointer items-start gap-2 border-b border-brand-800 px-3 py-2 text-sm text-white last:border-0 hover:bg-brand-900"
                >
                  <MapPin className="mt-0.5 h-4 w-4 flex-shrink-0 text-accent-500" />
                  <span>{s}</span>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
        <div>
          <label htmlFor="project_type" className="label">{t("fields.projectType")}</label>
          <select id="project_type" name="project_type" className="input" defaultValue="autre">
            {projectKeys.map((k) => (
              <option key={k} value={k}>{t(`projectTypes.${k}`)}</option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor="budget_range" className="label">{t("fields.budget")}</label>
          <select id="budget_range" name="budget_range" className="input" defaultValue="">
            <option value="">—</option>
            {budgetKeys.map((k) => (
              <option key={k} value={k}>{t(`budgets.${k}`)}</option>
            ))}
          </select>
        </div>
      </div>

      <div>
        <label htmlFor="message" className="label">{t("fields.message")}</label>
        <textarea id="message" name="message" required rows={5} className="input" />
      </div>

      <div className="space-y-2">
        <label className="flex items-start gap-2 text-sm text-white">
          <input type="checkbox" name="gdpr_consent" required className="mt-1" />
          <span>{t("fields.consent")}</span>
        </label>
        <label className="flex items-start gap-2 text-sm text-white/70">
          <input type="checkbox" name="marketing_consent" className="mt-1" />
          <span>{t("fields.marketing")}</span>
        </label>
      </div>

      {formError ? <p className="text-sm text-red-400">{formError}</p> : null}
      {state.status === "error" ? (
        <p className="text-sm text-red-400">
          {state.code === "rate_limited" ? t("errorRateLimit") : t("errorGeneric")}
        </p>
      ) : null}

      <button
        type="submit"
        disabled={state.status === "submitting"}
        className="btn-accent w-full sm:w-auto"
      >
        {state.status === "submitting" ? (
          <>
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            {t("submitting")}
          </>
        ) : (
          t("submit")
        )}
      </button>
    </form>
  );
}
