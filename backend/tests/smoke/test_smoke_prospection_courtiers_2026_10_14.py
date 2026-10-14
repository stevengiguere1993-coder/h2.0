"""Smoke — registre des courtiers (Prospection, Phil 2026-10-14).

- le scan construit le registre depuis les annonces Centris connues
  (≥ seuil, avec courtier) et les fiches d'analyse ; un même courtier vu
  deux fois = UNE ligne, coordonnées fusionnées ; second scan idempotent ;
- aperçu du courriel rendu avec sa plus grosse annonce ;
- envoi : journal + statut « contacté » + date de relance ; sans courriel
  → échec propre ; mode test ; mailer absent → échec propre ;
- fiche : PATCH, collision de nom 409, journal d'un appel entrant →
  « a répondu », export CSV, création manuelle, suppression ;
- paramètres : défauts, écriture, défaut appliqué au rendu ; employé → 403 ;
- unités : normalisation, séparation courriel/téléphone, parseur HTML,
  rendu du gabarit.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import pytest

from app.api.v1.endpoints import prospection_courtiers as ep
from app.services import prospection_courtiers as svc
from tests.smoke.conftest import TestSessionLocal

BASE = "/api/v1/prospection/courtiers"
URL_24 = "https://www.centris.ca/fr/immeuble~a-vendre~montreal/90000001"
URL_6 = "https://www.centris.ca/fr/immeuble~a-vendre~montreal/90000002"
IDS: dict = {}


class FakeMailer:
    ready = True

    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send(self, to, subject, html_body, **kw):
        self.sent.append(
            {
                "to": list(to),
                "subject": subject,
                "html": html_body,
                "reply_to": kw.get("reply_to"),
                "from_email": kw.get("from_email"),
                "from_name": kw.get("from_name"),
            }
        )


class MailerAbsent:
    ready = False

    async def send(self, *a, **kw):  # pragma: no cover
        raise AssertionError("ne doit pas être appelé")


@pytest.fixture()
def fake_mailer(monkeypatch) -> FakeMailer:
    fake = FakeMailer()
    monkeypatch.setattr("app.integrations.email_graph.get_mailer", lambda: fake)
    return fake


def _seed(run) -> None:
    from app.models.centris_listing import CentrisListing
    from app.models.lead_analysis import LeadAnalysis

    now = datetime.now(timezone.utc)

    async def _s():
        async with TestSessionLocal() as s:
            s.add(
                CentrisListing(
                    source_url=URL_24, mls_id="90000001",
                    category="immeuble_residentiel_6_plus",
                    address="1000 rue des Courtiers", city="Montréal",
                    price=5_000_000, nb_units=24,
                    broker_name="Jean Tremblay", broker_phone="514 555 1234",
                    first_seen_at=now - timedelta(days=3), last_seen_at=now,
                )
            )
            # Sous le seuil : ignorée.
            s.add(
                CentrisListing(
                    source_url=URL_6, mls_id="90000002",
                    category="immeuble_residentiel_6_plus",
                    address="6 rue Petite", city="Montréal", price=900_000,
                    nb_units=6, broker_name="Petit Courtier Smoke",
                    first_seen_at=now, last_seen_at=now,
                )
            )
            # Même courtier (double espace, pas d'accent) + courriel/tél.
            s.add(
                LeadAnalysis(
                    address="2000 rue Analyse", city="Laval",
                    asking_price=3_000_000, nb_logements=30,
                    courtier_nom="Jean  Tremblay",
                    courtier_contact="jean.tremblay@remax.ca / 438-555-9999",
                )
            )
            s.add(
                LeadAnalysis(
                    address="3000 rue Sans-Courriel", city="Longueuil",
                    asking_price=2_500_000, nb_logements=22,
                    courtier_nom="Marie Côté", courtier_contact="450 555 0000",
                )
            )
            # Nom « sale » tel que lu sur une fiche réelle : agence entre
            # parenthèses, titre en fin, téléphone impossible (055-…).
            s.add(
                LeadAnalysis(
                    address="4000 rue Gallico", city="Montréal",
                    asking_price=6_000_000, nb_logements=38,
                    courtier_nom="Denis Gallico Courtier (Immo Alliances)",
                    courtier_contact="055-685-6750",
                )
            )
            await s.commit()

    run(_s())


def _scan(client, h, vps: bool = False) -> dict:
    r = client.post(f"{BASE}/scan", headers=h, json={"vps": vps})
    assert r.status_code == 200, r.text
    job_id = r.json()["job_id"]
    etat = None
    for _ in range(200):
        j = client.get(f"{BASE}/scan/{job_id}", headers=h)
        assert j.status_code == 200, j.text
        etat = j.json()
        if etat["status"] != "en_cours":
            break
        time.sleep(0.05)
    assert etat and etat["status"] == "termine", etat
    assert "_task" not in etat and "duree_s" in etat
    return etat["resultat"]


def _un(client, h, q: str) -> dict:
    r = client.get(BASE, headers=h, params={"q": q})
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert len(items) == 1, items
    return items[0]


def test_scan_construit_le_registre(client, auth_headers, run, monkeypatch):
    monkeypatch.setattr(ep, "_session_factory_jobs", lambda: TestSessionLocal)
    _seed(run)
    rapport = _scan(client, auth_headers)
    assert rapport["seuil_logements"] == 20
    assert rapport["courtiers_crees"] >= 2
    assert rapport["annonces_centris_examinees"] >= 1
    assert rapport["analyses_examinees"] >= 2
    assert rapport["vps_utilise"] is False

    jean = _un(client, auth_headers, "Tremblay")
    IDS["jean"] = jean["id"]
    assert jean["nom"] == "Jean Tremblay"
    assert jean["courriel"] == "jean.tremblay@remax.ca"      # de la fiche
    assert jean["telephone"] == "514-555-1234"                # de l'annonce
    assert jean["nb_annonces"] == 2 and jean["nb_annonces_actives"] == 2
    assert jean["max_logements"] == 30
    assert jean["statut"] == "a_contacter"
    assert jean["source"] == "extension"

    marie = _un(client, auth_headers, "Côté")
    IDS["marie"] = marie["id"]
    assert marie["courriel"] is None
    assert marie["telephone"] == "450-555-0000"
    assert marie["nb_annonces"] == 1 and marie["max_logements"] == 22

    r = client.get(BASE, headers=auth_headers, params={"q": "Petit Courtier Smoke"})
    assert r.json()["total"] == 0  # sous le seuil

    denis = _un(client, auth_headers, "Gallico")
    assert denis["nom"] == "Denis Gallico"             # titre retiré
    assert denis["agence"] == "Immo Alliances"         # déduite des parenthèses
    assert denis["telephone"] is None                  # 055-… impossible

    # Idempotent : rien de créé, rien de dédoublé.
    rapport2 = _scan(client, auth_headers)
    assert rapport2["courtiers_crees"] == 0
    assert rapport2["courtiers_mis_a_jour"] >= 3
    assert _un(client, auth_headers, "Tremblay")["nb_annonces"] == 2

    # Statistiques et filtres.
    stats = client.get(BASE, headers=auth_headers).json()["stats"]
    assert stats["total"] >= 2 and stats["avec_courriel"] >= 1
    r = client.get(BASE, headers=auth_headers, params={"avec_courriel": "false", "q": "Côté"})
    assert r.json()["total"] == 1
    r = client.get(BASE, headers=auth_headers, params={"statut": "bidon"})
    assert r.status_code == 422


def test_apercu_et_envoi(client, auth_headers, fake_mailer):
    jean, marie = IDS["jean"], IDS["marie"]
    r = client.post(f"{BASE}/apercu", headers=auth_headers, json={"courtier_id": jean})
    assert r.status_code == 200, r.text
    a = r.json()
    assert a["exemple"] is False and a["to"] == "jean.tremblay@remax.ca"
    assert "20 logements" in a["sujet"]
    assert "Bonjour Jean" in a["corps_html"]
    assert "2000 rue Analyse" in a["corps_html"]          # plus grosse annonce
    assert "30 logements" in a["corps_html"]
    assert a["annonce"]["nb_units"] == 30

    r = client.post(
        f"{BASE}/envoyer", headers=auth_headers, json={"courtier_ids": [jean, marie, jean]}
    )
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["envoyes"] == 1 and res["test"] is False
    assert len(res["echecs"]) == 1 and res["echecs"][0]["id"] == marie
    assert "courriel" in res["echecs"][0]["erreur"].lower()
    assert len(fake_mailer.sent) == 1
    assert fake_mailer.sent[0]["to"] == ["jean.tremblay@remax.ca"]
    assert "20 logements" in fake_mailer.sent[0]["subject"]
    assert "2000 rue Analyse" in fake_mailer.sent[0]["html"]

    d = client.get(f"{BASE}/{jean}", headers=auth_headers).json()
    assert d["statut"] == "contacte"
    assert d["dernier_contact_le"] is not None
    attendu = (datetime.now(timezone.utc) + timedelta(days=14)).date().isoformat()
    assert d["prochaine_relance_le"] == attendu
    assert len(d["contacts"]) == 1
    assert d["contacts"][0]["canal"] == "courriel"
    assert d["contacts"][0]["direction"] == "sortant"
    assert "2000 rue Analyse" in (d["contacts"][0]["contenu"] or "")
    assert len(d["annonces"]) == 2

    # Mode test : rien n'est journalisé, sujet préfixé.
    r = client.post(
        f"{BASE}/envoyer", headers=auth_headers,
        json={"courtier_ids": [], "test_vers": "phil@example.com"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["test"] is True
    assert fake_mailer.sent[-1]["to"] == ["phil@example.com"]
    assert fake_mailer.sent[-1]["subject"].startswith("[TEST]")
    assert "Jean" in fake_mailer.sent[-1]["html"]
    assert len(client.get(f"{BASE}/{jean}", headers=auth_headers).json()["contacts"]) == 1

    # Garde-fous.
    assert client.post(f"{BASE}/envoyer", headers=auth_headers, json={"courtier_ids": []}).status_code == 400
    r = client.post(
        f"{BASE}/envoyer", headers=auth_headers, json={"courtier_ids": list(range(1, 60))}
    )
    assert r.status_code == 400


def test_envoi_sans_mailer(client, auth_headers, monkeypatch):
    monkeypatch.setattr("app.integrations.email_graph.get_mailer", lambda: MailerAbsent())
    r = client.post(f"{BASE}/envoyer", headers=auth_headers, json={"courtier_ids": [IDS["jean"]]})
    assert r.status_code == 200, r.text
    assert r.json()["envoyes"] == 0
    assert "non configur" in r.json()["echecs"][0]["erreur"]
    r = client.post(
        f"{BASE}/envoyer", headers=auth_headers,
        json={"courtier_ids": [], "test_vers": "phil@example.com"},
    )
    assert r.status_code == 502


def test_fiche_journal_et_statuts(client, auth_headers):
    jean, marie = IDS["jean"], IDS["marie"]
    r = client.patch(
        f"{BASE}/{marie}", headers=auth_headers,
        json={"courriel": " Marie.Cote@Sutton.com ", "statut": "contacte", "agence": "Sutton"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["courriel"] == "marie.cote@sutton.com"
    assert r.json()["statut"] == "contacte"
    assert client.patch(f"{BASE}/{jean}", headers=auth_headers, json={"nom": "Marie Côté"}).status_code == 409
    assert client.patch(f"{BASE}/{jean}", headers=auth_headers, json={"statut": "bidon"}).status_code == 422

    # Elle rappelle → « a répondu », relance effacée.
    r = client.post(
        f"{BASE}/{marie}/contacts", headers=auth_headers,
        json={"canal": "telephone", "direction": "entrant", "sujet": "Elle a rappelé"},
    )
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["statut"] == "repondu" and d["prochaine_relance_le"] is None
    assert d["contacts"][0]["sujet"] == "Elle a rappelé"
    assert d["nb_contacts"] == 1

    # Relance sortante de Jean (déjà contacté) → compteur de relances.
    r = client.post(
        f"{BASE}/{jean}/contacts", headers=auth_headers,
        json={"canal": "telephone", "direction": "sortant", "sujet": "Appel de suivi"},
    )
    assert r.status_code == 201, r.text
    assert r.json()["nb_relances"] == 1 and r.json()["statut"] == "contacte"
    assert r.json()["prochaine_relance_le"] is not None
    assert client.post(
        f"{BASE}/{jean}/contacts", headers=auth_headers, json={"canal": "fax"}
    ).status_code == 422

    # Export CSV.
    r = client.get(f"{BASE}/export.csv", headers=auth_headers)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    corps = r.content.decode("utf-8-sig")
    assert corps.splitlines()[0].startswith("Nom;Agence;Courriel")
    assert "Jean Tremblay" in corps and "jean.tremblay@remax.ca" in corps

    # Création manuelle : doublon refusé, puis fiche neuve supprimée.
    assert client.post(BASE, headers=auth_headers, json={"nom": "jean tremblay"}).status_code == 409
    r = client.post(
        BASE, headers=auth_headers,
        json={"nom": "Luc Nouveau", "agence": "Via Capitale", "courriel": "Luc@Via.ca"},
    )
    assert r.status_code == 201, r.text
    luc = r.json()
    assert luc["source"] == "manuel" and luc["courriel"] == "luc@via.ca"
    assert client.delete(f"{BASE}/{luc['id']}", headers=auth_headers).status_code == 204
    assert client.get(f"{BASE}/{luc['id']}", headers=auth_headers).status_code == 404
    assert client.get(f"{BASE}/999999", headers=auth_headers).status_code == 404


def test_parametres_et_acces(client, auth_headers, employee_headers):
    r = client.get(f"{BASE}/parametres", headers=auth_headers)
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["config"]["seuil_logements"] == 20
    assert p["config"]["relance_jours"] == 14
    assert p["defauts"]["sujet"] == svc.GABARIT_SUJET_DEFAUT
    assert any(v["cle"] == "prenom" for v in p["variables"])
    assert isinstance(p["mailer_pret"], bool)

    r = client.put(
        f"{BASE}/parametres", headers=auth_headers,
        json={"seuil_logements": 12, "sujet": "Acheteur {{seuil}}+ — {{agence}}"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["config"]["seuil_logements"] == 12
    r = client.post(f"{BASE}/apercu", headers=auth_headers, json={})
    assert r.status_code == 200
    assert r.json()["exemple"] is True
    assert r.json()["sujet"] == "Acheteur 12+ — RE/MAX Exemple"
    assert "1234, rue de l'Exemple" in r.json()["corps_html"]

    # Retour aux défauts (null = retirer la valeur).
    r = client.put(
        f"{BASE}/parametres", headers=auth_headers,
        json={"seuil_logements": 20, "sujet": None},
    )
    assert r.json()["config"]["sujet"] == svc.GABARIT_SUJET_DEFAUT
    assert r.json()["config"]["seuil_logements"] == 20

    # Un employé n'entre pas (données d'acquisition = gestionnaire).
    assert client.get(BASE, headers=employee_headers).status_code == 403
    assert client.put(
        f"{BASE}/parametres", headers=employee_headers, json={"seuil_logements": 5}
    ).status_code == 403


def test_url_tres_longue_rescannee_sans_doublon(run):
    """Bug prod 2026-10-14 : une URL de fiche > 500 car. était insérée
    tronquée au 1er scan puis non retrouvée au 2e → IntegrityError."""
    from app.models.prospection_courtier import ProspectionCourtierAnnonce
    from sqlalchemy import func, select

    url = "https://exemple.test/annonce?" + "x" * 600

    async def _deux_fois():
        async with TestSessionLocal() as s:
            c, _ = await svc.upsert_courtier(s, nom="Ursula Longurl", source="analyse")
            await svc.lier_annonce(s, c, source_url=url, nb_units=25)
            await svc.lier_annonce(s, c, source_url=url, nb_units=26)
            await s.flush()
            n = (
                await s.execute(
                    select(func.count()).select_from(ProspectionCourtierAnnonce).where(
                        ProspectionCourtierAnnonce.courtier_id == c.id
                    )
                )
            ).scalar_one()
            await s.rollback()
            return n

    assert run(_deux_fois()) == 1


def test_scan_tolere_une_fiche_cassee(run, monkeypatch):
    """Une fiche qui fait planter la liaison (ici lier_annonce lève) est
    notée dans le rapport ; les autres courtiers sont quand même créés."""
    original = svc.lier_annonce

    async def _casse(db, courtier, **kw):
        if "Gallico" in courtier.nom:
            raise RuntimeError("boum fiche")
        return await original(db, courtier, **kw)

    monkeypatch.setattr(svc, "lier_annonce", _casse)

    async def _scan():
        async with TestSessionLocal() as s:
            rapport = await svc.scan(s, config=dict(svc.DEFAUTS), utiliser_vps=False)
            await s.rollback()
            return rapport

    rapport = run(_scan())
    assert rapport["analyses_examinees"] >= 3
    assert any("Gallico" in e and "boum fiche" in e for e in rapport["erreurs"]), rapport["erreurs"]
    assert rapport["courtiers_mis_a_jour"] + rapport["courtiers_crees"] >= 2


def test_scan_vps_vide_explique_pourquoi(run, monkeypatch):
    """Le VPS répond 200 mais n'a lu aucune annonce (Centris bloque) : le
    rapport le dit, avec le diagnostic du VPS, sans planter le scan."""
    from app.integrations import scraping_proxy

    monkeypatch.setattr(scraping_proxy, "vps_available", lambda: True)

    async def _vide(**kw):
        assert kw["category"] == "immeuble_residentiel_6_plus"
        return {
            "listings": [],
            "diagnostic": {"title": "Just a moment...", "captcha": True, "page": 1},
        }

    monkeypatch.setattr(scraping_proxy, "scrape_centris_search_complet", _vide)

    async def _scan():
        async with TestSessionLocal() as s:
            rapport = await svc.scan(s, config=dict(svc.DEFAUTS), utiliser_vps=True)
            await s.rollback()
            return rapport

    rapport = run(_scan())
    assert rapport["vps_utilise"] is True
    assert rapport["vps_annonces_lues"] == 0
    assert rapport["vps_diagnostic"]["captcha"] is True
    assert any("captcha" in e for e in rapport["erreurs"]), rapport["erreurs"]

    # VPS non configuré : message explicite, pas d'exception.
    monkeypatch.setattr(scraping_proxy, "vps_available", lambda: False)
    rapport = run(_scan())
    assert rapport["vps_utilise"] is False
    assert any("non configur" in e for e in rapport["erreurs"])


def test_unites():
    assert svc.normaliser_cle("Jean  Tremblay, courtier immobilier résidentiel") == "jean tremblay"
    assert svc.normaliser_cle("Marie Côté") == svc.normaliser_cle("marie cote")
    assert svc.prenom_de("jean-francois roy") == "Jean-francois"
    assert svc.separer_contact("jean@remax.ca / 438-555-9999") == ("jean@remax.ca", "438-555-9999")
    assert svc.separer_contact("+1 (514) 555-1234") == (None, "514-555-1234")
    assert svc.separer_contact("noreply@centris.ca") == (None, None)
    assert svc.separer_contact("329-093-4500") == (None, None)   # central 093 impossible
    assert svc.separer_contact("251-144-6950") == (None, None)   # central 144 impossible
    assert svc.nettoyer_nom("François Courval Courtier") == ("François Courval", None)
    assert svc.nettoyer_nom("Amy Assaad courtier immobilier résidentiel") == ("Amy Assaad", None)
    assert svc.nettoyer_nom("Rosibel Martinez inc.") == ("Rosibel Martinez", None)
    assert svc.nettoyer_nom("Denis Gallico, Maxime Gerard (Immo Alliances)") == (
        "Denis Gallico, Maxime Gerard", "Immo Alliances"
    )
    assert svc.nettoyer_nom("Immeubles Gloria") == ("Immeubles Gloria", None)
    assert svc.nettoyer_nom("Marc-André Knot") == ("Marc-André Knot", None)
    assert svc.rendre("{{prenom}} {{inconnu}}!", {"prenom": "Jean"}) == "Jean !"

    html = """
    <html><body><div class="listing"><h1>Immeuble à revenus</h1></div>
    <div class="broker-info">
      <h2 class="broker-info__name">Marc Lavoie</h2>
      <p>Courtier immobilier agréé</p>
      <p>RE/MAX du Cartier</p>
      <a href="tel:5145551212">514 555-1212</a>
      <a href="mailto:marc@remax-cartier.ca">marc@remax-cartier.ca</a>
    </div></body></html>"""
    info = svc.parser_courtier_html(html)
    assert info["nom"] == "Marc Lavoie"
    assert info["agence"] == "RE/MAX du Cartier"
    assert info["telephone"] == "514-555-1212"
    assert info["courriel"] == "marc@remax-cartier.ca"
    assert svc.parser_courtier_html("", "X")["nom"] == "X"
    assert svc.parser_courtier_html("<p>rien</p>")["nom"] is None
