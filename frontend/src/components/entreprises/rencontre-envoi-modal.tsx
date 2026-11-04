"use client";

import { useEffect, useMemo, useState } from "react";
import { Loader2, Mail, Search, Send, X } from "lucide-react";

import { authedFetch } from "@/lib/auth";

/**
 * Fenêtre « Envoyer rapport » d'une rencontre : choix des contacts
 * (rolodex unifié /contacts/all) + adresses libres, sujet et mot
 * d'accompagnement. Le courriel part de la boîte Microsoft 365 de
 * l'utilisateur connecté (jamais d'info@) — c'est le backend qui le
 * décide, la fenêtre ne fait que l'afficher.
 */

type UnifiedContact = {
  id: string;
  full_name: string;
  company: string | null;
  email: string | null;
  kind: string;
};

const COURRIEL = /^[^@\s<>,;]+@[^@\s<>,;]+\.[^@\s<>,;]+$/;

function decouper(brut: string): string[] {
  return brut
    .split(/[\s,;]+/)
    .map((s) => s.trim())
    .filter(Boolean);
}

export function RencontreEnvoiModal({
  rencontreId,
  sujetParDefaut,
  expediteur,
  onClose,
  onSent
}: {
  rencontreId: number;
  sujetParDefaut: string;
  expediteur: string | null;
  onClose: () => void;
  onSent: (resultat: { a: string[]; cc: string[]; envois_json: string | null }) => void;
}) {
  const [contacts, setContacts] = useState<UnifiedContact[]>([]);
  const [chargement, setChargement] = useState(true);
  const [recherche, setRecherche] = useState("");
  const [choisis, setChoisis] = useState<string[]>([]);
  const [autres, setAutres] = useState("");
  const [cc, setCc] = useState("");
  const [sujet, setSujet] = useState(sujetParDefaut);
  const [message, setMessage] = useState("");
  const [envoi, setEnvoi] = useState(false);
  const [erreur, setErreur] = useState<string | null>(null);

  useEffect(() => {
    let annule = false;
    (async () => {
      try {
        const r = await authedFetch("/api/v1/contacts/all");
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const liste = ((await r.json()) as UnifiedContact[])
          .filter((c) => c.email && COURRIEL.test(c.email.trim()))
          .sort((a, b) => a.full_name.localeCompare(b.full_name, "fr"));
        if (!annule) setContacts(liste);
      } catch (e) {
        if (!annule) setErreur(`Contacts introuvables : ${(e as Error).message}`);
      } finally {
        if (!annule) setChargement(false);
      }
    })();
    return () => {
      annule = true;
    };
  }, []);

  const filtres = useMemo(() => {
    const q = recherche.trim().toLowerCase();
    if (!q) return contacts;
    return contacts.filter((c) =>
      [c.full_name, c.company, c.email]
        .filter(Boolean)
        .some((v) => (v as string).toLowerCase().includes(q))
    );
  }, [contacts, recherche]);

  const choisisSet = new Set(choisis.map((e) => e.toLowerCase()));
  const autresListe = decouper(autres);
  const ccListe = decouper(cc);
  const invalides = [...autresListe, ...ccListe].filter((a) => !COURRIEL.test(a));
  const destinataires = Array.from(
    new Map([...choisis, ...autresListe].map((a) => [a.toLowerCase(), a])).values()
  );

  function basculer(email: string) {
    const cle = email.toLowerCase();
    setChoisis((prev) =>
      prev.some((e) => e.toLowerCase() === cle)
        ? prev.filter((e) => e.toLowerCase() !== cle)
        : [...prev, email]
    );
  }

  async function envoyer() {
    if (destinataires.length === 0 || invalides.length > 0) return;
    setEnvoi(true);
    setErreur(null);
    try {
      const r = await authedFetch(`/api/v1/rencontres/${rencontreId}/envoyer`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          to: destinataires,
          cc: ccListe,
          sujet: sujet.trim() || null,
          message: message.trim() || null
        })
      });
      if (!r.ok) {
        let detail = `HTTP ${r.status}`;
        try {
          const j = await r.json();
          if (typeof j?.detail === "string") detail = j.detail;
        } catch {
          /* corps non JSON */
        }
        throw new Error(detail);
      }
      const j = await r.json();
      onSent({ a: j.a, cc: j.cc, envois_json: j.envois_json ?? null });
    } catch (e) {
      setErreur((e as Error).message);
    } finally {
      setEnvoi(false);
    }
  }

  const champ = {
    borderColor: "var(--qg-border)",
    color: "var(--qg-text)"
  } as const;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      onClick={onClose}
    >
      <div
        className="flex max-h-[90vh] w-full max-w-lg flex-col rounded-2xl border p-5 shadow-2xl"
        style={{ borderColor: "var(--qg-border)", backgroundColor: "var(--qg-bg)" }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-3">
          <div>
            <h2 className="text-lg font-bold" style={{ color: "var(--qg-text)" }}>
              Envoyer le rapport
            </h2>
            <p className="mt-0.5 text-xs" style={{ color: "var(--qg-text-muted)" }}>
              Part de ta boîte courriel
              {expediteur ? (
                <>
                  {" "}
                  <b style={{ color: "var(--qg-text)" }}>{expediteur}</b>
                </>
              ) : null}
              . Les réponses te reviennent.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded p-1"
            style={{ color: "var(--qg-text-muted)" }}
            title="Fermer"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="mt-4 flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto">
          <div>
            <label className="label">Contacts</label>
            <div className="relative">
              <Search
                className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2"
                style={{ color: "var(--qg-text-muted)" }}
              />
              <input
                className="input pl-7"
                placeholder="Chercher un nom, une entreprise, un courriel…"
                value={recherche}
                onChange={(e) => setRecherche(e.target.value)}
              />
            </div>
            <div
              className="mt-2 max-h-56 overflow-y-auto rounded-lg border"
              style={{ borderColor: "var(--qg-border-soft)" }}
            >
              {chargement ? (
                <div className="flex items-center justify-center py-6">
                  <Loader2 className="h-4 w-4 animate-spin text-accent-500" />
                </div>
              ) : filtres.length === 0 ? (
                <p className="px-3 py-3 text-xs" style={{ color: "var(--qg-text-muted)" }}>
                  Aucun contact avec courriel ne correspond.
                </p>
              ) : (
                filtres.map((c) => {
                  const email = (c.email as string).trim();
                  const coche = choisisSet.has(email.toLowerCase());
                  return (
                    <label
                      key={c.id}
                      className="flex cursor-pointer items-center gap-2 border-b px-3 py-1.5 text-sm last:border-b-0"
                      style={{ borderColor: "var(--qg-border-soft)", color: "var(--qg-text)" }}
                    >
                      <input
                        type="checkbox"
                        checked={coche}
                        onChange={() => basculer(email)}
                      />
                      <span className="min-w-0 flex-1 truncate">
                        {c.full_name}
                        {c.company ? (
                          <span style={{ color: "var(--qg-text-muted)" }}> · {c.company}</span>
                        ) : null}
                      </span>
                      <span className="truncate text-xs" style={{ color: "var(--qg-text-muted)" }}>
                        {email}
                      </span>
                    </label>
                  );
                })
              )}
            </div>
          </div>

          <div>
            <label className="label">Autres adresses (facultatif)</label>
            <input
              className="input"
              placeholder="nom@exemple.com, autre@exemple.com"
              value={autres}
              onChange={(e) => setAutres(e.target.value)}
            />
          </div>
          <div>
            <label className="label">Copie conforme (facultatif)</label>
            <input
              className="input"
              placeholder="cc@exemple.com"
              value={cc}
              onChange={(e) => setCc(e.target.value)}
            />
          </div>
          <div>
            <label className="label">Sujet</label>
            <input
              className="input"
              value={sujet}
              onChange={(e) => setSujet(e.target.value)}
              maxLength={255}
            />
          </div>
          <div>
            <label className="label">Mot d&apos;accompagnement (facultatif)</label>
            <textarea
              className="input min-h-[70px]"
              placeholder="Bonjour, voici le résumé de notre rencontre…"
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              maxLength={5000}
            />
          </div>

          {destinataires.length > 0 ? (
            <p className="text-xs" style={{ color: "var(--qg-text-soft)" }}>
              <Mail className="mr-1 inline h-3.5 w-3.5" />
              À : {destinataires.join(", ")}
              {ccListe.length ? ` · Cc : ${ccListe.join(", ")}` : ""}
            </p>
          ) : null}
          {invalides.length > 0 ? (
            <p className="rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
              Adresse invalide : {invalides.join(", ")}
            </p>
          ) : null}
          {erreur ? (
            <p className="rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
              {erreur}
            </p>
          ) : null}
        </div>

        <div className="mt-4 flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border px-4 py-2 text-sm"
            style={champ}
          >
            Annuler
          </button>
          <button
            type="button"
            onClick={() => void envoyer()}
            disabled={envoi || destinataires.length === 0 || invalides.length > 0}
            className="btn-accent inline-flex items-center gap-1.5 text-sm disabled:opacity-50"
          >
            {envoi ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
            Envoyer
            {destinataires.length > 0 ? ` (${destinataires.length})` : ""}
          </button>
        </div>
      </div>
    </div>
  );
}
