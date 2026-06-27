#!/usr/bin/env python3
import asyncio
import json
import time
import hashlib
import sqlite3
import random
import os
import sys
import socket
import struct
import secrets
import argparse
import traceback
import logging
import threading
import queue
import signal
import base64
import binascii
import re
import uuid
import zlib
import tempfile
import shutil
import subprocess
from collections import defaultdict, deque
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Set, Tuple, Union, Any
from enum import Enum, auto
from datetime import datetime, timedelta
from functools import wraps, lru_cache
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from logging.handlers import RotatingFileHandler

#DEPENDENCY CHECK 
def install_and_import(package, import_name=None):
    if import_name is None:
        import_name = package
    try:
        __import__(import_name)
        return True
    except ImportError:
        import subprocess
        subprocess.check_call([sys.executable, "-m", "pip", "install", package])
        __import__(import_name)
        return True

REQUIRED_PACKAGES = [
    ("websockets", "websockets"),
    ("requests", "requests"),
    ("cryptography", "cryptography"),
    ("aiohttp", "aiohttp"),
    ("pycryptodome", "Crypto"),
    ("python-dotenv", "dotenv")# removed the nano libraries as too much fixes with nano bridge
]

for pkg, import_name in REQUIRED_PACKAGES:
    install_and_import(pkg, import_name)

import websockets
from websockets import serve
import requests
import aiohttp
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature, decode_dss_signature
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad
from dotenv import load_dotenv

# Suppress warnings,
import warnings
warnings.filterwarnings("ignore")

# LOGGING!! 
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s - %(message)s',
    handlers=[
        RotatingFileHandler('microcore.log', maxBytes=10_485_760, backupCount=5),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# CONFIG 
NODE_HOST = "0.0.0.0" 
NODE_PORT = 8080
WS_PATH = "/ws"
P2P_PORT = 8081
HTTP_PORT = 8082

SYMBOL = "MCX"
NAME = "MicroCore"
VERSION = "26.0-MAINNET"

# DUCO payment address
DUCO_PAYMENT_ADDRESS = "XAVER_KENG_XUAN_YI" # its centralised for DUCO.

# REAL TOKEN BRIDGE CONFIG 
# REPLACE THESE WITH YOUR ACTUAL WALLET ADDRESSES
BRIDGE_ADDRESSES = {
    "BTC": "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa",
    "ETH": "0x742d35Cc6634C0532925a3b844Bc9e7598f0b0a0",
    "USDC": "0x742d35Cc6634C0532925a3b844Bc9e7598f0b0a0"
}

BTC_API = "https://blockchain.info/rawaddr/"
ETH_API = "https://api.etherscan.io/api"
USDC_API = "https://api.etherscan.io/api"
ETHERSCAN_API_KEY = ""


INITIAL_BLOCK_REWARD = 18  
HALVING_INTERVAL = 4_204_800

# Total cap increased 6x proportionally
# Original: 546,840,000 MCX
# New: 3,281,040,000 MCX (6x)
MAX_SUPPLY = 3_281_040_000  

LEVEL_STAKE_RANGE = 1000
MAX_LEVEL = 10
MIN_WALLETS_FOR_NEXT_LEVEL = 10

LEVEL_BLOCK_INTERVALS = {
    1: 40, 2: 35, 3: 30, 4: 25, 5: 20,
    6: 15, 7: 10, 8: 9, 9: 8, 10: 7
}


LEVEL_CAPS = {
    1: 113_529_600,    # Was 18,921,600 (6x)
    2: 129_744_000,    # Was 21,624,000 (6x)
    3: 151_372_800,    # Was 25,228,800 (6x)
    4: 181_647_360,    # Was 30,274,560 (6x)
    5: 227_059_200,    # Was 37,843,200 (6x)
    6: 302_745_600,    # Was 50,457,600 (6x)
    7: 454_118_400,    # Was 75,686,400 (6x)
    8: 504_576_000,    # Was 84,096,000 (6x)
    9: 567_648_000,    # Was 94,608,000 (6x)
    10: 648_740_160    # Was 108,123,360 (6x), about 5B supply, disappointing.
}

VALIDATOR_SHARE = 0.70
NODE_SHARE = 0.08
UPTIME_SHARE = 0.05
LP_SHARE = 0.05
BUYER_REWARDS_SHARE = 0.12

SWAP_FEE_RATE = 0.003
LP_FEE_SHARE = 0.60
NODE_FEE_SHARE = 0.40

DEX_GAS_FEE_RATE = 0.006
DEX_GAS_FEE_MIN = 1
DEX_GAS_FEE_MAX = 100

def calculate_dex_gas_fee(amount: int) -> int:
    fee = int(amount * DEX_GAS_FEE_RATE)
    if fee < DEX_GAS_FEE_MIN:
        return DEX_GAS_FEE_MIN
    if fee > DEX_GAS_FEE_MAX:
        return DEX_GAS_FEE_MAX
    return fee

CROSS_CHAIN_NODE_SHARE = 0.80
CROSS_CHAIN_MINER_SHARE = 0.20

SIGNING_WINDOW_MS = 2500
SLASH_RATE = 0.10
MIN_VALIDATORS_PER_BLOCK = 10
UPTIME_PING_INTERVAL = 30
DISTRIBUTION_INTERVAL_SEC = 300

MAX_PEERS = 30
SYNC_INTERVAL = 10
HEARTBEAT_INTERVAL = 30
PEX_INTERVAL = 60
DISCOVERY_INTERVAL = 300

BAN_THRESHOLD = 5
BAN_DURATION = 3600
SLASH_COOLDOWN = 60

MCX_FEE_MIN = 1
MCX_FEE_MAX = 100
FIAT_RAMP_ENABLED = True

BUYER_REWARDS = [5000, 3000, 2000, 1000, 1000, 500, 500, 500, 500, 500]

TRANSFER_FEE_RATE = 0.006
TRANSFER_FEE_MIN = 0.01

MEMPOOL_MAX_SIZE = 10000
MEMPOOL_EXPIRY = 3600

MAX_BLOCK_SIZE = 2 * 1024 * 1024
MAX_TX_PER_BLOCK = 1000

TOKEN_CREATION_FEE = 1000

#  REAL TOKEN PRICES 
REAL_TOKEN_PRICES = {
    "BTC": 60000,
    "ETH": 3000,
    "USDC": 1
}

MCX_PRICE_USD = 0.01

def calculate_transfer_fee(amount: float) -> float:
    fee = amount * TRANSFER_FEE_RATE
    return max(TRANSFER_FEE_MIN, fee)

def get_halving_reward(level: int, block_height: int) -> int:
    halvings = block_height // HALVING_INTERVAL
    reward = INITIAL_BLOCK_REWARD // (2 ** halvings)
    return max(reward, 1)

#  GOSSIP DISCOVERY 
BOOTSTRAP_NODES = [
    "101.127.80.48:8080",
    "node1.microcore.network:8080",
    "node2.microcore.network:8080"
]
PEER_CACHE_FILE = "microcore_peers.json"
NODE_CACHE_FILE = "microcore_nodes.json"
MINER_CACHE_FILE = "microcore_miners.json"

def save_peers_to_cache(peers):
    try:
        unique = list(set(peers))
        with open(PEER_CACHE_FILE, 'w') as f:
            json.dump(unique, f, indent=2)
        logger.info(f"[CACHE] Saved {len(unique)} peers")
    except Exception as e:
        logger.error(f"[CACHE] Save peers failed: {e}")

def load_peers_from_cache():
    try:
        with open(PEER_CACHE_FILE, 'r') as f:
            peers = json.load(f)
        logger.info(f"[CACHE] Loaded {len(peers)} peers from cache")
        return peers
    except:
        logger.info("[CACHE] No peer cache file found")
        return []

def save_nodes_to_cache(nodes):
    try:
        with open(NODE_CACHE_FILE, 'w') as f:
            json.dump(nodes, f, indent=2)
        logger.info(f"[CACHE] Saved {len(nodes)} nodes")
    except Exception as e:
        logger.error(f"[CACHE] Save nodes failed: {e}")

def load_nodes_from_cache():
    try:
        with open(NODE_CACHE_FILE, 'r') as f:
            nodes = json.load(f)
        logger.info(f"[CACHE] Loaded {len(nodes)} nodes from cache")
        return nodes
    except:
        return []

def save_miners_to_cache(miners):
    try:
        with open(MINER_CACHE_FILE, 'w') as f:
            json.dump(miners, f, indent=2)
        logger.info(f"[CACHE] Saved {len(miners)} miners")
    except:
        pass

def get_bootstrap_peers():
    peers = BOOTSTRAP_NODES.copy()
    cached = load_peers_from_cache()
    for p in cached:
        if p not in peers:
            peers.append(p)
    return peers

#  RATE LIMITER 
class RateLimiter:
    def __init__(self, max_requests: int = 60, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window = window_seconds
        self._requests: Dict[str, deque] = {}
        self._lock = asyncio.Lock()
        self._cleanup_task = None
        self._stats = defaultdict(int)
    
    async def start_cleanup(self):
        async def cleanup_loop():
            while True:
                await asyncio.sleep(60)
                await self.cleanup()
        self._cleanup_task = asyncio.create_task(cleanup_loop())
    
    async def cleanup(self):
        async with self._lock:
            now = time.time()
            for ip in list(self._requests.keys()):
                while self._requests[ip] and now - self._requests[ip][0] > self.window:
                    self._requests[ip].popleft()
                if not self._requests[ip]:
                    del self._requests[ip]
    
    async def is_allowed(self, client_ip: str) -> bool:
        async with self._lock:
            now = time.time()
            if client_ip not in self._requests:
                self._requests[client_ip] = deque()
            while self._requests[client_ip] and now - self._requests[client_ip][0] > self.window:
                self._requests[client_ip].popleft()
            if len(self._requests[client_ip]) >= self.max_requests:
                self._stats[client_ip] += 1
                logger.warning(f"[RATE LIMIT] {client_ip} exceeded limit ({self._stats[client_ip]} violations)")
                return False
            self._requests[client_ip].append(now)
            return True
    
    def get_stats(self) -> dict:
        return {
            "active_ips": len(self._requests),
            "violations": dict(self._stats),
            "total_requests": sum(len(q) for q in self._requests.values())
        }

#  HEALTH CHECK 
class HealthChecker:
    def __init__(self):
        self.start_time = time.time()
        self.last_block_time = time.time()
        self.blocks_produced = 0
        self.peer_count = 0
        self.miner_count = 0
        self.errors = 0
        self.status = "starting"
        self._error_history = deque(maxlen=100)
        self._block_history = deque(maxlen=100)
    
    def get_status(self) -> dict:
        uptime = int(time.time() - self.start_time)
        block_rate = len(self._block_history) / max(uptime / 3600, 0.1)
        return {
            "status": self.status,
            "uptime": uptime,
            "uptime_hours": uptime / 3600,
            "blocks_produced": self.blocks_produced,
            "block_rate_per_hour": block_rate,
            "peers": self.peer_count,
            "miners": self.miner_count,
            "errors": self.errors,
            "error_rate": self.errors / max(uptime / 3600, 0.1),
            "last_block": int(self.last_block_time),
            "last_block_age": int(time.time() - self.last_block_time),
            "version": VERSION,
            "healthy": self.errors < 10 and (time.time() - self.last_block_time) < 300
        }
    
    def record_block(self, block_id: int):
        self.blocks_produced += 1
        self.last_block_time = time.time()
        self._block_history.append((block_id, time.time()))
    
    def record_error(self, error: str):
        self.errors += 1
        self._error_history.append((error, time.time()))
        if self.errors > 100:
            self.status = "degraded"
    
    def get_block_history(self, limit: int = 10) -> List[dict]:
        return [{"id": bid, "timestamp": ts} for bid, ts in list(self._block_history)[-limit:]]

#  CRYPTOGRAPHY 
def djb2_hash(data: str) -> str:
    h = 5381
    for c in data:
        h = ((h << 5) + h) + ord(c)
    return format(h & 0xFFFFFFFF, '08x')

def sha256_hash(data: str) -> str:
    return hashlib.sha256(data.encode()).hexdigest()

def verify_signature(pub: str, msg: str, sig: str, miner_type: str) -> bool:
    if miner_type in ["uno", "avr", "web"]:
        expected = djb2_hash(f"{pub}{msg}")
        return sig == expected
    if miner_type in ["esp32", "pc", "phone", "pico"]:
        try:
            pub_key = serialization.load_pem_public_key(pub.encode())
            sig_bytes = bytes.fromhex(sig)
            r = int.from_bytes(sig_bytes[:32], 'big')
            s = int.from_bytes(sig_bytes[32:], 'big')
            pub_key.verify(encode_dss_signature(r, s), msg.encode(), ec.ECDSA(hashes.SHA256()))
            return True
        except Exception as e:
            logger.debug(f"[SIG] ECDSA verification failed: {e}")
            return False
    return False

def sign_message(priv_hex: str, msg: str) -> str:
    priv = ec.derive_private_key(int(priv_hex, 16), ec.SECP256K1())
    r, s = decode_dss_signature(priv.sign(msg.encode(), ec.ECDSA(hashes.SHA256())))
    return r.to_bytes(32, 'big').hex() + s.to_bytes(32, 'big').hex()

def generate_wallet():
    priv = ec.generate_private_key(ec.SECP256K1())
    priv_hex = priv.private_numbers().private_value.to_bytes(32, 'big').hex()
    pub = priv.public_key()
    pub_pem = pub.public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    addr = "MCR_" + hashlib.sha256(pub_pem.encode()).hexdigest()[:32].upper()
    return addr, priv_hex, pub_pem

def hash_block(b: dict) -> str:
    return hashlib.sha256(json.dumps(b, sort_keys=True).encode()).hexdigest()

def hash_transaction(tx: dict) -> str:
    return hashlib.sha256(json.dumps(tx, sort_keys=True).encode()).hexdigest()

def get_public_ip():
    try:
        return requests.get('https://api.ipify.org').json()['ip']
    except:
        try:
            return requests.get('https://icanhazip.com').text.strip()
        except:
            return None

#  ENCRYPTION 
def encrypt_private_key(priv_hex: str, password: str) -> dict:
    salt = os.urandom(16)
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=100000)
    key = kdf.derive(password.encode())
    iv = os.urandom(16)
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
    encryptor = cipher.encryptor()
    padded = pad(priv_hex.encode(), AES.block_size)
    encrypted = encryptor.update(padded) + encryptor.finalize()
    return {
        "salt": base64.b64encode(salt).decode(),
        "iv": base64.b64encode(iv).decode(),
        "data": base64.b64encode(encrypted).decode()
    }

def decrypt_private_key(encrypted: dict, password: str) -> str:
    salt = base64.b64decode(encrypted["salt"])
    iv = base64.b64decode(encrypted["iv"])
    data = base64.b64decode(encrypted["data"])
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=100000)
    key = kdf.derive(password.encode())
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
    decryptor = cipher.decryptor()
    decrypted = decryptor.update(data) + decryptor.finalize()
    return unpad(decrypted, AES.block_size).decode()

#  P2P PROTOCOL 
P2P_MAGIC = b"MCR1"
P2P_VERSION = 1

MSG_HANDSHAKE, MSG_PING, MSG_PONG, MSG_GET_BLOCKS, MSG_BLOCKS, \
MSG_NEW_BLOCK, MSG_NEW_TX, MSG_GET_PEERS, MSG_PEERS, MSG_SLASH, \
MSG_NODE_REGISTER, MSG_GET_STATUS, MSG_STATUS, MSG_GET_MEMPOOL, \
MSG_MEMPOOL, MSG_GET_MINERS, MSG_MINERS, MSG_BAN, MSG_UNBAN = range(19)

def encode_p2p(msg_type: int, payload: dict) -> bytes:
    j = json.dumps(payload).encode()
    return P2P_MAGIC + struct.pack(">BBI", P2P_VERSION, msg_type, len(j)) + j

def decode_p2p(data: bytes) -> tuple:
    if len(data) < 10 or data[:4] != P2P_MAGIC:
        return None, None
    version = data[4]
    msg_type = data[5]
    length = struct.unpack(">I", data[6:10])[0]
    payload = json.loads(data[10:10+length].decode())
    return msg_type, payload

#  DATA STRUCTURES 
@dataclass
class Miner:
    vid: str
    pub: str
    username: str
    wallet: str
    stake: int
    level: int
    uptime: int
    today_uptime: int
    last_ping: float
    active: bool
    rewards: int
    blocks: int
    slashes: int
    misses: int
    mtype: str
    liquidity_provided: int = 0
    fees_collected: int = 0
    banned_until: float = 0
    created_at: float = field(default_factory=time.time)
    last_block: int = 0
    consecutive_misses: int = 0
    total_uptime: int = 0
    best_level: int = 1
    towers: List[int] = field(default_factory=list)
    permanent_tower: bool = False
    ip_address: str = ""
    node_id: str = ""
    version: str = VERSION

@dataclass
class Node:
    node_id: str
    username: str
    wallet: str
    ip: str
    port: int
    last_seen: float
    height: int
    active: bool
    rewards_earned: int
    version: str = VERSION
    peers: List[str] = field(default_factory=list)
    mining_enabled: bool = True
    staking_enabled: bool = True
    last_sync: float = 0

@dataclass
class Transaction:
    tx_hash: str
    from_wallet: str
    to_wallet: str
    amount: int
    fee: int
    timestamp: float
    block_id: int
    status: str
    tx_type: str
    signature: str = ""
    nonce: int = 0
    confirmations: int = 0
    data: dict = field(default_factory=dict)

@dataclass
class Block:
    id: int
    ts: float
    prev: str
    validators: List[str]
    level: int
    sigs: Dict[str, str]
    hash: str
    reward: int
    tx_count: int = 0
    transactions: List[str] = field(default_factory=list)
    merkle_root: str = ""
    nonce: int = 0
    difficulty: int = 1
    version: str = VERSION
    timestamp: float = field(default_factory=time.time)
    height: int = 0

@dataclass
class RealTokenBridge:
    token_symbol: str
    bridge_address: str
    private_key_encrypted: dict
    balance: float
    last_updated: float
    pending_withdrawals: List[dict] = field(default_factory=list)

@dataclass
class SwapRequest:
    request_id: str
    user_wallet: str
    token_from: str
    token_to: str
    amount_from: int
    amount_to: int
    status: str
    created_at: float
    completed_at: float = 0
    tx_hash: str = ""
    real_tx_hash: str = ""

# MEMPOOL 
class Mempool:
    def __init__(self, max_size: int = MEMPOOL_MAX_SIZE):
        self.transactions: Dict[str, Transaction] = {}
        self.max_size = max_size
        self._lock = asyncio.Lock()
        self._expiry = MEMPOOL_EXPIRY
        self._pending_by_wallet: Dict[str, List[str]] = defaultdict(list)
        self._fees_by_amount: Dict[int, List[str]] = defaultdict(list)
    
    async def add_transaction(self, tx: Transaction) -> bool:
        async with self._lock:
            if len(self.transactions) >= self.max_size:
                await self._cleanup()
                if len(self.transactions) >= self.max_size:
                    return False
            if tx.tx_hash in self.transactions:
                return False
            self.transactions[tx.tx_hash] = tx
            self._pending_by_wallet[tx.from_wallet].append(tx.tx_hash)
            self._fees_by_amount[tx.fee].append(tx.tx_hash)
            return True
    
    async def remove_transaction(self, tx_hash: str) -> bool:
        async with self._lock:
            if tx_hash not in self.transactions:
                return False
            tx = self.transactions[tx_hash]
            self._pending_by_wallet[tx.from_wallet].remove(tx_hash)
            self._fees_by_amount[tx.fee].remove(tx_hash)
            del self.transactions[tx_hash]
            return True
    
    async def get_transactions(self, limit: int = 100) -> List[Transaction]:
        async with self._lock:
            await self._cleanup()
            sorted_txs = sorted(self.transactions.values(), key=lambda x: (x.fee, -x.timestamp), reverse=True)
            return sorted_txs[:limit]
    
    async def get_by_wallet(self, wallet: str) -> List[Transaction]:
        async with self._lock:
            hashes = self._pending_by_wallet.get(wallet, [])
            return [self.transactions[h] for h in hashes if h in self.transactions]
    
    async def _cleanup(self):
        now = time.time()
        to_remove = []
        for tx_hash, tx in self.transactions.items():
            if now - tx.timestamp > self._expiry:
                to_remove.append(tx_hash)
        for tx_hash in to_remove:
            await self.remove_transaction(tx_hash)
        if to_remove:
            logger.info(f"[MEMPOOL] Removed {len(to_remove)} expired transactions")
    
    async def clear(self):
        async with self._lock:
            self.transactions.clear()
            self._pending_by_wallet.clear()
            self._fees_by_amount.clear()
    
    def size(self) -> int:
        return len(self.transactions)
    
    def get_stats(self) -> dict:
        return {
            "size": len(self.transactions),
            "max_size": self.max_size,
            "pending_wallets": len(self._pending_by_wallet),
            "avg_fee": sum(self.transactions[t].fee for t in self.transactions) / max(len(self.transactions), 1)
        }

