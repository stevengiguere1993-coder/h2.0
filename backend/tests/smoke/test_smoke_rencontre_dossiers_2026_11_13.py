"""Smoke — tableau des dossiers suivis en rencontres + consignes (2026-11-13).

Steven : « un tableau de vue d'ensemble des différents dossiers en cours
que nous discutons lors des rencontres », tout automatique, avec une IA
qui liste et élimine les doublons ; puis « que les tableaux, les résumés
et les bilans s'ajustent à travers le temps selon mes demandes de
modifications ».

L'IA est remplacée par un double : il lit le prompt et rend le JSON
attendu, ce qui teste le rattachement, l'historique, les fusions et
l'injection des consignes sans réseau.
"""
from __future__ import annotations

import json
import re

import pytest

from app.integrations.ai._base import CompletionResult
from app.services import rencontre_dossiers as svc
from app.services.rencontre_dossiers import cle_titre


class FauxIA:
    """Double de ``complete`` pour les dossiers et les doublons."""

    def __init__(self) -> None:
        self.prompts: list[str] = []
        self.doublons: list[dict] = []
        #: Rencontres (mot repère) auxquelles l'IA répond n'importe quoi.
        self.illisibles: set[str] = set()
        #: L'IA rend aussi les dossiers existants dont la rencontre n'a
        #: PAS parlé, pour dire « non abordé » (vu en prod le 2026-11-13).
        self.bavarde = False

    async def __call__(self, *, prompt, system=None, **_kw):
        self.prompts.append(prompt)
        if system == svc.PROMPT_DOUBLONS:
            return CompletionResult(
                text=json.dumps({"groupes": self.doublons}),
                model="test",
                provider="test",
            )
        rencontre = prompt.split("## Rencontre à analyser", 1)[-1]
        existants = prompt.split("## Rencontre à analyser", 1)[0]
        if any(mot in rencontre for mot in self.illisibles):
            return CompletionResult(
                text="Désolé, je ne peux pas répondre.",
                model="test",
                provider="test",
            )
        dossiers = []

        def existant(titre: str):
            m = re.search(rf"#(\d+) — {re.escape(titre)}", existants)
            return int(m.group(1)) if m else None

        if "Grutier" in rencontre:
            regle = "grutier est embauché" in rencontre
            dossiers.append(
                {
                    "dossier_id": existant("Embauche grutier"),
                    "titre": "Embauche grutier",
                    "entreprise": None,
                    "contexte": None,
                    "responsable": "Zach",
                    "statut": "regle" if regle else "en_attente",
                    "resume": "On a parlé de l'embauche du grutier.",
                    "etat": "Grutier embauché." if regle else "Deux candidats à rappeler.",
                    "prochaine_action": None if regle else "Zach rappelle les candidats",
                    "echeance": None if regle else "vendredi",
                    "echeance_date": None if regle else "2026-01-09",
                    "decisions": ["Offre à 38 $ de l'heure"],
                    "actions": [{"title": "Rappeler les candidats grutier", "owner": "Zach", "due": "vendredi"}],
                    "questions": [],
                }
            )
        if "Toiture Wxyz" in rencontre:
            dossiers.append(
                {
                    "dossier_id": existant("Toiture Wxyz"),
                    "titre": "Toiture Wxyz",
                    "statut": "bloque",
                    "resume": "Le couvreur ne répond plus.",
                    "etat": "Bloqué : couvreur injoignable.",
                    "prochaine_action": "Trouver un autre couvreur",
                    "responsable": "Phil",
                }
            )
        for titre in ("Pavage Vbnmq", "Clôture Ghjkl", "Drainage Qwzxc"):
            if titre in rencontre:
                dossiers.append(
                    {
                        "dossier_id": existant(titre),
                        "titre": titre,
                        "statut": "en_cours",
                        "resume": f"On a parlé de : {titre}.",
                        "etat": "En marche.",
                    }
                )
        if "Serrures Plmko" in rencontre:
            dossiers.append(
                {
                    "dossier_id": existant("Serrures Plmko"),
                    "titre": "Serrures Plmko",
                    "statut": "en_attente",
                    "resume": "Les portes seront posées mercredi.",
                    "etat": (
                        "Les portes seront posées mercredi, mais la date "
                        "de livraison des serrures n'a pas été abordée."
                    ),
                }
            )
        if self.bavarde:
            rendus = {d["dossier_id"] for d in dossiers}
            for no, titre in re.findall(r"#(\d+) — ([^·\n]+)", existants):
                if int(no) in rendus:
                    continue
                dossiers.append(
                    {
                        "dossier_id": int(no),
                        "titre": titre.strip(),
                        "statut": "en_attente",
                        "resume": "Ce dossier n'a pas été discuté dans cette rencontre.",
                        "etat": f"Le dossier {titre.strip()} n'a pas été abordé.",
                        "prochaine_action": "À relancer",
                    }
                )
        return CompletionResult(
            text="```json\n" + json.dumps({"dossiers": dossiers}) + "\n```",
            model="test",
            provider="test",
        )


