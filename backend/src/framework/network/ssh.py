def ssh_command(node: Node):
    identity = Path(node.ssh.identity_file).expanduser().resolve()
    known_hosts = Path(node.ssh.known_hosts_file).expanduser().resolve()
    for path in (identity, known_hosts):
        if not path.is_file():
            raise ValueError(f"Local SSH file does not exist: {path}")
    return [
        "ssh",
        "-T",
        "-p",
        str(node.ssh.port),
        "-i",
        str(identity),
        "-o",
        "IdentitiesOnly=yes",
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=yes",
        "-o",
        f"UserKnownHostsFile={known_hosts}",
        "-o",
        "ConnectTimeout=10",
        "-o",
        "ServerAliveInterval=10",
        "-o",
        "ServerAliveCountMax=3",
        f"{node.ssh.user}@{node.ssh.host}",
        "sudo -n python3 -" if node.ssh.sudo else "python3 -",
    ]