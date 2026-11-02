"""Canonical generated Caddy configuration, shared by rendering and ownership checks."""


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
    handle {{
        respond 404
    }}
}}
"""


def standalone_config(node):
    # Preserve the original renderer's two final LFs. These bytes are also
    # used to verify ownership of installations created before Caddy attachment.
    return "{\n    admin off\n}\n\n" + subscription_site(node) + "\n"
