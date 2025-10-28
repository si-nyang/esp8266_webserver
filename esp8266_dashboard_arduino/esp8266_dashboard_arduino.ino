// web server
#include <ESP8266WiFi.h>
#include <ESP8266HTTPClient.h>
#include <WiFiClient.h>
#include <ESP8266WebServer.h>
#include <ArduinoJson.h>
#include <time.h>

// sensor
#include <Wire.h>
#include <SoftwareSerial.h>
#include "sensor_defs.h"
#include "st7789v.h"

// screen
#include <Adafruit_GFX.h>
#include <Adafruit_ST7789.h>
#include <SPI.h>

#include <Fonts/FreeSansBold24pt7b.h>
#include <Fonts/FreeSansBold12pt7b.h>
#include <Fonts/FreeSansBold9pt7b.h>
#include <Fonts/FreeSans9pt7b.h>

// WiFi id, password key
#ifndef STASSID
#define STASSID "신양의 iPhone"
#define STAPSK "sinyang721"
#endif

// client auth: request 보안용
const char* CLIENT_LOGIN = "admin";
const char* CLIENT_PASSWORD = "esp12f";

const char *ssid = STASSID;
const char *password = STAPSK;

String g_strDate;
String g_strDayOfWeek;
int g_iHour;
int g_iMinute;

float g_fTemp;
float g_fHumid;
float g_avg1m;
float g_avg10m;
int g_pm25; // 초미세먼지
int g_pm10; // 미세먼지

unsigned long g_lastSensorUpdate = 0;
unsigned long g_lastScreenUpdate = 0;

DynamicJsonDocument doc(10);

ESP8266WebServer server(80); // http 요청 처리용 포트
SoftwareSerial pmsSerial(SOFT_RX, SOFT_TX); // SoftwareSerial(RX, TX)
uint8_t pmsBuffer[PM_FRAME_SIZE];

int sensorI2Ctx(uint8_t sensorAddr, const uint8_t *txBuffer, uint8_t iLen)
{
  Wire.beginTransmission(sensorAddr);
  Wire.write(txBuffer, iLen);
  return Wire.endTransmission();
  // 0: success, 1: legnth over, 2: NACK(기기 x), 3: NACK(전송 실패), 4: others
}

int sensorI2Crx(uint8_t sensorAddr, uint8_t *rxBuffer, uint8_t iLen)
{ 
  Wire.requestFrom(sensorAddr, iLen);
  for( int i = 0; i < iLen; i++)
  {
    rxBuffer[i] = Wire.read();
  }
  return 0;
}

class AM2320 
{
  private:
  int wakeUp()
  { 
    uint8_t dummy[1] = {0x00};
    int ack;

    for(int i = 0; i < MAX_RETRY; i++)
    {
      ack = sensorI2Ctx(AM2320_ADDR, dummy, 1);
      if(ack == ACK) break;
    }
    if(ack != ACK) return NACK;
    
    return ACK;
  }

  uint16_t crc16(uint8_t *buffer, uint8_t nbytes) {
    uint16_t crc = 0xffff;
    for (int i = 0; i < nbytes; i++) {
      uint8_t b = buffer[i];
      crc ^= b;
      for (int x = 0; x < 8; x++) {
        if (crc & 0x0001) {
          crc >>= 1;
          crc ^= 0xA001;
        } else {
          crc >>= 1;
        }
      }
    }
    return crc;
  }