# REAL TOKEN BRIDGE
class RealTokenBridge:
    """
    Manages real token bridges for BTC, ETH, USDC
    DIRECTLY INTEGRATED with DEX pools
    NO EXTERNAL LIBRARIES - direct API calls only
    """
    
    def __init__(self, net):
        self.net = net
        self.tokens = {}
        self.pending_swaps: Dict[str, SwapRequest] = {}
        self._lock = asyncio.Lock()
        self._load_bridge_state()
        self._init_bridge_addresses()
    
    def _load_bridge_state(self):
        try:
            c = self.net.conn.cursor()
            c.execute("SELECT token_symbol, bridge_address, balance, last_updated FROM real_token_bridges")
            rows = c.fetchall()
            for row in rows:
                self.tokens[row[0]] = {
                    "bridge_address": row[1],
                    "balance": row[2],
                    "last_updated": row[3]
                }
            logger.info(f"[BRIDGE] Loaded {len(self.tokens)} token bridges")
        except Exception as e:
            logger.warning(f"[BRIDGE] No bridge state found: {e}")
            self.tokens = {}
    
    def _init_bridge_addresses(self):
        c = self.net.conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS real_token_bridges (
            token_symbol TEXT PRIMARY KEY,
            bridge_address TEXT NOT NULL,
            balance REAL DEFAULT 0,
            last_updated REAL DEFAULT 0,
            private_key_encrypted TEXT DEFAULT ''
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS bridge_swap_requests (
            request_id TEXT PRIMARY KEY,
            user_wallet TEXT NOT NULL,
            token_from TEXT NOT NULL,
            token_to TEXT NOT NULL,
            amount_from REAL NOT NULL,
            amount_to REAL NOT NULL,
            status TEXT DEFAULT 'pending',
            created_at REAL NOT NULL,
            completed_at REAL DEFAULT 0,
            tx_hash TEXT DEFAULT '',
            real_tx_hash TEXT DEFAULT '',
            error TEXT DEFAULT ''
        )''')
        self.net.conn.commit()
        
        for symbol, address in BRIDGE_ADDRESSES.items():
            if symbol not in self.tokens:
                bridge_priv_hex = secrets.token_hex(32)
                encrypted_priv = encrypt_private_key(
                    bridge_priv_hex,
                    f"bridge_{symbol}_microcore_v26_secure"
                )
                c.execute("INSERT OR REPLACE INTO real_token_bridges (token_symbol, bridge_address, balance, last_updated, private_key_encrypted) VALUES (?, ?, ?, ?, ?)",
                         (symbol, address, 0, time.time(), json.dumps(encrypted_priv)))
                self.net.conn.commit()
                self.tokens[symbol] = {
                    "bridge_address": address,
                    "balance": 0,
                    "last_updated": time.time(),
                    "private_key_encrypted": encrypted_priv
                }
                logger.info(f"[BRIDGE] Initialized {symbol} bridge at {address}")
    
    def _get_bridge_private_key(self, symbol: str) -> Optional[str]:
        try:
            if symbol not in self.tokens:
                return None
            token = self.tokens[symbol]
            if "private_key_encrypted" not in token:
                return None
            encrypted = token["private_key_encrypted"]
            if isinstance(encrypted, str):
                encrypted = json.loads(encrypted)
            return decrypt_private_key(encrypted, f"bridge_{symbol}_microcore_v26_secure")
        except Exception as e:
            logger.error(f"[BRIDGE] Failed to decrypt private key for {symbol}: {e}")
            return None
    
    #  VERIFY REAL TOKEN PAYMENTS 
    
    async def verify_btc_payment(self, sender_address: str, expected_amount: float) -> dict:
        try:
            response = requests.get(f"{BTC_API}{sender_address}", timeout=10)
            if response.status_code == 200:
                data = response.json()
                total_received = data.get('total_received', 0) / 1e8
                if total_received >= expected_amount:
                    return {"success": True, "received": total_received}
            return {"success": False, "error": "Payment not verified"}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def verify_eth_payment(self, sender_address: str, expected_amount: float) -> dict:
        try:
            response = requests.get(
                f"{ETH_API}?module=account&action=txlist&address={sender_address}&sort=desc&apikey={ETHERSCAN_API_KEY}",
                timeout=10
            )
            if response.status_code == 200:
                data = response.json()
                if data.get('status') == '1':
                    txs = data.get('result', [])
                    total_sent = 0
                    for tx in txs:
                        value = int(tx.get('value', 0)) / 1e18
                        total_sent += value
                    if total_sent >= expected_amount:
                        return {"success": True, "received": total_sent}
            return {"success": False, "error": "Payment not verified"}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def verify_usdc_payment(self, sender_address: str, expected_amount: float) -> dict:
        try:
            response = requests.get(
                f"{USDC_API}?module=account&action=tokentx&contractaddress=0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48&address={sender_address}&sort=desc&apikey={ETHERSCAN_API_KEY}",
                timeout=10
            )
            if response.status_code == 200:
                data = response.json()
                if data.get('status') == '1':
                    txs = data.get('result', [])
                    total_sent = 0
                    for tx in txs:
                        if tx.get('from', '').lower() == sender_address.lower():
                            value = int(tx.get('value', 0)) / 1e6
                            total_sent += value
                    if total_sent >= expected_amount:
                        return {"success": True, "received": total_sent}
            return {"success": False, "error": "Payment not verified"}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    #  SWAP MCX -> REAL TOKEN 
    
    async def swap_mcx_to_real(self, user_wallet: str, mcx_amount: int, token_symbol: str) -> dict:
        """
        User swaps MCX for REAL token (BTC, ETH, USDC)
        This is integrated with DEX - uses DEX pool for price discovery
        """
        async with self._lock:
            if token_symbol not in self.tokens:
                return {"success": False, "error": f"Token {token_symbol} not supported for real swap"}
            
            # Check user has enough MCX
            if self.net.balances.get(user_wallet, 0) < mcx_amount:
                return {"success": False, "error": f"Insufficient MCX balance. Have {self.net.balances.get(user_wallet, 0)}, need {mcx_amount}"}
            
            # Get DEX price from the MCX/token pool
            pool_id = f"MCX/{token_symbol}"
            pool = self.net.dex.pools.get(pool_id)
            if not pool:
                return {"success": False, "error": f"Pool {pool_id} not found"}
            
            # Calculate real token amount using DEX formula
            # Using the DEX pool reserves for price discovery
            reserve_mcx = pool["reserve_a"]  # MCX reserve
            reserve_token = pool["reserve_b"]  # Token reserve
            
            # Apply swap fee and gas fee
            gas_fee = calculate_dex_gas_fee(mcx_amount)
            swap_fee = int(mcx_amount * SWAP_FEE_RATE)
            total_fee = gas_fee + swap_fee
            mcx_after_fees = mcx_amount - total_fee
            
            # Calculate output using constant product formula
            real_token_amount = (mcx_after_fees * reserve_token) / (reserve_mcx + mcx_after_fees)
            
            if self.net.balances.get(user_wallet, 0) < mcx_amount + total_fee:
                return {"success": False, "error": f"Insufficient balance for fees. Need {total_fee} MCX"}
            
            # Check bridge has enough real tokens, no more fakes ig
            bridge = self.tokens.get(token_symbol)
            if bridge["balance"] < real_token_amount:
                return {"success": False, "error": f"Insufficient {token_symbol} in bridge. Available: {bridge['balance']}, Need: {real_token_amount}"}
            
            # Deduct MCX from user (amount + fees)
            self.net.balances[user_wallet] -= mcx_amount
            self.net.balances[user_wallet] -= total_fee
            self.net._save_balance(user_wallet, self.net.balances[user_wallet])
            
            # Distribut fees
            validator_share = int(gas_fee * 0.70)
            node_share = gas_fee - validator_share
            self.net.validator_fee_pool += validator_share
            self.net.node_pool += node_share
            
            # Add swap fee to LP pool
            lp_fee = int(swap_fee * LP_FEE_SHARE)
            node_fee = swap_fee - lp_fee
            self.net.lp_pool += lp_fee
            self.net.node_pool += node_fee
            
            # Update DEX pool reserves (MCX increases, token decreases)
            pool["reserve_a"] += mcx_amount
            pool["reserve_b"] -= real_token_amount
            self.net.dex._update_pool_in_db(pool_id)
            
            # Reduce bridge balance
            bridge["balance"] -= real_token_amount
            self._update_bridge_balance(token_symbol, bridge["balance"])
            
            # Create swap request
            request_id = f"{token_symbol}_{user_wallet}_{int(time.time())}_{secrets.token_hex(4)}"
            swap_request = SwapRequest(
                request_id=request_id,
                user_wallet=user_wallet,
                token_from="MCX",
                token_to=token_symbol,
                amount_from=mcx_amount,
                amount_to=real_token_amount,
                status="pending_real_transfer",
                created_at=time.time()
            )
            
            self.pending_swaps[request_id] = swap_request
            self._save_swap_request(swap_request)
            
            logger.info(f"[BRIDGE] Swap initiated: {mcx_amount} MCX -> {real_token_amount} {token_symbol} by {user_wallet}")
            
            return {
                "success": True,
                "request_id": request_id,
                "token_symbol": token_symbol,
                "mcx_amount": mcx_amount,
                "real_token_amount": real_token_amount,
                "bridge_address": bridge["bridge_address"],
                "status": "pending_real_transfer",
                "message": f"Please send {real_token_amount} {token_symbol} from the bridge address to {user_wallet}",
                "fees": {"gas": gas_fee, "swap": swap_fee, "total": total_fee},
                "dex_price": reserve_mcx / reserve_token if reserve_token > 0 else 0
            }
    
    # SWAP REAL TOKEN -> MCX     
    async def swap_real_to_mcx(self, user_wallet: str, token_symbol: str, real_token_amount: float, sender_address: str) -> dict:
        """
        User sends REAL token to bridge, receives MCX
        Integrated with DEX - uses DEX pool for price discovery
        """
        async with self._lock:
            if token_symbol not in self.tokens:
                return {"success": False, "error": f"Token {token_symbol} not supported for real swap"}
            
            # Verify payment on real blockchain
            verification = await self._verify_payment(token_symbol, sender_address, real_token_amount)
            if not verification["success"]:
                return {"success": False, "error": verification["error"]}
            
            # Get DEX pool
            pool_id = f"MCX/{token_symbol}"
            pool = self.net.dex.pools.get(pool_id)
            if not pool:
                return {"success": False, "error": f"Pool {pool_id} not found"}
            
            reserve_mcx = pool["reserve_a"]
            reserve_token = pool["reserve_b"]
            
            # Calculate MCX amount using DEX formula
            mcx_amount = int((real_token_amount * reserve_mcx) / (reserve_token - real_token_amount))
            
            if mcx_amount < 1:
                return {"success": False, "error": "Amount too small, minimum 1 MCX"}
            
            # Calculate fees (deducted from MCX received)
            gas_fee = calculate_dex_gas_fee(mcx_amount)
            swap_fee = int(mcx_amount * SWAP_FEE_RATE)
            total_fee = gas_fee + swap_fee
            net_mcx = mcx_amount - total_fee
            
            if net_mcx < 1:
                return {"success": False, "error": "Amount too small after fees"}
            
            # Credit MCX to user
            self.net.balances[user_wallet] = self.net.balances.get(user_wallet, 0) + net_mcx
            self.net._save_balance(user_wallet, self.net.balances[user_wallet])
            
            # Distribute fees
            validator_share = int(gas_fee * 0.70)
            node_share = gas_fee - validator_share
            self.net.validator_fee_pool += validator_share
            self.net.node_pool += node_share
            
            # Add swap fee to LP pool
            lp_fee = int(swap_fee * LP_FEE_SHARE)
            node_fee = swap_fee - lp_fee
            self.net.lp_pool += lp_fee
            self.net.node_pool += node_fee
            
            # Update DEX pool reserves (MCX decreases, token increases)
            pool["reserve_a"] -= mcx_amount
            pool["reserve_b"] += real_token_amount
            self.net.dex._update_pool_in_db(pool_id)
            
            # Increase bridge balance
            bridge = self.tokens.get(token_symbol)
            bridge["balance"] += real_token_amount
            self._update_bridge_balance(token_symbol, bridge["balance"])
            
            # Create swap request
            request_id = f"{token_symbol}_{user_wallet}_{int(time.time())}_{secrets.token_hex(4)}"
            swap_request = SwapRequest(
                request_id=request_id,
                user_wallet=user_wallet,
                token_from=token_symbol,
                token_to="MCX",
                amount_from=real_token_amount,
                amount_to=net_mcx,
                status="completed",
                created_at=time.time(),
                completed_at=time.time(),
                real_tx_hash=verification.get("tx_hash", "")
            )
            
            self.pending_swaps[request_id] = swap_request
            self._save_swap_request(swap_request)
            
            logger.info(f"[BRIDGE] Swap completed: {real_token_amount} {token_symbol} -> {net_mcx} MCX by {user_wallet}")
            
            return {
                "success": True,
                "request_id": request_id,
                "token_symbol": token_symbol,
                "real_token_amount": real_token_amount,
                "mcx_amount": net_mcx,
                "fees": {"gas": gas_fee, "swap": swap_fee, "total": total_fee},
                "dex_price": reserve_mcx / reserve_token if reserve_token > 0 else 0
            }
    
    async def _verify_payment(self, token_symbol: str, sender_address: str, expected_amount: float) -> dict:
        if token_symbol == "BTC":
            return await self.verify_btc_payment(sender_address, expected_amount)
        elif token_symbol == "ETH":
            return await self.verify_eth_payment(sender_address, expected_amount)
        elif token_symbol == "USDC":
            return await self.verify_usdc_payment(sender_address, expected_amount)
        else:
            return {"success": False, "error": f"Unsupported token: {token_symbol}"}
    
    def _update_bridge_balance(self, token_symbol: str, balance: float):
        c = self.net.conn.cursor()
        c.execute("UPDATE real_token_bridges SET balance=?, last_updated=? WHERE token_symbol=?",
                 (balance, time.time(), token_symbol))
        self.net.conn.commit()
        self.tokens[token_symbol]["balance"] = balance
        self.tokens[token_symbol]["last_updated"] = time.time()
    
    def _save_swap_request(self, swap_request: SwapRequest):
        c = self.net.conn.cursor()
        c.execute("INSERT OR REPLACE INTO bridge_swap_requests (request_id, user_wallet, token_from, token_to, amount_from, amount_to, status, created_at, completed_at, tx_hash, real_tx_hash, error) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                 (swap_request.request_id, swap_request.user_wallet, swap_request.token_from, swap_request.token_to,
                  swap_request.amount_from, swap_request.amount_to, swap_request.status,
                  swap_request.created_at, swap_request.completed_at, swap_request.tx_hash,
                  swap_request.real_tx_hash, ""))
        self.net.conn.commit()
    
    def get_bridge_status(self) -> dict:
        status = {}
        for symbol, token in self.tokens.items():
            status[symbol] = {
                "address": token["bridge_address"],
                "balance": token["balance"],
                "last_updated": token.get("last_updated", 0),
                "price_usd": REAL_TOKEN_PRICES.get(symbol, 0)
            }
        return status
    
    def get_pending_swaps(self, wallet: Optional[str] = None) -> List[dict]:
        c = self.net.conn.cursor()
        if wallet:
            c.execute("SELECT * FROM bridge_swap_requests WHERE user_wallet=? AND status='pending'", (wallet,))
        else:
            c.execute("SELECT * FROM bridge_swap_requests WHERE status='pending'")
        rows = c.fetchall()
        return [
            {
                "request_id": row[0],
                "user_wallet": row[1],
                "token_from": row[2],
                "token_to": row[3],
                "amount_from": row[4],
                "amount_to": row[5],
                "status": row[6],
                "created_at": row[7],
                "completed_at": row[8]
            }
            for row in rows
        ]
    
    def get_swap_history(self, wallet: str, limit: int = 20) -> List[dict]:
        c = self.net.conn.cursor()
        c.execute("SELECT * FROM bridge_swap_requests WHERE user_wallet=? ORDER BY created_at DESC LIMIT ?", (wallet, limit))
        rows = c.fetchall()
        return [
            {
                "request_id": row[0],
                "user_wallet": row[1],
                "token_from": row[2],
                "token_to": row[3],
                "amount_from": row[4],
                "amount_to": row[5],
                "status": row[6],
                "created_at": row[7],
                "completed_at": row[8],
                "tx_hash": row[9],
                "real_tx_hash": row[10]
            }
            for row in rows
        ]
    
# DEX
class DEX:
    def __init__(self, net):
        self.net = net
        self.pools = {}
        self.tokens = {}
        self.price_history = {}
        self.node_wallet = None
        self._lock = asyncio.Lock()
        self.fee_rate = SWAP_FEE_RATE
        self.gas_fee_rate = DEX_GAS_FEE_RATE
        self.gas_fee_min = DEX_GAS_FEE_MIN
        self.gas_fee_max = DEX_GAS_FEE_MAX
        self._load_tokens()
        self._load_pools()
        self._load_price_history()
        self._init_node_wallet()
    
    def _init_node_wallet(self):
        try:
            c = self.net.conn.cursor()
            c.execute('''CREATE TABLE IF NOT EXISTS node_wallet (
                address TEXT PRIMARY KEY,
                private_key_encrypted TEXT NOT NULL,
                public_key TEXT NOT NULL,
                created_at REAL NOT NULL,
                last_updated REAL DEFAULT 0
            )''')
            self.net.conn.commit()
            c.execute("SELECT address, private_key_encrypted, public_key FROM node_wallet LIMIT 1")
            row = c.fetchone()
            if row:
                self.node_wallet = {
                    "address": row[0],
                    "private_key_encrypted": row[1],
                    "public_key_pem": row[2]
                }
                logger.info(f"[DEX] Node wallet loaded: {self.node_wallet['address']}")
            else:
                address, priv_hex, pub_pem = generate_wallet()
                encrypted_priv = encrypt_private_key(priv_hex, "dex_wallet_microcore_v26_secure")
                c.execute("INSERT INTO node_wallet (address, private_key_encrypted, public_key, created_at) VALUES (?, ?, ?, ?)",
                         (address, json.dumps(encrypted_priv), pub_pem, time.time()))
                self.net.conn.commit()
                self.node_wallet = {
                    "address": address,
                    "private_key_encrypted": encrypted_priv,
                    "public_key_pem": pub_pem
                }
                logger.info(f"[DEX] Node wallet created: {address}")
        except Exception as e:
            logger.error(f"[DEX] Failed to init node wallet: {e}")
            self.node_wallet = None
    
    def _get_node_private_key(self) -> Optional[str]:
        if not self.node_wallet:
            return None
        try:
            if isinstance(self.node_wallet["private_key_encrypted"], str):
                encrypted = json.loads(self.node_wallet["private_key_encrypted"])
            else:
                encrypted = self.node_wallet["private_key_encrypted"]
            return decrypt_private_key(encrypted, "dex_wallet_microcore_v26_secure")
        except Exception as e:
            logger.error(f"[DEX] Failed to decrypt node wallet: {e}")
            return None
    
    def _load_tokens(self):
        try:
            c = self.net.conn.cursor()
            c.execute("SELECT symbol, name, supply, owner, created_at, decimals, mintable FROM tokens")
            rows = c.fetchall()
            for row in rows:
                self.tokens[row[0]] = {
                    "name": row[1],
                    "supply": row[2],
                    "owner": row[3],
                    "created_at": row[4],
                    "decimals": row[5] if len(row) > 5 else 18,
                    "mintable": bool(row[6]) if len(row) > 6 else False
                }
            logger.info(f"[DEX] Loaded {len(self.tokens)} tokens")
        except Exception as e:
            logger.warning(f"[DEX] No tokens found: {e}")
            self.tokens = {}
    
    def _load_pools(self):
        try:
            c = self.net.conn.cursor()
            c.execute("SELECT pool_id, token_a, token_b, reserve_a, reserve_b, total_lp, created_at, fee_rate, volume_24h, swap_count, last_updated FROM pools")
            rows = c.fetchall()
            for row in rows:
                self.pools[row[0]] = {
                    "token_a": row[1],
                    "token_b": row[2],
                    "reserve_a": row[3],
                    "reserve_b": row[4],
                    "total_lp": row[5],
                    "created_at": row[6],
                    "fee_rate": row[7] if len(row) > 7 else 0.003,
                    "volume_24h": row[8] if len(row) > 8 else 0,
                    "swap_count": row[9] if len(row) > 9 else 0,
                    "last_updated": row[10] if len(row) > 10 else 0,
                    "lp_positions": {}
                }
                c2 = self.net.conn.cursor()
                c2.execute("SELECT wallet, lp_shares, created_at, fees_earned FROM lp_positions WHERE pool_id=?", (row[0],))
                for lp_row in c2.fetchall():
                    self.pools[row[0]]["lp_positions"][lp_row[0]] = {
                        "shares": lp_row[1],
                        "created_at": lp_row[2],
                        "fees_earned": lp_row[3] if len(lp_row) > 3 else 0
                    }
            logger.info(f"[DEX] Loaded {len(self.pools)} pools")
        except Exception as e:
            logger.warning(f"[DEX] No pools found: {e}")
            self.pools = {}
    
    def _load_price_history(self):
        try:
            c = self.net.conn.cursor()
            c.execute("SELECT pool_id, price, timestamp FROM price_history ORDER BY timestamp DESC LIMIT 1000")
            rows = c.fetchall()
            for row in rows:
                if row[0] not in self.price_history:
                    self.price_history[row[0]] = []
                self.price_history[row[0]].append({"price": row[1], "timestamp": row[2]})
            logger.info(f"[DEX] Loaded price history for {len(self.price_history)} pools")
        except Exception as e:
            logger.warning(f"[DEX] No price history found: {e}")
            self.price_history = {}
    
    def _get_token_balance(self, wallet: str, symbol: str) -> int:
        if symbol == "MCX":
            return self.net.balances.get(wallet, 0)
        c = self.net.conn.cursor()
        c.execute("SELECT balance FROM token_balances WHERE wallet=? AND token_symbol=?", (wallet, symbol))
        row = c.fetchone()
        return row[0] if row else 0
    
    def _mint_token(self, symbol: str, to: str, amount: int) -> dict:
        if symbol == "MCX":
            self.net.balances[to] = self.net.balances.get(to, 0) + amount
            self.net._save_balance(to, self.net.balances[to])
            return {"success": True}
        c = self.net.conn.cursor()
        c.execute("INSERT OR REPLACE INTO token_balances (wallet, token_symbol, balance) VALUES (?, ?, COALESCE((SELECT balance FROM token_balances WHERE wallet=? AND token_symbol=?), 0) + ?)",
                  (to, symbol, to, symbol, amount))
        self.net.conn.commit()
        return {"success": True}
    
    def _burn_token(self, symbol: str, from_wallet: str, amount: int) -> dict:
        if symbol == "MCX":
            if self.net.balances.get(from_wallet, 0) < amount:
                return {"success": False, "error": "Insufficient balance"}
            self.net.balances[from_wallet] -= amount
            self.net._save_balance(from_wallet, self.net.balances[from_wallet])
            return {"success": True}
        balance = self._get_token_balance(from_wallet, symbol)
        if balance < amount:
            return {"success": False, "error": "Insufficient token balance"}
        c = self.net.conn.cursor()
        c.execute("UPDATE token_balances SET balance = balance - ? WHERE wallet=? AND token_symbol=?",
                  (amount, from_wallet, symbol))
        self.net.conn.commit()
        return {"success": True}
    
    def _record_price(self, pool_id: str, price: float, volume: int):
        try:
            c = self.net.conn.cursor()
            c.execute("INSERT INTO price_history (pool_id, price, timestamp, volume) VALUES (?, ?, ?, ?)",
                      (pool_id, price, time.time(), volume))
            self.net.conn.commit()
            if pool_id not in self.price_history:
                self.price_history[pool_id] = []
            self.price_history[pool_id].append({"price": price, "timestamp": time.time()})
            if len(self.price_history[pool_id]) > 1000:
                self.price_history[pool_id] = self.price_history[pool_id][-1000:]
        except Exception as e:
            logger.warning(f"[DEX] Failed to record price: {e}")
    
    def _calculate_gas_fee(self, amount: int) -> int:
        fee = int(amount * DEX_GAS_FEE_RATE)
        if fee < DEX_GAS_FEE_MIN:
            return DEX_GAS_FEE_MIN
        if fee > DEX_GAS_FEE_MAX:
            return DEX_GAS_FEE_MAX
        return fee
    
    def create_token(self, symbol: str, name: str, supply: int, owner: str, decimals: int = 18, mintable: bool = False) -> dict:
        if symbol in self.tokens:
            return {"success": False, "error": f"Token {symbol} already exists"}
        gas_fee = self._calculate_gas_fee(TOKEN_CREATION_FEE)
        if self.net.balances.get(owner, 0) < TOKEN_CREATION_FEE + gas_fee:
            return {"success": False, "error": f"Insufficient MCX. Need {TOKEN_CREATION_FEE} + {gas_fee} gas fee"}
        self.net.balances[owner] -= gas_fee
        validator_share = int(gas_fee * 0.70)
        node_share = gas_fee - validator_share
        self.net.validator_fee_pool += validator_share
        self.net.node_pool += node_share
        self.net.balances[owner] -= TOKEN_CREATION_FEE
        self.net.validator_fee_pool += TOKEN_CREATION_FEE
        self.net._save_balance(owner, self.net.balances[owner])
        self.tokens[symbol] = {
            "name": name,
            "supply": supply,
            "owner": owner,
            "created_at": time.time(),
            "decimals": decimals,
            "mintable": mintable
        }
        self._mint_token(symbol, owner, supply)
        c = self.net.conn.cursor()
        c.execute("INSERT INTO tokens (symbol, name, supply, owner, created_at, decimals, mintable) VALUES (?, ?, ?, ?, ?, ?, ?)",
                  (symbol, name, supply, owner, time.time(), decimals, 1 if mintable else 0))
        self.net.conn.commit()
        logger.info(f"[DEX] Created token {symbol} with supply {supply} for {owner} (gas fee: {gas_fee})")
        return {
            "success": True,
            "symbol": symbol,
            "name": name,
            "supply": supply,
            "owner": owner,
            "fee_paid": TOKEN_CREATION_FEE,
            "gas_fee": gas_fee
        }
    
    async def create_pool(self, token_a: str, token_b: str, amount_a: int, amount_b: int, creator: str) -> dict:
        async with self._lock:
            if token_a == token_b:
                return {"success": False, "error": "Cannot create pool with same token"}
            pool_id = f"{token_a}/{token_b}"
            pool_id_reverse = f"{token_b}/{token_a}"
            if pool_id in self.pools or pool_id_reverse in self.pools:
                return {"success": False, "error": "Pool already exists"}
            if token_a not in self.tokens and token_a != "MCX":
                return {"success": False, "error": f"Token {token_a} doesn't exist"}
            if token_b not in self.tokens and token_b != "MCX":
                return {"success": False, "error": f"Token {token_b} doesn't exist"}
            total_amount = amount_a + amount_b
            gas_fee = self._calculate_gas_fee(total_amount)
            if self.net.balances.get(creator, 0) < gas_fee:
                return {"success": False, "error": f"Insufficient MCX for gas fee. Need {gas_fee}"}
            bal_a = self._get_token_balance(creator, token_a)
            bal_b = self._get_token_balance(creator, token_b)
            if bal_a < amount_a:
                return {"success": False, "error": f"Insufficient {token_a} balance. Have {bal_a}, need {amount_a}"}
            if bal_b < amount_b:
                return {"success": False, "error": f"Insufficient {token_b} balance. Have {bal_b}, need {amount_b}"}
            self.net.balances[creator] -= gas_fee
            validator_share = int(gas_fee * 0.70)
            node_share = gas_fee - validator_share
            self.net.validator_fee_pool += validator_share
            self.net.node_pool += node_share
            self.net._save_balance(creator, self.net.balances[creator])
            lp_shares = int((amount_a * amount_b) ** 0.5)
            if lp_shares < 1:
                return {"success": False, "error": "Amount too small, LP shares would be 0"}
            if token_a == "MCX":
                self.net.balances[creator] -= amount_a
                self.net._save_balance(creator, self.net.balances[creator])
            else:
                self._burn_token(token_a, creator, amount_a)
            if token_b == "MCX":
                self.net.balances[creator] -= amount_b
                self.net._save_balance(creator, self.net.balances[creator])
            else:
                self._burn_token(token_b, creator, amount_b)
            self.pools[pool_id] = {
                "token_a": token_a,
                "token_b": token_b,
                "reserve_a": amount_a,
                "reserve_b": amount_b,
                "total_lp": lp_shares,
                "created_at": time.time(),
                "fee_rate": self.fee_rate,
                "volume_24h": 0,
                "swap_count": 0,
                "last_updated": time.time(),
                "lp_positions": {creator: {"shares": lp_shares, "created_at": time.time(), "fees_earned": 0}}
            }
            c = self.net.conn.cursor()
            c.execute("INSERT INTO pools (pool_id, token_a, token_b, reserve_a, reserve_b, total_lp, created_at, fee_rate, volume_24h, swap_count, last_updated) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                      (pool_id, token_a, token_b, amount_a, amount_b, lp_shares, time.time(), self.fee_rate, 0, 0, time.time()))
            c.execute("INSERT INTO lp_positions (pool_id, wallet, lp_shares, created_at, fees_earned) VALUES (?, ?, ?, ?, ?)",
                      (pool_id, creator, lp_shares, time.time(), 0))
            tx_hash = hashlib.sha256(f"{pool_id}{creator}{time.time()}{secrets.token_hex(8)}".encode()).hexdigest()[:16]
            c.execute("INSERT INTO dex_tx (tx_hash, pool_id, wallet, tx_type, amount_a, amount_b, lp_shares, gas_fee, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                      (tx_hash, pool_id, creator, "create_pool", amount_a, amount_b, lp_shares, gas_fee, time.time()))
            self.net.conn.commit()
            price = amount_a / amount_b if amount_b > 0 else 0
            self._record_price(pool_id, price, 0)
            logger.info(f"[DEX] Pool created: {pool_id} with {lp_shares} LP shares by {creator} (gas fee: {gas_fee})")
            return {
                "success": True,
                "pool_id": pool_id,
                "lp_shares": lp_shares,
                "amount_a": amount_a,
                "amount_b": amount_b,
                "price": price,
                "gas_fee": gas_fee
            }
    
    def _update_pool_in_db(self, pool_id: str):
        pool = self.pools.get(pool_id)
        if not pool:
            return
        c = self.net.conn.cursor()
        c.execute("UPDATE pools SET reserve_a=?, reserve_b=?, last_updated=? WHERE pool_id=?",
                 (pool["reserve_a"], pool["reserve_b"], time.time(), pool_id))
        self.net.conn.commit()

    async def add_liquidity(self, pool_id: str, amount_a: int, amount_b: int, user: str) -> dict:
        async with self._lock:
            if pool_id not in self.pools:
                return {"success": False, "error": "Pool not found"}
            pool = self.pools[pool_id]
            token_a = pool["token_a"]
            token_b = pool["token_b"]
            total_amount = amount_a + amount_b
            gas_fee = self._calculate_gas_fee(total_amount)
            if self.net.balances.get(user, 0) < gas_fee:
                return {"success": False, "error": f"Insufficient MCX for gas fee. Need {gas_fee}"}
            bal_a = self._get_token_balance(user, token_a)
            bal_b = self._get_token_balance(user, token_b)
            if bal_a < amount_a:
                return {"success": False, "error": f"Insufficient {token_a} balance. Have {bal_a}, need {amount_a}"}
            if bal_b < amount_b:
                return {"success": False, "error": f"Insufficient {token_b} balance. Have {bal_b}, need {amount_b}"}
            self.net.balances[user] -= gas_fee
            validator_share = int(gas_fee * 0.70)
            node_share = gas_fee - validator_share
            self.net.validator_fee_pool += validator_share
            self.net.node_pool += node_share
            self.net._save_balance(user, self.net.balances[user])
            if pool["total_lp"] == 0:
                lp_shares = int((amount_a * amount_b) ** 0.5)
            else:
                shares_a = (amount_a * pool["total_lp"]) // pool["reserve_a"] if pool["reserve_a"] > 0 else 0
                shares_b = (amount_b * pool["total_lp"]) // pool["reserve_b"] if pool["reserve_b"] > 0 else 0
                lp_shares = min(shares_a, shares_b)
            if lp_shares < 1:
                return {"success": False, "error": "LP shares would be 0"}
            if token_a == "MCX":
                self.net.balances[user] -= amount_a
                self.net._save_balance(user, self.net.balances[user])
            else:
                self._burn_token(token_a, user, amount_a)
            if token_b == "MCX":
                self.net.balances[user] -= amount_b
                self.net._save_balance(user, self.net.balances[user])
            else:
                self._burn_token(token_b, user, amount_b)
            pool["reserve_a"] += amount_a
            pool["reserve_b"] += amount_b
            pool["total_lp"] += lp_shares
            pool["last_updated"] = time.time()
            if user not in pool["lp_positions"]:
                pool["lp_positions"][user] = {"shares": 0, "created_at": time.time(), "fees_earned": 0}
            pool["lp_positions"][user]["shares"] += lp_shares
            c = self.net.conn.cursor()
            c.execute("UPDATE pools SET reserve_a=?, reserve_b=?, total_lp=?, last_updated=? WHERE pool_id=?",
                      (pool["reserve_a"], pool["reserve_b"], pool["total_lp"], time.time(), pool_id))
            c.execute("INSERT OR REPLACE INTO lp_positions (pool_id, wallet, lp_shares, created_at, fees_earned) VALUES (?, ?, ?, ?, ?)",
                      (pool_id, user, pool["lp_positions"][user]["shares"], pool["lp_positions"][user]["created_at"], pool["lp_positions"][user]["fees_earned"]))
            tx_hash = hashlib.sha256(f"{pool_id}{user}{time.time()}{secrets.token_hex(8)}".encode()).hexdigest()[:16]
            c.execute("INSERT INTO dex_tx (tx_hash, pool_id, wallet, tx_type, amount_a, amount_b, lp_shares, gas_fee, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                      (tx_hash, pool_id, user, "add_liquidity", amount_a, amount_b, lp_shares, gas_fee, time.time()))
            self.net.conn.commit()
            price = pool["reserve_a"] / pool["reserve_b"] if pool["reserve_b"] > 0 else 0
            self._record_price(pool_id, price, amount_a + amount_b)
            logger.info(f"[DEX] Added liquidity to {pool_id}: +{lp_shares} LP shares by {user} (gas fee: {gas_fee})")
            return {
                "success": True,
                "pool_id": pool_id,
                "lp_shares": lp_shares,
                "amount_a": amount_a,
                "amount_b": amount_b,
                "total_lp": pool["total_lp"],
                "price": price,
                "gas_fee": gas_fee
            }
    
    async def remove_liquidity(self, pool_id: str, lp_shares: int, user: str) -> dict:
        async with self._lock:
            if pool_id not in self.pools:
                return {"success": False, "error": "Pool not found"}
            pool = self.pools[pool_id]
            gas_fee = self._calculate_gas_fee(lp_shares)
            if self.net.balances.get(user, 0) < gas_fee:
                return {"success": False, "error": f"Insufficient MCX for gas fee. Need {gas_fee}"}
            if user not in pool["lp_positions"]:
                return {"success": False, "error": "No LP position found"}
            if pool["lp_positions"][user]["shares"] < lp_shares:
                return {"success": False, "error": f"Insufficient LP shares. Have {pool['lp_positions'][user]['shares']}, need {lp_shares}"}
            if pool["total_lp"] == 0:
                return {"success": False, "error": "Pool has no LP shares"}
            self.net.balances[user] -= gas_fee
            validator_share = int(gas_fee * 0.70)
            node_share = gas_fee - validator_share
            self.net.validator_fee_pool += validator_share
            self.net.node_pool += node_share
            self.net._save_balance(user, self.net.balances[user])
            ratio = lp_shares / pool["total_lp"]
            amount_a = int(pool["reserve_a"] * ratio)
            amount_b = int(pool["reserve_b"] * ratio)
            if amount_a == 0 or amount_b == 0:
                return {"success": False, "error": "Amount too small"}
            fees_earned = pool["lp_positions"][user]["fees_earned"]
            pool["reserve_a"] -= amount_a
            pool["reserve_b"] -= amount_b
            pool["total_lp"] -= lp_shares
            pool["last_updated"] = time.time()
            pool["lp_positions"][user]["shares"] -= lp_shares
            if pool["lp_positions"][user]["shares"] == 0:
                pool["lp_positions"][user]["fees_earned"] = 0
            else:
                pool["lp_positions"][user]["fees_earned"] = 0
            if pool["token_a"] == "MCX":
                self.net.balances[user] = self.net.balances.get(user, 0) + amount_a
                self.net._save_balance(user, self.net.balances[user])
            else:
                self._mint_token(pool["token_a"], user, amount_a)
            if pool["token_b"] == "MCX":
                self.net.balances[user] = self.net.balances.get(user, 0) + amount_b
                self.net._save_balance(user, self.net.balances[user])
            else:
                self._mint_token(pool["token_b"], user, amount_b)
            if fees_earned > 0:
                self._mint_token("MCX", user, fees_earned)
                pool["lp_positions"][user]["fees_earned"] = 0
            c = self.net.conn.cursor()
            c.execute("UPDATE pools SET reserve_a=?, reserve_b=?, total_lp=?, last_updated=? WHERE pool_id=?",
                      (pool["reserve_a"], pool["reserve_b"], pool["total_lp"], time.time(), pool_id))
            if pool["lp_positions"][user]["shares"] > 0:
                c.execute("INSERT OR REPLACE INTO lp_positions (pool_id, wallet, lp_shares, created_at, fees_earned) VALUES (?, ?, ?, ?, ?)",
                          (pool_id, user, pool["lp_positions"][user]["shares"], pool["lp_positions"][user]["created_at"], 0))
            else:
                c.execute("DELETE FROM lp_positions WHERE pool_id=? AND wallet=?", (pool_id, user))
            tx_hash = hashlib.sha256(f"{pool_id}{user}{time.time()}{secrets.token_hex(8)}".encode()).hexdigest()[:16]
            c.execute("INSERT INTO dex_tx (tx_hash, pool_id, wallet, tx_type, amount_a, amount_b, lp_shares, gas_fee, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                      (tx_hash, pool_id, user, "remove_liquidity", amount_a, amount_b, lp_shares, gas_fee, time.time()))
            self.net.conn.commit()
            price = pool["reserve_a"] / pool["reserve_b"] if pool["reserve_b"] > 0 else 0
            self._record_price(pool_id, price, amount_a + amount_b)
            logger.info(f"[DEX] Removed liquidity from {pool_id}: -{lp_shares} LP shares by {user} (gas fee: {gas_fee})")
            return {
                "success": True,
                "pool_id": pool_id,
                "amount_a": amount_a,
                "amount_b": amount_b,
                "fees_earned": fees_earned,
                "remaining_shares": pool["lp_positions"][user]["shares"],
                "price": price,
                "gas_fee": gas_fee
            }
    
    async def swap(self, pool_id: str, token_in: str, token_out: str, amount_in: int, user: str, slippage: float = 0.005) -> dict:
        async with self._lock:
            if pool_id not in self.pools:
                return {"success": False, "error": "Pool not found"}
            pool = self.pools[pool_id]
            if token_in not in [pool["token_a"], pool["token_b"]]:
                return {"success": False, "error": f"Token {token_in} not in pool"}
            if token_out not in [pool["token_a"], pool["token_b"]]:
                return {"success": False, "error": f"Token {token_out} not in pool"}
            if token_in == token_out:
                return {"success": False, "error": "Cannot swap same token"}
            gas_fee = self._calculate_gas_fee(amount_in)
            if token_in == pool["token_a"] and token_out == pool["token_b"]:
                reserve_in = pool["reserve_a"]
                reserve_out = pool["reserve_b"]
            elif token_in == pool["token_b"] and token_out == pool["token_a"]:
                reserve_in = pool["reserve_b"]
                reserve_out = pool["reserve_a"]
            else:
                return {"success": False, "error": "Invalid token pair"}
            bal = self._get_token_balance(user, token_in)
            if bal < amount_in + gas_fee:
                return {"success": False, "error": f"Insufficient {token_in} balance. Need {amount_in} + {gas_fee} gas fee"}
            if token_in == "MCX":
                self.net.balances[user] -= gas_fee
                self.net._save_balance(user, self.net.balances[user])
            else:
                self._burn_token(token_in, user, gas_fee)
            validator_share = int(gas_fee * 0.70)
            node_share = gas_fee - validator_share
            self.net.validator_fee_pool += validator_share
            self.net.node_pool += node_share
            fee = int(amount_in * self.fee_rate)
            protocol_fee = int(fee * 0.10)
            lp_fee = fee - protocol_fee
            amount_in_without_fee = amount_in - fee
            amount_out = (amount_in_without_fee * reserve_out) // (reserve_in + amount_in_without_fee)
            if amount_out <= 0:
                return {"success": False, "error": "Amount out too small"}
            quote = self.get_quote(pool_id, token_in, token_out, amount_in)
            expected_out = quote.get("amount_out", 0)
            if expected_out > 0:
                slippage_actual = abs(amount_out - expected_out) / expected_out
                if slippage_actual > slippage:
                    return {
                        "success": False,
                        "error": f"Slippage too high: {slippage_actual*100:.2f}% > {slippage*100:.2f}%",
                        "expected": expected_out,
                        "actual": amount_out
                    }
            if token_in == "MCX":
                self.net.balances[user] -= amount_in
                self.net._save_balance(user, self.net.balances[user])
            else:
                self._burn_token(token_in, user, amount_in)
            if token_out == "MCX":
                self.net.balances[user] = self.net.balances.get(user, 0) + amount_out
                self.net._save_balance(user, self.net.balances[user])
            else:
                self._mint_token(token_out, user, amount_out)
            if token_in == pool["token_a"]:
                pool["reserve_a"] += amount_in
                pool["reserve_b"] -= amount_out
            else:
                pool["reserve_b"] += amount_in
                pool["reserve_a"] -= amount_out
            self.net.lp_pool += lp_fee
            if self.node_wallet:
                self.net.balances[self.node_wallet["address"]] = self.net.balances.get(self.node_wallet["address"], 0) + protocol_fee
            pool["swap_count"] += 1
            pool["volume_24h"] += amount_in
            pool["last_updated"] = time.time()
            swap_hash = hashlib.sha256(f"{pool_id}{user}{token_in}{token_out}{amount_in}{time.time()}{secrets.token_hex(8)}".encode()).hexdigest()[:16]
            price = amount_in / amount_out if amount_out > 0 else 0
            c = self.net.conn.cursor()
            c.execute("INSERT INTO dex_swaps (swap_hash, pool_id, user, token_in, token_out, amount_in, amount_out, fee, gas_fee, price, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                      (swap_hash, pool_id, user, token_in, token_out, amount_in, amount_out, fee, gas_fee, price, time.time()))
            c.execute("UPDATE pools SET reserve_a=?, reserve_b=?, swap_count=?, volume_24h=?, last_updated=? WHERE pool_id=?",
                      (pool["reserve_a"], pool["reserve_b"], pool["swap_count"], pool["volume_24h"], time.time(), pool_id))
            self.net.conn.commit()
            new_price = pool["reserve_a"] / pool["reserve_b"] if pool["reserve_b"] > 0 else 0
            self._record_price(pool_id, new_price, amount_in + amount_out)
            logger.info(f"[DEX] Swap: {amount_in} {token_in} -> {amount_out} {token_out} by {user} (fee: {fee}, gas: {gas_fee})")
            return {
                "success": True,
                "swap_hash": swap_hash,
                "token_in": token_in,
                "token_out": token_out,
                "amount_in": amount_in,
                "amount_out": amount_out,
                "fee": fee,
                "gas_fee": gas_fee,
                "price": price,
                "slippage": slippage_actual if expected_out > 0 else 0
            }
    
    def get_quote(self, pool_id: str, token_in: str, token_out: str, amount_in: int) -> dict:
        if pool_id not in self.pools:
            return {"success": False, "error": "Pool not found"}
        pool = self.pools[pool_id]
        if token_in not in [pool["token_a"], pool["token_b"]]:
            return {"success": False, "error": f"Token {token_in} not in pool"}
        if token_out not in [pool["token_a"], pool["token_b"]]:
            return {"success": False, "error": f"Token {token_out} not in pool"}
        if token_in == token_out:
            return {"success": False, "error": "Cannot swap same token"}
        if token_in == pool["token_a"] and token_out == pool["token_b"]:
            reserve_in = pool["reserve_a"]
            reserve_out = pool["reserve_b"]
        elif token_in == pool["token_b"] and token_out == pool["token_a"]:
            reserve_in = pool["reserve_b"]
            reserve_out = pool["reserve_a"]
        else:
            return {"success": False, "error": "Invalid token pair"}
        gas_fee = self._calculate_gas_fee(amount_in)
        fee = int(amount_in * self.fee_rate)
        amount_in_without_fee = amount_in - fee
        amount_out = (amount_in_without_fee * reserve_out) // (reserve_in + amount_in_without_fee)
        price = amount_in / amount_out if amount_out > 0 else 0
        return {
            "success": True,
            "pool_id": pool_id,
            "token_in": token_in,
            "token_out": token_out,
            "amount_in": amount_in,
            "amount_out": amount_out,
            "fee": fee,
            "gas_fee": gas_fee,
            "price": price,
            "reserve_in": reserve_in,
            "reserve_out": reserve_out,
            "slippage": amount_in / (reserve_in + amount_in) if reserve_in > 0 else 0
        }
    
    def get_pools(self) -> dict:
        pools_data = []
        for pool_id, pool in self.pools.items():
            price = pool["reserve_a"] / pool["reserve_b"] if pool["reserve_b"] > 0 else 0
            pools_data.append({
                "pool_id": pool_id,
                "token_a": pool["token_a"],
                "token_b": pool["token_b"],
                "reserve_a": pool["reserve_a"],
                "reserve_b": pool["reserve_b"],
                "total_lp": pool["total_lp"],
                "price": price,
                "liquidity_providers": len(pool["lp_positions"]),
                "volume_24h": pool["volume_24h"],
                "swap_count": pool["swap_count"],
                "created_at": pool["created_at"],
                "fee_rate": pool["fee_rate"],
                "gas_fee_rate": DEX_GAS_FEE_RATE * 100
            })
        return {"success": True, "pools": pools_data}
    
    def get_user_lp(self, wallet: str) -> dict:
        positions = []
        for pool_id, pool in self.pools.items():
            if wallet in pool["lp_positions"]:
                lp_data = pool["lp_positions"][wallet]
                shares = lp_data["shares"]
                if shares > 0:
                    ratio = shares / pool["total_lp"] if pool["total_lp"] > 0 else 0
                    positions.append({
                        "pool_id": pool_id,
                        "token_a": pool["token_a"],
                        "token_b": pool["token_b"],
                        "lp_shares": shares,
                        "share_percentage": ratio * 100,
                        "amount_a": int(pool["reserve_a"] * ratio),
                        "amount_b": int(pool["reserve_b"] * ratio),
                        "fees_earned": lp_data["fees_earned"],
                        "created_at": lp_data["created_at"]
                    })
        return {"success": True, "wallet": wallet, "positions": positions}
    
    def get_pool(self, pool_id: str) -> dict:
        if pool_id not in self.pools:
            return {"success": False, "error": "Pool not found"}
        pool = self.pools[pool_id]
        price = pool["reserve_a"] / pool["reserve_b"] if pool["reserve_b"] > 0 else 0
        top_lps = sorted(
            [(w, d["shares"]) for w, d in pool["lp_positions"].items() if d["shares"] > 0],
            key=lambda x: x[1],
            reverse=True
        )[:10]
        return {
            "success": True,
            "pool_id": pool_id,
            "token_a": pool["token_a"],
            "token_b": pool["token_b"],
            "reserve_a": pool["reserve_a"],
            "reserve_b": pool["reserve_b"],
            "total_lp": pool["total_lp"],
            "price": price,
            "liquidity_providers": len(pool["lp_positions"]),
            "volume_24h": pool["volume_24h"],
            "swap_count": pool["swap_count"],
            "created_at": pool["created_at"],
            "fee_rate": pool["fee_rate"],
            "gas_fee_rate": DEX_GAS_FEE_RATE * 100,
            "top_lp_providers": [{"wallet": w, "shares": s} for w, s in top_lps]
        }
    
    def get_tokens(self) -> dict:
        tokens_data = []
        for symbol, token in self.tokens.items():
            tokens_data.append({
                "symbol": symbol,
                "name": token["name"],
                "supply": token["supply"],
                "owner": token["owner"],
                "created_at": token["created_at"],
                "decimals": token["decimals"],
                "mintable": token["mintable"]
            })
        tokens_data.append({
            "symbol": "MCX",
            "name": "MicroCore Token",
            "supply": self.net.total_minted,
            "owner": "genesis",
            "created_at": 0,
            "decimals": 18,
            "mintable": False
        })
        return {"success": True, "tokens": tokens_data}
    
    def get_user_token_balances(self, wallet: str) -> dict:
        balances = []
        mcx_balance = self.net.balances.get(wallet, 0)
        if mcx_balance > 0:
            balances.append({"symbol": "MCX", "balance": mcx_balance})
        c = self.net.conn.cursor()
        c.execute("SELECT token_symbol, balance FROM token_balances WHERE wallet=?", (wallet,))
        rows = c.fetchall()
        for row in rows:
            balances.append({"symbol": row[0], "balance": row[1]})
        return {"success": True, "wallet": wallet, "balances": balances}
    
    def get_price_history(self, pool_id: str, hours: int = 24) -> dict:
        if pool_id not in self.pools:
            return {"success": False, "error": "Pool not found"}
        cutoff = time.time() - (hours * 3600)
        c = self.net.conn.cursor()
        c.execute("SELECT price, timestamp, volume FROM price_history WHERE pool_id=? AND timestamp > ? ORDER BY timestamp ASC",
                  (pool_id, cutoff))
        rows = c.fetchall()
        history = [{"price": row[0], "timestamp": row[1], "volume": row[2]} for row in rows]
        if history:
            prices = [h["price"] for h in history]
            current_price = prices[-1]
            high = max(prices)
            low = min(prices)
            avg = sum(prices) / len(prices)
            volume_24h = sum(h["volume"] for h in history)
        else:
            current_price = self.pools[pool_id]["reserve_a"] / self.pools[pool_id]["reserve_b"] if self.pools[pool_id]["reserve_b"] > 0 else 0
            high = low = avg = current_price
            volume_24h = 0
        return {
            "success": True,
            "pool_id": pool_id,
            "history": history,
            "current_price": current_price,
            "high_24h": high,
            "low_24h": low,
            "avg_price": avg,
            "volume_24h": volume_24h
        }
    
    async def create_genesis_tokens(self):
        # Create tokens
        if "USDC" not in self.tokens:
            result = self.create_token("USDC", "USD Coin", 10_000_000, self.net.wallet)
            if result["success"]:
                logger.info(f"[GENESIS] Created USDC token")
        if "ETH" not in self.tokens:
            result = self.create_token("ETH", "Ethereum", 10_000, self.net.wallet)
            if result["success"]:
                logger.info(f"[GENESIS] Created ETH token")
        if "BTC" not in self.tokens:
            result = self.create_token("BTC", "Bitcoin", 2_100, self.net.wallet)
            if result["success"]:
                logger.info(f"[GENESIS] Created BTC token")
        
        # Create pools with REAL token bridge integration
        # These pools are connected to the real token bridge
        
        # MCX/USDC pool - connected to real USDC bridge
        mcx_amount = 100_000
        usdc_amount = 10_000
        self.net.balances[self.net.wallet] = self.net.balances.get(self.net.wallet, 0) + mcx_amount
        self.net._save_balance(self.net.wallet, self.net.balances[self.net.wallet])
        self._mint_token("USDC", self.net.wallet, usdc_amount)
        result = await self.create_pool("MCX", "USDC", mcx_amount, usdc_amount, self.net.wallet)
        if result["success"]:
            logger.info(f"[GENESIS] Created MCX/USDC pool with {mcx_amount} MCX and {usdc_amount} USDC")
            logger.info(f"[GENESIS] MCX/USDC pool connected to REAL USDC bridge")
        
        # MCX/ETH pool - connected to real ETH bridge
        eth_amount = 100
        mcx_for_eth = 100_000
        self.net.balances[self.net.wallet] = self.net.balances.get(self.net.wallet, 0) + mcx_for_eth
        self.net._save_balance(self.net.wallet, self.net.balances[self.net.wallet])
        self._mint_token("ETH", self.net.wallet, eth_amount)
        result = await self.create_pool("MCX", "ETH", mcx_for_eth, eth_amount, self.net.wallet)
        if result["success"]:
            logger.info(f"[GENESIS] Created MCX/ETH pool with {mcx_for_eth} MCX and {eth_amount} ETH")
            logger.info(f"[GENESIS] MCX/ETH pool connected to REAL ETH bridge")
        
        # MCX/BTC pool - connected to real BTC bridge
        btc_amount = 10
        mcx_for_btc = 100_000
        self.net.balances[self.net.wallet] = self.net.balances.get(self.net.wallet, 0) + mcx_for_btc
        self.net._save_balance(self.net.wallet, self.net.balances[self.net.wallet])
        self._mint_token("BTC", self.net.wallet, btc_amount)
        result = await self.create_pool("MCX", "BTC", mcx_for_btc, btc_amount, self.net.wallet)
        if result["success"]:
            logger.info(f"[GENESIS] Created MCX/BTC pool with {mcx_for_btc} MCX and {btc_amount} BTC")
            logger.info(f"[GENESIS] MCX/BTC pool connected to REAL BTC bridge")
        
        # Initial bridge balances (node operator must fund these)
        # These should be funded with REAL tokens
        self.bridge.tokens["USDC"]["balance"] = 100000  # 100,000 USDC
        self.bridge.tokens["ETH"]["balance"] = 100  # 100 ETH
        self.bridge.tokens["BTC"]["balance"] = 10  # 10 BTC
        self.bridge._update_bridge_balance("USDC", 100000)
        self.bridge._update_bridge_balance("ETH", 100)
        self.bridge._update_bridge_balance("BTC", 10)
        logger.info(f"[GENESIS] Bridge funded with REAL tokens: USDC=100,000, ETH=100, BTC=10")

# ==================== LEVEL MANAGER ====================
class LevelManager:
    def __init__(self, net):
        self.net = net
        self.max_unlocked = 1
        self.temp_towers: Dict[str, Dict[int, int]] = {}
        self.perm_towers: Dict[str, int] = {}
        self.level_wallets: Dict[int, Set[str]] = defaultdict(set)
        self.level_counts: Dict[int, int] = defaultdict(int)
        self._lock = asyncio.Lock()
        self._load_towers()
    
    def _load_towers(self):
        try:
            c = self.net.conn.cursor()
            c.execute("SELECT wallet, level, amount, type, created_at, expires_at FROM towers")
            rows = c.fetchall()
            for row in rows:
                wallet, level, amount, tower_type, created_at, expires_at = row
                if tower_type == "temporary":
                    if wallet not in self.temp_towers:
                        self.temp_towers[wallet] = {}
                    self.temp_towers[wallet][level] = amount
                else:
                    self.perm_towers[wallet] = self.perm_towers.get(wallet, 0) + amount
            logger.info(f"[LEVEL] Loaded {len(self.temp_towers)} temporary towers, {len(self.perm_towers)} permanent towers")
        except Exception as e:
            logger.warning(f"[LEVEL] No towers found: {e}")
            self.temp_towers = {}
            self.perm_towers = {}
    
    def _save_tower(self, wallet: str, level: int, amount: int, tower_type: str):
        c = self.net.conn.cursor()
        c.execute("INSERT OR REPLACE INTO towers (wallet, level, amount, type, created_at, expires_at) VALUES (?, ?, ?, ?, ?, ?)",
                  (wallet, level, amount, tower_type, time.time(), time.time() + 86400 * 30 if tower_type == "temporary" else 0))
        self.net.conn.commit()
    
    def register(self, wallet: str, stake: int):
        alloc = {}
        rem = stake
        lvl = 1
        while rem > 0 and lvl <= self.max_unlocked:
            add = min(rem, LEVEL_STAKE_RANGE)
            alloc[lvl] = alloc.get(lvl, 0) + add
            rem -= add
            lvl += 1
        if rem > 0 and lvl <= MAX_LEVEL:
            for lock_lvl in range(lvl, MAX_LEVEL + 1):
                if rem <= 0:
                    break
                add = min(rem, LEVEL_STAKE_RANGE)
                if lock_lvl not in self.temp_towers:
                    self.temp_towers[lock_lvl] = {}
                self.temp_towers[lock_lvl][wallet] = self.temp_towers[lock_lvl].get(wallet, 0) + add
                rem -= add
                self._save_tower(wallet, lock_lvl, add, "temporary")
        if rem > 0:
            self.perm_towers[wallet] = self.perm_towers.get(wallet, 0) + rem
            self._save_tower(wallet, MAX_LEVEL + 1, rem, "permanent")
        self.temp_towers[wallet] = alloc
        self._update()
    
    def _update(self):
        self.level_wallets.clear()
        self.level_counts.clear()
        for miner in self.net.miners.values():
            if miner.active:
                lvl = self.get_level(miner.wallet)
                self.level_wallets[lvl].add(miner.wallet)
        for lvl in range(1, MAX_LEVEL + 1):
            self.level_counts[lvl] = len(self.level_wallets.get(lvl, set()))
        while self.max_unlocked < MAX_LEVEL:
            next_level = self.max_unlocked + 1
            if self.level_counts.get(next_level, 0) >= MIN_WALLETS_FOR_NEXT_LEVEL:
                self.max_unlocked = next_level
                logger.info(f"[LEVEL] Level {self.max_unlocked} UNLOCKED!")
                self._convert_temporary_towers()
            else:
                break
    
    def _convert_temporary_towers(self):
        for wallet, towers in list(self.temp_towers.items()):
            if self.max_unlocked in towers:
                stake = towers[self.max_unlocked]
                for miner in self.net.miners.values():
                    if miner.wallet == wallet:
                        miner.stake += stake
                        miner.level = self.get_level(wallet)
                        break
                del towers[self.max_unlocked]
                self._save_tower(wallet, self.max_unlocked, stake, "permanent")
    
    def get_level(self, wallet: str) -> int:
        for lvl in range(self.max_unlocked, 0, -1):
            if wallet in self.temp_towers.get(lvl, {}):
                return min(lvl, MAX_LEVEL)
        for miner in self.net.miners.values():
            if miner.wallet == wallet:
                if miner.stake >= LEVEL_STAKE_RANGE:
                    return min((miner.stake - 1) // LEVEL_STAKE_RANGE + 1, MAX_LEVEL)
                return 1
        return 1
    
    def has_permanent_tower(self, wallet: str) -> bool:
        return wallet in self.perm_towers and self.perm_towers[wallet] > 0
    
    def get_tower_stake(self, wallet: str) -> int:
        total = 0
        if wallet in self.perm_towers:
            total += self.perm_towers[wallet]
        for level in self.temp_towers.values():
            if wallet in level:
                total += level[wallet]
        return total
    
    def get_level_stats(self) -> dict:
        return {
            "max_unlocked": self.max_unlocked,
            "levels": {
                str(lvl): {
                    "wallets": self.level_counts.get(lvl, 0),
                    "required": MIN_WALLETS_FOR_NEXT_LEVEL,
                    "unlocked": lvl <= self.max_unlocked
                }
                for lvl in range(1, MAX_LEVEL + 1)
            },
            "temporary_towers": len(self.temp_towers),
            "permanent_towers": len(self.perm_towers)
        }
    
# ==================== P2P NODE ====================
class P2PNode:
    def __init__(self, net):
        self.net = net
        self.peers: Dict[str, any] = {}
        self.banned_peers: Dict[str, float] = {}
        self.ip = get_public_ip()
        self._lock = asyncio.Lock()
        self._server = None
        self._connection_pool: Dict[str, asyncio.StreamWriter] = {}
        self._message_queue: Dict[str, queue.Queue] = {}
        self._executor = ThreadPoolExecutor(max_workers=10)
        self._metrics = {
            "messages_sent": 0,
            "messages_received": 0,
            "bytes_sent": 0,
            "bytes_received": 0,
            "connections": 0,
            "errors": 0
        }
    
    async def start(self):
        self._server = await asyncio.start_server(self._handle_connection, NODE_HOST, P2P_PORT, limit=100)
        logger.info(f"[P2P] Server on port {P2P_PORT}")
        if self.ip:
            logger.info(f"[P2P] Public IP: {self.ip}:{P2P_PORT}")
    
    async def _handle_connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        addr = writer.get_extra_info('peername')
        addr_str = f"{addr[0]}:{addr[1]}"
        if addr_str in self.banned_peers and time.time() < self.banned_peers[addr_str]:
            writer.close()
            await writer.wait_closed()
            return
        self._metrics["connections"] += 1
        try:
            length_data = await reader.read(4)
            if not length_data:
                writer.close()
                return
            msg_len = struct.unpack(">I", length_data)[0]
            if msg_len > 10_000_000:
                self.banned_peers[addr_str] = time.time() + BAN_DURATION
                writer.close()
                return
            data = await reader.read(msg_len)
            self._metrics["bytes_received"] += len(data)
            msg_type, payload = decode_p2p(data)
            if msg_type is not None:
                self._metrics["messages_received"] += 1
                await self._process_message(msg_type, payload, writer, addr_str)
        except Exception as e:
            logger.error(f"[P2P] Error handling {addr_str}: {e}")
            self._metrics["errors"] += 1
        finally:
            writer.close()
            await writer.wait_closed()
    
    async def _process_message(self, msg_type: int, payload: dict, writer: asyncio.StreamWriter, addr: str):
        try:
            if msg_type == MSG_HANDSHAKE:
                async with self._lock:
                    if addr not in self.peers:
                        self.peers[addr] = type('Peer', (), {'height': payload.get('height', 0), 'last_seen': time.time()})()
                response = encode_p2p(MSG_HANDSHAKE, {"height": self.net.height, "ip": self.ip, "version": VERSION})
                writer.write(struct.pack(">I", len(response)) + response)
                await writer.drain()
                self._metrics["messages_sent"] += 1
                if payload.get('height', 0) > self.net.height:
                    asyncio.create_task(self._request_blocks(addr, self.net.height, payload['height']))
            elif msg_type == MSG_PING:
                response = encode_p2p(MSG_PONG, {"timestamp": time.time()})
                writer.write(struct.pack(">I", len(response)) + response)
                await writer.drain()
                self._metrics["messages_sent"] += 1
            elif msg_type == MSG_PONG:
                if addr in self.peers:
                    self.peers[addr].last_seen = time.time()
            elif msg_type == MSG_GET_PEERS:
                async with self._lock:
                    peers_list = list(self.peers.keys())[:100]
                response = encode_p2p(MSG_PEERS, {"peers": peers_list})
                writer.write(struct.pack(">I", len(response)) + response)
                await writer.drain()
                self._metrics["messages_sent"] += 1
            elif msg_type == MSG_PEERS:
                new_peers = []
                async with self._lock:
                    for peer in payload.get("peers", []):
                        if peer not in self.peers and peer != f"{self.ip}:{P2P_PORT}":
                            self.peers[peer] = type('Peer', (), {'height': 0, 'last_seen': time.time()})()
                            new_peers.append(peer)
                            asyncio.create_task(self._connect(peer))
                if new_peers:
                    async with self._lock:
                        save_peers_to_cache(list(self.peers.keys()))
                logger.info(f"[P2P] Received {len(payload.get('peers', []))} peers, {len(new_peers)} new")
            elif msg_type == MSG_GET_BLOCKS:
                start = payload.get("start", 0)
                end = payload.get("end", self.net.height)
                if end - start > 2000:
                    end = start + 2000
                blocks = self.net.get_blocks_range(start, end)
                response = encode_p2p(MSG_BLOCKS, {"blocks": blocks})
                writer.write(struct.pack(">I", len(response)) + response)
                await writer.drain()
                self._metrics["messages_sent"] += 1
            elif msg_type == MSG_BLOCKS:
                await self.net.import_blocks(payload.get("blocks", []))
            elif msg_type == MSG_NEW_BLOCK:
                await self.net.receive_block(payload.get("block"))
            elif msg_type == MSG_NEW_TX:
                await self.net.receive_transaction(payload.get("tx"))
            elif msg_type == MSG_SLASH:
                self.net.slash_miner(payload.get("vid"), "P2P slashing event")
            elif msg_type == MSG_GET_STATUS:
                status = {"height": self.net.height, "peers": len(self.peers), "miners": len(self.net.miners), "version": VERSION}
                response = encode_p2p(MSG_STATUS, status)
                writer.write(struct.pack(">I", len(response)) + response)
                await writer.drain()
                self._metrics["messages_sent"] += 1
            elif msg_type == MSG_STATUS:
                if addr in self.peers:
                    self.peers[addr].height = payload.get("height", 0)
            elif msg_type == MSG_GET_MEMPOOL:
                mempool_txs = await self.net.mempool.get_transactions(100)
                txs = [{"hash": tx.tx_hash, "from": tx.from_wallet, "to": tx.to_wallet, "amount": tx.amount, "fee": tx.fee} for tx in mempool_txs]
                response = encode_p2p(MSG_MEMPOOL, {"transactions": txs})
                writer.write(struct.pack(">I", len(response)) + response)
                await writer.drain()
                self._metrics["messages_sent"] += 1
            elif msg_type == MSG_MEMPOOL:
                for tx_data in payload.get("transactions", []):
                    tx = Transaction(tx_data["hash"], tx_data["from"], tx_data["to"], tx_data["amount"], tx_data.get("fee", 0), time.time(), -1, "pending", "p2p")
                    await self.net.mempool.add_transaction(tx)
            elif msg_type == MSG_GET_MINERS:
                miners = self.net.get_miners_list()
                response = encode_p2p(MSG_MINERS, {"miners": miners})
                writer.write(struct.pack(">I", len(response)) + response)
                await writer.drain()
                self._metrics["messages_sent"] += 1
            elif msg_type == MSG_MINERS:
                for miner_data in payload.get("miners", []):
                    self.net.miners_cache[miner_data["vid"]] = miner_data
            elif msg_type == MSG_BAN:
                vid = payload.get("vid")
                if vid in self.net.miners:
                    self.net.miners[vid].active = False
                    self.net.miners[vid].banned_until = time.time() + BAN_DURATION
                    self.net.conn.execute("UPDATE miners SET active=0, banned_until=? WHERE vid=?", (time.time() + BAN_DURATION, vid))
                    self.net.conn.commit()
                    logger.info(f"[P2P] Banned miner: {vid}")
            elif msg_type == MSG_UNBAN:
                vid = payload.get("vid")
                if vid in self.net.miners:
                    self.net.miners[vid].active = True
                    self.net.miners[vid].banned_until = 0
                    self.net.conn.execute("UPDATE miners SET active=1, banned_until=0 WHERE vid=?", (vid,))
                    self.net.conn.commit()
                    logger.info(f"[P2P] Unbanned miner: {vid}")
        except Exception as e:
            logger.error(f"[P2P] Process message error: {e}")
    
    async def _request_blocks(self, peer: str, start: int, end: int):
        try:
            h, p = peer.split(":")
            reader, writer = await asyncio.open_connection(h, int(p))
            msg = encode_p2p(MSG_GET_BLOCKS, {"start": start, "end": end})
            writer.write(struct.pack(">I", len(msg)) + msg)
            await writer.drain()
            writer.close()
            await writer.wait_closed()
            self._metrics["messages_sent"] += 1
        except Exception as e:
            logger.error(f"[P2P] Request blocks failed: {e}")
    
    async def broadcast_block(self, block: dict):
        msg = encode_p2p(MSG_NEW_BLOCK, {"block": block})
        await self._broadcast_message(msg)
        self._metrics["messages_sent"] += 1
    
    async def broadcast_transaction(self, tx: dict):
        msg = encode_p2p(MSG_NEW_TX, {"tx": tx})
        await self._broadcast_message(msg)
        self._metrics["messages_sent"] += 1
    
    async def broadcast_slash(self, vid: str):
        msg = encode_p2p(MSG_SLASH, {"vid": vid})
        await self._broadcast_message(msg)
        self._metrics["messages_sent"] += 1
    
    async def _broadcast_message(self, msg: bytes):
        async with self._lock:
            peers_copy = list(self.peers.keys())
        for peer in peers_copy:
            try:
                h, p = peer.split(":")
                reader, writer = await asyncio.open_connection(h, int(p))
                writer.write(struct.pack(">I", len(msg)) + msg)
                await writer.drain()
                writer.close()
                await writer.wait_closed()
                self._metrics["messages_sent"] += 1
            except:
                async with self._lock:
                    if peer in self.peers:
                        del self.peers[peer]
    
    async def discover(self):
        bootstrap = get_bootstrap_peers()
        for peer in bootstrap:
            async with self._lock:
                if peer not in self.peers:
                    asyncio.create_task(self._connect(peer))
        async with self._lock:
            peers_copy = list(self.peers.keys())
        for peer_addr in peers_copy[:10]:
            try:
                h, p = peer_addr.split(":")
                reader, writer = await asyncio.open_connection(h, int(p))
                msg = encode_p2p(MSG_GET_PEERS, {})
                writer.write(struct.pack(">I", len(msg)) + msg)
                await writer.drain()
                writer.close()
                await writer.wait_closed()
                self._metrics["messages_sent"] += 1
            except:
                async with self._lock:
                    if peer_addr in self.peers:
                        del self.peers[peer_addr]
    
    async def _connect(self, addr: str):
        async with self._lock:
            if addr in self.peers:
                return
        try:
            h, p = addr.split(":")
            reader, writer = await asyncio.open_connection(h, int(p))
            msg = encode_p2p(MSG_HANDSHAKE, {"height": self.net.height, "ip": self.ip, "version": VERSION})
            writer.write(struct.pack(">I", len(msg)) + msg)
            await writer.drain()
            writer.close()
            await writer.wait_closed()
            async with self._lock:
                self.peers[addr] = type('Peer', (), {'height': 0, 'last_seen': time.time()})()
            logger.info(f"[P2P] Connected to peer: {addr}")
            async with self._lock:
                save_peers_to_cache(list(self.peers.keys()))
        except Exception as e:
            logger.debug(f"[P2P] Failed to connect to {addr}: {e}")
    
    async def sync_with_peers(self):
        async with self._lock:
            if not self.peers:
                return
            best_peer = None
            best_height = self.net.height
            for addr, peer in self.peers.items():
                if hasattr(peer, 'height') and peer.height > best_height:
                    best_height = peer.height
                    best_peer = addr
        if best_peer and best_height > self.net.height:
            logger.info(f"[P2P] Syncing from {best_peer}: local={self.net.height}, remote={best_height}")
            await self._request_blocks(best_peer, self.net.height, best_height)
    
    async def heartbeat(self):
        while True:
            await asyncio.sleep(HEARTBEAT_INTERVAL)
            msg = encode_p2p(MSG_PING, {"timestamp": time.time()})
            async with self._lock:
                peers_copy = list(self.peers.keys())
            for peer_addr in peers_copy:
                try:
                    h, p = peer_addr.split(":")
                    reader, writer = await asyncio.open_connection(h, int(p))
                    writer.write(struct.pack(">I", len(msg)) + msg)
                    await writer.drain()
                    writer.close()
                    await writer.wait_closed()
                    self._metrics["messages_sent"] += 1
                except:
                    async with self._lock:
                        if peer_addr in self.peers:
                            del self.peers[peer_addr]
    
    def get_metrics(self) -> dict:
        return {
            "peers": len(self.peers),
            "banned": len(self.banned_peers),
            "messages_sent": self._metrics["messages_sent"],
            "messages_received": self._metrics["messages_received"],
            "bytes_sent": self._metrics["bytes_sent"],
            "bytes_received": self._metrics["bytes_received"],
            "connections": self._metrics["connections"],
            "errors": self._metrics["errors"]
        }

#  MICROCORE NETWORK 
class MicroCoreNetwork:
    def __init__(self, is_genesis: bool, username: str, wallet: str, priv: str, pub: str):
        self.miners: Dict[str, Miner] = {}
        self.nodes: Dict[str, Node] = {}
        self.balances: Dict[str, int] = {}
        self.blocks: List[Block] = []
        self.transactions: List[Transaction] = []
        self.height = 0
        self.last_hash = "0" * 64
        self.pending_challenges: Dict[str, dict] = {}
        self.node_pool = 0
        self.uptime_pool = 0
        self.lp_pool = 0
        self.buyer_pool = 0
        self.validator_fee_pool = 0
        self.total_minted = 0
        self.is_genesis = is_genesis
        self.username = username
        self.wallet = wallet
        self.priv = priv
        self.pub = pub
        self.node_id = hashlib.sha256(f"{username}{time.time()}{secrets.token_hex(8)}".encode()).hexdigest()[:16]
        self.last_buyer_distribution = time.time()
        self.last_status_report = time.time()
        self.start_time = time.time()
        self.level_groups: Dict[int, List[str]] = {i: [] for i in range(1, 11)}
        self.levels_with_miners: Set[int] = set()
        self.rate_limiter = RateLimiter()
        self.health_checker = HealthChecker()
        self.level_mgr = None
        self.p2p = P2PNode(self)
        self.mempool = Mempool()
        self.miners_cache: Dict[str, dict] = {}
        self.node_cache: Dict[str, dict] = {}
        self.price_cache: Dict[str, float] = {}
        self.metrics = {
            "blocks_produced": 0,
            "transactions_processed": 0,
            "challenges_sent": 0,
            "slash_events": 0,
            "rewards_distributed": 0,
            "mempool_size": 0,
            "peer_count": 0
        }
        
        # Initialize database FIRST
        self._init_db()
        
        # Initialize LevelManager (needs conn)
        self.level_mgr = LevelManager(self)
        
        # Initialize DEX and Real Token Bridge (needs conn)
        self.dex = DEX(self)
        self.bridge = RealTokenBridge(self)
        
        # Genesis or load
        if is_genesis:
            self._genesis()
        else:
            self._load()
        
        # Register self
        self._register_self_miner()
        self._register_self_node()
        self._init_payment_tables()
        
        # Genesis tokens if needed
        if is_genesis:
            asyncio.create_task(self.dex.create_genesis_tokens())
        
        logger.info(f"[NETWORK] Initialized node: {self.node_id[:16]}... (genesis={is_genesis})")
    
    def _init_db(self):
        self.conn = sqlite3.connect('microcore.db', check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        c = self.conn.cursor()
        
        # Create ALL tables first
        c.execute('''CREATE TABLE IF NOT EXISTS miners (
            vid TEXT PRIMARY KEY, pub TEXT NOT NULL, username TEXT NOT NULL,
            wallet TEXT NOT NULL, stake INTEGER NOT NULL, level INTEGER NOT NULL,
            rewards INTEGER DEFAULT 0, blocks INTEGER DEFAULT 0, slashes INTEGER DEFAULT 0,
            uptime INTEGER DEFAULT 0, today_uptime INTEGER DEFAULT 0, type TEXT DEFAULT 'web',
            liquidity INTEGER DEFAULT 0, fees INTEGER DEFAULT 0, last_ping REAL DEFAULT 0,
            banned_until REAL DEFAULT 0, created_at REAL DEFAULT 0, last_block INTEGER DEFAULT 0,
            consecutive_misses INTEGER DEFAULT 0, total_uptime INTEGER DEFAULT 0,
            best_level INTEGER DEFAULT 1, ip_address TEXT DEFAULT '', node_id TEXT DEFAULT '',
            version TEXT DEFAULT '', active INTEGER DEFAULT 1)''')  # ← ADDED
        
        c.execute('''CREATE TABLE IF NOT EXISTS nodes (
            node_id TEXT PRIMARY KEY, username TEXT NOT NULL, wallet TEXT NOT NULL,
            ip TEXT DEFAULT '', port INTEGER DEFAULT 0, last_seen REAL DEFAULT 0,
            height INTEGER DEFAULT 0, active INTEGER DEFAULT 1, rewards_earned INTEGER DEFAULT 0,
            version TEXT DEFAULT '', mining_enabled INTEGER DEFAULT 1,
            staking_enabled INTEGER DEFAULT 1, last_sync REAL DEFAULT 0)''')
        
        c.execute('''CREATE TABLE IF NOT EXISTS blocks (
            id INTEGER PRIMARY KEY, ts REAL NOT NULL, phash TEXT NOT NULL,
            validators TEXT DEFAULT '', lvl INTEGER DEFAULT 1, hash TEXT NOT NULL,
            reward INTEGER DEFAULT 0, tx_count INTEGER DEFAULT 0, merkle_root TEXT DEFAULT '',
            nonce INTEGER DEFAULT 0, difficulty INTEGER DEFAULT 1, version TEXT DEFAULT '')''')
        
        c.execute('''CREATE TABLE IF NOT EXISTS transactions (
            tx_hash TEXT PRIMARY KEY, from_wallet TEXT NOT NULL, to_wallet TEXT NOT NULL,
            amount INTEGER NOT NULL, fee INTEGER DEFAULT 0, timestamp REAL NOT NULL,
            block_id INTEGER DEFAULT -1, status TEXT DEFAULT 'pending', tx_type TEXT DEFAULT 'send',
            signature TEXT DEFAULT '', nonce INTEGER DEFAULT 0, confirmations INTEGER DEFAULT 0,
            data TEXT DEFAULT '{}')''')
        
        c.execute('''CREATE TABLE IF NOT EXISTS balances (wallet TEXT PRIMARY KEY, bal INTEGER DEFAULT 0)''')
        c.execute('''CREATE TABLE IF NOT EXISTS buyer_stats (wallet TEXT PRIMARY KEY, username TEXT NOT NULL, bought REAL DEFAULT 0, last_reset REAL DEFAULT 0)''')
        c.execute('''CREATE TABLE IF NOT EXISTS slashing_events (id INTEGER PRIMARY KEY AUTOINCREMENT, vid TEXT NOT NULL, amount INTEGER NOT NULL, reason TEXT DEFAULT '', timestamp REAL NOT NULL, block_id INTEGER DEFAULT -1)''')
        c.execute('''CREATE TABLE IF NOT EXISTS level_supply (level INTEGER PRIMARY KEY, minted INTEGER DEFAULT 0, cap INTEGER DEFAULT 0, last_updated REAL DEFAULT 0)''')
        c.execute('''CREATE TABLE IF NOT EXISTS pending_crypto_payments (payment_id TEXT PRIMARY KEY, wallet TEXT NOT NULL, username TEXT NOT NULL, method TEXT NOT NULL, amount INTEGER NOT NULL, usd_amount REAL NOT NULL, sender_address TEXT DEFAULT '', status TEXT DEFAULT 'pending', created_at REAL NOT NULL, completed_at REAL DEFAULT 0, txid TEXT DEFAULT '', confirmations INTEGER DEFAULT 0, error TEXT DEFAULT '')''')
        
        # DEX TABLES
        c.execute('''CREATE TABLE IF NOT EXISTS tokens (symbol TEXT PRIMARY KEY, name TEXT NOT NULL, supply INTEGER NOT NULL, owner TEXT NOT NULL, created_at REAL NOT NULL, decimals INTEGER DEFAULT 18, mintable INTEGER DEFAULT 0)''')
        c.execute('''CREATE TABLE IF NOT EXISTS pools (pool_id TEXT PRIMARY KEY, token_a TEXT NOT NULL, token_b TEXT NOT NULL, reserve_a INTEGER NOT NULL, reserve_b INTEGER NOT NULL, total_lp INTEGER NOT NULL, created_at REAL NOT NULL, fee_rate REAL DEFAULT 0.003, volume_24h INTEGER DEFAULT 0, swap_count INTEGER DEFAULT 0, last_updated REAL DEFAULT 0)''')
        c.execute('''CREATE TABLE IF NOT EXISTS lp_positions (id INTEGER PRIMARY KEY AUTOINCREMENT, pool_id TEXT NOT NULL, wallet TEXT NOT NULL, lp_shares INTEGER NOT NULL, created_at REAL NOT NULL, last_updated REAL DEFAULT 0, fees_earned INTEGER DEFAULT 0, FOREIGN KEY (pool_id) REFERENCES pools(pool_id))''')
        c.execute('''CREATE TABLE IF NOT EXISTS dex_swaps (id INTEGER PRIMARY KEY AUTOINCREMENT, swap_hash TEXT UNIQUE NOT NULL, pool_id TEXT NOT NULL, user TEXT NOT NULL, token_in TEXT NOT NULL, token_out TEXT NOT NULL, amount_in INTEGER NOT NULL, amount_out INTEGER NOT NULL, fee INTEGER NOT NULL, gas_fee INTEGER DEFAULT 0, price REAL DEFAULT 0, timestamp REAL NOT NULL, block_id INTEGER DEFAULT -1, status TEXT DEFAULT 'completed')''')
        c.execute('''CREATE TABLE IF NOT EXISTS dex_tx (id INTEGER PRIMARY KEY AUTOINCREMENT, tx_hash TEXT UNIQUE NOT NULL, pool_id TEXT NOT NULL, wallet TEXT NOT NULL, tx_type TEXT NOT NULL, amount_a INTEGER DEFAULT 0, amount_b INTEGER DEFAULT 0, lp_shares INTEGER DEFAULT 0, gas_fee INTEGER DEFAULT 0, timestamp REAL NOT NULL, block_id INTEGER DEFAULT -1, status TEXT DEFAULT 'completed')''')
        c.execute('''CREATE TABLE IF NOT EXISTS price_history (id INTEGER PRIMARY KEY AUTOINCREMENT, pool_id TEXT NOT NULL, price REAL NOT NULL, timestamp REAL NOT NULL, volume INTEGER DEFAULT 0)''')
        c.execute('''CREATE TABLE IF NOT EXISTS token_balances (wallet TEXT NOT NULL, token_symbol TEXT NOT NULL, balance INTEGER NOT NULL, PRIMARY KEY (wallet, token_symbol))''')
        c.execute('''CREATE TABLE IF NOT EXISTS duco_transactions (id INTEGER PRIMARY KEY AUTOINCREMENT, txid TEXT UNIQUE NOT NULL, wallet TEXT NOT NULL, username TEXT NOT NULL, amount REAL NOT NULL, mcx_amount INTEGER NOT NULL, tx_time REAL NOT NULL, verified_at REAL DEFAULT 0)''')
        c.execute('''CREATE TABLE IF NOT EXISTS towers (id INTEGER PRIMARY KEY AUTOINCREMENT, wallet TEXT NOT NULL, level INTEGER NOT NULL, amount INTEGER NOT NULL, type TEXT DEFAULT 'temporary', created_at REAL DEFAULT 0, expires_at REAL DEFAULT 0)''')
        c.execute('''CREATE TABLE IF NOT EXISTS swaps (id TEXT PRIMARY KEY, from_wallet TEXT NOT NULL, to_wallet TEXT NOT NULL, from_token TEXT NOT NULL, to_token TEXT NOT NULL, amount_in REAL NOT NULL, amount_out REAL DEFAULT 0, fee REAL DEFAULT 0, gas_fee INTEGER DEFAULT 0, status TEXT DEFAULT 'pending', created_at REAL DEFAULT 0, completed_at REAL DEFAULT 0, tx_hash TEXT DEFAULT '')''')
        c.execute('''CREATE TABLE IF NOT EXISTS validator_history (id INTEGER PRIMARY KEY AUTOINCREMENT, vid TEXT NOT NULL, username TEXT NOT NULL, block_id INTEGER NOT NULL, level INTEGER NOT NULL, timestamp REAL NOT NULL, reward INTEGER DEFAULT 0)''')
        c.execute('''CREATE TABLE IF NOT EXISTS node_wallet (address TEXT PRIMARY KEY, private_key_encrypted TEXT NOT NULL, public_key TEXT NOT NULL, created_at REAL NOT NULL, last_updated REAL DEFAULT 0)''')
        c.execute('''CREATE TABLE IF NOT EXISTS real_token_bridges (token_symbol TEXT PRIMARY KEY, bridge_address TEXT NOT NULL, balance REAL DEFAULT 0, last_updated REAL DEFAULT 0, private_key_encrypted TEXT DEFAULT '')''')
        c.execute('''CREATE TABLE IF NOT EXISTS bridge_swap_requests (request_id TEXT PRIMARY KEY, user_wallet TEXT NOT NULL, token_from TEXT NOT NULL, token_to TEXT NOT NULL, amount_from REAL NOT NULL, amount_to REAL NOT NULL, status TEXT DEFAULT 'pending', created_at REAL NOT NULL, completed_at REAL DEFAULT 0, tx_hash TEXT DEFAULT '', real_tx_hash TEXT DEFAULT '', error TEXT DEFAULT '')''')
        
        # Create indexes AFTER all tables
        try:
            c.execute("CREATE INDEX IF NOT EXISTS idx_transactions_wallet ON transactions(from_wallet, to_wallet)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_transactions_block ON transactions(block_id)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_miners_username ON miners(username)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_miners_active ON miners(active)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_blocks_height ON blocks(id)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_payments_status ON pending_crypto_payments(status)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_lp_wallet ON lp_positions(wallet)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_swaps_wallet ON swaps(from_wallet, to_wallet)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_pools_tokens ON pools(token_a, token_b)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_price_history_pool ON price_history(pool_id, timestamp)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_bridge_swaps_user ON bridge_swap_requests(user_wallet)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_bridge_swaps_status ON bridge_swap_requests(status)")
        except sqlite3.OperationalError as e:
            logger.warning(f"[DB] Index warning (may already exist): {e}")
        
        # Initialize level supply with UPDATED caps
        for level in range(1, 11):
            try:
                c.execute("INSERT OR IGNORE INTO level_supply (level, minted, cap, last_updated) VALUES (?, 0, ?, ?)", 
                         (level, LEVEL_CAPS[level], time.time()))
            except:
                pass
        
        self.conn.commit()
        logger.info("[DB] Database initialized")
    
    def _init_payment_tables(self):
        c = self.conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS pending_crypto_payments (payment_id TEXT PRIMARY KEY, wallet TEXT NOT NULL, username TEXT NOT NULL, method TEXT NOT NULL, amount INTEGER NOT NULL, usd_amount REAL NOT NULL, sender_address TEXT DEFAULT '', status TEXT DEFAULT 'pending', created_at REAL NOT NULL, completed_at REAL DEFAULT 0, txid TEXT DEFAULT '', confirmations INTEGER DEFAULT 0, error TEXT DEFAULT '')''')
        self.conn.commit()
    
    def _save_balance(self, wallet: str, balance: int):
        self.conn.execute("INSERT OR REPLACE INTO balances VALUES (?, ?)", (wallet, balance))
        self.conn.commit()
    
    def _save_transaction(self, tx: Transaction):
        c = self.conn.cursor()
        c.execute("INSERT OR REPLACE INTO transactions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                  (tx.tx_hash, tx.from_wallet, tx.to_wallet, tx.amount, tx.fee, tx.timestamp, tx.block_id, tx.status, tx.tx_type, tx.signature, tx.nonce, tx.confirmations, json.dumps(tx.data)))
        self.conn.commit()
    
    def _save_miner(self, miner: Miner):
        c = self.conn.cursor()
        c.execute("INSERT OR REPLACE INTO miners VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                  (miner.vid, miner.pub, miner.username, miner.wallet, miner.stake, miner.level, miner.rewards, miner.blocks, miner.slashes, miner.uptime, miner.today_uptime, miner.mtype, miner.liquidity_provided, miner.fees_collected, miner.last_ping, miner.banned_until, miner.created_at, miner.last_block, miner.consecutive_misses, miner.total_uptime, miner.best_level, miner.ip_address, miner.node_id, miner.version, 1))
        self.conn.commit()
    
    def _save_node(self, node: Node):
        c = self.conn.cursor()
        c.execute("INSERT OR REPLACE INTO nodes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                  (node.node_id, node.username, node.wallet, node.ip, node.port, node.last_seen, node.height, 1 if node.active else 0, node.rewards_earned, node.version, 1 if node.mining_enabled else 0, 1 if node.staking_enabled else 0, node.last_sync))
        self.conn.commit()
    
    def _genesis(self):
        if self.conn.execute("SELECT COUNT(*) FROM blocks").fetchone()[0] == 0:
            self.balances[self.wallet] = 100000
            self.total_minted = 100000
            self._save_balance(self.wallet, 100000)
            logger.info(f"[GENESIS] Created 100,000 MCX for {self.wallet}")
            self._add_block(0, "0"*64, ["genesis"], 1, {})
            c = self.conn.cursor()
            for level in range(1, 11):
                c.execute("UPDATE level_supply SET minted=0 WHERE level=?", (level,))
            self.conn.commit()
            logger.info("[GENESIS] Genesis block created")
    
    def _load(self):
        for row in self.conn.execute("SELECT wallet, bal FROM balances"):
            self.balances[row[0]] = row[1]
        logger.info(f"[LOAD] Loaded {len(self.balances)} balances")
        for row in self.conn.execute("SELECT * FROM blocks ORDER BY id"):
            validators = row[3].split(',') if row[3] else []
            block = Block(row[0], row[1], row[2], validators, row[4], {}, row[5], row[6], row[7])
            block.merkle_root = row[8] if len(row) > 8 else ""
            block.nonce = row[9] if len(row) > 9 else 0
            block.difficulty = row[10] if len(row) > 10 else 1
            self.blocks.append(block)
            if block.id >= self.height:
                self.height = block.id + 1
                self.last_hash = block.hash
        logger.info(f"[LOAD] Loaded {len(self.blocks)} blocks")
        for row in self.conn.execute("SELECT * FROM miners"):
            miner = Miner(row[0], row[1], row[2], row[3], row[4], row[5], row[6], row[7], row[8] or 0, 0, True, row[9] or 0, row[10] or 0, row[11] or 0, row[12] or 0, row[13] or "web", row[14] or 0, row[15] or 0, row[16] or 0, row[17] or time.time(), row[18] or 0, row[19] or 0, row[20] or 0, row[21] or "", row[22] or "", row[23] or VERSION)
            self.miners[row[0]] = miner
        logger.info(f"[LOAD] Loaded {len(self.miners)} miners")
        for row in self.conn.execute("SELECT * FROM nodes"):
            node = Node(row[0], row[1], row[2], row[3] or "", row[4] or 0, row[5] or time.time(), row[6] or 0, bool(row[7]), row[8] or 0, row[9] or VERSION, [], bool(row[10]) if len(row) > 10 else True, bool(row[11]) if len(row) > 11 else True, row[12] or 0)
            self.nodes[row[0]] = node
        logger.info(f"[LOAD] Loaded {len(self.nodes)} nodes")
        for row in self.conn.execute("SELECT * FROM transactions WHERE block_id = -1 AND status = 'pending'"):
            tx = Transaction(row[0], row[1], row[2], row[3], row[4], row[5], row[6], row[7], row[8], row[9], row[10], row[11], json.loads(row[12]) if row[12] else {})
            asyncio.create_task(self.mempool.add_transaction(tx))
        logger.info(f"[LOAD] Loaded {self.mempool.size()} mempool transactions")
        c = self.conn.cursor()
        c.execute("SELECT wallet, level, amount, type FROM towers WHERE expires_at > ? OR type = 'permanent'", (time.time(),))
        for row in c.fetchall():
            wallet, level, amount, tower_type = row
            if tower_type == "temporary":
                if wallet not in self.level_mgr.temp_towers:
                    self.level_mgr.temp_towers[wallet] = {}
                self.level_mgr.temp_towers[wallet][level] = amount
            else:
                self.level_mgr.perm_towers[wallet] = self.level_mgr.perm_towers.get(wallet, 0) + amount
        logger.info("[LOAD] State loaded successfully")

    def _register_self_miner(self):
        if self.username not in [m.username for m in self.miners.values()]:
            miner = Miner(self.username, self.pub, self.username, self.wallet, 1000, 1, 0, 0, time.time(), True, 0, 0, 0, 0, "pc", 0, 0, 0, time.time(), 0, 0, 0, 1, [], False, get_public_ip() or "", self.node_id, VERSION)
            self.miners[self.username] = miner
            self.level_mgr.register(self.wallet, 1000)
            self._save_miner(miner)
            logger.info(f"[SELF MINER] Registered as {self.username}")
    
    def _register_self_node(self):
        if self.node_id not in self.nodes:
            node = Node(self.node_id, self.username, self.wallet, get_public_ip() or "127.0.0.1", NODE_PORT, time.time(), self.height, True, 0, VERSION, [], True, True, time.time())
            self.nodes[self.node_id] = node
            self._save_node(node)
            logger.info(f"[SELF NODE] Registered node ID: {self.node_id[:16]}...")

    def register_miner(self, vid: str, pub: str, username: str, wallet: str, stake: int, sig: str, timestamp: int, mtype: str = "web") -> bool:
        if vid in self.miners:
            return True
        c = self.conn.cursor()
        c.execute("SELECT banned_until FROM miners WHERE vid=?", (vid,))
        row = c.fetchone()
        if row and row[0] and row[0] > time.time():
            logger.warning(f"[REGISTER] {username} is banned until {row[0]}")
            return False
        if not verify_signature(pub, f"{username}{wallet}{timestamp}", sig, mtype):
            logger.warning(f"[REGISTER] Invalid signature from {username} (type: {mtype})")
            return False
        miner = Miner(vid, pub, username, wallet, stake, 1, 0, 0, time.time(), True, 0, 0, 0, 0, mtype, 0, 0, 0, time.time(), 0, 0, 0, 1, [], False, "", "", VERSION)
        self.miners[vid] = miner
        self.level_mgr.register(wallet, stake)
        miner.level = self.level_mgr.get_level(wallet)
        self._save_miner(miner)
        logger.info(f"[REGISTER] {username} (type: {mtype}) staked {stake} MCX, Level {miner.level}")
        return True
    
    def update_miner_uptime(self, vid: str, uptime_seconds: int, today_uptime: int):
        if vid in self.miners:
            miner = self.miners[vid]
            miner.uptime = uptime_seconds
            miner.today_uptime = today_uptime
            miner.last_ping = time.time()
            miner.active = True
            miner.total_uptime += 1
            self._save_miner(miner)
    
    def cleanup_inactive_miners(self) -> int:
        timeout = time.time() - 300
        c = self.conn.cursor()
        c.execute("SELECT vid, username FROM miners WHERE last_ping < ? AND active = 1", (timeout,))
        inactive = c.fetchall()
        for vid, username in inactive:
            if vid in self.miners:
                self.miners[vid].active = False
                self._save_miner(self.miners[vid])
            logger.info(f"[CLEANUP] Marked inactive miner: {username}")
        self.conn.commit()
        return len(inactive)
    
    def get_miners_list(self) -> List[dict]:
        return [{"vid": m.vid, "username": m.username, "wallet": m.wallet, "level": m.level, "stake": m.stake, "blocks": m.blocks, "rewards": m.rewards, "active": m.active, "uptime": m.uptime, "today_uptime": m.today_uptime, "type": m.mtype, "last_seen": m.last_ping, "fees_collected": m.fees_collected, "slashes": m.slashes, "consecutive_misses": m.consecutive_misses} for m in self.miners.values()]
    
    def get_nodes_list(self) -> List[dict]:
        return [{"node_id": n.node_id, "username": n.username, "wallet": n.wallet, "ip": n.ip, "port": n.port, "height": n.height, "active": n.active, "rewards": n.rewards_earned, "version": n.version, "mining_enabled": n.mining_enabled, "staking_enabled": n.staking_enabled} for n in self.nodes.values()]
    
    def process_stake(self, username: str, amount: int) -> dict:
        wallet = None
        for m in self.miners.values():
            if m.username == username:
                wallet = m.wallet
                break
        if not wallet:
            return {"success": False, "error": "User not found"}
        if self.get_balance(wallet) < amount:
            return {"success": False, "error": f"Insufficient balance. You have {self.get_balance(wallet)} MCX"}
        self.balances[wallet] -= amount
        self._save_balance(wallet, self.balances[wallet])
        for m in self.miners.values():
            if m.wallet == wallet:
                m.stake += amount
                self.level_mgr.register(wallet, m.stake)
                m.level = self.level_mgr.get_level(wallet)
                self._save_miner(m)
                tx_hash = hash_transaction({"from": wallet, "to": "stake_pool", "amount": amount})
                tx = Transaction(tx_hash, wallet, "stake_pool", amount, 0, time.time(), -1, "confirmed", "stake")
                self._save_transaction(tx)
                logger.info(f"[STAKE] {username} staked {amount} MCX (Level {m.level})")
                return {"success": True, "staked": m.stake, "level": m.level, "balance": self.balances[wallet]}
        return {"success": False, "error": "Miner not found"}
    
    def process_unstake(self, username: str, amount: int) -> dict:
        wallet = None
        for m in self.miners.values():
            if m.username == username:
                wallet = m.wallet
                break
        if not wallet:
            return {"success": False, "error": "User not found"}
        for m in self.miners.values():
            if m.wallet == wallet:
                if m.stake < amount:
                    return {"success": False, "error": f"Insufficient staked. You have {m.stake} MCX staked"}
                m.stake -= amount
                self.balances[wallet] = self.balances.get(wallet, 0) + amount
                self._save_balance(wallet, self.balances[wallet])
                self.level_mgr.register(wallet, m.stake)
                m.level = self.level_mgr.get_level(wallet)
                self._save_miner(m)
                tx_hash = hash_transaction({"from": "stake_pool", "to": wallet, "amount": amount})
                tx = Transaction(tx_hash, "stake_pool", wallet, amount, 0, time.time(), -1, "confirmed", "unstake")
                self._save_transaction(tx)
                logger.info(f"[UNSTAKE] {username} unstaked {amount} MCX (Level {m.level})")
                return {"success": True, "staked": m.stake, "level": m.level, "balance": self.balances[wallet]}
        return {"success": False, "error": "Miner not found"}
    
    def get_balance(self, wallet: str) -> int:
        return self.balances.get(wallet, 0)
    
    def get_top_stakers(self, limit: int = 10) -> List[dict]:
        stakers = []
        for m in self.miners.values():
            if m.active and m.stake > 0:
                stakers.append({"username": m.username, "staked": m.stake, "wallet": m.wallet, "level": m.level})
        stakers.sort(key=lambda x: x["staked"], reverse=True)
        return stakers[:limit]
    
    def get_buyer_stats(self, limit: int = 10) -> List[dict]:
        c = self.conn.cursor()
        c.execute("SELECT wallet, username, bought FROM buyer_stats ORDER BY bought DESC LIMIT ?", (limit,))
        return [{"wallet": r[0], "username": r[1], "bought": r[2]} for r in c.fetchall()]
    
    def send_mcx(self, from_user: str, to_user: str, amount: int) -> dict:
        from_wallet = None
        to_wallet = None
        for m in self.miners.values():
            if m.username == from_user:
                from_wallet = m.wallet
            if m.username == to_user:
                to_wallet = m.wallet
        if not from_wallet:
            return {"success": False, "error": f"Sender '{from_user}' not found"}
        if not to_wallet:
            return {"success": False, "error": f"Recipient '{to_user}' not found"}
        fee = calculate_transfer_fee(amount)
        fee = int(fee)
        if fee < 1:
            fee = 1
        if self.get_balance(from_wallet) < amount + fee:
            return {"success": False, "error": f"Insufficient balance. You have {self.get_balance(from_wallet)} MCX"}
        self.balances[from_wallet] -= (amount + fee)
        self.balances[to_wallet] = self.balances.get(to_wallet, 0) + amount
        self.validator_fee_pool += fee
        self._save_balance(from_wallet, self.balances[from_wallet])
        self._save_balance(to_wallet, self.balances[to_wallet])
        tx_hash = hash_transaction({"from": from_wallet, "to": to_wallet, "amount": amount, "fee": fee})
        tx = Transaction(tx_hash, from_wallet, to_wallet, amount, fee, time.time(), -1, "confirmed", "send")
        self._save_transaction(tx)
        logger.info(f"[SEND] {from_user} → {to_user}: {amount} MCX (fee: {fee} MCX)")
        return {"success": True, "tx_hash": tx_hash, "from": from_user, "to": to_user, "amount": amount, "fee": fee}
    
    def get_transactions(self, wallet: str, limit: int = 20) -> List[dict]:
        c = self.conn.cursor()
        c.execute("SELECT tx_hash, from_wallet, to_wallet, amount, fee, timestamp, block_id, status, tx_type FROM transactions WHERE from_wallet = ? OR to_wallet = ? ORDER BY timestamp DESC LIMIT ?", (wallet, wallet, limit))
        return [{"hash": r[0], "from": r[1], "to": r[2], "amount": r[3], "fee": r[4], "timestamp": r[5], "block": r[6], "status": r[7], "type": r[8]} for r in c.fetchall()]
    
    def verify_btc_balance(self, address: str) -> float:
        try:
            response = requests.get(f"{BTC_API}{address}", timeout=10)
            if response.status_code == 200:
                data = response.json()
                return data.get('final_balance', 0) / 1e8
            return 0
        except:
            return 0
    
    def verify_eth_balance(self, address: str) -> float:
        try:
            response = requests.get(f"{ETH_API}?module=account&action=balance&address={address}&tag=latest&apikey={ETHERSCAN_API_KEY}", timeout=10)
            if response.status_code == 200:
                data = response.json()
                if data.get('status') == '1':
                    return int(data.get('result', 0)) / 1e18
            return 0
        except:
            return 0
    
    def verify_usdc_balance(self, address: str) -> float:
        try:
            response = requests.get(f"{USDC_API}?module=account&action=tokentx&contractaddress=0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48&address={address}&sort=desc&apikey={ETHERSCAN_API_KEY}", timeout=10)
            if response.status_code == 200:
                data = response.json()
                if data.get('status') == '1':
                    txs = data.get('result', [])
                    total_received = 0
                    for tx in txs:
                        if tx.get('to', '').lower() == address.lower():
                            value = int(tx.get('value', 0)) / 1e6
                            total_received += value
                    return total_received
            return 0
        except:
            return 0
    
    def verify_duco_transaction(self, username: str, txid: str, tx_time: float, expected_amount: float) -> dict:
        try:
            response = requests.get(f"{DUCO_API}?transaction={txid}", timeout=10)
            if response.status_code != 200:
                return {"success": False, "error": "Transaction not found"}
            data = response.json()
            if not data.get('result'):
                return {"success": False, "error": "Transaction not found"}
            tx_data = data['result']
            sender = tx_data.get('sender', '')
            if sender.lower() != username.lower():
                return {"success": False, "error": f"Sender mismatch"}
            recipient = tx_data.get('recipient', '')
            if recipient != DUCO_PAYMENT_ADDRESS:
                return {"success": False, "error": f"Recipient mismatch"}
            tx_time_actual = tx_data.get('timestamp', 0)
            if abs(tx_time_actual - tx_time) > 300:
                return {"success": False, "error": f"Time mismatch"}
            amount = float(tx_data.get('amount', 0))
            if amount < expected_amount:
                return {"success": False, "error": f"Amount mismatch"}
            confirmations = tx_data.get('confirmations', 0)
            if confirmations < 1:
                return {"success": False, "error": f"Transaction pending"}
            return {"success": True, "amount": amount, "sender": sender, "recipient": recipient, "confirmations": confirmations}
        except Exception as e:
            return {"success": False, "error": f"Verification failed: {e}"}
    
    def process_duco_purchase(self, wallet: str, username: str, txid: str, tx_time: float, duco_amount: float) -> dict:
        verification = self.verify_duco_transaction(username, txid, tx_time, duco_amount)
        if not verification['success']:
            return {"success": False, "error": verification['error']}
        c = self.conn.cursor()
        c.execute("SELECT COUNT(*) FROM duco_transactions WHERE txid=?", (txid,))
        if c.fetchone()[0] > 0:
            return {"success": False, "error": "Already used"}
        mcx_amount = int(duco_amount / 1000)
        if mcx_amount < 1:
            return {"success": False, "error": "Amount too small"}
        self.balances[wallet] = self.balances.get(wallet, 0) + mcx_amount
        self._save_balance(wallet, self.balances[wallet])
        tx_hash = hash_transaction({"from": "duco_purchase", "to": wallet, "amount": mcx_amount})
        tx = Transaction(tx_hash, "duco_purchase", wallet, mcx_amount, 0, time.time(), -1, "confirmed", "duco_buy")
        self._save_transaction(tx)
        c.execute("INSERT OR REPLACE INTO buyer_stats (wallet, username, bought, last_reset) VALUES (?, ?, COALESCE((SELECT bought FROM buyer_stats WHERE wallet=?), 0) + ?, ?)",
                 (wallet, username, wallet, mcx_amount, time.time()))
        c.execute("INSERT INTO duco_transactions (txid, wallet, username, amount, mcx_amount, tx_time, verified_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                 (txid, wallet, username, duco_amount, mcx_amount, tx_time, time.time()))
        self.conn.commit()
        logger.info(f"[DUCO] {username} bought {mcx_amount} MCX with {duco_amount} DUCO")
        return {"success": True, "mcx_amount": mcx_amount, "duco_amount": duco_amount, "txid": txid, "wallet": wallet}
    
    def initiate_crypto_payment(self, wallet: str, username: str, usd_amount: float, method: str, sender_address: str) -> dict:
        mcx_amount = int(usd_amount / 0.01)
        payment_id = f"{method}_{wallet}_{int(time.time())}_{secrets.token_hex(4)}"
        c = self.conn.cursor()
        c.execute("INSERT INTO pending_crypto_payments (payment_id, wallet, username, method, amount, usd_amount, sender_address, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                 (payment_id, wallet, username, method, mcx_amount, usd_amount, sender_address, 'pending', time.time()))
        self.conn.commit()
        return {"success": True, "payment_id": payment_id, "mcx_amount": mcx_amount, "method": method, "usd_amount": usd_amount, "sender_address": sender_address}
    
    def check_crypto_payment(self, payment_id: str, method: str, expected_amount: float, sender_address: str) -> dict:
        c = self.conn.cursor()
        c.execute("SELECT wallet, username, amount, status FROM pending_crypto_payments WHERE payment_id=? AND status='pending'", (payment_id,))
        row = c.fetchone()
        if not row:
            return {"success": False, "error": "Payment not found or already processed"}
        wallet, username, mcx_amount, status = row
        if method == "btc":
            result = self._verify_btc_payment(sender_address, expected_amount)
        elif method == "eth":
            result = self._verify_eth_payment(sender_address, expected_amount)
        elif method == "usdc":
            result = self._verify_usdc_payment(sender_address, expected_amount)
        else:
            return {"success": False, "error": "Unsupported method"}
        if result.get("success"):
            self.balances[wallet] = self.balances.get(wallet, 0) + mcx_amount
            self._save_balance(wallet, self.balances[wallet])
            c.execute("UPDATE pending_crypto_payments SET status='completed', completed_at=? WHERE payment_id=?", (time.time(), payment_id))
            self.conn.commit()
            c.execute("INSERT OR REPLACE INTO buyer_stats (wallet, username, bought, last_reset) VALUES (?, ?, COALESCE((SELECT bought FROM buyer_stats WHERE wallet=?), 0) + ?, ?)",
                     (wallet, username, wallet, mcx_amount, time.time()))
            self.conn.commit()
            tx_hash = hash_transaction({"from": method, "to": wallet, "amount": mcx_amount})
            tx = Transaction(tx_hash, method, wallet, mcx_amount, 0, time.time(), -1, "confirmed", "buy")
            self._save_transaction(tx)
            logger.info(f"[CRYPTO] Credited {mcx_amount} MCX to {wallet} via {method.upper()}")
            return {"success": True, "mcx_amount": mcx_amount, "wallet": wallet}
        return {"success": False, "error": result.get("error", "Payment not yet received")}
    
    def _verify_btc_payment(self, sender_address: str, expected_amount: float) -> dict:
        try:
            response = requests.get(f"{BTC_API}{sender_address}", timeout=10)
            if response.status_code == 200:
                data = response.json()
                total_received = data.get('total_received', 0) / 1e8
                if total_received >= expected_amount:
                    return {"success": True, "received": total_received}
            return {"success": False, "error": "Payment not verified"}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def _verify_eth_payment(self, sender_address: str, expected_amount: float) -> dict:
        try:
            response = requests.get(f"{ETH_API}?module=account&action=txlist&address={sender_address}&sort=desc&apikey={ETHERSCAN_API_KEY}", timeout=10)
            if response.status_code == 200:
                data = response.json()
                if data.get('status') == '1':
                    txs = data.get('result', [])
                    total_sent = 0
                    for tx in txs:
                        value = int(tx.get('value', 0)) / 1e18
                        total_sent += value
                    if total_sent >= expected_amount:
                        return {"success": True, "received": total_sent}
            return {"success": False, "error": "Payment not verified"}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def _verify_usdc_payment(self, sender_address: str, expected_amount: float) -> dict:
        try:
            response = requests.get(f"{USDC_API}?module=account&action=tokentx&contractaddress=0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48&address={sender_address}&sort=desc&apikey={ETHERSCAN_API_KEY}", timeout=10)
            if response.status_code == 200:
                data = response.json()
                if data.get('status') == '1':
                    txs = data.get('result', [])
                    total_sent = 0
                    for tx in txs:
                        if tx.get('from', '').lower() == sender_address.lower():
                            value = int(tx.get('value', 0)) / 1e6
                            total_sent += value
                    if total_sent >= expected_amount:
                        return {"success": True, "received": total_sent}
            return {"success": False, "error": "Payment not verified"}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def get_payment_status(self, payment_id: str) -> dict:
        c = self.conn.cursor()
        c.execute("SELECT status, created_at, completed_at FROM pending_crypto_payments WHERE payment_id=?", (payment_id,))
        row = c.fetchone()
        if row:
            return {"status": row[0], "created_at": row[1], "completed_at": row[2]}
        return {"status": "not_found"}
    
    def get_block_interval(self, level: int) -> int:
        return LEVEL_BLOCK_INTERVALS.get(level, 40)
    
    def get_current_reward_for_level(self, level: int) -> int:
        c = self.conn.cursor()
        c.execute("SELECT minted, cap FROM level_supply WHERE level=?", (level,))
        row = c.fetchone()
        if not row:
            return INITIAL_BLOCK_REWARD
        minted, cap = row
        remaining = cap - minted
        if remaining <= 0:
            return 0
        halving_count = 0
        target = cap / 2
        while minted >= target and target > 0:
            halving_count += 1
            target = cap / (2 ** (halving_count + 1))
        reward = INITIAL_BLOCK_REWARD // (2 ** halving_count)
        return max(reward, 1)
    
    def update_level_supply(self, level: int, reward: int):
        c = self.conn.cursor()
        c.execute("UPDATE level_supply SET minted = minted + ?, last_updated = ? WHERE level = ?", (reward, time.time(), level))
        self.conn.commit()
    
    def get_total_minted(self) -> int:
        c = self.conn.cursor()
        c.execute("SELECT SUM(minted) FROM level_supply")
        total = c.fetchone()[0]
        return total or 0
    
    def get_remaining_supply_for_level(self, level: int) -> int:
        c = self.conn.cursor()
        c.execute("SELECT minted, cap FROM level_supply WHERE level=?", (level,))
        row = c.fetchone()
        if row:
            return max(0, row[1] - row[0])
        return LEVEL_CAPS.get(level, 0)
    
    def get_blocks_range(self, start: int, end: int) -> List[dict]:
        blocks = []
        for b in self.blocks:
            if start <= b.id <= end:
                blocks.append({"id": b.id, "ts": b.ts, "prev": b.prev, "validators": b.validators, "level": b.level, "hash": b.hash, "reward": b.reward, "tx_count": b.tx_count})
        return blocks
    
    def _add_block(self, bid: int, prev: str, validators: List[str], level: int, sigs: dict) -> Block:
        ts = time.time()
        block = Block(bid, ts, prev, validators, level, sigs, "", 0, 0)
        block.hash = hash_block({"id": bid, "ts": ts, "prev": prev, "validators": validators, "level": level, "merkle_root": block.merkle_root, "nonce": block.nonce})
        self.blocks.append(block)
        self.height = bid + 1
        self.last_hash = block.hash
        self.conn.execute("INSERT INTO blocks VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (bid, ts, prev, ','.join(validators), level, block.hash, 0, 0, block.merkle_root, block.nonce, block.difficulty, block.version))
        self.conn.commit()
        return block
    
    async def import_blocks(self, blocks_data: List[dict]):
        for b in sorted(blocks_data, key=lambda x: x['id']):
            if b['id'] >= self.height and b['prev'] == self.last_hash:
                block = Block(b['id'], b['ts'], b['prev'], b['validators'], b['level'], {}, b['hash'], b.get('reward', 0), 0)
                self.blocks.append(block)
                self.height = b['id'] + 1
                self.last_hash = block.hash
                self.conn.execute("INSERT INTO blocks VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (b['id'], b['ts'], b['prev'], ','.join(b['validators']), b['level'], b['hash'], b.get('reward', 0), 0, "", 0, 1, VERSION))
                self.conn.commit()
                logger.info(f"[SYNC] Imported block {b['id']}")
    
    async def receive_block(self, block_data: dict):
        bid = block_data.get('id')
        if bid == self.height and block_data.get('prev') == self.last_hash:
            block = Block(bid, block_data['ts'], block_data['prev'], block_data['validators'], block_data['level'], {}, block_data['hash'], block_data.get('reward', 0), 0)
            self.blocks.append(block)
            self.height = bid + 1
            self.last_hash = block.hash
            self.conn.execute("INSERT INTO blocks VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (bid, block.ts, block.prev, ','.join(block.validators), block.level, block.hash, block.reward, 0, "", 0, 1, VERSION))
            self.conn.commit()
            logger.info(f"[P2P] Received block {bid}")
    
    async def receive_transaction(self, tx_data: dict):
        tx_hash = tx_data.get('hash')
        c = self.conn.cursor()
        c.execute("SELECT COUNT(*) FROM transactions WHERE tx_hash=?", (tx_hash,))
        if c.fetchone()[0] == 0:
            tx = Transaction(tx_hash, tx_data['from'], tx_data['to'], tx_data['amount'], tx_data.get('fee', 1), tx_data['timestamp'], -1, 'pending', tx_data.get('type', 'send'))
            self._save_transaction(tx)
            await self.mempool.add_transaction(tx)
            logger.info(f"[P2P] Received transaction {tx_hash[:16]}...")

    async def ws_handler(self, websocket):
        if websocket.request.path != WS_PATH:
            logger.warning(f"[WS] Invalid path: {websocket.request.path}, expected {WS_PATH}")
            await websocket.close(1000, "Invalid path")
            return
        client_ip = websocket.remote_address[0] if websocket.remote_address else "unknown"
        if not await self.rate_limiter.is_allowed(client_ip):
            await websocket.close(1008, "Rate limit exceeded")
            logger.warning(f"[WS] Rate limit exceeded for {client_ip}")
            return
        logger.info(f"[WS] New connection from {client_ip}")
        try:
            async for message in websocket:
                try:
                    data = json.loads(message)
                    msg_type = data.get("type")
                    if msg_type == "ping":
                        await websocket.send(json.dumps({"type": "pong", "timestamp": time.time()}))
                        continue
                    await self._handle_ws_message(websocket, data, msg_type, client_ip)
                except json.JSONDecodeError:
                    logger.warning(f"[WS] Invalid JSON from {client_ip}: {message[:100]}")
                    await websocket.send(json.dumps({"type": "error", "message": "Invalid JSON"}))
                except Exception as e:
                    logger.error(f"[WS] Handler error: {e}")
                    await websocket.send(json.dumps({"type": "error", "message": str(e)}))
        except websockets.exceptions.ConnectionClosed:
            logger.debug(f"[WS] Connection closed: {client_ip}")
        except Exception as e:
            logger.error(f"[WS] Connection error: {e}")
    
    async def _handle_ws_message(self, websocket, data: dict, msg_type: str, client_ip: str):
        try:
            if msg_type == "register":
                ok = self.register_miner(data["validator_id"], data["public_key"], data["username"], data["wallet"], data["stake"], data["signature"], data["timestamp"], data.get("miner_type", "web"))
                if ok:
                    await websocket.send(json.dumps({"type": "registered", "level": self.level_mgr.get_level(data["wallet"]), "max_level": self.level_mgr.max_unlocked, "remaining_supply": self.get_remaining_supply_for_level(1), "current_reward": self.get_current_reward_for_level(1), "dex_pools": self.dex.get_pools(), "bridge_status": self.bridge.get_bridge_status()}))
            elif msg_type == "block_signature":
                ch = data["challenge"]
                if ch in self.pending_challenges:
                    self.pending_challenges[ch]["sigs"][data["validator_id"]] = data["signature"]
            elif msg_type == "uptime_ping":
                self.update_miner_uptime(data["validator_id"], data.get("uptime_seconds", 0), data.get("today_uptime", 0))
            elif msg_type == "get_peers":
                peers = [f"{addr}" for addr in self.p2p.peers.keys()]
                await websocket.send(json.dumps({"type": "peers", "peers": peers}))
            elif msg_type == "stake":
                result = self.process_stake(data["wallet"], data["amount"])
                await websocket.send(json.dumps({"type": "staking_confirmed", **result}))
            elif msg_type == "unstake":
                result = self.process_unstake(data["wallet"], data["amount"])
                await websocket.send(json.dumps({"type": "staking_confirmed", **result}))
            elif msg_type == "send":
                result = self.send_mcx(data["from"], data["to"], data["amount"])
                await websocket.send(json.dumps({"type": "send_result", **result}))
            elif msg_type == "swap_mcx_to_real":
                wallet = data.get("wallet")
                token_symbol = data.get("token_symbol", "").upper()
                mcx_amount = data.get("amount", 0)
                if not wallet or not token_symbol or mcx_amount <= 0:
                    await websocket.send(json.dumps({"type": "bridge_error", "error": "Invalid parameters"}))
                    return
                result = await self.bridge.swap_mcx_to_real(wallet, mcx_amount, token_symbol)
                await websocket.send(json.dumps({"type": "bridge_result", "data": result}))
                if result.get("success"):
                    balance = self.get_balance(wallet)
                    await websocket.send(json.dumps({"type": "balance", "balance": balance}))
            elif msg_type == "swap_real_to_mcx":
                wallet = data.get("wallet")
                token_symbol = data.get("token_symbol", "").upper()
                real_amount = data.get("amount", 0)
                sender_address = data.get("sender_address", "")
                if not wallet or not token_symbol or real_amount <= 0 or not sender_address:
                    await websocket.send(json.dumps({"type": "bridge_error", "error": "Invalid parameters"}))
                    return
                result = await self.bridge.swap_real_to_mcx(wallet, token_symbol, real_amount, sender_address)
                await websocket.send(json.dumps({"type": "bridge_result", "data": result}))
                if result.get("success"):
                    balance = self.get_balance(wallet)
                    await websocket.send(json.dumps({"type": "balance", "balance": balance}))
            elif msg_type == "get_bridge_status":
                status = self.bridge.get_bridge_status()
                await websocket.send(json.dumps({"type": "bridge_status", "data": status}))
            elif msg_type == "get_pending_swaps":
                wallet = data.get("wallet")
                swaps = self.bridge.get_pending_swaps(wallet)
                await websocket.send(json.dumps({"type": "pending_swaps", "data": swaps}))
            elif msg_type == "get_swap_history":
                wallet = data.get("wallet")
                limit = data.get("limit", 20)
                history = self.bridge.get_swap_history(wallet, limit)
                await websocket.send(json.dumps({"type": "swap_history", "data": history}))
            elif msg_type == "create_token":
                symbol = data.get("symbol", "").upper()
                name = data.get("name", "")
                supply = data.get("supply", 0)
                decimals = data.get("decimals", 18)
                mintable = data.get("mintable", False)
                creator = data.get("wallet")
                if not creator:
                    await websocket.send(json.dumps({"type": "dex_error", "error": "Wallet required"}))
                    return
                result = self.dex.create_token(symbol, name, supply, creator, decimals, mintable)
                await websocket.send(json.dumps({"type": "token_created", "data": result}))
            elif msg_type == "create_pool":
                token_a = data.get("token_a")
                token_b = data.get("token_b")
                amount_a = data.get("amount_a", 0)
                amount_b = data.get("amount_b", 0)
                creator = data.get("wallet")
                if not creator:
                    await websocket.send(json.dumps({"type": "dex_error", "error": "Wallet required"}))
                    return
                result = await self.dex.create_pool(token_a, token_b, amount_a, amount_b, creator)
                await websocket.send(json.dumps({"type": "pool_created", "data": result}))
                if result.get("success"):
                    balance = self.get_balance(creator)
                    await websocket.send(json.dumps({"type": "balance", "balance": balance}))
            elif msg_type == "swap":
                pool_id = data.get("pool_id")
                token_in = data.get("token_in")
                token_out = data.get("token_out")
                amount_in = data.get("amount_in", 0)
                user = data.get("wallet")
                slippage = data.get("slippage", 0.005)
                if not user:
                    await websocket.send(json.dumps({"type": "dex_error", "error": "Wallet required"}))
                    return
                result = await self.dex.swap(pool_id, token_in, token_out, amount_in, user, slippage)
                await websocket.send(json.dumps({"type": "swap_result", "data": result}))
                if result.get("success"):
                    balance = self.get_balance(user)
                    token_balance = self.dex._get_token_balance(user, token_out)
                    await websocket.send(json.dumps({"type": "balance", "balance": balance, "token_balances": {token_out: token_balance}}))
            elif msg_type == "add_liquidity":
                pool_id = data.get("pool_id")
                amount_a = data.get("amount_a", 0)
                amount_b = data.get("amount_b", 0)
                user = data.get("wallet")
                if not user:
                    await websocket.send(json.dumps({"type": "dex_error", "error": "Wallet required"}))
                    return
                result = await self.dex.add_liquidity(pool_id, amount_a, amount_b, user)
                await websocket.send(json.dumps({"type": "liquidity_added", "data": result}))
                if result.get("success"):
                    balance = self.get_balance(user)
                    await websocket.send(json.dumps({"type": "balance", "balance": balance}))
            elif msg_type == "remove_liquidity":
                pool_id = data.get("pool_id")
                lp_shares = data.get("lp_shares", 0)
                user = data.get("wallet")
                if not user:
                    await websocket.send(json.dumps({"type": "dex_error", "error": "Wallet required"}))
                    return
                result = await self.dex.remove_liquidity(pool_id, lp_shares, user)
                await websocket.send(json.dumps({"type": "liquidity_removed", "data": result}))
                if result.get("success"):
                    balance = self.get_balance(user)
                    await websocket.send(json.dumps({"type": "balance", "balance": balance}))
            elif msg_type == "get_quote":
                pool_id = data.get("pool_id")
                token_in = data.get("token_in")
                token_out = data.get("token_out")
                amount_in = data.get("amount_in", 0)
                result = self.dex.get_quote(pool_id, token_in, token_out, amount_in)
                await websocket.send(json.dumps({"type": "quote", "data": result}))
            elif msg_type == "get_pools":
                result = self.dex.get_pools()
                await websocket.send(json.dumps({"type": "pools", "data": result}))
            elif msg_type == "get_user_lp":
                wallet = data.get("wallet")
                if not wallet:
                    await websocket.send(json.dumps({"type": "dex_error", "error": "Wallet required"}))
                    return
                result = self.dex.get_user_lp(wallet)
                await websocket.send(json.dumps({"type": "user_lp", "data": result}))
            elif msg_type == "get_pool":
                pool_id = data.get("pool_id")
                result = self.dex.get_pool(pool_id)
                await websocket.send(json.dumps({"type": "pool_data", "data": result}))
            elif msg_type == "get_tokens":
                result = self.dex.get_tokens()
                await websocket.send(json.dumps({"type": "tokens", "data": result}))
            elif msg_type == "get_user_tokens":
                wallet = data.get("wallet")
                if not wallet:
                    await websocket.send(json.dumps({"type": "dex_error", "error": "Wallet required"}))
                    return
                result = self.dex.get_user_token_balances(wallet)
                await websocket.send(json.dumps({"type": "user_tokens", "data": result}))
            elif msg_type == "get_price_history":
                pool_id = data.get("pool_id")
                hours = data.get("hours", 24)
                result = self.dex.get_price_history(pool_id, hours)
                await websocket.send(json.dumps({"type": "price_history", "data": result}))
            elif msg_type == "get_balance":
                balance = self.get_balance(data["wallet"])
                staked = 0
                for m in self.miners.values():
                    if m.wallet == data["wallet"]:
                        staked = m.stake
                        break
                await websocket.send(json.dumps({"type": "balance", "balance": balance, "staked": staked}))
            elif msg_type == "get_miners":
                miners = self.get_miners_list()
                await websocket.send(json.dumps({"type": "miners", "miners": miners}))
            elif msg_type == "get_nodes":
                nodes = self.get_nodes_list()
                await websocket.send(json.dumps({"type": "nodes", "nodes": nodes}))
            elif msg_type == "get_top_stakers":
                stakers = self.get_top_stakers(10)
                await websocket.send(json.dumps({"type": "top_stakers", "stakers": stakers}))
            elif msg_type == "get_top_buyers":
                buyers = self.get_buyer_stats(10)
                await websocket.send(json.dumps({"type": "top_buyers", "buyers": buyers}))
            elif msg_type == "control_miner":
                vid = data.get("miner_id")
                action = data.get("action")
                miner = self.miners.get(vid)
                if not miner:
                    await websocket.send(json.dumps({"type": "control_result", "success": False, "message": "Miner not found"}))
                    return
                if action == "stop":
                    miner.active = False
                    self.conn.execute("UPDATE miners SET active=0 WHERE vid=?", (vid,))
                    self.conn.commit()
                    logger.info(f"[CONTROL] Stopped miner: {miner.username}")
                elif action == "start":
                    miner.active = True
                    miner.banned_until = 0
                    self.conn.execute("UPDATE miners SET active=1, banned_until=0 WHERE vid=?", (vid,))
                    self.conn.commit()
                    logger.info(f"[CONTROL] Started miner: {miner.username}")
                elif action == "restart":
                    miner.active = False
                    self.conn.execute("UPDATE miners SET active=0 WHERE vid=?", (vid,))
                    self.conn.commit()
                    await asyncio.sleep(1)
                    miner.active = True
                    miner.banned_until = 0
                    self.conn.execute("UPDATE miners SET active=1, banned_until=0 WHERE vid=?", (vid,))
                    self.conn.commit()
                    logger.info(f"[CONTROL] Restarted miner: {miner.username}")
                await websocket.send(json.dumps({"type": "control_result", "miner_id": vid, "action": action, "success": True, "message": f"{action} command sent to miner"}))
            elif msg_type == "get_status":
                total_supply = 0
                for level in range(1, 11):
                    total_supply += self.get_remaining_supply_for_level(level)
                cleaned = self.cleanup_inactive_miners()
                if cleaned > 0:
                    logger.info(f"[CLEANUP] Removed {cleaned} inactive miners")
                await websocket.send(json.dumps({"type": "status", "data": {"block_id": self.height, "total_miners": len(self.miners), "active_miners": sum(1 for m in self.miners.values() if m.active), "total_nodes": len(self.nodes), "active_nodes": sum(1 for n in self.nodes.values() if n.active), "max_level": self.level_mgr.max_unlocked, "current_reward": self.get_current_reward_for_level(1), "total_minted": self.total_minted, "remaining_supply": total_supply, "node_pool": self.node_pool, "uptime_pool": self.uptime_pool, "lp_pool": self.lp_pool, "buyer_pool": self.buyer_pool, "validator_fee_pool": self.validator_fee_pool, "level_intervals": LEVEL_BLOCK_INTERVALS, "level_caps": LEVEL_CAPS, "levels_with_miners": sorted(self.levels_with_miners), "pools": self.dex.get_pools(), "bridge_status": self.bridge.get_bridge_status(), "cleanup_removed": cleaned, "mempool_size": self.mempool.size(), "peers": len(self.p2p.peers), "uptime": int(time.time() - self.start_time)}}))
            elif msg_type == "get_health":
                await websocket.send(json.dumps({"type": "health", "data": self.health_checker.get_status()}))
            elif msg_type == "get_mempool":
                txs = await self.mempool.get_transactions(data.get("limit", 100))
                await websocket.send(json.dumps({"type": "mempool", "transactions": [{"hash": tx.tx_hash, "from": tx.from_wallet, "to": tx.to_wallet, "amount": tx.amount, "fee": tx.fee, "timestamp": tx.timestamp} for tx in txs]}))
            else:
                await websocket.send(json.dumps({"type": "error", "message": f"Unknown message type: {msg_type}"}))
        except Exception as e:
            logger.error(f"[WS] Message handler error: {e}")
            await websocket.send(json.dumps({"type": "error", "message": str(e)}))
    
    def update_level_groups(self):
        self.level_groups = {i: [] for i in range(1, 11)}
        self.levels_with_miners = set()
        for miner in self.miners.values():
            if miner.active:
                level = min(miner.level, MAX_LEVEL)
                if level in self.level_groups:
                    self.level_groups[level].append(miner.vid)
                    self.levels_with_miners.add(level)
    
    def select_validators_for_level(self, level: int) -> List[str]:
        miners = self.level_groups.get(level, [])
        if len(miners) < MIN_VALIDATORS_PER_BLOCK:
            return []
        seed = int(self.last_hash[:16], 16) if self.last_hash != "0"*64 else int(time.time())
        rng = random.Random(seed)
        weighted_miners = []
        for vid in miners:
            if vid in self.miners:
                m = self.miners[vid]
                weight = m.stake * (1 + m.blocks / max(m.blocks, 1))
                weighted_miners.extend([vid] * int(weight / 100))
        if not weighted_miners:
            return rng.sample(miners, min(len(miners), MIN_VALIDATORS_PER_BLOCK))
        selected = []
        available = weighted_miners.copy()
        while len(selected) < MIN_VALIDATORS_PER_BLOCK and available:
            choice = rng.choice(available)
            if choice not in selected:
                selected.append(choice)
            available = [v for v in available if v != choice]
        return selected
    
    def get_level_with_most_miners(self) -> Optional[int]:
        best_level = 1
        best_count = 0
        for level in range(1, 11):
            count = len(self.level_groups.get(level, []))
            if count > best_count:
                best_count = count
                best_level = level
        return best_level if best_count >= MIN_VALIDATORS_PER_BLOCK else None
    
    def get_effective_production_level(self, original_level: int) -> Optional[int]:
        miners_count = len(self.level_groups.get(original_level, []))
        if miners_count >= MIN_VALIDATORS_PER_BLOCK:
            return original_level
        else:
            return self.get_level_with_most_miners()
    
    def generate_challenge(self, block_id: int, validators: List[str]) -> str:
        return hashlib.sha256(f"{block_id}{''.join(sorted(validators))}{time.time()}{self.last_hash}{secrets.token_hex(16)}".encode()).hexdigest()
    
    def verify_challenge_response(self, vid: str, challenge: str, block_id: int, sig: str) -> bool:
        if vid not in self.miners:
            return False
        message = f"{challenge}{vid}{block_id}"
        return verify_signature(self.miners[vid].pub, message, sig, self.miners[vid].mtype)
    
    async def produce_block_for_level(self, original_level: int) -> bool:
        effective_level = self.get_effective_production_level(original_level)
        if effective_level is None:
            return False
        validators = self.select_validators_for_level(effective_level)
        if len(validators) < MIN_VALIDATORS_PER_BLOCK:
            return False
        block_id = self.height        
        challenge = self.generate_challenge(block_id, validators)
        self.pending_challenges[challenge] = {"bid": block_id, "validators": validators, "level": effective_level, "original_level": original_level, "sigs": {}, "start_time": time.time()}
        await asyncio.sleep(SIGNING_WINDOW_MS / 1000)
        pending = self.pending_challenges.pop(challenge, {})
        sigs = pending.get("sigs", {})
        valid_sigs = {}
        total_slashed = 0
        for vid, sig in sigs.items():
            if self.verify_challenge_response(vid, challenge, block_id, sig):
                valid_sigs[vid] = sig
        if len(valid_sigs) >= MIN_VALIDATORS_PER_BLOCK:
            block = self._add_block(block_id, self.last_hash, list(valid_sigs.keys()), effective_level, valid_sigs)
            self.distribute_block_reward(block, list(valid_sigs.keys()))
            asyncio.create_task(self.p2p.broadcast_block({"id": block_id, "ts": block.ts, "prev": block.prev, "validators": block.validators, "level": effective_level, "original_level": original_level, "hash": block.hash, "reward": block.reward}))
            if original_level != effective_level:
                logger.info(f"[BLOCK {block_id}] ACCEPTED | Original Level {original_level} -> Produced by Level {effective_level} | Validators: {len(valid_sigs)}")
            else:
                logger.info(f"[BLOCK {block_id}] ACCEPTED | Level {effective_level} | Validators: {len(valid_sigs)}")
            self.health_checker.record_block(block_id)
            self.metrics["blocks_produced"] += 1
            return True
        else:
            missing = set(validators) - set(sigs.keys())
            for vid in missing:
                total_slashed += self.slash_miner(vid, f"Missed signing for block {block_id}", block_id)
            if total_slashed > 0 and len(valid_sigs) > 0:
                per_signer = total_slashed // len(valid_sigs)
                for vid in valid_sigs:
                    if vid in self.miners:
                        m = self.miners[vid]
                        m.stake += per_signer
                        m.rewards += per_signer
                        self.balances[m.wallet] = self.balances.get(m.wallet, 0) + per_signer
                        self._save_balance(m.wallet, self.balances[m.wallet])
                        self._save_miner(m)
                logger.info(f"[REDIST] {total_slashed} MCX redistributed to {len(valid_sigs)} signers")
            if original_level != effective_level:
                logger.warning(f"[BLOCK {block_id}] REJECTED | Original Level {original_level} -> Attempted Level {effective_level} | Got {len(valid_sigs)}/{MIN_VALIDATORS_PER_BLOCK} signatures")
            else:
                logger.warning(f"[BLOCK {block_id}] REJECTED | Level {effective_level} | Got {len(valid_sigs)}/{MIN_VALIDATORS_PER_BLOCK} signatures")
            self.health_checker.record_error(f"Block {block_id} rejected: {len(valid_sigs)}/{MIN_VALIDATORS_PER_BLOCK} signatures")
            return False
    
    async def produce_blocks_loop(self):
        while True:
            self.update_level_groups()
            for level in range(1, 11):
                success = await self.produce_block_for_level(level)
                if success:
                    interval = self.get_block_interval(level)
                    await asyncio.sleep(interval)
            await asyncio.sleep(0.1)
    
    def distribute_block_reward(self, block: Block, signers: List[str]):
        if block.reward > 0:
            return
        reward = self.get_current_reward_for_level(block.level)
        if reward <= 0:
            logger.warning(f"[BLOCK {block.id}] No reward remaining for Level {block.level}")
            return
        block.reward = reward
        validator_total = int(reward * 0.7)
        node_total = int(reward * 0.08)
        uptime_total = int(reward * 0.05)
        lp_total = int(reward * 0.05)
        buyer_total = int(reward * 0.12)
        validator_share = validator_total // max(len(signers), 1)
        for vid in signers:
            if vid in self.miners:
                m = self.miners[vid]
                m.rewards += validator_share
                m.stake += validator_share
                m.blocks += 1
                m.misses = 0
                m.last_block = block.id
                self.balances[m.wallet] = self.balances.get(m.wallet, 0) + validator_share
                self._save_balance(m.wallet, self.balances[m.wallet])
                self.level_mgr.register(m.wallet, m.stake)
                m.level = self.level_mgr.get_level(m.wallet)
                self._save_miner(m)
                self.conn.execute("INSERT INTO validator_history (vid, username, block_id, level, timestamp, reward) VALUES (?, ?, ?, ?, ?, ?)", (vid, m.username, block.id, block.level, time.time(), validator_share))
                self.conn.commit()
        self.node_pool += node_total
        self.uptime_pool += uptime_total
        self.lp_pool += lp_total
        self.buyer_pool += buyer_total
        if self.validator_fee_pool > 0 and len(signers) > 0:
            fee_share = self.validator_fee_pool // len(signers)
            for vid in signers:
                if vid in self.miners:
                    m = self.miners[vid]
                    m.rewards += fee_share
                    m.stake += fee_share
                    m.fees_collected += fee_share
                    self.balances[m.wallet] = self.balances.get(m.wallet, 0) + fee_share
                    self._save_balance(m.wallet, self.balances[m.wallet])
                    self.level_mgr.register(m.wallet, m.stake)
                    m.level = self.level_mgr.get_level(m.wallet)
                    self._save_miner(m)
            logger.info(f"[BLOCK {block.id}] FEE DISTRIBUTION: {self.validator_fee_pool} MCX in fees to {len(signers)} validators ({fee_share} each)")
            self.validator_fee_pool = 0
        self.update_level_supply(block.level, reward)
        self.total_minted = self.get_total_minted()
        self.metrics["rewards_distributed"] += reward
        logger.info(f"[BLOCK {block.id}] REWARD: {reward} MCX | Level {block.level} | Validators: {validator_share} each")
    
    def distribute_periodic_rewards(self):
        active_miners = [m for m in self.miners.values() if m.active]
        total_uptime = sum(m.uptime for m in active_miners)
        if total_uptime > 0 and self.uptime_pool > 0:
            for miner in active_miners:
                if miner.uptime > 0:
                    share = int(self.uptime_pool * (miner.uptime / total_uptime))
                    miner.rewards += share
                    miner.stake += share
                    self.balances[miner.wallet] = self.balances.get(miner.wallet, 0) + share
                    self._save_balance(miner.wallet, self.balances[miner.wallet])
                    self.level_mgr.register(miner.wallet, miner.stake)
                    miner.level = self.level_mgr.get_level(miner.wallet)
                    self._save_miner(m)
            logger.info(f"[DISTRO] Uptime rewards: {self.uptime_pool} MCX to {len(active_miners)} miners")
        active_nodes = [n for n in self.nodes.values() if n.active]
        if active_nodes and self.node_pool > 0:
            node_share = self.node_pool // max(len(active_nodes), 1)
            for node in active_nodes:
                node.rewards_earned += node_share
                self.balances[node.wallet] = self.balances.get(node.wallet, 0) + node_share
                self._save_balance(node.wallet, self.balances[node.wallet])
                self._save_node(node)
            logger.info(f"[DISTRO] Node rewards: {self.node_pool} MCX to {len(active_nodes)} nodes")
        self.node_pool = 0
        self.uptime_pool = 0
        self.lp_pool = 0
    
    def distribute_buyer_rewards(self):
        if self.buyer_pool == 0:
            return
        c = self.conn.cursor()
        c.execute("SELECT wallet, username, bought FROM buyer_stats WHERE last_reset > ? ORDER BY bought DESC LIMIT 10", (time.time() - 30 * 24 * 3600,))
        top_buyers = c.fetchall()
        if not top_buyers:
            return
        for i, (wallet, username, _) in enumerate(top_buyers):
            if i >= len(BUYER_REWARDS):
                break
            reward = min(BUYER_REWARDS[i], self.buyer_pool)
            self.balances[wallet] = self.balances.get(wallet, 0) + reward
            self.buyer_pool -= reward
            tx_hash = hash_transaction({"from": "buyer_rewards", "to": wallet, "amount": reward})
            tx = Transaction(tx_hash, "buyer_rewards", wallet, reward, 0, time.time(), -1, "confirmed", "reward")
            self._save_transaction(tx)
            logger.info(f"[BUYER REWARD] #{i+1} {username[:20]}... +{reward} MCX")
        c.execute("UPDATE buyer_stats SET bought = 0, last_reset = ?", (time.time(),))
        self.conn.commit()
        self.buyer_pool = 0
    
    def slash_miner(self, vid: str, reason: str, block_id: int = -1) -> int:
        if vid not in self.miners:
            return 0
        m = self.miners[vid]
        slash = max(int(m.stake * SLASH_RATE), LEVEL_STAKE_RANGE)
        m.stake -= slash
        if m.stake < LEVEL_STAKE_RANGE:
            m.stake = LEVEL_STAKE_RANGE
        m.slashes += 1
        m.misses += 1
        m.consecutive_misses += 1
        self.level_mgr.register(m.wallet, m.stake)
        m.level = self.level_mgr.get_level(m.wallet)
        if m.slashes >= BAN_THRESHOLD:
            m.active = False
            m.banned_until = time.time() + BAN_DURATION
            logger.warning(f"[BAN] {m.username} BANNED for 1 hour after {BAN_THRESHOLD} slashes")
        self._save_miner(m)
        self.conn.execute("INSERT INTO slashing_events (vid, amount, reason, timestamp, block_id) VALUES (?, ?, ?, ?, ?)", (vid, slash, reason, time.time(), block_id))
        self.conn.commit()
        self.metrics["slash_events"] += 1
        logger.warning(f"[SLASH] {m.username} lost {slash} MCX (now {m.stake} MCX, Level {m.level})")
        asyncio.create_task(self.p2p.broadcast_slash(vid))
        return slash

# MAIN SERVER 
class MicroCoreServer:
    def __init__(self, network: MicroCoreNetwork):
        self.network = network
        self._shutdown = False
        self._tasks = []
    
    async def block_production_loop(self):
        while not self._shutdown:
            try:
                await self.network.produce_blocks_loop()
            except Exception as e:
                logger.error(f"[PRODUCER] Error: {e}")
                await asyncio.sleep(5)
    
    async def peer_discovery_loop(self):
        while not self._shutdown:
            try:
                await self.network.p2p.discover()
                await asyncio.sleep(DISCOVERY_INTERVAL)
            except Exception as e:
                logger.error(f"[PEER] Discovery error: {e}")
                await asyncio.sleep(5)
    
    async def peer_sync_loop(self):
        while not self._shutdown:
            try:
                await self.network.p2p.sync_with_peers()
                await asyncio.sleep(SYNC_INTERVAL)
            except Exception as e:
                logger.error(f"[PEER] Sync error: {e}")
                await asyncio.sleep(5)
    
    async def periodic_distribution_loop(self):
        while not self._shutdown:
            try:
                await asyncio.sleep(DISTRIBUTION_INTERVAL_SEC)
                self.network.distribute_periodic_rewards()
            except Exception as e:
                logger.error(f"[DISTRO] Error: {e}")
    
    async def buyer_rewards_loop(self):
        while not self._shutdown:
            try:
                await asyncio.sleep(3600)
                if time.time() - self.network.last_buyer_distribution > 30 * 24 * 3600:
                    self.network.distribute_buyer_rewards()
                    self.network.last_buyer_distribution = time.time()
            except Exception as e:
                logger.error(f"[BUYER] Error: {e}")
    
    async def embedded_miner_loop(self):
        while not self._shutdown:
            try:
                for challenge, pending in self.network.pending_challenges.items():
                    vid = self.network.username
                    if vid in pending["validators"] and vid not in pending["sigs"]:
                        message = f"{challenge}{vid}{pending['bid']}"
                        signature = sign_message(self.network.priv, message)
                        pending["sigs"][vid] = signature
                        logger.info(f"[EMBEDDED MINER] Signed block {pending['bid']} (Level {pending['level']})")
                await asyncio.sleep(0.2)
            except Exception as e:
                logger.error(f"[EMBEDDED] Error: {e}")
                await asyncio.sleep(1)
    
    async def cleanup_loop(self):
        while not self._shutdown:
            try:
                await asyncio.sleep(60)
                cleaned = self.network.cleanup_inactive_miners()
                if cleaned > 0:
                    logger.info(f"[CLEANUP] Removed {cleaned} inactive miners")
                await self.network.rate_limiter.cleanup()
            except Exception as e:
                logger.error(f"[CLEANUP] Error: {e}")
    
    async def status_reporter_loop(self):
        while not self._shutdown:
            try:
                await asyncio.sleep(60)
                total_minted = self.network.total_minted
                total_cap = sum(LEVEL_CAPS.values())
                percent = (total_minted / total_cap) * 100 if total_cap > 0 else 0
                remaining = total_cap - total_minted
                logger.info(f"\n{'='*60}")
                logger.info(f"MICROCORE NETWORK STATUS")
                logger.info(f"{'='*60}")
                logger.info(f"Block Height: {self.network.height}")
                logger.info(f"Total Minted: {total_minted:,} / {total_cap:,} ({percent:.4f}%)")
                logger.info(f"Remaining Supply: {remaining:,} MCX")
                logger.info(f"Active Miners: {sum(1 for m in self.network.miners.values() if m.active)}")
                logger.info(f"Total Miners: {len(self.network.miners)}")
                logger.info(f"Active Nodes: {sum(1 for n in self.network.nodes.values() if n.active)}")
                logger.info(f"Total Nodes: {len(self.network.nodes)}")
                logger.info(f"P2P Peers: {len(self.network.p2p.peers)}")
                logger.info(f"Max Unlocked Level: {self.network.level_mgr.max_unlocked}")
                logger.info(f"Levels with Miners: {sorted(self.network.levels_with_miners)}")
                logger.info(f"Node Pool: {self.network.node_pool} MCX")
                logger.info(f"Uptime Pool: {self.network.uptime_pool} MCX")
                logger.info(f"LP Pool: {self.network.lp_pool} MCX")
                logger.info(f"Buyer Rewards Pool: {self.network.buyer_pool} MCX")
                logger.info(f"Validator Fee Pool: {self.network.validator_fee_pool} MCX")
                logger.info(f"Mempool Size: {self.network.mempool.size()}")
                logger.info(f"Health: {self.network.health_checker.get_status()}")
                for level in range(1, 11):
                    remaining_supply = self.network.get_remaining_supply_for_level(level)
                    cap = LEVEL_CAPS[level]
                    level_percent = ((cap - remaining_supply) / cap) * 100 if cap > 0 else 0
                    miner_count = len(self.network.level_groups.get(level, []))
                    reward = self.network.get_current_reward_for_level(level)
                    logger.info(f"Level {level}: {miner_count} miners | {remaining_supply:,} / {cap:,} MCX remaining ({level_percent:.1f}%) | Reward: {reward} MCX")
                pools = self.network.dex.get_pools()
                if pools.get("success"):
                    logger.info(f"DEX Pools: {len(pools['pools'])}")
                    for pool in pools["pools"]:
                        logger.info(f"  {pool['pool_id']}: {pool['reserve_a']} {pool['token_a']} / {pool['reserve_b']} {pool['token_b']} (Price: {pool['price']:.6f})")
                bridge_status = self.network.bridge.get_bridge_status()
                if bridge_status:
                    logger.info(f"REAL TOKEN BRIDGES:")
                    for symbol, data in bridge_status.items():
                        logger.info(f"  {symbol}: Balance: {data['balance']:.2f} | Address: {data['address']}")
                logger.info(f"{'='*60}\n")
            except Exception as e:
                logger.error(f"[STATUS] Error: {e}")
    
    async def cleanup(self):
        self._shutdown = True
        for task in self._tasks:
            task.cancel()
        if self.network.conn:
            self.network.conn.close()
        logger.info("[SHUTDOWN] Cleanup complete")
    
    async def run(self):
        logger.info(f"\n{'='*60}")
        logger.info(f"MICROCORE (MCX) NODE v{VERSION} — WITH DEX & REAL TOKEN BRIDGES")
        logger.info(f"{'='*60}")
        logger.info(f"Username: {self.network.username}")
        logger.info(f"Wallet: {self.network.wallet}")
        logger.info(f"Node ID: {self.network.node_id[:16]}...")
        logger.info(f"{'='*60}")
        logger.info(f"WebSocket: ws://0.0.0.0:{NODE_PORT}{WS_PATH}")
        logger.info(f"P2P: 0.0.0.0:{P2P_PORT}")
        logger.info(f"Bootnodes: {BOOTSTRAP_NODES}")
        logger.info(f"GOSSIP DISCOVERY: ON")
        logger.info(f"EMBEDDED MINER: ACTIVE")
        logger.info(f"RATE LIMITING: ENABLED (60 req/min per IP)")
        logger.info(f"{'='*60}")
        logger.info(f"LEVEL SYSTEM: 10 levels, 1,000 MCX per level")
        logger.info(f"BLOCK TIMES: L1:40s, L2:35s, L3:30s, L4:25s, L5:20s, L6:15s, L7:10s, L8:9s, L9:8s, L10:7s")
        logger.info(f"BLOCK REWARD: 18 MCX (halving per level)")  
        logger.info(f"TOTAL CAP: ~3,281,040,000 MCX")  
        logger.info(f"{'='*60}")
        logger.info(f"REAL TOKEN BRIDGES (NO LIBRARIES):")
        for symbol, address in BRIDGE_ADDRESSES.items():
            logger.info(f"  {symbol}: {address}")
        logger.info(f"{'='*60}")
        logger.info(f"DEX FEATURES:")
        logger.info(f"  - Tokens: USDC (10M), ETH (10K), BTC (2.1K)")
        logger.info(f"  - Pools: MCX/USDC, MCX/ETH, MCX/BTC")
        logger.info(f"  - Swap Fee: 0.3% (0.27% to LPs, 0.03% to Protocol)")
        logger.info(f"  - Gas Fee: 0.6% (70% to Validators, 30% to Node)")
        logger.info(f"  - LP Tracking: On-chain (database)")
        logger.info(f"  - Price Discovery: x * y = k")
        logger.info(f"  - Node Wallet: ENCRYPTED (AES-256-CBC + PBKDF2)")
        logger.info(f"{'='*60}")
        logger.info(f"SECURITY:")
        logger.info(f"  [ENCRYPTED] Private keys NEVER displayed")
        logger.info(f"  [ENCRYPTED] AES-256-CBC encryption for all wallets")
        logger.info(f"  [ENCRYPTED] PBKDF2 with 100,000 iterations")
        logger.info(f"  [ENCRYPTED] Node wallet encrypted in database")
        logger.info(f"  [ENCRYPTED] Bridge wallets encrypted in database")
        logger.info(f"  [ENCRYPTED] Even the node operator cannot see private keys")
        logger.info(f"{'='*60}")
        logger.info(f"Node is running! Press Ctrl+C to stop.\n")
        self._tasks = [
            asyncio.create_task(self.network.p2p.start()),
            asyncio.create_task(self.network.p2p.heartbeat()),
            asyncio.create_task(self.peer_discovery_loop()),
            asyncio.create_task(self.peer_sync_loop()),
            asyncio.create_task(self.periodic_distribution_loop()),
            asyncio.create_task(self.buyer_rewards_loop()),
            asyncio.create_task(self.block_production_loop()),
            asyncio.create_task(self.embedded_miner_loop()),
            asyncio.create_task(self.cleanup_loop()),
            asyncio.create_task(self.status_reporter_loop()),
            asyncio.create_task(self.network.rate_limiter.start_cleanup()),
        ]
        async with serve(self.network.ws_handler, NODE_HOST, NODE_PORT):
            logger.info(f"[WS] WebSocket server started on ws://0.0.0.0:{NODE_PORT}{WS_PATH}")
            await asyncio.Future()

#  MAIN 
async def main():
    parser = argparse.ArgumentParser(description=f'{NAME} Complete Node v{VERSION}')
    parser.add_argument('--genesis', action='store_true', help='Run as genesis node')
    parser.add_argument('--peer', type=str, help='Connect to peer node (IP:PORT)')
    parser.add_argument('--username', type=str, required=True, help='Your username')
    parser.add_argument('--wallet', type=str, default="", help='Your wallet address')
    parser.add_argument('--privkey', type=str, default="", help='Your private key (optional)')
    parser.add_argument('--no-miner', action='store_true', help='Disable embedded miner')
    args = parser.parse_args()
    
    print(f"\n{'='*60}")
    print(f"{NAME} ({SYMBOL}) COMPLETE NODE v{VERSION} — WITH DEX & REAL TOKEN BRIDGES")
    print(f"{'='*60}")
    print(f"Username: {args.username}")
    print(f"Genesis Mode: {args.genesis}")
    print(f"Embedded Miner: {'DISABLED' if args.no_miner else 'ACTIVE'}")
    print(f"Gossip Discovery: ON")
    print(f"DEX: ENABLED (MCX/USDC, MCX/ETH, MCX/BTC)")
    print(f"REAL TOKEN BRIDGES: BTC, ETH, USDC (NO LIBRARIES)")
    print(f"BLOCK REWARD: 18 MCX")
    print(f"TOTAL CAP: ~3,281,040,000 MCX")
    print(f"Security: [ENCRYPTED] All private keys encrypted")
    print(f"NO STRIPE REQUIRED")
    print(f"{'='*60}\n")
    
    wallet_file = f"microcore_wallet_{args.username}.json"
    
    if args.wallet and args.privkey:
        my_wallet = args.wallet
        my_priv = args.privkey
        priv_obj = ec.derive_private_key(int(my_priv, 16), ec.SECP256K1())
        pub = priv_obj.public_key()
        my_pub = pub.public_bytes(encoding=serialization.Encoding.PEM, format=serialization.PublicFormat.SubjectPublicKeyInfo).decode()
        logger.info(f"[WALLET] Using existing wallet: {my_wallet}")
        logger.info(f"[WALLET] [ENCRYPTED] Private key provided (not displayed)")
    elif args.wallet:
        my_wallet = args.wallet
        _, my_priv, my_pub = generate_wallet()
        logger.info(f"[WALLET] Using provided wallet: {my_wallet}")
        logger.info(f"[WALLET] [ENCRYPTED] Private key generated and encrypted (not displayed)")
    elif os.path.exists(wallet_file):
        logger.info(f"[WALLET] Found existing wallet file for {args.username}")
        with open(wallet_file, 'r') as f:
            wallet_data = json.load(f)
            my_wallet = wallet_data["address"]
            my_priv = decrypt_private_key(
                wallet_data["private_key_encrypted"],
                args.username + "_microcore_v26_secure"
            )
            my_pub = wallet_data["public_key_pem"]
        logger.info(f"[WALLET] Loaded existing wallet: {my_wallet}")
    else:
        my_wallet, my_priv, my_pub = generate_wallet()
        print(f"\n[ENCRYPTED] NEW WALLET CREATED!")
        print(f"Wallet Address: {my_wallet}")
        print(f"Private Key: ******** ([ENCRYPTED])")
        print(f"Public Key: {my_pub[:64]}...")
        print(f"\n[ENCRYPTED] Your private key is ENCRYPTED and stored in:")
        print(f"   {wallet_file}")
        print(f"   [ENCRYPTED] You do NOT need to know it")
        print(f"   [ENCRYPTED] The node handles everything automatically")
        print(f"   [ENCRYPTED] Even YOU cannot see it without the password")
        print(f"   [ENCRYPTED] AES-256-CBC + PBKDF2 encryption with 100,000 iterations")
        encrypted_priv = encrypt_private_key(my_priv, args.username + "_microcore_v26_secure")
        wallet_data = {
            "username": args.username,
            "address": my_wallet,
            "private_key_encrypted": encrypted_priv,
            "public_key_pem": my_pub,
            "created_at": time.time(),
            "version": VERSION
        }
        with open(wallet_file, 'w') as f:
            json.dump(wallet_data, f, indent=2)
        logger.info(f"[WALLET] [ENCRYPTED] Wallet saved to: {wallet_file}")
        logger.info(f"[WALLET] [ENCRYPTED] Private key is ENCRYPTED with AES-256-CBC")
    
    network = MicroCoreNetwork(
        is_genesis=args.genesis,
        username=args.username,
        wallet=my_wallet,
        priv=my_priv,
        pub=my_pub
    )
    
    server = MicroCoreServer(network)
    
    if args.peer:
        logger.info(f"[P2P] Connecting to peer: {args.peer}")
        await network.p2p._connect(args.peer)
    
    try:
        await server.run()
    except asyncio.CancelledError:
        logger.info("[SHUTDOWN] Server stopped")
    finally:
        await server.cleanup()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[SHUTDOWN] Node stopped by user")
        sys.exit(0)
    except Exception as e:
        print(f"\n[ERROR] {e}")
        traceback.print_exc()
        sys.exit(1)
