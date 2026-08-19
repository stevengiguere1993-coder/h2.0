"""Garde-fou : AUCUN courriel au locataire ne contourne la porte unique.

L'audit 2026-08-17 a montré que six chemins d'envoi coexistaient et que
quatre d'entre eux oubliaient le profil d'expéditeur et/ou la trace. Le
correctif (``app.services.locatif_mail.envoyer_au_locataire``) ne tient
que si personne ne rouvre une porte de service : ce test échoue dès
qu'un appel direct au mailer réapparaît dans le pôle locatif.

Si un nouveau chemin a VRAIMENT besoin d'un envoi direct, il faut
l'ajouter sciemment à ``AUTORISES`` — et alors reproduire à la main le
profil d'expéditeur ET les deux traces.
"""

from __future__ import annotations

import re
from pathlib import Path

APP = Path(__file__).resolve().parents[2] / "app"

# Portée : tout ce qui parle au locataire.
CIBLES = [
    *(APP / "api" / "v1" / "endpoints").glob("immobilier*.py"),
    APP / "api" / "v1" / "endpoints" / "public_bail.py",
    APP / "api" / "v1" / "endpoints" / "public_document.py",
    *(APP / "services").glob("bail_*.py"),
    *(APP / "services").glob("locatif_*.py"),
]

AUTORISES = {
    # La porte elle-même.
    "locatif_mail.py",
    # Implémentation de référence (profil + double trace en propre).
    "immobilier_communications.py",
    # Demande de preuve d'assurance : profil + double trace en propre,
    # antérieure à la porte unique et vérifiée conforme.
    "immobilier_assurances.py",
}

APPEL_DIRECT = re.compile(r"\bmailer(?:\(\))?\.send\s*\(|get_mailer\(\)\.send\s*\(")


def test_aucun_envoi_direct_hors_porte_unique() -> None:
    coupables: list[str] = []
    for f in CIBLES:
        if not f.exists() or f.name in AUTORISES:
            continue
        for no, ligne in enumerate(
            f.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if APPEL_DIRECT.search(ligne):
                coupables.append(f"{f.name}:{no}")
    assert not coupables, (
        "Envoi direct au mailer détecté hors de la porte unique "
        f"({', '.join(coupables)}). Utilise "
        "app.services.locatif_mail.envoyer_au_locataire — sinon le "
        "locataire reçoit le mauvais expéditeur et l'envoi ne laisse "
        "aucune trace sur sa fiche."
    )


def test_les_chemins_connus_importent_bien_la_porte() -> None:
    """Les chemins recensés par l'audit doivent référencer la porte —
    garde contre un revert silencieux."""
    attendus = {
        "api/v1/endpoints/immobilier.py",          # DPA + relance de loyer
        "api/v1/endpoints/immobilier_documents.py",  # signature + courriel
        "api/v1/endpoints/public_document.py",     # copie signée
        "services/bail_sign.py",                   # bail à signer
        "services/bail_renouvellement.py",         # avis de renouvellement
    }
    manquants = [
        rel
        for rel in sorted(attendus)
        if "envoyer_au_locataire" not in (APP / rel).read_text(encoding="utf-8")
    ]
    assert not manquants, (
        "Ces chemins n'appellent plus la porte unique : "
        f"{', '.join(manquants)}"
    )
