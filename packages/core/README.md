# @crescent/core (Python)

Shared backend helpers. **Never imports from any `services/*`** — it's the shared
foundation, not a dumping ground.

## What's in it right now
The **access-token verifier**. Pulse and Forge use this to check a caller's JWT
without ever touching identity's database or copying its signing key — they
fetch identity's public key(s) once, cache them, and verify locally.

## Install (from another service in this monorepo)
Editable install so changes in `packages/core/` land immediately, no rebuild:

```bash
pip install -e ../../packages/core
```

Or add to a service's `requirements.txt`:

```
-e ../../packages/core
```

## Usage in a product (Pulse / Forge)

```python
from fastapi import FastAPI, Depends
from crescent_core import JWKSClient, current_user_dep, TokenClaims

app = FastAPI()

# Once, at startup — a single shared client for the app's lifetime.
jwks = JWKSClient(jwks_url="http://identity:8000/.well-known/jwks.json")
current_user = current_user_dep(jwks_client=jwks, issuer="cyphercrescent-identity")

@app.get("/me")
def me(user: TokenClaims = Depends(current_user)):
    return {"user_id": user.user_id, "org_id": user.org_id, "role": user.role}
```

## What the verifier guarantees
- Signature valid against identity's **public** key (RS256).
- Not expired.
- Issuer matches what you configured.
- `token_type == "access"` (refresh tokens can't sneak through).

Returns a `TokenClaims` object with `user_id`, `email`, `org_id`, `role`,
`token_version`, and the raw payload as `.raw`.

## What it does NOT do
- Doesn't hit identity's database.
- Doesn't talk to identity at all after JWKS is cached (TTL: 1 hour by default,
  or immediately on unknown `kid` — supports key rotation).
- Doesn't know or care what roles exist. That's the product's job.
