"""Smoke — règles de l'avis d'augmentation (2026-07-30).

Arrondi du nouveau loyer au dollar SUPÉRIEUR, période reconduite selon
l'art. 1941 C.c.Q. (12 mois → même jour un an plus tard), PDF TAL-806
qui coche TOUJOURS la 1re case (« sera augmenté à »), et suppression
liée avis ↔ document / relevé 31.
"""
from __future__ import annotations

from datetime import date


def test_arrondir_loyer_dollar_superieur():
    from app.services.bail_renouvellement import arrondir_loyer

    assert arrondir_loyer(1044.26) == 1045.0
    assert arrondir_loyer(1044.01) == 1045.0
    assert arrondir_loyer(1050.0) == 1050.0  # déjà rond : inchangé
    # 1000 × 1.03 = 1030.0 exactement — pas de dérive flottante.
    assert arrondir_loyer(1000 * 1.03) == 1030.0


def test_fin_reconduite_regle_12_mois():
    from app.services.bail_renouvellement import fin_reconduite

    # Bail annuel classique 1er juillet → 30 juin : reconduit au même
    # jour un an plus tard (plus de dérive en jours).
    assert fin_reconduite(date(2026, 7, 1), date(2027, 6, 30)) == date(
        2028, 6, 30
    )
    # Bail annuel NON aligné sur juillet : suit le bail.
    assert fin_reconduite(date(2026, 3, 15), date(2027, 3, 14)) == date(
        2028, 3, 14
    )
    # Bail court (6 mois) : reconduit pour la même durée.
    assert fin_reconduite(date(2026, 1, 1), date(2026, 6, 30)) == date(
        2026, 12, 28
    )
    # 29 février : replié sur le 28.
    assert fin_reconduite(date(2027, 3, 1), date(2028, 2, 29)) == date(
        2029, 2, 28
    )


def test_pdf_toujours_case_nouveau_loyer():
    """Le mapper TAL-806 coche la case 1 (« sera augmenté à ») quand le
    mode est nouveau_loyer — c'est le seul mode que l'app envoie
    désormais, la hausse %/$ étant convertie en amont."""
    from app.services.tal_forms import TalContext
    from app.services.tal_officiel import _map_avis_modification

    ctx = TalContext(
        locataire_nom="Philippe Meuser",
        bail_loyer_mensuel=1400.0,
        modif_mode="nouveau_loyer",
        nouveau_loyer=1445.0,
        nouvelle_date_debut=date(2027, 7, 1),
        nouvelle_date_fin=date(2028, 6, 30),
    )
    text, boxes = _map_avis_modification(ctx)
    assert boxes == ["Montant-1"]  # 1re case, jamais les hausses
    assert "sera augmenté à" in text
    assert "Indiquer le nouveau loyer" in text


def test_fenetre_reconduit_regles():
    """Un cycle « reconduit » n'est pas un avis envoyé : loin de la
    fin, la ligne est « reconduit » (verte) ; quand la fenêtre du
    prochain cycle s'ouvre, le suivi normal reprend."""
    from app.services.locatif_suivis import SuivisConfig

    cfg = SuivisConfig()
    # Loin de la fin (delta 700 j), reconduit → hors_fenetre à la base,
    # l'overview le transforme en « reconduit ».
    assert cfg.fenetre_renouvellement(700, avis_envoye=False) == (
        "hors_fenetre"
    )
    # Fenêtre rouverte (delta 120 j) : le suivi reprend (« à envoyer »).
    assert cfg.fenetre_renouvellement(120, avis_envoye=False) in (
        "a_envoyer",
        "imminente",
    )


def test_suppression_liee_endpoints(client, auth_headers):
    """Les suppressions liées répondent proprement (pas de 500) même
    sur des cibles inexistantes."""
    r = client.delete(
        "/api/v1/immobilier/renouvellements/999999",
        headers=auth_headers,
    )
    assert r.status_code == 404, r.text
    # Relevé 31 jamais suivi : le DELETE est idempotent (déjà
    # « à produire ») → 204.
    r2 = client.delete(
        "/api/v1/immobilier/releves31/2025/999999",
        headers=auth_headers,
    )
    assert r2.status_code == 204, r2.text
