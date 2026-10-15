"""Smoke — recherche automatique du courriel des courtiers (Phil
2026-10-14 : « il faut que ça soit automatique »).

Aucun réseau : Gemini, les moteurs web et la lecture des pages sont
remplacés. On vérifie :
- la notation (le courriel doit correspondre au NOM, les adresses
  génériques sont écartées), le nettoyage, l'extraction, les parseurs
  DuckDuckGo / Bing ;
- la recherche d'un courtier : courriel lu sur une page où son nom
  apparaît → « vérifié » avec la source ; page sans courriel nominatif →
  rien d'écrit, candidats écartés notés ;
- l'enrichissement en lot (fiche par fiche, TTL, rapport) ;
- les routes : lot en tâche de fond, fiche par fiche, saisie manuelle =
  vérifié, réglages ; le scan appelle l'enrichissement.
"""
from __future__ import annotations

import time
import types

import pytest

from app.api.v1.endpoints import prospection_courtiers as ep
from app.services import prospection_courtiers as svc
from app.services import prospection_courtiers_courriels as courriels
from tests.smoke.conftest import TestSessionLocal

BASE = "/api/v1/prospection/courtiers"
IDS: dict = {}
#: Vraie lecture de page (capturée AVANT que les fixtures la remplacent).
LIRE_PAGE_REELLE = courriels.lire_page


async def _rien(*a, **kw):
    return None


@pytest.fixture()
def sans_reseau(monkeypatch):
    """Ni Gemini ni moteurs ni pages : tout est simulé par le test."""
    monkeypatch.setattr(courriels, "_via_gemini", _rien)
    monkeypatch.setattr(courriels, "random", types.SimpleNamespace(uniform=lambda a, b: 0.0))

    async def _pas_de_web(*a, **kw):
        return []

    async def _pas_de_page(url):
        return "", []

    monkeypatch.setattr(courriels, "rechercher_web", _pas_de_web)
    monkeypatch.setattr(courriels, "lire_page", _pas_de_page)
    return monkeypatch


def test_notation_et_nettoyage():
    assert courriels.tokens_nom("Marc-André Knot") == ["marc", "andre", "knot"]
    assert courriels.tokens_nom("Denis Gallico, Maxime Gerard (Immo Alliances)") == ["denis", "gallico"]
    assert courriels.courriel_propre("Mailto:D.Gallico@ImmoAlliances.ca?subject=x") == "d.gallico@immoalliances.ca"
    assert courriels.courriel_propre("logo@2x.png") is None
    assert courriels.courriel_propre("x@centris.ca") is None
    s, r = courriels.score_courriel("d.gallico@immoalliances.ca", "Denis Gallico", "Immo Alliances")
    assert s >= 70 and "initiale et nom" in r
    s, _ = courriels.score_courriel("denis.gallico@remax-quebec.com", "Denis Gallico", None)
    assert s == 85
    s, _ = courriels.score_courriel("gallico@immoalliances.ca", "Denis Gallico", "Immo Alliances")
    assert s == 70  # nom de famille + domaine de l'agence
    s, r = courriels.score_courriel("info@immoalliances.ca", "Denis Gallico", "Immo Alliances")
    assert s == 10 and "générique" in r
    s, _ = courriels.score_courriel("marc.andre@immeublesgloria.com", "Marc-André Knot", None)
    assert s == 55  # prénom composé seul : accepté, mais au plancher
    s, _ = courriels.score_courriel("martin@autreagence.ca", "Denis Gallico", None)
    assert s < 55
    # Vrai cas rencontré : un gmail « amccote@ » n'est pas Marie Côté.
    s, r = courriels.score_courriel("amccote@gmail.com", "Marie Côté", "Sutton")
    assert s < 55 and "webmail" in r
    s, _ = courriels.score_courriel("marie.cote@gmail.com", "Marie Côté", None)
    assert s == 85  # prénom + nom : accepté même sur gmail
    s, _ = courriels.score_courriel("mcote@suttonquebec.com", "Marie Côté", "Sutton Québec")
    assert s >= 70  # initiale + nom, domaine de l'agence
    s, r = courriels.score_courriel("cote@quelconque.ca", "Marie Côté", None)
    assert s < 55 and "nom court" in r
    s, _ = courriels.score_courriel("gallico@quelconque.ca", "Denis Gallico", None)
    assert s == 60  # nom long (≥ 5 lettres) : accepté
    # Vrai cas : daniel@groupe-immosauve.com pour Daniel Sauvé.
    s, r = courriels.score_courriel("daniel@groupe-immosauve.com", "Daniel Sauvé", None)
    assert s >= 60 and "nom dans le domaine" in r
    assert courriels.extraire_courriels(
        "Joignez D.Gallico@immoalliances.ca ou info@immoalliances.ca — logo@2x.png",
        ["mailto:d.gallico@immoalliances.ca?subject=Info"],
    ) == ["d.gallico@immoalliances.ca", "info@immoalliances.ca"]


