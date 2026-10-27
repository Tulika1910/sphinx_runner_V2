"""
Players, scores and the Firebase leaderboard.  Standard library only.

 * Everything is saved on this computer first (data/players.json) - the game never waits for the network.
 * If firebase_config.json exists, players who agreed to it are also uploaded to Firebase (Firestore) in a
   background thread.  Uploads that fail (offline, wrong rules...) are kept and retried later.
 * See FIREBASE_SETUP.md for the 10-minute Firebase setup.
"""
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")


def valid_email(s: str) -> bool:
    return bool(EMAIL_RE.match(s.strip()))


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


# =============================================================================
# Firebase over plain HTTPS (no SDK needed)
# =============================================================================
class FirebaseError(Exception):
    def __init__(self, status, message):
        super().__init__(f"{status}: {message}")
        self.status = status
        self.message = message


class FirebaseClient:
    """Anonymous sign-in + Firestore REST.  Each install gets its own anonymous user; the security
    rules in FIREBASE_SETUP.md let that user write only its own players and add scores."""

    def __init__(self, cfg: dict, state_path: Path):
        self.key = cfg["apiKey"]
        self.project = cfg["projectId"]
        self.identity = cfg.get("identityUrl", "https://identitytoolkit.googleapis.com").rstrip("/")
        self.token_url = cfg.get("tokenUrl", "https://securetoken.googleapis.com").rstrip("/")
        self.firestore = cfg.get("firestoreUrl", "https://firestore.googleapis.com").rstrip("/")
        self.state_path = state_path
        self.state = _read_json(state_path, {})

    # ---- http -----------------------------------------------------------
    def _http(self, url, method="GET", body=None, token=None, form=False):
        data, headers = None, {}
        if body is not None:
            if form:
                data = urllib.parse.urlencode(body).encode()
                headers["Content-Type"] = "application/x-www-form-urlencoded"
            else:
                data = json.dumps(body).encode()
                headers["Content-Type"] = "application/json"
        if token:
            headers["Authorization"] = f"Bearer {token}"
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                raw = r.read().decode() or "{}"
                return json.loads(raw)
        except urllib.error.HTTPError as e:
            try:
                msg = json.loads(e.read().decode()).get("error", {}).get("message", e.reason)
            except Exception:
                msg = e.reason
            raise FirebaseError(e.code, str(msg))

    # ---- auth -----------------------------------------------------------
    def _save_auth(self, uid, id_token, refresh_token, expires_in):
        self.state = {"uid": uid, "idToken": id_token, "refreshToken": refresh_token,
                      "expiresAt": time.time() + int(expires_in) - 60}
        _write_json(self.state_path, self.state)

    def auth(self):
        """Returns (uid, idToken), signing in or refreshing when needed."""
        s = self.state
        if s.get("idToken") and s.get("expiresAt", 0) > time.time():
            return s["uid"], s["idToken"]
        if s.get("refreshToken"):
            try:
                r = self._http(f"{self.token_url}/v1/token?key={self.key}", "POST",
                               {"grant_type": "refresh_token", "refresh_token": s["refreshToken"]}, form=True)
                self._save_auth(r["user_id"], r["id_token"], r["refresh_token"], r.get("expires_in", 3600))
                return self.state["uid"], self.state["idToken"]
            except FirebaseError:
                pass                                              # fall through: sign in again
        r = self._http(f"{self.identity}/v1/accounts:signUp?key={self.key}", "POST", {"returnSecureToken": True})
        self._save_auth(r["localId"], r["idToken"], r["refreshToken"], r.get("expiresIn", 3600))
        return self.state["uid"], self.state["idToken"]

    # ---- firestore ------------------------------------------------------
    @property
    def docs(self):
        return f"{self.firestore}/v1/projects/{self.project}/databases/(default)/documents"

    @staticmethod
    def encode(d: dict) -> dict:
        out = {}
        for k, v in d.items():
            if isinstance(v, bool):
                out[k] = {"booleanValue": v}
            elif isinstance(v, int):
                out[k] = {"integerValue": str(v)}
            elif isinstance(v, float):
                out[k] = {"doubleValue": v}
            elif k.endswith("At"):
                out[k] = {"timestampValue": str(v)}
            else:
                out[k] = {"stringValue": str(v)}
        return out

    @staticmethod
    def decode(fields: dict) -> dict:
        out = {}
        for k, v in fields.items():
            if "integerValue" in v:
                out[k] = int(v["integerValue"])
            elif "doubleValue" in v:
                out[k] = float(v["doubleValue"])
            elif "booleanValue" in v:
                out[k] = v["booleanValue"]
            else:
                out[k] = v.get("stringValue", v.get("timestampValue", ""))
        return out

    def send(self, op: dict):
        """Run one queued operation: {'kind': 'player'|'score', 'data': {...}}"""
        uid, token = self.auth()
        d = dict(op["data"])
        d["owner"] = uid
        if op["kind"] == "player":
            pid = d["id"]
            self._http(f"{self.docs}/players/{urllib.parse.quote(pid)}", "PATCH",
                       {"fields": self.encode({k: v for k, v in d.items() if k != "id"})}, token)
        elif op["kind"] == "score":
            self._http(f"{self.docs}/scores", "POST", {"fields": self.encode(d)}, token)

    def top_scores(self, limit=10):
        uid, token = self.auth()
        q = {"structuredQuery": {"from": [{"collectionId": "scores"}],
                                 "orderBy": [{"field": {"fieldPath": "score"}, "direction": "DESCENDING"}],
                                 "limit": limit}}
        rows = self._http(f"{self.docs}:runQuery", "POST", q, token)
        return [self.decode(r["document"]["fields"]) for r in rows if "document" in r]


