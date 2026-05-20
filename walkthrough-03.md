# Authentication & JWT Implementation Walkthrough

This walkthrough details the design, changes, and verification of the new JWT-based authentication layer added to the Agentic AI Service Request System.

---

## 1. Database Additions
Two new tables were added to the SQLite database structure:
* **`users`**: Contains user credentials, verification status (`is_verified`), registration date, and email verification/password reset token states.
* **`token_blacklist`**: Implements stateful server-side invalidation of stateless JWT access tokens upon logout.

#### Schema definitions added to [db_setup.py](file:///c:/Users/User-1/Music/informalServicesMPAgent/db_setup.py):
```sql
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    is_verified INTEGER DEFAULT 0,
    verification_token TEXT,
    reset_token TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS token_blacklist (
    token TEXT PRIMARY KEY,
    expires_at TEXT NOT NULL
);
```

#### Helper database queries added to [src/db.py](file:///c:/Users/User-1/Music/informalServicesMPAgent/src/db.py):
* `get_user_by_email(email)`
* `create_user(email, password_hash, verification_token)`
* `verify_user_email(token)`
* `update_verification_token(email, token)`
* `set_reset_token(email, token)`
* `reset_user_password(token, new_password_hash)`
* `blacklist_token(token, expires_at)`
* `is_token_blacklisted(token)`

---

## 2. Authentication Router (`src/auth.py`)

A brand new module [auth.py](file:///c:/Users/User-1/Music/informalServicesMPAgent/src/auth.py) was created to centralize all authentication logic, token processing, Pydantic schemas, and endpoints:
* **Signup (`POST /auth/signup`)**: Hashes the plain text password using `bcrypt`, inserts the user record, and logs a simulated activation email in the console containing the verification link.
* **Verify Email (`GET /auth/verify-email`)**: Activates the user account when the validation link is hit.
* **Resend Verification (`POST /auth/resend-verification`)**: Regenerates and logs the activation link if the user missed it.
* **Login (`POST /auth/login`)**: Performs credentials checks, verifies that the user is validated, and generates a JWT token with a **1-week** lifetime loaded dynamically from the environment.
* **Logout (`POST /auth/logout`)**: Extracts the bearer token and adds it to the database `token_blacklist` to prevent subsequent re-use of that session.
* **Forgot Password (`POST /auth/forgot-password`)**: Generates and prints a simulated password recovery link.
* **Reset Password (`POST /auth/reset-password`)**: Allows resetting the user's password utilizing the secure reset link.

---

## 3. Strict Application Safeguarding (`src/main.py`)

All service endpoints in [main.py](file:///c:/Users/User-1/Music/informalServicesMPAgent/src/main.py) were strictly safeguarded using standard FastAPI dependency injection (`Depends(get_current_user)`):
* **Router Integration:**
  ```python
  from src.auth import get_current_user, router as auth_router
  app.include_router(auth_router, prefix="/auth", tags=["Authentication"])
  ```
* **Strict Endpoint Authorization & Thread Ownership Verification:**
  * **`POST /request`**: Extracts the user's identity from the active JWT session. If an existing `thread_id` is supplied, it queries SQLite to check that the thread is owned by the logged-in user. If not, it raises a `403 Forbidden` response.
  * **`GET /threads/{user_id}` & `GET /bookings/{user_id}`**: Ensures that the `user_id` query param matches the email of the active logged-in user.
  * **`GET /threads/{thread_id}/messages`**: Verifies that the requested thread exists and is owned by the authenticated caller.

---

## 4. Verification Results

We verified all 12 operational scenarios automatically using our test harness:
1. **Signup**: Succeeded with mock verification link generation.
2. **Login before email verification**: Failed as expected (`400: Please verify your email before logging in`).
3. **Resend verification link**: Succeeded and logged the verification token.
4. **Email verification**: Activated user successfully (`200 OK`).
5. **Login after verification**: Successfully generated the signed JWT.
6. **Access protected endpoint without token**: Safely rejected (`401 Unauthorized`).
7. **Access protected endpoint with valid token**: Succeeded (`200 OK`).
8. **Forgot password**: Generated reset token link successfully.
9. **Reset password**: Successfully changed password using the reset link.
10. **Login with new password**: Succeeded and returned a valid new token.
11. **Logout**: Added token to blacklist.
12. **Access protected endpoint with blacklisted token**: Safely rejected (`401: Token has been logged out`).

---

The new authentication layer is fully robust, verified, and integrated into the application lifespan.
