# TCP congestion control: BBR and CUBIC

Nodekit exposes TCP congestion control on the Node > Network tab. Discover the VPS first, select BBR or CUBIC, preview the plan, and confirm. The remote agent verifies the fingerprint again before writing.

## Scope and persistence

This action changes the VPS-wide default algorithm for **new TCP sockets**, not only SSH sockets. It does **not** reconnect existing SSH tunnels, restart Xray or Caddy, change DNS, MTU, routes, or UFW. Use a separate maintenance window to reconnect any active tunnels.

Nodekit owns exactly two files: /etc/sysctl.d/99-zz-omsi-nodekit-tcp.conf and /etc/modules-load.d/omsi-nodekit-tcp.conf. Symlinks, directories, and foreign file content at these paths are rejected. Files elsewhere, including existing manual BBR config, are not modified.

BBR loads tcp_bbr if required, verifies kernel availability, records persistent settings, and applies sysctl. CUBIC persists the default and deletes only the Nodekit-owned module autoload file. On failure, the agent attempts to restore its own files and previous runtime default; it never overwrites concurrent operator edits.

## Manual BBR setups

If you already have files such as /etc/sysctl.d/90-omsi-bbr.conf or /etc/sysctl.d/99-omsi-bbr.conf, manually inspect them before applying this action. Nodekit does not remove or adopt them; a later-sorted Nodekit sysctl file may take precedence after reboot. Check the current runtime and persisted settings again after reboot.

BBR may considerably improve throughput on lossy networks, but does not remove packet loss. Compare TCP throughput, retransmissions and loaded latency before declaring the route healthy.

Diagnostics: sysctl net.ipv4.tcp_congestion_control; sysctl net.ipv4.tcp_available_congestion_control; ss -tinp.

This feature requires a privileged remote agent on Linux and works independently of panel runtime (native/Docker).

After applying BBR/CUBIC, use Node > SSH tunnels > Restart (one row) or Restart
all, review the selected names, then launch. This reconnects only already
installed, verified Nodekit SSH services so their new outgoing TCP sockets use
the current default. Traffic through them briefly disconnects. See
[SSH restart controls](ssh-egress.md#перезапуск-установленных-ssh-туннелей).
