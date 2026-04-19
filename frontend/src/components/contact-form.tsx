"use client";

import { useEffect, useRef, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { Loader2 } from "lucide-react";
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

// Ensures the Google Maps Places script is loaded only once per page,
// even if the ContactForm is mounted in several places (home + contact).
let _placesLoader: Promise<void> | null = null;
function loadGooglePlaces(apiKey: string): Promise<void> {
  if (typeof window === "undefined") return Promise.resolve();
  const w = window as unknown as { google?: { maps?: { places?: unknown } } };
  if (w.google?.maps?.places) return Promise.resolve();
  if (_placesLoader) return _placesLoader;
  _placesLoader = new Promise((resolve, reject) => {
    const existing = document.querySelector(
      'script[data-horizon-google-places="1"]'
    ) as HTMLScriptElement | null;
    if (existing) {
      existing.addEventListener("load", () => resolve());
      existing.addEventListener("error", () => reject(new Error("places_load_failed")));
      return;
    }
    const script = document.createElement("script");
    script.src = `https://maps.googleapis.com/maps/api/js?key=${encodeURIComponent(
      apiKey
    )}&libraries=places&loading=async`;
    script.async = true;
    script.defer = true;
    script.dataset.horizonGooglePlaces = "1";
    script.onload = () => resolve();
    script.onerror = () => reject(new Error("places_load_failed"));
    document.head.appendChild(script);
  });
  return _placesLoader;
}

export function ContactForm({ source }: { source?: string }) {
  const t = useTranslations("contact");
  const locale = useLocale();
  const [state, setState] = useState<FormState>({ status: "idle" });
  const [formError, setFormError] = useState<string | null>(null);
  const addressRef = useRef<HTMLInputElement | null>(null);

  // Google Places Autocomplete on the address field.
  useEffect(() => {
    const apiKey = process.env.NEXT_PUBLIC_GOOGLE_MAPS_API_KEY;
    if (!apiKey || !addressRef.current) return;
    let cancelled = false;
    let listener: { remove(): void } | null = null;

    loadGooglePlaces(apiKey)
      .then(() => {
        if (cancelled || !addressRef.current) return;
        const g = (window as unknown as { google: any }).google;
        const ac = new g.maps.places.Autocomplete(addressRef.current, {
          componentRestrictions: { country: "ca" },
          types: ["address"],
          fields: ["formatted_address"]
        });
        listener = ac.addListener("place_changed", () => {
          const place = ac.getPlace();
          if (place?.formatted_address && addressRef.current) {
            addressRef.current.value = place.formatted_address;
          }
        });
      })
      .catch(() => {
        /* ignore — plain text input remains usable */
      });

    return () => {
      cancelled = true;
      listener?.remove();
    };
  }, []);

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
        <div>
          <label htmlFor="address" className="label">{t("fields.address")}</label>
          <input
            id="address"
            name="address"
            ref={addressRef}
            className="input"
            autoComplete="street-address"
            placeholder="123 rue Example, Montreal, QC"
          />
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
