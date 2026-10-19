"""Harness: drives the FastAPI auth routes against a scratch database.

Writes the same JSON shape as express_auth.js so one comparator can diff them.
Env: PARITY_MONGO, PARITY_OUT_DIR.
"""

import base64
import json

import harness_env
from harness_env import scratch_database, write_result

DB_NAME = "tradium_parity_fastapi_auth"


def parse_set_cookie(line):
    parts = [part.strip() for part in line.split(";")]
    pair, *attrs = parts
    name, _, value = pair.partition("=")
    attributes = {}
    for attr in attrs:
        if "=" in attr:
            key, _, val = attr.partition("=")
            attributes[key.lower()] = val
        else:
            attributes[attr.lower()] = True
    return {"name": name, "valueLength": len(value), "attributes": attributes}


def decode_jwt(token):
    try:
        header, payload, _ = token.split(".")

        def decode(part):
            padded = part + "=" * (-len(part) % 4)
            return json.loads(base64.urlsafe_b64decode(padded).decode())

        return {"header": decode(header), "payload": decode(payload)}
    except Exception:
        return None


def token_value(line):
    name, _, value = line.split(";")[0].partition("=")
    return value if name.strip() == "token" else None


def main():
    from fastapi.testclient import TestClient

    from api.main import create_app

    client_mongo, database = scratch_database(DB_NAME)
    jar = {}
    sequence = []

    with TestClient(create_app(database=database), raise_server_exceptions=False) as client:

        def call(name, method, endpoint, body=None, extra_cookie=None):
            cookies = dict(jar) if extra_cookie is None else extra_cookie
            cookie_header = "; ".join(f"{key}={value}" for key, value in cookies.items())
            headers = {"cookie": cookie_header} if cookie_header else {}
            client.cookies.clear()
            response = client.request(method, endpoint, json=body, headers=headers)
            raw_cookies = response.headers.get_list("set-cookie")
            tokens = []
            for line in raw_cookies:
                cookie_name, _, cookie_value = line.split(";")[0].partition("=")
                jar[cookie_name.strip()] = cookie_value.strip()
                token = token_value(line)
                if token is not None:
                    tokens.append(token)
            entry = {
                "name": name,
                "method": method,
                "path": endpoint,
                "status": response.status_code,
                "contentType": response.headers.get("content-type"),
                "bodyText": response.text,
                "setCookies": [parse_set_cookie(line) for line in raw_cookies],
                "tokenCookies": tokens,
            }
            if tokens:
                entry["jwt"] = decode_jwt(tokens[0])
            sequence.append(entry)
            return entry

        call(
            "signup",
            "POST",
            "/api/auth/signup",
            {"username": "parityuser", "email": "parity@example.com", "password": "password123"},
        )
        call("meAuthed", "GET", "/api/auth/me")
        call(
            "login",
            "POST",
            "/api/auth/login",
            {"email": "parity@example.com", "password": "password123"},
        )
        call("logout", "POST", "/api/auth/logout")
        call("meAfterLogout", "GET", "/api/auth/me")
        call("meAnonymous", "GET", "/api/auth/me", extra_cookie={})
        call(
            "badLogin",
            "POST",
            "/api/auth/login",
            {"email": "parity@example.com", "password": "wrong-password"},
        )

    client_mongo.drop_database(DB_NAME)
    write_result(
        "fastapi_auth.json",
        {"implementation": "fastapi", "dbName": DB_NAME, "sequence": sequence},
    )


if __name__ == "__main__":
    main()
