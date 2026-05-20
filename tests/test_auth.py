import asyncio
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import aiosqlite
from fastapi import HTTPException

from src.auth import (
    ForgotPasswordRequest,
    LoginRequest,
    ResetPasswordRequest,
    ResendVerificationRequest,
    SignupRequest,
    create_access_token,
    get_current_user,
    login,
    logout,
    forgot_password,
    reset_password,
    reset_password_form,
    resend_verification,
    signup,
    verify_email,
)
from src.db import get_threads, migrate_database_schema, save_thread


async def setup_auth_db(path: Path) -> None:
    async with aiosqlite.connect(path) as conn:
        await conn.execute(
            """
            CREATE TABLE providers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                service_type TEXT,
                location TEXT,
                rating REAL,
                base_price REAL,
                available BOOLEAN
            )
            """
        )
        await conn.execute(
            """
            CREATE TABLE bookings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                provider_id INTEGER,
                user_id TEXT,
                booking_time TEXT,
                status TEXT
            )
            """
        )
        await conn.execute(
            """
            CREATE TABLE threads (
                thread_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                title TEXT NOT NULL DEFAULT 'New Conversation',
                created_at TEXT NOT NULL
            )
            """
        )
        await conn.execute(
            """
            CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL DEFAULT '',
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                is_verified INTEGER DEFAULT 0,
                verification_token TEXT,
                reset_token TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        await conn.execute(
            """
            CREATE TABLE token_blacklist (
                token TEXT PRIMARY KEY,
                expires_at TEXT NOT NULL
            )
            """
        )
        await conn.commit()


async def get_user_row(email: str) -> dict:
    async with aiosqlite.connect(os.environ["SERVICE_AGENT_DB"]) as conn:
        conn.row_factory = aiosqlite.Row
        cursor = await conn.execute("SELECT * FROM users WHERE email = ?", (email,))
        row = await cursor.fetchone()
        return dict(row)


class AuthTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "service_agent.db"
        os.environ["SERVICE_AGENT_DB"] = str(self.db_path)
        asyncio.run(setup_auth_db(self.db_path))
        asyncio.run(migrate_database_schema())

    def tearDown(self):
        self.tmp.cleanup()
        os.environ.pop("SERVICE_AGENT_DB", None)

    def test_signup_verify_login_logout_flow(self):
        async def run():
            with patch("src.auth.send_verification_email") as send_email:
                result = await signup(SignupRequest(name="Test User", email=" Test@Example.COM ", password="secret1"))

            self.assertNotIn("verification_token", result)
            send_email.assert_awaited_once()

            user = await get_user_row("test@example.com")
            self.assertEqual(user["name"], "Test User")
            self.assertEqual(user["email"], "test@example.com")
            self.assertNotEqual(user["password_hash"], "secret1")
            self.assertTrue(user["verification_token"])
            self.assertTrue(user["verification_expires_at"])

            with self.assertRaises(HTTPException) as login_error:
                await login(LoginRequest(email="test@example.com", password="secret1"))
            self.assertEqual(login_error.exception.status_code, 400)

            verify_result = await verify_email(user["verification_token"])
            self.assertEqual(verify_result.status_code, 200)
            self.assertIn(b"Email Verified", verify_result.body)

            login_result = await login(LoginRequest(email="test@example.com", password="secret1"))
            self.assertEqual(login_result["token_type"], "bearer")
            token = login_result["access_token"]
            current_user = await get_current_user(token)
            self.assertEqual(current_user["email"], "test@example.com")

            await logout(current_user=current_user, token=token)
            with self.assertRaises(HTTPException) as auth_error:
                await get_current_user(token)
            self.assertEqual(auth_error.exception.status_code, 401)

        asyncio.run(run())

    def test_forgot_and_reset_password_do_not_expose_token(self):
        async def run():
            with patch("src.auth.send_verification_email"):
                await signup(SignupRequest(name="Test User", email="test@example.com", password="oldpass"))
            user = await get_user_row("test@example.com")
            await verify_email(user["verification_token"])

            with patch("src.auth.send_verification_or_reset_email") as send_email:
                result = await forgot_password(ForgotPasswordRequest(email="test@example.com"))

            self.assertNotIn("reset_token", result)
            send_email.assert_awaited_once()
            user = await get_user_row("test@example.com")
            self.assertTrue(user["reset_token"])
            self.assertTrue(user["reset_expires_at"])

            await reset_password(ResetPasswordRequest(token=user["reset_token"], new_password="newpass1"))
            login_result = await login(LoginRequest(email="test@example.com", password="newpass1"))
            self.assertEqual(login_result["token_type"], "bearer")

            with self.assertRaises(HTTPException):
                await reset_password(ResetPasswordRequest(token=user["reset_token"], new_password="newpass2"))

            missing_result = await forgot_password(ForgotPasswordRequest(email="missing@example.com"))
            self.assertEqual(
                missing_result["message"],
                "If the email is registered, a password reset link has been sent.",
            )

        asyncio.run(run())

    def test_expired_action_tokens_are_rejected(self):
        async def run():
            with patch("src.auth.send_verification_email"):
                await signup(SignupRequest(name="Test User", email="test@example.com", password="secret1"))
            user = await get_user_row("test@example.com")
            expired_at = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
            async with aiosqlite.connect(self.db_path) as conn:
                await conn.execute(
                    "UPDATE users SET verification_expires_at = ? WHERE email = ?",
                    (expired_at, "test@example.com"),
                )
                await conn.commit()

            verify_error = await verify_email(user["verification_token"])
            self.assertEqual(verify_error.status_code, 400)
            self.assertIn(b"Verification Link Expired", verify_error.body)

            async with aiosqlite.connect(self.db_path) as conn:
                await conn.execute(
                    """
                    UPDATE users
                    SET is_verified = 1,
                        verification_token = NULL,
                        reset_token = ?,
                        reset_expires_at = ?
                    WHERE email = ?
                    """,
                    ("expired-reset", expired_at, "test@example.com"),
                )
                await conn.commit()

            with self.assertRaises(HTTPException) as reset_error:
                await reset_password(ResetPasswordRequest(token="expired-reset", new_password="newpass1"))
            self.assertEqual(reset_error.exception.status_code, 400)

        asyncio.run(run())

    def test_get_threads_returns_thread_fields(self):
        async def run():
            await save_thread("thread-1", "test@example.com", title="AC Repair")
            rows = await get_threads("test@example.com")
            self.assertEqual(
                rows,
                [{"thread_id": "thread-1", "title": "AC Repair", "created_at": rows[0]["created_at"]}],
            )
            self.assertNotIn("booking_id", rows[0])

        asyncio.run(run())

    def test_get_current_user_rejects_unverified_and_blacklisted_tokens(self):
        async def run():
            with patch("src.auth.send_verification_email"):
                await signup(SignupRequest(name="Test User", email="test@example.com", password="secret1"))
            token = create_access_token({"sub": "test@example.com"})
            with self.assertRaises(HTTPException) as unverified_error:
                await get_current_user(token)
            self.assertEqual(unverified_error.exception.status_code, 403)

        asyncio.run(run())

    def test_resend_verification_uses_same_mailer_as_signup(self):
        async def run():
            with patch("src.auth.send_verification_email"):
                await signup(SignupRequest(name="Test User", email="test@example.com", password="secret1"))

            with patch("src.auth.send_verification_email") as send_email:
                result = await resend_verification(ResendVerificationRequest(email="test@example.com"))

            self.assertEqual(result["message"], "Verification link sent successfully.")
            send_email.assert_awaited_once()
            self.assertEqual(send_email.await_args.args[0], "test@example.com")

        asyncio.run(run())

    def test_signup_requires_name(self):
        async def run():
            with self.assertRaises(HTTPException) as error:
                await signup(SignupRequest(name=" ", email="test@example.com", password="secret1"))
            self.assertEqual(error.exception.status_code, 400)
            self.assertEqual(error.exception.detail, "Name is required")

        asyncio.run(run())

    def test_reset_password_link_renders_browser_form(self):
        async def run():
            response = await reset_password_form("reset-token")
            self.assertEqual(response.status_code, 200)
            self.assertIn(b"Reset Password", response.body)
            self.assertIn(b"/auth/reset-password", response.body)
            self.assertIn(b"reset-token", response.body)

        asyncio.run(run())
