"""Authentication logic and JWT/bcrypt utilities."""
import asyncio
import logging
import os
import secrets
import smtplib
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr, formatdate, make_msgid
from html import escape

import bcrypt
import jwt
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import HTMLResponse
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel

load_dotenv()

logger = logging.getLogger(__name__)

# JWT Configuration
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "default-dev-secret-key-change-in-prod")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
try:
    JWT_ACCESS_TOKEN_EXPIRE_DAYS = int(os.getenv("JWT_ACCESS_TOKEN_EXPIRE_DAYS", "7"))
except ValueError:
    JWT_ACCESS_TOKEN_EXPIRE_DAYS = 7
try:
    VERIFICATION_TOKEN_EXPIRE_HOURS = int(os.getenv("VERIFICATION_TOKEN_EXPIRE_HOURS", "24"))
except ValueError:
    VERIFICATION_TOKEN_EXPIRE_HOURS = 24
try:
    RESET_TOKEN_EXPIRE_HOURS = int(os.getenv("RESET_TOKEN_EXPIRE_HOURS", "1"))
except ValueError:
    RESET_TOKEN_EXPIRE_HOURS = 1
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://127.0.0.1:8000").rstrip("/")

# OAuth2 setup
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

# Pydantic Schemas
class SignupRequest(BaseModel):
    name: str
    email: str
    password: str

class LoginRequest(BaseModel):
    email: str
    password: str

class ResendVerificationRequest(BaseModel):
    email: str

class ForgotPasswordRequest(BaseModel):
    email: str

class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str

# Encryption & JWT utilities
def hash_password(password: str) -> str:
    """Hash a plain text password using bcrypt."""
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain text password against a bcrypt hash."""
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
    except Exception:
        return False


def create_access_token(data: dict) -> str:
    """Create a new signed JWT access token."""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(days=JWT_ACCESS_TOKEN_EXPIRE_DAYS)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)
    return encoded_jwt


def create_action_token() -> str:
    """Create a high-entropy token for account action links."""
    return secrets.token_urlsafe(32)


def token_expiry(hours: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


def decode_access_token(token: str) -> dict | None:
    """Decode a signed JWT token safely."""
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.PyJWTError:
        return None


# SMTP Config from Env
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
try:
    SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
except ValueError:
    SMTP_PORT = 587
SMTP_USERNAME = os.getenv("SMTP_USERNAME", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM_NAME = os.getenv("SMTP_FROM_NAME", "ServicesAgent").strip().strip('"')


def is_smtp_configured() -> bool:
    """Check if SMTP credentials are configured and not placeholders."""
    if not SMTP_USERNAME or not SMTP_PASSWORD:
        return False
    if SMTP_USERNAME in ("your-email@gmail.com", ""):
        return False
    if SMTP_PASSWORD in ("your-gmail-app-password", ""):
        return False
    return True


def _send_smtp_email_sync(to_email: str, subject: str, html_body: str, plain_body: str):
    """Synchronous helper to send email via SMTP, to be run in a thread."""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = formataddr((SMTP_FROM_NAME, SMTP_USERNAME))
    msg["To"] = to_email
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=SMTP_USERNAME.split("@")[-1] if "@" in SMTP_USERNAME else None)

    msg.attach(MIMEText(plain_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=10) as server:
        server.starttls()
        server.login(SMTP_USERNAME, SMTP_PASSWORD)
        server.sendmail(SMTP_USERNAME, to_email, msg.as_string())


async def send_verification_or_reset_email(to_email: str, subject: str, link: str, is_recovery: bool = False):
    """
    Send an email for verification or password reset.
    If SMTP credentials are not configured or sending fails,
    gracefully fall back to printing the link to the console.
    """
    action_type = "Reset password" if is_recovery else "Verify your email"
    
    plain_body = f"Hello,\n\nPlease click the following link to {action_type.lower()}:\n{link}\n\nThank you!"
    
    html_body = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <style>
            body {{
                font-family: 'Inter', 'Helvetica Neue', Helvetica, Arial, sans-serif;
                background-color: #f4f5f7;
                color: #1e293b;
                margin: 0;
                padding: 0;
            }}
            .container {{
                max-width: 600px;
                margin: 40px auto;
                background: #ffffff;
                border-radius: 12px;
                box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06);
                overflow: hidden;
                border: 1px solid #e2e8f0;
            }}
            .header {{
                background: linear-gradient(135deg, #4f46e5 0%, #3b82f6 100%);
                padding: 30px;
                text-align: center;
                color: #ffffff;
            }}
            .header h1 {{
                margin: 0;
                font-size: 24px;
                font-weight: 700;
                letter-spacing: -0.025em;
            }}
            .content {{
                padding: 40px 30px;
                line-height: 1.6;
            }}
            .content p {{
                margin: 0 0 20px 0;
                font-size: 16px;
                color: #475569;
            }}
            .btn-container {{
                text-align: center;
                margin: 30px 0;
            }}
            .btn {{
                background-color: #4f46e5;
                color: #ffffff !important;
                text-decoration: none;
                padding: 14px 28px;
                font-size: 16px;
                font-weight: 600;
                border-radius: 6px;
                display: inline-block;
                box-shadow: 0 4px 6px -1px rgba(79, 70, 229, 0.2), 0 2px 4px -1px rgba(79, 70, 229, 0.1);
                text-align: center;
            }}
            .btn:hover {{
                background-color: #4338ca;
            }}
            .footer {{
                background-color: #f8fafc;
                padding: 20px 30px;
                text-align: center;
                border-top: 1px solid #e2e8f0;
                font-size: 14px;
                color: #64748b;
            }}
            .fallback-link {{
                word-break: break-all;
                font-size: 13px;
                color: #94a3b8;
                margin-top: 20px;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>Service Request System</h1>
            </div>
            <div class="content">
                <p>Hello,</p>
                <p>Thank you for using the Agentic AI Service Request System. Please click the button below to {action_type.lower()}:</p>
                <div class="btn-container">
                    <a href="{link}" class="btn" target="_blank">{action_type}</a>
                </div>
                <p>If the button doesn't work, you can also copy and paste the following link into your browser:</p>
                <div class="fallback-link">{link}</div>
            </div>
            <div class="footer">
                <p>This is an automated email. Please do not reply directly.</p>
            </div>
        </div>
    </body>
    </html>
    """

    if not is_smtp_configured():
        logger.warning("SMTP is not configured or using placeholders. Falling back to console output.")
        print(f"\n[EMAIL FALLBACK] To: {to_email}\nSubject: {subject}\nLink: {link}\n")
        logger.info(f"Fallback email verification/reset url logged for {to_email}")
        return

    last_error = None
    for attempt in range(2):
        try:
            await asyncio.to_thread(
                _send_smtp_email_sync,
                to_email,
                subject,
                html_body,
                plain_body
            )
            logger.info(f"Successfully sent SMTP email to {to_email} with subject: {subject}")
            return
        except Exception as e:
            last_error = e
            if attempt == 0:
                logger.warning(f"SMTP send failed, retrying once: {e}")
                await asyncio.sleep(1)

    logger.error(f"Failed to send email via SMTP: {last_error}. Falling back to console output.")
    print(f"\n[EMAIL FALLBACK ON ERROR] To: {to_email}\nSubject: {subject}\nLink: {link}\nReason: {last_error}\n")


