#include <EEPROM.h>
#include <avr/wdt.h>
#include <avr/pgmspace.h>
#include <avr/power.h>

//  VERSION =
#define VERSION "8.0-MAINNET"
#define MINER_TYPE "avr"

//  USER CONFIGURATION 
const char USERNAME[] PROGMEM = "youR_Username";                    
const char PRIVATE_KEY[] PROGMEM = "wallet_private_keys";  

//  NETWORK CONSTANTS 
#define SYMBOL "MCX"
#define MIN_VALIDATORS_PER_BLOCK 10
#define SIGNING_WINDOW_MS 2500
#define SLASH_RATE 0.10
#define BAN_THRESHOLD 5
#define UPTIME_PING_INTERVAL 30000
#define RE_REGISTER_INTERVAL 30000
#define MAX_LEVEL 10
#define LEVEL_STAKE_RANGE 1000
#define INITIAL_STAKE 1000
#define DAILY_SECONDS 86400
#define LED_PIN 13
#define LED_ON HIGH
#define LED_OFF LOW
#define SERIAL_BAUD 115200
#define MAX_JSON_SIZE 300
#define EEPROM_VERSION 0x81

//  LEVEL BLOCK INTERVALS 
const uint16_t LEVEL_BLOCK_INTERVALS[] PROGMEM = {0, 40, 35, 30, 25, 20, 15, 10, 9, 8, 7};

//  EEPROM ADDRESSES 
#define EEPROM_STAKE_ADDR 0
#define EEPROM_REWARDS_ADDR 4
#define EEPROM_BLOCKS_ADDR 8
#define EEPROM_UPTIME_ADDR 12
#define EEPROM_TODAY_UPTIME_ADDR 16
#define EEPROM_LAST_RESET_ADDR 20
#define EEPROM_SLASH_COUNT_ADDR 24
#define EEPROM_CONSECUTIVE_MISSES_ADDR 28
#define EEPROM_LEVEL_ADDR 32
#define EEPROM_CHECKSUM_ADDR 36
#define EEPROM_MAGIC_ADDR 40
#define EEPROM_MINER_VERSION_ADDR 44
#define EEPROM_NODE_INDEX_ADDR 45
#define EEPROM_RECONNECT_ATTEMPTS_ADDR 46
#define EEPROM_LAST_BLOCK_ID_ADDR 48
#define EEPROM_TOTAL_UPTIME_ADDR 52
#define EEPROM_BEST_LEVEL_ADDR 56

#define MAGIC_NUMBER 0xA5A5A5A5

//  BOARD DETECTION 
#if defined(__AVR_ATmega2560__)
  #define BOARD_TYPE "Mega"
  #define HAS_EXTRA_RAM 1
#elif defined(__AVR_ATmega32U4__)
  #define BOARD_TYPE "Micro"
  #define HAS_EXTRA_RAM 0
#elif defined(__AVR_ATmega328P__)
  #define BOARD_TYPE "Uno/Nano"
  #define HAS_EXTRA_RAM 0
#elif defined(__AVR_ATmega168__)
  #define BOARD_TYPE "Diecimila"
  #define HAS_EXTRA_RAM 0
#else
  #define BOARD_TYPE "AVR"
  #define HAS_EXTRA_RAM 0
#endif

//  MEMORY OPTIMIZATION 
// Use smaller buffers on 2KB RAM devices
#if HAS_EXTRA_RAM
  #define JSON_BUF_SIZE 800
  #define TEMP_BUF_SIZE 150
#else
  #define JSON_BUF_SIZE 600
  #define TEMP_BUF_SIZE 100
#endif

//  GLOBAL VARIABLES 
// Optimize memory by grouping related variables
struct MinerState {
  uint32_t stake;
  uint32_t rewards;
  uint32_t blocks;
  uint32_t uptime;
  uint32_t todayUptime;
  uint32_t lastReset;
  uint32_t level;
  uint32_t consecutiveMisses;
  uint32_t slashCount;
  uint32_t lastBlockId;
  uint32_t totalUptime;
  uint32_t bestLevel;
} state;

struct RuntimeState {
  uint32_t lastPing;
  uint32_t lastChallenge;
  uint32_t blockId;
  uint32_t lastRegAttempt;
  uint32_t lastBlockTime;
  uint32_t blocksMissed;
  uint32_t blocksAttempted;
  uint32_t reconnectAttempts;
  uint32_t nodeIndex;
  uint32_t lastStatusReport;
} runtime;

