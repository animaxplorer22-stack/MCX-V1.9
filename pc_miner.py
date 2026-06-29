#include <EEPROM.h>
#include <avr/wdt.h>
#include <avr/pgmspace.h>
#include <avr/power.h>

// ==================== VERSION ====================
#define VERSION "8.0-MAINNET"
#define MINER_TYPE "avr"

// ==================== USER CONFIGURATION ====================
const char USERNAME[] PROGMEM = "XAVER123";                    // ← CHANGE THIS
const char PRIVATE_KEY[] PROGMEM = "MCR_A87D9AF718F62C8D073FDDFE6BC0F039";  // ← CHANGE THIS

// ==================== NETWORK CONSTANTS ====================
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

// ==================== LEVEL BLOCK INTERVALS ====================
const uint16_t LEVEL_BLOCK_INTERVALS[] PROGMEM = {0, 40, 35, 30, 25, 20, 15, 10, 9, 8, 7};

// ==================== EEPROM ADDRESSES ====================
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

// ==================== BOARD DETECTION ====================
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

// ==================== MEMORY OPTIMIZATION ====================
#if HAS_EXTRA_RAM
  #define JSON_BUF_SIZE 800
  #define TEMP_BUF_SIZE 150
#else
  #define JSON_BUF_SIZE 600
  #define TEMP_BUF_SIZE 100
#endif

// ==================== GLOBAL VARIABLES ====================
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

// ==================== LED FUNCTIONS ====================
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
    case 5: led_blink(2, 200); break;
    case 6: led_blink(3, 300); break;
  }
}

// ==================== DJB2 HASH (8 chars) — FIXED ====================
void djb2_hash(const char* in, char* out) {
  uint32_t h = 5381;
  uint8_t i = 0;
  while (in[i] && i < 200) {
    h = ((h << 5) + h) + (uint8_t)in[i];
    i++;
  }
  // ✅ REMOVED: millis(), analogRead() — now DETERMINISTIC!
  // The node must be able to verify the signature
  sprintf(out, "%08lx", h);
}

// ==================== EEPROM MANAGEMENT ====================
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

// ==================== LEVEL MANAGEMENT ====================
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

// ==================== UPTIME MANAGEMENT ====================
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

// ==================== SLASHING ====================
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

// ==================== REWARDS ====================
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

// ==================== JSON BUILDERS ====================
void buildRegister(char* buf) {
  char username[13];
  char priv[33];
  
  strcpy_P(username, USERNAME);
  strcpy_P(priv, PRIVATE_KEY);
  
  char combo[50];
  snprintf(combo, sizeof(combo), "%s%s", username, priv);
  djb2_hash(combo, vid);
  
  char wHash[9];
  djb2_hash(vid, wHash);
  snprintf(wallet, sizeof(wallet), "MCR_%.8s", wHash);
  
  uint32_t timestamp = millis() / 1000;
  
  char msg[100];
  snprintf(msg, sizeof(msg), "%s%s%lu", username, wallet, timestamp);
  char sigInput[150];
  snprintf(sigInput, sizeof(sigInput), "%s%s", priv, msg);
  char sig[9];
  djb2_hash(sigInput, sig);
  
  Serial.print("{\"debug\":\"signing\",\"public_key\":\"");
  Serial.print(priv);
  Serial.print("\",\"msg\":\"");
  Serial.print(msg);
  Serial.print("\",\"sig\":\"");
  Serial.print(sig);
  Serial.println("\"}");
  
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

// ==================== SEND JSON ====================
void sendJson(const char* buf) {
  if (buf[0] == '{') {
    Serial.println(buf);
    Serial.flush();
  }
}

// ==================== PROCESS MESSAGES ====================
void processMessage(const char* buf) {
  if (strstr_P(buf, PSTR("\"type\":\"registered\""))) {
    isRegistered = 1;
    isBanned = 0;
    runtime.reconnectAttempts = 0;
    reconnectBackoff = 0;
    led_status_indicator(6);
    
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
    
    snprintf_P(jsonBuf, JSON_BUF_SIZE,
      PSTR("{\"type\":\"challenge_received\",\"block_id\":%lu,\"level\":%lu}"),
      runtime.blockId, state.level);
    sendJson(jsonBuf);
    return;
  }
  
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
  
  if (strstr_P(buf, PSTR("\"type\":\"get_status\""))) {
    char statusBuf[JSON_BUF_SIZE];
    buildStatus(statusBuf);
    sendJson(statusBuf);
    return;
  }
  
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
  
  if (strstr_P(buf, PSTR("\"type\":\"ping\""))) {
    char pongBuf[JSON_BUF_SIZE];
    buildPong(pongBuf);
    sendJson(pongBuf);
    return;
  }
  
  if (strstr_P(buf, PSTR("\"type\":\"peers\""))) {
    const char* pStart = strstr_P(buf, PSTR("\"peers\":[\""));
    if (pStart) {
      pStart += 10;
      uint8_t i = 0;
      while (*pStart && *pStart != '"' && i < 15) {
        nodeIP[i++] = *pStart++;
      }
      nodeIP[i] = 0;
    }
    return;
  }
}

// ==================== POWER SAVING ====================
void power_adjust() {
  if (powerSavingMode) {
    #ifdef __AVR_ATmega328P__
      ADCSRA &= ~(1 << ADEN);
      SPCR &= ~(1 << SPE);
    #endif
    led_off();
  }
}

// ==================== SERIAL INPUT ====================
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
    } else {
      idx = 0;
      Serial.println("{\"type\":\"error\",\"message\":\"Buffer overflow\"}");
    }
  }
}

