"""Classe QB d'un achat poussé depuis Kratos = « Construction », jamais
l'adresse du chantier (Steven 2026-10-16 : « en envoyant un reçu de
Kratos vers QB on continue de mettre Client : Projet, mais en classe on
doit mettre Construction »). Cette classe de volet ne désigne aucun
projet à l'import QB → Kratos."""

import asyncio

from app.core.config import settings
from app.integrations.quickbooks import QuickBooksError
from app.services import achat_qbo
from app.services.qbo_cost_pull import _classe_generique


class _QboFaux:
    def __init__(self, classes=None, erreur=None):
        self.classes = classes or {}
        self.erreur = erreur
        self.demandes = []

    async def ensure_class(self, *, name):
        self.demandes.append(name)
        if self.erreur:
            raise self.erreur
        return self.classes.get(name)


def test_classe_construction_demandee(monkeypatch):
    monkeypatch.setattr(settings, "qbo_achat_class_name", "Construction")
    qbo = _QboFaux(
        classes={"Construction": {"Id": "77", "Name": "Construction"}}
    )
    assert asyncio.run(achat_qbo._classe_achats_id(qbo, 467)) == "77"
    # Jamais l'adresse du chantier : une seule classe demandée, la bonne.
    assert qbo.demandes == ["Construction"]


def test_reglage_vide_aucune_classe(monkeypatch):
    monkeypatch.setattr(settings, "qbo_achat_class_name", "")
    qbo = _QboFaux()
    assert asyncio.run(achat_qbo._classe_achats_id(qbo, 1)) is None
    assert qbo.demandes == []


def test_suivi_des_classes_desactive(monkeypatch):
    """ensure_class rend None quand la compagnie ne suit pas les classes."""
    monkeypatch.setattr(settings, "qbo_achat_class_name", "Construction")
    assert asyncio.run(achat_qbo._classe_achats_id(_QboFaux(), 1)) is None


def test_refus_qb_n_empeche_pas_l_envoi(monkeypatch):
    monkeypatch.setattr(settings, "qbo_achat_class_name", "Construction")
    qbo = _QboFaux(erreur=QuickBooksError("boom"))
    assert asyncio.run(achat_qbo._classe_achats_id(qbo, 1)) is None


def test_classe_de_volet_ne_designe_aucun_projet(monkeypatch):
    monkeypatch.setattr(settings, "qbo_achat_class_name", "Construction")
    monkeypatch.setattr(settings, "qbo_shop_class_name", "Construction")
    monkeypatch.setattr(settings, "qbo_recus_class_name", "Kratos")
    assert _classe_generique("Construction") is True
    assert _classe_generique("construction") is True
    assert _classe_generique("Kratos") is True
    assert _classe_generique("158 Rue Maurice, Saint-Rémi") is False
    assert _classe_generique("Construction garage") is False
    assert _classe_generique("") is False
