"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "@/i18n/navigation";
import {
  Camera,
  KeyRound,
  Loader2,
  Save,
  Trash2,
  UserCircle
} from "lucide-react";

import { authedFetch, getToken, setToken } from "@/lib/auth";
import { useCurrentUser } from "@/hooks/use-current-user";

/**
 * Page « Mon profil » accessible depuis la sidebar de tous les
 * volets. Permet à l'utilisateur de :
 *   - mettre à jour son prénom + nom,
 *   - uploader / changer / retirer sa photo de profil,
 *   - changer son mot de passe (formulaire intégré).
 */
export default function ProfilePage() {
  const router = useRouter();
  const { user, loading, signOut } = useCurrentUser();
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [savingProfile, setSavingProfile] = useState(false);
  const [profileMsg, setProfileMsg] = useState<string | null>(null);
  const [profileErr, setProfileErr] = useState<string | null>(null);

  // Avatar : object URL généré au fetch via authedFetch (l'endpoint
  // exige le Bearer token donc on ne peut pas faire <img src=URL>).
  const [avatarUrl, setAvatarUrl] = useState<string | null>(null);
  const [avatarBusy, setAvatarBusy] = useState(false);
  const fileRef = useRef<HTMLInputElement | null>(null);

  // Mot de passe — bloc intégré (déprécie /changer-mot-de-passe).
  const [currentPwd, setCurrentPwd] = useState("");
  const [newPwd, setNewPwd] = useState("");
  const [confirmPwd, setConfirmPwd] = useState("");
  const [pwdBusy, setPwdBusy] = useState(false);
  const [pwdMsg, setPwdMsg] = useState<string | null>(null);
  const [pwdErr, setPwdErr] = useState<string | null>(null);

  useEffect(() => {
    if (user) {
      setFirstName(user.first_name || "");
      setLastName(user.last_name || "");
    }
  }, [user]);

  // Charge l'avatar courant.
  useEffect(() => {
    let revoke: string | null = null;
    (async () => {
      if (!user?.has_avatar) {
        setAvatarUrl(null);
        return;
      }
      const r = await authedFetch("/api/v1/auth/me/avatar");
      if (!r.ok) return;
      const blob = await r.blob();
      const url = URL.createObjectURL(blob);
      revoke = url;
      setAvatarUrl(url);
    })();
    return () => {
      if (revoke) URL.revokeObjectURL(revoke);
    };
  }, [user?.id, user?.has_avatar]);

  if (loading || !user) {
    return (
      <div className="flex min-h-[40vh] items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-accent-500" />
      </div>
    );
  }

  async function saveProfile(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setSavingProfile(true);
    setProfileMsg(null);
    setProfileErr(null);
    try {
      const res = await authedFetch("/api/v1/auth/me/profile", {
        method: "PATCH",
        body: JSON.stringify({
          first_name: firstName,
          last_name: lastName
        })
      });
      if (!res.ok) {
        const txt = await res.text().catch(() => "");
        throw new Error(`HTTP ${res.status} ${txt.slice(0, 120)}`);
      }
      setProfileMsg("Profil mis à jour.");
      // Force un reload du hook pour rafraîchir la sidebar partout.
      router.refresh();
    } catch (e) {
      setProfileErr((e as Error).message || "Échec");
    } finally {
      setSavingProfile(false);
    }
  }

  async function uploadAvatar(file: File) {
    setAvatarBusy(true);
    setProfileErr(null);
    setProfileMsg(null);
    try {
      const fd = new FormData();
      fd.append("file", file, file.name);
      const res = await authedFetch("/api/v1/auth/me/avatar", {
        method: "POST",
        body: fd
      });
      if (!res.ok) {
        const txt = await res.text().catch(() => "");
        throw new Error(`HTTP ${res.status} ${txt.slice(0, 120)}`);
      }
      // Re-fetch immédiat pour mettre à jour le rendu (le booléen
      // has_avatar du user passera à true au prochain refresh).
      const r = await authedFetch("/api/v1/auth/me/avatar");
      if (r.ok) {
        const blob = await r.blob();
        if (avatarUrl) URL.revokeObjectURL(avatarUrl);
        setAvatarUrl(URL.createObjectURL(blob));
      }
      setProfileMsg("Photo mise à jour.");
      router.refresh();
    } catch (e) {
      setProfileErr((e as Error).message || "Upload échoué.");
    } finally {
      setAvatarBusy(false);
    }
  }

  async function deleteAvatar() {
    setAvatarBusy(true);
    try {
      const res = await authedFetch("/api/v1/auth/me/avatar", {
        method: "DELETE"
      });
      if (!res.ok) throw new Error();
      if (avatarUrl) URL.revokeObjectURL(avatarUrl);
      setAvatarUrl(null);
      setProfileMsg("Photo retirée.");
      router.refresh();
    } catch {
      setProfileErr("Suppression échouée.");
    } finally {
      setAvatarBusy(false);
    }
  }

  async function changePassword(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setPwdMsg(null);
    setPwdErr(null);
    if (newPwd.length < 8) {
      setPwdErr("Le nouveau mot de passe doit faire au moins 8 caractères.");
      return;
    }
    if (newPwd !== confirmPwd) {
      setPwdErr("Les deux mots de passe ne correspondent pas.");
      return;
    }
    setPwdBusy(true);
    try {
      const res = await authedFetch("/api/v1/auth/change-password", {
        method: "POST",
        body: JSON.stringify({
          current_password: currentPwd,
          new_password: newPwd
        })
      });
      if (!res.ok) {
        const j = await res.json().catch(() => ({}));
        throw new Error(j?.detail || `HTTP ${res.status}`);
      }
      setPwdMsg("Mot de passe changé.");
      setCurrentPwd("");
      setNewPwd("");
      setConfirmPwd("");
    } catch (e) {
      setPwdErr((e as Error).message || "Échec");
    } finally {
      setPwdBusy(false);
    }
  }

  // Initiales pour fallback de l'avatar (Prénom + Nom ou email).
  const initials = (() => {
    const fn = (user.first_name || "").trim();
    const ln = (user.last_name || "").trim();
    if (fn || ln) {
      return `${fn[0] || ""}${ln[0] || ""}`.toUpperCase() || "?";
    }
    return (user.email || "?")[0].toUpperCase();
  })();

  return (
    <div className="mx-auto max-w-2xl space-y-6 p-4 lg:p-6">
      <header>
        <h1 className="text-2xl font-bold text-white">Mon profil</h1>
        <p className="mt-1 text-sm text-white/60">
          Personnalise ton affichage dans le portail.
        </p>
      </header>

      {/* Avatar */}
      <section className="rounded-2xl border border-brand-800 bg-brand-900 p-5">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
          Photo de profil
        </h2>
        <div className="mt-4 flex items-center gap-4">
          {avatarUrl ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={avatarUrl}
              alt="Photo de profil"
              className="h-20 w-20 rounded-full object-cover ring-2 ring-accent-500/40"
            />
          ) : (
            <div className="flex h-20 w-20 items-center justify-center rounded-full bg-brand-800 text-2xl font-bold text-white/70 ring-2 ring-brand-700">
              {initials}
            </div>
          )}
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => fileRef.current?.click()}
              disabled={avatarBusy}
              className="btn-secondary text-sm disabled:opacity-60"
            >
              {avatarBusy ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <Camera className="mr-2 h-4 w-4" />
              )}
              {avatarUrl ? "Changer la photo" : "Ajouter une photo"}
            </button>
            {avatarUrl ? (
              <button
                type="button"
                onClick={deleteAvatar}
                disabled={avatarBusy}
                className="inline-flex items-center rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-300 hover:bg-rose-500/20 disabled:opacity-60"
              >
                <Trash2 className="mr-2 h-4 w-4" /> Retirer
              </button>
            ) : null}
          </div>
          <input
            ref={fileRef}
            type="file"
            accept="image/jpeg,image/png,image/webp"
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0];
              e.target.value = "";
              if (f) void uploadAvatar(f);
            }}
          />
        </div>
        <p className="mt-3 text-xs text-white/40">
          JPEG, PNG ou WEBP — 4 Mo max.
        </p>
      </section>

      {/* Identité */}
      <section className="rounded-2xl border border-brand-800 bg-brand-900 p-5">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
          Identité
        </h2>
        <form onSubmit={saveProfile} className="mt-4 space-y-3">
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <label className="label">Prénom</label>
              <input
                type="text"
                value={firstName}
                onChange={(e) => setFirstName(e.target.value)}
                placeholder="Ex. Steven"
                maxLength={100}
                className="input"
              />
            </div>
            <div>
              <label className="label">Nom</label>
              <input
                type="text"
                value={lastName}
                onChange={(e) => setLastName(e.target.value)}
                placeholder="Ex. Giguère"
                maxLength={100}
                className="input"
              />
            </div>
          </div>
          <div>
            <label className="label">Courriel</label>
            <input
              type="email"
              value={user.email}
              disabled
              className="input opacity-70"
            />
            <p className="mt-1 text-[11px] text-white/40">
              Le courriel ne peut pas être modifié ici. Demande à un
              administrateur si tu en as besoin.
            </p>
          </div>

          {profileMsg ? (
            <p className="rounded-md border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-300">
              {profileMsg}
            </p>
          ) : null}
          {profileErr ? (
            <p className="rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
              {profileErr}
            </p>
          ) : null}

          <button
            type="submit"
            disabled={savingProfile}
            className="btn-accent text-sm disabled:opacity-60"
          >
            {savingProfile ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <Save className="mr-2 h-4 w-4" />
            )}
            Enregistrer
          </button>
        </form>
      </section>

      {/* Mot de passe */}
      <section className="rounded-2xl border border-brand-800 bg-brand-900 p-5">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
          Mot de passe
        </h2>
        <form onSubmit={changePassword} className="mt-4 space-y-3">
          <div>
            <label className="label">Mot de passe actuel</label>
            <input
              type="password"
              value={currentPwd}
              onChange={(e) => setCurrentPwd(e.target.value)}
              autoComplete="current-password"
              className="input"
              required
            />
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <label className="label">Nouveau mot de passe</label>
              <input
                type="password"
                value={newPwd}
                onChange={(e) => setNewPwd(e.target.value)}
                minLength={8}
                autoComplete="new-password"
                className="input"
                required
              />
            </div>
            <div>
              <label className="label">Confirmation</label>
              <input
                type="password"
                value={confirmPwd}
                onChange={(e) => setConfirmPwd(e.target.value)}
                minLength={8}
                autoComplete="new-password"
                className="input"
                required
              />
            </div>
          </div>

          {pwdMsg ? (
            <p className="rounded-md border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-300">
              {pwdMsg}
            </p>
          ) : null}
          {pwdErr ? (
            <p className="rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
              {pwdErr}
            </p>
          ) : null}

          <button
            type="submit"
            disabled={pwdBusy}
            className="btn-accent text-sm disabled:opacity-60"
          >
            {pwdBusy ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <KeyRound className="mr-2 h-4 w-4" />
            )}
            Changer le mot de passe
          </button>
        </form>
      </section>

      {/* Footer — déconnexion + identité affichée */}
      <section className="flex items-center justify-between rounded-2xl border border-brand-800 bg-brand-900/60 px-5 py-3 text-xs text-white/50">
        <span className="inline-flex items-center gap-2">
          <UserCircle className="h-4 w-4" />
          Connecté en tant que {user.display_name || user.email}
        </span>
        <button
          type="button"
          onClick={() => {
            // Nettoie aussi le token explicitement (defense in depth).
            if (getToken()) setToken(null);
            signOut();
          }}
          className="text-rose-300 hover:text-rose-200"
        >
          Se déconnecter
        </button>
      </section>
    </div>
  );
}