// ==================== STATUS REPORT ====================
void printStatus() {
  char statusBuf[JSON_BUF_SIZE];
  buildStatus(statusBuf);
  sendJson(statusBuf);
  
  snprintf_P(tempBuf, TEMP_BUF_SIZE,
    PSTR("[STATUS] Level:%lu Interval:%u Stake:%lu Blocks:%lu Rewards:%lu Uptime:%lu Board:%s"),
    state.level, getBlockInterval(), state.stake, state.blocks, state.rewards, 
    state.uptime, BOARD_TYPE);
  Serial.println(tempBuf);
}

// ==================== WATCHDOG ====================
void setup_watchdog() {
  #ifndef __AVR_ATmega32U4__
    wdt_enable(WDTO_8S);
  #else
    wdt_enable(WDTO_4S);
  #endif
}

void reset_watchdog() {
  wdt_reset();
}

// ==================== RECONNECT BACKOFF ====================
uint32_t getReconnectDelay() {
  uint32_t base = 5000;
  uint32_t maxDelay = 300000;
  uint32_t delay = base * (1 << reconnectBackoff);
  if (delay > maxDelay) delay = maxDelay;
  if (reconnectBackoff < 8) reconnectBackoff++;
  return delay;
}

// ==================== SETUP ====================
void setup() {
  led_init();
  Serial.begin(SERIAL_BAUD);
  delay(2000);
  
  setup_watchdog();
  randomSeed(analogRead(0) + analogRead(1) + millis());
  
  loadEEPROM();
  calcLevel();
  
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
  
  char regBuf[JSON_BUF_SIZE];
  buildRegister(regBuf);
  sendJson(regBuf);
  
  led_blink(3, 100);
  delay(200);
  led_blink(2, 50);
  
  snprintf_P(jsonBuf, JSON_BUF_SIZE,
    PSTR("{\"type\":\"miner_startup\",\"version\":\"%s\",\"level\":%lu,\"stake\":%lu,\"block_interval\":%u,\"validator_id\":\"%s\",\"board\":\"%s\",\"ram\":%u,\"flash\":%u}"),
    VERSION, state.level, state.stake, getBlockInterval(), vid, BOARD_TYPE,
    RAMEND - RAMSTART);
  Serial.println(jsonBuf);
  
  led_blink(2, 100);
}

