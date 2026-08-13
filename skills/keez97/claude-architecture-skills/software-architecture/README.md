---
name: software-architecture
source: https://github.com/keez97/claude-architecture-skills/blob/main/skills/software-architecture/SKILL.md
repo: https://github.com/keez97/claude-architecture-skills
---

# Software Architecture — Cheat Sheet

Skill globale: `software-architecture`

## Quando si attiva

- "Come strutturo questo sistema?" — decomposizione, confini, layering
- Scelta pattern: microservices / CQRS / event-driven? (trade-off onesti)
- "Questo codice sta diventando un casino" — coupling, cohesion, refactoring
- Violazioni SOLID · decisioni architetturali da documentare

Non per questioni di stile/lint Python (serve un'altra skill).

## Review Mode: Architecture Health Audit

Quando analizzi un sistema esistente:

- **Architecture Health Score** — punteggio complessivo
- **Findings Table** — problemi con severità
- **Anti-Patterns & Over-Engineering Flags** — es. servizi che fanno troppo
- **Before/After Showcase** — esempi concreti di refactoring

## Design Mode: Nuovo sistema

1. **Requirements Restatement** — riformula i requisiti prima di progettare
2. **Architecture Decision Records (ADRs)** — documenta OGNI decisione:
   - `ADR-001: [Titolo]` → Status → Context → Decision → Alternatives Considered → Consequences → Revisit When
3. **Component Decomposition** — componenti con un solo scopo, interfacce chiare
4. **Design Patterns con giudizio** — Repository, Factory, Strategy, Observer/Pub-Sub, Mediator (solo dove servono)

## SOLID applicato, non predicato

| Principio | Essenza | Anti-pattern |
|-----------|---------|--------------|
| **SRP** | Una classe, un motivo per cambiare | `UserService` fa auth + email + audit |
| **OCP** | Estendi senza modificare | router modificato per ogni provider → registra una volta all'avvio |
| **LSP** | Sottotipi intercambiabili | `CachedUserRepository` che non è un vero `UserRepository` |
| **ISP** | Interfacce piccole e specifiche | `UserService` importa `PaymentProcessor` per un solo metodo |
| **DIP** | Dipendi da astrazioni, non da implementazioni | `UserService` accoppiato a PostgreSQL → inietta repository |

## Pattern chiave

- **Repository** — astrai l'accesso ai dati dietro un'interfaccia
- **Factory** — creazione oggetti complessi centralizzata
- **Strategy** — algoritmi intercambiabili a runtime
- **Observer/Pub-Sub** — disaccoppiamento event-driven
- **Mediator** — orchestrazione di componenti che non devono conoscersi

## Cosa ti restituisce

- Health score + findings + anti-pattern flags
- Esempi `BEFORE` / `AFTER` di codice
- ADR documentate con conseguenze e quando rivederle
