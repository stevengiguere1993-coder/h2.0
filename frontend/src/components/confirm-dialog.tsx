"use client";

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode
} from "react";
import { AlertTriangle, Loader2 } from "lucide-react";

/**
 * Global confirmation dialog — replaces window.confirm() which is
 * silently blocked in PWA standalone mode on iOS and several Android
 * browsers (the user sees nothing happen when they tap "Supprimer").
 *
 * Usage:
 *   const confirm = useConfirm();
 *   if (!(await confirm({ title: "Supprimer cette phase ?" }))) return;
 */

type Options = {
  title: string;
  description?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  destructive?: boolean;
};

type Ctx = (opts: Options | string) => Promise<boolean>;

const ConfirmContext = createContext<Ctx | null>(null);

export function ConfirmProvider({ children }: { children: ReactNode }) {
  const [opts, setOpts] = useState<Options | null>(null);
  const [resolver, setResolver] = useState<((v: boolean) => void) | null>(null);
  const [busy, setBusy] = useState(false);

  const ask = useCallback<Ctx>((input) => {
    const normalized: Options =
      typeof input === "string" ? { title: input } : input;
    return new Promise<boolean>((resolve) => {
      setOpts(normalized);
      setResolver(() => resolve);
    });
  }, []);

  function close(result: boolean) {
    if (resolver) resolver(result);
    setResolver(null);
    setOpts(null);
    setBusy(false);
  }

  const ctx = useMemo(() => ask, [ask]);

  return (
    <ConfirmContext.Provider value={ctx}>
      {children}
      {opts ? (
        <div
          className="fixed inset-0 z-[1000] flex items-center justify-center bg-black/70 p-4"
          onClick={() => !busy && close(false)}
        >
          <div
            className="w-full max-w-sm rounded-2xl border border-brand-800 bg-brand-950 p-5 text-white shadow-xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-start gap-3">
              <div
                className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-full ${
                  opts.destructive !== false
                    ? "bg-rose-500/15 text-rose-300"
                    : "bg-accent-500/15 text-accent-300"
                }`}
              >
                <AlertTriangle className="h-5 w-5" />
              </div>
              <div className="min-w-0 flex-1">
                <p className="text-base font-bold">{opts.title}</p>
                {opts.description ? (
                  <p className="mt-1 text-sm text-white/60">
                    {opts.description}
                  </p>
                ) : null}
              </div>
            </div>
            <div className="mt-5 flex items-center justify-end gap-2">
              <button
                type="button"
                onClick={() => close(false)}
                disabled={busy}
                className="btn-secondary text-sm"
              >
                {opts.cancelLabel || "Annuler"}
              </button>
              <button
                type="button"
                onClick={() => {
                  setBusy(true);
                  close(true);
                }}
                disabled={busy}
                className={`text-sm ${
                  opts.destructive !== false
                    ? "inline-flex items-center rounded-lg bg-rose-500 px-3 py-2 font-semibold text-white hover:bg-rose-600 disabled:opacity-60"
                    : "btn-accent"
                }`}
              >
                {busy ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                ) : null}
                {opts.confirmLabel ||
                  (opts.destructive !== false ? "Supprimer" : "Confirmer")}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </ConfirmContext.Provider>
  );
}

export function useConfirm(): Ctx {
  const ctx = useContext(ConfirmContext);
  if (!ctx) {
    // Fallback to window.confirm in places not wrapped by the provider
    // (e.g. public pages). This keeps the API safe even outside /app.
    return async (input: Options | string) => {
      const msg = typeof input === "string" ? input : input.title;
      return typeof window !== "undefined" ? window.confirm(msg) : false;
    };
  }
  return ctx;
}
