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
# REGION CONFIGURATION
# -----------------------------
REGION_CONFIG = {
    'ind': {'domain': 'client.ind.freefiremobile.com', 'token_file': 'tokens_ind.json'},
    'vn': {'domain': 'clientbp.ggpolarbear.com', 'token_file': 'tokens_vn.json'},
    'me': {'domain': 'clientbp.ggpolarbear.com', 'token_file': 'tokens_me.json'},
    'pk': {'domain': 'clientbp.ggpolarbear.com', 'token_file': 'tokens_pk.json'}
}

# -----------------------------
# TOKEN AUTO REFRESH CONFIG
# -----------------------------
TOKEN_API_URL = "http://jwt.thug4ff.xyz/token"
ACCOUNT_FILES = {
    "IND": "accounts-IND.json",
    "VN": "accounts-VN.json",
    "ME": "accounts-ME.json",
    "PK": "accounts-PK.json"
}
TOKEN_OUTPUT_FILES = {
    "IND": "tokens_ind.json",
    "VN": "tokens_vn.json",
    "ME": "tokens_me.json",
    "PK": "tokens_pk.json"
}
token_rotation = {}

# -----------------------------
# UTILITY FUNCTIONS
# -----------------------------
def load_tokens(region):
    try:
        config = REGION_CONFIG.get(region)
        if not config:
            return None
        with open(config['token_file'], "r") as f:
            return json.load(f)
    except:
        return None

def encrypt_message(plaintext_bytes):
    key = b'Yg&tc%DEuh6%Zc^8'
    iv = b'6oyZDr22E3ychjM%'
    cipher = AES.new(key, AES.MODE_CBC, iv)
    padded = pad(plaintext_bytes, AES.block_size)
    encrypted = cipher.encrypt(padded)
    return binascii.hexlify(encrypted).decode('utf-8')

def create_uid_protobuf(uid):
    msg = danger_generator_pb2.danger_generator()
    msg.saturn_ = int(uid)
    msg.garena = 1
    return msg.SerializeToString()

def enc(uid):
    pb = create_uid_protobuf(uid)
    return encrypt_message(pb)

def decode_player_info(binary):
    info = danger_count_pb2.Danger_ff_like()
    info.ParseFromString(binary)
    return info

def get_player_info(uid, region):
    tokens = load_tokens(region)
    if tokens is None or len(tokens) == 0:
        return None, None, region
    token = tokens[0]['token']
    config = REGION_CONFIG.get(region)
    url = f"https://{config['domain']}/GetPlayerPersonalShow"

    encrypted_uid = enc(uid)
    edata = bytes.fromhex(encrypted_uid)

    headers = {
        'User-Agent': "Dalvik/2.1.0",
        'Connection': "Keep-Alive",
        'Accept-Encoding': "gzip",
        'Authorization': f"Bearer {token}",
        'Content-Type': "application/x-www-form-urlencoded",
        'X-Unity-Version': "2018.4.11f1",
        'X-GA': "v1 1",
        'ReleaseVersion': "OB52"
    }

    try:
        response = requests.post(url, data=edata, headers=headers, verify=False, timeout=10)
        if response.status_code != 200:
            return None, None, region
        info = decode_player_info(response.content)
        data = json.loads(MessageToJson(info))
        account = data.get("AccountInfo", {})
        player_name = account.get("PlayerNickname", "Unknown")
        player_uid = account.get("UID", uid)
        return player_name, player_uid, region
    except:
        return None, None, region

def send_friend_request(uid, token, domain, results, lock):
    try:
        encrypted_id = Encrypt_ID(uid)
        payload = f"08a7c4839f1e10{encrypted_id}1801"
        encrypted_payload = encrypt_api(payload)
        url = f"https://{domain}/RequestAddingFriend"
        headers = {
            "Authorization": f"Bearer {token}",
            "X-Unity-Version": "2018.4.11f1",
            "X-GA": "v1 1",
            "ReleaseVersion": "OB52",
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "Dalvik/2.1.0"
        }
        response = requests.post(url, data=bytes.fromhex(encrypted_payload), headers=headers, timeout=10)
        with lock:
            if response.status_code == 200:
                results['success'] += 1
            else:
                results['failed'] += 1
        time.sleep(10)
    except:
        with lock:
            results['failed'] += 1