async def send_verification_email(to_email: str, verification_token: str) -> None:
    verification_link = f"{PUBLIC_BASE_URL}/auth/verify-email?token={verification_token}"
    await send_verification_or_reset_email(
        to_email=to_email,
        subject="Verify your email",
        link=verification_link,
        is_recovery=False,
    )


def verification_page(title: str, message: str, success: bool) -> HTMLResponse:
    status_code = 200 if success else 400
    accent = "#16a34a" if success else "#dc2626"
    soft = "#ecfdf5" if success else "#fef2f2"
    icon = "OK" if success else "!"
    html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>{title}</title>
        <style>
            :root {{
                color-scheme: light;
                font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            }}
            body {{
                margin: 0;
                min-height: 100vh;
                display: grid;
                place-items: center;
                background: #f8fafc;
                color: #0f172a;
            }}
            main {{
                width: min(92vw, 520px);
                padding: 40px;
                border: 1px solid #e2e8f0;
                border-radius: 8px;
                background: #ffffff;
                box-shadow: 0 18px 45px rgba(15, 23, 42, 0.08);
                text-align: center;
            }}
            .mark {{
                width: 64px;
                height: 64px;
                display: inline-grid;
                place-items: center;
                border-radius: 999px;
                background: {soft};
                color: {accent};
                font-size: 24px;
                font-weight: 800;
                margin-bottom: 22px;
            }}
            h1 {{
                margin: 0 0 12px;
                font-size: 28px;
                line-height: 1.2;
                font-weight: 750;
                letter-spacing: 0;
            }}
            p {{
                margin: 0;
                color: #475569;
                font-size: 16px;
                line-height: 1.6;
            }}
            .brand {{
                margin-top: 28px;
                color: #94a3b8;
                font-size: 13px;
            }}
        </style>
    </head>
    <body>
        <main>
            <div class="mark" aria-hidden="true">{icon}</div>
            <h1>{title}</h1>
            <p>{message}</p>
            <div class="brand">Service Request System</div>
        </main>
    </body>
    </html>
    """
    return HTMLResponse(content=html, status_code=status_code)


def reset_password_page(token: str) -> HTMLResponse:
    safe_token = escape(token, quote=True)
    html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>Reset Password</title>
        <style>
            :root {{
                color-scheme: light;
                font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            }}
            body {{
                margin: 0;
                min-height: 100vh;
                display: grid;
                place-items: center;
                background: #f8fafc;
                color: #0f172a;
            }}
            main {{
                width: min(92vw, 520px);
                padding: 38px;
                border: 1px solid #e2e8f0;
                border-radius: 8px;
                background: #ffffff;
                box-shadow: 0 18px 45px rgba(15, 23, 42, 0.08);
            }}
            h1 {{
                margin: 0 0 10px;
                font-size: 28px;
                line-height: 1.2;
                font-weight: 750;
                letter-spacing: 0;
            }}
            p {{
                margin: 0 0 24px;
                color: #475569;
                font-size: 15px;
                line-height: 1.6;
            }}
            label {{
                display: block;
                margin-bottom: 8px;
                font-size: 14px;
                font-weight: 650;
                color: #334155;
            }}
            input {{
                box-sizing: border-box;
                width: 100%;
                height: 46px;
                border: 1px solid #cbd5e1;
                border-radius: 6px;
                padding: 0 12px;
                font-size: 15px;
                color: #0f172a;
                outline: none;
            }}
            input:focus {{
                border-color: #2563eb;
                box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.14);
            }}
            button {{
                width: 100%;
                height: 46px;
                margin-top: 18px;
                border: 0;
                border-radius: 6px;
                background: #2563eb;
                color: #ffffff;
                font-size: 15px;
                font-weight: 700;
                cursor: pointer;
            }}
            button:disabled {{
                cursor: wait;
                opacity: 0.72;
            }}
            .message {{
                min-height: 22px;
                margin-top: 16px;
                font-size: 14px;
                line-height: 1.5;
            }}
            .success {{
                color: #15803d;
            }}
            .error {{
                color: #b91c1c;
            }}
            .brand {{
                margin-top: 26px;
                text-align: center;
                color: #94a3b8;
                font-size: 13px;
            }}
        </style>
    </head>
    <body>
        <main>
            <h1>Reset Password</h1>
            <p>Enter a new password for your ServicesAgent account.</p>
            <form id="reset-form">
                <input type="hidden" id="token" value="{safe_token}">
                <label for="password">New password</label>
                <input id="password" name="password" type="password" minlength="6" autocomplete="new-password" required>
                <button id="submit" type="submit">Update password</button>
                <div id="message" class="message" role="status" aria-live="polite"></div>
            </form>
            <div class="brand">Service Request System</div>
        </main>
        <script>
            const form = document.getElementById("reset-form");
            const button = document.getElementById("submit");
            const message = document.getElementById("message");
            form.addEventListener("submit", async (event) => {{
                event.preventDefault();
                message.textContent = "";
                message.className = "message";
                button.disabled = true;
                try {{
                    const response = await fetch("/auth/reset-password", {{
                        method: "POST",
                        headers: {{ "Content-Type": "application/json" }},
                        body: JSON.stringify({{
                            token: document.getElementById("token").value,
                            new_password: document.getElementById("password").value
                        }})
                    }});
                    const data = await response.json();
                    if (!response.ok) {{
                        throw new Error(data.detail || "Unable to reset password.");
                    }}
                    message.textContent = data.message || "Password reset successfully. You can now log in.";
                    message.classList.add("success");
                    form.reset();
                }} catch (error) {{
                    message.textContent = error.message;
                    message.classList.add("error");
                }} finally {{
                    button.disabled = false;
                }}
            }});
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html)


# Dependency for securing endpoints
async def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    """FastAPI Dependency to authenticate users via JWT."""
    from src.db import get_user_by_email, is_token_blacklisted

    # 1. Check blacklist first
    if await is_token_blacklisted(token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has been logged out",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 2. Decode the token payload
    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 3. Retrieve user by email
    email = payload.get("sub")
    if not email:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token signature invalid",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = await get_user_by_email(email)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 4. Check email verification
    if not user.get("is_verified"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Email verification required",
        )

    return user


router = APIRouter()

@router.post("/signup")
async def signup(body: SignupRequest):
    """Register a new user (initially unverified)."""
    from src.db import create_user, get_user_by_email

    name_clean = body.name.strip()
    email_clean = body.email.strip().lower()
    if not name_clean:
        raise HTTPException(status_code=400, detail="Name is required")
    if not email_clean or "@" not in email_clean:
        raise HTTPException(status_code=400, detail="Invalid email format")
    if len(body.password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")

    existing = await get_user_by_email(email_clean)
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    pwd_hash = hash_password(body.password)
    verification_token = create_action_token()

    await create_user(
        name_clean,
        email_clean,
        pwd_hash,
        verification_token,
        token_expiry(VERIFICATION_TOKEN_EXPIRE_HOURS),
    )

    await send_verification_email(email_clean, verification_token)

    return {"message": "Signup successful. Please verify your email."}


@router.get("/verify-email")
async def verify_email(token: str):
    """Verify user's email address using unique token."""
    from src.db import verify_user_email

    success = await verify_user_email(token)
    if not success:
        return verification_page(
            "Verification Link Expired",
            "This email verification link is invalid or has expired. Please request a new verification email and try again.",
            success=False,
        )

    return verification_page(
        "Email Verified",
        "Your email address has been verified successfully. You can now return to the app and log in.",
        success=True,
    )


