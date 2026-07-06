// Browser calls go through the Next.js rewrite on the same origin; on
// the server we need an absolute URL.
const DEFAULT_BASE =
  typeof window !== "undefined"
    ? ""
    : process.env.NEXT_PUBLIC_API_BASE_URL || "https://h2-0.onrender.com";

export type ContactPayload = {
  name: string;
  email: string;
  phone?: string;
  address?: string;
  project_type: string;
  budget_range?: string;
  message: string;
  locale: string;
  source?: string;
  gdpr_consent: boolean;
  marketing_consent: boolean;
  // Honeypot anti-bot : toujours vide pour un humain (champ invisible).
  website?: string;
};

export type ContactAck = { ok: boolean; reference: string };

export async function submitContactRequest(
  payload: ContactPayload,
  photos?: File[]
): Promise<ContactAck> {
  // Backend expects multipart/form-data (Form + File fields).
  const fd = new FormData();
  fd.append("name", payload.name);
  fd.append("email", payload.email);
  fd.append("message", payload.message);
  fd.append("gdpr_consent", payload.gdpr_consent ? "true" : "false");
  fd.append("marketing_consent", payload.marketing_consent ? "true" : "false");
  fd.append("project_type", payload.project_type || "autre");
  fd.append("locale", payload.locale || "fr");
  if (payload.phone) fd.append("phone", payload.phone);
  if (payload.address) fd.append("address", payload.address);
  if (payload.budget_range) fd.append("budget_range", payload.budget_range);
  if (payload.source) fd.append("source", payload.source);
  if (payload.website) fd.append("website", payload.website);
  if (photos && photos.length > 0) {
    for (const file of photos) fd.append("photos", file, file.name);
  }

  const res = await fetch(`${DEFAULT_BASE}/api/v1/contact`, {
    method: "POST",
    // Do NOT set Content-Type manually — the browser adds the correct
    // multipart boundary automatically when body is a FormData.
    body: fd,
    cache: "no-store"
  });

  if (res.status === 429) {
    const err = new Error("rate_limited");
    (err as Error & { code?: string }).code = "rate_limited";
    throw err;
  }

  if (!res.ok) {
    const err = new Error(`http_${res.status}`);
    (err as Error & { code?: string }).code = `http_${res.status}`;
    throw err;
  }

  return (await res.json()) as ContactAck;
}
