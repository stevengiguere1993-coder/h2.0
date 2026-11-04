"""Envoi du rapport d'une rencontre par courriel (Steven, 2026-10-29).

« Envoyer rapport » sur la fiche d'une rencontre : on choisit les
contacts, et le courriel part de la boîte de l'utilisateur CONNECTÉ
(Microsoft 365, ``from_email=user.email``), jamais d'info@. Les réponses
reviennent à cette même personne.

Le corps reprend le résumé global puis, section par section, le résumé
IA structuré (décisions, actions, questions en suspens, risques). Les
transcripts bruts ne partent pas. Chaque envoi est tracé dans
``rencontres.envois_json`` (affiché sur la fiche).
"""

from __future__ import annotations

import html
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Optional

from app.models.rencontre import Rencontre, RencontreSection

log = logging.getLogger(__name__)

_COURRIEL = re.compile(r"^[^@\s<>,;]+@[^@\s<>,;]+\.[^@\s<>,;]+$")

#: Nombre d'envois gardés dans l'historique de la fiche.
_MAX_ENVOIS = 50


class EnvoiRapportErreur(Exception):
    """Envoi refusé ou échoué — ``status`` = code HTTP à renvoyer."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def normaliser_courriels(adresses: Optional[list[str]]) -> list[str]:
    """Nettoie, valide et dédoublonne (insensible à la casse). Lève
    ``EnvoiRapportErreur(422)`` sur une adresse invalide."""
    out: list[str] = []
    vus: set[str] = set()
    for brut in adresses or []:
        a = (brut or "").strip()
        if not a:
            continue
        if not _COURRIEL.match(a):
            raise EnvoiRapportErreur(422, f"Adresse courriel invalide : {a}")
        if a.lower() in vus:
            continue
        vus.add(a.lower())
        out.append(a)
    return out


def sujet_par_defaut(r: Rencontre) -> str:
    sujet = f"Rapport de rencontre — {r.title}"
    if r.meeting_date:
        sujet += f" ({r.meeting_date.isoformat()})"
    return sujet[:255]


def _txt(s: Any) -> str:
    """Texte échappé, sauts de ligne conservés."""
    return html.escape(str(s or "").strip()).replace("\n", "<br>")


def _liste(titre: str, items: list[str]) -> str:
    items = [i for i in items if str(i or "").strip()]
    if not items:
        return ""
    lis = "".join(f"<li style=\"margin:2px 0\">{_txt(i)}</li>" for i in items)
    return (
        f"<p style=\"margin:10px 0 2px;font-weight:600\">{html.escape(titre)}</p>"
        f"<ul style=\"margin:0;padding-left:20px\">{lis}</ul>"
    )


def _actions(items: list[dict]) -> str:
    lignes: list[str] = []
    for a in items or []:
        if not isinstance(a, dict) or not str(a.get("title") or "").strip():
            continue
        ligne = _txt(a.get("title"))
        extras = []
        if a.get("owner"):
            extras.append(f"responsable : {_txt(a['owner'])}")
        if a.get("due"):
            extras.append(f"échéance : {_txt(a['due'])}")
        if extras:
            ligne += f" <span style=\"color:#555\">({' · '.join(extras)})</span>"
        lignes.append(ligne)
    if not lignes:
        return ""
    lis = "".join(f"<li style=\"margin:2px 0\">{l}</li>" for l in lignes)
    return (
        "<p style=\"margin:10px 0 2px;font-weight:600\">Actions à faire</p>"
        f"<ul style=\"margin:0;padding-left:20px\">{lis}</ul>"
    )


def _resume_section(s: RencontreSection) -> Optional[dict]:
    if not s.ai_summary_json:
        return None
    try:
        v = json.loads(s.ai_summary_json)
    except Exception:  # noqa: BLE001
        return None
    return v if isinstance(v, dict) else None


def construire_rapport_html(
    r: Rencontre,
    sections: list[RencontreSection],
    *,
    entreprises: list[str],
    message: Optional[str],
    expediteur: str,
) -> str:
    entete: list[str] = []
    if r.meeting_date:
        entete.append(f"<b>Date :</b> {html.escape(r.meeting_date.isoformat())}")
    if r.location:
        entete.append(f"<b>Lieu :</b> {_txt(r.location)}")
    if r.attendees:
        entete.append(f"<b>Participants :</b> {_txt(r.attendees)}")
    if entreprises:
        entete.append(
            f"<b>Entreprises :</b> {html.escape(', '.join(entreprises))}"
        )

    parties: list[str] = []
    if (message or "").strip():
        parties.append(f"<p style=\"margin:0 0 16px\">{_txt(message)}</p>")
    parties.append(
        f"<h2 style=\"margin:0 0 6px;font-size:18px\">{html.escape(r.title)}</h2>"
    )
    if entete:
        parties.append(
            "<p style=\"margin:0 0 14px;color:#333\">"
            + "<br>".join(entete)
            + "</p>"
        )
    if (r.global_summary or "").strip():
        parties.append(
            "<h3 style=\"margin:16px 0 4px;font-size:15px\">Résumé global</h3>"
            f"<p style=\"margin:0\">{_txt(r.global_summary)}</p>"
        )

    blocs: list[str] = []
    for s in sections:
        res = _resume_section(s)
        if not res:
            continue
        corps = ""
        if str(res.get("summary") or "").strip():
            corps += f"<p style=\"margin:0\">{_txt(res['summary'])}</p>"
        corps += _liste("Décisions", list(res.get("decisions") or []))
        corps += _actions(list(res.get("action_items") or []))
        corps += _liste("Questions en suspens", list(res.get("open_questions") or []))
        corps += _liste("Risques", list(res.get("risks") or []))
        if not corps:
            continue
        titre = (
            ""
            if len(sections) == 1 and s.title.strip() == r.title.strip()
            else f"<h4 style=\"margin:0 0 4px;font-size:14px\">{html.escape(s.title)}</h4>"
        )
        blocs.append(
            "<div style=\"margin:12px 0;padding:10px 12px;border-left:3px solid "
            f"#98651c;background:#faf7f2\">{titre}{corps}</div>"
        )
    if blocs:
        parties.append(
            "<h3 style=\"margin:18px 0 4px;font-size:15px\">"
            + ("Points discutés" if len(blocs) > 1 else "Détail")
            + "</h3>"
            + "".join(blocs)
        )
    if not (r.global_summary or "").strip() and not blocs and (r.notes or "").strip():
        parties.append(
            "<h3 style=\"margin:16px 0 4px;font-size:15px\">Notes</h3>"
            f"<p style=\"margin:0\">{_txt(r.notes)}</p>"
        )
    parties.append(
        "<p style=\"margin:22px 0 0;color:#666;font-size:12px\">"
        f"Rapport envoyé par {html.escape(expediteur)} depuis Kratos.</p>"
    )
    return (
        "<div style=\"font-family:Arial,Helvetica,sans-serif;font-size:14px;"
        "line-height:1.45;color:#111;max-width:720px\">"
        + "".join(parties)
        + "</div>"
    )


def a_du_contenu(r: Rencontre, sections: list[RencontreSection]) -> bool:
    return bool(
        (r.global_summary or "").strip()
        or (r.notes or "").strip()
        or any(_resume_section(s) for s in sections)
    )


def _motif_graph(exc: Exception, boite: str) -> str:
    """Message lisible pour un refus Microsoft Graph."""
    status = getattr(getattr(exc, "response", None), "status_code", None)
    if status in (401, 403, 404):
        return (
            f"Microsoft 365 refuse d'envoyer depuis {boite} : cette adresse "
            "n'est pas une boîte du domaine (ou Kratos n'a pas le droit "
            "d'envoyer en son nom). Le rapport n'est pas parti."
        )
    return f"Envoi échoué ({type(exc).__name__}) : {str(exc)[:200]}"


async def envoyer_rapport(
    *,
    user,
    r: Rencontre,
    sections: list[RencontreSection],
    entreprises: list[str],
    to: list[str],
    cc: list[str],
    sujet: Optional[str],
    message: Optional[str],
) -> dict[str, Any]:
    """Envoie le rapport depuis la boîte de ``user`` et ajoute l'envoi à
    ``r.envois_json``. N'appelle pas commit. Lève ``EnvoiRapportErreur``."""
    from app.integrations.email_graph import get_mailer

    to = normaliser_courriels(to)
    cc = [a for a in normaliser_courriels(cc) if a.lower() not in {t.lower() for t in to}]
    if not to:
        raise EnvoiRapportErreur(422, "Choisis au moins un destinataire.")
    if not a_du_contenu(r, sections):
        raise EnvoiRapportErreur(
            422,
            "Rien à envoyer : résume la rencontre (ou ajoute des notes) d'abord.",
        )
    boite = (getattr(user, "email", None) or "").strip()
    if not boite:
        raise EnvoiRapportErreur(
            422, "Ton compte n'a pas d'adresse courriel : envoi impossible."
        )
    mailer = get_mailer()
    if not mailer.ready:
        raise EnvoiRapportErreur(503, "Courriel Microsoft 365 non configuré.")

    nom = getattr(user, "display_name", None) or boite
    sujet_final = (sujet or "").strip()[:255] or sujet_par_defaut(r)
    corps = construire_rapport_html(
        r, sections, entreprises=entreprises, message=message, expediteur=nom
    )
    try:
        await mailer.send(
            to=to,
            cc=cc or None,
            subject=sujet_final,
            html_body=corps,
            from_email=boite,
            from_name=nom,
            reply_to=boite,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("rapport rencontre %s : envoi échoué", r.id, exc_info=True)
        raise EnvoiRapportErreur(502, _motif_graph(exc, boite)) from exc

    envoi = {
        "le": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "par": nom,
        "de": boite,
        "a": to,
        "cc": cc,
        "sujet": sujet_final,
    }
    try:
        historique = json.loads(r.envois_json or "[]")
        if not isinstance(historique, list):
            historique = []
    except Exception:  # noqa: BLE001
        historique = []
    historique.append(envoi)
    r.envois_json = json.dumps(historique[-_MAX_ENVOIS:], ensure_ascii=False)
    return envoi
