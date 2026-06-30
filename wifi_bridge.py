#!/usr/bin/env python3


import asyncio
import serial
import serial.tools.list_ports
import json
import websockets
import time
import os
import sys
import signal
import logging
from collections import deque
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from datetime import datetime

# ==================== CONFIGURATION ====================
CONFIG = {
    "bootstrap_nodes": ["192.168.88.9:8080"],
    "node_port": 8080,
    "ws_path": "/ws",
    "baud_rate": 115200,
    "max_reconnect_attempts": 10,
    "reconnect_delay": 5,
    "heartbeat_interval": 30,
    "max_buffer_size": 1000,
    "scan_interval": 5,
    "miner_timeout": 60,
    "max_valid_level": 10,
    "min_valid_stake": 100,
    "max_valid_stake": 1000000,
    "serial_timeout": 2,
    "write_timeout": 1,
}

PEER_CACHE_FILE = "bridge_peers.json"
LOG_FILE = "bridge.log"

# ==================== LOGGING ====================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ==================== DATA CLASSES ====================
@dataclass
class MinerInfo:
    """Stores miner information with validation"""
    port: str
    username: str = "unknown"
    validator_id: str = "unknown"
    wallet: str = ""
    board: str = "Unknown"
    level: int = 1
    stake: int = 1000
    rewards: int = 0
    blocks: int = 0
    uptime: int = 0
    today_uptime: int = 0
    last_seen: float = 0
    registered: bool = False
    active: bool = True
    
    def update_from_data(self, data: dict):
        """Update from JSON data with validation"""
        # Validate and update level
        level = data.get("level", 1)
        if isinstance(level, (int, float)) and 1 <= level <= CONFIG["max_valid_level"]:
            self.level = int(level)
        else:
            logger.warning(f"[VALIDATE] Invalid level {level} from {self.port}, keeping {self.level}")
        
        # Validate and update stake
        stake = data.get("stake", 1000)
        if isinstance(stake, (int, float)) and CONFIG["min_valid_stake"] <= stake <= CONFIG["max_valid_stake"]:
            self.stake = int(stake)
        else:
            logger.warning(f"[VALIDATE] Invalid stake {stake} from {self.port}, keeping {self.stake}")
        
        # Update other fields
        self.username = data.get("username", self.username)
        self.validator_id = data.get("validator_id", self.validator_id)
        self.wallet = data.get("wallet", self.wallet)
        self.board = data.get("board", self.board)
        self.rewards = max(0, data.get("rewards", self.rewards))
        self.blocks = max(0, data.get("blocks", self.blocks))
        self.uptime = max(0, data.get("uptime", self.uptime))
        self.today_uptime = max(0, data.get("today_uptime", self.today_uptime))
        self.last_seen = time.time()
        
        if data.get("type") in ["register", "miner_startup"]:
            self.registered = True
            self.active = True
    
    def to_dict(self) -> dict:
        return {
            "port": self.port,
            "username": self.username,
            "validator_id": self.validator_id,
            "wallet": self.wallet,
            "board": self.board,
            "level": self.level,
            "stake": self.stake,
            "rewards": self.rewards,
            "blocks": self.blocks,
            "uptime": self.uptime,
            "today_uptime": self.today_uptime,
            "last_seen": self.last_seen,
            "registered": self.registered,
            "active": self.active
        }

@dataclass
class BridgeStats:
    """Bridge statistics"""
    start_time: float = field(default_factory=time.time)
    messages_sent: int = 0
    messages_received: int = 0
    arduino_messages: int = 0
    invalid_json: int = 0
    bytes_sent: int = 0
    bytes_received: int = 0
    reconnections: int = 0
    errors: int = 0
    
    def format_bytes(self, bytes_val: int) -> str:
        for unit in ['B', 'KB', 'MB', 'GB']:
            if bytes_val < 1024.0:
                return f"{bytes_val:.1f} {unit}"
            bytes_val /= 1024.0
        return f"{bytes_val:.1f} TB"
    
    def get_uptime(self) -> str:
        uptime = int(time.time() - self.start_time)
        hours = uptime // 3600
        minutes = (uptime % 3600) // 60
        seconds = uptime % 60
        return f"{hours}h {minutes}m {seconds}s"