// ==================== LOOP ====================
void loop() {
  reset_watchdog();
  readSerial();
  
  if (isBanned && millis() - state.lastReset > DAILY_SECONDS * 3) {
    isBanned = 0;
    miningEnabled = 1;
    state.slashCount = 0;
    saveEEPROM();
    snprintf_P(jsonBuf, JSON_BUF_SIZE,
      PSTR("{\"type\":\"ban_expired\",\"slashes_reset\":true}"));
    sendJson(jsonBuf);
    char regBuf[JSON_BUF_SIZE];
    buildRegister(regBuf);
    sendJson(regBuf);
  }
  
  if (millis() - runtime.lastPing >= UPTIME_PING_INTERVAL) {
    runtime.lastPing = millis();
    updateUptime();
    if (isRegistered) {
      char upBuf[JSON_BUF_SIZE];
      buildUptime(upBuf);
      sendJson(upBuf);
    }
  }
  
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
  
  if (millis() - runtime.lastStatusReport >= 300000) {
    printStatus();
    runtime.lastStatusReport = millis();
  }
  
  if (powerSavingMode) {
    delay(50);
    power_adjust();
  } else {
    delay(10);
  }
}

    # ==================== WEBSOCKET COMMUNICATION ====================
    async def register(self):
        timestamp = int(time.time())
        
        # ========== FIX: Registration signature = make_signature() ==========
        msg_to_sign = f"{self.wallet.username}{self.wallet.address}{timestamp}"
        signature = self.wallet.sign(msg_to_sign)
        
        self.update_today_uptime()
        
        msg = {
            "type": "register",
            "validator_id": self.validator_id,
            "username": self.wallet.username,
            "public_key": self.wallet.public_key_pem,
            "wallet": self.wallet.address,
            "stake": self.current_stake,
            "level": self.current_level,
            "rewards": self.total_rewards,
            "blocks": self.blocks_signed,
            "uptime": self.total_uptime,
            "today_uptime": self.today_uptime,
            "miner_type": MINER_TYPE,
            "version": VERSION,
            "timestamp": timestamp,
            "signature": signature
        }
        
        if self.websocket:
            await self.websocket.send(json.dumps(msg))
            self.add_log(f"[REG] Registered as '{self.wallet.username}' (Level {self.current_level})", "info")
    
    async def send_uptime_ping(self):
        self.update_today_uptime()
        msg = {
            "type": "uptime_ping",
            "validator_id": self.validator_id,
            "username": self.wallet.username,
            "uptime_seconds": self.total_uptime,
            "today_uptime": self.today_uptime,
            "stake": self.current_stake,
            "level": self.current_level
        }
        if self.websocket:
            await self.websocket.send(json.dumps(msg))
    
    async def sign_block(self):
        # ========== FIX: Block signature = make_signature() ==========
        msg_to_sign = f"{self.current_challenge}{self.validator_id}{self.current_block_id}"
        signature = self.wallet.sign(msg_to_sign)
        
        msg = {
            "type": "block_signature",
            "validator_id": self.validator_id,
            "username": self.wallet.username,
            "challenge": self.current_challenge,
            "signature": signature,
            "level": self.current_level,
            "stake": self.current_stake,
            "block_id": self.current_block_id,
            "timestamp": time.time()
        }
        
        if self.websocket:
            await self.websocket.send(json.dumps(msg))
            self.add_log(f"[SIGN] Signed block {self.current_block_id} (Level {self.current_level})", "success")
    
    async def send_status(self):
        msg = {
            "type": "miner_status",
            "validator_id": self.validator_id,
            "username": self.wallet.username,
            "stake": self.current_stake,
            "level": self.current_level,
            "blocks": self.blocks_signed,
            "rewards": self.total_rewards,
            "uptime": self.total_uptime,
            "today_uptime": self.today_uptime,
            "mining": self.mining_enabled
        }
        if self.websocket:
            await self.websocket.send(json.dumps(msg))
    
    # ==================== MESSAGE HANDLING ====================
    async def handle_message(self, data: str):
        try:
            msg = json.loads(data)
            msg_type = msg.get("type")
            
            if msg_type == "registered":
                self.add_log(f"[NODE] ✅ Registration confirmed | Level: {msg.get('level')} | Reward: {msg.get('current_reward')} MCX/block", "success")
                self.reconnect_attempts = 0
                self.is_banned = False
            
            elif msg_type == "peers":
                for peer in msg.get("peers", []):
                    self.add_peer_from_gossip(peer)
                self.add_log(f"[GOSSIP] Received {len(msg.get('peers', []))} peers from node", "info")
            
            elif msg_type == "challenge":
                if not self.mining_enabled or self.is_banned:
                    self.add_log("[MINING] Mining disabled or banned, ignoring challenge", "warning")
                    return
                
                self.current_challenge = msg.get("challenge", "")
                self.current_block_id = msg.get("block_id", 0)
                self.last_challenge_time = time.time()
                self.is_validator = True
                await self.sign_block()
                
                if self.challenge_timeout_task:
                    self.challenge_timeout_task.cancel()
                
                async def timeout_handler():
                    await asyncio.sleep(SIGNING_WINDOW_MS / 1000)
                    if self.is_validator:
                        self.record_miss(self.current_block_id, "Timeout")
                        self.handle_slash()
                        self.is_validator = False
                
                self.challenge_timeout_task = asyncio.create_task(timeout_handler())
            
            elif msg_type == "block_accepted":
                if self.challenge_timeout_task:
                    self.challenge_timeout_task.cancel()
                reward = msg.get("reward", 18)
                level = msg.get("level", 1)
                self.last_block_id = self.current_block_id
                self.add_reward(reward, self.current_block_id, level)
                self.is_validator = False
                self.add_log(f"[NODE] ✅ Block {msg.get('block_id')} ACCEPTED! +{reward} MCX", "success")
            
            elif msg_type == "block_rejected":
                if self.challenge_timeout_task:
                    self.challenge_timeout_task.cancel()
                self.is_validator = False
                self.add_log(f"[NODE] ❌ Block {msg.get('block_id')} REJECTED", "error")
            
            elif msg_type == "slash":
                self.add_log("[NODE] ⚠️ Slash command received", "error")
                amount = msg.get("amount", 0)
                reason = msg.get("reason", "Node slashing")
                self.handle_slash(amount, reason)
                self.is_validator = False
            
            elif msg_type == "level_update":
                new_stake = msg.get("stake", self.current_stake)
                if new_stake != self.current_stake:
                    self.current_stake = new_stake
                    self.current_level = self.calculate_level()
                    if self.current_level > self.best_level:
                        self.best_level = self.current_level
                    self.stats_db.save_stat('stake', self.current_stake)
                    self.stats_db.save_stat('level', self.current_level)
                    self.stats_db.save_stat('best_level', self.best_level)
                    self.add_log(f"[NODE] Level update: Level {self.current_level} (Stake: {self.current_stake} MCX)", "info")
            
            elif msg_type == "control":
                action = msg.get("action")
                if action == "stop":
                    self.add_log("[CONTROL] ⏹ Stop command received - stopping mining", "warning")
                    self.mining_enabled = False
                    self.is_validator = False
                elif action == "start":
                    self.add_log("[CONTROL] ▶️ Start command received - resuming mining", "success")
                    self.mining_enabled = True
                elif action == "restart":
                    self.add_log("[CONTROL] 🔄 Restart command received", "info")
                    self.mining_enabled = False
                    self.is_validator = False
                    await asyncio.sleep(1)
                    self.mining_enabled = True
                elif action == "status":
                    await self.send_status()
                elif action == "power_save_on":
                    self.battery_saver = True
                    self.add_log("[CONTROL] 💤 Power saving ENABLED", "info")
                elif action == "power_save_off":
                    self.battery_saver = False
                    self.add_log("[CONTROL] ⚡ Power saving DISABLED", "info")
                
                ack = {"type": "control_ack", "action": action, "success": True}
                if self.websocket:
                    await self.websocket.send(json.dumps(ack))
            
            elif msg_type == "get_status":
                await self.send_status()
            
            elif msg_type == "balance":
                if msg.get("stake"):
                    self.current_stake = msg["stake"]
                    self.current_level = self.calculate_level()
                    self.stats_db.save_stat('stake', self.current_stake)
                    self.stats_db.save_stat('level', self.current_level)
            
            elif msg_type == "error":
                self.add_log(f"[NODE] ❌ Error: {msg.get('message', 'Unknown')}", "error")
            
            else:
                self.add_log(f"[DEBUG] Unhandled message type: {msg_type}", "info")
        
        except json.JSONDecodeError:
            self.add_log(f"[ERROR] Invalid JSON: {data[:100]}", "error")
        except Exception as e:
            self.add_log(f"[ERROR] Message handling: {e}", "error")
    
    # ==================== CONNECTION LOOP ====================
    async def connect_and_run(self):
        self.reconnect_attempts = 0
        reconnect_delay = RECONNECT_BASE_DELAY
        
        while self.running:
            peer_url = self.get_current_peer_url()
            if not peer_url:
                self.add_log("[ERROR] No peers available. Check BOOTSTRAP_NODES", "error")
                await asyncio.sleep(30)
                self.peers = get_bootstrap_peers_with_cache()
                self.discovered_peers = set(self.peers)
                continue
            
            try:
                self.add_log(f"[CONN] Connecting to {peer_url}...", "info")
                
                async with websockets.connect(
                    peer_url,
                    ping_interval=20,
                    ping_timeout=10,
                    close_timeout=5,
                    max_size=10_000_000
                ) as ws:
                    self.websocket = ws
                    self.connected = True
                    self.reconnect_attempts = 0
                    reconnect_delay = RECONNECT_BASE_DELAY
                    self.add_log(f"[CONN] ✅ Connected to {peer_url}", "success")
                    
                    await ws.send(json.dumps({"type": "get_peers"}))
                    await self.register()
                    
                    # Flush buffered messages
                    with self.buffer_lock:
                        while self.message_buffer:
                            try:
                                await ws.send(self.message_buffer.popleft())
                            except:
                                break
                    
                    while self.running and self.mining_enabled and self.connected:
                        if time.time() - self.last_uptime_ping > UPTIME_PING_INTERVAL:
                            await self.send_uptime_ping()
                            self.last_uptime_ping = time.time()
                        
                        if time.time() - self.last_status_report > STATUS_INTERVAL:
                            self.print_status()
                            self.last_status_report = time.time()
                        
                        if time.time() - self.last_heartbeat > HEARTBEAT_INTERVAL:
                            await ws.send(json.dumps({"type": "ping", "timestamp": time.time()}))
                            self.last_heartbeat = time.time()
                        
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
                            await self.handle_message(raw)
                        except asyncio.TimeoutError:
                            pass
                        
                        if self.is_validator and (time.time() - self.last_challenge_time) > (SIGNING_WINDOW_MS / 1000 + 0.5):
                            self.add_log(f"[TIMEOUT] Fallback timeout! Missed block {self.current_block_id}", "error")
                            self.record_miss(self.current_block_id, "Fallback timeout")
                            self.handle_slash()
                            self.is_validator = False
                        
                        # Check ban status
                        if self.is_banned:
                            if time.time() > self.banned_until:
                                self.is_banned = False
                                self.slash_count = 0
                                self.mining_enabled = True
                                self.add_log("[BAN] Ban expired! Resuming mining.", "success")
                                await self.register()
                        
                        await asyncio.sleep(0.05)
            
            except websockets.exceptions.ConnectionClosed as e:
                self.add_log(f"[CONN] Connection closed: {e}", "error")
                self.connected = False
            except Exception as e:
                self.add_log(f"[CONN] Connection error: {e}", "error")
                self.connected = False
            
            if not self.running:
                break
            
            # Exponential backoff
            self.switch_to_next_peer()
            reconnect_delay = min(reconnect_delay * 2, RECONNECT_MAX_DELAY)
            self.add_log(f"[CONN] Reconnecting in {reconnect_delay:.0f}s...", "info")
            await asyncio.sleep(reconnect_delay)
        
        self.websocket = None
    
    def print_status(self):
        uptime = int(time.time() - self.start_time)
        hours = uptime // 3600
        minutes = (uptime % 3600) // 60
        today_hours = self.today_uptime / 3600
        
        success_rate = 0
        total = self.blocks_signed + self.consecutive_misses
        if total > 0:
            success_rate = (self.blocks_signed / total) * 100
        
        print("\n" + "=" * 60)
        print("💻 MICROCORE PC MINER STATUS")
        print("=" * 60)
        print(f"Username: {self.wallet.username}")
        print(f"Wallet: {self.wallet.address[:24]}...")
        print(f"Validator ID: {self.validator_id[:20]}...")
        print("-" * 40)
        print(f"Level: {self.current_level} / {MAX_LEVEL}")
        print(f"Best Level: {self.best_level}")
        print(f"Stake: {self.current_stake:,} MCX")
        print(f"Block Interval: {self.get_block_interval()} seconds")
        print(f"Rewards: {self.total_rewards:,} MCX")
        print(f"Blocks Signed: {self.blocks_signed}")
        print(f"Missed Blocks: {self.consecutive_misses}")
        print(f"Success Rate: {success_rate:.1f}%")
        print(f"Slash Count: {self.slash_count} / {BAN_THRESHOLD}")
        print(f"Banned: {'⚠️ YES' if self.is_banned else '✅ NO'}")
        print("-" * 40)
        print(f"Total Uptime: {hours}h {minutes}m")
        print(f"Today's Uptime: {today_hours:.1f}h / 24h")
        print(f"Peers in Cache: {len(self.discovered_peers)}")
        print(f"Node Switches: {self.node_switch_count}")
        print(f"Mining: {'🟢 ACTIVE' if self.mining_enabled else '🔴 STOPPED'}")
        print(f"Connected: {'✅ YES' if self.connected else '❌ NO'}")
        print(f"Battery Saver: {'✅ ON' if self.battery_saver else '❌ OFF'}")
        print("=" * 60 + "\n")
    
    async def run(self):
        print("\n" + "=" * 60)
        print("💻 MICROCORE PC MINER v8.0 💻")
        print("ECDSA secp256k1 | Gossip Discovery | No DNS")
        print("10 Levels | 1,000 MCX/level | Permanent Towers")
        print("=" * 60)
        print(f"Username: {self.wallet.username}")
        print(f"Wallet: {self.wallet.address}")
        print(f"Validator ID: {self.validator_id[:20]}...")
        print("-" * 40)
        print(f"Initial Stake: {self.current_stake} MCX")
        print(f"Initial Level: {self.current_level}")
        print(f"Block Interval: {self.get_block_interval()} seconds")
        print(f"Signing Window: {SIGNING_WINDOW_MS} ms")
        print(f"Slash Rate: {SLASH_RATE * 100}%")
        print("-" * 40)
        print(f"Bootnodes: {self.peers[:3] if self.peers else 'None'}")
        print(f"Peers in cache: {len(self.discovered_peers)}")
        print(f"Battery Saver: {'✅ ON' if self.battery_saver else '❌ OFF'}")
        print(f"Background Mode: {'✅ ON' if self.background_mode else '❌ OFF'}")
        print("=" * 60)
        print("\n🚀 Miner starting... Press Ctrl+C to stop\n")
        
        await self.connect_and_run()

