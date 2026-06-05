# Spec — Calcul du TRI investisseur (lead_tri_calc)

Documente la logique du moteur `app.services.lead_tri_calc.compute_tri`,
reproduction **au centime près** d'un calculateur Excel validé sur 3 deals
réels. Modélise le rendement d'un investisseur minoritaire dans un projet
immobilier de type **achat → chantier/stabilisation → refinancement**, avec
3 horizons de sortie possibles : **an 2**, **an 7**, **an 12**.

Le moteur est purement fonctionnel (aucune dépendance BD) et défensif :
chaque intrant `None` est traité comme `0.0`, chaque division par zéro
renvoie `0.0`.

## Les 12 intrants

| Intrant       | Signification                                        | Source |
|---------------|------------------------------------------------------|--------|
| `prix`        | Prix d'achat de l'immeuble                           | auto   |
| `rpv_achat`   | Ratio prêt-valeur à l'achat (ex. 0.8)                | auto   |
| `pret_constr` | Prêt de construction/chantier (prêteur B)            | auto   |
| `mdf`         | Mise de fonds nécessaire (cash sorti à l'achat)      | auto   |
| `capital`     | Capital total injecté par l'investisseur (base TRI)  | manuel |
| `pct`         | Fraction des parts détenues (ex. 0.5)                | manuel |
| `loyers2`     | Loyers bruts stabilisés an 2                         | auto   |
| `dep2`        | Dépenses d'opération an 2                            | auto   |
| `valeur2`     | Valeur de l'immeuble stabilisée an 2                 | auto   |
| `rpv_refi`    | Ratio prêt-valeur au refinancement (ex. 0.85)        | auto   |
| `cr_loyers`   | Croissance annuelle des loyers (ex. 0.03)            | manuel |
| `cr_dep`      | Croissance annuelle des dépenses                     | manuel |

Les **8 intrants auto** sont dérivés du calcul d'analyse Kratos existant et
restent éditables côté front. Les **4 manuels** (`capital`, `pct`,
`cr_loyers`, `cr_dep`) sont saisis par l'utilisateur et persistés sur la
fiche (`tri_capital_injecte`, `tri_pct_investisseur`,
`tri_croissance_loyers`, `tri_croissance_depenses`).

## ① Bases

```
hypotheque     = rpv_achat × prix          # hypothèque conventionnelle d'achat
marge          = capital − mdf             # marge de manœuvre (cash non immobilisé)
rno2           = loyers2 − dep2            # revenu net d'opération an 2
multiplicateur = valeur2 / rno2            # ≈ inverse du cap rate (garde si rno2=0)
cap_rate       = 1 / multiplicateur        # cap rate implicite
```

## ② Projection par horizon (an 2 / an 7 / an 12)

Exposants de croissance composée : an 2 → 0, an 7 → 5, an 12 → 10.

```
loyers[h] = loyers2 × (1 + cr_loyers) ^ expo[h]
dep[h]    = dep2    × (1 + cr_dep)    ^ expo[h]
rno[h]    = loyers[h] − dep[h]

valeur[2]  = valeur2                       # ancre de référence an 2
valeur[7]  = rno[7]  × multiplicateur      # revalorisation par le RNO
valeur[12] = rno[12] × multiplicateur
```

## ③ Refinancement : prêt max, équité, argent disponible

```
pret_refi[h] = rpv_refi × valeur[h]
equite[h]    = valeur[h] − pret_refi[h]

dispo[2]  = pret_refi[2] + marge − (hypotheque + pret_constr)
dispo[7]  = pret_refi[7] − pret_refi[2]
dispo[12] = pret_refi[12] − pret_refi[7]
```

À l'an 2, le refi rembourse la dette de portage (hypothèque d'achat + prêt
de construction) ; ce qui reste, plus la marge, est disponible. Aux an 7 et
an 12, le dispo est l'incrément de prêt rendu possible par la revalorisation.

## ④ Cascade : retour de capital prioritaire + surplus partagé

On rembourse le capital de l'investisseur **en priorité**, horizon par
horizon, jamais plus que l'argent disponible ni que le restant dû.

```
restant_avant[2] = capital
pour chaque horizon h (dans l'ordre) :
    retour[h]        = max(0, min(dispo[h], restant_avant[h]))
    surplus[h]       = max(0, dispo[h] − retour[h])
    restant_apres[h] = restant_avant[h] − retour[h]
    restant_avant[h+1] = restant_apres[h]

cash[h]         = retour[h] + pct × surplus[h]      # encaissé par l'investisseur
valeur_parts[h] = pct × equite[h] + restant_apres[h]  # valeur liquidative de ses parts
```

Le retour de capital revient en propre à l'investisseur ; il ne partage que
le **surplus** au prorata de ses parts. La valeur de ses parts comprend sa
quote-part d'équité plus tout capital non encore remboursé.

## ⑤ Flux + TRI par année de sortie

Pour chaque année de sortie (an 2 / an 7 / an 12), on construit une ligne de
temps de 13 ans (index 0 à 12) :

```
f[0]          = −capital                  # injection initiale
f[2]         += cash[2]
f[7]         += cash[7]    (si sortie ≥ an 7)
f[12]        += cash[12]   (si sortie ≥ an 12)
f[exit_year] += valeur_parts[exit_year]   # liquidation à la sortie
```

Le TRI de chaque ligne est obtenu par `irr(f)`.

## IRR — bissection

`irr(cashflows)` cherche le taux `r` annuel qui annule la valeur actuelle
nette (VAN) :

```
NPV(r) = Σ_t  cashflows[t] / (1 + r) ^ t
```

Méthode robuste par **bissection** sur l'intervalle `[-0.9999, 10.0]` :

1. Si `NPV(lo)` et `NPV(hi)` sont de même signe → pas de racine encadrable,
   on renvoie `None` (cas dégénéré, flux tous de même signe).
2. Sinon on resserre l'intervalle de moitié à chaque itération (jusqu'à
   200 fois ou `|NPV(mid)| < 1e-9`).

Pas de Newton-Raphson : la bissection ne diverge jamais et reproduit
exactement le calculateur de référence.

## Validation

3 scénarios de référence validés au centième (cf.
`tests/services/test_lead_tri_calc.py`) :

| Scénario  | TRI an 2 | TRI an 7 | TRI an 12 |
|-----------|----------|----------|-----------|
| Deal 1    | 25.198 % | 22.226 % | 21.375 %  |
| Deal 1(2) | 29.739 % | 24.960 % | 23.730 %  |
| Deal 2    | 13.476 % | 14.770 % | 16.534 %  |