def test_courriel_coupe_ou_obfusque(run, sans_reseau):
    """Vrai cas prod : « rosibe</span>l@groupemackay.com » donnait
    « l@groupemackay.com » ; et « rosibel [at] groupemackay [dot] com »."""
    assert courriels.deobfusquer("rosibel [at] groupemackay [dot] com") == "rosibel@groupemackay.com"
    assert courriels.deobfusquer("rosibel (arobas) groupemackay.com") == "rosibel@groupemackay.com"
    assert courriels.extraire_courriels("Écrivez à rosibel [at] groupemackay [dot] com") == [
        "rosibel@groupemackay.com"
    ]

    html = ('<html><body><h1>Rosibel Martinez</h1><p>Courtier immobilier, Groupe Mackay</p>'
            '<p><span>rosibe</span><span>l@groupemackay.com</span></p></body></html>')

    async def _get(url, **kw):
        return 200, html

    sans_reseau.setattr(courriels, "_http_get", _get)
    # Vraie lire_page (réseau remplacé) : le texte collé rend le courriel entier.
    texte, mailtos = run(LIRE_PAGE_REELLE("https://groupemackay.com/equipe/rosibel"))
    trouves = courriels.extraire_courriels(texte, mailtos)
    assert "rosibel@groupemackay.com" in trouves
    assert "mackayrosibel@groupemackay.com" not in trouves  # pas recollé entre deux <p>

    # Recherche complète : prénom seul, mais le nom est sur la page → vérifié.
    async def _web(requete, **kw):
        return [{"url": "https://groupemackay.com/equipe/rosibel", "titre": "Rosibel Martinez", "extrait": ""}]

    sans_reseau.setattr(courriels, "rechercher_web", _web)
    sans_reseau.setattr(courriels, "lire_page", LIRE_PAGE_REELLE)
    res = run(courriels.chercher_courriel(_courtier("Rosibel Martinez"), config={}))
    assert res["courriel"] == "rosibel@groupemackay.com" and res["confiance"] == "verifie"


