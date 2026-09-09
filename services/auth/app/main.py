"""Auth service — accounts for charities and their recipients.

TWO ROLES, DELIBERATELY UNEQUAL
-------------------------------
charity    full access: stock, CRUD, agent actions, feedback.
recipient  can do exactly one thing — submit a request. No stock, no agent, no
           other people's feedback. Enforced server-side by `require_charity`,
           not by hiding buttons in the UI.

Recipients do not have to have an account at all: a charity can mint a public
request link (`/auth/request-links`) and hand out the URL. Anyone opening it
can file a request and nothing else. That is the path most beneficiaries will
actually use — asking an elderly person to create a password is a barrier, not
a feature.
"""
from __future__ import annotations

import logging
import secrets
from typing import Optional
from pantry_common.security import signing_secret

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, Field

from app import db
from app.security import (PASSWORD_RULES, hash_password, make_token,
                          password_problems, read_token, verify_password)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("auth")

app = FastAPI(title="Pantry Auth")
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])


class SignUp(BaseModel):
    email: EmailStr
    password: str
    display_name: str = Field(min_length=1, max_length=120)
    role: str = "charity"


class LogIn(BaseModel):
    email: EmailStr
    password: str


class ChangePassword(BaseModel):
    current_password: str
    new_password: str
    # Confirmation matching is a client-side UX check (the settings form
    # verifies new_password == confirm before ever submitting) -- the server
    # only needs the one new value it is actually going to hash and store.


class RecipientIn(BaseModel):
    email: EmailStr
    password: str
    display_name: str = Field(min_length=1, max_length=120)
    beneficiary_id: Optional[str] = None


def current_user(authorization: Optional[str] = Header(None)) -> dict:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "missing bearer token")
    claims = read_token(authorization.split(" ", 1)[1])
    if not claims:
        raise HTTPException(401, "invalid or expired token")
    return claims


def require_charity(user: dict = Depends(current_user)) -> dict:
    """Server-side role gate. The UI also hides these, but this is the fence."""
    if user.get("role") != "charity":
        raise HTTPException(403, "this action is for charity accounts only")
    return user


@app.on_event("startup")
def _startup() -> None:
    signing_secret()
    db.init_pool()


@app.get("/health")
def health():
    try:
        with db.get_cursor() as cur:
            cur.execute("SELECT count(*) AS n FROM auth.users")
            n = cur.fetchone()["n"]
        return {"status": "ok", "database": "ok", "users": n}
    except Exception as exc:  # noqa: BLE001
        return {"status": "degraded", "detail": str(exc)}


@app.get("/auth/password-policy")
def password_policy():
    """The signup screen renders these, so they can never drift from the check."""
    return {"rules": [label for label, _ in PASSWORD_RULES]}


@app.post("/auth/signup", status_code=201)
def signup(payload: SignUp):
    if payload.role != "charity":
        raise HTTPException(400, "self-signup is for charity accounts; "
                                 "recipients are invited by a charity")
    problems = password_problems(payload.password)
    if problems:
        raise HTTPException(422, {"code": "WEAK_PASSWORD",
                                  "message": "Password needs " + ", ".join(problems),
                                  "problems": problems})
    with db.get_cursor() as cur:
        cur.execute("SELECT 1 FROM auth.users WHERE lower(email)=lower(%s)",
                    (payload.email,))
        if cur.fetchone():
            raise HTTPException(409, "an account with that email already exists")
        cur.execute(
            """INSERT INTO auth.users (email, password_hash, role, display_name)
               VALUES (%s,%s,'charity',%s)
               RETURNING id, email, role, display_name, beneficiary_id""",
            (payload.email.lower(), hash_password(payload.password),
             payload.display_name))
        user = cur.fetchone()
    logger.info("charity account created: %s", user["email"])
    return {"token": make_token(user), "user": {**user, "name": user["display_name"]}}


@app.post("/auth/login")
def login(payload: LogIn):
    with db.get_cursor() as cur:
        cur.execute(
            """SELECT id, email, password_hash, role, display_name,
                      beneficiary_id, is_active
               FROM auth.users WHERE lower(email)=lower(%s)""",
            (payload.email,))
        user = cur.fetchone()
    # Same message for unknown email and wrong password — do not reveal which
    # addresses have accounts.
    if not user or not verify_password(payload.password, user["password_hash"]):
        raise HTTPException(401, "email or password is incorrect")
    if not user["is_active"]:
        raise HTTPException(403, "this account has been deactivated")
    with db.get_cursor() as cur:
        cur.execute("UPDATE auth.users SET last_login_at=now() WHERE id=%s",
                    (user["id"],))
    user.pop("password_hash")
    return {"token": make_token(user), "user": {**user, "name": user["display_name"]}}


@app.post("/auth/logout")
def logout(user: dict = Depends(current_user)):
    """Tokens are stateless and short-lived; the client discards it.

    Honest about what this does: there is no server-side revocation list. For a
    12-hour token on a hackathon demo that is the right trade; a production
    build would need a denylist or refresh tokens.
    """
    return {"ok": True, "message": "token discarded client-side"}


