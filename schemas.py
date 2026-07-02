from pydantic import BaseModel, EmailStr

# ─── Register ───────────────────────────────────────────
class UserRegister(BaseModel):
    name: str
    email: EmailStr
    password: str

class RegisterResponse(BaseModel):
    status: str
    message: str
    email: str

# ─── Login ──────────────────────────────────────────────
class UserLogin(BaseModel):
    email: EmailStr
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str
    email: str

class LoginResponse(BaseModel):
    status: str
    message: str
    data: TokenResponse
