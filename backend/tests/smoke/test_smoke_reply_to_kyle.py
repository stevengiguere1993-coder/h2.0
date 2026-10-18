"""Smoke — adresse de réponse de Kyle posée au démarrage (2026-10-18).

Steven : « le courriel pour reply suite à l'envoi de courriel de Kyle
doit être kyle@gestionmagnifica.com ». Vérifie, sur la base SQLite des
smoke tests :
1. le profil d'expéditeur de Kyle (réglages Communications) reçoit la
   nouvelle adresse « Répondre à », les autres profils ne bougent pas, et
   le chemin d'envoi (``expediteur_defaut``) la voit ;
2. le marqueur applied_backfills est posé : un changement fait ensuite à
   la main n'est jamais réécrasé ;
3. sans profil de Kyle, rien n'est écrit et le marqueur n'est PAS posé
   (nouvel essai au prochain démarrage).
"""

from __future__ import annotations

from sqlalchemy import text

from app.services.automation_state import (
    get_automation_config,
    set_automation_config,
)
from app.services.locatif_expediteurs import (
    CLE_CORRECTION_REPLY_TO_KYLE,
    REGLAGES_COMMUNICATIONS,
    REPLY_TO_KYLE,
    corriger_reply_to_kyle_une_fois,
)

from .conftest import TestSessionLocal

PHIL = {
    "label": "Phil",
    "from_email": "info@immohorizon.com",
    "from_name": "Phil — Horizon",
    "reply_to": "phil@immohorizon.com",
}


async def _poser_config(cfg: dict) -> None:
    async with TestSessionLocal() as s:
        # Table créée par init_db en prod (absente du schéma de test).
        await s.execute(
            text(
                "CREATE TABLE IF NOT EXISTS applied_backfills ("
                "key VARCHAR(120) PRIMARY KEY, "
                "applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
            )
        )
        await s.execute(
            text("DELETE FROM applied_backfills WHERE key = :k"),
            {"k": CLE_CORRECTION_REPLY_TO_KYLE},
        )
        await set_automation_config(s, REGLAGES_COMMUNICATIONS, cfg)
        await s.commit()


async def _corriger() -> list[str]:
    async with TestSessionLocal() as s:
        return await corriger_reply_to_kyle_une_fois(s)


async def _marqueur_pose() -> bool:
    async with TestSessionLocal() as s:
        row = (
            await s.execute(
                text("SELECT 1 FROM applied_backfills WHERE key = :k"),
                {"k": CLE_CORRECTION_REPLY_TO_KYLE},
            )
        ).first()
        return row is not None


def _profil(label: str, cfg: dict) -> dict:
    return next(p for p in cfg["profils"] if p["label"] == label)


def test_profil_kyle_corrige_une_seule_fois(run, db_setup):
    run(
        _poser_config(
            {
                "from_email": "info@immohorizon.com",
                "from_name": "",
                "reply_to": "",
                "profils": [
                    {
                        "label": "Kyle",
                        "from_email": "info@immohorizon.com",
                        "from_name": "Kyle Brown - Gestion locative",
                        "reply_to": "kyle.gestion@gmail.com",
                    },
                    PHIL,
                ],
                "profil_defaut": "Kyle",
            }
        )
    )

    modifs = run(_corriger())
    assert modifs == [
        f"profil « Kyle » : kyle.gestion@gmail.com → {REPLY_TO_KYLE}"
    ]
    cfg = run(get_automation_config(REGLAGES_COMMUNICATIONS))
    assert _profil("Kyle", cfg)["reply_to"] == REPLY_TO_KYLE
    assert _profil("Kyle", cfg)["from_name"] == "Kyle Brown - Gestion locative"
    assert _profil("Phil", cfg) == PHIL
    assert cfg["profil_defaut"] == "Kyle"
    assert run(_marqueur_pose()) is True

    # Le chemin d'ENVOI (page Communications, avis, bail à signer…) lit
    # la même config : les réponses des locataires partent chez Kyle.
    from app.api.v1.endpoints.immobilier_communications import (
        expediteur_defaut,
    )

    from_email, from_name, reply_to = run(expediteur_defaut())
    assert (from_email, from_name) == (
        "info@immohorizon.com", "Kyle Brown - Gestion locative",
    )
    assert reply_to == REPLY_TO_KYLE

    # Un changement fait ensuite à la main est respecté (one-shot).
    async def _changer_a_la_main() -> None:
        async with TestSessionLocal() as s:
            cfg2 = await get_automation_config(REGLAGES_COMMUNICATIONS)
            _profil("Kyle", cfg2)["reply_to"] = "autre@exemple.com"
            await set_automation_config(s, REGLAGES_COMMUNICATIONS, cfg2)
            await s.commit()

    run(_changer_a_la_main())
    assert run(_corriger()) == []
    cfg3 = run(get_automation_config(REGLAGES_COMMUNICATIONS))
    assert _profil("Kyle", cfg3)["reply_to"] == "autre@exemple.com"


def test_sans_profil_kyle_rien_n_est_ecrit_ni_marque(run, db_setup):
    cfg_depart = {
        "from_email": "info@immohorizon.com",
        "from_name": "Horizon",
        "reply_to": "",
        "profils": [PHIL],
        "profil_defaut": "Phil",
    }
    run(_poser_config(cfg_depart))

    assert run(_corriger()) == []
    assert run(get_automation_config(REGLAGES_COMMUNICATIONS)) == cfg_depart
    # Pas de marqueur : le profil de Kyle n'existe pas encore, on
    # réessaiera au prochain démarrage.
    assert run(_marqueur_pose()) is False
