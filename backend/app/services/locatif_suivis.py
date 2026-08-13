"""Fenêtres des SUIVIS ANNUELS locatifs (réglables dans Paramètres).

Retour Phil 2026-07-28 : « à partir de quand dans l'année tu switch pour
"à confirmer" / "à produire" ? ». Trois cadences, toutes réglables :

- **Renouvellements** : un bail passe « à envoyer » quand il reste au plus
  ``renouvellement_mois_avant`` mois avant sa fin (défaut 6 — l'avis TAL
  se transmet entre 6 et 3 mois avant la fin).
- **Assurances** : la preuve se re-confirme une fois par année, à partir
  du mois ``assurance_bascule_mois`` (défaut janvier). Toute confirmation
  ANTÉRIEURE à la dernière bascule annuelle repasse « à reconfirmer ».
- **Relevés 31** : jusqu'au mois ``releve31_bascule_mois`` inclus (défaut
  novembre), on travaille sur l'année PRÉCÉDENTE ; dès le 1er décembre,
  l'onglet passe à l'année courante et tout repart « à produire »
  (retour Phil 2026-07-31). (L'échéance légale reste le dernier jour
  de février.) La MÊME bascule verrouille la production : les relevés de
  l'année N ne sont créables qu'à partir du 1er décembre N
  (``ouverture_releve31``), retour Phil 2026-08-13.

Clé de config partagée (``automation_settings``) pour que tous les
endpoints lisent LES MÊMES fenêtres.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

log = logging.getLogger("immobilier.suivis")

#: Clé dans ``automation_settings``.
SUIVIS_KEY = "immo.suivis"

DEFAULT_RENOUVELLEMENT_MOIS_AVANT = 6
DEFAULT_ASSURANCE_BASCULE_MOIS = 1
DEFAULT_RELEVE31_BASCULE_MOIS = 11


@dataclass
class SuivisConfig:
    #: « À envoyer » commence N mois avant la fin du bail (1..12).
    renouvellement_mois_avant: int = DEFAULT_RENOUVELLEMENT_MOIS_AVANT
    #: Mois (1..12) de la re-confirmation annuelle des assurances.
    assurance_bascule_mois: int = DEFAULT_ASSURANCE_BASCULE_MOIS
    #: Jusqu'à ce mois inclus (1..12), les relevés 31 par défaut = année N-1.
    releve31_bascule_mois: int = DEFAULT_RELEVE31_BASCULE_MOIS
    #: Inclure les baux AU MOIS (chambres) dans le suivi des assurances.
    #: Défaut False : le proprio assure la maison de chambres, on n'exige
    #: rien du chambreur (retour Phil 2026-07-28).
    assurance_inclut_au_mois: bool = False

    def statut_assurance(self, confirmee_le: date | None) -> str:
        """'jamais' | 'a_reconfirmer' | 'ok' selon la bascule annuelle."""
        if confirmee_le is None:
            return "jamais"
        today = date.today()
        cutoff = date(today.year, self.assurance_bascule_mois, 1)
        if today < cutoff:  # la dernière bascule est celle de l'an dernier
            cutoff = date(today.year - 1, self.assurance_bascule_mois, 1)
        return "a_reconfirmer" if confirmee_le < cutoff else "ok"

    def annee_releve31_defaut(self, today: date) -> int:
        """Année fiscale par défaut des relevés 31 selon la bascule."""
        return (
            today.year - 1
            if today.month <= self.releve31_bascule_mois
            else today.year
        )

    def ouverture_releve31(self, annee: int) -> date:
        """Premier jour où les relevés de ``annee`` deviennent produisibles.

        MÊME bascule que ``annee_releve31_defaut`` : le lendemain du mois
        ``releve31_bascule_mois`` (défaut novembre → 1er décembre de
        ``annee``). Laisse décembre + janvier + février pour produire et
        remettre, l'échéance légale restant le dernier jour de février de
        ``annee + 1`` (retour Phil 2026-08-13 : « pour 2026, je peux juste
        les créer en 2027 » → la fenêtre s'ouvre le 1er déc. 2026)."""
        mois = self.releve31_bascule_mois
        if mois >= 12:
            return date(annee + 1, 1, 1)
        return date(annee, mois + 1, 1)

    def releve31_creation_ouverte(self, annee: int, today: date) -> bool:
        """La fenêtre de production de ``annee`` est-elle ouverte ?"""
        return today >= self.ouverture_releve31(annee)

    def fenetre_renouvellement(
        self, jours_avant_fin: int, avis_envoye: bool
    ) -> str:
        """'echu' | 'envoye' | 'imminente' | 'a_envoyer' | 'hors_fenetre'.

        « Échu » (date de fin passée SANS avis dans le système) prime sur
        tout : le bail est reconduit tacitement en vrai, mais sa date doit
        être corrigée dans Kratos — avant, il disparaissait silencieusement
        de la liste (retour Phil 2026-07-28)."""
        if jours_avant_fin < 0 and not avis_envoye:
            return "echu"
        if avis_envoye:
            return "envoye"
        seuil = self.renouvellement_mois_avant * 30
        if jours_avant_fin <= 90:
            return "imminente"
        if jours_avant_fin <= seuil:
            return "a_envoyer"
        return "hors_fenetre"


def _clamp_mois(v, defaut: int) -> int:
    try:
        n = int(v)
    except (TypeError, ValueError):
        return defaut
    return n if 1 <= n <= 12 else defaut


def parse_suivis(cfg: dict) -> SuivisConfig:
    cfg = cfg or {}
    return SuivisConfig(
        renouvellement_mois_avant=_clamp_mois(
            cfg.get("renouvellement_mois_avant"),
            DEFAULT_RENOUVELLEMENT_MOIS_AVANT,
        ),
        assurance_bascule_mois=_clamp_mois(
            cfg.get("assurance_bascule_mois"), DEFAULT_ASSURANCE_BASCULE_MOIS
        ),
        releve31_bascule_mois=_clamp_mois(
            cfg.get("releve31_bascule_mois"), DEFAULT_RELEVE31_BASCULE_MOIS
        ),
        assurance_inclut_au_mois=bool(cfg.get("assurance_inclut_au_mois")),
    )


async def get_suivis() -> SuivisConfig:
    """FAIL-SAFE : les défauts si la config n'existe pas encore."""
    from app.services.automation_state import get_automation_config

    return parse_suivis(await get_automation_config(SUIVIS_KEY))


async def set_suivis(
    db, cfg: SuivisConfig, *, user_id: int | None = None
) -> SuivisConfig:
    """Enregistre les 3 fenêtres (bornées 1..12). Ne commit pas."""
    from app.services.automation_state import set_automation_config

    clean = SuivisConfig(
        renouvellement_mois_avant=_clamp_mois(
            cfg.renouvellement_mois_avant, DEFAULT_RENOUVELLEMENT_MOIS_AVANT
        ),
        assurance_bascule_mois=_clamp_mois(
            cfg.assurance_bascule_mois, DEFAULT_ASSURANCE_BASCULE_MOIS
        ),
        releve31_bascule_mois=_clamp_mois(
            cfg.releve31_bascule_mois, DEFAULT_RELEVE31_BASCULE_MOIS
        ),
        assurance_inclut_au_mois=bool(cfg.assurance_inclut_au_mois),
    )
    await set_automation_config(
        db,
        SUIVIS_KEY,
        {
            "renouvellement_mois_avant": clean.renouvellement_mois_avant,
            "assurance_bascule_mois": clean.assurance_bascule_mois,
            "releve31_bascule_mois": clean.releve31_bascule_mois,
            "assurance_inclut_au_mois": clean.assurance_inclut_au_mois,
        },
        user_id=user_id,
    )
    return clean