@pytest.fixture()
def ia(monkeypatch) -> FauxIA:
    faux = FauxIA()
    monkeypatch.setattr(svc, "complete", faux)
    monkeypatch.setattr(svc, "is_configured", lambda: True)
    return faux


def _importer(client, auth_headers, titre: str, jour: str, texte: str) -> int:
    r = client.post(
        "/api/v1/rencontres/importer",
        headers=auth_headers,
        data={"texte": texte, "title": titre, "meeting_date": jour},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _analyser_tout(client, auth_headers) -> None:
    for _ in range(60):
        r = client.post("/api/v1/rencontres/dossiers/analyser", headers=auth_headers)
        assert r.status_code == 200, r.text
        d = r.json()
        assert not d["ia_absente"]
        if d["restantes"] == 0:
            return
    raise AssertionError("l'analyse ne se termine pas")


def _dossier(client, auth_headers, titre: str, **params) -> dict | None:
    r = client.get(
        "/api/v1/rencontres/dossiers",
        headers=auth_headers,
        params={"inclure_regles": True, **params},
    )
    assert r.status_code == 200, r.text
    for d in r.json()["dossiers"]:
        if d["titre"] == titre:
            return d
    return None


def test_cle_titre_ignore_accents_pluriels_et_mots_vides():
    assert cle_titre("Électros d'Adam") == cle_titre("electro adam")
    assert cle_titre("Le camion") == cle_titre("Camions")
    assert cle_titre("Camion") != cle_titre("Camion Ford")


def test_sans_ia_rien_n_est_ecrit(client, auth_headers):
    _importer(client, auth_headers, "Sans IA (dossiers)", "2026-01-02", "Grutier : on cherche.")
    r = client.post("/api/v1/rencontres/dossiers/analyser", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["ia_absente"] is True
    assert r.json()["restantes"] >= 1
    assert _dossier(client, auth_headers, "Embauche grutier") is None


def test_analyse_rattache_et_tient_l_historique(client, auth_headers, ia):
    a = _importer(
        client, auth_headers, "Hebdo A (dossiers)", "2026-01-05",
        "Zach : pour le Grutier, deux candidats à rappeler.\n"
        "Phil : la Toiture Wxyz, le couvreur ne répond plus.",
    )
    b = _importer(
        client, auth_headers, "Hebdo B (dossiers)", "2026-01-12",
        "Zach : le Grutier, c'est fait, le grutier est embauché.",
    )
    _analyser_tout(client, auth_headers)

    d = _dossier(client, auth_headers, "Embauche grutier")
    assert d is not None
    # La rencontre la plus récente fait foi.
    assert d["statut"] == "regle"
    assert d["dernier_etat"] == "Grutier embauché."
    assert d["derniere_discussion"] == "2026-01-12"
    assert d["responsable"] == "Zach"
    assert d["nb_rencontres"] >= 2

    # Un dossier réglé sort de la vue par défaut.
    r = client.get("/api/v1/rencontres/dossiers", headers=auth_headers)
    assert all(x["titre"] != "Embauche grutier" for x in r.json()["dossiers"])
    assert r.json()["rencontres_a_analyser"] == 0

    fiche = client.get(f"/api/v1/rencontres/dossiers/{d['id']}", headers=auth_headers).json()
    ids = [h["rencontre_id"] for h in fiche["historique"]]
    assert ids.index(b) < ids.index(a)  # plus récent d'abord
    assert fiche["historique"][-1]["actions"][0]["titre"] == "Rappeler les candidats grutier"

    t = _dossier(client, auth_headers, "Toiture Wxyz")
    assert t["statut"] == "bloque" and t["prochaine_action"] == "Trouver un autre couvreur"

    # Réanalyser sans changement ne refait rien ; l'analyse est idempotente.
    avant = len(ia.prompts)
    _analyser_tout(client, auth_headers)
    assert len(ia.prompts) == avant


def test_modification_a_la_main_est_retenue(client, auth_headers, ia):
    _analyser_tout(client, auth_headers)
    t = _dossier(client, auth_headers, "Toiture Wxyz")
    r = client.patch(
        f"/api/v1/rencontres/dossiers/{t['id']}",
        headers=auth_headers,
        json={"titre": "Toiture du Wxyz", "statut": "en_attente", "responsable": "Steven"},
    )
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["titre"] == "Toiture du Wxyz" and "Toiture Wxyz" in d["alias"]
    assert d["statut"] == "en_attente" and d["modifie_a_la_main"] is True

    # Une réanalyse des mêmes rencontres ne défait pas la correction.
    r = client.post("/api/v1/rencontres/dossiers/reanalyser", headers=auth_headers)
    assert r.status_code == 200 and r.json()["rencontres_a_analyser"] >= 2
    _analyser_tout(client, auth_headers)
    d = _dossier(client, auth_headers, "Toiture du Wxyz")
    assert d is not None, "le titre saisi à la main doit rester"
    assert d["statut"] == "en_attente"
    assert d["responsable"] == "Steven"
    assert _dossier(client, auth_headers, "Toiture Wxyz") is None

    # Champ inconnu refusé.
    r = client.patch(
        f"/api/v1/rencontres/dossiers/{d['id']}", headers=auth_headers, json={"truc": 1}
    )
    assert r.status_code == 422


def _creer(client, auth_headers, titre: str, **extra) -> int:
    r = client.post(
        "/api/v1/rencontres/dossiers", headers=auth_headers, json={"titre": titre, **extra}
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_doublons_fusion_d_office_proposition_et_annulation(client, auth_headers, ia):
    a = _creer(client, auth_headers, "Camion Qzx", dernier_etat="On cherche.")
    b = _creer(client, auth_headers, "Le camion QZX")
    c = _creer(client, auth_headers, "Achat véhicule Qzx de travail")
    e = _creer(client, auth_headers, "Stationnement Vbn")
    f = _creer(client, auth_headers, "Garage Vbn")

    # L'IA : (a, c) « certain » avec un mot commun → fusion ; (e, f)
    # « probable » → proposé seulement.
    ia.doublons = [
        {"ids": [a, c], "certitude": "certain", "raison": "Même véhicule"},
        {"ids": [e, f], "certitude": "probable", "raison": "Même lieu ?"},
    ]
    r = client.post("/api/v1/rencontres/dossiers/doublons/verifier", headers=auth_headers)
    assert r.status_code == 200, r.text
    res = r.json()
    fusionnes = {x["dossier_id"] for x in res["fusionnes"]}
    # Même titre (a, b) d'office ; puis c par l'IA.
    assert len(fusionnes & {a, b}) == 1 and (c in fusionnes or a in fusionnes)
    assert res["proposes"] >= 1

    vivants = {d["id"] for d in client.get(
        "/api/v1/rencontres/dossiers", headers=auth_headers
    ).json()["dossiers"]}
    assert len(vivants & {a, b, c}) == 1
    assert {e, f} <= vivants

    d = client.get("/api/v1/rencontres/dossiers/doublons", headers=auth_headers).json()
    paire = next(
        p for p in d["proposes"] if {p["a"]["id"], p["b"]["id"]} == {e, f}
    )
    assert paire["raison"] == "Même lieu ?"
    assert {x["id"] for x in d["fusions_recentes"]} >= (({a, b, c}) - vivants)

    # « Garder séparés » : plus jamais proposée ni fusionnée.
    r = client.post(
        f"/api/v1/rencontres/dossiers/doublons/{paire['id']}/separer", headers=auth_headers
    )
    assert r.status_code == 200
    ia.doublons = [{"ids": [e, f], "certitude": "certain", "raison": "Même lieu"}]
    r = client.post("/api/v1/rencontres/dossiers/doublons/verifier", headers=auth_headers)
    assert r.json()["fusionnes"] == [] and r.json()["proposes"] == 0

    # Défaire une fusion : le dossier revient et n'est plus refusionné.
    perdu = next(iter({a, b} - vivants))
    r = client.post(
        f"/api/v1/rencontres/dossiers/{perdu}/defusionner", headers=auth_headers
    )
    assert r.status_code == 200, r.text
    ia.doublons = []
    r = client.post("/api/v1/rencontres/dossiers/doublons/verifier", headers=auth_headers)
    assert all(x["dossier_id"] != perdu for x in r.json()["fusionnes"])
    vivants = {d["id"] for d in client.get(
        "/api/v1/rencontres/dossiers", headers=auth_headers
    ).json()["dossiers"]}
    assert {a, b} <= vivants

    # Fusion à la main, puis conflit si on recommence.
    r = client.post(
        f"/api/v1/rencontres/dossiers/{e}/fusionner", headers=auth_headers, json={"dans_id": f}
    )
    assert r.status_code == 200, r.text
    assert "Stationnement Vbn" in r.json()["alias"]
    assert [x["id"] for x in r.json()["fusionnes"]] == [e]
    r = client.post(
        f"/api/v1/rencontres/dossiers/{e}/fusionner", headers=auth_headers, json={"dans_id": f}
    )
    assert r.status_code == 409


def test_fusion_additionne_l_historique_et_se_defait(client, auth_headers, ia):
    _analyser_tout(client, auth_headers)
    g = _dossier(client, auth_headers, "Embauche grutier")
    autre = _creer(client, auth_headers, "Recrutement opérateur de grue")
    r = client.post(
        f"/api/v1/rencontres/dossiers/{g['id']}/fusionner",
        headers=auth_headers,
        json={"dans_id": autre},
    )
    assert r.status_code == 200, r.text
    fiche = r.json()
    assert fiche["id"] == autre and len(fiche["historique"]) >= 2
    assert fiche["derniere_discussion"] == "2026-01-12"

    r = client.post(
        f"/api/v1/rencontres/dossiers/{g['id']}/defusionner", headers=auth_headers
    )
    assert r.status_code == 200, r.text
    assert len(r.json()["historique"]) >= 2
    vide = client.get(f"/api/v1/rencontres/dossiers/{autre}", headers=auth_headers).json()
    assert vide["historique"] == []


def test_consignes_retenues_et_donnees_a_l_ia(client, auth_headers, ia, monkeypatch):
    r = client.post(
        "/api/v1/rencontres/consignes",
        headers=auth_headers,
        json={"texte": "Toujours regrouper par immeuble Plokij.", "portee": "tout"},
    )
    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    r = client.post(
        "/api/v1/rencontres/consignes",
        headers=auth_headers,
        json={"texte": "Résumés en cinq lignes Mnbvc.", "portee": "resumes"},
    )
    assert r.status_code == 201

    # Tableau des dossiers : reçoit « tout », pas « resumes ».
    rid = _importer(client, auth_headers, "Hebdo C (dossiers)", "2026-01-19", "Grutier : rien de neuf.")
    _analyser_tout(client, auth_headers)
    prompt = next(p for p in reversed(ia.prompts) if "Hebdo C (dossiers)" in p)
    assert "Toujours regrouper par immeuble Plokij." in prompt
    assert "Mnbvc" not in prompt

    # Résumés : reçoivent « tout » et « resumes ».
    from app.services import rencontre_ai

    recus: list[str] = []

    async def faux_resume(*, prompt, **_kw):
        recus.append(prompt)
        return CompletionResult(
            text=json.dumps({"summary": "ok", "decisions": [], "action_items": [],
                             "open_questions": [], "risks": []}),
            model="test", provider="test",
        )

    monkeypatch.setattr(rencontre_ai, "complete", faux_resume)
    monkeypatch.setattr(rencontre_ai, "is_configured", lambda: True)
    fiche = client.get(f"/api/v1/rencontres/{rid}", headers=auth_headers).json()
    sid = fiche["sections"][0]["id"]
    r = client.post(
        f"/api/v1/rencontres/{rid}/sections/{sid}/summarize", headers=auth_headers
    )
    assert r.status_code == 200, r.text
    assert "Plokij" in recus[-1] and "Mnbvc" in recus[-1]

    # Désactivée : elle ne part plus.
    r = client.patch(
        f"/api/v1/rencontres/consignes/{cid}", headers=auth_headers, json={"actif": False}
    )
    assert r.status_code == 200 and r.json()["actif"] is False
    r = client.post(
        f"/api/v1/rencontres/{rid}/sections/{sid}/summarize", headers=auth_headers
    )
    assert "Plokij" not in recus[-1] and "Mnbvc" in recus[-1]

    liste = client.get("/api/v1/rencontres/consignes", headers=auth_headers).json()
    assert {c["id"] for c in liste["consignes"]} >= {cid}
    assert client.post(
        "/api/v1/rencontres/consignes", headers=auth_headers,
        json={"texte": "abc", "portee": "ailleurs"},
    ).status_code == 422


def test_supprimer_un_dossier_ia_laisse_une_consigne(client, auth_headers, ia):
    _analyser_tout(client, auth_headers)
    g = _dossier(client, auth_headers, "Embauche grutier")
    r = client.delete(f"/api/v1/rencontres/dossiers/{g['id']}", headers=auth_headers)
    assert r.status_code == 200, r.text
    cid = r.json()["consigne_id"]
    assert cid
    liste = client.get("/api/v1/rencontres/consignes", headers=auth_headers).json()
    c = next(x for x in liste["consignes"] if x["id"] == cid)
    assert "Embauche grutier" in c["texte"] and c["portee"] == "dossiers"
    assert client.get(
        f"/api/v1/rencontres/dossiers/{g['id']}", headers=auth_headers
    ).status_code == 404
    client.delete(f"/api/v1/rencontres/consignes/{cid}", headers=auth_headers)


def test_ordre_du_jour_et_question_a_kratos(client, auth_headers, ia):
    did = _creer(
        client, auth_headers, "Déneigement Hjklm",
        statut="bloque", dernier_etat="Contrat non signé.",
        prochaine_action="Relancer le déneigeur", responsable="Mick",
    )
    r = client.get("/api/v1/rencontres/dossiers/ordre-du-jour", headers=auth_headers)
    assert r.status_code == 200, r.text
    odj = r.json()
    assert "Déneigement Hjklm" in odj["texte"] and "Bloqués" in odj["texte"]
    assert any(did in g["dossier_ids"] for g in odj["groupes"])

    r = client.post(
        "/api/v1/rencontres/demander",
        headers=auth_headers,
        json={"question": "Où en est le déneigement Hjklm ?"},
    )
    assert r.status_code == 200, r.text
    d = r.json()
    assert [x["id"] for x in d["dossiers"]] == [did]
    assert "Contrat non signé." in d["reponse"]


def test_rencontre_illisible_ne_bloque_pas_les_suivantes(client, auth_headers, ia):
    """Une rencontre que l'IA n'arrive pas à lire reste « à analyser »
    sans empêcher la lecture des rencontres plus récentes."""
    _analyser_tout(client, auth_headers)
    ia.illisibles.add("Charabia Qsdfg")
    a = _importer(
        client, auth_headers, "Vieille rencontre", "2025-01-01",
        "Charabia Qsdfg : un texte que l'IA ne sait pas lire.",
    )
    _importer(
        client, auth_headers, "Hebdo après le charabia", "2026-03-02",
        "Phil : Pavage Vbnmq, la soumission est reçue.",
    )
    r = client.post("/api/v1/rencontres/dossiers/analyser", headers=auth_headers)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["analysees"] == 1 and d["restantes"] == 1, d
    assert [e["rencontre_id"] for e in d["echecs"]] == [a]
    assert _dossier(client, auth_headers, "Pavage Vbnmq") is not None


def test_sans_non_aborde_ne_garde_que_ce_qui_a_ete_dit():
    f = svc.sans_non_aborde
    assert f("La réception des électros pour Adam n'a pas été abordée.") is None
    assert f("Aucune mention de ce dossier lors de cette rencontre.") is None
    assert f("Point non abordé cette semaine.") is None
    assert f("Il n'a pas été question du déneigement.") is None
    assert f(None) is None and f("") is None
    assert (
        f(
            "Les portes seront installées mercredi, mais la date de "
            "réception des électros n'a pas été abordée."
        )
        == "Les portes seront installées mercredi."
    )
    assert (
        f("Le camion n'a pas été discuté mais Oli continue de chercher. Trois soumissions reçues.")
        == "Oli continue de chercher. Trois soumissions reçues."
    )
    # De vrais états de dossier : rien n'est retiré.
    for vrai in (
        "Deux candidats à rappeler.",
        "Le prêt n'a pas encore été discuté avec le banquier.",
        "Aucune nouvelle du couvreur.",
        "Les bugs n'ont pas été traités.",
    ):
        assert f(vrai) == vrai


def test_dossier_non_aborde_ne_change_pas_d_etat(client, auth_headers, ia):
    """En prod, l'IA a rendu des dossiers existants dont la deuxième
    rencontre ne parlait pas, avec « n'a pas été abordé » : c'est devenu
    leur dernier état. Une rencontre muette sur un dossier n'y touche pas."""
    a = _importer(
        client, auth_headers, "Hebdo M (non abordé)", "2026-04-06",
        "Phil : le Drainage Qwzxc avance, le plombier passe jeudi.",
    )
    _analyser_tout(client, auth_headers)
    avant = _dossier(client, auth_headers, "Drainage Qwzxc")
    assert avant is not None and avant["nb_rencontres"] == 1

    ia.bavarde = True
    _importer(
        client, auth_headers, "Hebdo N (non abordé)", "2026-04-13",
        "Mick : les Serrures Plmko, les portes seront posées mercredi.",
    )
    _analyser_tout(client, auth_headers)

    t = _dossier(client, auth_headers, "Drainage Qwzxc")
    assert t["statut"] == "en_cours"
    assert t["dernier_etat"] == "En marche."
    assert t["prochaine_action"] is None
    assert t["nb_rencontres"] == 1
    assert t["derniere_discussion"] == "2026-04-06"
    fiche = client.get(
        f"/api/v1/rencontres/dossiers/{t['id']}", headers=auth_headers
    ).json()
    assert [h["rencontre_id"] for h in fiche["historique"]] == [a]

    # Une phrase mixte garde ce qui a été dit.
    s = _dossier(client, auth_headers, "Serrures Plmko")
    assert s is not None
    assert s["dernier_etat"] == "Les portes seront posées mercredi."


def test_lecture_en_fond_suivie_par_l_ecran(client, auth_headers, ia):
    """L'écran lance la lecture en arrière-plan (réponse immédiate) et
    suit « analyse » dans la liste ; la rencontre illisible est sautée,
    pas retentée en boucle."""
    ia.illisibles.add("Baragouin Zxcvb")
    _importer(
        client, auth_headers, "Autre vieille rencontre", "2025-02-01",
        "Baragouin Zxcvb : encore un texte illisible.",
    )
    _importer(
        client, auth_headers, "Hebdo lue en fond", "2026-03-09",
        "Phil : Clôture Ghjkl, les poteaux sont livrés.",
    )
    r = client.post(
        "/api/v1/rencontres/dossiers/analyser",
        headers=auth_headers,
        params={"en_fond": True},
    )
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["en_fond"] is True and d["lancee"] is True, d
    assert d["ia_absente"] is False and d["restantes"] >= 2

    liste = {}
    for _ in range(300):
        r = client.get("/api/v1/rencontres/dossiers", headers=auth_headers)
        assert r.status_code == 200, r.text
        liste = r.json()
        if not liste["analyse"]["en_cours"]:
            break
    else:
        raise AssertionError("la lecture en fond ne se termine pas")
    assert liste["analyse"]["termine_le"]
    assert liste["analyse"]["echecs"] == 1, liste["analyse"]
    assert liste["analyse"]["analysees"] >= 1
    # L'illisible reste à lire ; le reste est fait.
    assert liste["rencontres_a_analyser"] == 1
    assert _dossier(client, auth_headers, "Clôture Ghjkl") is not None


def test_reserve_a_la_page_rencontres(client, employee_headers):
    for methode, chemin in (
        ("get", "/api/v1/rencontres/dossiers"),
        ("get", "/api/v1/rencontres/dossiers/doublons"),
        ("get", "/api/v1/rencontres/dossiers/ordre-du-jour"),
        ("post", "/api/v1/rencontres/dossiers/analyser"),
        ("post", "/api/v1/rencontres/dossiers/doublons/verifier"),
        ("get", "/api/v1/rencontres/consignes"),
    ):
        r = getattr(client, methode)(chemin, headers=employee_headers)
        assert r.status_code == 403, (chemin, r.status_code)
