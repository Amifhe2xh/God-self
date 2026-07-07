import os
import sys
import base64
import asyncio
import logging

logger = logging.getLogger(__name__)

CIPHER_REPO = "https://github.com/rishabhops/CipherElite.git"
CIPHER_DIR = os.path.join(os.getcwd(), "CipherElite")
USERS_DIR = os.path.join(os.getcwd(), "data", "cipher_users")


def fix_session_padding(session_str: str) -> str:
    """Fix base64 padding for session string."""
    session_str = session_str.strip()
    # Remove any whitespace or newlines
    session_str = session_str.replace("\n", "").replace("\r", "").replace(" ", "")
    # Fix padding
    missing = len(session_str) % 4
    if missing:
        session_str += "=" * (4 - missing)
    # Verify it's valid base64
    try:
        base64.urlsafe_b64decode(session_str)
        logger.info(f"Session string valid, length={len(session_str)}")
    except Exception as e:
        logger.warning(f"Session string decode issue: {e}")
    return session_str


class CipherManager:
    def __init__(self, db):
        self.db = db
        self.processes: dict[int, asyncio.subprocess.Process] = {}
        self.monitors: dict[int, bool] = {}
        os.makedirs(USERS_DIR, exist_ok=True)

    @staticmethod
    async def ensure_cipherelite():
        # Check multiple possible entry points
        main_py = os.path.join(CIPHER_DIR, "main.py")
        if os.path.isfile(main_py):
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

        logger.info("Installing CipherElite dependencies...")
        req_file = os.path.join(CIPHER_DIR, "requirements.txt")
        if os.path.isfile(req_file):
            proc2 = await asyncio.create_subprocess_exec(
                sys.executable, "-m", "pip", "install",
                "-r", req_file,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            stdout2, _ = await proc2.communicate()
            if proc2.returncode != 0:
                logger.warning(f"Some deps may have failed")

        if os.path.isfile(main_py):
            logger.info("CipherElite ready!")
            return True
        else:
            logger.error("main.py not found after clone!")
            # List what's in the directory
            for f in os.listdir(CIPHER_DIR):
                logger.info(f"  Found: {f}")
            return False

    async def start_instance(self, user_id: int, api_id: int,
                             api_hash: str, session_string: str,
                             prefix: str = ".") -> bool:
        await self.stop_instance(user_id)

        user_dir = os.path.join(USERS_DIR, str(user_id))
        os.makedirs(user_dir, exist_ok=True)

        # Fix session padding
        session_string = fix_session_padding(session_string)

        logger.info(f"Session for {user_id}: length={len(session_string)}")

        # Write .env file carefully
        env_path = os.path.join(CIPHER_DIR, ".env")
        try:
            with open(env_path, "w", encoding="utf-8") as f:
                f.write(f"API_ID={api_id}\n")
                f.write(f"API_HASH={api_hash}\n")
                f.write(f"ELITE_SESSION={session_string}\n")
                f.write(f"PREFIX={prefix}\n")
            logger.info(f".env written with session length {len(session_string)}")

            # Verify what was written
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    if "ELITE_SESSION" in line:
                        parts = line.strip().split("=", 1)
                        if len(parts) == 2:
                            read_session = parts[1]
                            logger.info(
                                f".env verified: ELITE_SESSION "
                                f"length={len(read_session)}"
                            )
        except Exception as e:
            logger.error(f"Failed to write .env: {e}")
            return False

        # Also set as environment variable
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
            main_py = os.path.join(CIPHER_DIR, "main.py")
            if not os.path.isfile(main_py):
                logger.error("main.py not found!")
                return False

            cmd = [sys.executable, main_py]
            logger.info(f"Starting CipherElite for {user_id}: {' '.join(cmd)}")

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

            logger.info(f"CipherElite PID {proc.pid} for user {user_id}")

            asyncio.create_task(
                self._monitor(user_id, api_id, api_hash, session_string, prefix)
            )

            # Wait and check
            await asyncio.sleep(5)

            if proc.returncode is not None:
                stderr_out = (await proc.stderr.read()).decode(errors="replace")
                stdout_out = (await proc.stdout.read()).decode(errors="replace")
                logger.error(
                    f"CipherElite crashed for {user_id}:\n"
                    f"STDOUT: {stdout_out[-500:]}\n"
                    f"STDERR: {stderr_out[-500:]}"
                )
                return False

            logger.info(f"CipherElite running for {user_id}")
            return True

        except Exception as e:
            logger.error(f"start_instance error for {user_id}: {e}")
            return False

    async def stop_instance(self, user_id: int):
        self.monitors.pop(user_id, None)
        proc = self.processes.pop(user_id, None)
        if proc and proc.returncode is None:
            try:
                proc.terminate()
                await asyncio.sleep(2)
                if proc.returncode is None:
                    proc.kill()
            except ProcessLookupError:
                pass
            logger.info(f"Stopped CipherElite for {user_id}")
        self.db.set_pid(user_id, 0)

    async def _monitor(self, user_id, api_id, api_hash,
                       session_string, prefix):
        retries = 0
        max_retries = 3

        while self.monitors.get(user_id, False):
            proc = self.processes.get(user_id)
            if not proc:
                break

            if proc.returncode is not None:
                retries += 1
                if retries > max_retries:
                    logger.error(
                        f"Max retries reached for {user_id}. Giving up."
                    )
                    self.monitors.pop(user_id, None)
                    self.db.deactivate_user(user_id)
                    break

                logger.warning(
                    f"Restarting CipherElite for {user_id} "
                    f"({retries}/{max_retries})"
                )
                await asyncio.sleep(5)
                if self.monitors.get(user_id, False):
                    await self.start_instance(
                        user_id, api_id, api_hash, session_string, prefix
                    )
                    break
            else:
                retries = 0

            await asyncio.sleep(15)

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

    async def stop_all(self):
        self.monitors.clear()
        for uid in list(self.processes):
            await self.stop_instance(uid)
        logger.info("All CipherElite instances stopped.")

    def is_running(self, user_id: int) -> bool:
        proc = self.processes.get(user_id)
        return proc is not None and proc.returncode is None