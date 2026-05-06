"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "@/i18n/navigation";
import {
  ArrowLeft,
  Camera,
  Check,
  KeyRound,
  Loader2,
  Save,
  Trash2,
  UserCircle
} from "lucide-react";

import { authedFetch, getToken, setToken } from "@/lib/auth";
import { useCurrentUser } from "@/hooks/use-current-user";
import { Link } from "@/i18n/navigation";
import { KratosLogo } from "@/components/kratos-logo";
import {
  PROFILE_COLORS,
  PROFILE_COLOR_SWATCH as PROFILE_SWATCH_CLS,
  type ProfileColor
} from "@/lib/profile-colors";

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
  const [profileColor, setProfileColor] = useState<ProfileColor | null>(
    null
  );
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
      setProfileColor(
        ((user as unknown) as { profile_color?: ProfileColor | null })
          .profile_color ?? null
      );
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
          last_name: lastName,
          profile_color: profileColor
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

  async function persistColor(c: ProfileColor | null) {
    setProfileMsg(null);
    setProfileErr(null);
    try {
      const res = await authedFetch("/api/v1/auth/me/profile", {
        method: "PATCH",
        body: JSON.stringify({ profile_color: c })
      });
      if (!res.ok) {
        const txt = await res.text().catch(() => "");
        throw new Error(`HTTP ${res.status} ${txt.slice(0, 120)}`);
      }
      router.refresh();
    } catch (e) {
      setProfileErr((e as Error).message || "Échec");
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
    <>
      {/* Topbar minimaliste — flèche back à gauche, Kratos à droite
          (renvoie au portail). Pas de sidebar ici parce que /profil
          est partagé entre tous les volets. */}
      <header
        className="sticky top-0 z-30 flex items-center justify-between border-b border-brand-800 bg-brand-950/95 px-4 backdrop-blur lg:px-6"
        style={{ paddingTop: "env(safe-area-inset-top)" }}
      >
        <div className="flex min-h-[64px] items-center gap-3 lg:min-h-[120px]">
          <button
            type="button"
            onClick={() => router.back()}
            className="inline-flex items-center gap-1.5 rounded-md px-2 py-1.5 text-sm text-white/70 hover:bg-brand-900 hover:text-white"
            aria-label="Retour"
          >
            <ArrowLeft className="h-4 w-4" />
            <span>Retour</span>
          </button>
          <span className="text-sm font-semibold text-white">
            Mon profil
          </span>
        </div>
        <Link
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          href={"/connexion" as any}
          aria-label="Retour au portail"
          title="Retour au portail"
          className="rounded-md p-1 hover:opacity-80"
        >
          <KratosLogo size={120} floating={false} />
        </Link>
      </header>

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

      {/* Couleur de profil */}
      <section className="rounded-2xl border border-brand-800 bg-brand-900 p-5">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
          Couleur de profil
        </h2>
        <p className="mt-1 text-xs text-white/50">
          Sert à teinter ta pastille d&apos;assignation dans le pipeline
          des deals et les listes d&apos;équipe.
        </p>
        <div className="mt-4 flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => {
              setProfileColor(null);
              void persistColor(null);
            }}
            aria-label="Aucune couleur"
            className={`flex h-9 w-9 items-center justify-center rounded-full border-2 bg-brand-800 transition ${
              profileColor === null
                ? "border-white"
                : "border-transparent hover:border-white/30"
            }`}
          >
            {profileColor === null ? (
              <Check className="h-4 w-4 text-white" />
            ) : null}
          </button>
          {PROFILE_COLORS.map((c) => {
            const isActive = profileColor === c.value;
            return (
              <button
                key={c.value}
                type="button"
                onClick={() => {
                  setProfileColor(c.value);
                  void persistColor(c.value);
                }}
                aria-label={c.label}
                title={c.label}
                className={`flex h-9 w-9 items-center justify-center rounded-full border-2 transition ${
                  isActive
                    ? "border-white"
                    : "border-transparent hover:border-white/30"
                } ${PROFILE_SWATCH_CLS[c.value]}`}
              >
                {isActive ? (
                  <Check className="h-4 w-4 text-white drop-shadow" />
                ) : null}
              </button>
            );
          })}
        </div>
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
    </>
  );
}