@app.get("/auth/me")
def me(user: dict = Depends(current_user)):
    return {"user": user}


@app.post("/auth/change-password")
def change_password(payload: ChangePassword, user: dict = Depends(current_user)):
    with db.get_cursor() as cur:
        cur.execute("SELECT id, password_hash FROM auth.users WHERE id=%s", (int(user["sub"]),))
        row = cur.fetchone()
    if not row or not verify_password(payload.current_password, row["password_hash"]):
        raise HTTPException(401, "current password is incorrect")

    problems = password_problems(payload.new_password)
    if problems:
        raise HTTPException(422, {"code": "WEAK_PASSWORD",
                                  "message": "Password needs " + ", ".join(problems),
                                  "problems": problems})

    with db.get_cursor() as cur:
        cur.execute("UPDATE auth.users SET password_hash=%s WHERE id=%s",
                    (hash_password(payload.new_password), row["id"]))
    logger.info("password changed: user id %s", row["id"])
    return {"ok": True}


# ----------------------------------------------------- recipient management --
@app.post("/auth/recipients", status_code=201)
def create_recipient(payload: RecipientIn, charity: dict = Depends(require_charity)):
    """A charity creates a recipient login. Recipients cannot self-signup."""
    problems = password_problems(payload.password)
    if problems:
        raise HTTPException(422, {"code": "WEAK_PASSWORD",
                                  "message": "Password needs " + ", ".join(problems),
                                  "problems": problems})
    with db.get_cursor() as cur:
        cur.execute("SELECT 1 FROM auth.users WHERE lower(email)=lower(%s)",
                    (payload.email,))
        if cur.fetchone():
            raise HTTPException(409, "an account with that email already exists")
        bid = payload.beneficiary_id or f"BEN-{secrets.token_hex(4).upper()}"
        cur.execute(
            """INSERT INTO auth.users
                 (email, password_hash, role, display_name, beneficiary_id, charity_id)
               VALUES (%s,%s,'recipient',%s,%s,%s)
               RETURNING id, email, role, display_name, beneficiary_id, created_at""",
            (payload.email.lower(), hash_password(payload.password),
             payload.display_name, bid, int(charity["sub"])))
        return cur.fetchone()


@app.get("/auth/recipients")
def list_recipients(charity: dict = Depends(require_charity)):
    with db.get_cursor() as cur:
        cur.execute(
            """SELECT id, email, display_name, beneficiary_id, is_active,
                      created_at, last_login_at
               FROM auth.users WHERE charity_id=%s AND role='recipient'
               ORDER BY created_at DESC""", (int(charity["sub"]),))
        return cur.fetchall()


# ---------------------------------------------------------- public links ----
@app.post("/auth/request-links", status_code=201)
def create_request_link(label: str = "Public request link",
                        charity: dict = Depends(require_charity)):
    token = secrets.token_urlsafe(12)
    with db.get_cursor() as cur:
        cur.execute(
            """INSERT INTO auth.request_links (token, charity_id, label)
               VALUES (%s,%s,%s) RETURNING token, label, is_active, created_at, uses""",
            (token, int(charity["sub"]), label))
        return cur.fetchone()


@app.get("/auth/request-links")
def list_request_links(charity: dict = Depends(require_charity)):
    with db.get_cursor() as cur:
        cur.execute("""SELECT token, label, is_active, created_at, uses
                       FROM auth.request_links WHERE charity_id=%s
                       ORDER BY created_at DESC""", (int(charity["sub"]),))
        return cur.fetchall()


@app.get("/auth/request-links/{token}")
def resolve_request_link(token: str):
    """Public — the recipient page calls this to validate a handed-out link."""
    with db.get_cursor() as cur:
        cur.execute(
            """SELECT l.token, l.label, l.is_active, u.display_name AS charity_name
               FROM auth.request_links l JOIN auth.users u ON u.id = l.charity_id
               WHERE l.token=%s""", (token,))
        link = cur.fetchone()
    if not link or not link["is_active"]:
        raise HTTPException(404, "this request link is not valid")
    return link


@app.post("/auth/request-links/{token}/used")
def mark_used(token: str):
    with db.get_cursor() as cur:
        cur.execute("UPDATE auth.request_links SET uses = uses + 1 WHERE token=%s AND is_active RETURNING token",
                    (token,))
        if not cur.fetchone():
            raise HTTPException(404, "this request link is not valid")
    return {"ok": True}


@app.delete("/auth/request-links/{token}")
def revoke_request_link(token: str, charity: dict = Depends(require_charity)):
    with db.get_cursor() as cur:
        cur.execute("""UPDATE auth.request_links SET is_active=FALSE
                       WHERE token=%s AND charity_id=%s""",
                    (token, int(charity["sub"])))
    return {"ok": True}
