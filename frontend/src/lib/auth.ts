// In the browser we always hit the same origin so the Next.js rewrite
// can proxy the request to the Render backend. This eliminates CORS
// and any ISP/iOS block targeting onrender.com. On the server (SSR,
// Node runtime) we still need an absolute URL, so we fall back to the
// public base URL.
const DEFAULT_BASE =
  typeof window !== "undefined"
    ? ""
    : process.env.NEXT_PUBLIC_API_BASE_URL || "https://h2-0.onrender.com";

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
export type UserRole = "owner" | "admin" | "manager" | "employee";

export type CurrentUser = {
  id: number;
  email: string;
  is_active: boolean;
  is_admin: boolean;
  role: UserRole;
  must_change_password?: boolean;
  theme_preference?: "light" | "dark";
  /** Volets accessibles : construction, prospection, entreprises,
   *  immobilier, investisseur. Absent = backward compat (tous). */
  volets?: string[];
};

const ROLE_RANK: Record<UserRole, number> = {
  owner: 4,
  admin: 3,
  manager: 2,
  employee: 1
};

/** True if `user` has at least `min` role privilege level. */
export function hasMinRole(user: CurrentUser | null, min: UserRole): boolean {
  if (!user) return false;
  return ROLE_RANK[user.role] >= ROLE_RANK[min];
}

export async function login(
  email: string,
  password: string,
  rememberMe: boolean = false
): Promise<LoginResult> {
  const body = new URLSearchParams();
  body.set("username", email);
  body.set("password", password);
  if (rememberMe) body.set("remember_me", "true");

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
  // Do NOT force a content-type when the body is FormData — the browser must
  // set multipart/form-data with its own boundary, and a JSON override breaks
  // file uploads (backend sees `body.file` as missing).
  const isFormData =
    typeof FormData !== "undefined" && init.body instanceof FormData;
  if (init.body && !isFormData && !headers.has("content-type"))
    headers.set("content-type", "application/json");

  const url = `${DEFAULT_BASE}${path}`;
  const doFetch = () =>
    fetch(url, { ...init, headers, cache: "no-store" });

  // Render Free cold starts + spotty mobile networks occasionally
  // make the first attempt throw a bare network error ("Load failed"
  // on Safari, "Failed to fetch" on Chrome). Retry once after a short
  // pause before surfacing the error to the caller.
  try {
    return await doFetch();
  } catch (err) {
    await new Promise((r) => setTimeout(r, 1500));
    return doFetch();
  }
}
