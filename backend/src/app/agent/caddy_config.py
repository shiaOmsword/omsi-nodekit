"""Canonical generated Caddy configuration, shared by rendering and ownership checks."""

from .panel_access import panel_bind


def panel_route(node):
    access = node["caddy"].get("panel_access") or {}
    mode = access.get("mode", "disabled")
    if mode == "disabled":
        return ""
    path = node["panel"]["base_path"]
    paths = f"{path.rstrip('/')} {path}*" if path != "/" else "/*"
    lines = [
        f"    @admin_panel path {paths}",
        "    handle @admin_panel {",
        "        route {",
    ]
    if mode == "basic_auth":
        lines += [
            "            basic_auth {",
            f"                {access['username']} {access['password_hash']}",
            "            }",
        ]
    else:
        lines += [
            "            @panel_denied not remote_ip " + " ".join(access["allowed_ips"]),
            "            respond @panel_denied 403",
        ]
    lines += [f"            reverse_proxy {panel_bind(node)}:{node['panel']['port']} {{"]
    if mode == "basic_auth":
        lines.append("                header_up -Authorization")
    lines += ["            }", "        }", "    }"]
    return "\n".join(lines) + "\n"


def subscription_site(node):
    panel, caddy = node["panel"], node["caddy"]
    bind = (node.get("deployment") or {}).get("subscription_bind", "127.0.0.1")
    return f"""https://{caddy["domain"]}:{caddy["https_port"]} {{
    tls {{
        issuer acme {{
            disable_tlsalpn_challenge
        }}
    }}
    @subscriptions path {panel["subscription_path"]}*
    handle @subscriptions {{
        reverse_proxy {bind}:{panel["subscription_port"]}
    }}
{panel_route(node)}    handle {{
        respond 404
    }}
}}
"""


def standalone_config(node):
    # Preserve the original renderer's two final LFs. These bytes are also
    # used to verify ownership of installations created before Caddy attachment.
    return "{\n    admin off\n}\n\n" + subscription_site(node) + "\n"
