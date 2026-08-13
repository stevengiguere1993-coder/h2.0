"""Smoke — Relevés 31 : sélection par CHEVAUCHEMENT, un relevé PAR
LOCATAIRE et fenêtre de production (retours Phil 2026-08-13).

Trois régressions couvertes :

1. « Pour 2026, Drissa n'apparaît même pas comme locataire. » — la liste
   se construisait à partir des baux couvrant le 31 décembre. Un bail
   qui commence en octobre N-1 et se termine en juin N faisait
   disparaître son locataire de l'année N. Elle se construit désormais
   par chevauchement de l'année d'imposition.
2. « Il devrait avoir un mécanisme m'empêchant de les créer avant. » —
   les relevés de l'année N ne se produisent qu'à partir du 1er décembre
   N (même bascule que ``releve31_bascule_mois``, défaut novembre).
3. Trou fiscal : au 44 Kennedy, les logements 101/105/107 ont eu DEUX
   locataires successifs dans la même année. Chacun a légalement droit
   à SON relevé — la liste sort donc une ligne PAR OCCUPANT et le suivi
   est porté par (année, logement, bail).
"""
from __future__ import annotations

from datetime import date

from app.services.locatif_suivis import SuivisConfig


def _annee_fermee(today: date) -> int:
    """Une année dont la fenêtre de production n'est PAS encore ouverte."""
    return today.year if today < date(today.year, 12, 1) else today.year + 1


def _annee_ouverte(today: date) -> int:
    """Une année dont la fenêtre est ouverte depuis longtemps."""
    return today.year - 1


def _set_bascule(client, auth_headers, mois: int) -> None:
    """Fixe ``releve31_bascule_mois`` — d'autres smoke tests la bougent,
    on ne peut pas se fier au défaut."""
    r = client.put(
        "/api/v1/immobilier/suivis-config",
        headers=auth_headers,
        json={
            "renouvellement_mois_avant": 6,
            "assurance_bascule_mois": 1,
            "releve31_bascule_mois": mois,
        },
    )
    assert r.status_code == 200, r.text


# ── 1) Logique pure de la fenêtre (déterministe) ────────────────────


def test_ouverture_releve31_1er_decembre():
    """Bascule par défaut (novembre) → ouverture le 1er décembre de N."""
    c = SuivisConfig()  # releve31_bascule_mois = 11
    assert c.ouverture_releve31(2026) == date(2026, 12, 1)
    assert c.releve31_creation_ouverte(2026, date(2026, 11, 30)) is False
    assert c.releve31_creation_ouverte(2026, date(2026, 12, 1)) is True
    # Décembre + janvier + février pour produire ET remettre.
    assert c.releve31_creation_ouverte(2026, date(2027, 2, 28)) is True
    # L'ouverture suit la MÊME bascule que l'année par défaut de l'onglet.
    assert c.annee_releve31_defaut(date(2026, 11, 30)) == 2025
    assert c.annee_releve31_defaut(date(2026, 12, 1)) == 2026


def test_ouverture_suit_le_reglage():
    """Bascule réglée en septembre → ouverture le 1er octobre ; réglée en
    décembre → le 1er janvier N+1 (pas de mois 13)."""
    sept = SuivisConfig(releve31_bascule_mois=9)
    assert sept.ouverture_releve31(2026) == date(2026, 10, 1)
    dec = SuivisConfig(releve31_bascule_mois=12)
    assert dec.ouverture_releve31(2026) == date(2027, 1, 1)
    assert dec.releve31_creation_ouverte(2026, date(2026, 12, 31)) is False


# ── 2) Bout en bout : liste + garde-fou ─────────────────────────────


