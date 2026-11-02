"""Plan legacy shared-subId recovery through 3x-ui's unique client API.

Keep the old public subscription on its deterministic owner and append HTTPS
subscriptions for recovered group members. Never rewrite unrelated accounts.
"""

from framework.messages import MessageKey
from framework.messages import text as message_text

from .client_external_sync import (
    _canonical,
    _current_details,
    _merge,
    build_sync_plan,
    subscription_target,
)


def build_import_link_plans(context, api, catalog, selected, existing, pending, include_links):
    plans, count = (
        build_sync_plan(context, api, catalog, selected, existing, pending)
        if include_links
        else ([], 0)
    )
    affected = {
        c["_shared_subscription"]["sub_id"] for c in selected if "_shared_subscription" in c
    }
    if not affected:
        return plans, count
    root = subscription_target(context)
    accounts = {
        item["data"]["email"].lower(): item["data"]
        for source in catalog
        for item in source["clients"]
        if "_shared_subscription" in item["data"]
    }
    chosen = {c["email"].lower() for c in selected}
    creating = {c["email"].lower() for c in pending}
    target = {str(c.get("email", "")).lower(): c for c in existing}
    for sub_id in sorted(affected):
        members = [c for c in accounts.values() if c["_shared_subscription"]["sub_id"] == sub_id]
        owner_email = members[0]["_shared_subscription"]["owner"]
        owner = accounts[owner_email]
        if owner_email not in chosen:
            current = target.get(owner_email, {})
            if (
                str(current.get("uuid") or current.get("id") or "").lower() != owner["id"].lower()
                or current.get("subId") != sub_id
            ):
                raise RuntimeError(message_text(MessageKey.CLIENT_SHARED_DEPENDENCY))
        links = []
        for member in sorted(members, key=lambda c: c["email"].lower()):
            email = member["email"].lower()
            if email == owner_email:
                continue
            if email not in chosen:
                current = target.get(email)
                if current is None:
                    continue
                if (
                    str(current.get("uuid") or current.get("id") or "").lower()
                    != member["id"].lower()
                    or current.get("subId") != member["subId"]
                ):
                    raise RuntimeError(message_text(MessageKey.CLIENT_IMPORT_CONFLICT))
            links.append(
                {
                    "kind": "subscription",
                    "value": root + member["subId"],
                    "remark": "",
                    "enable": True,
                    "expiryTime": 0,
                    "namePrefix": "",
                }
            )
        plan = next((p for p in plans if p["email"].lower() == owner_email), None)
        is_new = owner_email in creating
        before = (
            plan["before"]
            if plan
            else ([] if is_new else _current_details(api, owner["email"], owner))
        )
        desired, added = _merge(plan["desired"] if plan else before, _canonical(links))
        count += added
        if plan:
            plan["desired"] = desired
            plan["added"] += added
        elif added:
            plans.append(
                {
                    "email": owner["email"],
                    "client": owner,
                    "new": is_new,
                    "before": before,
                    "desired": desired,
                    "added": added,
                }
            )

    # Generated owner -> child edges must not close a source/existing link cycle.
    edges = {
        p["client"]["subId"]: [
            link["value"][len(root) :]
            for link in p["desired"]
            if link["kind"] == "subscription" and link["value"].startswith(root)
        ]
        for p in plans
    }
    visiting, visited = set(), set()

    def visit(token):
        if token in visiting:
            raise RuntimeError(message_text(MessageKey.CLIENT_EXTERNAL_CYCLE))
        if token in visited:
            return
        visiting.add(token)
        for child in edges.get(token, []):
            visit(child)
        visiting.remove(token)
        visited.add(token)

    for token in edges:
        visit(token)
    return plans, count
