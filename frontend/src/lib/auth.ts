const DEFAULT_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL || "https://h2-0.onrender.com";

const TOKEN_KEY = "hsi_access_token";

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string | null) {
  if (typeof window === "undefined") return;
  try {
    if (token) window.localStorage.setItem(TOKEN_KEY, token);
    else window.localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* ignore */
  }
}

export type LoginResult = { access_token: string; token_type: string };
export type CurrentUser = {
  id: number;
  email: string;
  is_active: boolean;
  is_admin: boolean;
};

export async function login(email: string, password: string): Promise<LoginResult> {
  const body = new URLSearchParams();
  body.set("username", email);
  body.set("password", password);

  const res = await fetch(`${DEFAULT_BASE}/api/v1/auth/login`, {
    method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded" },
    body,
    cache: "no-store"
  });

  if (res.status === 401) {
    const err = new Error("invalid_credentials");
    (err as Error & { code?: string }).code = "invalid_credentials";
    throw err;
  }
  if (!res.ok) {
    const err = new Error(`http_${res.status}`);
    (err as Error & { code?: string }).code = `http_${res.status}`;
    throw err;
  }
  return (await res.json()) as LoginResult;
}

export async function getMe(token: string): Promise<CurrentUser> {
  const res = await fetch(`${DEFAULT_BASE}/api/v1/auth/me`, {
    headers: { authorization: `Bearer ${token}` },
    cache: "no-store"
  });
  if (!res.ok) throw new Error(`http_${res.status}`);
  return (await res.json()) as CurrentUser;
}

export async function authedFetch(
  path: string,
  init: RequestInit = {}
): Promise<Response> {
  const token = getToken();
  const headers = new Headers(init.headers);
  if (token) headers.set("authorization", `Bearer ${token}`);
  if (init.body && !headers.has("content-type"))
    headers.set("content-type", "application/json");
  return fetch(`${DEFAULT_BASE}${path}`, {
    ...init,
    headers,
    cache: "no-store"
  });
}
