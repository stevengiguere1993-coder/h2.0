"""Adresse de réponse des courriels de Kyle (Steven, 2026-10-18).

Tests PURS (aucune base) de ``corriger_reply_to_kyle`` : tout profil
d'expéditeur qui désigne Kyle reçoit kyle@gestionmagnifica.com en
« Répondre à » ; les autres profils ne bougent pas.
"""

from __future__ import annotations

import copy

from app.services.locatif_expediteurs import (
    REPLY_TO_KYLE,
    corriger_reply_to_kyle,
    profil_est_kyle,
)

PHIL = {
    "label": "Phil",
    "from_email": "info@immohorizon.com",
    "from_name": "Phil — Horizon",
    "reply_to": "phil@immohorizon.com",
}


def _cfg(*profils: dict, **plats) -> dict:
    cfg = {
        "from_email": "info@immohorizon.com",
        "from_name": "",
        "reply_to": "",
        "profils": [copy.deepcopy(p) for p in profils],
        "profil_defaut": profils[0]["label"] if profils else "",
    }
    cfg.update(plats)
    return cfg


def _profil(label: str, cfg: dict) -> dict:
    return next(p for p in cfg["profils"] if p["label"] == label)


def test_profil_est_kyle_par_nom_nom_affiche_boite_ou_reponse():
    assert profil_est_kyle({"label": "Kyle"})
    assert profil_est_kyle({"label": "Gestion locative",
                            "from_name": "Kyle Brown - Gestion locative"})
    assert profil_est_kyle({"label": "Externe",
                            "reply_to": "kyle.gestion@gmail.com"})
    assert profil_est_kyle({"label": "Boîte", "from_email": "KYLE@immohorizon.com"})
    assert not profil_est_kyle(PHIL)
    assert not profil_est_kyle({})


def test_profil_kyle_corrige_les_autres_intacts():
    kyle = {
        "label": "Kyle",
        "from_email": "info@immohorizon.com",
        "from_name": "Kyle — Gestion Horizon",
        "reply_to": "kyle.gestion@gmail.com",
    }
    cfg = _cfg(kyle, PHIL)
    original = copy.deepcopy(cfg)

    res = corriger_reply_to_kyle(cfg)

    assert res.kyle_trouve is True
    assert _profil("Kyle", res.config)["reply_to"] == REPLY_TO_KYLE
    # Le reste du profil et le profil de Phil sont inchangés.
    assert _profil("Kyle", res.config)["from_name"] == "Kyle — Gestion Horizon"
    assert _profil("Phil", res.config) == PHIL
    assert res.config["profil_defaut"] == "Kyle"
    assert res.modifications == [
        f"profil « Kyle » : kyle.gestion@gmail.com → {REPLY_TO_KYLE}"
    ]
    # Fonction pure : la config d'entrée n'a pas bougé.
    assert cfg == original


def test_profil_kyle_reconnu_par_nom_affiche_ou_adresse_de_reponse():
    par_nom = {"label": "Gestion locative", "from_email": "info@immohorizon.com",
               "from_name": "Kyle Brown - Gestion locative", "reply_to": ""}
    par_reponse = {"label": "Externe", "from_email": "info@immohorizon.com",
                   "from_name": "", "reply_to": "kyle.gestion@gmail.com"}
    res = corriger_reply_to_kyle(_cfg(par_nom, par_reponse, PHIL))
    assert res.kyle_trouve is True
    assert _profil("Gestion locative", res.config)["reply_to"] == REPLY_TO_KYLE
    assert _profil("Externe", res.config)["reply_to"] == REPLY_TO_KYLE
    assert _profil("Phil", res.config)["reply_to"] == "phil@immohorizon.com"
    assert len(res.modifications) == 2
    assert "(vide)" in res.modifications[0]


def test_deja_correct_rien_a_modifier():
    kyle = {"label": "Kyle", "from_email": "info@immohorizon.com",
            "from_name": "Kyle", "reply_to": " Kyle@GestionMagnifica.com "}
    cfg = _cfg(kyle)
    res = corriger_reply_to_kyle(cfg)
    assert res.kyle_trouve is True
    assert res.modifications == []
    assert res.config == cfg


def test_aucun_profil_kyle_rien_trouve():
    cfg = _cfg(PHIL)
    res = corriger_reply_to_kyle(cfg)
    assert res.kyle_trouve is False
    assert res.modifications == []
    assert res.config == cfg
    assert corriger_reply_to_kyle({}) == ({}, [], False)
    assert corriger_reply_to_kyle({"profils": ["corrompu", None]}).kyle_trouve is False


def test_defauts_plats_corriges_seulement_s_ils_designent_kyle():
    # Défauts plats au nom de Kyle (envoi sans profil) → corrigés.
    res = corriger_reply_to_kyle(
        _cfg(from_name="Kyle — Gestion Horizon", reply_to="")
    )
    assert res.kyle_trouve is True
    assert res.config["reply_to"] == REPLY_TO_KYLE
    assert res.modifications == [f"défauts d'envoi : (vide) → {REPLY_TO_KYLE}"]
    # Défauts plats de l'équipe (boîte info@) → jamais touchés.
    res2 = corriger_reply_to_kyle(_cfg(PHIL, from_name="Horizon", reply_to=""))
    assert res2.kyle_trouve is False
    assert res2.config["reply_to"] == ""
