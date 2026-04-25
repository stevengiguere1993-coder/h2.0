"use client";

import { useState } from "react";
import { Loader2, X } from "lucide-react";

import { authedFetch } from "@/lib/auth";

export type FournisseurMini = {
  id: number;
  name: string;
  email: string | null;
  phone: string | null;
  category: string | null;
};

export function FournisseurModal({
  open,
  onClose,
  onCreated,
  initialName
}: {
  open: boolean;
  onClose: () => void;
  onCreated: (f: FournisseurMini) => void;
  initialName?: string;
}) {
  const [name, setName] = useState(initialName || "");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [category, setCategory] = useState("");
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  if (!open) return null;

  async function save(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) {
      setErr("Le nom est requis.");
      return;
    }
    setSaving(true);
    setErr(null);
    try {
      const res = await authedFetch("/api/v1/fournisseurs", {
        method: "POST",
        body: JSON.stringify({
          name: name.trim(),
          email: email.trim() || null,
          phone: phone.trim() || null,
          category: category.trim() || null,
          active: true
        })
      });
      if (!res.ok) {
        const t = await res.text();
        throw new Error(t.slice(0, 240) || `http_${res.status}`);
      }
      const created = (await res.json()) as FournisseurMini;
      onCreated(created);
      // Reset for next time
      setName("");
      setEmail("");
      setPhone("");
      setCategory("");
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm">
      <form
        onSubmit={save}
        className="relative w-full max-w-md rounded-2xl border border-brand-800 bg-brand-950 p-5 shadow-2xl"
      >
        <button
          type="button"
          onClick={onClose}
          className="absolute right-3 top-3 rounded-md p-1 text-white/50 hover:bg-brand-800 hover:text-white"
          aria-label="Fermer"
        >
          <X className="h-4 w-4" />
        </button>
        <h2 className="text-base font-bold text-white">
          Nouveau fournisseur
        </h2>
        <p className="mt-1 text-xs text-white/50">
          Création rapide — tu pourras ajouter les détails plus tard
          dans la fiche fournisseur.
        </p>

        {err ? (
          <p className="mt-3 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
            {err}
          </p>
        ) : null}

        <div className="mt-4 space-y-3">
          <div>
            <label htmlFor="f_name" className="label">
              Nom *
            </label>
            <input
              id="f_name"
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              autoFocus
              className="input"
              placeholder="Ex. Rona Saint-Jérôme"
            />
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <label htmlFor="f_email" className="label">
                Courriel
              </label>
              <input
                id="f_email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="input"
              />
            </div>
            <div>
              <label htmlFor="f_phone" className="label">
                Téléphone
              </label>
              <input
                id="f_phone"
                type="tel"
                value={phone}
                onChange={(e) => setPhone(e.target.value)}
                className="input"
              />
            </div>
          </div>
          <div>
            <label htmlFor="f_category" className="label">
              Catégorie
            </label>
            <input
              id="f_category"
              type="text"
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              placeholder="Ex. Plomberie, Bois, Électricité…"
              className="input"
            />
          </div>
        </div>

        <div className="mt-5 flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            disabled={saving}
            className="btn-secondary text-xs"
          >
            Annuler
          </button>
          <button
            type="submit"
            disabled={saving}
            className="btn-accent text-sm"
          >
            {saving ? (
              <Loader2 className="mr-1 h-4 w-4 animate-spin" />
            ) : null}
            Créer
          </button>
        </div>
      </form>
    </div>
  );
}
