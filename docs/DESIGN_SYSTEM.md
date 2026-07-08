# Design system Kratos (Phase 4)

Base partagée pour uniformiser l'UI de tous les pôles. Le **pôle Construction**
(`[locale]/app/*`) est le **modèle de référence** : les primitives ci-dessous
sont extraites de son langage visuel (dark-first, cohérent, kanbans soignés).

> Règle d'or : **composer avec les tokens existants** (`brand-*`, `accent-*`,
> `emerald/rose/amber/sky/blue/violet`, `white/opacité`). Le thème clair
> (`html[data-portal-theme="light"]`) remappe déjà ces tokens dans
> `globals.css` → toute primitive qui les utilise fonctionne en **sombre ET
> clair** sans travail supplémentaire. Ne pas introduire de hex bruts.

## Tokens (`tailwind.config.ts`)

- **Couleurs** : `brand-50…950` (monochrome, aligné logo), `accent-300/400/500/600/700` (doré ; 500 = CTA).
- **Ombres** : `shadow-soft` (léger), `shadow-card` (encadré), `shadow-lift` (survol/flottant).
- **Polices** : `font-sans` (Inter), `font-display` (Plus Jakarta) pour h1–h4.

## Classes CSS (`globals.css`, `@layer components`)

| Classe | Usage |
|--------|-------|
| `.btn-primary` / `.btn-secondary` / `.btn-accent` / `.btn-danger` / `.btn-ghost` | Boutons (variantes sémantiques). |
| `.btn-xs` / `.btn-sm` / `.btn-lg` | Modificateurs de taille (se composent : `class="btn-accent btn-sm"`). |
| `.card` | Encadré principal (rounded-2xl, p-6). |
| `.panel` / `.panel-soft` | Conteneur de section (rounded-xl, p-4) / variante translucide. |
| `.section-title` | Intitulé de section (eyebrow majuscules discrètes). |
| `.badge` + `.badge-{neutral,emerald,amber,rose,sky,blue,violet}` | Pastilles de statut (11px, rayon plein). |
| `.empty-state` | État vide (bordure pointillée centrée). |
| `.input` / `.label` | Champs de formulaire. |

## Primitives React (`components/ui/`, barrel `@/components/ui`)

```tsx
import {
  Button, Badge, Card, PageHeader, SectionTitle, EmptyState
} from "@/components/ui";
```

- **`<Button variant size>`** — `variant`: primary|secondary|accent|danger|ghost ; `size`: xs|sm|md|lg. `buttonClasses(variant, size, className)` exposé pour styler un `<Link>` en bouton.
- **`<Badge variant>`** — neutral|emerald|amber|rose|sky|blue|violet.
- **`<Card variant>`** — card|panel|panel-soft.
- **`<PageHeader title subtitle icon backHref|onBack|showBack actions>`** — en-tête de page unifié (bouton Retour + titre + actions).
- **`<SectionTitle>`** — `<h2>` eyebrow.
- **`<EmptyState icon title description action>`** — état vide centré.

## Conventions d'uniformisation (checklist de propagation)

En reprenant une page, remplacer les motifs ad hoc par les primitives :

1. En-tête « ← Retour + titre » manuel → `<PageHeader />`.
2. Pastilles `rounded-full px-2 py-0.5 text-[10px]…` → `.badge .badge-{ton}` (ou `<Badge />`). **Uniformise 10px→11px.**
3. Conteneurs `rounded-xl border border-brand-800 bg-brand-900 p-4` → `.panel` (ou `<Card variant="panel" />`).
4. Titres de section `text-sm font-semibold uppercase…` → `.section-title`.
5. Boutons compacts ad hoc → `.btn-* .btn-sm` / `.btn-xs`.
6. États vides bricolés → `<EmptyState />`.

**Rayons** : `rounded-2xl` (encadrés), `rounded-xl` (sections/boutons), `rounded-lg` (champs, petits boutons), `rounded-full` (badges/pastilles).

## Statut

- ✅ **Fondation** posée (tokens + classes + primitives), additive, bi-thème.
- ⏭️ **À faire (avec revue visuelle de Phil)** : propager pôle par pôle en partant de Construction (le modèle). Commencer par les pages à fort trafic, une PR par lot, vérif visuelle avant merge.