uint8_t isValidator;
uint8_t isRegistered;
uint8_t miningEnabled;
uint8_t isBanned;
uint8_t powerSavingMode;
uint8_t reconnectBackoff;

char vid[17];
char wallet[17];
char challenge[33];
char jsonBuf[JSON_BUF_SIZE];
char tempBuf[TEMP_BUF_SIZE];
char nodeIP[16];

//  LED FUNCTIONS 
void led_init() { 
  pinMode(LED_PIN, OUTPUT); 
  led_off(); 
}

void led_on() { 
  digitalWrite(LED_PIN, LED_ON); 
}

void led_off() { 
  digitalWrite(LED_PIN, LED_OFF); 
}

void led_blink(uint8_t n, uint16_t d) {
  for (uint8_t i = 0; i < n; i++) {
    led_on();
    delay(d);
    led_off();
    delay(d);
  }
}

void led_status_indicator(uint8_t mode) {
  switch(mode) {
    case 0: led_off(); break;
    case 1: led_on(); break;
    case 2: led_blink(1, 100); break;
    case 3: led_blink(5, 50); break;
    case 4: led_on(); delay(2000); led_off(); delay(500); break;
    case 5: led_blink(2, 200); break;  // Reconnecting
    case 6: led_blink(3, 300); break;  // Registered
  }
}

//  DJB2 HASH (8 chars)
void djb2_hash(const char* in, char* out) {
  uint32_t h = 5381;
  uint8_t i = 0;
  while (in[i] && i < 200) {
    h = ((h << 5) + h) + (uint8_t)in[i];
    i++;
  }
  // Add hardware entropy
  h = ((h << 5) + h) + (uint32_t)millis();
  h = ((h << 5) + h) + (uint32_t)analogRead(A0);
  #if defined(__AVR_ATmega2560__)
    h = ((h << 5) + h) + (uint32_t)analogRead(A1);
  #endif
  sprintf(out, "%08lx", h);
}

//  EEPROM MANAGEMENT 
uint32_t calcChecksum() {
  uint32_t sum = 0;
  sum += state.stake;
  sum += state.rewards;
  sum += state.blocks;
  sum += state.uptime;
  sum += state.todayUptime;
  sum += state.slashCount;
  sum += state.consecutiveMisses;
  sum += state.level;
  sum += state.lastBlockId;
  sum += state.totalUptime;
  sum ^= MAGIC_NUMBER;
  return sum;
}

void saveEEPROM() {
  EEPROM.put(EEPROM_STAKE_ADDR, state.stake);
  EEPROM.put(EEPROM_REWARDS_ADDR, state.rewards);
  EEPROM.put(EEPROM_BLOCKS_ADDR, state.blocks);
  EEPROM.put(EEPROM_UPTIME_ADDR, state.uptime);
  EEPROM.put(EEPROM_TODAY_UPTIME_ADDR, state.todayUptime);
  EEPROM.put(EEPROM_LAST_RESET_ADDR, state.lastReset);
  EEPROM.put(EEPROM_SLASH_COUNT_ADDR, state.slashCount);
  EEPROM.put(EEPROM_CONSECUTIVE_MISSES_ADDR, state.consecutiveMisses);
  EEPROM.put(EEPROM_LEVEL_ADDR, state.level);
  EEPROM.put(EEPROM_CHECKSUM_ADDR, calcChecksum());
  EEPROM.put(EEPROM_MAGIC_ADDR, MAGIC_NUMBER);
  EEPROM.put(EEPROM_MINER_VERSION_ADDR, EEPROM_VERSION);
  EEPROM.put(EEPROM_NODE_INDEX_ADDR, runtime.nodeIndex);
  EEPROM.put(EEPROM_RECONNECT_ATTEMPTS_ADDR, runtime.reconnectAttempts);
  EEPROM.put(EEPROM_LAST_BLOCK_ID_ADDR, state.lastBlockId);
  EEPROM.put(EEPROM_TOTAL_UPTIME_ADDR, state.totalUptime);
  EEPROM.put(EEPROM_BEST_LEVEL_ADDR, state.bestLevel);
}

