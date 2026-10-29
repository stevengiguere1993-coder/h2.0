"""GPS refusé → position approximative par adresse internet (Steven,
2026-10-29) : adresses privées ignorées, cache par adresse, aucun échec
ne bloque le punch."""

from types import SimpleNamespace

import pytest

from app.integrations import ip_geo
from app.services.punch_geo import (
    approximative,
    ip_client,
    normaliser,
    position_ou_approx,
)


@pytest.fixture(autouse=True)
def _cache_vide():
    ip_geo.vider_cache()
    yield
    ip_geo.vider_cache()


def _requete(xff=None, host=None):
    headers = {"x-forwarded-for": xff} if xff else {}
    client = SimpleNamespace(host=host) if host else None
    return SimpleNamespace(headers=headers, client=client)


def test_ip_publique_filtre_le_local_et_l_invalide():
    assert ip_geo.ip_publique("8.8.8.8") == "8.8.8.8"
    assert ip_geo.ip_publique(" 8.8.8.8 ") == "8.8.8.8"
    assert ip_geo.ip_publique("127.0.0.1") is None
    assert ip_geo.ip_publique("10.0.0.5") is None
    assert ip_geo.ip_publique("192.168.1.20") is None
    assert ip_geo.ip_publique("testclient") is None
    assert ip_geo.ip_publique(None) is None


def test_ip_client_prend_le_premier_x_forwarded_for():
    assert ip_client(_requete(xff="24.1.2.3, 10.0.0.1")) == "24.1.2.3"
    assert ip_client(_requete(host="24.1.2.3")) == "24.1.2.3"
    assert ip_client(_requete()) is None
    assert ip_client(None) is None


def test_approximative_et_refus_du_prefixe_venant_de_l_app():
    assert approximative(45.5016889, -73.567256) == "~45.501689,-73.567256"
    assert approximative(None, 1.0) is None
    # L'app ne peut pas se déclarer « approximative » elle-même.
    assert normaliser("~45.5,-73.5") is None


@pytest.mark.asyncio
async def test_position_par_ip_cache_et_tolere_les_pannes(monkeypatch):
    appels = []

    async def faux(ip):
        appels.append(ip)
        return (45.5, -73.6)

    monkeypatch.setattr(ip_geo, "_interroger", faux)
    assert await ip_geo.position_par_ip("24.1.2.3") == (45.5, -73.6)
    assert await ip_geo.position_par_ip("24.1.2.3") == (45.5, -73.6)
    assert appels == ["24.1.2.3"]  # une seule requête réseau
    assert await ip_geo.position_par_ip("127.0.0.1") is None
    assert appels == ["24.1.2.3"]

    async def panne(ip):
        raise RuntimeError("réseau")

    ip_geo.vider_cache()
    monkeypatch.setattr(ip_geo, "_interroger", panne)
    assert await ip_geo.position_par_ip("24.1.2.4") is None


@pytest.mark.asyncio
async def test_position_ou_approx(monkeypatch):
    async def faux(ip):
        return (45.5, -73.6)

    monkeypatch.setattr(ip_geo, "_interroger", faux)
    req = _requete(xff="24.1.2.3")
    # GPS reçu : on le garde tel quel.
    assert await position_ou_approx("45.1,-73.1", req) == "45.1,-73.1"
    # GPS refusé : approximation marquée.
    assert await position_ou_approx(None, req) == "~45.500000,-73.600000"
    # Adresse privée (tests, réseau local) : rien.
    assert await position_ou_approx(None, _requete(host="testclient")) is None
