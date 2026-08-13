---
name: impeccable
repo: https://github.com/pbakaus/impeccable
source: https://github.com/pbakaus/impeccable/blob/main/skill/SKILL.src.md
---

# Impeccable — Cheat Sheet

Skill globale: `impeccable` (v4.0.4)

## Quando si attiva

Design/redesign/miglioramento di interfacce frontend: UX, gerarchia visiva, a11y, performance, responsive, theming, typography, micro-interazioni, empty states, onboarding. **Non** per lavoro backend-only.

## Setup (una volta per sessione)

```bash
node <skill-base-dir>/scripts/context.mjs --target <path-or-route>
```

Poi carica il playbook del comando, ispeziona target + sorgente di verità visiva (tokens/theme/CSS), e subito prima di editare UI carica `reference/craft-floor.md` (floor di qualità).

## Comandi (formato `command [target]`)

| Comando | Categoria | Cosa fa |
|---------|-----------|---------|
| `shape [feature]` | Build | Pianifica UX/UI prima di scrivere codice |
| `init` / `teach` | Build | Cattura il contesto di prodotto in `PRODUCT.md` |
| `document` | Build | Genera `DESIGN.md` dal codice esistente |
| `extract [target]` | Build | Estrae tokens/componenti riusabili in design system |
| `critique [target]` | Evaluate | Review UX con scoring euristico |
| `audit [target]` | Evaluate | Controlli tecnici (a11y, perf, responsive) |
| `polish [target]` | Refine | Pass finale di qualità prima del rilascio |
| `bolder [target]` | Refine | Amplifica design noiosi/sicuri |
| `quieter [target]` | Refine | Smorza design aggressivi |
| `distill [target]` | Refine | Riduci all'essenza |
| `harden [target]` | Refine | Produzione: errori, i18n, edge case |
| `onboard [target]` | Refine | First-run flows, empty states, attivazione |
| `animate [target]` | Enhance | Animazioni e motion intenzionali |
| `colorize [target]` | Enhance | Colore strategico a UI monocromatiche |
| `typeset [target]` | Enhance | Gerarchia tipografica e font |
| `layout [target]` | Enhance | Spacing, ritmo, gerarchia visiva |
| `delight [target]` | Enhance | Personalità e tocchi memorabili |
| `overdrive [target]` | Enhance | Spingere oltre i limiti convenzionali |
| `clarify [target]` | Fix | UX copy, label, error messages |
| `adapt [target]` | Fix | Adattare a device/screen size |
| `optimize [target]` | Fix | Diagnosi e fix di performance UI |
| `live` | Iterate | Modalità varianti visive nel browser |

Senza argomento → menu contestuale. Se il comando è ambiguo, chiede una volta.

## Scorciatoie e hook

- **Pin/Unpin**: `node <skill-base-dir>/scripts/pin.mjs <pin|unpin> <command>` crea uno shortcut standalone `/<command>`
- **Hooks**: `/impeccable hooks <on|off|status|ignore-rule|ignore-file|ignore-value|reset>` — auto-detector che gira dopo le modifiche ai file UI e segnala findings
- **Doctor**: `/impeccable doctor` — riporta/ripara drift tra gli artifact (PRODUCT.md, DESIGN.md, config, brief, hook) e la versione corrente

## Principi chiave

- **The brief wins**: estetica/colori/font pinnati dall'utente vanno rispettati anche contro i warning di pattern
- **Refinement preserves; redesign replaces**: refinement mantiene identità e contenuti; redesign sostituisce il look ma non la verità di prodotto
- **Verifica in passate limitate**: build completo → 1 round di ispezione (desktop+mobile) → fix in batch → al massimo 1 conferma. Niente self-QA infinito
- **No assets esterni**: il deliverable deve essere completo tranne asset che l'utente deve fornire
