---
name: fastapi-expert
source: https://github.com/Jeffallan/claude-skills/blob/main/skills/fastapi-expert/SKILL.md
repo: https://github.com/Jeffallan/claude-skills
---

# FastAPI Expert — Cheat Sheet

Skill globale: `fastapi-expert`

## Quando si attiva

- REST API con FastAPI · Pydantic V2 schemas · DB async (SQLAlchemy) · JWT auth · WebSocket · performance API

## Core Workflow (con checkpoint)

1. **Analyze requirements** — endpoint, data models, auth
2. **Design schemas** — Pydantic V2 per validazione
3. **Implement** — endpoint async con dependency injection
4. **Secure** — auth, authorization, rate limiting
5. **Test** — pytest + httpx; dopo ogni gruppo di endpoint:

   ```bash
   pytest
   ```
   e verifica OpenAPI docs su `/docs`

> **Checkpoint dopo ogni step**: schemi validano, endpoint restituiscono status code giusti, `/docs` riflette la superficie API.

## Pattern indispensabili

- **Type hints ovunque** (FastAPI li richiede)
- **Pydantic V2** (`field_validator`, `model_validator`, `model_config`) — MAI V1 (`@validator`, `class Config`)
- **`Annotated`** per dependency injection:
  ```python
  DbDep = Annotated[AsyncSession, Depends(get_db)]
  ```
- **`X | None`** invece di `Optional[X]`
- **async/await** per TUTTE le I/O — mai DB sincrono in endpoint async
- Status code corretti (`201`, `409`, `401`...)

## Schema Pydantic V2 (esempio)

```python
class UserCreate(BaseModel):
    model_config = model_config(str_strip_whitespace=True)
    email: EmailStr
    password: str

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v
```

## JWT auth (snippet base)

```python
from jose import JWTError, jwt
from fastapi.security import OAuth2PasswordBearer

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")
ALGORITHM = "HS256"

def create_access_token(subject: str, expires_delta: timedelta = timedelta(minutes=30)) -> str:
    payload = {"sub": subject, "exp": datetime.now(timezone.utc) + expires_delta}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

async def get_current_user(token: Annotated[str, Depends(oauth2_scheme)]) -> str:
    ...
CurrentUser = Annotated[str, Depends(get_current_user)]
```

## MUST NOT DO

- Password in chiaro · dati sensibili nelle response · valori di config hardcodati · sync DB operations · Pydantic V1 · misturare sync/async in modo improprio

## Deliverable

1. Schema file (Pydantic) · 2. Router endpoint · 3. CRUD se c'è DB · 4. Note sulle decisioni chiave

## Riferimenti

| Topic | File |
|-------|------|
| Pydantic V2 | `references/pydantic-v2.md` |
| SQLAlchemy async | `references/async-sqlalchemy.md` |
| Endpoint/routing | `references/endpoints-routing.md` |
| Auth | `references/authentication.md` |
| Test async | `references/testing-async.md` |
| Migrazione da Django | `references/migration-from-django.md` |

Doc ufficiale: <https://jeffallan.github.io/claude-skills/skills/backend/fastapi-expert/>
