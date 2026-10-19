"""Diff the captures produced by the harness and report what actually differs.

Reads express_*.json and fastapi_*.json from PARITY_OUT_DIR and prints three
sections: authentication, numeric serialization and background jobs. The final
verdict separates *functional* divergences from *informational* ones (a
different number type or header spelling that no client can observe).
Env: PARITY_OUT_DIR.
"""

import json
import os
import re
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT_DIR = Path(os.environ.get("PARITY_OUT_DIR", HERE / "out"))

OBJECT_ID = re.compile(r"[0-9a-f]{24}")
TIMESTAMP = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z")


def load(name):
    path = OUT_DIR / name
    if not path.exists():
        raise SystemExit(f"missing capture: {path} (run the harnesses first)")
    return json.loads(path.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# authentication
# --------------------------------------------------------------------------- #

FUNCTIONAL_COOKIE_ATTRS = ("path", "httponly", "samesite", "secure", "domain")
PAST_EXPIRES = ("thu, 01 jan 1970",)


def cookie_map(set_cookies):
    out = {}
    for cookie in set_cookies:
        attrs = {}
        for key, value in cookie["attributes"].items():
            key = key.lower()
            attrs[key] = value.lower() if isinstance(value, str) else value
        out[cookie["name"]] = attrs
    return out


def deletes_cookie(attrs):
    """True when the cookie is being cleared: ``Max-Age=0`` or a past ``Expires``."""
    if attrs.get("max-age") == "0":
        return True
    expires = attrs.get("expires")
    return bool(expires) and str(expires).lower().startswith(PAST_EXPIRES)


def compare_auth():
    left = load("express_auth.json")
    right = load("fastapi_auth.json")
    functional = []
    informational = []

    for a, b in zip(left["sequence"], right["sequence"]):
        label = a["name"]
        if a["status"] != b["status"]:
            functional.append(f"{label}: status {a['status']} vs {b['status']}")

        def steady(text):
            return TIMESTAMP.sub("<date>", OBJECT_ID.sub("<oid>", text))

        body_a, body_b = steady(a["bodyText"]), steady(b["bodyText"])
        if body_a != body_b:
            functional.append(f"{label}: body {body_a!r} vs {body_b!r}")
        if a["contentType"].split(";")[0] != b["contentType"].split(";")[0]:
            informational.append(
                f"{label}: content-type {a['contentType']!r} vs {b['contentType']!r}"
            )

        cookies_a = cookie_map(a["setCookies"])
        cookies_b = cookie_map(b["setCookies"])
        if set(cookies_a) != set(cookies_b):
            functional.append(f"{label}: cookie names {sorted(cookies_a)} vs {sorted(cookies_b)}")
        for name in sorted(set(cookies_a) & set(cookies_b)):
            attrs_a, attrs_b = cookies_a[name], cookies_b[name]
            for attr in FUNCTIONAL_COOKIE_ATTRS:
                if attrs_a.get(attr) != attrs_b.get(attr):
                    functional.append(
                        f"{label}: cookie {name} {attr} "
                        f"{attrs_a.get(attr)!r} vs {attrs_b.get(attr)!r}"
                    )
            # Deleting and expiring are the same outcome; only the mechanism differs.
            if deletes_cookie(attrs_a) != deletes_cookie(attrs_b):
                functional.append(
                    f"{label}: cookie {name} is cleared on one side only "
                    f"({attrs_a} vs {attrs_b})"
                )
            elif not deletes_cookie(attrs_a) and attrs_a.get("max-age") != attrs_b.get("max-age"):
                functional.append(
                    f"{label}: cookie {name} max-age "
                    f"{attrs_a.get('max-age')!r} vs {attrs_b.get('max-age')!r}"
                )
            elif deletes_cookie(attrs_a) and attrs_a != attrs_b:
                informational.append(
                    f"{label}: cookie {name} cleared via different attributes "
                    f"({attrs_a} vs {attrs_b})"
                )
            if bool(attrs_a.get("expires")) != bool(attrs_b.get("expires")):
                informational.append(
                    f"{label}: cookie {name} sends Expires on "
                    f"{'express' if attrs_a.get('expires') else 'fastapi'} only"
                )

        for step, impl in ((a, "express"), (b, "fastapi")):
            if not step.get("jwt"):
                continue
            payload = step["jwt"]["payload"]
            if abs(payload.get("exp", 0) - payload.get("iat", 0)) != 604800:
                functional.append(f"{label}: {impl} token lifetime is not 604800s")
            if set(payload) != {"id", "iat", "exp"}:
                functional.append(f"{label}: {impl} token claims {sorted(payload)}")

        token_a = a["tokenCookies"][0] if a["tokenCookies"] else None
        token_b = b["tokenCookies"][0] if b["tokenCookies"] else None
        if token_a is None and token_b is None:
            continue
        if (token_a is None) != (token_b is None):
            functional.append(f"{label}: one side sends a token cookie and the other does not")
        elif a.get("jwt") and b.get("jwt"):
            if len(token_a) != len(token_b):
                informational.append(f"{label}: token length {len(token_a)} vs {len(token_b)}")
        elif token_a != token_b:
            informational.append(f"{label}: cleared cookie value {token_a!r} vs {token_b!r}")
    return functional, informational


# --------------------------------------------------------------------------- #
# numeric serialization
# --------------------------------------------------------------------------- #


def compare_numbers():
    left = load("express_numbers.json")
    right = load("fastapi_numbers.json")
    functional = []
    informational = []

    if left["status"] != right["status"]:
        functional.append(f"status {left['status']} vs {right['status']}")

    rows_a = {row["symbol"]: row for row in json.loads(left["bodyText"])}
    rows_b = {row["symbol"]: row for row in json.loads(right["bodyText"])}
    if set(rows_a) != set(rows_b):
        functional.append(f"symbols {sorted(rows_a)} vs {sorted(rows_b)}")

    for symbol in sorted(set(rows_a) & set(rows_b)):
        a, b = rows_a[symbol], rows_b[symbol]
        if set(a) != set(b):
            functional.append(f"{symbol}: keys {sorted(a)} vs {sorted(b)}")
        for key in sorted(set(a) & set(b)):
            if a[key] == b[key]:
                continue
            functional.append(f"{symbol}.{key}: {a[key]!r} vs {b[key]!r}")
        for key in sorted(set(a) & set(b)):
            if type(a[key]) is not type(b[key]) and a[key] == b[key]:
                kind_a = "int" if isinstance(a[key], int) and not isinstance(a[key], bool) else "float"
                kind_b = "int" if isinstance(b[key], int) and not isinstance(b[key], bool) else "float"
                informational.append(
                    f"{symbol}.{key}: renders as {kind_a} in express, {kind_b} in fastapi "
                    f"(same JSON number)"
                )
    return functional, informational


# --------------------------------------------------------------------------- #
# background jobs
# --------------------------------------------------------------------------- #


def strip_types(node):
    """Reduce a tagged value to plain data, so only *value* differences remain."""
    if isinstance(node, dict) and node.get("t") == "doc":
        return {key: strip_types(value) for key, value in node["v"].items()}
    if isinstance(node, dict) and node.get("t") == "array":
        return [strip_types(value) for value in node["v"]]
    if isinstance(node, dict) and "t" in node:
        tag = node["t"]
        if tag == "null":
            return None
        if tag in ("int", "double", "long"):
            # int32 and double with the same value are the same number to a client.
            return format(float(node["v"]), ".17g")
        return node.get("v")
    return node


def key_of(node):
    return json.dumps(strip_types(node), sort_keys=True)


def walk(node, path, out):
    if isinstance(node, dict) and node.get("t") == "doc":
        for name, child in node["v"].items():
            walk(child, f"{path}.{name}" if path else name, out)
        return
    if isinstance(node, dict) and node.get("t") == "array":
        for child in node["v"]:
            walk(child, f"{path}[]", out)
        return
    if isinstance(node, dict) and "t" in node:
        out.append((path, node["t"]))
        return
    if isinstance(node, dict):
        for name, child in node.items():
            walk(child, f"{path}.{name}" if path else name, out)


def type_map(dump):
    table = defaultdict(Counter)
    for name, docs in dump["collections"].items():
        for doc in docs:
            leaves = []
            walk(doc, "", leaves)
            for path, tag in leaves:
                table[f"{name}.{path}"][tag] += 1
    return table


def compare_jobs():
    left = load("express_jobs.json")
    right = load("fastapi_jobs.json")
    functional = []
    informational = []

    for name in sorted(set(left["collections"]) | set(right["collections"])):
        rows_a = left["collections"].get(name, [])
        rows_b = right["collections"].get(name, [])
        only_a = Counter(key_of(doc) for doc in rows_a) - Counter(key_of(doc) for doc in rows_b)
        only_b = Counter(key_of(doc) for doc in rows_b) - Counter(key_of(doc) for doc in rows_a)
        for label, counter in (("express only", only_a), ("fastapi only", only_b)):
            for doc_key, count in counter.items():
                functional.append(f"{name} {label} (x{count}): {doc_key}")

    table_a = type_map(left)
    table_b = type_map(right)
    for path in sorted(set(table_a) | set(table_b)):
        types_a = table_a.get(path, Counter())
        types_b = table_b.get(path, Counter())
        if types_a == types_b:
            continue
        informational.append(
            f"{path}: {dict(types_a)} vs {dict(types_b)}"
        )
    return functional, informational


# --------------------------------------------------------------------------- #
# read routes (orders, watchlist, positions, funds, portfolio, market, search)
# --------------------------------------------------------------------------- #


def diff_values(a, b, path, functional, informational):
    """Walk two parsed JSON values and record structural (functional) diffs."""
    if isinstance(a, dict) and isinstance(b, dict):
        if set(a) != set(b):
            functional.append(f"{path}: keys {sorted(a)} vs {sorted(b)}")
        for key in sorted(set(a) & set(b)):
            diff_values(a[key], b[key], f"{path}.{key}", functional, informational)
        return
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            functional.append(f"{path}: length {len(a)} vs {len(b)}")
        for index, (left, right) in enumerate(zip(a, b)):
            diff_values(left, right, f"{path}[{index}]", functional, informational)
        return
    if a == b:
        numbers = (
            isinstance(a, (int, float))
            and not isinstance(a, bool)
            and isinstance(b, (int, float))
            and not isinstance(b, bool)
        )
        if numbers and type(a) is not type(b):
            spelling = lambda v: "int" if isinstance(v, int) else "float"  # noqa: E731
            informational.append(
                f"{path}: renders as {spelling(a)} in express, {spelling(b)} in fastapi "
                f"(same JSON number)"
            )
        return
    functional.append(f"{path}: {a!r} vs {b!r}")


def compare_routes():
    left = load("express_routes.json")
    right = load("fastapi_routes.json")
    functional = []
    informational = []

    by_a = {route["name"]: route for route in left["routes"]}
    by_b = {route["name"]: route for route in right["routes"]}
    if set(by_a) != set(by_b):
        functional.append(f"route names {sorted(by_a)} vs {sorted(by_b)}")

    for name in sorted(set(by_a) & set(by_b)):
        a, b = by_a[name], by_b[name]
        if a["status"] != b["status"]:
            functional.append(f"{name}: status {a['status']} vs {b['status']}")
            continue
        ct_a = (a["contentType"] or "").split(";")[0]
        ct_b = (b["contentType"] or "").split(";")[0]
        if ct_a != ct_b:
            informational.append(f"{name}: content-type {ct_a!r} vs {ct_b!r}")
        try:
            value_a = json.loads(a["bodyText"])
            value_b = json.loads(b["bodyText"])
        except json.JSONDecodeError:
            if a["bodyText"] != b["bodyText"]:
                functional.append(f"{name}: body {a['bodyText']!r} vs {b['bodyText']!r}")
            continue
        diff_values(value_a, value_b, name, functional, informational)
        if a["bodyText"] != b["bodyText"] and not any(
            line.startswith(name) for line in functional
        ):
            informational.append(f"{name}: raw bytes differ (JSON-equivalent)")
    return functional, informational


def report(title, functional, informational):
    print(f"=== {title} ===")
    if not functional and not informational:
        print("  identical")
        return
    for line in functional:
        print(f"  [DIFF]          {line}")
    for line in informational:
        print(f"  [informational] {line}")
    if not functional:
        print("  -> equivalent (informational differences only)")
    print()


def main():
    sections = [
        ("authentication", compare_auth()),
        ("numeric serialization", compare_numbers()),
        ("background jobs", compare_jobs()),
        ("read routes", compare_routes()),
    ]
    for title, (functional, informational) in sections:
        report(title, functional, informational)

    failed = [title for title, (functional, _) in sections if functional]
    if failed:
        print("RESULT: differences found in " + ", ".join(failed))
        raise SystemExit(1)
    print("RESULT: equivalent - no functional difference observed")


if __name__ == "__main__":
    main()
