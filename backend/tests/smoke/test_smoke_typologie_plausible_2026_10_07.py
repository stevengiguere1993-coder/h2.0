"""Smoke — typologie plausible (Phil 2026-10-07 : « l'extracteur avait
écrit 12 × 3.5 et 91 × 4.5, c'était juste 12 × 3.5 »). Jamais plus
d'unités que de logements, au parser local comme après la fusion avec
Gemini."""
from __future__ import annotations

from app.services import lead_extraction as ex


def test_parser_local_rejette_une_typologie_impossible():
    # 91 × 4 ½ pour un 12 logements : poste impossible → retiré.
    d = ex.parse_text("Rosemont, 12 logements. 12 x 3 ½ et 91 x 4 ½. Prix demandé 2 500 000 $")
    assert d["nb_logements"] == 12
    assert d["typology"] == {"3.5": 12}
    # Postes individuellement possibles mais somme > logements : typologie ignorée.
    d = ex.parse_text("12 logements. 8 x 3 ½ et 8 x 4 ½. Prix demandé 2 500 000 $")
    assert "typology" not in d and d["nb_logements"] == 12
    # Cohérent : conservé.
    d = ex.parse_text("12 logements. 8 x 3 ½ et 4 x 4 ½. Prix demandé 2 500 000 $")
    assert d["typology"] == {"3.5": 8, "4.5": 4}
    # Sans nombre de logements connu : la typologie le déduit (inchangé).
    d = ex.parse_text("6 x 3 ½ et 2 x 4 ½. Prix demandé 900 000 $")
    assert d["typology"] == {"3.5": 6, "4.5": 2} and d["nb_logements"] == 8


def test_fusion_garde_la_source_plausible():
    local = {"nb_logements": 12, "typology": {"4.5": 91}, "asking_price": 2_500_000}
    gemini = {"nb_logements": 12, "typology": {"3.5": 12}, "asking_price": 2_500_000}
    merged, warns, _n = ex._merge_local_gemini(local, gemini)
    assert merged["typology"] == {"3.5": 12}
    assert any("incohérente" in w for w in warns)
    # Les deux impossibles → aucune typologie plutôt qu'une fausse.
    merged, warns, _n = ex._merge_local_gemini(
        {"nb_logements": 12, "typology": {"4.5": 91}},
        {"nb_logements": 12, "typology": {"3.5": 40}},
    )
    assert "typology" not in merged and any("ignorée" in w for w in warns)
    # Cohérent des deux côtés : union MAX inchangée.
    merged, _w, _n = ex._merge_local_gemini(
        {"nb_logements": 12, "typology": {"3.5": 12}},
        {"nb_logements": 12, "typology": {"3.5": 12}},
    )
    assert merged["typology"] == {"3.5": 12}
