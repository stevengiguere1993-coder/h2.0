"""Smoke — retours de Steven du 2026-11-13 (paiements de loyer) :

- point 10 : périodes de prix de loyer — changer le prix à partir d'un
  mois ne touche ni le dû ni le solde des mois passés ;
- point 13 : les mois impayés antérieurs sont détaillés sur la ligne du
  mois courant, et leur somme = le solde ;
- point 17 : un trop-payé éponge d'abord les mois ANTÉRIEURS impayés
  avant d'avancer sur les mois à venir ;
- point 14 : confirmation de paiement envoyée la nuit suivante (courriel,
  sinon rien hors production), une seule fois, à l'état final du jour.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models.immobilier import Bail, Immeuble, Locataire, Logement, PaiementLoyer
from app.services import loyer_confirmations as lc
from app.services import loyer_periodes as lp

from tests.smoke.conftest import TestSessionLocal


def _mois(d: date, delta: int) -> date:
    m = d.month - 1 + delta
    return date(d.year + m // 12, m % 12 + 1, 1)


def _seed(run, *, nom: str, email: str | None = None, phone: str | None = None) -> dict:
    async def _s() -> dict:
        async with TestSessionLocal() as s:
            imm = Immeuble(name=nom, address=f"1 rue {nom}", is_active=True)
            s.add(imm)
            await s.flush()
            lg = Logement(immeuble_id=imm.id, numero="1", status="vacant")
            loc = Locataire(full_name=f"Locataire {nom}", email=email, phone=phone)
            s.add_all([lg, loc])
            await s.commit()
            return {"immeuble_id": imm.id, "logement_id": lg.id, "locataire_id": loc.id}

    return run(_s())


def _bail(client, headers, seed, *, debut: date, loyer: float, **extra) -> dict:
    body = {
        "logement_id": seed["logement_id"], "locataire_id": seed["locataire_id"],
        "date_debut": debut.isoformat(), "date_fin": _mois(debut, 12).isoformat(),
        "loyer_mensuel": loyer, "status": "actif", "jour_echeance": 1, **extra,
    }
    r = client.post("/api/v1/immobilier/baux", headers=headers, json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _row(client, headers, bail_id: int, mois: date) -> dict:
    r = client.get(f"/api/v1/immobilier/loyers/overview?mois={mois.strftime('%Y-%m')}", headers=headers)
    assert r.status_code == 200, r.text
    return next(x for x in r.json()["rows"] if x["bail_id"] == bail_id)


def _payer(client, headers, bail_id: int, mois: date, montant: float, paye_le: date) -> dict:
    r = client.post("/api/v1/immobilier/paiements", headers=headers, json={
        "bail_id": bail_id, "mois_couvert": mois.isoformat(), "montant": montant,
        "paye_le": paye_le.isoformat(),
    })
    assert r.status_code in (200, 201), r.text
    return r.json()


# ── Périodes de loyer (unitaire) ──────────────────────────────────────


class _B:
    def __init__(self, debut: date, loyer: float):
        self.date_debut = debut
        self.loyer_mensuel = loyer
        self.loyer_periodes_json = None


def test_periodes_unitaire():
    b = _B(date(2026, 7, 1), 470)
    assert lp.loyer_du_mois(b, date(2026, 8, 15)) == 470
    assert lp.loyers_entre(b, date(2026, 7, 1), date(2026, 9, 1)) == 1410
    lp.ajouter_periode(b, date(2026, 11, 1), 500, today=date(2026, 11, 13))
    assert b.loyer_mensuel == 500
    assert lp.loyer_du_mois(b, date(2026, 10, 1)) == 470
    assert lp.loyer_du_mois(b, date(2026, 11, 1)) == 500
    assert lp.loyers_entre(b, date(2026, 7, 1), date(2026, 11, 1)) == 4 * 470 + 500
    # Changement FUTUR : le loyer en vigueur ne bouge pas avant sa date.
    lp.ajouter_periode(b, date(2027, 1, 1), 520, today=date(2026, 11, 13))
    assert b.loyer_mensuel == 500
    assert lp.synchroniser_loyer_courant(b, date(2027, 1, 2)) is True and b.loyer_mensuel == 520
    lp.synchroniser_loyer_courant(b, date(2026, 11, 13))
    # Retrait : le mois reprend le prix précédent ; la 1re période reste.
    lp.retirer_periode(b, date(2027, 1, 1), today=date(2026, 11, 13))
    assert [v for _d, v in lp.lire_periodes(b)] == [470, 500]
    with pytest.raises(ValueError):
        lp.retirer_periode(b, date(2026, 7, 1), today=date(2026, 11, 13))
    lp.retirer_periode(b, date(2026, 11, 1), today=date(2026, 11, 13))
    assert b.loyer_periodes_json is None and b.loyer_mensuel == 470
    # Daté du début du bail = correction du prix de départ, sans période.
    lp.ajouter_periode(b, date(2026, 7, 1), 480, today=date(2026, 11, 13))
    assert b.loyer_periodes_json is None and b.loyer_mensuel == 480
    # JSON illisible : jamais d'exception, on retombe sur le loyer du bail.
    b.loyer_periodes_json = "{pas du json"
    assert lp.loyer_du_mois(b, date(2026, 9, 1)) == 480


# ── Périodes de loyer (API) : le passé ne bouge pas ───────────────────


def test_changement_de_prix_ne_touche_pas_le_passe(client, auth_headers, run):
    seed = _seed(run, nom="Periodes")
    m0 = date.today().replace(day=1)
    m_2, m_1 = _mois(m0, -2), _mois(m0, -1)
    bid = _bail(client, auth_headers, seed, debut=m_2, loyer=470, au_mois=True)["id"]
    # Les deux mois passés payés au prix d'alors.
    _payer(client, auth_headers, bid, m_2, 470, m_2)
    _payer(client, auth_headers, bid, m_1, 470, m_1)
    assert _row(client, auth_headers, bid, m0)["solde_total"] == 470.0

    r = client.post(f"/api/v1/immobilier/baux/{bid}/loyer-periodes", headers=auth_headers,
                    json={"depuis": m0.strftime("%Y-%m"), "loyer": 500})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["loyer_mensuel"] == 500.0
    assert [(p["depuis"], p["loyer"], p["courante"]) for p in out["periodes"]] == [
        (m_2.isoformat(), 470.0, False), (m0.isoformat(), 500.0, True),
    ]
    # Mois courant : 500 dû. Mois passés : toujours 470, donc payés.
    row = _row(client, auth_headers, bid, m0)
    assert row["loyer_mensuel"] == 500.0 and row["solde_total"] == 500.0
    assert row["loyer_a_periodes"] is True
    assert [(x["mois"], x["restant"]) for x in row["mois_impayes"]] == [(m0.isoformat(), 500.0)]
    passe = _row(client, auth_headers, bid, m_1)
    assert passe["loyer_mensuel"] == 470.0 and passe["etat"] == "paye" and passe["solde_total"] == 0.0
    # « Marquer payé » du mois courant vise 500, pas 470.
    _payer(client, auth_headers, bid, m0, 500, m0)
    assert _row(client, auth_headers, bid, m0)["etat"] == "paye"
    # Le bail affiche le loyer en vigueur ; le logement suit.
    assert client.get(f"/api/v1/immobilier/baux/{bid}/loyer-periodes",
                      headers=auth_headers).json()["loyer_mensuel"] == 500.0
    r = client.get(f"/api/v1/immobilier/baux/{bid}", headers=auth_headers)
    assert r.status_code == 200 and r.json()["loyer_mensuel"] == 500.0
    assert client.get("/api/v1/immobilier/baux/echeances", headers=auth_headers).status_code == 200
    assert client.get("/api/v1/immobilier/baux/sans-document", headers=auth_headers).status_code == 200

    # Retirer la période : tout revient à 470 (30 $ de trop-perçu, solde 0).
    r = client.delete(f"/api/v1/immobilier/baux/{bid}/loyer-periodes?depuis={m0.strftime('%Y-%m')}",
                      headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["loyer_mensuel"] == 470.0 and len(r.json()["periodes"]) == 1
    r = client.delete(f"/api/v1/immobilier/baux/{bid}/loyer-periodes?depuis={m_2.strftime('%Y-%m')}",
                      headers=auth_headers)
    assert r.status_code == 400


# ── Mois impayés antérieurs + arriérés d'abord ────────────────────────


def test_mois_impayes_detailles_et_arrieres_dabord(client, auth_headers, run):
    seed = _seed(run, nom="Arrieres")
    m0 = date.today().replace(day=1)
    m_3, m_2, m_1 = _mois(m0, -3), _mois(m0, -2), _mois(m0, -1)
    bid = _bail(client, auth_headers, seed, debut=m_3, loyer=800)["id"]
    _payer(client, auth_headers, bid, m_2, 800, m_2)   # m-3 et m-1 restent dus
    row = _row(client, auth_headers, bid, m0)
    assert row["solde_total"] == 2400.0
    assert [(x["mois"], x["du"], x["recu"], x["restant"]) for x in row["mois_impayes"]] == [
        (m_3.isoformat(), 800.0, 0.0, 800.0),
        (m_1.isoformat(), 800.0, 0.0, 800.0),
        (m0.isoformat(), 800.0, 0.0, 800.0),
    ]
    assert round(sum(x["restant"] for x in row["mois_impayes"]), 2) == row["solde_total"]

    # 1 800 $ saisis sur le mois courant : 800 pour ce mois, puis le
    # surplus va aux mois PASSÉS (le plus ancien d'abord) — plus aucun
    # mois à venir marqué « payé » pendant qu'un vieux mois traîne.
    _payer(client, auth_headers, bid, m0, 1800, date.today())

    async def _lignes():
        async with TestSessionLocal() as s:
            rows = (await s.execute(
                select(PaiementLoyer.mois_couvert, PaiementLoyer.montant)
                .where(PaiementLoyer.bail_id == bid).order_by(PaiementLoyer.mois_couvert)
            )).all()
            return [(m, float(v)) for m, v in rows]

    assert run(_lignes()) == [(m_3, 800.0), (m_2, 800.0), (m_1, 200.0), (m0, 800.0)]
    row = _row(client, auth_headers, bid, m0)
    assert row["solde_total"] == 600.0 and row["solde_anterieur"] is True
    assert [(x["mois"], x["recu"], x["restant"]) for x in row["mois_impayes"]] == [
        (m_1.isoformat(), 200.0, 600.0),
    ]
    # Tout est à jour : le vrai paiement d'avance avance encore.
    _payer(client, auth_headers, bid, m0, 600 + 800, date.today())
    assert run(_lignes())[-1] == (_mois(m0, 1), 800.0)
    assert _row(client, auth_headers, bid, m0)["mois_impayes"] == []


# ── Confirmation de paiement, la nuit ─────────────────────────────────


class FakeMailer:
    ready = True
    sender = "systeme@test.local"

    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send(self, to, subject, html_body, **kw):
        self.sent.append({"to": list(to), "subject": subject, "html": html_body})


def test_textes_confirmation():
    class P:
        def __init__(self, montant, paye_le, mois):
            self.montant, self.paye_le, self.mois_couvert = montant, paye_le, mois

    v = [P(465, date(2026, 11, 1), date(2026, 11, 1)), P(465, date(2026, 11, 12), date(2026, 11, 1))]
    assert lc.sujet(v) == "Confirmation de paiement — loyer de novembre 2026"
    html = lc.corps_html("Thérèse <b>", "9085 Millen, log. 2", v)
    assert "Thérèse &lt;b&gt;" in html and "reçu le 1er novembre 2026" in html
    assert "Total reçu" in html and "930,00" in html and "$930.00 (November 2026)" in html
    sms = lc.corps_sms("9085 Millen, log. 2", v)
    assert "930,00 $ pour novembre 2026 (9085 Millen, log. 2)" in sms
    assert lc.est_du(datetime(2026, 11, 14, 2, 5, tzinfo=lc.FUSEAU), 2) is True
    assert lc.est_du(datetime(2026, 11, 14, 1, 59, tzinfo=lc.FUSEAU), 2) is False
    assert lc.est_du(datetime(2026, 11, 14, 14, 0, tzinfo=lc.FUSEAU), 2) is False


def test_confirmation_de_nuit(client, auth_headers, run, monkeypatch):
    fake = FakeMailer()
    monkeypatch.setattr("app.integrations.email_graph.get_mailer", lambda: fake)
    monkeypatch.setattr(lc, "ACTIF_DEPUIS", date(2020, 1, 1))
    avec = _seed(run, nom="ConfCourriel", email="locataire.conf@exemple.ca")
    sans = _seed(run, nom="ConfSans")
    m0 = date.today().replace(day=1)
    b1 = _bail(client, auth_headers, avec, debut=_mois(m0, -1), loyer=930)["id"]
    b2 = _bail(client, auth_headers, sans, debut=_mois(m0, -1), loyer=600)["id"]
    _payer(client, auth_headers, b1, _mois(m0, -1), 930, date.today())
    p_a = _payer(client, auth_headers, b1, m0, 465, date.today())
    p_b = _payer(client, auth_headers, b1, m0, 400, date.today())
    p_suppr = _payer(client, auth_headers, b1, m0, 65, date.today())
    _payer(client, auth_headers, b2, _mois(m0, -1), 600, date.today())
    # Corrections « dans la journée » : 400 → 465, et un versement retiré.
    assert client.patch(f"/api/v1/immobilier/paiements/{p_b['id']}", headers=auth_headers,
                        json={"montant": 465}).status_code == 200
    assert client.delete(f"/api/v1/immobilier/paiements/{p_suppr['id']}",
                         headers=auth_headers).status_code == 204

    async def _nuit(now_local):
        async with TestSessionLocal() as s:
            rap = await lc.envoyer_confirmations(s, now_local)
            await s.commit()
            return rap

    maintenant = datetime.now(lc.FUSEAU)
    # La nuit même (versements d'AUJOURD'HUI) : rien ne part encore.
    def _miens() -> list[dict]:
        # La base de test est partagée : on ne regarde que NOTRE locataire.
        return [m for m in fake.sent if m["to"] == ["locataire.conf@exemple.ca"]]

    run(_nuit(maintenant))
    assert _miens() == []
    # La nuit suivante : un courriel pour le bail avec courriel (3
    # versements, montants finaux), « aucun » pour l'autre (ni courriel ni
    # cellulaire).
    demain = maintenant + timedelta(days=1)
    rap = run(_nuit(demain))
    assert rap["courriels"] >= 1 and rap["sans_coordonnees"] >= 1 and rap["echecs"] == 0
    assert len(_miens()) == 1
    html = _miens()[0]["html"]
    assert html.count("<li>") == 3 and "1 860,00" in html and "400,00" not in html

    async def _etat():
        async with TestSessionLocal() as s:
            rows = (await s.execute(
                select(PaiementLoyer).where(PaiementLoyer.bail_id.in_([b1, b2]))
            )).scalars().all()
            return sorted((p.bail_id == b1, p.confirmation_canal) for p in rows)

    assert run(_etat()) == [(False, "aucun"), (True, "courriel"), (True, "courriel"), (True, "courriel")]
    # Jamais deux fois ; et l'historique expose la confirmation.
    assert run(_nuit(demain))["versements"] == 0 and len(_miens()) == 1
    d = client.get(f"/api/v1/immobilier/locataires/{avec['locataire_id']}/dossier", headers=auth_headers).json()
    assert all(p["confirmation_canal"] == "courriel" and p["confirmation_envoyee_le"] for p in d["paiements"])
    assert any("Confirmation de paiement" in c["contenu"] for c in d["communications"])
    assert p_a["id"]  # (référence gardée)


def test_confirmation_ignore_vieux_versements_et_imports(run):
    """Un versement « reçu » il y a des mois (rattrapage d'historique) ou
    sans auteur (import) n'est jamais confirmé."""
    debut, fin = lc.fenetre(datetime(2026, 11, 20, 2, 0, tzinfo=lc.FUSEAU))

    class P:
        confirmation_envoyee_le = None
        montant = 600
        cree_par = "kyle@x.ca"
        paye_le = date(2026, 11, 19)
        created_at = datetime(2026, 11, 19, 18, 0, tzinfo=timezone.utc)

    assert lc.versement_admissible(P(), debut, fin) is True
    vieux = P(); vieux.paye_le = date(2026, 7, 1)
    assert lc.versement_admissible(vieux, debut, fin) is False
    imp = P(); imp.cree_par = None
    assert lc.versement_admissible(imp, debut, fin) is False
    auj = P(); auj.created_at = datetime(2026, 11, 20, 6, 0, tzinfo=timezone.utc)
    assert lc.versement_admissible(auj, debut, fin) is False
    # Rien avant la mise en service.
    d0, f0 = lc.fenetre(datetime(2026, 11, 13, 2, 0, tzinfo=lc.FUSEAU))
    assert d0 == f0
    assert "loyer_confirmations" in {a.key for a in __import__("app.automations.catalog", fromlist=["CATALOG"]).CATALOG}
