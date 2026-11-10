"use client";

/**
 * Admin locative → onglet « Contacts » (Phil 2026-11-10).
 *
 * « Crée une genre de mini base de données des contacts dans cette section
 * uniquement. Donc une fois une personne créée, je peux venir la sélectionner
 * la fois d'après. »
 *
 * Le carnet de cette section SEULEMENT : locateurs, locataires et cautions de
 * baux hors système. Aucun lien avec les fiches locataires de Kratos. Une
 * personne nommée dans un bail indépendant ou un avis y entre d'elle-même ;
 * on peut aussi l'ajouter ici. Retirer un contact ne le supprime pas : il
 * sort des listes de sélection et se remet d'un clic.
 */

import { useMemo, useState } from "react";
import { BookUser, Loader2, Pencil, Plus, RotateCcw, Search, Trash2 } from "lucide-react";

import { authedFetch } from "@/lib/auth";
import { BASE_ADMIN as BASE, Champ, type Contact, Fenetre, ROLES, libelleRole, lireErreur, sansAccents } from "./commun";

type F = { nom: string; role: string; telephone: string; courriel: string; adresse: string; notes: string };

const F_VIDE: F = { nom: "", role: "", telephone: "", courriel: "", adresse: "", notes: "" };

const ROLE_BADGE: Record<string, string> = { locateur: "badge-violet", locataire: "badge-sky", caution: "badge-amber" };