  public:
  float readRegi(uint8_t regiAddr)
  {
    float fResult;
    uint8_t txBuffer[AM2320TX_BUFSIZE] = {0};
    uint8_t rxBuffer[AM2320RX_BUFSIZE] = {0};
    uint16_t the_crc;
    uint16_t data;
    int ack = wakeUp();
    if(ack != ACK) return 0xFFFF;
    delay(AM2320_READY_WAITING);

    // tx
    txBuffer[AM2320TX_FUNC_CODE] = AM2320_CMD_READREG; 
    txBuffer[AM2320TX_START_ADDR] = regiAddr;
    txBuffer[AM2320TX_REGI_NUM] = AM2320_READ_LEN; // high, low
    sensorI2Ctx(AM2320_ADDR, txBuffer, AM2320TX_BUFSIZE);
    delay(AM2320_SENSOR_WAITING);

    // rx
    sensorI2Crx(AM2320_ADDR, rxBuffer, AM2320RX_BUFSIZE); 

    if (rxBuffer[AM2320RX_FUNC_CODE] != AM2320_CMD_READREG) return 0xFFFF; // must be 0x03 modbus reply
    if (rxBuffer[AM2320RX_REGI_NUM] != AM2320_READ_LEN) return 0xFFFF; // must be 2 bytes reply

    // CRC check
    the_crc = rxBuffer[AM2320RX_CRC_LOW]; // row byte first come
    the_crc <<= 8;
    the_crc |= rxBuffer[AM2320RX_CRC_HIGH];
    if (the_crc != crc16(rxBuffer, AM2320RX_BUFSIZE - 2)) 
    {
      Serial.println("crc error");
      return  0xFFFF;
    }

    // data
    data = ((uint16_t(rxBuffer[AM2320RX_DATA_HIGH]) << 8) | uint16_t(rxBuffer[AM2320RX_DATA_LOW]));

    if (data == 0xFFFF) return 0xFFFF;
    if(regiAddr == AM2320_REG_TEMP_H)
    {
      if (data & 0x8000) fResult = float(-(data & 0x7FFF) / 10.0);
      else fResult = float((data & 0xFFFF) / 10.0);
    }
    else fResult = float(data) / 10.0;

    return fResult;
  }
};

class GDK101 // gamma sensor
{
  private:

  public:
  void reset()
  {
    // tx
    uint8_t txBuffer[GDK101_RESET_CHECK_BIT] = {0};
    if(sensorI2Ctx(GDK101_ADDR, txBuffer, GDK101_RESET_CHECK_BIT) == 0)
    {
      delay(GDK101_WAITING);
      // rx
      uint8_t rxBuffer[GDK101_RESET_CHECK_BIT] = {0};
      sensorI2Crx(GDK101_ADDR, rxBuffer, GDK101_RESET_CHECK_BIT);

      Serial.print("Reset Response\t\t\t");
      if(rxBuffer[GDK101_RESET_CHECK_BIT] != GDK101_RESET_FAIL) Serial.println("Reset Success.");
      else Serial.println("Reset Fail.");
    }
    else
    {
      Serial.println("cannot reset.");
    }
  }

  float sendCMD(uint8_t cmd)
  {
    // tx
    uint8_t txBuffer[GDK101TX_BUFSIZE] = {cmd};
    sensorI2Ctx(GDK101_ADDR, txBuffer, GDK101TX_BUFSIZE);
    delay(GDK101_WAITING);
    
    // rx
    uint8_t rxBuffer[GDK101RX_BUFSIZE] = {0};
    sensorI2Crx(GDK101_ADDR, rxBuffer, GDK101RX_BUFSIZE);

    float fResult;
    fResult = rxBuffer[GDK101_DATA_INT] + (float)rxBuffer[GDK101_DATA_DEC]/100;

    return fResult;
  }
};

class PMG7
{
  private:
  uint16_t calculateCheckSum()
  {
    uint16_t iTemp = 0;
    for(int i = 0; i < PM_FRAME_SIZE - CHECKSUM_LEN; i++)
    {
      iTemp += pmsBuffer[i];
    }
    return iTemp;
  }

