# Implementation Plan: Authentication & JWT Endpoints

This document outlines the architecture, database schema, design decisions, and step-by-step changes required to implement secure JWT-based authentication for the Agentic AI Service Request System.

---

## Goal Description

Introduce robust, secure, and stateless authentication utilizing JWT (JSON Web Tokens). Users will be able to sign up, verify their email address, log in, manage password recovery, and log out (supported by server-side token invalidation via blacklisting). All authentication endpoints will reside in a new, separate module `src/auth.py` and be cleanly routed into the main FastAPI application.

---

## Proposed Architecture & Security Flow

1. **Password Hashing:** Passwords will be securely hashed using `bcrypt` before being stored in the database.
2. **Stateless Authentication with Stateful Invalidation:**
   - On successful login, the server issues a JWT containing the user identity and an expiration claim (`exp`).
   - Standard FastAPI dependency injection (`Depends`) will be used to protect existing endpoints (e.g. associating requests/threads/bookings with the authenticated user instead of using a hardcoded `"anonymous"` user).
   - **Logout Solution:** To invalidate tokens upon logout without resorting to heavy state, a `token_blacklist` SQLite table will be created. The system will store logged-out tokens until their expiration time, returning an unauthorized error if a blacklisted token is presented.
3. **Email Verification & Password Reset:**
   - Both features will use unique, cryptographically secure random tokens.
   - For verification: `is_verified` (boolean check).
   - For forget password: A request generates a reset token, and a corresponding `/auth/reset-password` endpoint processes the token to complete the password change safely.
   - Mail delivery is simulated using logger output in the console containing the generated links (e.g., `http://127.0.0.1:8000/auth/verify-email?token=...`).

---

## User Review Required

> [!IMPORTANT]
> Please review the following design decisions and confirm before we proceed:
> 
> 1. **Token Blacklist on Logout:** We are proposing a `token_blacklist` table in the SQLite database to store logged-out tokens until their natural expiration. This provides complete security by ensuring that once a user clicks "Log out", that JWT is immediately invalidated server-side. Are you comfortable with this approach?
> 2. **Authentication Enforcement:** Once authentication is added, should we make the current `/request`, `/threads`, and `/bookings` endpoints **strictly require** authentication, or should we keep them open with a fallback to the `"anonymous"` user for backward compatibility?
> 3. **Reset Password Route:** In addition to the requested `/auth/forgot-password` endpoint, we have proposed a `/auth/reset-password` endpoint to complete the password change process using the generated reset token.

---

## Open Questions

> [!NOTE]
> - **JWT Expiration Time:** What should be the lifetime of the access token? We propose a standard 60 minutes.
> - **JWT Secret Key:** We will load `JWT_SECRET_KEY` and `JWT_ALGORITHM` (default HS256) from environment variables. If `JWT_SECRET_KEY` is missing in production, we will raise an error, but fallback to a generated random string for dev environments.

---

## Proposed Changes

### Dependencies

#### [MODIFY] [pyproject.toml](file:///c:/Users/User-1/Music/informalServicesMPAgent/pyproject.toml)
Add standard libraries for JWT and hashing:
* `pyjwt>=2.8.0` (For encoding and decoding JWTs securely)
* `bcrypt>=4.1.0` (For modern, secure password hashing)

---

### Database Setup

#### [MODIFY] [db_setup.py](file:///c:/Users/User-1/Music/informalServicesMPAgent/db_setup.py)
Extend the SQLite setup script to create:
1. `users` table:
   ```sql
   CREATE TABLE IF NOT EXISTS users (
       id INTEGER PRIMARY KEY AUTOINCREMENT,
       email TEXT UNIQUE NOT NULL,
       password_hash TEXT NOT NULL,
       is_verified INTEGER DEFAULT 0,
       verification_token TEXT,
       reset_token TEXT,
       created_at TEXT NOT NULL
   )
   ```
2. `token_blacklist` table:
   ```sql
   CREATE TABLE IF NOT EXISTS token_blacklist (
       token TEXT PRIMARY KEY,
       expires_at TEXT NOT NULL
   )
   ```