uint8_t loadEEPROM() {
  uint32_t magic;
  uint32_t chk;
  uint8_t version;
  
  EEPROM.get(EEPROM_MAGIC_ADDR, magic);
  EEPROM.get(EEPROM_CHECKSUM_ADDR, chk);
  EEPROM.get(EEPROM_MINER_VERSION_ADDR, version);
  
  if (magic != MAGIC_NUMBER || chk != calcChecksum() || version != EEPROM_VERSION) {
    // Initialize with defaults
    state.stake = INITIAL_STAKE;
    state.rewards = 0;
    state.blocks = 0;
    state.uptime = 0;
    state.todayUptime = 0;
    state.lastReset = millis() / 1000;
    state.slashCount = 0;
    state.consecutiveMisses = 0;
    state.level = 1;
    state.lastBlockId = 0;
    state.totalUptime = 0;
    state.bestLevel = 1;
    runtime.nodeIndex = 0;
    runtime.reconnectAttempts = 0;
    saveEEPROM();
    return 0;
  }
  
  EEPROM.get(EEPROM_STAKE_ADDR, state.stake);
  EEPROM.get(EEPROM_REWARDS_ADDR, state.rewards);
  EEPROM.get(EEPROM_BLOCKS_ADDR, state.blocks);
  EEPROM.get(EEPROM_UPTIME_ADDR, state.uptime);
  EEPROM.get(EEPROM_TODAY_UPTIME_ADDR, state.todayUptime);
  EEPROM.get(EEPROM_LAST_RESET_ADDR, state.lastReset);
  EEPROM.get(EEPROM_SLASH_COUNT_ADDR, state.slashCount);
  EEPROM.get(EEPROM_CONSECUTIVE_MISSES_ADDR, state.consecutiveMisses);
  EEPROM.get(EEPROM_LEVEL_ADDR, state.level);
  EEPROM.get(EEPROM_NODE_INDEX_ADDR, runtime.nodeIndex);
  EEPROM.get(EEPROM_RECONNECT_ATTEMPTS_ADDR, runtime.reconnectAttempts);
  EEPROM.get(EEPROM_LAST_BLOCK_ID_ADDR, state.lastBlockId);
  EEPROM.get(EEPROM_TOTAL_UPTIME_ADDR, state.totalUptime);
  EEPROM.get(EEPROM_BEST_LEVEL_ADDR, state.bestLevel);
  
  return 1;
}

//  LEVEL MANAGEMENT 
void calcLevel() {
  state.level = (state.stake < LEVEL_STAKE_RANGE) ? 1 : ((state.stake - 1) / LEVEL_STAKE_RANGE) + 1;
  if (state.level < 1) state.level = 1;
  if (state.level > MAX_LEVEL) state.level = MAX_LEVEL;
  if (state.level > state.bestLevel) state.bestLevel = state.level;
}

uint16_t getBlockInterval() {
  uint8_t idx = (state.level > MAX_LEVEL) ? MAX_LEVEL : state.level;
  return pgm_read_word(&LEVEL_BLOCK_INTERVALS[idx]);
}

uint8_t isLevelUnlocked(uint8_t targetLevel) {
  return (state.stake >= targetLevel * LEVEL_STAKE_RANGE);
}

uint8_t getMaxUnlockedLevel() {
  uint8_t maxLevel = state.stake / LEVEL_STAKE_RANGE;
  if (maxLevel > MAX_LEVEL) maxLevel = MAX_LEVEL;
  return maxLevel;
}

//  UPTIME MANAGEMENT 
void checkDailyReset() {
  uint32_t now = millis() / 1000;
  if ((now - state.lastReset) >= DAILY_SECONDS) {
    state.todayUptime = 0;
    state.lastReset = now;
    saveEEPROM();
  }
}

void updateUptime() {
  checkDailyReset();
  state.uptime += (UPTIME_PING_INTERVAL / 1000);
  state.todayUptime += (UPTIME_PING_INTERVAL / 1000);
  state.totalUptime += (UPTIME_PING_INTERVAL / 1000);
  if (state.todayUptime > DAILY_SECONDS) state.todayUptime = DAILY_SECONDS;
  saveEEPROM();
}