  public:
  bool setPMSdata()
  {
    uint16_t iCheckSum;
    uint16_t the_checkSum;

    if(pmsBuffer[0] != FRAME_HEADER1 || pmsBuffer[1] != FRAME_HEADER2)
    {
      Serial.println("Fail to load data");
      return false;
    }

    iCheckSum = calculateCheckSum();
    the_checkSum = ((uint16_t)pmsBuffer[PM_FRAME_SIZE - CHECKSUM_LEN] << 8) | ((uint16_t)pmsBuffer[PM_FRAME_SIZE - CHECKSUM_LEN + 1]);
    if(iCheckSum != the_checkSum)
    {
      Serial.println("checkSum err");
      return false;
    }

    // 대기질 data 4 ~ 6 = [10:15]
    // g_pm1 = (pmsBuffer[PM1_DATA_HIGH] << 8) | pmsBuffer[PM1_DATA_LOW];
    g_pm25 = (pmsBuffer[PM25_DATA_HIGH] << 8) | pmsBuffer[PM25_DATA_LOW];
    g_pm10 = (pmsBuffer[PM10_DATA_HIGH] << 8) | pmsBuffer[PM10_DATA_LOW];

    return true;
  }
};

void printResult()
{
  Serial.print("Temp: ");
  Serial.print(g_fTemp);
  Serial.print(" *C, Humidity: ");
  Serial.print(g_fHumid);
  Serial.println(" %");
  Serial.print("Measuring Value(10min avg)\t");
  Serial.print(g_avg10m); Serial.println(" uSv/hr");
  Serial.print("Measuring Value(1min avg)\t");
  Serial.print(g_avg1m); Serial.println(" uSv/hr");
  // Serial.printf("PM 1.0: %d ug/m3\r\n", g_pm1);
  Serial.printf("PM 2.5: %d ug/m3\r\n", g_pm25);
  Serial.printf("PM  10: %d ug/m3\r\n", g_pm10);
}

AM2320 am2320;
GDK101 gdk101;
PMG7 pmg7;
Adafruit_ST7789 tft = Adafruit_ST7789(TFT_CS, TFT_DC, TFT_RST);
WiFiClient client;
HTTPClient http;

// 2초마다 sensor data update: millis() 사용
void updateSensor()
{
  bool PMSsuccess;

  g_fTemp = am2320.readRegi(AM2320_REG_TEMP_H);
  g_fHumid = am2320.readRegi(AM2320_REG_HUM_H);
  g_avg10m = gdk101.sendCMD(GDK101_CMD_AVG_10M);
  g_avg1m = gdk101.sendCMD(GDK101_CMD_AVG_1M);

  for(int i = 0; i < MAX_RETRY; i++)
  {
    if (pmsSerial.available() >= PM_FRAME_SIZE) {
      for (int i = 0; i < PM_FRAME_SIZE; i++) {
        pmsBuffer[i] = pmsSerial.read();
      }
      PMSsuccess = pmg7.setPMSdata();
      
    } else break;

    if(PMSsuccess) break;
  }
  if(!PMSsuccess) 
  {
    Serial.println("Fail to get PMS data");
  }
  
  printResult();
  Serial.println("================================================");
}

void serverSet()
{
  Serial.println("Connecting as station...");
  WiFi.mode(WIFI_STA);

  // home config
  // IPAddress local_IP(192, 168, 219, 50);   // 원하는 고정 IP (DHCP 범위와 충돌 안 나게)
  // IPAddress gateway(192, 168, 219, 1);     // 공유기 주소
  // IPAddress subnet(255, 255, 255, 0);      // 일반적인 서브넷
  // IPAddress dns(8, 8, 8, 8);               // DNS (선택)
  // if (!WiFi.config(local_IP, gateway, subnet, dns)) {
  //   Serial.println("WiFi.config failed");
  // }

  WiFi.begin(ssid, password);

  // 연결 대기 (최대 15초)
  uint32_t t0 = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - t0 < 15000) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("");

  if (WiFi.status() == WL_CONNECTED) {
    Serial.print("Connected to ");
    Serial.println(ssid);
    Serial.print("IP address: ");
    Serial.println(WiFi.localIP());
  } else {
    Serial.println("WiFi connect failed");
  }
}

bool serverAuthCheck()
{
  bool bTemp = true;

  if (!server.authenticate(CLIENT_LOGIN, CLIENT_PASSWORD)) {
    String message1 = "Error 403 - Authentication Failed!";
    Serial.println(message1);
    server.send(403, "text/plain", message1);
    bTemp = false;
  } 

  return bTemp;
}

