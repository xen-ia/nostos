---
name: superpowers
repo: https://github.com/obra/superpowers
source: https://github.com/obra/superpowers/tree/main/skills
---

# Superpowers — Cheat Sheet

Repo ufficiale: <https://github.com/obra/superpowers>

## Cos'è

Metodologia di sviluppo per agenti, costruita su una serie di skill componibili. **Le skill si attivano da sole** al momento giusto: non devi lanciarle manualmente. L'agente le usa come flusso di lavoro obbligatorio.

Installata come plugin in `opencode.json`:
`"plugin": ["superpowers@git+https://github.com/obra/superpowers.git"]`

## Il flusso completo (dall'idea al merge)

```
idea → brainstorming → worktree → writing-plans → subagent-driven-development → TDD → code-review → finishing-a-development-branch
```

Le skill **processo** (brainstorming, systematic-debugging) hanno la priorità e dettano l'approccio; quelle **implementative** lo eseguono.

## Le skill

| Skill | Quando si attiva | Cosa fa |
|-------|------------------|---------|
| `brainstorming` | Prima di ogni lavoro creativo (feature, componente, bug-fix) | Classifica la richiesta (spike / bounded / architectural), fa domande, presenta un design, e **chiede approvazione prima di scrivere codice** |
| `using-git-worktrees` | Prima di feature o di eseguire un piano | Crea workspace isolato (`.worktrees/`), installa dipendenze, verifica baseline test pulita |
| `writing-plans` | Quando hai spec/requisiti per task multi-step | Scrive piano di implementazione in task mordi e mordi (2-5 min), ogni task con file, codice e verifica completi |
| `subagent-driven-development` | Per eseguire un piano in questa sessione | Subagent fresco per task + review (spec compliance + qualità) dopo ognuno + review finale su tutto il branch |
| `executing-plans` | Per eseguire un piano in sessione separata | Esegue i task del piano a lotti con checkpoint di review |
| `test-driven-development` | Durante implementazione di qualunque feature/bugfix | RED-GREEN-REFACTOR: test prima, guardalo fallire, codice minimo, guardalo passare. **Nessun codice di produzione senza test fallito prima** |
| `systematic-debugging` | A ogni bug, test failure, comportamento inatteso | 4 fasi: root cause → pattern → ipotesi → fix. **Nessun fix senza root cause**. Dopo 3+ fix falliti: metti in discussione l'architettura |
| `requesting-code-review` | Dopo ogni task, feature grossa, prima del merge | Dispatcher subagent reviewer con contesto preciso (mai la tua sessione) |
| `receiving-code-review` | Quando ricevi feedback di review | Verifica prima di implementare, pushback tecnico, mai accordo performativo |
| `dispatching-parallel-agents` | Con 2+ task indipendenti | Un agente per dominio, in parallelo (più dispatch nella stessa risposta = parallel) |
| `finishing-a-development-branch` | Implementazione completa, test verdi | Verifica test → presenta opzioni: merge locale / PR / tieni branch |
| `verification-before-completion` | Prima di dichiarare lavoro completo | Nessuna claim senza evidenza: run il comando, leggi l'output |
| `writing-skills` | Per creare/modificare skill | Best practice per nuove skill |
| `using-superpowers` | All'inizio di ogni conversazione | Inietta le regole: controlla le skill PRIMA di ogni risposta/azione |

## Come usarla (da utente)

Non serve alcun comando magico — basta parlare normalmente e l'agente carica la skill giusta:

| Tu dici | Skill che parte |
|---------|-----------------|
| "Voglio aggiungere la feature X" | brainstorming |
| "Sistemami questo bug / questi test falliscono" | systematic-debugging (+ TDD) |
| "C'è un piano, eseguilo" | subagent-driven-development o executing-plans |
| "Rivedi il lavoro" | requesting-code-review |
| "Ho finito" | finishing-a-development-branch |

Per forzare/elencare:
- "quali skill hai disponibili?" — elenca le skill
- "usa la skill brainstorming" / "usa systematic-debugging per questo" — forza una skill specifica

## Regole d'oro (che ti farà rispettare)

- **Approval gate**: nessuna implementazione prima del tuo "ok" al design
- **TDD**: niente codice di produzione senza un test fallito prima
- **Root cause**: niente fix senza aver capito la causa
- **Worktree**: mai lavorare su main senza il tuo consenso esplicito
- **Evidence**: "funziona" solo con comando eseguito e output verificato
- **Subagent**: mai accettare il report di un agente senza verificare il diff

## File generati (dove finiscono le cose)

- Spec/design: `docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md`
- Piani: `docs/superpowers/plans/YYYY-MM-DD-<feature-name>.md`
- Ledger SDD (progressi per-task): `<repo>/.superpowers/sdd/<plan>/progress.md` (git-ignored)

## Tool mapping (OpenCode)

Le skill parlano di "azioni"; in opencode si traducono in:
- Create/aggiorna todo → `todowrite`
- Subagent → `task` (subagent_type `general` per implementazione, `explore` per esplorazione)
- Invoca skill → tool `skill` nativo
- Crea/modifica/elimina file → `apply_patch`
- Comandi shell → `bash` · ricerca file/contenuti → `grep`, `glob` · fetch URL → `webfetch`

## Aggiornamento

La versione è pinnata al commit git: se le skill non si aggiornano al riavvio, svuota la cache plugin di opencode o reinstalla. Per pinnare una versione: `"superpowers@git+https://github.com/obra/superpowers.git#v5.0.3"`.