// SLASHING 
void handleSlash(const char* reason) {
  uint32_t slashAmount = (uint32_t)(state.stake * SLASH_RATE);
  if (slashAmount < LEVEL_STAKE_RANGE) slashAmount = LEVEL_STAKE_RANGE;
  if (slashAmount > state.stake) slashAmount = state.stake;
  
  state.stake -= slashAmount;
  if (state.stake < LEVEL_STAKE_RANGE) state.stake = LEVEL_STAKE_RANGE;
  
  state.slashCount++;
  state.consecutiveMisses++;
  calcLevel();
  saveEEPROM();
  
  // Send slash notification
  snprintf_P(jsonBuf, JSON_BUF_SIZE,
    PSTR("{\"type\":\"slash_event\",\"amount\":%lu,\"stake\":%lu,\"level\":%lu,\"slashes\":%lu,\"reason\":\"%s\"}"),
    slashAmount, state.stake, state.level, state.slashCount, reason);
  sendJson(jsonBuf);
  
  if (state.slashCount >= BAN_THRESHOLD) {
    isBanned = 1;
    miningEnabled = 0;
    led_status_indicator(4);
    snprintf_P(jsonBuf, JSON_BUF_SIZE,
      PSTR("{\"type\":\"banned\",\"slashes\":%lu,\"until\":\"24h\"}"),
      state.slashCount);
    sendJson(jsonBuf);
  }
}

//  REWARDS 
void addReward(uint32_t reward) {
  state.rewards += reward;
  state.stake += reward;
  state.blocks++;
  state.lastBlockId = runtime.blockId;
  state.consecutiveMisses = 0;
  calcLevel();
  saveEEPROM();
  runtime.blocksAttempted++;
  led_blink(1, 50);
}

void recordMiss() {
  state.consecutiveMisses++;
  runtime.blocksMissed++;
  runtime.blocksAttempted++;
}

//  JSON BUILDERS 
void buildRegister(char* buf) {
  char username[13];
  char priv[33];
  
  strcpy_P(username, USERNAME);
  strcpy_P(priv, PRIVATE_KEY);
  
  // Generate VID
  char combo[50];
  snprintf(combo, sizeof(combo), "%s%s", username, priv);
  djb2_hash(combo, vid);
  
  // Generate Wallet
  char wHash[9];
  djb2_hash(vid, wHash);
  snprintf(wallet, sizeof(wallet), "MCR_%.8s", wHash);
  
  // Generate timestamp
  uint32_t timestamp = millis() / 1000;
  
  // Generate signature
char msg[100];
snprintf(msg, sizeof(msg), "%s%s%lu", username, wallet, timestamp);
char sigInput[150];
snprintf(sigInput, sizeof(sigInput), "%s%s", priv, msg);  // ✅ CORRECT — priv IS the public key for AVR
char sig[9];
djb2_hash(sigInput, sig);
// DEBUG: Print what's being signed
Serial.print("{\"debug\":\"signing\",\"public_key\":\"");
Serial.print(priv);
Serial.print("\",\"msg\":\"");
Serial.print(msg);
Serial.print("\",\"sig\":\"");
Serial.print(sig);
Serial.println("\"}");
  
  // Build JSON
  snprintf_P(buf, JSON_BUF_SIZE,
    PSTR("{\"type\":\"register\","
         "\"validator_id\":\"%s\","
         "\"public_key\":\"%s\","
         "\"username\":\"%s\","
         "\"wallet\":\"%s\","
         "\"stake\":%lu,"
         "\"level\":%lu,"
         "\"rewards\":%lu,"
         "\"blocks\":%lu,"
         "\"uptime\":%lu,"
         "\"today_uptime\":%lu,"
         "\"miner_type\":\"%s\","
         "\"version\":\"%s\","
         "\"timestamp\":%lu,"
         "\"signature\":\"%s\","
         "\"board\":\"%s\"}"),
    vid, priv, username, wallet, state.stake, state.level, state.rewards, state.blocks,
    state.uptime, state.todayUptime, MINER_TYPE, VERSION, timestamp, sig, BOARD_TYPE);
}

void buildUptime(char* buf) {
  snprintf_P(buf, JSON_BUF_SIZE,
    PSTR("{\"type\":\"uptime_ping\","
         "\"validator_id\":\"%s\","
         "\"username\":\"%s\","
         "\"uptime_seconds\":%lu,"
         "\"today_uptime\":%lu,"
         "\"stake\":%lu,"
         "\"level\":%lu,"
         "\"blocks_signed\":%lu,"
         "\"total_uptime\":%lu,"
         "\"best_level\":%lu}"),
    vid, USERNAME, state.uptime, state.todayUptime, state.stake, state.level, 
    state.blocks, state.totalUptime, state.bestLevel);
}