# ==================== MAIN ====================
async def main():
    print("\n" + "=" * 60)
    print("💻 MICROCORE PC MINER v8.0 — MAINNET READY 💻")
    print("=" * 60)
    
    # Check if wallet exists
    wallet = None
    if os.path.exists(WALLET_FILE):
        password = getpass.getpass("Enter wallet password: ")
        wallet = Wallet.load_encrypted(WALLET_FILE, password)
        if wallet:
            print(f"\n✅ Wallet loaded: {wallet.username}")
        else:
            print("\n❌ Failed to load wallet. Wrong password?")
            print("   Try deleting wallet file and creating new one.")
            return
    else:
        print("\n[FIRST RUN] No wallet found.")
        username = input("Enter your username: ").strip()
        if not username:
            username = f"pc_miner_{int(time.time())}"
        
        password = getpass.getpass("Enter password for wallet encryption: ")
        confirm = getpass.getpass("Confirm password: ")
        
        if password != confirm:
            print("[ERROR] Passwords do not match!")
            return
        
        wallet = Wallet.create_new(username)
        wallet.save_encrypted(WALLET_FILE, password)
        print(f"\n✅ Wallet created and encrypted!")
        print(f"   Username: {wallet.username}")
        print(f"   Address: {wallet.address}")
        print(f"\n⚠️ SAVE THESE CREDENTIALS!")
        print(f"   Wallet file: {os.path.abspath(WALLET_FILE)}")
    
    miner = PCMiner(wallet)
    
    try:
        await miner.run()
    except asyncio.CancelledError:
        print("\n[SHUTDOWN] Miner cancelled")
    except KeyboardInterrupt:
        print("\n[SHUTDOWN] Miner stopped by user")
    finally:
        miner.save_stats()
        miner.stats_db.close()
        print(f"\n📊 FINAL STATS")
        print(f"   Rewards: {miner.total_rewards} MCX")
        print(f"   Blocks: {miner.blocks_signed}")
        print(f"   Slashes: {miner.slash_count}")
        print(f"   Node Switches: {miner.node_switch_count}")
        print(f"   Final Stake: {miner.current_stake} MCX")
        print(f"   Final Level: {miner.current_level}")
        print(f"   Best Level: {miner.best_level}")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[EXIT] Goodbye!")
        sys.exit(0)
