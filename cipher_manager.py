import os
import sys
import shutil
import signal
import asyncio
import logging

logger = logging.getLogger(__name__)

CIPHER_REPO = "https://github.com/rishabhops/CipherElite.git"
CIPHER_DIR = os.path.join(os.getcwd(), "CipherElite")
USERS_DIR = os.path.join(os.getcwd(), "data", "cipher_users")


class CipherManager:
    def __init__(self, db):
        self.db = db
        self.processes: dict[int, asyncio.subprocess.Process] = {}
        self.monitors: dict[int, bool] = {}
        os.makedirs(USERS_DIR, exist_ok=True)

    # ── Clone CipherElite (called once at startup) ───────────

    @staticmethod
    async def ensure_cipherelite():
        if os.path.isdir(os.path.join(CIPHER_DIR, "heroku")):
            logger.info("CipherElite already present.")
            return True

        logger.info("Cloning CipherElite...")
        proc = await asyncio.create_subprocess_exec(
            "git", "clone", "--depth=1", CIPHER_REPO, CIPHER_DIR,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            logger.error(f"Clone failed: {stderr.decode()}")
            return False

        logger.info("Installing CipherElite requirements...")
        req_file = os.path.join(CIPHER_DIR, "requirements.txt")
        if os.path.isfile(req_file):
            proc2 = await asyncio.create_subprocess_exec(
                sys.executable, "-m", "pip", "install", "-r", req_file,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc2.communicate()
            if proc2.returncode != 0:
                logger.warning("Some CipherElite deps may have failed.")

        logger.info("CipherElite ready.")
        return True

    # ── Start a CipherElite instance for a user ──────────────

    async def start_instance(self, user_id: int, api_id: int,
                             api_hash: str, session_string: str,
                             prefix: str = ".") -> bool:
        # stop if already running
        await self.stop_instance(user_id)

        user_dir = os.path.join(USERS_DIR, str(user_id))
        os.makedirs(user_dir, exist_ok=True)

        # write .env for this user
        env_content = (
            f"API_ID={api_id}\n"
            f"API_HASH={api_hash}\n"
            f"ELITE_SESSION={session_string}\n"
            f"PREFIX={prefix}\n"
        )
        env_path = os.path.join(CIPHER_DIR, ".env")
        with open(env_path, "w") as f:
            f.write(env_content)

        # build environment
        env = os.environ.copy()
        env.update({
            "API_ID": str(api_id),
            "API_HASH": api_hash,
            "ELITE_SESSION": session_string,
            "PREFIX": prefix,
            "HOME": user_dir,
            "XDG_DATA_HOME": os.path.join(user_dir, "data"),
            "XDG_CONFIG_HOME": os.path.join(user_dir, "config"),
        })

        try:
            # determine entry point
            main_py = os.path.join(CIPHER_DIR, "main.py")

            if os.path.isfile(main_py):
                cmd = [sys.executable, main_py]
            else:
                cmd = [sys.executable, "-m", "heroku"]

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=CIPHER_DIR,
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            self.processes[user_id] = proc
            self.db.set_pid(user_id, proc.pid)
            self.monitors[user_id] = True

            logger.info(
                f"CipherElite started for user {user_id} (PID: {proc.pid})"
            )

            # start monitoring task
            asyncio.create_task(self._monitor(user_id, api_id, api_hash,
                                               session_string, prefix))

            # wait a bit and check if it crashed immediately
            await asyncio.sleep(3)
            if proc.returncode is not None:
                stderr = await proc.stderr.read()
                logger.error(
                    f"CipherElite crashed for {user_id}: "
                    f"{stderr.decode()[-500:]}"
                )
                return False

            return True

        except Exception as e:
            logger.error(f"Failed to start CipherElite for {user_id}: {e}")
            return False

    # ── Stop a user's instance ───────────────────────────────

    async def stop_instance(self, user_id: int):
        self.monitors.pop(user_id, None)
        proc = self.processes.pop(user_id, None)
        if proc and proc.returncode is None:
            try:
                proc.send_signal(signal.SIGTERM)
                await asyncio.sleep(2)
                if proc.returncode is None:
                    proc.kill()
            except ProcessLookupError:
                pass
            logger.info(f"CipherElite stopped for user {user_id}")
        self.db.set_pid(user_id, 0)

    # ── Monitor & auto-restart ───────────────────────────────

    async def _monitor(self, user_id, api_id, api_hash,
                       session_string, prefix):
        retries = 0
        max_retries = 5

        while self.monitors.get(user_id, False):
            proc = self.processes.get(user_id)
            if not proc:
                break

            if proc.returncode is not None:
                retries += 1
                if retries > max_retries:
                    logger.error(
                        f"CipherElite for {user_id} exceeded max retries."
                    )
                    self.monitors.pop(user_id, None)
                    self.db.deactivate_user(user_id)
                    break

                logger.warning(
                    f"CipherElite for {user_id} crashed. "
                    f"Restarting ({retries}/{max_retries})..."
                )
                await asyncio.sleep(5)
                if self.monitors.get(user_id, False):
                    await self.start_instance(
                        user_id, api_id, api_hash,
                        session_string, prefix,
                    )
                    # the new start_instance will create its own monitor
                    break
            else:
                retries = 0  # reset on healthy check

            await asyncio.sleep(10)

    # ── Restore all active sessions ──────────────────────────

    async def restore_all(self) -> int:
        users = self.db.get_all_active()
        ok = 0
        for u in users:
            success = await self.start_instance(
                u["user_id"], u["api_id"], u["api_hash"],
                u["session_string"], u.get("prefix", "."),
            )
            if success:
                ok += 1
            else:
                self.db.deactivate_user(u["user_id"])
        return ok

    # ── Stop everything ──────────────────────────────────────

    async def stop_all(self):
        self.monitors.clear()
        for uid in list(self.processes):
            await self.stop_instance(uid)
        logger.info("All CipherElite instances stopped.")

    # ── Get status ───────────────────────────────────────────

    def is_running(self, user_id: int) -> bool:
        proc = self.processes.get(user_id)
        return proc is not None and proc.returncode is None