void buildSignature(char* buf) {
  char sigMsg[100];
  snprintf(sigMsg, sizeof(sigMsg), "%s%s%lu", challenge, vid, runtime.blockId);
  char sig[9];
  djb2_hash(sigMsg, sig);
  
  snprintf_P(buf, JSON_BUF_SIZE,
    PSTR("{\"type\":\"block_signature\","
         "\"validator_id\":\"%s\","
         "\"username\":\"%s\","
         "\"challenge\":\"%s\","
         "\"signature\":\"%s\","
         "\"block_id\":%lu,"
         "\"level\":%lu,"
         "\"stake\":%lu,"
         "\"blocks_signed\":%lu}"),
    vid, USERNAME, challenge, sig, runtime.blockId, state.level, state.stake, state.blocks);
}

void buildStatus(char* buf) {
  snprintf_P(buf, JSON_BUF_SIZE,
    PSTR("{\"type\":\"miner_status\","
         "\"validator_id\":\"%s\","
         "\"username\":\"%s\","
         "\"wallet\":\"%s\","
         "\"stake\":%lu,"
         "\"level\":%lu,"
         "\"blocks\":%lu,"
         "\"rewards\":%lu,"
         "\"uptime\":%lu,"
         "\"today_uptime\":%lu,"
         "\"total_uptime\":%lu,"
         "\"slashes\":%lu,"
         "\"misses\":%lu,"
         "\"best_level\":%lu,"
         "\"last_block\":%lu,"
         "\"mining\":%d,"
         "\"banned\":%d,"
         "\"board\":\"%s\","
         "\"version\":\"%s\"}"),
    vid, USERNAME, wallet, state.stake, state.level, state.blocks, state.rewards,
    state.uptime, state.todayUptime, state.totalUptime, state.slashCount, 
    state.consecutiveMisses, state.bestLevel, state.lastBlockId,
    miningEnabled, isBanned, BOARD_TYPE, VERSION);
}

void buildPong(char* buf) {
  snprintf_P(buf, JSON_BUF_SIZE,
    PSTR("{\"type\":\"pong\",\"timestamp\":%lu,\"validator_id\":\"%s\"}"),
    millis(), vid);
}

//  SEND JSON 
void sendJson(const char* buf) {
  if (buf[0] == '{') {
    Serial.println(buf);
    Serial.flush();
  }
}