# ==================== PEER MANAGEMENT ====================
class PeerManager:
    """Manages node peers with persistence"""
    
    def __init__(self):
        self.peers: List[str] = []
        self.current_index: int = 0
        self.discovered: set = set()
        self._load_cache()
        self._init_from_config()
    
    def _init_from_config(self):
        for peer in CONFIG["bootstrap_nodes"]:
            self.add_peer(peer)
    
    def _load_cache(self):
        try:
            if os.path.exists(PEER_CACHE_FILE):
                with open(PEER_CACHE_FILE, 'r') as f:
                    cached = json.load(f)
                    for peer in cached:
                        self.add_peer(peer)
                logger.info(f"[PEERS] Loaded {len(cached)} peers from cache")
        except Exception as e:
            logger.debug(f"[PEERS] Could not load cache: {e}")
    
    def _save_cache(self):
        try:
            with open(PEER_CACHE_FILE, 'w') as f:
                json.dump(list(self.discovered), f, indent=2)
        except Exception as e:
            logger.debug(f"[PEERS] Could not save cache: {e}")
    
    def add_peer(self, peer: str):
        peer = peer.strip()
        if not peer:
            return
        if "://" not in peer:
            peer = f"ws://{peer}"
        if not peer.endswith(CONFIG["ws_path"]):
            peer = f"{peer}{CONFIG['ws_path']}"
        
        if peer not in self.discovered:
            self.discovered.add(peer)
            self.peers.append(peer)
            self._save_cache()
            logger.info(f"[PEERS] Added: {peer}")
    
    def get_current_peer(self) -> Optional[str]:
        if not self.peers:
            return None
        return self.peers[self.current_index % len(self.peers)]
    
    def switch_peer(self):
        if not self.peers:
            return None
        self.current_index = (self.current_index + 1) % len(self.peers)
        logger.info(f"[PEERS] Switched to peer #{self.current_index}")
        return self.get_current_peer()
    
    def get_all(self) -> List[str]:
        return self.peers.copy()

# ==================== SERIAL MANAGER ====================
class SerialManager:
    """Manages serial connections to Arduino miners"""
    
    def __init__(self):
        self.ports: Dict[str, serial.Serial] = {}
        self.miners: Dict[str, MinerInfo] = {}
        self.buffers: Dict[str, deque] = {}
        self.tasks: Dict[str, asyncio.Task] = {}
        self._lock = asyncio.Lock()
    
    def is_port_open(self, port: str) -> bool:
        return port in self.ports and self.ports[port].is_open
    
    async def open_port(self, port: str) -> bool:
        async with self._lock:
            if port in self.ports and self.ports[port].is_open:
                return True
            
            try:
                ser = serial.Serial(
                    port,
                    CONFIG["baud_rate"],
                    timeout=CONFIG["serial_timeout"],
                    write_timeout=CONFIG["write_timeout"],
                    exclusive=True
                )
                ser.reset_input_buffer()
                ser.reset_output_buffer()
                
                self.ports[port] = ser
                if port not in self.miners:
                    self.miners[port] = MinerInfo(port=port)
                
                logger.info(f"[SERIAL] ✅ Opened {port}")
                return True
                
            except serial.SerialException as e:
                if "Access is denied" in str(e):
                    logger.warning(f"[SERIAL] {port} in use by another program")
                else:
                    logger.error(f"[SERIAL] Failed to open {port}: {e}")
                return False
            except Exception as e:
                logger.error(f"[SERIAL] Unexpected error opening {port}: {e}")
                return False
    
    async def close_port(self, port: str):
        async with self._lock:
            if port in self.ports:
                try:
                    self.ports[port].close()
                except:
                    pass
                del self.ports[port]
            
            if port in self.tasks:
                self.tasks[port].cancel()
                del self.tasks[port]
            
            if port in self.miners:
                self.miners[port].active = False
            
            logger.info(f"[SERIAL] Closed {port}")
    
    async def write_to_port(self, port: str, data: str) -> bool:
        if not self.is_port_open(port):
            return False
        
        try:
            self.ports[port].write((data + "\n").encode())
            return True
        except Exception as e:
            logger.error(f"[SERIAL] Write to {port} failed: {e}")
            return False
    
    def get_all_ports(self) -> List[str]:
        return list(self.ports.keys())
    
    def get_miner_info(self, port: str) -> Optional[dict]:
        if port in self.miners:
            return self.miners[port].to_dict()
        return None
    
    def get_all_miners(self) -> List[dict]:
        return [m.to_dict() for m in self.miners.values() if m.active]
    
    def update_miner(self, port: str, data: dict):
        if port in self.miners:
            self.miners[port].update_from_data(data)
            return True
        return False

