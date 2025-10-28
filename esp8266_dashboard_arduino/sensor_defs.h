#ifndef SENSORS_DEFS
# define SENSORS_DEFS

// --- GPIO PIN SET ---
# define SDA_PIN 4 // SDA=GPIO4(D2)
# define SCL_PIN 5 // SCL=GPIO5(D1)
# define SOFT_RX D3
# define SOFT_TX -1

// --- AM2320 (temperature, humid sensor) ---
# define AM2320_ADDR 0x5C 
# define AM2320_CMD_READREG 0x03
# define AM2320_REG_HUM_H 0x00
# define AM2320_REG_TEMP_H 0x02

# define ACK 0
# define NACK !ACK

# define AM2320TX_FUNC_CODE 0
# define AM2320TX_START_ADDR 1
# define AM2320TX_REGI_NUM 2

# define AM2320RX_FUNC_CODE 0
# define AM2320RX_REGI_NUM 1
# define AM2320RX_DATA_HIGH 2
# define AM2320RX_DATA_LOW 3
# define AM2320RX_CRC_HIGH 4
# define AM2320RX_CRC_LOW 5

# define AM2320TX_BUFSIZE 3 // cmd, regiAddr, length
# define AM2320RX_BUFSIZE 6 // fc code(1) + # of regi(1) + data(2) + crc(2)
# define AM2320_READ_LEN 2

// --- GDK101 (gamma sensor) ---
# define GDK101_ADDR 0x18 
# define GDK101_CMD_RESET 0xA0
# define GDK101_CMD_AVG_10M 0xB2
# define GDK101_CMD_AVG_1M 0xB3

# define GDK101_RESET_CHECK_BIT 1
# define GDK101_RESET_FAIL 1

# define GDK101TX_BUFSIZE 1
# define GDK101RX_BUFSIZE 2

# define GDK101_DATA_INT 0
# define GDK101_DATA_DEC 1

// --- PM-G7 (dust sensor) ---
# define PM_FRAME_SIZE 32
# define CHECKSUM_LEN 2
# define FRAME_HEADER1 0x42
# define FRAME_HEADER2 0x4d
# define PM1_DATA_HIGH 10
# define PM1_DATA_LOW 11
# define PM25_DATA_HIGH 12
# define PM25_DATA_LOW 13
# define PM10_DATA_HIGH 14
# define PM10_DATA_LOW 15

// ------
# define MAX_RETRY 3
# define LOOP_DELAY 1000
# define AM2320_SENSOR_WAITING 3
# define AM2320_READY_WAITING 10
# define GDK101_WAITING 10

#endif