# Checklist for Authentication and JWT implementation

- [x] Add packages `pyjwt` and `bcrypt` to `pyproject.toml` and install them.
- [x] Set environment variables in `.env`: `JWT_SECRET_KEY`, `JWT_ALGORITHM`, and `JWT_ACCESS_TOKEN_EXPIRE_DAYS`.
- [x] Modify `db_setup.py` to create `users` and `token_blacklist` tables.
- [x] Update `src/db.py` to:
  - Add `users` and `token_blacklist` to validation and database helpers.
  - Implement async database functions for user CRUD, verification, password reset, and blacklist management.
- [x] Create `src/auth.py` with:
  - Password hashing and JWT generation/validation logic.
  - Authentication FastAPI dependency injection for current user parsing.
  - Endpoints: sign up, verify email, resend verification, login, logout, forget password, and reset password.
- [x] Modify `src/main.py` to:
  - Register `auth_router`.
  - Update `/request`, `/threads`, `/bookings` to strictly require authentication and use the logged-in user's ID.
- [x] Verify the implementation using manual curl queries.