@router.post("/resend-verification")
async def resend_verification(body: ResendVerificationRequest):
    """Regenerate and resend verification email."""
    from src.db import get_user_by_email, update_verification_token

    email_clean = body.email.strip().lower()
    user = await get_user_by_email(email_clean)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if user.get("is_verified"):
        return {"message": "Email is already verified"}

    verification_token = create_action_token()
    await update_verification_token(
        email_clean,
        verification_token,
        token_expiry(VERIFICATION_TOKEN_EXPIRE_HOURS),
    )

    await send_verification_email(email_clean, verification_token)

    return {"message": "Verification link sent successfully."}


@router.post("/login")
async def login(body: LoginRequest):
    """Validate credentials and return JWT token."""
    from src.db import get_user_by_email

    email_clean = body.email.strip().lower()
    user = await get_user_by_email(email_clean)
    if not user or not verify_password(body.password, user.get("password_hash")):
        raise HTTPException(status_code=400, detail="Incorrect email or password")

    if not user.get("is_verified"):
        raise HTTPException(status_code=400, detail="Please verify your email before logging in")

    # Generate JWT
    access_token = create_access_token(data={"sub": user.get("email")})
    return {"access_token": access_token, "token_type": "bearer"}


@router.post("/logout")
async def logout(current_user: dict = Depends(get_current_user), token: str = Depends(oauth2_scheme)):
    """Log out user by blacklisting active token."""
    from src.db import blacklist_token

    payload = decode_access_token(token)
    if payload and "exp" in payload:
        expires_at = datetime.fromtimestamp(payload["exp"], timezone.utc).isoformat()
    else:
        expires_at = (datetime.now(timezone.utc) + timedelta(days=JWT_ACCESS_TOKEN_EXPIRE_DAYS)).isoformat()

    await blacklist_token(token, expires_at)
    return {"message": "Successfully logged out"}


