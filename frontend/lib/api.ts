/**
 * Minimal typed client for the FastAPI backend.
 * Only public endpoints are exposed here; authenticated endpoints
 * will be called from server components with a bearer token.
 */

import { getApiBaseUrl } from './utils';

export type ProjectType =
  | 'salle_bain'
  | 'cuisine'
  | 'multilogement'
  | 'renovation_complete'
  | 'autre';

export interface ContactRequestPayload {
  name: string;
  email: string;
  phone?: string;
  address?: string;
  project_type: ProjectType;
  budget_range?: string;
  message: string;
  locale: 'fr' | 'en';
  source?: string;
  gdpr_consent: boolean;
  marketing_consent?: boolean;
}

export interface ContactRequestAck {
  ok: boolean;
  reference: string;
}

export class ApiError extends Error {
  readonly status: number;
  readonly body: unknown;
  constructor(message: string, status: number, body: unknown) {
    super(message);
    this.status = status;
    this.body = body;
  }
}

export async function submitContactRequest(
  payload: ContactRequestPayload,
  init?: { signal?: AbortSignal }
): Promise<ContactRequestAck> {
  const res = await fetch(`${getApiBaseUrl()}/api/v1/contact`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
    cache: 'no-store',
    signal: init?.signal,
  });

  if (!res.ok) {
    let body: unknown = null;
    try {
      body = await res.json();
    } catch {
      body = await res.text();
    }
    throw new ApiError(`Contact request failed (${res.status})`, res.status, body);
  }

  return (await res.json()) as ContactRequestAck;
}
