"""Une ligne de facture n'est jamais rattachée à une CATÉGORIE de Produits
et services QB (facture 160, 2026-10-17 : refus 2500 « un élément est
configuré comme une catégorie au lieu d'un produit ou d'un service »)."""

import asyncio
from typing import Any, Dict, List

from app.integrations.quickbooks import QuickBooksClient


class _QB(QuickBooksClient):
    def __init__(self, items: List[Dict[str, Any]]) -> None:
        self.items = items
        self.crees: List[str] = []

    async def query(self, q: str) -> List[Dict[str, Any]]:
        nom = q.split("Name = '", 1)[1].split("'", 1)[0]
        return [i for i in self.items if i["Name"] == nom]

    async def create_item(self, name: str, description: Any = None) -> Dict[str, Any]:
        self.crees.append(name)
        item = {"Id": str(100 + len(self.crees)), "Name": name, "Type": "Service"}
        self.items.append(item)
        return item


def test_categorie_jamais_choisie():
    qb = _QB([{"Id": "7", "Name": "Matériaux", "Type": "Category"}])
    item = asyncio.run(qb.ensure_item("Matériaux"))
    assert item["Type"] == "Service"
    assert qb.crees == ["Matériaux (service)"]
    assert asyncio.run(qb.find_item_by_name("Matériaux")) is None
    # Envoi suivant : le même service est réutilisé.
    assert asyncio.run(qb.ensure_item("Matériaux"))["Id"] == item["Id"]
    assert qb.crees == ["Matériaux (service)"]


def test_service_existant_garde_son_nom():
    qb = _QB(
        [
            {"Id": "7", "Name": "Matériaux", "Type": "Category"},
            {"Id": "8", "Name": "Matériaux", "Type": "Service"},
        ]
    )
    assert asyncio.run(qb.ensure_item("Matériaux"))["Id"] == "8"
    assert qb.crees == []


def test_nom_libre_cree_tel_quel():
    qb = _QB([])
    asyncio.run(qb.ensure_item("Main-d'œuvre"))
    assert qb.crees == ["Main-d'œuvre"]