@router.post("/forgot-password")
async def forgot_password(body: ForgotPasswordRequest):
    """Initiate password recovery flow."""
    from src.db import get_user_by_email, set_reset_token

    response = {"message": "If the email is registered, a password reset link has been sent."}
    email_clean = body.email.strip().lower()
    user = await get_user_by_email(email_clean)
    if not user:
        return response

    reset_token = create_action_token()
    await set_reset_token(email_clean, reset_token, token_expiry(RESET_TOKEN_EXPIRE_HOURS))

    reset_link = f"{PUBLIC_BASE_URL}/auth/reset-password?token={reset_token}"
    await send_verification_or_reset_email(
        to_email=email_clean,
        subject="Reset password",
        link=reset_link,
        is_recovery=True
    )

    return response


@router.get("/reset-password")
async def reset_password_form(token: str):
    """Render a browser page for password reset links."""
    return reset_password_page(token)


@router.post("/reset-password")
async def reset_password(body: ResetPasswordRequest):
    """Reset password utilizing valid token."""
    from src.db import reset_user_password

    if len(body.new_password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")

    new_pwd_hash = hash_password(body.new_password)
    success = await reset_user_password(body.token, new_pwd_hash)
    if not success:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")

    return {"message": "Password reset successfully. You can now log in with your new password."}
