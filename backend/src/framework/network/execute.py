"""Generic subprocess execution. No application models, storage, or job states."""

import subprocess
import threading
from collections.abc import Iterator


class ProcessError(RuntimeError):
    pass


class CommandRunner:
    def completed(self, args: list[str], *, timeout: float):
        try:
            return subprocess.run(
                args,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise ProcessError(f"{args[0]} timed out after {timeout}s") from exc
        except OSError as exc:
            raise ProcessError(f"Cannot start executable: {args[0]}") from exc

    def status(self, args: list[str], *, timeout: float) -> int:
        return self.completed(args, timeout=timeout).returncode

    def run(self, args: list[str], *, timeout: float, sensitive: bool = False) -> str:
        result = self.completed(args, timeout=timeout)
        if result.returncode:
            detail = "Sensitive command failed" if sensitive else result.stderr[-1500:]
            raise ProcessError(f"{args[0]} failed ({result.returncode}): {detail}")
        return result.stdout.strip()

    def stream(self, args: list[str], content: str, *, timeout: float) -> Iterator[str]:
        try:
            process = subprocess.Popen(
                args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except OSError as exc:
            raise ProcessError(f"Cannot start executable: {args[0]}") from exc
        expired = threading.Event()
        write_errors = []

        def kill():
            expired.set()
            if process.poll() is None:
                process.kill()

        def send():
            try:
                process.stdin.write(content)
            except (BrokenPipeError, OSError) as exc:
                write_errors.append(exc)
            finally:
                try:
                    process.stdin.close()
                except OSError:
                    pass

        timer = threading.Timer(timeout, kill)
        sender = threading.Thread(target=send, daemon=True)
        timer.start()
        sender.start()
        try:
            yield from process.stdout
            code = process.wait()
            sender.join(timeout=3)
            if expired.is_set():
                raise ProcessError(
                    f"Process timed out after {timeout}s; inspect remote services before retrying"
                )
            if code:
                raise ProcessError(f"Remote operation failed (SSH exit {code}); see the journal")
            if write_errors:
                raise ProcessError("Could not deliver the entire remote script")
        finally:
            timer.cancel()
            if process.poll() is None:
                process.kill()
            process.wait()
            sender.join(timeout=3)
            process.stdout.close()
