"""Expéditeurs des Communications locatives — règles d'affaires.

Kyle, gestionnaire contractuel du volet Gestion locative, écrit aux
locataires depuis Kratos. La boîte d'ENVOI est une boîte Microsoft 365
du tenant (Graph refuse un domaine externe) ; son PROFIL d'expéditeur
(Communications → Profils d'expéditeur) porte le nom affiché et
l'adresse « Répondre à », là où atterrissent les réponses des
locataires. Ce profil vit dans la config ``immo.communications`` (table
automation_settings), pas dans le code.

Steven (2026-10-18) : « le courriel pour reply suite à l'envoi de
courriel de Kyle doit être kyle@gestionmagnifica.com ». La valeur est
donc posée ici au démarrage, UNE seule fois (marqueur applied_backfills),
sur tout profil qui est le sien : un changement fait ensuite à la main
dans les profils n'est jamais réécrasé.
"""

from __future__ import annotations

import copy
import json
import logging
from typing import Any, NamedTuple

from sqlalchemy import select, text

from app.models.automation_setting import AutomationSetting
from app.services.automation_state import set_automation_config

log = logging.getLogger(__name__)

#: Clé de config des réglages d'envoi de la page Communications
#: (profils d'expéditeur + défauts plats).
REGLAGES_COMMUNICATIONS = "immo.communications"

#: Adresse de réponse des courriels envoyés au nom de Kyle (Steven,
#: 2026-10-18).
REPLY_TO_KYLE = "kyle@gestionmagnifica.com"

#: Marqueur applied_backfills de la correction one-shot.
CLE_CORRECTION_REPLY_TO_KYLE = "immo_communications_reply_to_kyle_v1"


def _designe_kyle(valeur: Any) -> bool:
    return "kyle" in str(valeur or "").lower()


def profil_est_kyle(profil: dict) -> bool:
    """Un profil est celui de Kyle si son nom, son nom affiché, sa boîte
    d'envoi ou son adresse de réponse le nomment (« Kyle », « Kyle Brown -
    Gestion locative », kyle.gestion@gmail.com…)."""
    return any(
        _designe_kyle(profil.get(k))
        for k in ("label", "from_name", "from_email", "reply_to")
    )


class CorrectionReplyTo(NamedTuple):
    #: Config corrigée (copie — l'original n'est pas modifié).
    config: dict
    #: Ce qui a changé, lisible dans les logs.
    modifications: list[str]
    #: Vrai dès qu'un profil (ou les défauts plats) désigne Kyle, même
    #: déjà correct. Faux = rien à corriger ici, pas encore.
    kyle_trouve: bool


def corriger_reply_to_kyle(cfg: dict) -> CorrectionReplyTo:
    """Pose ``REPLY_TO_KYLE`` comme adresse de réponse de tout profil de
    Kyle, et des défauts plats (envoi sans profil) s'ils le désignent.
    Fonction PURE : ne touche ni la base ni ``cfg``."""
    nouveau = copy.deepcopy(cfg or {})
    modifications: list[str] = []
    trouve = False
    for profil in nouveau.get("profils") or []:
        if not isinstance(profil, dict) or not profil_est_kyle(profil):
            continue
        trouve = True
        avant = str(profil.get("reply_to") or "").strip()
        if avant.lower() != REPLY_TO_KYLE:
            profil["reply_to"] = REPLY_TO_KYLE
            modifications.append(
                f"profil « {profil.get('label') or '?'} » : "
                f"{avant or '(vide)'} → {REPLY_TO_KYLE}"
            )
    if profil_est_kyle(nouveau):
        trouve = True
        avant = str(nouveau.get("reply_to") or "").strip()
        if avant.lower() != REPLY_TO_KYLE:
            nouveau["reply_to"] = REPLY_TO_KYLE
            modifications.append(
                f"défauts d'envoi : {avant or '(vide)'} → {REPLY_TO_KYLE}"
            )
    return CorrectionReplyTo(nouveau, modifications, trouve)


async def corriger_reply_to_kyle_une_fois(db) -> list[str]:
    """Correction au démarrage, une seule fois (marqueur applied_backfills).

    Le marqueur n'est posé que lorsqu'un profil de Kyle existe — sinon on
    réessaie au prochain démarrage, le temps que le profil soit créé.
    Une fois posé, un choix fait ensuite à la main dans les profils n'est
    jamais réécrasé. Commite quand quelque chose est écrit.
    """
    deja = (
        await db.execute(
            text("SELECT 1 FROM applied_backfills WHERE key = :k"),
            {"k": CLE_CORRECTION_REPLY_TO_KYLE},
        )
    ).first()
    if deja is not None:
        return []
    ligne = (
        await db.execute(
            select(AutomationSetting).where(
                AutomationSetting.key == REGLAGES_COMMUNICATIONS
            )
        )
    ).scalar_one_or_none()
    cfg: dict = {}
    if ligne is not None and ligne.config_json:
        try:
            data = json.loads(ligne.config_json)
            cfg = data if isinstance(data, dict) else {}
        except ValueError:
            cfg = {}
    resultat = corriger_reply_to_kyle(cfg)
    if not resultat.kyle_trouve:
        log.info(
            "Adresse de réponse de Kyle : aucun profil d'expéditeur ne le "
            "désigne encore — nouvel essai au prochain démarrage."
        )
        return []
    if resultat.modifications:
        await set_automation_config(
            db, REGLAGES_COMMUNICATIONS, resultat.config
        )
    await db.execute(
        text(
            "INSERT INTO applied_backfills (key) VALUES (:k) "
            "ON CONFLICT (key) DO NOTHING"
        ),
        {"k": CLE_CORRECTION_REPLY_TO_KYLE},
    )
    await db.commit()
    return resultat.modifications
