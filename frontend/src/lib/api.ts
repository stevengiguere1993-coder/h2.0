const DEFAULT_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL || "https://h2-0.onrender.com";

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
};

export type ContactAck = { ok: boolean; reference: string };

export async function submitContactRequest(
  payload: ContactPayload
): Promise<ContactAck> {
  const res = await fetch(`${DEFAULT_BASE}/api/v1/contact`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
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