void handleNotFound()
{
  String message = "404 Not Found\n\n";
  message += "The requested URL was not found on this server.\n";
  message += "URI: ";
  message += server.uri();
  message += "\n";
  server.send(404, "text/plain", message);
}

void handleSnapshot()
{
  if(!serverAuthCheck()) return;

  Serial.println("*** JSON Requested : Snapshot ***");
  doc["Temperature"] = g_fTemp;
  doc["Humidity"] = g_fHumid;
  doc["GammaAverage1m"] = g_avg1m;
  doc["GammaAverage10m"] = g_avg10m;
  doc["PM2_5"] = g_pm25;
  doc["PM10"] = g_pm10;

  String json = "";
  serializeJson(doc, json); // doc -> json으로 직렬화 -> String으로 저장

  Serial.print("Sent: ");
  Serial.println(json);
  Serial.println("");
  server.send(200, "application/json", json);

}

const char* ntpServer = "pool.ntp.org";
uint8_t timeZone = 9;
uint8_t summerTime = 0; // 3600

void GetTime()
{
  struct tm timeinfo;
  if(!getLocalTime(&timeinfo)){
    Serial.println("Failed to obtain time");
    return;
  }
  char buf[40];
  strftime(buf, sizeof(buf), "%A, %B %d %Y %H:%M:%S", &timeinfo);
  Serial.println(buf);

  char bufDate[16];
  strftime(bufDate, sizeof(bufDate), "%Y.%m.%d", &timeinfo);
  g_strDate = bufDate;

  char bufDay[8];
  strftime(bufDay, sizeof(bufDay), "%a", &timeinfo); // Mon/Tue/Wed...
  g_strDayOfWeek = String(bufDay);
  g_strDayOfWeek.toUpperCase();

  g_iHour   = timeinfo.tm_hour;
  g_iMinute = timeinfo.tm_min;
}

// ── 헬퍼 ───────────────────────────────────────────
static void setFont9B()  { tft.setFont(&FreeSansBold9pt7b);  }
static void setFont12B() { tft.setFont(&FreeSansBold12pt7b); }
static void setFont24B() { tft.setFont(&FreeSansBold24pt7b); }
static void setFont9()   { tft.setFont(&FreeSans9pt7b);      }

uint16_t COL_BG, COL_CARD, COL_TEXT, COL_LINE, COL_OK, COL_WARN, COL_SUB;

static void printLeft(int16_t x, int16_t y, const String& s, uint16_t color) 
{
  tft.setTextColor(color);
  tft.setCursor(x, y);
  tft.print(s);
}

static void printRight(int16_t xr, int16_t y, const String& s, uint16_t color) 
{
  int16_t x1, y1; uint16_t w, h;
  tft.getTextBounds(s, 0, y, &x1, &y1, &w, &h);
  tft.setTextColor(color);
  tft.setCursor(xr - (int16_t)w, y);
  tft.print(s);
}

static void drawDegreeDot(int16_t cx, int16_t cy, uint16_t color) 
{
  tft.fillCircle(cx, cy - 9, 2, color);
}

// ── 값 컬러 (실내 기준 3단계) ───────────────────────────────
static uint16_t pm25Color(float pm25)
{
  if (pm25 <= 15) return COL_OK;         // 좋음
  if (pm25 <= 35) return COL_WARN;       // 보통
  return tft.color565(220, 68, 55);      // 나쁨
}

static uint16_t pm10Color(float pm10)
{
  if (pm10 <= 30) return COL_OK;
  if (pm10 <= 80) return COL_WARN;
  return tft.color565(220, 68, 55);
}

static uint16_t radColor(float uSv_h)
{
  if (uSv_h < 0.3) return COL_OK;        // 일반 실내 수준
  if (uSv_h < 0.6) return COL_WARN;      // 약간 높음
  return tft.color565(220, 68, 55);      // 주의 필요
}

