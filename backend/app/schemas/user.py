from datetime import datetime
from pydantic import BaseModel, EmailStr


class UserCreate(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    id: int
    email: EmailStr
    is_active: bool
    is_verified: bool
    is_admin: bool
    token_version: int
    role: str
    created_at: datetime

    class Config:
        from_attributes = True


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class TokenWithFlags(Token):
    needs_password_setup: bool = False


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class GoogleLoginRequest(BaseModel):
    id_token: str


class SetPasswordRequest(BaseModel):
    password: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    email: EmailStr
    token: str
    password: str


class UserAdminOut(BaseModel):
    id: int
    email: EmailStr
    is_active: bool
    is_verified: bool
    is_admin: bool
    role: str
    created_at: datetime

    class Config:
        from_attributes = True


class UserAdminUpdate(BaseModel):
    is_active: bool | None = None
    is_admin: bool | None = None
    role: str | None = None


class UserAdminCreate(BaseModel):
    email: EmailStr
    password: str
    is_admin: bool = False
    role: str = "viewer"


class UserPasswordReset(BaseModel):
    password: str


class AuditLogOut(BaseModel):
    id: int
    action: str
    actor_email: EmailStr | None = None
    target_email: EmailStr | None = None
    meta: dict | None = None
    created_at: datetime

    class Config:
        from_attributes = True


class IdentityOut(BaseModel):
    """Who the caller is, for either an application user or a demo sandbox.

    The frontend reads email/role/is_admin from this and now also learns
    whether it is running inside a sandbox, so it can switch to demo chrome
    without a second round trip.
    """

    email: str
    role: str
    is_admin: bool = False
    is_active: bool = True
    is_demo: bool = False
    id: int | None = None
    is_verified: bool = True
    token_version: int = 0
    created_at: datetime | None = None