def test_resultats_pertinents_et_ordre_des_moteurs(run, monkeypatch):
    """Vrai cas prod : Bing, flairant un robot, renvoyait des horaires NFL
    pour « Daniel Sauvé » → lot jugé vide, moteur suivant."""
    jet = courriels.tokens_nom("Daniel Sauvé")
    bidon = [
        {"url": "https://www.espn.com/nfl/schedule/mnf", "titre": "Monday Night Football", "extrait": "NFL"},
        {"url": "https://ca.shein.com/pdsearch/47.55555", "titre": "Shein", "extrait": ""},
    ]
    bon = [{"url": "https://www.remax-quebec.com/fr/courtiers-immobiliers/daniel.sauve/index.rmx",
            "titre": "Daniel Sauvé — Courtier immobilier RE/MAX", "extrait": "514 555 1234"}]
    assert courriels.resultats_pertinents(bidon, jet) == []
    assert courriels.resultats_pertinents(bidon + bon, jet) == bon

    appels: list = []

    async def _get(url, **kw):
        appels.append(url)
        if "bing.com" in url:
            return 200, ('<ol><li class="b_algo"><h2><a href="https://www.espn.com/nfl/schedule/mnf">'
                         "Monday Night Football</a></h2><p>NFL</p></li></ol>")
        return 200, "<html></html>"

    async def _vps(requete, max_results=8, must_contain=None):
        appels.append("vps")
        assert must_contain == ["daniel", "sauve"]
        # Le VPS peut renvoyer un lien de redirection : décodé côté backend.
        return [{"url": "https://duckduckgo.com/l/?uddg=" + bon[0]["url"].replace(":", "%3A").replace("/", "%2F"),
                 "titre": bon[0]["titre"], "extrait": ""}]

    from app.integrations import scraping_proxy

    monkeypatch.setattr(courriels, "_http_get", _get)
    monkeypatch.setattr(scraping_proxy, "vps_available", lambda: True)
    monkeypatch.setattr(scraping_proxy, "scrape_web_search", _vps)
    journal: list = []
    # Ordre : direct (bing bidon) puis vps → le VPS gagne ; sans clé, google est sauté.
    res = run(courriels.rechercher_web("Daniel Sauvé courtier", moteurs=("google", "bing", "vps"),
                                       jetons=jet, journal=journal))
    assert res == [{"url": bon[0]["url"], "titre": bon[0]["titre"], "extrait": ""}]
    assert any("moteur bing : 1 résultat(s), 0 pertinent(s)" in l for l in journal)
    assert any(l.startswith("moteur vps : 1 résultat(s), 1 pertinent(s)") for l in journal)
    assert courriels.MOTEURS_WEB_DEFAUT[0] == "google" and courriels.MOTEURS_WEB_DEFAUT[1] == "vps"


def test_parseurs_moteurs():
    ddg = """<div class="results">
      <div class="result"><a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.immoalliances.ca%2Fequipe%2Fdenis-gallico&amp;rut=abc">Denis Gallico – Immo Alliances</a>
        <a class="result__snippet">Denis Gallico, courtier immobilier. d.gallico@immoalliances.ca · 514 206-5468</a></div>
      <div class="result"><a class="result__a" href="https://www.centris.ca/fr/courtier-immobilier~denis-gallico/123">Centris</a></div>
    </div>"""
    res = courriels.parser_duckduckgo(ddg)
    assert res[0]["url"] == "https://www.immoalliances.ca/equipe/denis-gallico"
    assert "d.gallico@immoalliances.ca" in res[0]["extrait"]
    assert res[1]["url"].startswith("https://www.centris.ca")
    bing = """<ol id="b_results"><li class="b_algo"><h2><a href="https://www.remax-quebec.com/fr/courtiers-immobiliers/francois.courval/index.rmx">François Courval</a></h2>
      <div class="b_caption"><p>François Courval, courtier immobilier résidentiel RE/MAX. fcourval@remax-quebec.com</p></div></li></ol>"""
    # Redirection Bing : l'URL réelle est encodée en base64 dans « u=a1… ».
    redir = ("https://www.bing.com/ck/a?!&&p=abc&u=a1"
             + "aHR0cHM6Ly9jb250YWN0b3V0LmNvbS9BbXktQXNzYWFkLTI1NzQ0NzAw" + "&ntb=1")
    assert courriels.decoder_redirection_bing(redir) == "https://contactout.com/Amy-Assaad-25744700"
    assert courriels.decoder_redirection_bing("https://www.remax-quebec.com/x") == "https://www.remax-quebec.com/x"
    assert courriels.decoder_redirection(
        "https://duckduckgo.com/l/?uddg=https%3A%2F%2Fdanielsauve.ca%2F&rut=9cd114"
    ) == "https://danielsauve.ca/"
    assert courriels.decoder_redirection(redir) == "https://contactout.com/Amy-Assaad-25744700"
    res = courriels.parser_bing(bing)
    assert res == [{
        "url": "https://www.remax-quebec.com/fr/courtiers-immobiliers/francois.courval/index.rmx",
        "titre": "François Courval",
        "extrait": "François Courval, courtier immobilier résidentiel RE/MAX. fcourval@remax-quebec.com",
    }]


