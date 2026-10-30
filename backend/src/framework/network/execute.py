"""Generic subprocess execution. No application models, storage, or job states."""

import subprocess
import threading
from collections.abc import Iterator

from framework.messages import MessageKey
from framework.messages import text as message_text


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
            raise ProcessError(
                message_text(MessageKey.COMMAND_TIMED_OUT, command=args[0], timeout=timeout)
            ) from exc
        except OSError as exc:
            raise ProcessError(
                message_text(MessageKey.EXECUTABLE_UNAVAILABLE, command=args[0])
            ) from exc

    def status(self, args: list[str], *, timeout: float) -> int:
        return self.completed(args, timeout=timeout).returncode

    def run(self, args: list[str], *, timeout: float, sensitive: bool = False) -> str:
        result = self.completed(args, timeout=timeout)
        if result.returncode:
            detail = (
                message_text(MessageKey.PROCESS_SENSITIVE_FAILED)
                if sensitive
                else result.stderr[-1500:]
            )
            raise ProcessError(
                message_text(
                    MessageKey.COMMAND_FAILED,
                    command=args[0],
                    status=result.returncode,
                    detail=detail,
                )
            )
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
            raise ProcessError(
                message_text(MessageKey.EXECUTABLE_UNAVAILABLE, command=args[0])
            ) from exc
        expired = threading.Event()
        # Keep the wire protocol independent of Windows CRLF translation (sudo -S).
        process.stdin.reconfigure(newline="\n")
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
                raise ProcessError(message_text(MessageKey.PROCESS_TIMED_OUT, timeout=timeout))
            if code:
                raise ProcessError(message_text(MessageKey.SSH_EXIT_FAILED, status=code))
            if write_errors:
                raise ProcessError(message_text(MessageKey.PROCESS_SCRIPT_INCOMPLETE))
        finally:
            timer.cancel()
            if process.poll() is None:
                process.kill()
            process.wait()
            sender.join(timeout=3)
            process.stdout.close()