// PROCESS MESSAGES
void processMessage(const char* buf) {
  // Registration response
  if (strstr_P(buf, PSTR("\"type\":\"registered\""))) {
    isRegistered = 1;
    isBanned = 0;
    runtime.reconnectAttempts = 0;
    reconnectBackoff = 0;
    led_status_indicator(6);
    
    // Parse level and reward from response
    const char* lStart = strstr_P(buf, PSTR("\"level\":"));
    if (lStart) {
      lStart += 8;
      uint32_t newLevel = 0;
      while (*lStart >= '0' && *lStart <= '9') {
        newLevel = newLevel * 10 + (*lStart - '0');
        lStart++;
      }
      if (newLevel > state.level) {
        state.level = newLevel;
        if (state.level > state.bestLevel) state.bestLevel = state.level;
        saveEEPROM();
      }
    }
    
    // Parse stake update
    const char* sStart = strstr_P(buf, PSTR("\"stake\":"));
    if (sStart) {
      sStart += 8;
      uint32_t newStake = 0;
      while (*sStart >= '0' && *sStart <= '9') {
        newStake = newStake * 10 + (*sStart - '0');
        sStart++;
      }
      if (newStake > state.stake) {
        state.stake = newStake;
        calcLevel();
        saveEEPROM();
      }
    }
    
    snprintf_P(jsonBuf, JSON_BUF_SIZE,
      PSTR("{\"type\":\"registered_ack\",\"level\":%lu,\"stake\":%lu,\"best_level\":%lu}"),
      state.level, state.stake, state.bestLevel);
    sendJson(jsonBuf);
    return;
  }
  
  // Challenge
  if (strstr_P(buf, PSTR("\"type\":\"challenge\""))) {
    if (!miningEnabled || isBanned) {
      snprintf_P(jsonBuf, JSON_BUF_SIZE,
        PSTR("{\"type\":\"challenge_skipped\",\"reason\":\"%s\"}"),
        isBanned ? "banned" : "mining_disabled");
      sendJson(jsonBuf);
      return;
    }
    
    const char* cStart = strstr_P(buf, PSTR("\"challenge\":\""));
    if (cStart) {
      cStart += 12;
      uint8_t i = 0;
      while (*cStart && *cStart != '"' && i < 32) {
        challenge[i++] = *cStart++;
      }
      challenge[i] = 0;
    }
    
    const char* bStart = strstr_P(buf, PSTR("\"block_id\":"));
    if (bStart) {
      bStart += 11;
      runtime.blockId = 0;
      while (*bStart >= '0' && *bStart <= '9') {
        runtime.blockId = runtime.blockId * 10 + (*bStart - '0');
        bStart++;
      }
    }
    
    runtime.lastChallenge = millis();
    isValidator = 1;
    led_status_indicator(2);
    
    char sigBuf[JSON_BUF_SIZE];
    buildSignature(sigBuf);
    sendJson(sigBuf);
    
    // Log challenge received
    snprintf_P(jsonBuf, JSON_BUF_SIZE,
      PSTR("{\"type\":\"challenge_received\",\"block_id\":%lu,\"level\":%lu}"),
      runtime.blockId, state.level);
    sendJson(jsonBuf);
    return;
  }
  
  // Block accepted
  if (strstr_P(buf, PSTR("\"type\":\"block_accepted\""))) {
    uint32_t reward = 0;
    const char* rStart = strstr_P(buf, PSTR("\"reward\":"));
    if (rStart) {
      rStart += 8;
      while (*rStart >= '0' && *rStart <= '9') {
        reward = reward * 10 + (*rStart - '0');
        rStart++;
      }
    }
    
    addReward(reward);
    isValidator = 0;
    led_blink(1, 50);
    
    snprintf_P(jsonBuf, JSON_BUF_SIZE,
      PSTR("{\"type\":\"block_accepted_ack\",\"block_id\":%lu,\"reward\":%lu,\"total_blocks\":%lu,\"stake\":%lu,\"level\":%lu}"),
      runtime.blockId, reward, state.blocks, state.stake, state.level);
    sendJson(jsonBuf);
    return;
  }
  
  // Block rejected
  if (strstr_P(buf, PSTR("\"type\":\"block_rejected\""))) {
    isValidator = 0;
    led_status_indicator(1);
    recordMiss();
    
    const char* rStart = strstr_P(buf, PSTR("\"reason\":\""));
    char reason[32] = "Block rejected";
    if (rStart) {
      rStart += 10;
      uint8_t i = 0;
      while (*rStart && *rStart != '"' && i < 31) {
        reason[i++] = *rStart++;
      }
      reason[i] = 0;
    }
    
    snprintf_P(jsonBuf, JSON_BUF_SIZE,
      PSTR("{\"type\":\"block_rejected_ack\",\"block_id\":%lu,\"misses\":%lu,\"reason\":\"%s\"}"),
      runtime.blockId, state.consecutiveMisses, reason);
    sendJson(jsonBuf);
    return;
  }
  
  // Slash
  if (strstr_P(buf, PSTR("\"type\":\"slash\""))) {
    const char* rStart = strstr_P(buf, PSTR("\"reason\":\""));
    char reason[32] = "Node slashing";
    if (rStart) {
      rStart += 10;
      uint8_t i = 0;
      while (*rStart && *rStart != '"' && i < 31) {
        reason[i++] = *rStart++;
      }
      reason[i] = 0;
    }
    handleSlash(reason);
    isValidator = 0;
    return;
  }
  
  // Control
  if (strstr_P(buf, PSTR("\"type\":\"miner_control\""))) {
    const char* aStart = strstr_P(buf, PSTR("\"action\":\""));
    if (aStart) {
      aStart += 10;
      if (strncmp_P(aStart, PSTR("stop"), 3) == 0) {
        miningEnabled = 0;
        isValidator = 0;
        led_off();
        sendJson(PSTR("{\"type\":\"control_response\",\"success\":true,\"action\":\"stop\"}"));
      }
      else if (strncmp_P(aStart, PSTR("start"), 4) == 0) {
        miningEnabled = 1;
        isBanned = 0;
        led_on();
        sendJson(PSTR("{\"type\":\"control_response\",\"success\":true,\"action\":\"start\"}"));
        char regBuf[JSON_BUF_SIZE];
        buildRegister(regBuf);
        sendJson(regBuf);
      }
      else if (strncmp_P(aStart, PSTR("restart"), 7) == 0) {
        miningEnabled = 0;
        isValidator = 0;
        led_off();
        delay(1000);
        miningEnabled = 1;
        isBanned = 0;
        led_on();
        char regBuf[JSON_BUF_SIZE];
        buildRegister(regBuf);
        sendJson(regBuf);
        sendJson(PSTR("{\"type\":\"control_response\",\"success\":true,\"action\":\"restart\"}"));
      }
      else if (strncmp_P(aStart, PSTR("power_save"), 10) == 0) {
        powerSavingMode = !powerSavingMode;
        if (powerSavingMode) {
          power_adjust();
          sendJson(PSTR("{\"type\":\"control_response\",\"success\":true,\"action\":\"power_save_on\"}"));
        } else {
          sendJson(PSTR("{\"type\":\"control_response\",\"success\":true,\"action\":\"power_save_off\"}"));
        }
      }
    }
    return;
  }
  
  // Status request
  if (strstr_P(buf, PSTR("\"type\":\"get_status\""))) {
    char statusBuf[JSON_BUF_SIZE];
    buildStatus(statusBuf);
    sendJson(statusBuf);
    return;
  }
  
  // Level update
  if (strstr_P(buf, PSTR("\"type\":\"level_update\""))) {
    const char* sStart = strstr_P(buf, PSTR("\"stake\":"));
    if (sStart) {
      sStart += 8;
      uint32_t newStake = 0;
      while (*sStart >= '0' && *sStart <= '9') {
        newStake = newStake * 10 + (*sStart - '0');
        sStart++;
      }
      if (newStake != state.stake) {
        state.stake = newStake;
        calcLevel();
        saveEEPROM();
        snprintf_P(jsonBuf, JSON_BUF_SIZE,
          PSTR("{\"type\":\"level_updated\",\"stake\":%lu,\"level\":%lu,\"best_level\":%lu}"),
          state.stake, state.level, state.bestLevel);
        sendJson(jsonBuf);
      }
    }
    return;
  }
  
  // Ping
  if (strstr_P(buf, PSTR("\"type\":\"ping\""))) {
    char pongBuf[JSON_BUF_SIZE];
    buildPong(pongBuf);
    sendJson(pongBuf);
    return;
  }
  
  // Peers
  if (strstr_P(buf, PSTR("\"type\":\"peers\""))) {
    // Parse first peer
    const char* pStart = strstr_P(buf, PSTR("\"peers\":[\""));
    if (pStart) {
      pStart += 10;
      uint8_t i = 0;
      while (*pStart && *pStart != '"' && i < 15) {
        nodeIP[i++] = *pStart++;
      }
      nodeIP[i] = 0;
      // Node IP saved for future reconnections
    }
    return;
  }
}