def _courtier(nom, agence=None, secteur=None):
    from app.models.prospection_courtier import ProspectionCourtier

    return ProspectionCourtier(nom=nom, agence=agence, secteur=secteur, cle_dedup=svc.normaliser_cle(nom))


def test_recherche_un_courtier_verifie(run, sans_reseau):
    page_url = "https://www.immoalliances.ca/equipe/denis-gallico"

    async def _web(requete, **kw):
        assert "Denis Gallico" in requete
        assert kw.get("jetons") == ["denis", "gallico"]
        return [
            {"url": "https://www.centris.ca/fr/courtier~denis-gallico/1", "titre": "Centris", "extrait": ""},
            {"url": page_url, "titre": "Denis Gallico – Immo Alliances", "extrait": "Courtier immobilier"},
            {"url": "https://www.facebook.com/x", "titre": "Facebook", "extrait": "pas ici"},
        ]

    lues: list = []

    async def _page(url):
        lues.append(url)
        if url == page_url:
            return (
                "Denis Gallico Courtier immobilier Immo Alliances Téléphone 514 206-5468 "
                "Courriel d.gallico@immoalliances.ca Bureau info@immoalliances.ca",
                ["mailto:d.gallico@immoalliances.ca"],
            )
        return "", []

    sans_reseau.setattr(courriels, "rechercher_web", _web)
    sans_reseau.setattr(courriels, "lire_page", _page)
    journal: list = []
    res = run(courriels.chercher_courriel(
        _courtier("Denis Gallico", "Immo Alliances", "Montréal"), config={}, journal=journal
    ))
    assert any(l.startswith("gemini : rien") for l in journal)
    assert any("web «" in l and "3 résultat(s)" in l for l in journal)
    assert any(l.startswith("page https://www.immoalliances.ca") for l in journal)
    assert any("candidat d.gallico@immoalliances.ca" in l for l in journal)
    assert res["courriel"] == "d.gallico@immoalliances.ca"
    assert res["confiance"] == "verifie"
    assert res["source"] == page_url
    assert "info@immoalliances.ca" in res["ecartes"]
    assert lues == [page_url]  # Centris et Facebook jamais ouverts
    assert "web" in res["methode"]


def test_sites_de_recherche_de_personnes_ignores(run, sans_reseau):
    """Vrai cas : ssantangelo@att.net sur veripages.com (États-Unis) marqué
    « vérifié » pour Salvator Santangelo — ces sites sont ignorés."""
    async def _web(requete, **kw):
        return [{"url": "https://veripages.com/name/Salvatore/Santangelo/", "titre": "Salvatore Santangelo",
                 "extrait": "ssantangelo@att.net"}]

    lues: list = []

    async def _page(url):
        lues.append(url)
        return "Salvatore Santangelo ssantangelo@att.net", []

    sans_reseau.setattr(courriels, "rechercher_web", _web)
    sans_reseau.setattr(courriels, "lire_page", _page)
    journal: list = []
    res = run(courriels.chercher_courriel(_courtier("Salvator Santangelo"), config={}, journal=journal))
    assert res["courriel"] is None
    assert lues == []  # la page n'est même pas ouverte
    assert any("site de recherche de personnes" in l for l in journal)


def test_recherche_un_courtier_sans_resultat_nominatif(run, sans_reseau):
    async def _web(requete, **kw):
        return [{"url": "https://www.sutton.com/bureau", "titre": "Sutton", "extrait": "info@sutton.com"}]

    async def _page(url):
        return "Sutton Québec — info@sutton.com — Nos courtiers", ["mailto:info@sutton.com"]

    sans_reseau.setattr(courriels, "rechercher_web", _web)
    sans_reseau.setattr(courriels, "lire_page", _page)
    res = run(courriels.chercher_courriel(_courtier("Marie Côté", "Sutton"), config={}))
    assert res["courriel"] is None and res["confiance"] is None
    assert res["ecartes"] == ["info@sutton.com"]
    assert "aucun courriel au nom du courtier" in res["note"]