# ==================== PORT SCANNER ====================
class PortScanner:
    """Scans for Arduino ports"""
    
    @staticmethod
    def find_all() -> List[str]:
        """Find all serial ports"""
        ports = serial.tools.list_ports.comports()
        found = []
        
        for port in ports:
            # Only include COM/tty ports
            if "COM" in port.device or "tty" in port.device:
                # Exclude non-Arduino devices
                exclude_keywords = ["Bluetooth", "BlueTooth", "BT", "Modem", "Printer"]
                exclude = False
                for keyword in exclude_keywords:
                    if keyword.lower() in port.description.lower():
                        exclude = True
                        break
                if not exclude:
                    found.append(port.device)
                    logger.debug(f"[SCAN] Found: {port.device} - {port.description}")
        
        return found
    
    @staticmethod
    async def test_port(port: str, baud: int = 115200) -> bool:
        """Test if port has valid Arduino data"""
        try:
            ser = serial.Serial(port, baud, timeout=1)
            time.sleep(0.5)
            
            # Read available data
            data = b""
            start = time.time()
            while time.time() - start < 1:
                if ser.in_waiting:
                    data += ser.read(ser.in_waiting)
                    if b'\n' in data:
                        break
                time.sleep(0.05)
            
            ser.close()
            
            if not data:
                return False
            
            # Check if it looks like JSON
            try:
                text = data.decode('utf-8', errors='ignore')
                return '{' in text and '}' in text
            except:
                return False
                
        except Exception as e:
            logger.debug(f"[SCAN] Test {port} failed: {e}")
            return False

# ==================== JSON VALIDATOR ====================
class JSONValidator:
    """Validates and sanitizes JSON data from Arduino"""
    
    @staticmethod
    def is_valid(data: str) -> bool:
        """Check if string is valid JSON"""
        if not data or not data.strip():
            return False
        if not data.startswith('{') and not data.startswith('['):
            return False
        try:
            json.loads(data)
            return True
        except:
            return False
    
    @staticmethod
    def extract_json(line: str) -> Optional[str]:
        """Extract JSON object from a line"""
        if not line:
            return None
        
        start = line.find('{')
        end = line.rfind('}')
        
        if start >= 0 and end > start:
            return line[start:end+1]
        return None
    
    @staticmethod
    def sanitize(data: dict) -> dict:
        """Sanitize miner data"""
        # Level: 1-10
        level = data.get("level", 1)
        if not isinstance(level, (int, float)) or level < 1 or level > CONFIG["max_valid_level"]:
            logger.warning(f"[SANITIZE] Invalid level {level} → 1")
            data["level"] = 1
        else:
            data["level"] = int(level)
        
        # Stake: 100 - 1,000,000
        stake = data.get("stake", 1000)
        if not isinstance(stake, (int, float)):
            logger.warning(f"[SANITIZE] Invalid stake type → 1000")
            data["stake"] = 1000
        elif stake < CONFIG["min_valid_stake"]:
            logger.warning(f"[SANITIZE] Stake too low {stake} → {CONFIG['min_valid_stake']}")
            data["stake"] = CONFIG["min_valid_stake"]
        elif stake > CONFIG["max_valid_stake"]:
            logger.warning(f"[SANITIZE] Stake too high {stake} → {CONFIG['max_valid_stake']}")
            data["stake"] = CONFIG["max_valid_stake"]
        else:
            data["stake"] = int(stake)
        
        # Rewards: >= 0
        rewards = data.get("rewards", 0)
        if not isinstance(rewards, (int, float)) or rewards < 0:
            data["rewards"] = 0
        else:
            data["rewards"] = int(rewards)
        
        # Blocks: >= 0
        blocks = data.get("blocks", 0)
        if not isinstance(blocks, (int, float)) or blocks < 0:
            data["blocks"] = 0
        else:
            data["blocks"] = int(blocks)
        
        # Uptime: >= 0
        uptime = data.get("uptime", 0)
        if not isinstance(uptime, (int, float)) or uptime < 0:
            data["uptime"] = 0
        else:
            data["uptime"] = int(uptime)
        
        return data