export function ContactsTab({
  contacts,
  charge,
  onCarnetChange
}: {
  contacts: Contact[];
  charge: boolean;
  onCarnetChange: () => Promise<void> | void;
}) {
  const [q, setQ] = useState("");
  const [role, setRole] = useState("");
  const [retires, setRetires] = useState(false);
  const [edition, setEdition] = useState<{ contact: Contact | null } | null>(null);
  const [busy, setBusy] = useState<number | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const nbRetires = useMemo(() => contacts.filter((c) => !c.actif).length, [contacts]);
  const visibles = useMemo(() => {
    const terme = sansAccents(q.trim());
    return contacts
      .filter((c) => (retires ? true : c.actif))
      .filter((c) => (role ? c.role === role : true))
      .filter((c) => (terme ? [c.nom, c.courriel, c.telephone, c.adresse].some((x) => sansAccents(x || "").includes(terme)) : true))
      .sort((a, b) => Number(b.actif) - Number(a.actif) || sansAccents(a.nom).localeCompare(sansAccents(b.nom)));
  }, [contacts, q, role, retires]);

  async function basculer(c: Contact) {
    setBusy(c.id);
    setErr(null);
    try {
      const r = c.actif
        ? await authedFetch(`${BASE}/contacts/${c.id}`, { method: "DELETE" })
        : await authedFetch(`${BASE}/contacts/${c.id}`, { method: "PATCH", body: JSON.stringify({ actif: true }) });
      if (!r.ok) throw new Error(await lireErreur(r));
      await onCarnetChange();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  return (
    <>
      {edition ? (
        <ContactForm
          contact={edition.contact}
          onClose={() => setEdition(null)}
          onSaved={() => {
            setEdition(null);
            void onCarnetChange();
          }}
        />
      ) : null}

      <div>
        <div className="flex flex-wrap items-start gap-3">
          <div className="min-w-0 flex-1">
            <p className="max-w-3xl text-sm text-white/60">
              Le carnet de cette section seulement : les locateurs, locataires et cautions des baux hors système. Une personne nommée
              dans un bail ou un avis y entre d&apos;elle-même, et se choisit ensuite d&apos;un clic dans les formulaires. Rien ici ne
              touche aux locataires de Kratos.
            </p>
          </div>
          <button type="button" onClick={() => setEdition({ contact: null })} className="btn-accent btn-sm">
            <Plus className="h-4 w-4" /> Nouveau contact
          </button>
        </div>

        {err ? <p className="mt-4 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-200">{err}</p> : null}

        <section className="mt-4 rounded-xl border border-brand-800 bg-brand-900">
          <div className="flex flex-wrap items-center gap-3 border-b border-brand-800 px-4 py-3">
            <h2 className="text-xs font-semibold uppercase tracking-wider text-accent-500">Contacts ({visibles.length})</h2>
            <div className="relative ml-auto w-full sm:w-64">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-white/40" />
              <input className="input pl-8" value={q} onChange={(ev) => setQ(ev.target.value)} placeholder="Nom, courriel, téléphone…" />
            </div>
            <select className="input w-full sm:w-40" value={role} onChange={(ev) => setRole(ev.target.value)} aria-label="Filtrer par rôle">
              <option value="">Tous les rôles</option>
              {ROLES.map((r) => (
                <option key={r.value} value={r.value}>
                  {r.pluriel}
                </option>
              ))}
            </select>
            {nbRetires > 0 ? (
              <label className="inline-flex items-center gap-1.5 text-xs text-white/60">
                <input type="checkbox" checked={retires} onChange={(ev) => setRetires(ev.target.checked)} />
                Afficher les retirés ({nbRetires})
              </label>
            ) : null}
          </div>

          {charge ? (
            <div className="flex items-center gap-2 px-4 py-10 text-sm text-white/50">
              <Loader2 className="h-4 w-4 animate-spin" /> Chargement…
            </div>
          ) : visibles.length === 0 ? (
            <div className="px-4 py-10 text-center">
              <p className="text-sm text-white/60">
                {contacts.length === 0 ? "Le carnet est vide. Il se remplit dès le premier bail ou le premier avis." : "Aucun contact ne correspond."}
              </p>
            </div>
          ) : (
            <ul className="divide-y divide-brand-800">
              {visibles.map((c) => (
                <li key={c.id} className={`flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3 ${c.actif ? "" : "opacity-60"}`}>
                  <div className="min-w-[220px] flex-1">
                    <p className="truncate text-sm font-semibold text-white">{c.nom}</p>
                    <p className="mt-0.5 truncate text-xs text-white/55">
                      {[c.courriel, c.telephone, c.adresse].filter(Boolean).join(" · ") || "Aucune coordonnée"}
                    </p>
                    {c.notes ? <p className="mt-0.5 truncate text-xs text-white/45">{c.notes}</p> : null}
                  </div>
                  {c.role ? <span className={`badge ${ROLE_BADGE[c.role] || "badge-neutral"}`}>{libelleRole(c.role)}</span> : null}
                  {!c.actif ? <span className="badge badge-neutral">Retiré</span> : null}
                  <div className="flex items-center gap-1">
                    <button type="button" className="btn-ghost btn-xs" onClick={() => setEdition({ contact: c })}>
                      <Pencil className="h-3.5 w-3.5" /> Modifier
                    </button>
                    {c.actif ? (
                      <button
                        type="button"
                        className="btn-ghost btn-xs text-rose-300"
                        title="Retirer du carnet (sans le supprimer)"
                        disabled={busy === c.id}
                        onClick={() => void basculer(c)}
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    ) : (
                      <button type="button" className="btn-ghost btn-xs" disabled={busy === c.id} onClick={() => void basculer(c)}>
                        <RotateCcw className="h-3.5 w-3.5" /> Remettre
                      </button>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </>
  );
}

function ContactForm({ contact, onClose, onSaved }: { contact: Contact | null; onClose: () => void; onSaved: () => void }) {
  const [f, setF] = useState<F>(() =>
    contact
      ? {
          nom: contact.nom,
          role: contact.role || "",
          telephone: contact.telephone || "",
          courriel: contact.courriel || "",
          adresse: contact.adresse || "",
          notes: contact.notes || ""
        }
      : F_VIDE
  );
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const poser = (k: keyof F, v: string) => setF((x) => ({ ...x, [k]: v }));

  async function enregistrer() {
    if (!f.nom.trim()) {
      setErr("Le nom est requis.");
      return;
    }
    setBusy(true);
    setErr(null);
    try {
      const corps = {
        nom: f.nom.trim(),
        role: f.role || null,
        telephone: f.telephone.trim() || null,
        courriel: f.courriel.trim() || null,
        adresse: f.adresse.trim() || null,
        notes: f.notes.trim() || null
      };
      const r = await authedFetch(contact ? `${BASE}/contacts/${contact.id}` : `${BASE}/contacts`, {
        method: contact ? "PATCH" : "POST",
        body: JSON.stringify(corps)
      });
      if (!r.ok) throw new Error(await lireErreur(r));
      onSaved();
    } catch (x) {
      setErr((x as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Fenetre
      titre={contact ? "Modifier le contact" : "Nouveau contact"}
      sousTitre="Carnet de l'Admin locative"
      icone={<BookUser className="h-4 w-4" />}
      onClose={onClose}
      pied={
        <>
          <button type="button" onClick={onClose} className="btn-secondary btn-sm ml-auto" disabled={busy}>
            Fermer
          </button>
          <button type="button" onClick={() => void enregistrer()} className="btn-accent btn-sm disabled:opacity-60" disabled={busy}>
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : null} Enregistrer
          </button>
        </>
      }
    >
      <div className="grid gap-2 sm:grid-cols-2">
        <Champ label="Nom (personne ou compagnie)" className="sm:col-span-2">
          <input className="input" value={f.nom} onChange={(ev) => poser("nom", ev.target.value)} maxLength={255} autoFocus />
        </Champ>
        <Champ label="Rôle habituel">
          <select className="input" value={f.role} onChange={(ev) => poser("role", ev.target.value)}>
            <option value="">Non précisé</option>
            {ROLES.map((r) => (
              <option key={r.value} value={r.value}>
                {r.label}
              </option>
            ))}
          </select>
        </Champ>
        <Champ label="Téléphone">
          <input className="input" value={f.telephone} onChange={(ev) => poser("telephone", ev.target.value)} placeholder="514-555-0100" maxLength={40} />
        </Champ>
        <Champ label="Courriel" className="sm:col-span-2">
          <input className="input" type="email" value={f.courriel} onChange={(ev) => poser("courriel", ev.target.value)} maxLength={320} />
        </Champ>
        <Champ label="Adresse" className="sm:col-span-2">
          <input className="input" value={f.adresse} onChange={(ev) => poser("adresse", ev.target.value)} maxLength={500} />
        </Champ>
        <Champ label="Notes (facultatif)" className="sm:col-span-2">
          <textarea className="input min-h-[64px]" value={f.notes} onChange={(ev) => poser("notes", ev.target.value)} maxLength={4000} />
        </Champ>
      </div>
      {err ? <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">{err}</p> : null}
    </Fenetre>
  );
}