//  POWER SAVING 
void power_adjust() {
  if (powerSavingMode) {
    // Reduce clock speed if possible
    #ifdef __AVR_ATmega328P__
      // Disable ADC to save power
      ADCSRA &= ~(1 << ADEN);
      // Disable Brown-out detection
      // Disable SPI
      SPCR &= ~(1 << SPE);
    #endif
    // Reduce LED usage
    led_off();
  }
}

// SERIAL INPUT 
void readSerial() {
  while (Serial.available()) {
    char c = Serial.read();
    static uint16_t idx = 0;
    
    if (c == '\n' || c == '\r') {
      if (idx > 0) {
        jsonBuf[idx] = 0;
        processMessage(jsonBuf);
        idx = 0;
      }
    } else if (idx < JSON_BUF_SIZE - 1) {
      jsonBuf[idx++] = c;
    }
  }
}

//  STATUS REPORT 
void printStatus() {
  char statusBuf[JSON_BUF_SIZE];
  buildStatus(statusBuf);
  sendJson(statusBuf);
  
  // Debug info
  snprintf_P(tempBuf, TEMP_BUF_SIZE,
    PSTR("[STATUS] Level:%lu Interval:%u Stake:%lu Blocks:%lu Rewards:%lu Uptime:%lu Board:%s"),
    state.level, getBlockInterval(), state.stake, state.blocks, state.rewards, 
    state.uptime, BOARD_TYPE);
  Serial.println(tempBuf);
}

// WATCHDOG 
void setup_watchdog() {
  #ifndef __AVR_ATmega32U4__
    // Enable watchdog with 8 second timeout
    wdt_enable(WDTO_8S);
  #else
    // ATmega32U4 uses different watchdog setup
    wdt_enable(WDTO_4S);
  #endif
}

void reset_watchdog() {
  wdt_reset();
}

// RECONNECT BACKOFF
uint32_t getReconnectDelay() {
  uint32_t base = 5000;  // 5 seconds
  uint32_t maxDelay = 300000;  // 5 minutes
  uint32_t delay = base * (1 << reconnectBackoff);
  if (delay > maxDelay) delay = maxDelay;
  if (reconnectBackoff < 8) reconnectBackoff++;
  return delay;
}

