"""Brief du matin par courriel (Phil, 2026-10-15).

Problème : la routine claude.ai de Phil (« Horizon — Ma journée », lun.-ven.
05 h) lit Kratos par le connecteur MCP, mais le connecteur n'est pas
attaché de façon fiable aux sessions planifiées (« Kratos n'a pas été lu
ce matin »). Les crons Render de Kratos, eux, ne tournent pas (toutes les
automatisations affichent « jamais exécutée »).

Solution autonome : une boucle démarrée AVEC l'application (comme les
filets QBO) envoie chaque matin, à l'heure réglée (Paramètres →
Automatisations → « Brief du matin par courriel », défaut 04 h 30
Montréal, jours ouvrables), le digest Kratos de chaque destinataire par
courriel. La routine n'a plus qu'à lire ce courriel dans Outlook (un
connecteur de première partie, toujours attaché) ; le connecteur Kratos
devient un plus, pas une dépendance.

Destinataires : UNIQUEMENT la liste ``destinataires`` (courriels) de la
configuration de l'automatisation (Paramètres → Automatisations, ou
``PUT /api/v1/automations/brief-matin/destinataires``). Liste vide =
personne. Plus aucun repli implicite : le 2026-10-15, le repli « tous
les détenteurs d'une clé API » a envoyé le brief aux partenaires de
Phil sans que personne l'ait décidé — on n'écrit à quelqu'un que si
un humain l'a inscrit.
Idempotent par jour (``claim_cron_run``). Jamais de contenu hors des
permissions de l'utilisateur : le digest est celui de ``kratos_mon_brief``.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

log = logging.getLogger(__name__)

JOB = "brief_matin"
FUSEAU = ZoneInfo("America/Toronto")
_PREMIER_PASSAGE_S = 60.0
_INTERVALLE_S = 300.0
#: Deux envois ne peuvent pas être à moins de 20 h d'écart (un par jour).
_MIN_INTERVALLE_S = 20 * 3600

_JOURS = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")
_MOIS = (
    "janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
    "septembre", "octobre", "novembre", "décembre",
)


def date_lisible(d: datetime) -> str:
    return f"{_JOURS[d.weekday()]} {d.day} {_MOIS[d.month - 1]} {d.year}"


def sujet_du_jour(d: datetime) -> str:
    return f"Kratos — brief du {date_lisible(d)}"


def liste_destinataires(config: Optional[dict[str, Any]]) -> list[str]:
    """Courriels configurés, nettoyés et dédoublonnés (ordre conservé)."""
    out: list[str] = []
    for e in ((config or {}).get("destinataires") or []):
        s = str(e).strip().lower()
        if s and s not in out:
            out.append(s)
    return out


async def destinataires(db: AsyncSession, config: Optional[dict[str, Any]] = None) -> list:
    """Utilisateurs à servir : UNIQUEMENT la liste ``destinataires``
    (courriels) de la configuration — vide = personne. Aucun repli
    implicite (règle Phil 2026-10-15 : on n'écrit à quelqu'un que si un
    humain l'a inscrit)."""
    from app.models.user import User

    emails = liste_destinataires(config)
    if not emails:
        return []
    rows = (
        await db.execute(select(User).where(func.lower(User.email).in_(emails)))
    ).scalars().all()
    vus: set[str] = set()
    out = []
    for u in rows:
        email = (getattr(u, "email", "") or "").strip().lower()
        if not email or email in vus or not getattr(u, "is_active", True):
            continue
        vus.add(email)
        out.append(u)
    return out


def _echapper(s: Any) -> str:
    return (
        str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )


#: Balises qui encadrent le bloc JSON dans le courriel : la routine
#: n'a qu'à prendre le texte entre les deux.
JSON_DEBUT = "<<<KRATOS_JSON"
JSON_FIN = "KRATOS_JSON>>>"
_MAX_EVENEMENTS = 150
_MAX_LISTE = 50


def periode_debut(now_local: datetime) -> datetime:
    """DEBUT de la période couverte, comme dans la routine de Phil : hier
    05 h ; le lundi, vendredi 05 h (vendredi + fin de semaine)."""
    recul = 3 if now_local.weekday() == 0 else 1
    return (now_local - timedelta(days=recul)).replace(hour=5, minute=0, second=0, microsecond=0)


def _heure_locale(iso: Optional[str]) -> str:
    if not iso:
        return ""
    try:
        d = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d.astimezone(FUSEAU).strftime("%a %d %H:%M")
    except ValueError:
        return str(iso)[:16]


async def collecter_donnees(db: AsyncSession, user, now_local: datetime) -> dict[str, Any]:
    """Tout ce que la routine allait chercher par le connecteur, scopé aux
    permissions de l'utilisateur (digest) ; activité, analyses et deals
    lus comme une clé API sans restriction de pôle (destinataires =
    propriétaires d'une clé)."""
    from app.api.v1.endpoints.activity import list_entities
    from app.api.v1.endpoints.mcp_server import _ScopeCtx, _sommaire_du_jour
    from app.services.user_ai import digest_pour_utilisateur

    debut = periode_debut(now_local)
    donnees: dict[str, Any] = {
        "genere_le": now_local.isoformat(timespec="seconds"),
        "periode": {"debut": debut.isoformat(timespec="seconds"), "fin": now_local.isoformat(timespec="seconds")},
        "digest": "",
        "sommaire": {},
        "analyses": [],
        "deals": [],
        "avertissements": [],
    }
    try:
        donnees["digest"] = await digest_pour_utilisateur(db, user)
    except Exception as exc:  # noqa: BLE001
        donnees["avertissements"].append(f"digest indisponible : {type(exc).__name__}")
    try:
        som = await _sommaire_du_jour(
            db, None, {"from": debut.date().isoformat(), "to": now_local.date().isoformat()}
        )
        debut_utc = debut.astimezone(timezone.utc)
        evenements = []
        for e in som.get("evenements") or []:
            q = e.get("quand")
            try:
                dq = datetime.fromisoformat(str(q)) if q else None
                if dq is not None and dq.tzinfo is None:
                    dq = dq.replace(tzinfo=timezone.utc)
            except ValueError:
                dq = None
            if dq is not None and dq < debut_utc:
                continue
            det = e.get("details")
            if isinstance(det, dict):
                det = {k: (v if len(str(v)) <= 160 else str(v)[:160] + "…") for k, v in list(det.items())[:8]}
            evenements.append({
                "quand": q, "qui": e.get("qui"), "action": e.get("action"),
                "entite": e.get("entite"), "id": e.get("id"), "details": det,
            })
        donnees["sommaire"] = {
            "total_visibles": som.get("total_visibles"),
            "fenetre_tronquee": som.get("fenetre_tronquee"),
            "synthese": som.get("synthese") or {},
            "evenements": evenements[:_MAX_EVENEMENTS],
            "evenements_omis": max(0, len(evenements) - _MAX_EVENEMENTS),
        }
    except Exception as exc:  # noqa: BLE001
        donnees["avertissements"].append(f"journal d'activité indisponible : {type(exc).__name__}")
    for cle, list_type, kw in (
        ("analyses", "analyses", {"active_only": True}),
        ("deals", "deals", {}),
    ):
        try:
            res = await list_entities(db, _ScopeCtx(None), list_type, limit=_MAX_LISTE, **kw)
            items = res.get("items") if isinstance(res, dict) else res
            donnees[cle] = list(items or [])[:_MAX_LISTE]
        except Exception as exc:  # noqa: BLE001
            donnees["avertissements"].append(f"{cle} indisponibles : {type(exc).__name__}")
    return donnees


def _ligne_item(it: dict[str, Any]) -> str:
    if not isinstance(it, dict):
        return _echapper(it)
    nom = it.get("label") or it.get("title") or it.get("name") or it.get("address") or f"#{it.get('id')}"
    morceaux = [f"#{it.get('id')} {nom}"]
    for k in ("city", "status_label", "status", "stage", "priority", "nb_logements", "asking_price", "amount", "montant"):
        v = it.get(k)
        if v not in (None, "", []):
            morceaux.append(f"{k} : {v}")
    return _echapper(" — ".join(str(m) for m in morceaux))


def construire_html(donnees: dict[str, Any], prenom: str, quand: datetime) -> str:
    import json as _json

    digest = donnees.get("digest") or ""
    lignes = [l.strip() for l in digest.splitlines() if l.strip()]
    titre = lignes[0] if lignes else f"État de Kratos au {quand.date().isoformat()}"
    puces = "".join(f"<li>{_echapper(l)}</li>" for l in lignes[1:])
    som = donnees.get("sommaire") or {}
    synth = som.get("synthese") or {}
    par_pole = ", ".join(f"{k} : {v}" for k, v in (synth.get("par_pole") or {}).items()) or "rien"
    par_personne = ", ".join(f"{k} : {v}" for k, v in (synth.get("par_personne") or {}).items()) or "personne"
    evenements = som.get("evenements") or []
    lignes_ev = "".join(
        f"<li>{_echapper(_heure_locale(e.get('quand')))} — {_echapper(e.get('qui') or 'système')} — "
        f"{_echapper(e.get('action'))} {_echapper(e.get('entite') or '')}"
        f"{('#' + str(e.get('id'))) if e.get('id') else ''}"
        + (f" <span style=\"color:#666\">{_echapper(_json.dumps(e.get('details'), ensure_ascii=False)[:160])}</span>" if e.get("details") else "")
        + "</li>"
        for e in evenements[:80]
    )
    analyses = donnees.get("analyses") or []
    deals = donnees.get("deals") or []
    periode = donnees.get("periode") or {}
    avert = donnees.get("avertissements") or []
    bloc_json = _json.dumps(donnees, ensure_ascii=False, default=str)
    return (
        f"<p>Bonjour {_echapper(prenom)},</p>"
        f"<p>État de Kratos ce {_echapper(date_lisible(quand))}, généré à {quand.strftime('%H:%M')} "
        f"(Montréal). Période couverte : du {_echapper(_heure_locale(periode.get('debut')))} au "
        f"{_echapper(_heure_locale(periode.get('fin')))}.</p>"
        + ("".join(f"<p style=\"color:#b00\">⚠ {_echapper(a)}</p>" for a in avert))
        + f"<h3>Chiffres</h3><p><strong>{_echapper(titre)}</strong></p><ul>{puces}</ul>"
        + f"<h3>Ce qui a bougé depuis le début de la période</h3>"
        f"<p>Par pôle : {_echapper(par_pole)}.<br/>Par personne : {_echapper(par_personne)}.</p>"
        + (f"<ol>{lignes_ev}</ol>" if lignes_ev else "<p>Aucun événement.</p>")
        + (f"<p style=\"color:#666\">{len(evenements) - 80} événements de plus dans le bloc JSON.</p>" if len(evenements) > 80 else "")
        + f"<h3>Analyses de leads en cours ({len(analyses)})</h3>"
        + ("<ul>" + "".join(f"<li>{_ligne_item(a)}</li>" for a in analyses) + "</ul>" if analyses else "<p>Aucune.</p>")
        + f"<h3>Deals actifs ({len(deals)})</h3>"
        + ("<ul>" + "".join(f"<li>{_ligne_item(d)}</li>" for d in deals) + "</ul>" if deals else "<p>Aucun.</p>")
        + "<h3>Bloc machine (pour la routine Claude)</h3>"
        "<p style=\"color:#666;font-size:12px\">Le texte entre les deux balises est du JSON : periode, digest, "
        "sommaire (synthese, evenements), analyses, deals, avertissements.</p>"
        f"<pre style=\"font-size:11px;white-space:pre-wrap\">{JSON_DEBUT}\n{_echapper(bloc_json)}\n{JSON_FIN}</pre>"
        "<p style=\"color:#666;font-size:12px\">Courriel produit par Kratos pour les routines Claude "
        "(Paramètres → Automatisations → Brief du matin par courriel). "
        "<a href=\"https://immohorizon.com/app\">Ouvrir Kratos</a></p>"
    )


async def envoyer_brief(
    db: AsyncSession, *, quand: Optional[datetime] = None, config: Optional[dict[str, Any]] = None
) -> dict[str, Any]:
    """Envoie le brief à chaque destinataire. Renvoie {envoyes, destinataires,
    erreurs}. N'appelle pas commit."""
    from app.integrations.email_graph import get_mailer
    from app.services.audit import log_action
    from app.services.automation_state import get_automation_config

    quand = quand or datetime.now(FUSEAU)
    cfg = config if config is not None else await get_automation_config(JOB)
    users = await destinataires(db, cfg)
    rapport: dict[str, Any] = {"envoyes": 0, "destinataires": [u.email for u in users], "erreurs": []}
    if not users:
        rapport["erreurs"].append(
            "aucun destinataire configuré — Paramètres → Automatisations → "
            "Brief du matin → destinataires (vide = personne)"
        )
        return rapport
    mailer = get_mailer()
    if not mailer.ready:
        rapport["erreurs"].append("Mailer Microsoft 365 non configuré")
        return rapport
    sujet = sujet_du_jour(quand)
    for u in users:
        try:
            donnees = await collecter_donnees(db, u, quand)
            prenom = (
                getattr(u, "first_name", None) or getattr(u, "full_name", None)
                or getattr(u, "name", None) or u.email
            ).split()[0]
            await mailer.send(to=[u.email], subject=sujet, html_body=construire_html(donnees, prenom, quand))
            rapport["envoyes"] += 1
            await log_action(
                db, user=u, action="brief_matin.envoye", entity_type="user",
                entity_id=getattr(u, "id", None), details={"sujet": sujet},
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("brief du matin : envoi à %s échoué", u.email, exc_info=True)
            rapport["erreurs"].append(f"{u.email} : {type(exc).__name__}: {str(exc)[:160]}")
    return rapport


def est_du(now_local: datetime, heure: int, minute: int, jours_ouvrables: bool) -> bool:
    """Vrai si on a dépassé l'heure d'envoi du jour (et que c'est un jour
    servi). L'idempotence par jour est assurée ailleurs (claim_cron_run)."""
    if jours_ouvrables and now_local.weekday() >= 5:
        return False
    return (now_local.hour, now_local.minute) >= (heure, minute)


async def envoyer_si_du(now_local: Optional[datetime] = None) -> Optional[dict[str, Any]]:
    """Point d'entrée de la boucle : envoie une fois par jour, après l'heure
    réglée. None si rien à faire."""
    from app.db.session import AsyncSessionLocal
    from app.services.automation_state import (
        get_automation_config,
        get_automation_int,
        is_automation_enabled,
    )
    from app.services.cron_guard import claim_cron_run

    if not await is_automation_enabled(JOB):
        return None
    now_local = now_local or datetime.now(FUSEAU)
    heure = await get_automation_int(JOB, "heure", 4)
    minute = await get_automation_int(JOB, "minute", 30)
    cfg = await get_automation_config(JOB)
    jours_ouvrables = str(cfg.get("jours_ouvrables", "1")) not in ("0", "false", "False")
    if not est_du(now_local, heure, minute % 60, jours_ouvrables):
        return None
    async with AsyncSessionLocal() as db:
        if not await claim_cron_run(db, JOB, _MIN_INTERVALLE_S):
            return None
        rapport = await envoyer_brief(db, quand=now_local, config=cfg)
        await db.commit()
        log.info("brief du matin envoyé : %s", rapport)
        return rapport


async def boucle() -> None:
    """Boucle de fond démarrée avec l'app (comme les filets QBO) : premier
    passage ~1 min après le boot, puis toutes les 5 minutes. Jamais sous
    pytest : la boucle travaillerait en parallèle des tests sur la base
    de test (4 tests du registre des courtiers tombaient)."""
    import sys

    if "pytest" in sys.modules:
        log.info("brief du matin : boucle désactivée (tests)")
        return
    delay = _PREMIER_PASSAGE_S
    while True:
        try:
            await asyncio.sleep(delay)
            delay = _INTERVALLE_S
            await envoyer_si_du()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.warning("Boucle brief du matin : itération échouée", exc_info=True)


__all__ = [
    "JOB",
    "FUSEAU",
    "sujet_du_jour",
    "date_lisible",
    "destinataires",
    "liste_destinataires",
    "construire_html",
    "collecter_donnees",
    "periode_debut",
    "JSON_DEBUT",
    "JSON_FIN",
    "envoyer_brief",
    "est_du",
    "envoyer_si_du",
    "boucle",
]