class SyncWorker(threading.Thread):
    """Uploads in the background and remembers what still has to go (data/pending.json)."""

    def __init__(self, client: FirebaseClient, pending_path: Path):
        super().__init__(daemon=True)
        self.client = client
        self.pending_path = pending_path
        self.pending = _read_json(pending_path, [])
        self.lock = threading.Lock()
        self.wake = threading.Event()
        self._stop_flag = threading.Event()
        self._refresh = True
        self.top = []
        self.last_error = ""
        self.connected = False

    def add(self, op):
        with self.lock:
            self.pending.append(op)
            _write_json(self.pending_path, self.pending)
        self.wake.set()

    def request_refresh(self):
        self._refresh = True
        self.wake.set()

    def stop(self):
        self._stop_flag.set()
        self.wake.set()

    def idle(self) -> bool:
        with self.lock:
            return not self.pending

    def _drain(self) -> bool:
        while True:
            with self.lock:
                if not self.pending:
                    return True
                op = self.pending[0]
            try:
                self.client.send(op)
            except FirebaseError as e:
                self.last_error = f"Firebase {e.status}: {e.message}"
                if e.status != 400:                       # 400 = our data was refused: drop it, don't block the queue
                    return False
            except Exception as e:                       # offline, timeouts...
                self.last_error = f"offline ({type(e).__name__})"
                return False
            with self.lock:
                if self.pending and self.pending[0] is op:
                    self.pending.pop(0)
                    _write_json(self.pending_path, self.pending)
            self.connected, self.last_error = True, ""

    def run(self):
        wait = 0.0
        self.wake.set()                                   # do a first upload / leaderboard fetch straight away
        while not self._stop_flag.is_set():
            self.wake.wait(timeout=wait or 30)
            self.wake.clear()
            if self._stop_flag.is_set():
                break
            ok = self._drain()
            if self._refresh:
                try:
                    self.top = self.client.top_scores(10)
                    self._refresh = False
                    self.connected, self.last_error = True, ""
                except FirebaseError as e:
                    self.last_error, ok = f"Firebase {e.status}: {e.message}", False
                except Exception as e:
                    self.last_error, ok = f"offline ({type(e).__name__})", False
            wait = 0.0 if ok else 15.0


