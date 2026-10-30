def execute(store: Store, job_id: str, node: Node, action: str, backup_id: str | None):
    store.start(job_id)
    received_backup = None
    try:
        backup = store.backup_path(backup_id).read_bytes() if backup_id else None
        script = agent_source(node, action, backup)
        command = ssh_command(node)
        store.event(job_id, f"Connecting to {node.ssh.user}@{node.ssh.host}:{node.ssh.port}")
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        timed_out = threading.Event()

        def timeout():
            timed_out.set()
            process.kill()

        timer = threading.Timer(1200, timeout)
        timer.start()

        def send():
            try:
                process.stdin.write(script)
                process.stdin.close()
            except (BrokenPipeError, OSError):
                pass

        sender = threading.Thread(target=send, daemon=True)
        sender.start()
        try:
            for line in process.stdout:
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    store.event(job_id, line.strip(), "warning")
                    continue
                if "backup" in event:
                    if action != "backup" or received_backup is not None:
                        raise RuntimeError("Unexpected backup payload")
                    raw = base64.b64decode(event["backup"], validate=True)
                    validate_backup(raw)
                    received_backup = store.add_backup(raw, f"{node.id}-x-ui.db")["id"]
                    store.save_manifest(received_backup, node)
                else:
                    store.event(job_id, str(event.get("message", "")), event.get("level", "info"))
            returncode = process.wait()
            sender.join(timeout=3)
            if timed_out.is_set():
                raise RuntimeError(
                    "SSH timed out after 20 minutes; inspect remote services before retrying"
                )
            if returncode:
                raise RuntimeError(
                    f"Remote operation failed (SSH exit {returncode}); see the journal"
                )
            if action == "backup" and not received_backup:
                raise RuntimeError("Remote operation returned no backup")
        finally:
            timer.cancel()
            if process.poll() is None:
                process.kill()
                process.wait()
        store.finish(job_id, "succeeded", backup_id=received_backup)
    except Exception as exc:
        store.event(job_id, str(exc), "error")
        store.finish(job_id, "failed", str(exc), backup_id=received_backup)
