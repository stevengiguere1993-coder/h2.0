# Spec — Moteur d'analyse financière de leads (Phase 3)

> Cible : répliquer **exactement** les calculs de `CALCULATEUR_OFFICIEL.xlsm`
> (sans abordabilité) et `CALCULATEUR_OFFICIEL_APH_SELECT.xlsm` (avec
> abordabilité). Le fichier `21f6e948-3845_boulevard_SaintJoseph_Est_Montréal.xlsm`
> sert de cas de test (valeurs attendues).

Deux calculateurs distincts, **majoritairement identiques** sur la
mécanique du financement. Le APH SELECT ajoute une variante refi
« Efficacité + abord » avec ratio prêt/valeur plus généreux (95 %)
et un amortissement de 50 ans, contre 0,85 / 40 ans en mode SCHL
standard.

---

## 1. Inputs (saisis par l'utilisateur)

| Clé technique                | Cellule | Libellé                                   | Type    | Exemple St-Joseph |
|------------------------------|---------|--------------------------------------------|---------|-------------------|
| `adresse`                    | B3      | Adresse                                    | str     | « 3845, boulevard Saint-Joseph Est, Montréal » |
| `prix_achat`                 | B4      | Prix d'achat                               | $       | 1 699 000         |
| `nombre_logements`           | B6      | Nombre de logements                        | int     | 8                 |
| `revenus_annuels`            | B7      | Revenus annuels (loyers bruts)             | $/an    | 103 992           |
| `taxes_municipales`          | B8      |                                            | $/an    | 10 349            |
| `taxes_scolaires`            | B9      |                                            | $/an    | 805               |
| `assurances`                 | B10     |                                            | $/an    | 4 655             |
| `energie`                    | B11     | Énergie payée par le propriétaire          | $/an    | 221               |
| `depenses_autres`            | B12     | Autres dépenses                            | $/an    | 0                 |
| `tga`                        | B13     | Taux global d'actualisation (cap rate)     | %       | 0,04 (4 %)        |
| `taux_interet_achat`         | B14     | Taux d'intérêt prêt à l'achat              | %       | 0,04              |
| `nb_logements_ajoutes`       | D4      | Logements à ajouter au refi                | int     | 0                 |
| `nb_thermopompes_ajoutees`   | D5      | Thermopompes ajoutées (refi)               | int     | 2                 |
| `wifi_ajoute`                | D6      | « Oui » / « Non » (Wifi inclus refi)       | bool    | Oui               |
| `reduction_energie_pct`      | D7      | % réduction du poste énergie (refi)        | %       | 0                 |
| `nouveau_loyer_moyen`        | D8      | Nouveau loyer/mois après refi (officiel)   | $/mois  | 1 500             |
| `taux_interet_refi`          | D9 / D10| Taux refi SCHL & APH (mêmes 2 colonnes)    | %       | 0,0375            |
| `duree_projet_annees`        | L3 / K3 | Durée du projet (pour intérêts pendant…)   | int     | 2                 |
| `frais_developpement`        | L14     | Frais développement (input)                | $       | 80 000            |
| `frais_negociations`         | L15     | Frais négociation                          | $       | 80 000            |
| `frais_travaux`              | L16     | Coût des travaux                           | $       | 160 000           |
| `typologie[*]`               | G6..G12 | Nb logements par typo (2,5 à 8,5)          | int     | { 3,5: 4, 4,5: 4 }|
| `typologie_prix[*]`          | H6..H12 | Prix loyer par typo                        | $/mois  | { 3,5: 1400, 4,5: 1600 } |

### Inputs spécifiques au **APH SELECT** (avec abordabilité)
| Clé technique                | Cellule | Libellé                                   | Exemple Salaberry |
|------------------------------|---------|--------------------------------------------|-------------------|
| `nb_logements_abordables`    | E8      | Nbr logements en zone abordable            | 14                |
| `nouveau_loyer_abordable`    | D8      | $/mois loyer abordable                     | 1 090             |
| `nouveau_loyer_pdm`          | D9      | $/mois loyer prix du marché (PDM)          | 1 400             |

