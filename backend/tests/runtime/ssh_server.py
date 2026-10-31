"""Optional real SSH fixture for containers where sshd cannot call setgroups.

Paramiko is only needed when explicitly selecting --ssh-backend paramiko;
it is not an application dependency and never runs on a managed VPS.
"""

import base64
import logging
import select
import socket
import threading


class SSHFixture:
    def __init__(self, hostkey, public_key, port, target):
        import paramiko

        logging.getLogger("paramiko.transport").setLevel(logging.CRITICAL)
        self.paramiko = paramiko
        self.hostkey = paramiko.Ed25519Key.from_private_key_file(str(hostkey))
        self.allowed_key = paramiko.Ed25519Key(
            data=base64.b64decode(public_key.read_text().split()[1])
        )
        self.target = target
        self.transports = []
        self.closed = False
        self.listener = socket.socket()
        self.listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.listener.bind(("127.0.0.1", port))
        self.listener.listen()
        self.listener.settimeout(0.2)
        threading.Thread(target=self.accept, daemon=True).start()

    def accept(self):
        while not self.closed:
            try:
                connection, _ = self.listener.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(target=self.connection, args=(connection,), daemon=True).start()

    def connection(self, connection):
        paramiko, expected_key, target = self.paramiko, self.allowed_key, self.target

        class Server(paramiko.ServerInterface):
            def get_allowed_auths(self, username):
                return "publickey"

            def check_auth_publickey(self, username, key):
                return (
                    paramiko.AUTH_SUCCESSFUL
                    if username == "root" and key == expected_key
                    else paramiko.AUTH_FAILED
                )

            def check_channel_direct_tcpip_request(self, chanid, origin, destination):
                return (
                    paramiko.OPEN_SUCCEEDED
                    if destination == target
                    else paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED
                )

        transport = paramiko.Transport(connection)
        self.transports.append(transport)
        try:
            transport.add_server_key(self.hostkey)
            transport.start_server(server=Server())
            while transport.is_active() and not self.closed:
                channel = transport.accept(0.2)
                if channel:
                    threading.Thread(target=self.forward, args=(channel,), daemon=True).start()
        except (EOFError, OSError, paramiko.SSHException):
            pass
        finally:
            transport.close()

    def forward(self, channel):
        try:
            with socket.create_connection(self.target, timeout=5) as remote:
                readers = [channel, remote]
                while readers and not self.closed:
                    ready, _, _ = select.select(readers, [], [], 0.2)
                    for source in ready:
                        destination = remote if source is channel else channel
                        data = source.recv(65536)
                        if data:
                            destination.sendall(data)
                        else:
                            readers.remove(source)
                            if destination is channel:
                                channel.shutdown_write()
                            else:
                                remote.shutdown(socket.SHUT_WR)
        except OSError:
            pass
        finally:
            channel.close()

    def close(self):
        self.closed = True
        self.listener.close()
        for transport in self.transports:
            transport.close()