# -----------------------------
# FLASK ENDPOINTS
# -----------------------------
@app.route("/send_requests", methods=["GET"])
def handle_friend_request():
    uid = request.args.get("uid")
    region = request.args.get("region", "ind").lower()
    if not uid:
        return Response(json.dumps({"error": "uid required"}), mimetype="application/json")
    if region not in REGION_CONFIG:
        return Response(json.dumps({"error": f"Invalid region. Supported: {', '.join(REGION_CONFIG.keys())}"}), mimetype="application/json")

    tokens = load_tokens(region)
    if not tokens:
        return Response(json.dumps({"error": f"No tokens for region {region}"}), mimetype="application/json")

    player_name, player_uid, region = get_player_info(uid, region)
    if not player_name:
        return Response(json.dumps({"error": "Player not found"}), mimetype="application/json")

    config = REGION_CONFIG.get(region)
    domain = config['domain']

    results = {"success": 0, "failed": 0}
    lock = threading.Lock()

    for i in range(min(len(tokens), 100)):
        token = tokens[i]['token']
        send_friend_request(uid, token, domain, results, lock)

    output = OrderedDict([
        ("PlayerName", player_name),
        ("UID", player_uid),
        ("Region", region.upper()),
        ("Success", results["success"]),
        ("Failed", results["failed"]),
        ("Status", 1 if results["success"] > 0 else 2)
    ])
    return Response(json.dumps(output), mimetype="application/json")

@app.route("/regions", methods=["GET"])
def list_regions():
    regions = [{"code": code, "domain": config['domain'], "token_file": config['token_file']} for code, config in REGION_CONFIG.items()]
    return Response(json.dumps({"regions": regions}), mimetype="application/json")

# -----------------------------
# TOKEN REFRESH LOGIC
# -----------------------------
def load_accounts(file_path):
    try:
        with open(file_path, "r") as f:
            return json.load(f)
    except:
        return []

def fetch_token(account):
    uid = account.get("uid")
    password = account.get("password")
    if not uid or not password:
        return None
    try:
        url = f"{TOKEN_API_URL}?uid={uid}&password={password}"
        resp = requests.get(url, timeout=6)
        resp.raise_for_status()
        data = resp.json()
        token = data.get("token")
        if token and token != "N/A":
            return token
        return None
    except:
        return None

def refresh_region_tokens(region):
    print(f"[Refresh] {region} started")
    accounts = load_accounts(ACCOUNT_FILES.get(region))
    output_file = TOKEN_OUTPUT_FILES.get(region)
    if not accounts:
        print(f"[Refresh] No accounts for {region}")
        return
    new_tokens = []
    for account in accounts:
        token = fetch_token(account)
        if token:
            new_tokens.append({"token": token})
        time.sleep(10)
    if new_tokens:
        with open(output_file, "w") as f:
            json.dump(new_tokens, f, indent=4)
        token_rotation[region] = new_tokens
        print(f"[Refresh] {region} updated. Total tokens: {len(new_tokens)}")
    else:
        print(f"[Refresh] No valid tokens for {region}")

def token_refresh_loop():
    print("[Refresh] Token refresh loop started (10s per token)")
    while True:
        for region in ACCOUNT_FILES.keys():
            refresh_region_tokens(region)

# -----------------------------
# MAIN
# -----------------------------
if __name__ == "__main__":
    t = threading.Thread(target=token_refresh_loop, daemon=True)
    t.start()
    app.run(debug=True, host="0.0.0.0", port=5000)