### Barème de dépenses normalisées (`K36..K44` — constantes du modèle)
```python
BAREME = {
    "concierge_lt12":  215.0,   # $ / log / an, immeubles <12 log
    "concierge_gte12": 365.0,   # $ / log / an, immeubles 12+ log
    "entretien":       610.0,   # $ / log / an
    "gestion_lt12":    0.0425,  # % revenus, <12 log
    "gestion_gte12":   0.05,    # % revenus, 12+ log
    "wifi_par_log":    5.0,     # $ / log / mois
    "internet_fixe":   120.0,   # $ / mois (1 connexion par bâtiment)
    "thermopompe":     190.0,   # $ / thermopompe / an (entretien)
}
```

---

## 2. Frais de démarrage / optimisation (`L4..L19`) — feed `B5`

Le bloc K3-L19 calcule **automatiquement** les frais de démarrage, dont
le total est injecté en B5 (input "Frais démarrage/optimisation").

| Ligne | Clé                          | Formule                                                              |
|-------|-------------------------------|----------------------------------------------------------------------|
| L3    | `duree_projet_annees`        | (input, ex. 2)                                                       |
| L4    | `courtier_hypothecaire_1`    | `0.01 * prix_achat`                                                  |
| L5    | `courtier_hypothecaire_2`    | `0.01 * pret_accorde_refi_APH` (= cellule D23 dans Excel)            |
| L6    | `taxes_bienvenue`            | Barème Montréal progressif (tiers à 0,5 % / 1 % / 1,5 % / 2 % / 2,5 % / 3,5 % / 4 %) |
| L7    | `evaluateur`                 | 1 500                                                                |
| L8    | `evaluateur_2`               | 1 500                                                                |
| L9    | `inspection`                 | 1 700                                                                |
| L10   | `avocat`                     | 4 000                                                                |
| L11   | `notaire`                    | 1 600                                                                |
| L12   | `notaire_2`                  | 1 600                                                                |
| L13   | `rapport_efficacite`         | 4 500                                                                |
| L14   | `frais_developpement`        | (input)                                                              |
| L15   | `frais_negociations`         | (input)                                                              |
| L16   | `frais_travaux`              | (input)                                                              |
| L17   | `interets_pendant_projet`    | `0.75 * prix_achat * 0.08 * duree_projet_annees` (75 % LTV × 8 %)    |
| L18   | `revenus_nets_pendant_projet`| `-revenus_nets_initial * duree_projet_annees` (négatif si net négatif)|
| L19   | **`total_frais_demarrage`**  | `Σ L4..L18` → renvoyé en `B5`                                        |

### Taxes de bienvenue Montréal (tiers cumulatifs 2024-2025)
```
0       → 61 500    : 0,5 %
61 500  → 307 800   : 1,0 %
307 800 → 552 300   : 1,5 %
552 300 → 1 104 700 : 2,0 %
1 104 700 → 2 136 500 : 2,5 %
2 136 500 → 3 113 000 : 3,5 %
3 113 000 +          : 4,0 %
```

---

## 3. Calculs (3 colonnes : Achat / Refi SCHL / Refi APH ou Efficacité)

Pour chaque colonne, on calcule la **valeur économique** par 2 méthodes
(TGA et RCD), on prend la plus basse, on capant éventuellement à la
valeur marchande pour la colonne Achat. Cette valeur retenue × ratio
prêt/valeur donne le montant de financement.

### Constantes par colonne

| Colonne   | Ratio prêt/valeur | Amortissement | RCD  | Taux             |
|-----------|-------------------|----------------|------|------------------|
| B: Achat  | 0,75              | 25 ans         | 1,20 | `taux_interet_achat` |
| C: SCHL   | 0,85              | 35 ans         | 1,30 | `taux_interet_refi`  |
| D: APH50  | 0,85              | 40 ans         | 1,10 | `taux_interet_refi`  |
| D: APH SELECT (Efficacité+abord) | 0,95 | 50 ans | 1,10 | `taux_interet_refi` |

### Pipeline de calcul (pour une colonne)

