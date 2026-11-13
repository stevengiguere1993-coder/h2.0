"""Smoke — questions à Kratos sur TOUTES les rencontres (2026-11-13).

Steven : « si je pose une question à Kratos sur un élément, il doit être
capable de regarder dans chacune des rencontres et me dire si nous avons
discuté de quelque chose ou l'avancement d'un dossier ».
"""
from __future__ import annotations

from datetime import date

from app.models.rencontre import Rencontre
from app.services.rencontre_recherche import (
    Passage,
    _tranches,
    mots_cles,
    noter_passages,
    reponse_sans_ia,
)


def test_mots_cles_retire_mots_vides_et_meta():
    mots = mots_cles(
        "Est-ce qu'on a discuté du déneigement de Saint-Clément dans les "
        "rencontres ? Où en est le dossier P9 ?"
    )
    assert "deneigement" in mots
    assert "saint" in mots and "clement" in mots
    assert "p9" in mots
    for meta in ("discute", "rencontre", "dossier", "est"):
        assert meta not in mots


def test_mots_cles_pluriel_et_accents():
    assert mots_cles("Les LOCATAIRES électros") == ["locataire", "electro"]
    assert mots_cles("travaux zorblax") == ["travau", "zorblax"]


def test_tranches_coupe_les_longs_textes():
    texte = "Phrase numéro un. " * 200
    t = _tranches(texte, taille=300)
    assert len(t) > 5
    assert all(len(x) <= 300 for x in t)


def _p(rid: int, d: date, typ: str, texte: str) -> Passage:
    return Passage(
        rencontre_id=rid,
        rencontre_titre=f"Rencontre {rid}",
        rencontre_date=d,
        section=None,
        type=typ,
        texte=texte,
    )


def test_noter_prefere_les_passages_qui_couvrent_tous_les_mots():
    ps = [
        _p(1, date(2026, 10, 1), "transcript", "On parle du camion aujourd'hui."),
        _p(1, date(2026, 10, 1), "decision", "Achat du camion chez le concessionnaire Ford."),
        _p(2, date(2026, 10, 8), "transcript", "Les locataires d'Adam paient."),
    ]
    trouves = noter_passages(ps, mots_cles("camion concessionnaire"))
    assert [p.texte for p in trouves][0].startswith("Achat du camion")
    assert all("Adam" not in p.texte for p in trouves)


def test_reponse_sans_ia_liste_les_sources():
    ps = [_p(7, date(2026, 10, 26), "action", "Relancer Olivia — responsable : Zach")]
    txt = reponse_sans_ia("Olivia", ps)
    assert "Rencontre #7" in txt and "Relancer Olivia" in txt
    assert "Je ne trouve pas" in reponse_sans_ia("x", [])


def _importer(client, auth_headers, titre: str, jour: str, texte: str) -> int:
    r = client.post(
        "/api/v1/rencontres/importer",
        headers=auth_headers,
        data={"texte": texte, "title": titre, "meeting_date": jour},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_recherche_et_question_sur_toutes_les_rencontres(client, auth_headers):
    a = _importer(
        client,
        auth_headers,
        "Hebdo octobre (smoke recherche)",
        "2026-10-05",
        "Steven : pour le Zorblax de la rue Kennedy, on attend la "
        "soumission du couvreur.\nPhil : je relance la semaine prochaine.",
    )
    b = _importer(
        client,
        auth_headers,
        "Hebdo novembre (smoke recherche)",
        "2026-11-02",
        "Phil : la soumission du couvreur pour le Zorblax est arrivée, "
        "on signe lundi.\nSteven : parfait.",
    )
    # Une rencontre sans rapport ne doit pas sortir.
    _importer(
        client,
        auth_headers,
        "Autre sujet (smoke recherche)",
        "2026-11-03",
        "On parle de la paie et des vacances de Noël.",
    )

    r = client.get(
        "/api/v1/rencontres/recherche",
        headers=auth_headers,
        params={"q": "Où en est le dossier Zorblax ?"},
    )
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["mots_cles"] == ["zorblax"]
    ids = [x["rencontre_id"] for x in d["rencontres_trouvees"]]
    assert ids == [a, b]  # ordre chronologique
    assert all("Zorblax" in p["extrait"] for p in d["passages"])

    r = client.post(
        "/api/v1/rencontres/demander",
        headers=auth_headers,
        json={"question": "A-t-on discuté du Zorblax ?"},
    )
    assert r.status_code == 200, r.text
    d = r.json()
    assert [s["rencontre_id"] for s in d["sources"]] == [a, b]
    assert d["reponse"]

    r = client.post(
        "/api/v1/rencontres/demander",
        headers=auth_headers,
        json={"question": "A-t-on parlé du Quuxifor ?"},
    )
    assert r.status_code == 200
    assert r.json()["sources"] == []
    assert "aucune mention" in r.json()["reponse"].lower()


def test_recherche_reservee_a_la_page_rencontres(client, employee_headers):
    r = client.get(
        "/api/v1/rencontres/recherche",
        headers=employee_headers,
        params={"q": "Zorblax"},
    )
    assert r.status_code == 403
    r = client.post(
        "/api/v1/rencontres/demander",
        headers=employee_headers,
        json={"question": "Zorblax ?"},
    )
    assert r.status_code == 403


def test_modele_inchange():
    # Aucune colonne ajoutée : la recherche lit les champs existants.
    assert {"global_summary", "notes", "entreprise_ids_json"} <= set(
        Rencontre.__table__.columns.keys()
    )


def test_centre_d_aide_recoit_les_passages_des_rencontres(
    client, auth_headers, employee_headers, monkeypatch
):
    """La question posée au Centre d'aide reçoit les passages des
    rencontres — pour qui voit la page Rencontres seulement."""
    from app.api.v1.endpoints import help as help_ep
    from app.integrations.ai._base import CompletionResult

    recu: list[str] = []

    async def faux_chat(*, messages, **_kw):
        recu.append(messages[-1].content)
        return CompletionResult(text="ok", model="test", provider="test")

    monkeypatch.setattr(help_ep, "chat", faux_chat)
    _importer(
        client,
        auth_headers,
        "Hebdo aide (smoke recherche)",
        "2026-11-09",
        "Steven : le Blivetron du 710 Legendre est commandé, livraison jeudi.",
    )
    r = client.post(
        "/api/v1/help/ask",
        headers=auth_headers,
        json={"question": "Où en est le Blivetron ?"},
    )
    assert r.status_code == 200, r.text
    assert "Blivetron du 710 Legendre" in recu[-1]
    assert "Rencontre #" in recu[-1]

    r = client.post(
        "/api/v1/help/ask",
        headers=employee_headers,
        json={"question": "Où en est le Blivetron ?"},
    )
    assert r.status_code == 200, r.text
    assert "710 Legendre" not in recu[-1]
