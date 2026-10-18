"""Smoke — remplacement d'un locataire et arrêt de la dette après départ
(retour Steven 2026-10-18) :

1. logement ORDINAIRE : « remplacer » un locataire ferme son bail la
   veille du début du nouveau (départ ACTÉ), sa dette reste sur lui et
   dans l'unité, le nouveau bail se crée ; un crédit règle la dette
   même après la fin du bail ; le locataire parti et soldé se supprime ;
2. logement EN CHAMBRES : deux baux actifs de locataires différents
   cohabitent (bug « nouveau locataire 8900 chambre E »), le même
   locataire ne se chevauche pas, et un bail AU MOIS fermé ne réclame
   plus un loyer après le départ ;
3. recalage lazy : un bail annuel échu dont le successeur est en place
   se TERMINE (il n'est plus reconduit par-dessus) ; un bail au mois
   échu se termine si son départ est déclaré, et court sinon.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from app.models.immobilier import Bail, Immeuble, Locataire, Logement
from app.services.locatif_demarrage import DEFAULT_DEMARRAGE

from tests.smoke.conftest import TestSessionLocal


def _mois(k: int) -> date:
    """1er du mois, k mois avant (k < 0) ou après le mois courant."""
    m0 = date.today().replace(day=1)
    y, m = m0.year, m0.month + k
    while m < 1:
        y, m = y - 1, m + 12
    while m > 12:
        y, m = y + 1, m - 12
    return date(y, m, 1)


def _veille(d: date) -> date:
    return d - timedelta(days=1)


def _seed(run, *, nom: str, chambres: bool = False) -> dict:
    async def _s() -> dict:
        async with TestSessionLocal() as s:
            imm = Immeuble(name=nom, address=f"1 rue {nom}", is_active=True)
            s.add(imm)
            await s.flush()
            lg = Logement(
                immeuble_id=imm.id, numero="E", status="vacant",
                location_en_chambres=chambres,
            )
            l1 = Locataire(full_name=f"Ancien {nom}")
            l2 = Locataire(full_name=f"Colocataire {nom}")
            l3 = Locataire(full_name=f"Nouveau {nom}")
            s.add_all([lg, l1, l2, l3])
            await s.commit()
            return {
                "immeuble_id": imm.id, "logement_id": lg.id,
                "l1": l1.id, "l2": l2.id, "l3": l3.id,
            }

    return run(_s())


def _set_demarrage(client, headers, d: date) -> None:
    r = client.put("/api/v1/immobilier/demarrage", headers=headers, json={"date": d.isoformat()})
    assert r.status_code == 200, r.text


def _post_bail(client, headers, logement_id, locataire_id, *, debut: date, fin: date,
               loyer=1000, status="actif", **extra):
    body = {
        "logement_id": logement_id, "locataire_id": locataire_id,
        "date_debut": debut.isoformat(), "date_fin": fin.isoformat(),
        "loyer_mensuel": loyer, "status": status, "jour_echeance": 1,
    }
    body.update(extra)
    return client.post("/api/v1/immobilier/baux", headers=headers, json=body)


def _dossier_logement(client, headers, logement_id) -> dict:
    r = client.get(f"/api/v1/immobilier/logements/{logement_id}/dossier", headers=headers)
    assert r.status_code == 200, r.text
    return {b["id"]: b for b in r.json()["baux"]}


def _rows(client, headers, mois: date) -> dict:
    r = client.get(f"/api/v1/immobilier/loyers/overview?mois={mois:%Y-%m}", headers=headers)
    assert r.status_code == 200, r.text
    return {row["bail_id"]: row for row in r.json()["rows"]}


def test_remplacer_locataire_logement_ordinaire(client, auth_headers, run):
    seed = _seed(run, nom="Remplacement")
    _set_demarrage(client, auth_headers, _mois(-6))
    try:
        today = date.today()
        debut1, debut2 = _mois(-5), _mois(-2)
        r = _post_bail(client, auth_headers, seed["logement_id"], seed["l1"],
                       debut=debut1, fin=_veille(debut1.replace(year=debut1.year + 1)))
        assert r.status_code == 201, r.text
        b1 = r.json()["id"]

        # Sans remplacement : l'occupant bloque toujours (un seul bail actif).
        r = _post_bail(client, auth_headers, seed["logement_id"], seed["l3"],
                       debut=debut2, fin=_veille(debut2.replace(year=debut2.year + 1)), loyer=1100)
        assert r.status_code == 409 and "occupe encore" in r.json()["detail"], r.text

        # Garde-fous du remplacement.
        r = _post_bail(client, auth_headers, seed["logement_id"], seed["l1"],
                       debut=debut2, fin=_veille(debut2.replace(year=debut2.year + 1)),
                       remplacer_bail_id=b1)
        assert r.status_code == 422, r.text  # même locataire
        r = _post_bail(client, auth_headers, seed["logement_id"], seed["l3"],
                       debut=debut2, fin=_veille(debut2.replace(year=debut2.year + 1)), loyer=1100,
                       remplacer_bail_id=b1, remplacer_date_depart=debut2.isoformat())
        assert r.status_code == 422, r.text  # départ pas avant le début

        # Remplacement : départ de l'ancien la veille, nouveau bail créé.
        r = _post_bail(client, auth_headers, seed["logement_id"], seed["l3"],
                       debut=debut2, fin=_veille(debut2.replace(year=debut2.year + 1)), loyer=1100,
                       remplacer_bail_id=b1)
        assert r.status_code == 201, r.text
        b2 = r.json()["id"]
        assert r.json()["depart_declare_le"] is None

        baux = _dossier_logement(client, auth_headers, seed["logement_id"])
        assert baux[b1]["status"] == "resilie"
        assert baux[b1]["date_fin"] == _veille(debut2).isoformat()
        assert baux[b1]["depart_declare_le"] == today.isoformat()
        # Dette de l'ancien : 3 mois (−5, −4, −3), pas un de plus.
        assert baux[b1]["solde_du"] == 3000.0
        # Nouveau : −2, −1, courant.
        assert baux[b2]["status"] == "actif" and baux[b2]["solde_du"] == 3300.0

        rows = _rows(client, auth_headers, _mois(0))
        assert rows[b1]["solde_total"] == 3000.0 and rows[b1]["etat"] == "retard"
        assert rows[b1]["bail_statut"] == "resilie"
        assert rows[b2]["solde_total"] == 3300.0

        # Crédit de règlement daté du mois COURANT (après la fin du bail) :
        # accepté — c'est ce que la fiche propose (bug « crédit de 600 $ »).
        r = client.post(f"/api/v1/immobilier/baux/{b1}/frais", headers=auth_headers,
                        json={"mois_couvert": _mois(0).isoformat(), "montant": -3000,
                              "libelle": "Règlement de départ"})
        assert r.status_code == 201, r.text
        r = client.post(f"/api/v1/immobilier/baux/{b1}/frais", headers=auth_headers,
                        json={"mois_couvert": _mois(2).isoformat(), "montant": -1, "libelle": "Futur"})
        assert r.status_code == 400 and "couvert" in r.json()["detail"]
        baux = _dossier_logement(client, auth_headers, seed["logement_id"])
        assert baux[b1]["solde_du"] == 0.0
        assert b1 not in _rows(client, auth_headers, _mois(0))  # dette réglée → disparaît

        # Fiche du locataire parti : son bail, son solde (0), son départ.
        r = client.get(f"/api/v1/immobilier/locataires/{seed['l1']}/dossier", headers=auth_headers)
        assert r.status_code == 200, r.text
        d1 = r.json()["baux"][0]
        assert d1["id"] == b1 and d1["solde_du"] == 0.0
        assert d1["depart_declare_le"] == today.isoformat()

        # Locataire parti et soldé : se supprime (purge de son historique).
        r = client.delete(f"/api/v1/immobilier/locataires/{seed['l1']}?force=true&purger=true",
                          headers=auth_headers)
        assert r.status_code == 204, r.text
    finally:
        _set_demarrage(client, auth_headers, DEFAULT_DEMARRAGE)


def test_chambres_coexistence_et_fin_de_dette(client, auth_headers, run):
    seed = _seed(run, nom="Chambres", chambres=True)
    _set_demarrage(client, auth_headers, _mois(-6))
    try:
        today = date.today()
        debut, debut3 = _mois(-5), _mois(-2)
        fin = _veille(debut.replace(year=debut.year + 1))
        r = _post_bail(client, auth_headers, seed["logement_id"], seed["l1"], debut=debut, fin=fin, loyer=500)
        assert r.status_code == 201, r.text
        r1 = r.json()["id"]
        assert r.json()["au_mois"] is True
        # Deux chambres, deux locataires : les baux cohabitent.
        r = _post_bail(client, auth_headers, seed["logement_id"], seed["l2"], debut=debut, fin=fin, loyer=500)
        assert r.status_code == 201, r.text
        r2 = r.json()["id"]
        # Le MÊME locataire deux fois sur la même période : non.
        r = _post_bail(client, auth_headers, seed["logement_id"], seed["l1"], debut=debut3, fin=fin, loyer=500)
        assert r.status_code == 409, r.text

        # Le nouveau remplace l'ancien de la chambre E.
        r = _post_bail(client, auth_headers, seed["logement_id"], seed["l3"],
                       debut=debut3, fin=fin, loyer=550, remplacer_bail_id=r1)
        assert r.status_code == 201, r.text
        r3 = r.json()["id"]

        baux = _dossier_logement(client, auth_headers, seed["logement_id"])
        assert baux[r1]["status"] == "resilie"
        assert baux[r1]["date_fin"] == _veille(debut3).isoformat()
        assert baux[r1]["depart_declare_le"] == today.isoformat()
        assert baux[r2]["status"] == "actif" and baux[r3]["status"] == "actif"

        rows = _rows(client, auth_headers, _mois(0))
        # Ancien : −5, −4, −3 — un bail AU MOIS fermé ne court plus.
        assert rows[r1]["solde_total"] == 1500.0 and rows[r1]["bail_statut"] == "resilie"
        # Colocataire resté : −5 … courant = 6 mois.
        assert rows[r2]["solde_total"] == 3000.0
        # Nouveau : −2, −1, courant.
        assert rows[r3]["solde_total"] == 1650.0
        assert baux[r1]["solde_du"] == 1500.0 and baux[r2]["solde_du"] == 3000.0
    finally:
        _set_demarrage(client, auth_headers, DEFAULT_DEMARRAGE)


def _bail_direct(run, *, logement_id, locataire_id, debut: date, fin: date, au_mois=False,
                 depart_declare_le: date | None = None, loyer=800) -> int:
    async def _s() -> int:
        async with TestSessionLocal() as s:
            now = datetime.now(timezone.utc)
            b = Bail(
                logement_id=logement_id, locataire_id=locataire_id,
                date_debut=debut, date_fin=fin, loyer_mensuel=loyer,
                status="actif", au_mois=au_mois, jour_echeance=1,
                depart_declare_le=depart_declare_le,
                created_at=now, updated_at=now,
            )
            s.add(b)
            await s.commit()
            return b.id

    return run(_s())


def test_recalage_lazy_termine_au_lieu_de_reconduire(client, auth_headers, run):
    # Bail annuel ÉCHU dont le successeur est déjà en place (dossier de
    # relocation refermé « reloué » depuis longtemps) : avant, il était
    # reconduit tacitement d'un an par-dessus le nouveau → double loyer.
    seed = _seed(run, nom="Lazy")
    debut1 = _mois(-14)
    ancien = _bail_direct(run, logement_id=seed["logement_id"], locataire_id=seed["l1"],
                          debut=debut1, fin=_veille(_mois(-1)))
    suivant = _bail_direct(run, logement_id=seed["logement_id"], locataire_id=seed["l3"],
                           debut=_mois(-1), fin=_veille(_mois(11)))
    _rows(client, auth_headers, _mois(0))  # déclenche le recalage lazy
    baux = _dossier_logement(client, auth_headers, seed["logement_id"])
    assert baux[ancien]["status"] == "termine"
    assert baux[ancien]["date_fin"] == _veille(_mois(-1)).isoformat()  # pas étiré
    assert baux[suivant]["status"] == "actif"

    # Chambres : bail au mois échu — terminé si départ DÉCLARÉ, sinon il court.
    seed_c = _seed(run, nom="LazyChambres", chambres=True)
    parti = _bail_direct(run, logement_id=seed_c["logement_id"], locataire_id=seed_c["l1"],
                         debut=_mois(-8), fin=_veille(_mois(-1)), au_mois=True,
                         depart_declare_le=_mois(-2))
    reste = _bail_direct(run, logement_id=seed_c["logement_id"], locataire_id=seed_c["l2"],
                         debut=_mois(-8), fin=_veille(_mois(-1)), au_mois=True)
    _rows(client, auth_headers, _mois(0))
    baux = _dossier_logement(client, auth_headers, seed_c["logement_id"])
    assert baux[parti]["status"] == "termine"
    assert baux[reste]["status"] == "actif"
    assert baux[reste]["date_fin"] == _veille(_mois(-1)).isoformat()