static uint16_t tempColor(float t)
{
  if (t >= 18 && t <= 27) return COL_OK;
  if (t >= 16 && t <= 29) return COL_WARN;
  return tft.color565(220, 68, 55);
}

static uint16_t humidColor(float h)
{
  if (h >= 40 && h <= 60) return COL_OK;
  if (h >= 30 && h <= 70) return COL_WARN;
  return tft.color565(220, 68, 55);
}

void drawDashboard(
  const char* dateStr, const char* weekdayStr,
  int hour, int minute,
  float tempC, float humid,
  int pm25, int pm10,
  float rad1m, float rad10m
) {
  // ── 배경/카드/분할선 ──
  tft.fillScreen(COL_BG);
  tft.fillRoundRect(CARD_X, CARD_Y, CARD_W, CARD_H, CARD_R, COL_CARD);

  // 세로선: 시작점 topSepY와 정확히 일치
  const int16_t topSepY = CARD_Y + 38;  // 날짜보다 약간 아래로
  tft.drawFastVLine(RIGHT_X, topSepY, CARD_H - (topSepY - CARD_Y) - 8, COL_LINE);

  // ── Top bar: 날짜(크게, 중앙) + 요일(우측 정렬) ──
  setFont12B();
  const int16_t dateBase = CARD_Y + 28;  // 날짜 약간 내림
  const int16_t cardCenterX = CARD_X + CARD_W/2;
  int16_t bx, by; uint16_t bw, bh;
  String sDate(dateStr);
  tft.getTextBounds(sDate, 0, dateBase, &bx, &by, &bw, &bh);
  printLeft(cardCenterX - (int16_t)bw/2, dateBase, sDate, COL_TEXT);

  setFont9B();
  printRight(CARD_X + CARD_W - 12, dateBase, String(weekdayStr), COL_TEXT);

  // 가로선: 세로선 시작점(topSepY)과 동일하게
  tft.drawFastHLine(CARD_X + 12, topSepY, CARD_W - 24, COL_LINE);


  // ── 왼쪽 큰 시간 ──
  setFont24B();
  char hh[3];  // "00" + '\0'
  char mm[3];
  snprintf(hh, sizeof(hh), "%02d", hour);
  snprintf(mm, sizeof(mm), "%02d", minute);
  printLeft(CARD_X + 30, CARD_Y + 110, String(hh), COL_TEXT);
  printLeft(CARD_X + 30, CARD_Y + 170, String(mm), COL_TEXT);

  // ── 오른쪽 패널 균일 간격 레이아웃 ──
  int16_t y = CARD_Y + 56;          // 첫 라벨 시작 베이스라인
  const int16_t xL = RIGHT_X + 12;  // 좌측 열
  const int16_t xR = CARD_X + CARD_W - 20; // 우측 정렬 기준

  // [Temp/Humid]
  setFont9B();  printLeft(xL, y, "Temp", COL_SUB);                 // Label
  y += G_LABEL_TO_VALUE;
  setFont12B(); printLeft(xL, y, String(tempC, 1), tempColor(tempC)); // Value
  drawDegreeDot(xL + 50, y, COL_SUB);
  setFont9();  printLeft(xL + 55, y, "C", COL_SUB);

  // 같은 행 오른쪽에 Humid
  setFont9B();  printLeft(xR - 60, y - G_LABEL_TO_VALUE, "Humid", COL_SUB);
  setFont12B(); printRight(xR - 10, y, String(humid, 1), humidColor(humid));
  setFont9();  printLeft(xR -5, y, "%", COL_SUB);
  // 값 → 구분선
  y += G_VALUE_TO_SEP;
  tft.drawFastHLine(RIGHT_X, y, RIGHT_W, COL_LINE);
  // 구분선 → 다음 섹션 라벨
  y += G_SEP_TO_LABEL;

  // [Dust]
  setFont9B();  printLeft(xL, y, "Dust", COL_SUB);                 // Section Label
  y += G_LABEL_TO_VALUE;

  // PM10
  setFont9();  printLeft(xL, y, "PM10", COL_SUB);
  setFont12B(); printRight(xR - 48, y, String(pm10), pm10Color(pm10));
  setFont9();   printRight(xR, y, "µg/m³", COL_SUB);               // Unit 
  y += G_ROW;

  // PM2.5
  setFont9();  printLeft(xL, y, "PM2.5", COL_SUB);                // Row Label
  setFont12B(); printRight(xR - 48, y, String(pm25), pm25Color(pm25)); // Value
  setFont9();   printRight(xR, y, "µg/m³", COL_SUB);               // Unit

  // 값 → 구분선
  y += G_VALUE_TO_SEP;
  tft.drawFastHLine(RIGHT_X, y, RIGHT_W, COL_LINE);
  // 구분선 → 다음 섹션 라벨
  y += G_SEP_TO_LABEL;

  // [Radiation]
  setFont9B();  printLeft(xL, y, "Radiation", COL_SUB);            // Section Label
  y += G_LABEL_TO_VALUE;

  // 1m
  setFont9();  printLeft(xL, y, "1m", COL_SUB);
  setFont12B(); printRight(xR - 48, y, String(rad1m), radColor(rad1m));
  setFont9();   printRight(xR, y, "µSv/h", COL_SUB);               // Unit
  y += G_ROW;

  // 10m
  setFont9();  printLeft(xL, y, "10m", COL_SUB);
  setFont12B(); printRight(xR - 48, y, String(rad10m), radColor(rad10m));
  setFont9();   printRight(xR, y, "µSv/h", COL_SUB);               // Unit 

  // 필요 시 하단 여백 추가하려면:
  // y += G_VALUE_TO_SEP;
}