# =============================================================================
# Local players
# =============================================================================
class Store:
    def __init__(self, base: Path = BASE, config_path: Path = None):
        self.dir = Path(base) / "data"
        self.file = self.dir / "players.json"
        self.lock = threading.Lock()
        self.db = _read_json(self.file, {"version": 1, "last_player": None, "players": {}})
        self.db.setdefault("players", {})
        self.sync = None
        cfg = _read_json(Path(config_path) if config_path else Path(base) / "firebase_config.json", None)
        if cfg and cfg.get("apiKey") and cfg.get("projectId") and "YOUR" not in cfg["apiKey"]:
            client = FirebaseClient(cfg, self.dir / "firebase_auth.json")
            self.sync = SyncWorker(client, self.dir / "pending.json")
            self.sync.start()

    # ---- players -------------------------------------------------------
    def _save(self):
        _write_json(self.file, self.db)

    def players(self):
        with self.lock:
            return sorted(self.db["players"].values(), key=lambda p: p.get("last_played", ""), reverse=True)

    def get(self, pid):
        return self.db["players"].get(pid)

    def last_player(self):
        pid = self.db.get("last_player")
        return self.get(pid) if pid else None

    def add_player(self, name, email, consent, avatar):
        p = {"id": uuid.uuid4().hex[:12], "name": name.strip()[:24], "email": email.strip()[:80],
             "consent": bool(consent), "avatar": avatar, "control": "keyboard",
             "best_score": 0, "coins_total": 0, "games": 0,
             "created": now_iso(), "last_played": now_iso()}
        with self.lock:
            self.db["players"][p["id"]] = p
            self.db["last_player"] = p["id"]
            self._save()
        self._upload_player(p)
        return p

    def update(self, pid, **fields):
        with self.lock:
            p = self.db["players"][pid]
            p.update(fields)
            p["last_played"] = now_iso()
            self.db["last_player"] = pid
            self._save()
        if {"avatar", "name"} & set(fields):
            self._upload_player(p)
        return p

    def record_run(self, pid, score, coins):
        """Call once when a run ends.  Returns {'new_best': bool, 'best': int}."""
        with self.lock:
            p = self.db["players"][pid]
            new_best = score > p["best_score"]
            if new_best:
                p["best_score"] = score
            p["coins_total"] += coins
            p["games"] += 1
            p["last_played"] = now_iso()
            self._save()
        self._upload_player(p)
        if self.sync and p["consent"] and score > 0:
            self.sync.add({"kind": "score", "data": {
                "playerId": p["id"], "name": p["name"], "avatar": p["avatar"],
                "score": int(score), "coins": int(coins), "createdAt": now_iso()}})
            self.sync.request_refresh()
        return {"new_best": new_best, "best": p["best_score"]}

    def _upload_player(self, p):
        if self.sync and p["consent"]:
            self.sync.add({"kind": "player", "data": {
                "id": p["id"], "name": p["name"], "email": p["email"], "avatar": p["avatar"],
                "bestScore": int(p["best_score"]), "coinsTotal": int(p["coins_total"]),
                "games": int(p["games"]), "consent": True,
                "createdAt": p["created"], "updatedAt": now_iso()}})

    # ---- leaderboard & status -------------------------------------------
    def leaderboard(self, limit=5):
        """Returns (entries, source) - entries are dicts with name, score, avatar."""
        if self.sync and self.sync.top:
            return [{"name": r.get("name", "?"), "score": r.get("score", 0), "avatar": r.get("avatar", "")}
                    for r in self.sync.top[:limit]], "online"
        local = sorted(self.players(), key=lambda p: p["best_score"], reverse=True)
        return [{"name": p["name"], "score": p["best_score"], "avatar": p["avatar"]}
                for p in local[:limit] if p["best_score"] > 0], "this computer"

    def status(self) -> str:
        if not self.sync:
            return "Saved on this computer (Firebase not set up)"
        if self.sync.last_error:
            return f"Online leaderboard: {self.sync.last_error}"
        return "Online leaderboard connected" if self.sync.connected else "Connecting to online leaderboard..."

    def close(self, timeout=2.0):
        if self.sync:
            end = time.time() + timeout
            while not self.sync.idle() and time.time() < end:
                time.sleep(0.05)
            self.sync.stop()