def test_releve31_chevauchement_et_fenetre(client, auth_headers, run):
    """Un bail qui ne couvre QU'UNE PARTIE de l'année N met quand même
    son locataire dans la liste de N ; la production est refusée avant le
    1er décembre N et acceptée après."""
    from app.models.immobilier import (
        Bail,
        BailStatus,
        Immeuble,
        Locataire,
        Logement,
        LogementStatus,
    )

    from .conftest import TestSessionLocal

    today = date.today()
    an_ouvert = _annee_ouverte(today)
    an_ferme = _annee_fermee(today)
    # Bascule = novembre (défaut produit) → ouverture le 1er décembre.
    _set_bascule(client, auth_headers, 11)

    async def _seed():
        async with TestSessionLocal() as s:
            imm = Immeuble(
                name="8900 St-Hubert (smoke R31)",
                address="8900 rue Saint-Hubert",
                city="Montréal",
                is_active=True,
            )
            s.add(imm)
            await s.flush()
            lg = Logement(
                immeuble_id=imm.id,
                numero="8906-B",
                status=LogementStatus.OCCUPE.value,
            )
            loc = Locataire(full_name="Drissa Smoke R31")
            s.add_all([lg, loc])
            await s.flush()
            # Bail du 1er oct. (N-1) au 30 juin (N) : il NE couvre PAS le
            # 31 décembre de N — c'est exactement le cas rapporté.
            b = Bail(
                logement_id=lg.id,
                locataire_id=loc.id,
                date_debut=date(an_ouvert - 1, 10, 1),
                date_fin=date(an_ouvert, 6, 30),
                loyer_mensuel=1150.0,
                status=BailStatus.ACTIF.value,
            )
            s.add(b)
            await s.commit()
            return {"logement": lg.id, "immeuble": imm.id, "bail": b.id}

    ids = run(_seed())

    # (a) Le locataire apparaît pour l'année où il n'a occupé QUE le
    #     premier semestre — avant le correctif, la ligne était absente.
    d = client.get(
        f"/api/v1/immobilier/releves31?annee={an_ouvert}",
        headers=auth_headers,
    ).json()
    ligne = next(
        (r for r in d["rows"] if r["logement_id"] == ids["logement"]), None
    )
    assert ligne is not None, (
        f"Le logement 8906-B doit apparaître en {an_ouvert} même si son "
        f"bail se termine le 30 juin."
    )
    assert ligne["locataire_nom"] == "Drissa Smoke R31"
    assert ligne["bail_id"] == ids["bail"]
    # Période d'occupation bornée à l'année.
    assert ligne["occupation_debut"] == f"{an_ouvert}-01-01"
    assert ligne["occupation_fin"] == f"{an_ouvert}-06-30"
    assert ligne["nb_occupants_logement"] == 1

    # (b) … et aussi pour l'année précédente (occupée d'octobre à déc.).
    d0 = client.get(
        f"/api/v1/immobilier/releves31?annee={an_ouvert - 1}",
        headers=auth_headers,
    ).json()
    l0 = next(
        (r for r in d0["rows"] if r["logement_id"] == ids["logement"]), None
    )
    assert l0 is not None
    assert l0["occupation_debut"] == f"{an_ouvert - 1}-10-01"
    assert l0["occupation_fin"] == f"{an_ouvert - 1}-12-31"

    # (c) Fenêtre FERMÉE : création refusée en 422, message explicite.
    ferme = client.get(
        f"/api/v1/immobilier/releves31?annee={an_ferme}", headers=auth_headers
    ).json()
    assert ferme["creation_ouverte"] is False
    assert ferme["ouverture_le"] == f"{an_ferme}-12-01"
    r = client.patch(
        f"/api/v1/immobilier/releves31/{an_ferme}/{ids['logement']}",
        headers=auth_headers,
        json={"numero_releve": "R310000001"},
    )
    assert r.status_code == 422, r.text
    detail = r.json()["detail"]
    assert str(an_ferme) in detail and "1er décembre" in detail
    assert str(an_ferme + 1) in detail  # remise avant fin février N+1

    # (d) Fenêtre OUVERTE : la même création passe.
    ouvert = client.get(
        f"/api/v1/immobilier/releves31?annee={an_ouvert}", headers=auth_headers
    ).json()
    assert ouvert["creation_ouverte"] is True
    assert ouvert["ouverture_le"] == f"{an_ouvert}-12-01"
    r = client.patch(
        f"/api/v1/immobilier/releves31/{an_ouvert}/{ids['logement']}",
        headers=auth_headers,
        json={"numero_releve": "R310000002"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["numero_releve"] == "R310000002"
    assert r.json()["statut"] == "produit"

    # Nettoyage : la ligne repart « à produire » et la config revient à
    # la valeur que laissent les autres smoke tests.
    client.delete(
        f"/api/v1/immobilier/releves31/{an_ouvert}/{ids['logement']}",
        headers=auth_headers,
    )
    _set_bascule(client, auth_headers, 2)


def test_releve31_deux_locataires_dans_lannee(client, auth_headers, run):
    """Changement de locataire en cours d'année : DEUX lignes, une par
    locataire, chacune avec sa période et son propre suivi. Chacun a
    légalement droit à son relevé (44 Kennedy 101/105/107)."""
    from app.models.immobilier import (
        Bail,
        BailStatus,
        Immeuble,
        Locataire,
        Logement,
        LogementStatus,
    )

    from .conftest import TestSessionLocal

    an = _annee_ouverte(date.today())

    async def _seed():
        async with TestSessionLocal() as s:
            imm = Immeuble(
                name="Duplex smoke R31 turnover",
                address="12 rue Turnover",
                is_active=True,
            )
            s.add(imm)
            await s.flush()
            lg = Logement(
                immeuble_id=imm.id,
                numero="T-1",
                status=LogementStatus.OCCUPE.value,
            )
            sortant = Locataire(full_name="Sortant Smoke R31")
            entrant = Locataire(full_name="Entrant Smoke R31")
            s.add_all([lg, sortant, entrant])
            await s.flush()
            b_sortant = Bail(
                logement_id=lg.id, locataire_id=sortant.id,
                date_debut=date(an - 1, 7, 1),
                date_fin=date(an, 6, 30),
                loyer_mensuel=900.0,
                status=BailStatus.TERMINE.value,
            )
            b_entrant = Bail(
                logement_id=lg.id, locataire_id=entrant.id,
                date_debut=date(an, 7, 1),
                date_fin=date(an + 1, 6, 30),
                loyer_mensuel=1000.0,
                status=BailStatus.ACTIF.value,
            )
            s.add_all([b_sortant, b_entrant])
            await s.commit()
            return {
                "logement": lg.id,
                "sortant": b_sortant.id,
                "entrant": b_entrant.id,
            }

    ids = run(_seed())
    lg_id = ids["logement"]

    d = client.get(
        f"/api/v1/immobilier/releves31?annee={an}", headers=auth_headers
    ).json()
    lignes = [r for r in d["rows"] if r["logement_id"] == lg_id]
    # UNE ligne par locataire — c'est le trou fiscal corrigé.
    assert len(lignes) == 2, lignes
    par_bail = {r["bail_id"]: r for r in lignes}
    assert set(par_bail) == {ids["sortant"], ids["entrant"]}
    sortant = par_bail[ids["sortant"]]
    entrant = par_bail[ids["entrant"]]
    assert sortant["locataire_nom"] == "Sortant Smoke R31"
    assert entrant["locataire_nom"] == "Entrant Smoke R31"
    # Chacun avec SA période bornée à l'année.
    assert (sortant["occupation_debut"], sortant["occupation_fin"]) == (
        f"{an}-01-01", f"{an}-06-30",
    )
    assert (entrant["occupation_debut"], entrant["occupation_fin"]) == (
        f"{an}-07-01", f"{an}-12-31",
    )
    assert sortant["nb_occupants_logement"] == 2
    # Ordre chronologique : le sortant s'affiche au-dessus de l'entrant.
    assert lignes.index(sortant) < lignes.index(entrant)

    # Un numéro collé sur le SORTANT ne déteint pas sur l'entrant.
    r = client.patch(
        f"/api/v1/immobilier/releves31/{an}/{lg_id}?bail_id={ids['sortant']}",
        headers=auth_headers,
        json={"numero_releve": "R31SORTANT"},
    )
    assert r.status_code == 200, r.text
    r = client.patch(
        f"/api/v1/immobilier/releves31/{an}/{lg_id}?bail_id={ids['entrant']}",
        headers=auth_headers,
        json={"numero_releve": "R31ENTRANT"},
    )
    assert r.status_code == 200, r.text
    d2 = client.get(
        f"/api/v1/immobilier/releves31?annee={an}", headers=auth_headers
    ).json()
    par_bail2 = {
        r["bail_id"]: r for r in d2["rows"] if r["logement_id"] == lg_id
    }
    assert par_bail2[ids["sortant"]]["numero_releve"] == "R31SORTANT"
    assert par_bail2[ids["entrant"]]["numero_releve"] == "R31ENTRANT"
    assert par_bail2[ids["sortant"]]["statut"] == "produit"

    # La copie PDF générée est établie au nom du BON locataire : c'est
    # le cœur du trou fiscal (le sortant recevait le relevé de l'autre).
    g = client.post(
        f"/api/v1/immobilier/releves31/{an}/{lg_id}/generer"
        f"?bail_id={ids['sortant']}",
        headers=auth_headers,
    )
    assert g.status_code == 200, g.text
    doc_id = g.json()["document_id"]
    assert doc_id

    def _doc_locataire(document_id: int) -> int:
        async def _lire():
            async with TestSessionLocal() as s:
                from app.models.immobilier import ImmDocument

                doc = await s.get(ImmDocument, document_id)
                return doc.locataire_id

        return run(_lire())

    assert _doc_locataire(doc_id) == par_bail2[ids["sortant"]]["locataire_id"]

    # Annuler le relevé du sortant laisse celui de l'entrant intact.
    assert client.delete(
        f"/api/v1/immobilier/releves31/{an}/{lg_id}?bail_id={ids['sortant']}",
        headers=auth_headers,
    ).status_code == 204
    d3 = client.get(
        f"/api/v1/immobilier/releves31?annee={an}", headers=auth_headers
    ).json()
    par_bail3 = {
        r["bail_id"]: r for r in d3["rows"] if r["logement_id"] == lg_id
    }
    assert par_bail3[ids["sortant"]]["statut"] == "a_produire"
    assert par_bail3[ids["sortant"]]["numero_releve"] is None
    assert par_bail3[ids["entrant"]]["numero_releve"] == "R31ENTRANT"

    # Chaque locataire ne voit que SON relevé sur sa fiche.
    loc_entrant = par_bail3[ids["entrant"]]["locataire_id"]
    mes = client.get(
        f"/api/v1/immobilier/locataires/{loc_entrant}/releves31",
        headers=auth_headers,
    ).json()
    assert [x["numero_releve"] for x in mes] == ["R31ENTRANT"]

    client.delete(
        f"/api/v1/immobilier/releves31/{an}/{lg_id}?bail_id={ids['entrant']}",
        headers=auth_headers,
    )


def test_releve31_creation_manuelle(client, auth_headers, run):
    """Bouton « Créer un relevé » : POST /releves31 fabrique la ligne
    même quand la détection automatique ne voit rien (bail absent), et
    respecte la fenêtre de production."""
    from app.models.immobilier import Immeuble, Logement, LogementStatus

    from .conftest import TestSessionLocal

    today = date.today()
    an_ouvert = _annee_ouverte(today)
    an_ferme = _annee_fermee(today)
    _set_bascule(client, auth_headers, 11)

    async def _seed():
        async with TestSessionLocal() as s:
            imm = Immeuble(
                name="Manuel smoke R31", address="9 rue Manuelle",
                is_active=True,
            )
            s.add(imm)
            await s.flush()
            # Aucun bail : la détection automatique ignore ce logement.
            lg = Logement(
                immeuble_id=imm.id, numero="M-1",
                status=LogementStatus.VACANT.value,
            )
            s.add(lg)
            await s.commit()
            return lg.id

    lg_id = run(_seed())

    # Absent de la détection automatique…
    d = client.get(
        f"/api/v1/immobilier/releves31?annee={an_ouvert}", headers=auth_headers
    ).json()
    assert all(r["logement_id"] != lg_id for r in d["rows"])

    # … mais créable à la main.
    r = client.post(
        "/api/v1/immobilier/releves31",
        headers=auth_headers,
        json={"annee": an_ouvert, "logement_id": lg_id},
    )
    assert r.status_code == 201, r.text
    assert r.json()["statut"] == "a_produire"
    # Idempotent : re-créer renvoie la même ligne, pas un doublon.
    r2 = client.post(
        "/api/v1/immobilier/releves31",
        headers=auth_headers,
        json={"annee": an_ouvert, "logement_id": lg_id},
    )
    assert r2.status_code == 201, r2.text

    # La fenêtre de production s'applique aussi à la création manuelle.
    r3 = client.post(
        "/api/v1/immobilier/releves31",
        headers=auth_headers,
        json={"annee": an_ferme, "logement_id": lg_id},
    )
    assert r3.status_code == 422, r3.text
    assert "1er décembre" in r3.json()["detail"]

    client.delete(
        f"/api/v1/immobilier/releves31/{an_ouvert}/{lg_id}",
        headers=auth_headers,
    )
    _set_bascule(client, auth_headers, 2)
