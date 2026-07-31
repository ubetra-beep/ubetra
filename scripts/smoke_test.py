import json
import urllib.error
import urllib.request


def req(method, path, data=None, token=None):
    body = None if data is None else json.dumps(data).encode()
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        "http://127.0.0.1:8000/api" + path,
        data=body,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        print(exc.read().decode())
        raise


print("health", req("GET", "/health"))
reg = req("POST", "/auth/register", {"username": "dom1", "email": "dom1@example.com", "password": "secret12"})
print("register ok", bool(reg.get("access_token")))
dyn = req(
    "POST",
    "/dynamics",
    {"name": "Test dynamic", "role": "dominant"},
    token=reg["access_token"],
)
print("dynamic", dyn["invite_code"], dyn["id"])
reg2 = req("POST", "/auth/register", {"username": "sub1", "email": "sub1@example.com", "password": "secret12"})
joined = req(
    "POST",
    "/dynamics/join",
    {"invite_code": dyn["invite_code"], "role": "submissive"},
    token=reg2["access_token"],
)
print("partners", len(joined["partners"]))
interests = req("GET", f"/dynamics/{dyn['id']}/interests", token=reg["access_token"])
print(
    "categories",
    len(interests["categories"]),
    "first cat interests",
    len(interests["categories"][0]["interests"]),
)