def test_recherche_gemini_relu_sur_la_page(run, sans_reseau):
    """Gemini propose un courriel + une source ; on relit la page : si le
    nom et le courriel y sont, c'est « vérifié »."""
    async def _gemini(nom, agence, secteur):
        return {"courriel": "fcourval@remax-quebec.com", "telephone": "450 555-1234",
                "site_web": None, "source_url": "https://www.remax-quebec.com/fr/courtiers/francois.courval",
                "sources": [], "modele": "gemini-test"}

    async def _page(url):
        return "François Courval courtier immobilier RE/MAX fcourval@remax-quebec.com", []

    sans_reseau.setattr(courriels, "_via_gemini", _gemini)
    sans_reseau.setattr(courriels, "lire_page", _page)
    res = run(courriels.chercher_courriel(_courtier("François Courval", "RE/MAX"), config={}))
    assert res["courriel"] == "fcourval@remax-quebec.com" and res["confiance"] == "verifie"
    assert res["telephone"] == "450 555-1234"
    assert res["methode"].startswith("gemini:")


def test_enrichissement_en_lot(run, db_setup, sans_reseau):
    async def _seed():
        async with TestSessionLocal() as s:
            a, _ = await svc.upsert_courtier(s, nom="Ursule Testmail", agence="Via Capitale", source="manuel")
            b, _ = await svc.upsert_courtier(s, nom="Ovide Sanscourriel", source="manuel")
            await s.commit()
            return a.id, b.id

    IDS["ursule"], IDS["ovide"] = run(_seed())

    async def _chercher(c, *, config=None, journal=None):
        if "Ursule" in c.nom:
            return {"courriel": "ursule.testmail@viacapitale.com", "confiance": "probable",
                    "source": "https://viacapitale.com/ursule", "telephone": "514 555 2222",
                    "site_web": "https://ursule.ca", "note": "prénom et nom — 2 page(s) lue(s)",
                    "methode": "web", "ecartes": []}
        return {"courriel": None, "confiance": None, "source": None, "telephone": None,
                "site_web": None, "note": "aucun courriel au nom du courtier — 3 page(s) lue(s)",
                "methode": "web", "ecartes": ["info@x.ca"]}

    sans_reseau.setattr(courriels, "chercher_courriel", _chercher)

    async def _lot(**kw):
        async with TestSessionLocal() as s:
            r = await courriels.enrichir_courriels(s, config=dict(svc.DEFAUTS), max_courtiers=50, **kw)
            await s.commit()
            return r

    r = run(_lot(courtier_ids=[IDS["ursule"], IDS["ovide"]]))
    assert r["examines"] == 2 and r["trouves"] == 1 and r["probables"] == 1 and r["sans_resultat"] == 1

    async def _lire():
        async with TestSessionLocal() as s:
            from app.models.prospection_courtier import ProspectionCourtier

            a = await s.get(ProspectionCourtier, IDS["ursule"])
            b = await s.get(ProspectionCourtier, IDS["ovide"])
            return (a.courriel, a.courriel_confiance, a.courriel_source, a.telephone, a.site_web,
                    a.courriel_cherche_le is not None, b.courriel, b.courriel_recherche_note)

    etat = run(_lire())
    assert etat[:5] == ("ursule.testmail@viacapitale.com", "probable", "https://viacapitale.com/ursule",
                        "514-555-2222", "https://ursule.ca")
    assert etat[5] is True and etat[6] is None and "aucun courriel" in etat[7]
    # Sans ids : Ovide vient d'être cherché → sauté (TTL), Ursule a un courriel → pas candidat.
    r2 = run(_lot())
    assert r2["examines"] == 0 or all(d["id"] not in (IDS["ursule"], IDS["ovide"]) for d in r2["details"])
    assert r2["sautes_recemment_cherches"] >= 1


