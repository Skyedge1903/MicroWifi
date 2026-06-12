#include <Arduino.h>
#include "driver/i2s.h"

const i2s_port_t I2S_PORT = I2S_NUM_0;

// -------- Audio --------
const int SAMPLE_RATE = 16000;
const int FRAME_MS = 5;   // <- latence réduite
const int SAMPLES_PER_FRAME = SAMPLE_RATE * FRAME_MS / 1000; // 80
const int AUDIO_BYTES = SAMPLES_PER_FRAME * sizeof(int16_t);

// -------- I2S pins --------
const int PIN_I2S_BCLK = 14;
const int PIN_I2S_WS   = 15;
const int PIN_I2S_SD   = 16;

// -------- Serial --------
const uint32_t SERIAL_BAUD = 921600;

// -------- Buffers --------
int32_t i2s_raw[SAMPLES_PER_FRAME];
int16_t pcm16[SAMPLES_PER_FRAME];

#pragma pack(push, 1)
struct AudioPacketHeader {
  uint8_t sync1;      // 0xAA
  uint8_t sync2;      // 0x55
  uint16_t length;    // taille payload
  uint32_t frame_id;  // compteur
};
#pragma pack(pop)

uint32_t frame_id = 0;

uint16_t checksum16(const uint8_t* data, size_t len) {
  uint32_t sum = 0;
  for (size_t i = 0; i < len; i++) sum += data[i];
  return (uint16_t)(sum & 0xFFFF);
}

void setupI2S() {
  i2s_config_t i2s_config = {
    .mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_RX),
    .sample_rate = SAMPLE_RATE,
    .bits_per_sample = I2S_BITS_PER_SAMPLE_32BIT,
    .channel_format = I2S_CHANNEL_FMT_ONLY_LEFT,
    .communication_format = (i2s_comm_format_t)(I2S_COMM_FORMAT_I2S | I2S_COMM_FORMAT_I2S_MSB),
    .intr_alloc_flags = ESP_INTR_FLAG_LEVEL1,
    .dma_buf_count = 4,
    .dma_buf_len = SAMPLES_PER_FRAME,
    .use_apll = false,
    .tx_desc_auto_clear = false,
    .fixed_mclk = 0
  };

  i2s_pin_config_t pin_config = {
    .bck_io_num = PIN_I2S_BCLK,
    .ws_io_num = PIN_I2S_WS,
    .data_out_num = I2S_PIN_NO_CHANGE,
    .data_in_num = PIN_I2S_SD
  };

  i2s_driver_install(I2S_PORT, &i2s_config, 0, NULL);
  i2s_set_pin(I2S_PORT, &pin_config);
  i2s_zero_dma_buffer(I2S_PORT);
  i2s_start(I2S_PORT);
}

void setup() {
  Serial.begin(SERIAL_BAUD);
  delay(200);
  setupI2S();
}

void loop() {
  size_t bytes_read = 0;
  esp_err_t err = i2s_read(I2S_PORT, (void*)i2s_raw, sizeof(i2s_raw), &bytes_read, portMAX_DELAY);
  if (err != ESP_OK || bytes_read != sizeof(i2s_raw)) {
    return;
  }

  // Conversion 32-bit I2S -> PCM 16-bit signé
  for (int i = 0; i < SAMPLES_PER_FRAME; i++) {
    uint8_t* p = (uint8_t*)&i2s_raw[i];
    uint16_t raw16 = ((uint16_t)p[3] << 8) | p[2];
    pcm16[i] = (int16_t)raw16;
  }

  AudioPacketHeader hdr;
  hdr.sync1 = 0xAA;
  hdr.sync2 = 0x55;
  hdr.length = AUDIO_BYTES;
  hdr.frame_id = frame_id++;

  uint16_t crc = checksum16((const uint8_t*)pcm16, AUDIO_BYTES);

  Serial.write((const uint8_t*)&hdr, sizeof(hdr));
  Serial.write((const uint8_t*)pcm16, AUDIO_BYTES);
  Serial.write((const uint8_t*)&crc, sizeof(crc));
}