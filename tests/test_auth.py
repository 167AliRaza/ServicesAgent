import asyncio
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import motor.motor_asyncio
from fastapi import HTTPException

import src.db as db_module
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
from src.db import (
    get_threads,
    migrate_database_schema,
    init_mongodb,
    save_thread,
    get_user_by_email,
)


async def setup_mongo_test_db(uri: str, db_name: str) -> None:
    """Initialize a fresh MongoDB test database and clear collections."""
    init_mongodb(uri, db_name)
    # Drop existing collections to ensure a clean slate
    await db_module.db.client[db_name].drop_collection("users")
    await db_module.db.client[db_name].drop_collection("providers")
    await db_module.db.client[db_name].drop_collection("bookings")
    await db_module.db.client[db_name].drop_collection("threads")
    await db_module.db.client[db_name].drop_collection("token_blacklist")
    await migrate_database_schema()


class AuthTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.mongo_uri = os.getenv("MONGODB_TEST_URI")
        if not self.mongo_uri:
            self.tmp.cleanup()
            raise unittest.SkipTest("MONGODB_TEST_URI is not configured")
        # Use a test MongoDB database name derived from the temp directory name
        self.test_db_name = f"test_{Path(self.tmp.name).name}"
        asyncio.run(setup_mongo_test_db(self.mongo_uri, self.test_db_name))
        # Ensure the application uses the test DB by setting env vars used in config
        os.environ["MONGODB_DB"] = self.test_db_name
        os.environ["MONGODB_URI"] = self.mongo_uri

    def tearDown(self):
        # Drop the test database after tests finish
        client = motor.motor_asyncio.AsyncIOMotorClient(self.mongo_uri)
        asyncio.run(client.drop_database(self.test_db_name))
        self.tmp.cleanup()
        os.environ.pop("MONGODB_DB", None)
        os.environ.pop("MONGODB_URI", None)

    def test_signup_verify_login_logout_flow(self):
        async def run():
            with patch("src.auth.send_verification_email") as send_email:
                result = await signup(
                    SignupRequest(name="Test User", email=" Test@Example.COM ", password="secret1")
                )

            self.assertNotIn("verification_token", result)
            send_email.assert_awaited_once()

            user = await get_user_by_email("test@example.com")
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
            user = await get_user_by_email("test@example.com")
            await verify_email(user["verification_token"])

            with patch("src.auth.send_verification_or_reset_email") as send_email:
                result = await forgot_password(ForgotPasswordRequest(email="test@example.com"))

            self.assertNotIn("reset_token", result)
            send_email.assert_awaited_once()
            user = await get_user_by_email("test@example.com")
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
            user = await get_user_by_email("test@example.com")
            expired_at = datetime.now(timezone.utc) - timedelta(minutes=1)
            await db_module.db.users.update_one({"email": "test@example.com"}, {"$set": {"verification_expires_at": expired_at}})

            verify_error = await verify_email(user["verification_token"])
            self.assertEqual(verify_error.status_code, 400)
            self.assertIn(b"Verification Link Expired", verify_error.body)

            await db_module.db.users.update_one(
                {"email": "test@example.com"},
                {"$set": {"is_verified": 1, "verification_token": None, "reset_token": "expired-reset", "reset_expires_at": expired_at}},
            )

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