#### [MODIFY] [src/db.py](file:///c:/Users/User-1/Music/informalServicesMPAgent/src/db.py)
* Add `users` and `token_blacklist` to `REQUIRED_TABLES` list.
* Add helper async functions for database operations:
  * `get_user_by_email(email)`
  * `create_user(email, password_hash, verification_token)`
  * `verify_user_email(token)`
  * `update_verification_token(email, token)`
  * `set_reset_token(email, token)`
  * `reset_user_password(token, new_password_hash)`
  * `blacklist_token(token, expires_at)`
  * `is_token_blacklisted(token)`

---

### Router & Endpoints

#### [NEW] [src/auth.py](file:///c:/Users/User-1/Music/informalServicesMPAgent/src/auth.py)
Implement the core authentication logic, Pydantic schemas, and endpoints:
* **Utilities:**
  * Password hashing (`bcrypt.hashpw` & `bcrypt.checkpw`)
  * Token generation (`jwt.encode`)
  * Token verification and loading current user (`Depends(oauth2_scheme)`)
* **Endpoints:**
  * `POST /auth/signup` - Receives email & password, hashes password, saves user with a generated `verification_token`, logs simulated email containing the verification link.
  * `GET /auth/verify-email` - Validates the verification token and flags user as `is_verified=1`.
  * `POST /auth/resend-verification` - Regenerates and updates the verification token, logs the simulated email.
  * `POST /auth/login` - Validates credentials, checks verification status, issues JWT token.
  * `POST /auth/logout` - Extracts active JWT token and adds it to `token_blacklist` table.
  * `POST /auth/forgot-password` - Sets a cryptographically secure `reset_token` and logs recovery link.
  * `POST /auth/reset-password` - Resets password with a valid `reset_token`, clearing the token afterward.

---

### Integration

#### [MODIFY] [src/main.py](file:///c:/Users/User-1/Music/informalServicesMPAgent/src/main.py)
* Import the new router: `from src.auth import router as auth_router`
* Register the router: `app.include_router(auth_router, prefix="/auth", tags=["Authentication"])`
* Optional: Provide dependency injection to resolve `user_id` from the JWT in current endpoints rather than defaulting to `"anonymous"`.

---

## Verification Plan

### Automated/Manual Testing

1. **Verify Database Creation:**
   Run `python db_setup.py` and verify `users` and `token_blacklist` tables are successfully initialized in `service_agent.db`.

2. **Test Endpoints via `curl`:**
   * **Signup:**
     ```powershell
     curl -X POST http://127.0.0.1:8000/auth/signup -H "Content-Type: application/json" -d '{"email":"test@example.com","password":"SecurePassword123"}'
     ```
     Verify response is successful and prints a mock verification link in the console.
   * **Resend Verification:**
     ```powershell
     curl -X POST http://127.0.0.1:8000/auth/resend-verification -H "Content-Type: application/json" -d '{"email":"test@example.com"}'
     ```
   * **Verify Email:**
     ```powershell
     curl "http://127.0.0.1:8000/auth/verify-email?token=<token_from_logs>"
     ```
   * **Login (Expect JWT Token):**
     ```powershell
     curl -X POST http://127.0.0.1:8000/auth/login -H "Content-Type: application/json" -d '{"email":"test@example.com","password":"SecurePassword123"}'
     ```
   * **Logout:**
     ```powershell
     curl -X POST http://127.0.0.1:8000/auth/logout -H "Authorization: Bearer <jwt_token>"
     ```
   * **Forgot Password:**
     ```powershell
     curl -X POST http://127.0.0.1:8000/auth/forgot-password -H "Content-Type: application/json" -d '{"email":"test@example.com"}'
     ```
   * **Reset Password:**
     ```powershell
     curl -X POST http://127.0.0.1:8000/auth/reset-password -H "Content-Type: application/json" -d '{"token":"<reset_token_from_logs>","new_password":"NewSecurePassword789"}'
     ```
