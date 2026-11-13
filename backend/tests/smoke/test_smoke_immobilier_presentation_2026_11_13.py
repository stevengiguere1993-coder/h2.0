"""Smoke — refonte d'Immobilier, lots 0 et 1 (Steven, 2026-11-13).

« Avant de mettre tout en place, on s'assure de pouvoir backer à l'état
actuel si c'est trop difficile d'utilisation » : un interrupteur par lot,
commun à l'équipe, changé par un admin. Et la page « Aujourd'hui » : une
seule liste de choses à faire, comptée par les vues où chaque ligne mène.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import delete

from app.models.automation_setting import AutomationSetting
from app.models.immobilier import Immeuble, Locataire, Logement
from app.services import immobilier_aujourdhui as auj
from app.services import immobilier_presentation as pres

from tests.smoke.conftest import TestSessionLocal


def _remettre_a_zero(run) -> None:
    async def _s() -> None:
        async with TestSessionLocal() as s:
            await s.execute(
                delete(AutomationSetting).where(AutomationSetting.key == pres.KEY)
            )
            await s.commit()

    run(_s())


# ── Interrupteur ───────────────────────────────────────────────────────


def test_defaut_nouvelle_presentation_pour_les_lots_livres():
    reglages = pres.normaliser({})
    assert reglages == {cle: True for cle in pres.CLES}
    actif = pres.actifs(reglages)
    for lot in pres.LOTS:
        # Un lot pas encore livré ne montre jamais la nouvelle présentation.
        assert actif[lot["cle"]] is bool(lot["livre"])
    assert actif["menu"] is True


def test_reglage_illisible_retombe_sur_le_defaut():
    assert pres.normaliser("pas un dict") == {cle: True for cle in pres.CLES}
    assert pres.normaliser({"menu": "non", "inconnu": False})["menu"] is True
    assert "inconnu" not in pres.normaliser({"inconnu": False})


def test_api_retour_a_la_presentation_actuelle(client, auth_headers, employee_headers, run):
    _remettre_a_zero(run)
    r = client.get("/api/v1/immobilier/presentation", headers=auth_headers)
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["actif"]["menu"] is True
    assert [lot["cle"] for lot in corps["lots"]] == list(pres.CLES)
    assert corps["modifie_le"] is None

    # Un employé lit le réglage (son menu en dépend) mais ne le change pas.
    r = client.get("/api/v1/immobilier/presentation", headers=employee_headers)
    assert r.status_code == 200, r.text
    r = client.put(
        "/api/v1/immobilier/presentation", headers=employee_headers, json={"menu": False}
    )
    assert r.status_code == 403, r.text

    # L'admin revient à la présentation actuelle : effet immédiat, pour tous.
    r = client.put(
        "/api/v1/immobilier/presentation", headers=auth_headers, json={"menu": False}
    )
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["actif"]["menu"] is False
    assert next(lot for lot in corps["lots"] if lot["cle"] == "menu")["nouvelle"] is False
    assert corps["modifie_le"] is not None
    r = client.get("/api/v1/immobilier/presentation", headers=employee_headers)
    assert r.json()["actif"]["menu"] is False

    # Les autres lots n'ont pas bougé ; une clé inconnue ou un corps vide
    # sont refusés.
    assert next(lot for lot in corps["lots"] if lot["cle"] == "loyers")["nouvelle"] is True
    r = client.put(
        "/api/v1/immobilier/presentation", headers=auth_headers, json={"autre": True}
    )
    assert r.status_code == 422, r.text
    r = client.put("/api/v1/immobilier/presentation", headers=auth_headers, json={})
    assert r.status_code == 422, r.text

    # Et on revient à la nouvelle présentation d'un clic.
    r = client.put(
        "/api/v1/immobilier/presentation", headers=auth_headers, json={"menu": True}
    )
    assert r.status_code == 200 and r.json()["actif"]["menu"] is True
    _remettre_a_zero(run)


# ── « Aujourd'hui » : composition des lignes ───────────────────────────


def test_montant_format_fr():
    assert auj.montant(4500) == "4 500 $"
    assert auj.montant(450.5) == "450,50 $"
    assert auj.montant(17325) == "17 325 $"


def test_composer_lignes_et_rien_a_signaler():
    chiffres = auj.Chiffres(
        loyers_nb=11, loyers_total=4500,
        avis_en_retard=1, avis_qui="Félix Gauthier, log. 7",
        baux_a_importer=15, baux_a_importer_immeubles=2,
        a_louer=2, a_louer_jours_max=13,
        bons_ouverts=2,
    )
    lignes, rien = auj.composer(chiffres)
    # Pastille du menu : 11 loyers + 1 avis en retard, pas les bons non urgents.
    assert auj.nb_urgent(chiffres) == 12
    par_cle = {ligne.cle: ligne for ligne in lignes}
    assert [ligne.cle for ligne in lignes] == [
        "loyers", "renouvellements", "baux_a_importer", "a_louer", "bons_travail",
    ]
    assert par_cle["loyers"].titre == "11 loyers à encaisser"
    assert par_cle["loyers"].detail == "4 500 $ en retard"
    assert par_cle["loyers"].ton == "urgent"
    assert par_cle["loyers"].href == "/immobilier/paiements?etat=retard"
    assert par_cle["renouvellements"].titre == "1 avis de renouvellement en retard"
    assert par_cle["renouvellements"].detail == "Félix Gauthier, log. 7"
    assert par_cle["renouvellements"].bouton == "Préparer"
    assert par_cle["baux_a_importer"].titre == "15 baux signés à importer"
    assert par_cle["baux_a_importer"].detail == "dans 2 immeubles"
    assert par_cle["a_louer"].detail == "le plus ancien libre depuis 13 jours"
    assert par_cle["bons_travail"].detail == "aucun urgent"
    assert par_cle["bons_travail"].ton == "info"
    # Dépôts : rien à faire → dans « rien à signaler », pas dans la liste.
    assert rien == ["dépôts à rendre"]


def test_composer_singuliers_et_source_illisible():
    lignes, rien = auj.composer(
        auj.Chiffres(
            loyers_nb=1, loyers_total=950.25,
            avis_a_envoyer=2,
            a_louer=1, a_louer_jours_max=1,
            bons_ouverts=3, bons_urgents=1,
            depots_nb=1, depots_total=450,
            assurances_a_relancer=1, consentements_a_relancer=2,
            indisponibles=["baux_a_importer"],
        )
    )
    par_cle = {ligne.cle: ligne for ligne in lignes}
    assert par_cle["loyers"].titre == "1 loyer à encaisser"
    assert par_cle["renouvellements"].titre == "2 avis de renouvellement à envoyer"
    assert par_cle["renouvellements"].ton == "attention"
    assert par_cle["a_louer"].detail == "libre depuis 1 jour"
    assert par_cle["bons_travail"].detail == "dont 1 urgent"
    assert par_cle["bons_travail"].ton == "urgent"
    assert par_cle["depots"].titre == "1 dépôt à rendre"
    assert par_cle["assurances"].href.endswith("?onglet=assurances")
    assert par_cle["consentements"].titre == "2 consentements à relancer"
    # Une source illisible n'est ni « à faire » ni « rien à signaler ».
    assert "baux_a_importer" not in par_cle and rien == []


# ── « Aujourd'hui » : API ──────────────────────────────────────────────


def _mois(d: date, delta: int) -> date:
    m = d.month - 1 + delta
    return date(d.year + m // 12, m % 12 + 1, 1)


def test_api_aujourdhui_compte_comme_les_pages(client, auth_headers, run):
    async def _seed() -> dict:
        async with TestSessionLocal() as s:
            imm = Immeuble(name="Refonte Auj", address="1 rue Refonte", is_active=True)
            s.add(imm)
            await s.flush()
            lg = Logement(immeuble_id=imm.id, numero="7", status="vacant")
            loc = Locataire(full_name="Locataire Aujourdhui")
            s.add_all([lg, loc])
            await s.commit()
            return {"logement_id": lg.id, "locataire_id": loc.id}

    seed = run(_seed())
    # Bail actif commencé il y a 3 mois, jamais payé, sans bail signé au
    # dossier : il doit sortir en loyer à encaisser ET en bail à importer.
    debut = _mois(date.today(), -3)
    r = client.post("/api/v1/immobilier/baux", headers=auth_headers, json={
        "logement_id": seed["logement_id"], "locataire_id": seed["locataire_id"],
        "date_debut": debut.isoformat(), "date_fin": _mois(debut, 12).isoformat(),
        "loyer_mensuel": 800, "status": "actif", "jour_echeance": 1,
    })
    assert r.status_code == 201, r.text

    r = client.get("/api/v1/immobilier/aujourdhui", headers=auth_headers)
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["indisponibles"] == []
    par_cle = {ligne["cle"]: ligne for ligne in corps["lignes"]}

    # Mêmes comptes que les vues où les lignes mènent.
    lo = client.get("/api/v1/immobilier/loyers/overview", headers=auth_headers).json()
    assert lo["nb_retards"] >= 1
    # La page Loyers réunit l'interne et la gestion externe (lot 2).
    ext = client.get("/api/v1/immobilier/loyers/externes", headers=auth_headers).json()
    assert par_cle["loyers"]["nb"] == lo["nb_retards"] + ext["nb_retards"]
    sans = client.get("/api/v1/immobilier/baux/sans-document", headers=auth_headers).json()
    assert sans["nb"] >= 1
    assert par_cle["baux_a_importer"]["nb"] == sans["nb"]
    assert corps["nb_urgent"] >= par_cle["loyers"]["nb"]
    for ligne in corps["lignes"]:
        assert ligne["href"].startswith("/immobilier/")
        assert ligne["ton"] in ("urgent", "attention", "info")
        # Le titre commence par un compte (pour les avis : ceux en retard,
        # ``nb`` comptant aussi ceux à envoyer).
        assert ligne["titre"].split(" ")[0].isdigit()
        assert 1 <= int(ligne["titre"].split(" ")[0]) <= ligne["nb"]

    # Une entreprise sans immeuble : rien à faire, rien d'illisible.
    r = client.get(
        "/api/v1/immobilier/aujourdhui?entreprise_id=999999", headers=auth_headers
    )
    assert r.status_code == 200, r.text
    vide = r.json()
    assert vide["indisponibles"] == []
    assert not {"loyers", "baux_a_importer", "a_louer", "depots"} & {
        ligne["cle"] for ligne in vide["lignes"]
    }


def test_api_aujourdhui_exige_le_volet(client, employee_headers):
    # L'employé de test n'a pas le volet Immobilier : la page lui est
    # fermée, comme les vues qu'elle réunit.
    r = client.get("/api/v1/immobilier/aujourdhui", headers=employee_headers)
    assert r.status_code == 403, r.text
