"""Garde-fou — le zip de l'extension servi par Kratos
(frontend/public/telechargements/extension-horizon-h2.zip, lien « Extension
Chrome » de Rôles fonciers, Phil 2026-09-30) doit être EXACTEMENT le contenu
de browser-extension/, et la version affichée celle du manifeste. Après une
modification de l'extension : régénérer le zip (script
scratchpad/lien_extension_2026_09_30.py ou équivalent) et la constante
EXTENSION_VERSION de la page."""
from __future__ import annotations

import json
import os
import re
import zipfile

RACINE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SRC = os.path.join(RACINE, "browser-extension")
ZIP = os.path.join(
    RACINE, "frontend", "public", "telechargements", "extension-horizon-h2.zip"
)
PAGE = os.path.join(
    RACINE, "frontend", "src", "app", "[locale]", "prospection",
    "immeubles-mtl", "page.tsx",
)


def _lf(b: bytes) -> bytes:
    return b.replace(b"\r\n", b"\n")


def test_zip_identique_au_dossier_de_l_extension():
    attendus = {}
    for racine, _, noms in os.walk(SRC):
        for n in noms:
            chemin = os.path.join(racine, n)
            rel = os.path.relpath(chemin, SRC).replace(os.sep, "/")
            attendus["extension-horizon-h2/" + rel] = _lf(open(chemin, "rb").read())
    with zipfile.ZipFile(ZIP) as z:
        contenus = {n: _lf(z.read(n)) for n in z.namelist()}
    assert set(contenus) == set(attendus)
    differents = [n for n in attendus if contenus[n] != attendus[n]]
    assert not differents, f"zip périmé, à régénérer : {differents}"


def test_version_affichee_egale_au_manifeste():
    version = json.load(open(os.path.join(SRC, "manifest.json"), encoding="utf-8"))["version"]
    page = open(PAGE, encoding="utf-8").read()
    m = re.search(r'const EXTENSION_VERSION = "([^"]+)"', page)
    assert m and m.group(1) == version
    h20 = open(os.path.join(SRC, "content-h20.js"), encoding="utf-8").read()
    assert f'window.__h2_extension = "{version}"' in h20