void setup() 
{
  delay(1000);
  Serial.begin(74880);
  pmsSerial.begin(9600); // dust sensor
  Wire.begin(SDA_PIN, SCL_PIN); // Temp&Hum, radiation: i2c
  delay(LOOP_DELAY);
  gdk101.reset(); // gamma sensor reset
  updateSensor();

  // request addr setting
  serverSet();
  server.on("/snapshot", handleSnapshot);
  server.onNotFound(handleNotFound);
  
  server.begin();
  Serial.println("ESP8266 Server started");

  // screen start
  tft.init(240, 320);
  tft.setRotation(1);
  tft.setTextWrap(false);

  // 🌙 Dark mode colors
  COL_BG   = tft.color565(18, 18, 18);     // #121212
  COL_CARD = tft.color565(30, 30, 30);     // #1E1E1E
  COL_TEXT = tft.color565(234, 234, 234);  // #EAEAEA
  COL_SUB  = tft.color565(156, 163, 175);  // #9CA3AF
  COL_LINE = tft.color565(45, 45, 45);     // #2D2D2D
  COL_OK   = tft.color565(76, 175, 80);    // #4CAF50
  COL_WARN = tft.color565(243, 156, 18);   // #F39C12

  // GetTimeFromFlask();
  configTime(3600 * timeZone, 3600 * summerTime, ntpServer); //init and get the time
  GetTime();
  drawDashboard(g_strDate.c_str(), g_strDayOfWeek.c_str(),
                g_iHour, g_iMinute,
                g_fTemp, g_fHumid,
                g_pm25, g_pm10,
                g_avg1m, g_avg10m);
}

void loop() 
{
  // Wait for requests
  server.handleClient();

  // millis() -> 2초마다 sensor update: get 요청처리 delay 방지용
  if(millis() - g_lastSensorUpdate > 2000)
  {
    g_lastSensorUpdate = millis();
    updateSensor();
  }

  if(millis() - g_lastScreenUpdate > 30000)
  {
    g_lastScreenUpdate = millis();
    // GetTimeFromFlask();
    GetTime();
    drawDashboard(g_strDate.c_str(), g_strDayOfWeek.c_str(),
              g_iHour, g_iMinute,
              g_fTemp, g_fHumid,
              g_pm25, g_pm10,
              g_avg1m, g_avg10m);
  }
}