def test_routes_courriels(client, auth_headers, monkeypatch, sans_reseau):
    monkeypatch.setattr(ep, "_session_factory_jobs", lambda: TestSessionLocal)
    ovide = IDS["ovide"]

    async def _chercher(c, *, config=None, journal=None):
        return {"courriel": "ovide.sanscourriel@royallepage.ca", "confiance": "verifie",
                "source": "https://www.royallepage.ca/fr/agent/ovide", "telephone": None, "site_web": None,
                "note": "prénom et nom — 1 page(s) lue(s)", "methode": "web", "ecartes": []}

    monkeypatch.setattr(courriels, "chercher_courriel", _chercher)

    # Fiche par fiche (synchrone).
    r = client.post(f"{BASE}/{ovide}/chercher-courriel", headers=auth_headers)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["courriel"] == "ovide.sanscourriel@royallepage.ca"
    assert d["courriel_confiance"] == "verifie"
    assert d["courriel_source"].startswith("https://www.royallepage.ca")

    # Lot en tâche de fond (forcer : il a déjà un courriel → « trouvé aussi »).
    r = client.post(f"{BASE}/courriels/chercher", headers=auth_headers,
                    json={"courtier_ids": [ovide], "max": 5, "forcer": True})
    assert r.status_code == 200, r.text
    job = r.json()["job_id"]
    etat = None
    for _ in range(200):
        etat = client.get(f"{BASE}/scan/{job}", headers=auth_headers).json()
        if etat["status"] != "en_cours":
            break
        time.sleep(0.05)
    assert etat and etat["status"] == "termine", etat
    assert etat["resultat"]["courriels"]["examines"] == 1

    # Diagnostic : rejoue sans écrire, renvoie le journal.
    r = client.post(f"{BASE}/{ovide}/chercher-courriel/diagnostic", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["courtier"]["id"] == ovide and isinstance(r.json()["journal"], list)
    assert r.json()["resultat"]["courriel"] == "ovide.sanscourriel@royallepage.ca"

    # Saisie manuelle : la référence, « vérifié ».
    r = client.patch(f"{BASE}/{ovide}", headers=auth_headers, json={"courriel": "Ovide@Perso.ca"})
    assert r.status_code == 200, r.text
    assert r.json()["courriel"] == "ovide@perso.ca"
    assert r.json()["courriel_confiance"] == "verifie"
    assert r.json()["courriel_source"] == "saisi à la main"
    r = client.patch(f"{BASE}/{ovide}", headers=auth_headers, json={"courriel": ""})
    assert r.json()["courriel"] is None and r.json()["courriel_source"] is None
    assert r.json()["courriel_confiance"] is None
    client.patch(f"{BASE}/{ovide}", headers=auth_headers, json={"courriel": "ovide@perso.ca"})

    # Réglages exposés.
    p = client.get(f"{BASE}/parametres", headers=auth_headers).json()["config"]
    assert p["recherche_courriels_auto"] is True and p["max_courriels_par_scan"] == 20
    assert p["recherche_courriel_ttl_jours"] == 30
    r = client.put(f"{BASE}/parametres", headers=auth_headers, json={"recherche_courriels_auto": False})
    assert r.json()["config"]["recherche_courriels_auto"] is False
    client.put(f"{BASE}/parametres", headers=auth_headers, json={"recherche_courriels_auto": True})


def test_scan_enchaine_la_recherche_des_courriels(client, auth_headers, monkeypatch, sans_reseau):
    monkeypatch.setattr(ep, "_session_factory_jobs", lambda: TestSessionLocal)
    appels: list = []

    async def _enrichir(db, *, config, courtier_ids=None, max_courtiers=20, forcer=False, progres=None):
        appels.append(max_courtiers)
        return {"examines": 0, "trouves": 0, "verifies": 0, "probables": 0,
                "sans_resultat": 0, "sautes_recemment_cherches": 0, "erreurs": [], "details": []}

    monkeypatch.setattr(courriels, "enrichir_courriels", _enrichir)
    r = client.post(f"{BASE}/scan", headers=auth_headers, json={"vps": False})
    job = r.json()["job_id"]
    etat = None
    for _ in range(200):
        etat = client.get(f"{BASE}/scan/{job}", headers=auth_headers).json()
        if etat["status"] != "en_cours":
            break
        time.sleep(0.05)
    assert etat and etat["status"] == "termine", etat
    assert appels == [20]
    assert "courriels" in etat["resultat"]