```python
# Étape 1 — Constructon du prix
prix_acquisition = prix_achat + frais_demarrage
# (frais_demarrage = L19 calculé plus haut)

# Étape 2 — Nombre de logements et loyer
if colonne == "achat":
    nb_log = nombre_logements
    loyer_mois = revenus_annuels / 12 / nb_log
    revenus_totaux = revenus_annuels
elif colonne == "refi_schl":
    nb_log = nombre_logements + nb_logements_ajoutes
    loyer_mois = nouveau_loyer_moyen
    revenus_totaux = loyer_mois * nb_log * 12
elif colonne == "refi_aph":  # ou APH SELECT
    nb_log = nombre_logements + nb_logements_ajoutes
    if APH_SELECT:
        # Mix abordable + PDM
        rev_abord = nb_logements_abordables * nouveau_loyer_abordable
        nb_pdm = nb_log - nb_logements_abordables
        rev_pdm = nb_pdm * nouveau_loyer_pdm
        loyer_mois = (rev_abord + rev_pdm) / nb_log
    else:
        loyer_mois = nouveau_loyer_moyen
    revenus_totaux = loyer_mois * nb_log * 12

# Étape 3 — Dépenses normalisées
inoccupation = 0.03 * revenus_totaux
taxes_muni   = taxes_municipales                       # même base toutes colonnes
taxes_scol   = taxes_scolaires
assurances_d = assurances
energie_d    = energie if colonne == "achat" else energie * (1 - reduction_energie_pct)
concierge    = (BAREME.concierge_lt12 if nb_log < 12 else BAREME.concierge_gte12) * nb_log
entretien    = nb_log * BAREME.entretien
gestion      = (BAREME.gestion_lt12 if nb_log < 12 else BAREME.gestion_gte12) * revenus_totaux

if colonne == "achat":
    wifi = 0
    thermopompes = 0
else:  # refi
    wifi = (BAREME.wifi_par_log * nb_log * 12 + BAREME.internet_fixe * 12) if wifi_ajoute else 0
    thermopompes = nb_thermopompes_ajoutees * BAREME.thermopompe

autres = depenses_autres
depenses_totales = (inoccupation + taxes_muni + taxes_scol + assurances_d
                    + energie_d + concierge + entretien + gestion
                    + wifi + thermopompes + autres)

# Étape 4 — Valeur économique TGA
revenus_net = revenus_totaux - depenses_totales
valeur_eco_tga = revenus_net / tga
hyp_max_tga   = valeur_eco_tga * ratio_pret_valeur

# Étape 5 — Valeur économique RCD
paiement_hyp_max = revenus_net / rcd
# Excel: =-PV((1+taux/2)^(1/6)-1, amort*12, paiement_max/12)
# Composition canadienne (semestrielle convertie en mensuelle)
taux_mensuel = (1 + taux_annuel / 2) ** (1/6) - 1
hyp_max_rcd  = -PV(taux_mensuel, amortissement * 12, paiement_hyp_max / 12)
valeur_eco_rcd = hyp_max_rcd / ratio_pret_valeur

# Étape 6 — Valeur marchande (colonne Achat seulement)
if colonne == "achat":
    valeur_marchande = prix_achat
    hyp_max_vm = valeur_marchande * ratio_pret_valeur
    valeur_retenue = min(valeur_marchande, valeur_eco_rcd, valeur_eco_tga)
else:
    valeur_retenue = min(valeur_eco_rcd, valeur_eco_tga)

# Étape 7 — Financement et résultat final
financement = valeur_retenue * ratio_pret_valeur

if colonne == "achat":
    mdf_necessaire = prix_acquisition - financement
else:
    equite_a_la_fin = financement - prix_acquisition  # « Gain actionnaires »
```

---

## 4. Outputs (à afficher dans la fiche)

### Bloc « RÉSULTAT » (R17..R25)

|                                          | Achat            | Refi SCHL          | Refi APH/Eff       |
|------------------------------------------|------------------|---------------------|--------------------|
| Loyer moyen                              | `loyer_mois`     | `loyer_mois`        | `loyer_mois`       |
| Valeur économique selon RCD              | `valeur_eco_rcd` | `valeur_eco_rcd`    | `valeur_eco_rcd`   |
| Valeur économique selon TGA              | `valeur_eco_tga` | `valeur_eco_tga`    | `valeur_eco_tga`   |
| Valeur marchande                         | `valeur_marchande`| « selon rapport »  | « selon rapport »  |
| Valeur économique retenue                | `valeur_retenue` | `valeur_retenue`    | `valeur_retenue`   |
| Prêt accordé                             | `financement`    | `financement`       | `financement`      |
| MDF nécessaire                           | `mdf_necessaire` | N/A                 | N/A                |
| Gain des actionnaires (après remboursement)| N/A            | `equite_a_la_fin`   | `equite_a_la_fin`  |

**Best refi scenario** affiché sur la carte kanban :
```python
best_refi = max(equite_a_la_fin_schl, equite_a_la_fin_aph_ou_efficacite)
```

---

