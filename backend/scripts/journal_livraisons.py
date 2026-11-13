"""Régénère ``app/data/journal_livraisons.tsv`` à partir de l'historique git.

Le Centre d'aide (« Question ») s'en sert pour dire si une
fonctionnalité existe ou si un problème a déjà été corrigé, et quand.
Chaque ligne : ``AAAA-MM-JJ<TAB>sujet du commit``, du plus récent au
plus ancien, sans les commits de service (chore, test, docs, revert,
merge, relance de déploiement).

Usage (depuis la racine du dépôt, historique complet requis) :

    git fetch --unshallow origin  # si le clone est superficiel
    python backend/scripts/journal_livraisons.py [réf]   # défaut origin/main
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

SORTIE = Path(__file__).resolve().parents[1] / "app" / "data" / "journal_livraisons.tsv"
_BRUIT = re.compile(
    r"^(chore|test|tests|docs|wip|style|ci|build|revert|merge)\b|^Revert |^Merge |relance du déploiement",
    re.IGNORECASE,
)


def main() -> int:
    ref = sys.argv[1] if len(sys.argv) > 1 else "origin/main"
    sortie = subprocess.run(
        ["git", "log", "--no-merges", "--date=short", "--format=%ad%x09%s", ref],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    lignes = []
    vus = set()
    for ligne in sortie.splitlines():
        date, _, sujet = ligne.partition("\t")
        sujet = sujet.strip()
        if not sujet or _BRUIT.search(sujet) or sujet in vus:
            continue
        vus.add(sujet)
        lignes.append(f"{date}\t{sujet}")
    SORTIE.write_text("\n".join(lignes) + "\n", encoding="utf-8")
    print(f"{len(lignes)} livraisons écrites dans {SORTIE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