# ==================== WEBSOCKET BRIDGE ====================
class WebSocketBridge:
    """Main bridge class"""
    
    def __init__(self):
        self.running = True
        self.websocket = None
        self.connected = False
        
        self.peer_manager = PeerManager()
        self.serial_manager = SerialManager()
        self.stats = BridgeStats()
        self.validator = JSONValidator()
        
        self.reconnect_attempts = 0
        self.last_heartbeat = 0
        
        # Signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        logger.info("\n[SHUTDOWN] Stopping bridge...")
        self.running = False
    
    # ==================== WEBSOCKET ====================
    async def _connect_to_node(self):
        """Connect to node with auto-reconnect"""
        while self.running:
            peer_url = self.peer_manager.get_current_peer()
            if not peer_url:
                logger.error("[NODE] No peers available")
                await asyncio.sleep(10)
                continue
            
            try:
                logger.info(f"[NODE] Connecting to {peer_url}")
                
                async with websockets.connect(
                    peer_url,
                    ping_interval=15,
                    ping_timeout=10,
                    close_timeout=5,
                    max_size=2**20,
                    open_timeout=10
                ) as ws:
                    self.websocket = ws
                    self.connected = True
                    self.reconnect_attempts = 0
                    logger.info(f"[NODE] ✅ Connected")
                    
                    # Register bridge
                    await ws.send(json.dumps({
                        "type": "register_bridge",
                        "version": "10.0",
                        "timestamp": int(time.time())
                    }))
                    
                    # Request peers
                    await ws.send(json.dumps({"type": "get_peers"}))
                    
                    # Message loop
                    async for message in ws:
                        await self._handle_node_message(message)
                        
            except websockets.exceptions.ConnectionClosed as e:
                logger.warning(f"[NODE] Connection closed: {e}")
            except asyncio.TimeoutError:
                logger.warning("[NODE] Connection timeout")
            except Exception as e:
                logger.error(f"[NODE] Connection error: {e}")
            
            # Disconnected
            self.connected = False
            self.websocket = None
            self.stats.reconnections += 1
            
            # Switch peer if needed
            if self.peer_manager.peers:
                self.peer_manager.switch_peer()
            
            # Exponential backoff
            delay = min(CONFIG["reconnect_delay"] * (2 ** min(self.reconnect_attempts, 5)), 60)
            logger.info(f"[NODE] Reconnecting in {delay}s...")
            await asyncio.sleep(delay)
            self.reconnect_attempts += 1
    
    async def _handle_node_message(self, message: str):
        """Handle messages from node"""
        try:
            data = json.loads(message)
            self.stats.messages_received += 1
            self.stats.bytes_received += len(message)
            
            # Handle peers
            if data.get("type") == "peers":
                for peer in data.get("peers", []):
                    self.peer_manager.add_peer(peer)
                logger.info(f"[NODE] Got {len(data.get('peers', []))} peers")
                return
            
            # Forward to all miners
            for port in self.serial_manager.get_all_ports():
                await self.serial_manager.write_to_port(port, message)
                self.stats.bytes_sent += len(message)
                
        except json.JSONDecodeError:
            logger.warning(f"[NODE] Invalid JSON: {message[:100]}")
        except Exception as e:
            logger.error(f"[NODE] Handler error: {e}")
    
    # ==================== SERIAL ====================
    async def _handle_serial_ports(self):
        """Manage serial ports"""
        while self.running:
            # Scan for new ports
            found_ports = PortScanner.find_all()
            
            # Force COM4 if not already open
            if "COM4" not in self.serial_manager.ports and "COM4" in found_ports:
                logger.info("[SERIAL] Found COM4, opening...")
                if await self.serial_manager.open_port("COM4"):
                    # Create handler task
                    task = asyncio.create_task(self._handle_serial_messages("COM4"))
                    self.serial_manager.tasks["COM4"] = task
            
            # Open new ports
            for port in found_ports:
                if port not in self.serial_manager.ports:
                    if await self.serial_manager.open_port(port):
                        task = asyncio.create_task(self._handle_serial_messages(port))
                        self.serial_manager.tasks[port] = task
            
            # Check existing ports
            for port in list(self.serial_manager.ports.keys()):
                if not self.serial_manager.is_port_open(port):
                    logger.warning(f"[SERIAL] {port} closed, reopening...")
                    await self.serial_manager.close_port(port)
                    if await self.serial_manager.open_port(port):
                        task = asyncio.create_task(self._handle_serial_messages(port))
                        self.serial_manager.tasks[port] = task
            
            await asyncio.sleep(CONFIG["scan_interval"])
    
    async def _handle_serial_messages(self, port: str):
        """Handle messages from a serial port"""
        if not self.serial_manager.is_port_open(port):
            return
        
        ser = self.serial_manager.ports[port]
        buffer = ""
        error_count = 0
        
        logger.info(f"[SERIAL:{port}] Listening...")
        
        while self.running and self.serial_manager.is_port_open(port):
            try:
                if ser.in_waiting:
                    # Read all available bytes
                    raw = ser.read(ser.in_waiting)
                    try:
                        text = raw.decode('utf-8', errors='replace')
                        buffer += text
                    except:
                        continue
                    
                    # Process complete lines
                    while '\n' in buffer:
                        line, buffer = buffer.split('\n', 1)
                        line = line.strip()
                        
                        if not line:
                            continue
                        
                        self.stats.arduino_messages += 1
                        
                        # Extract JSON
                        json_line = self.validator.extract_json(line)
                        if not json_line:
                            self.stats.invalid_json += 1
                            if self.stats.invalid_json % 10 == 0:
                                logger.debug(f"[SERIAL:{port}] Non-JSON: {line[:50]}")
                            continue
                        
                        # Validate JSON
                        if not self.validator.is_valid(json_line):
                            self.stats.invalid_json += 1
                            logger.debug(f"[SERIAL:{port}] Invalid JSON: {json_line[:100]}")
                            continue
                        
                        # Parse and sanitize
                        try:
                            data = json.loads(json_line)
                            
                            # Sanitize miner data
                            if data.get("type") in ["register", "miner_startup", "uptime_ping"]:
                                data = self.validator.sanitize(data)
                                
                                # Update miner info
                                self.serial_manager.update_miner(port, data)
                                
                                if data.get("type") in ["register", "miner_startup"]:
                                    miner = self.serial_manager.miners.get(port)
                                    logger.info(f"[SERIAL:{port}] ✅ Registered: {miner.username} (Lv{miner.level})")
                            
                            # Forward to node
                            if self.connected and self.websocket:
                                try:
                                    await self.websocket.send(json_line)
                                    self.stats.messages_sent += 1
                                    self.stats.bytes_sent += len(json_line)
                                except Exception as e:
                                    logger.error(f"[SERIAL:{port}] Forward failed: {e}")
                                    # Buffer message
                                    if port not in self.serial_manager.buffers:
                                        self.serial_manager.buffers[port] = deque(maxlen=CONFIG["max_buffer_size"])
                                    self.serial_manager.buffers[port].append(json_line)
                            else:
                                # Buffer message
                                if port not in self.serial_manager.buffers:
                                    self.serial_manager.buffers[port] = deque(maxlen=CONFIG["max_buffer_size"])
                                self.serial_manager.buffers[port].append(json_line)
                            
                            error_count = 0
                            
                        except json.JSONDecodeError as e:
                            self.stats.invalid_json += 1
                            logger.debug(f"[SERIAL:{port}] JSON error: {e}")
                
                # Flush buffers if connected
                if self.connected and self.websocket:
                    for p, buffer_queue in list(self.serial_manager.buffers.items()):
                        while buffer_queue:
                            try:
                                msg = buffer_queue.popleft()
                                await self.websocket.send(msg)
                                self.stats.messages_sent += 1
                                self.stats.bytes_sent += len(msg)
                            except:
                                break
                
                await asyncio.sleep(0.01)
                
            except serial.SerialException as e:
                error_count += 1
                if "Access is denied" in str(e):
                    logger.error(f"[SERIAL:{port}] Access denied - port in use")
                    await self.serial_manager.close_port(port)
                    break
                elif error_count > 5:
                    logger.error(f"[SERIAL:{port}] Too many errors ({error_count})")
                    await self.serial_manager.close_port(port)
                    break
                else:
                    logger.warning(f"[SERIAL:{port}] Serial error: {e}")
                    await asyncio.sleep(1)
                    
            except Exception as e:
                error_count += 1
                logger.error(f"[SERIAL:{port}] Handler error: {e}")
                if error_count > 10:
                    break
                await asyncio.sleep(1)
        
        logger.info(f"[SERIAL:{port}] Handler stopped")
    
    # ==================== HEARTBEAT ====================
    async def _heartbeat_loop(self):
        """Send heartbeats to keep connections alive"""
        while self.running:
            await asyncio.sleep(CONFIG["heartbeat_interval"])
            
            # Send heartbeat to serial ports
            for port in self.serial_manager.get_all_ports():
                await self.serial_manager.write_to_port(port, 
                    f'{{"type":"heartbeat","timestamp":{int(time.time())}}}')
    
    # ==================== STATUS REPORTER ====================
    async def _status_reporter(self):
        """Report status periodically"""
        while self.running:
            await asyncio.sleep(10)
            
            logger.info(f"\n{'='*60}")
            logger.info("[STATUS] BRIDGE v10.0")
            logger.info(f"{'='*60}")
            logger.info(f"Uptime: {self.stats.get_uptime()}")
            logger.info(f"Arduino messages: {self.stats.arduino_messages:,}")
            logger.info(f"Invalid JSON: {self.stats.invalid_json:,}")
            logger.info(f"Messages to node: {self.stats.messages_sent:,}")
            logger.info(f"Messages from node: {self.stats.messages_received:,}")
            logger.info(f"Bytes sent: {self.stats.format_bytes(self.stats.bytes_sent)}")
            logger.info(f"Bytes received: {self.stats.format_bytes(self.stats.bytes_received)}")
            logger.info(f"Reconnections: {self.stats.reconnections}")
            logger.info(f"Errors: {self.stats.errors}")
            logger.info(f"Node: {'✅ Connected' if self.connected else '❌ Disconnected'}")
            logger.info(f"Active ports: {len(self.serial_manager.get_all_ports())}")
            
            # Show miners
            for port in self.serial_manager.get_all_ports():
                info = self.serial_manager.get_miner_info(port)
                if info:
                    status = "✅" if info.get("registered") else "⏳"
                    logger.info(f"  {port}: {status} {info.get('username')} | {info.get('board')} | Lv{info.get('level')} | {info.get('stake')} MCX")
            
            logger.info(f"{'='*60}")
    
    # ==================== RUN ====================
    async def run(self):
        """Run the bridge"""
        print("\n" + "=" * 60)
        print("MICROCORE WIFI BRIDGE v10.0 — COMPLETE REWRITE")
        print("=" * 60)
        print(f"Bootnodes: {CONFIG['bootstrap_nodes']}")
        print(f"Baud rate: {CONFIG['baud_rate']}")
        print(f"Max level: {CONFIG['max_valid_level']}")
        print(f"Min stake: {CONFIG['min_valid_stake']}")
        print(f"Max stake: {CONFIG['max_valid_stake']}")
        print("=" * 60)
        print("\n🚀 Starting bridge... Press Ctrl+C to stop\n")
        
        # Run all tasks
        await asyncio.gather(
            self._connect_to_node(),
            self._handle_serial_ports(),
            self._heartbeat_loop(),
            self._status_reporter(),
        )

# ==================== MAIN ====================
async def main():
    bridge = WebSocketBridge()
    try:
        await bridge.run()
    except KeyboardInterrupt:
        print("\n[SHUTDOWN] Stopped by user")
    finally:
        # Cleanup
        for port in bridge.serial_manager.get_all_ports():
            await bridge.serial_manager.close_port(port)
        print("[SHUTDOWN] Goodbye!")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[EXIT] Goodbye!")
        sys.exit(0)
