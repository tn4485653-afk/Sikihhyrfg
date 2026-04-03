from flask import Flask, request, Response
import json
import threading
import requests
from google.protobuf.json_format import MessageToJson
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
import binascii
from collections import OrderedDict
import time
import danger_count_pb2
import danger_generator_pb2
from byte import Encrypt_ID, encrypt_api

app = Flask(__name__)

# -----------------------------
# CONFIG
# -----------------------------
REGION_CONFIG = {
    'ind': {'domain': 'client.ind.freefiremobile.com', 'token_file': 'tokens_ind.json'},
    'vn': {'domain': 'clientbp.ggpolarbear.com', 'token_file': 'tokens_vn.json'},
    'me': {'domain': 'clientbp.ggpolarbear.com', 'token_file': 'tokens_me.json'},
    'pk': {'domain': 'clientbp.ggpolarbear.com', 'token_file': 'tokens_pk.json'}
}

TOKEN_API_URL = "http://jwt.thug4ff.xyz/token"

ACCOUNT_FILES = {
    "IND": "accounts-IND.json",
    "VN": "accounts-VN.json",
    "ME": "accounts-ME.json",
    "PK": "accounts-PK.json"
}

# chống spam refresh
last_refresh = {}

# -----------------------------
# TOKEN UTILS
# -----------------------------
def load_tokens(region):
    try:
        with open(REGION_CONFIG[region]['token_file'], "r") as f:
            return json.load(f)
    except:
        return []

def save_tokens(region, tokens):
    with open(REGION_CONFIG[region]['token_file'], "w") as f:
        json.dump(tokens, f, indent=4)

def load_accounts(region):
    try:
        with open(ACCOUNT_FILES[region.upper()], "r") as f:
            return json.load(f)
    except:
        return []

def fetch_token(acc):
    try:
        url = f"{TOKEN_API_URL}?uid={acc['uid']}&password={acc['password']}"
        res = requests.get(url, timeout=6)
        data = res.json()
        token = data.get("token")
        if token and token != "N/A":
            return token
    except:
        pass
    return None

def should_refresh(region):
    now = time.time()
    if region not in last_refresh or now - last_refresh[region] > 300:
        last_refresh[region] = now
        return True
    return False

def refresh_region_tokens(region):
    print(f"[REFRESH] {region.upper()}")

    accounts = load_accounts(region)
    if not accounts:
        print("No accounts")
        return

    old_tokens = load_tokens(region)
    new_tokens = []

    for acc in accounts:
        token = fetch_token(acc)
        if token:
            new_tokens.append({"token": token})
        time.sleep(5)

    if new_tokens:
        combined = old_tokens + new_tokens
        unique = [dict(t) for t in {tuple(d.items()) for d in combined}]
        save_tokens(region, unique)
        print(f"[DONE] {len(unique)} tokens")

# -----------------------------
# AUTO REFRESH 5H
# -----------------------------
def token_refresh_loop():
    print("[AUTO REFRESH STARTED - 5H]")
    while True:
        for region in ACCOUNT_FILES.keys():
            refresh_region_tokens(region)

        print("Sleeping 5 hours...")
        time.sleep(5 * 60 * 60)

# -----------------------------
# ENCRYPT
# -----------------------------
def encrypt_message(data):
    key = b'Yg&tc%DEuh6%Zc^8'
    iv = b'6oyZDr22E3ychjM%'
    cipher = AES.new(key, AES.MODE_CBC, iv)
    return binascii.hexlify(cipher.encrypt(pad(data, AES.block_size))).decode()

def create_uid(uid):
    msg = danger_generator_pb2.danger_generator()
    msg.saturn_ = int(uid)
    msg.garena = 1
    return msg.SerializeToString()

def enc(uid):
    return encrypt_message(create_uid(uid))

def decode_info(binary):
    msg = danger_count_pb2.Danger_ff_like()
    msg.ParseFromString(binary)
    return msg

# -----------------------------
# PLAYER INFO
# -----------------------------
def get_player_info(uid, region):
    tokens = load_tokens(region)
    if not tokens:
        return None, None

    token = tokens[0]['token']
    url = f"https://{REGION_CONFIG[region]['domain']}/GetPlayerPersonalShow"

    try:
        res = requests.post(url, data=bytes.fromhex(enc(uid)),
                            headers={"Authorization": f"Bearer {token}"},
                            verify=False, timeout=10)

        if res.status_code == 401 and should_refresh(region):
            refresh_region_tokens(region)
            return None, None

        data = json.loads(MessageToJson(decode_info(res.content)))
        acc = data.get("AccountInfo", {})

        return acc.get("PlayerNickname", "Unknown"), acc.get("UID", uid)
    except:
        return None, None

# -----------------------------
# SEND REQUEST
# -----------------------------
def send_request(uid, token, domain, region, results, lock):
    try:
        payload = f"08a7c4839f1e10{Encrypt_ID(uid)}1801"
        enc_payload = encrypt_api(payload)

        res = requests.post(
            f"https://{domain}/RequestAddingFriend",
            data=bytes.fromhex(enc_payload),
            headers={"Authorization": f"Bearer {token}"},
            timeout=10
        )

        with lock:
            if res.status_code == 200:
                results["success"] += 1
            elif res.status_code == 401:
                results["failed"] += 1
                if should_refresh(region):
                    print("401 → refresh")
                    refresh_region_tokens(region)
            else:
                results["failed"] += 1

        time.sleep(3)

    except:
        with lock:
            results["failed"] += 1

# -----------------------------
# API
# -----------------------------
@app.route("/send_requests")
def send_requests():
    uid = request.args.get("uid")
    region = request.args.get("region", "vn").lower()

    if not uid:
        return {"error": "uid required"}

    tokens = load_tokens(region)
    if not tokens:
        return {"error": "no tokens"}

    name, player_uid = get_player_info(uid, region)
    if not name:
        return {"error": "player not found"}

    results = {"success": 0, "failed": 0}
    lock = threading.Lock()
    domain = REGION_CONFIG[region]['domain']

    for tk in tokens[:50]:
        send_request(uid, tk['token'], domain, region, results, lock)

    return OrderedDict([
        ("PlayerName", name),
        ("UID", player_uid),
        ("Success", results["success"]),
        ("Failed", results["failed"])
    ])

@app.route("/regions")
def regions():
    return {"regions": list(REGION_CONFIG.keys())}

# -----------------------------
# MAIN
# -----------------------------
if __name__ == "__main__":
    t = threading.Thread(target=token_refresh_loop, daemon=True)
    t.start()

    print("Server running...")
    app.run(host="0.0.0.0", port=5000)