## 5. Cas de test — Saint-Joseph (`21f6e948-3845_boulevard_SaintJoseph_Est_Montreal.xlsm`)

### Inputs
```
prix_achat = 1_699_000
nombre_logements = 8
revenus_annuels = 103_992
taxes_municipales = 10_349
taxes_scolaires = 805
assurances = 4_655
energie = 221
depenses_autres = 0
tga = 0.04
taux_interet_achat = 0.04
nb_logements_ajoutes = 0
nb_thermopompes_ajoutees = 2
wifi_ajoute = True
reduction_energie_pct = 0
nouveau_loyer_moyen = 1_500
taux_interet_refi = 0.0375
duree_projet_annees = 2
frais_developpement = 80_000
frais_negociations = 80_000
frais_travaux = 160_000
typologie = { "3.5": 4, "4.5": 4 }  # Loyer 4×1400 + 4×1600
```

### Sorties attendues (tolérance ±0,5 % pour arrondis)
```
total_frais_demarrage  ≈ 462 503
prix_acquisition       ≈ 2 161 503
valeur_eco_rcd_achat   ≈ 1 299 460
valeur_eco_tga_achat   ≈ 1 845 560
valeur_marchande       = 1 699 000
valeur_retenue_achat   ≈ 1 299 460
financement_achat      ≈   974 595
mdf_necessaire         ≈ 1 186 910

valeur_eco_rcd_schl    ≈ 1 928 900
valeur_eco_tga_schl    ≈ 2 725 250
valeur_retenue_schl    ≈ 1 928 900
financement_schl       ≈ 1 639 570
equite_apres_schl      ≈  -521 934   # négatif → mauvais scénario

valeur_eco_rcd_aph50   ≈ 2 415 880
valeur_eco_tga_aph50   ≈ 2 715 750
valeur_retenue_aph50   ≈ 2 415 880
financement_aph50      ≈ 2 053 490
equite_apres_aph50     ≈  -108 009   # toujours négatif mais meilleur
```

---

## 6. Architecture côté backend (à implémenter en Phase 3b)

- Module `app/services/lead_analysis_finance.py`
  - Fonction `compute_official(inputs: dict) -> dict` (calculateur sans abordabilité)
  - Fonction `compute_aph_select(inputs: dict) -> dict` (avec abordabilité)
  - Tests unitaires `tests/services/test_lead_analysis_finance.py` qui
    valident contre les valeurs attendues de Saint-Joseph et de Salaberry
    (l'exemple APH SELECT).
- Endpoint `POST /api/v1/lead-analyses/{id}/run-financial-analysis`
  - Body : `{ "model": "official" | "aph_select" }`
  - Lit les champs manuels du `LeadAnalysis`, lance le calcul,
    stocke le résultat dans `analysis_results_json` + `best_refi_amount`,
    bascule le statut en `decision_en_attente`, retourne le résultat.
- Côté frontend, la fiche affiche les sorties dans un tableau 3 colonnes
  conforme au bloc « RÉSULTAT » du calculateur.

---

## 7. Points d'attention / à valider avec Steven

1. **Frais de développement, négociations, travaux** : actuellement
   inputs séparés dans le `LeadAnalysis`. Confirmer s'ils sont
   éditables au cas par cas ou s'ils ont des défauts à proposer.
2. **Énergie côté refi** : la formule applique `(1 - reduction_pct)`
   uniquement aux colonnes refi (C et D), pas à l'achat. Cohérent
   avec l'Excel.
3. **« Frais démarrage » feeds back to B5** : dans l'Excel, B5 contient
   `=L19`. Côté code on calcule L19 d'abord, puis on l'injecte. À
   confirmer : on garde aussi un override manuel si l'utilisateur veut
   écraser ?
4. **Typologie** : les colonnes G/H sont utilisées pour calculer un
   TGA basé sur les loyers, mais ce TGA (H13) est **écrasé** par B13
   dans les calculs. C'est un outil de référence pour aider l'utilisateur
   à choisir un TGA réaliste — pas un input du moteur. Ok ?
5. **APH SELECT — variante D** : ratio 0,95 et amort 50 ans sont
   inhabituels (programme SCHL APH effectivement, 95 % LTV à 50 ans).
   Confirmer l'exactitude.
6. **Best refi pour la carte kanban** : on prend `max(equite_schl, equite_aph)`.
   Si les deux sont négatifs (mauvais cas), on affiche le « moins pire ».
   Ok ou on affiche null ?