// ==================== SETUP ====================
void setup() {
  // Initialize
  led_init();
  Serial.begin(SERIAL_BAUD);
  delay(2000);
  
  // Setup watchdog
  setup_watchdog();
  
  // Initialize random seed
  randomSeed(analogRead(0) + analogRead(1) + millis());
  
  // Load EEPROM
  loadEEPROM();
  calcLevel();
  
  // Set initial state
  isRegistered = 0;
  isValidator = 0;
  isBanned = 0;
  miningEnabled = 1;
  powerSavingMode = 0;
  reconnectBackoff = 0;
  runtime.lastPing = millis();
  runtime.lastRegAttempt = 0;
  runtime.blocksAttempted = 0;
  runtime.blocksMissed = 0;
  runtime.lastStatusReport = 0;
  
  // Send registration
  char regBuf[JSON_BUF_SIZE];
  buildRegister(regBuf);
  sendJson(regBuf);
  
  // Startup blink pattern
  led_blink(3, 100);
  delay(200);
  led_blink(2, 50);
  
  // Print startup info
  snprintf_P(jsonBuf, JSON_BUF_SIZE,
    PSTR("{\"type\":\"miner_startup\",\"version\":\"%s\",\"level\":%lu,\"stake\":%lu,\"block_interval\":%u,\"validator_id\":\"%s\",\"board\":\"%s\",\"ram\":%u,\"flash\":%u}"),
    VERSION, state.level, state.stake, getBlockInterval(), vid, BOARD_TYPE,
    RAMEND - RAMSTART);
  Serial.println(jsonBuf);
  
  led_blink(2, 100);
}

//  LOOP 
void loop() {
  // Reset watchdog
  reset_watchdog();
  
  // Process incoming messages
  readSerial();
  
  // Check for ban expiration (auto-recover after 24 hours)
  if (isBanned && millis() - state.lastReset > DAILY_SECONDS * 3) {
    isBanned = 0;
    miningEnabled = 1;
    state.slashCount = 0;
    saveEEPROM();
    snprintf_P(jsonBuf, JSON_BUF_SIZE,
      PSTR("{\"type\":\"ban_expired\",\"slashes_reset\":true}"));
    sendJson(jsonBuf);
    // Re-register after unban
    char regBuf[JSON_BUF_SIZE];
    buildRegister(regBuf);
    sendJson(regBuf);
  }
  
  // Send uptime ping every 30 seconds
  if (millis() - runtime.lastPing >= UPTIME_PING_INTERVAL) {
    runtime.lastPing = millis();
    updateUptime();
    
    if (isRegistered) {
      char upBuf[JSON_BUF_SIZE];
      buildUptime(upBuf);
      sendJson(upBuf);
    }
  }
  
  // Re-register if not registered (with backoff)
  if (!isRegistered && millis() - runtime.lastRegAttempt >= getReconnectDelay()) {
    if (!isBanned) {
      char regBuf[JSON_BUF_SIZE];
      buildRegister(regBuf);
      sendJson(regBuf);
      runtime.reconnectAttempts++;
      if (runtime.reconnectAttempts > 5) {
        led_status_indicator(5);
      }
    }
    runtime.lastRegAttempt = millis();
  }
  
  // Auto-slash if validator missed signing window
  if (isValidator && millis() - runtime.lastChallenge >= SIGNING_WINDOW_MS) {
    recordMiss();
    handleSlash("Missed signing window");
    isValidator = 0;
    led_status_indicator(3);
    snprintf_P(jsonBuf, JSON_BUF_SIZE,
      PSTR("{\"type\":\"auto_slash\",\"block_id\":%lu,\"misses\":%lu,\"consecutive\":%lu}"),
      runtime.blockId, runtime.blocksMissed, state.consecutiveMisses);
    sendJson(jsonBuf);
  }
  
  // Status indicator
  if (!isBanned) {
    if (miningEnabled) {
      if (isValidator) {
        led_status_indicator(2);
      } else if (!isRegistered) {
        led_status_indicator(5);
      } else {
        led_status_indicator(1);
      }
    } else {
      led_status_indicator(0);
    }
  }
  
  // Periodic status report (every 5 minutes)
  if (millis() - runtime.lastStatusReport >= 300000) {
    printStatus();
    runtime.lastStatusReport = millis();
  }
  
  // Power saving - reduce CPU usage
  if (powerSavingMode) {
    delay(50);
    power_adjust();
  } else {
    delay(10);
  }
}
