import os
import sys
import asyncio
import logging

logger = logging.getLogger(__name__)

CIPHER_DIR = os.path.join(os.getcwd(), "CipherElite")
USERS_DIR = os.path.join(os.getcwd(), "data", "cipher_users")


class CipherManager:
    def __init__(self, db):
        self.db = db
        self.processes: dict[int, asyncio.subprocess.Process] = {}
        self.monitors: dict[int, bool] = {}
        os.makedirs(USERS_DIR, exist_ok=True)

    async def start_instance(self, user_id: int, api_id: int,
                             api_hash: str, session_string: str,
                             prefix: str = ".") -> bool:
        await self.stop_instance(user_id)

        user_dir = os.path.join(USERS_DIR, str(user_id))
        os.makedirs(user_dir, exist_ok=True)

        env_path = os.path.join(CIPHER_DIR, ".env")
        try:
            with open(env_path, "w", encoding="utf-8") as f:
                f.write(f"API_ID={api_id}\n")
                f.write(f"API_HASH={api_hash}\n")
                f.write(f"ELITE_SESSION={session_string}\n")
                f.write(f"PREFIX={prefix}\n")
            logger.info(f".env written, session={len(session_string)} chars")
        except Exception as e:
            logger.error(f"Failed to write .env: {e}")
            return False

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

            proc = await asyncio.create_subprocess_exec(
                sys.executable, main_py,
                cwd=CIPHER_DIR,
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            self.processes[user_id] = proc
            self.db.set_pid(user_id, proc.pid)
            self.monitors[user_id] = True
            logger.info(f"CipherElite PID {proc.pid} for {user_id}")

            asyncio.create_task(
                self._monitor(user_id, api_id, api_hash,
                              session_string, prefix)
            )

            await asyncio.sleep(5)

            if proc.returncode is not None:
                out = (await proc.stdout.read()).decode(errors="replace")
                err = (await proc.stderr.read()).decode(errors="replace")
                logger.error(
                    f"Crashed for {user_id}:\nOUT:{out[-400:]}\nERR:{err[-400:]}"
                )
                return False

            logger.info(f"CipherElite running for {user_id}")
            return True

        except Exception as e:
            logger.error(f"Error for {user_id}: {e}")
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
            logger.info(f"Stopped for {user_id}")
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
                    logger.error(f"Max retries for {user_id}")
                    self.monitors.pop(user_id, None)
                    self.db.deactivate_user(user_id)
                    break
                logger.warning(f"Restart {retries}/{max_retries} for {user_id}")
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
            if await self.start_instance(
                u["user_id"], u["api_id"], u["api_hash"],
                u["session_string"], u.get("prefix", "."),
            ):
                ok += 1
            else:
                self.db.deactivate_user(u["user_id"])
        return ok

    async def stop_all(self):
        self.monitors.clear()
        for uid in list(self.processes):
            await self.stop_instance(uid)

    def is_running(self, user_id: int) -> bool:
        proc = self.processes.get(user_id)
        return proc is not None and proc.returncode is None