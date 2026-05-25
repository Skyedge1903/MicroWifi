#include <WiFi.h>
#include <WiFiUdp.h>
#include "driver/i2s.h"

const char* ssid = "ESP_MIC";
const char* password = "12345678";

IPAddress target_ip;
const int udp_port = 3333;
WiFiUDP udp;

bool client_ok = false;

const i2s_port_t I2S_PORT = I2S_NUM_0;
const int SAMPLE_RATE = 44100;
const int FRAME_MS = 5;
const int NUM_SAMPLES = SAMPLE_RATE * FRAME_MS / 1000; // 220 samples
int16_t audio_buffer[NUM_SAMPLES]; // 220 samples * 2 bytes = 440 bytes

void setupI2S() {
  i2s_config_t i2s_config = {
    .mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_RX),
    .sample_rate = SAMPLE_RATE,
    .bits_per_sample = I2S_BITS_PER_SAMPLE_16BIT,
    .channel_format = I2S_CHANNEL_FMT_ONLY_LEFT,
    .communication_format = I2S_COMM_FORMAT_STAND_I2S,
    .intr_alloc_flags = ESP_INTR_FLAG_LEVEL1,
    .dma_buf_count = 4,
    .dma_buf_len = NUM_SAMPLES,
    .use_apll = false
  };

  i2s_pin_config_t pin_config = {
    .bck_io_num = 14,
    .ws_io_num = 15,
    .data_out_num = I2S_PIN_NO_CHANGE,
    .data_in_num = 16
  };

  i2s_driver_install(I2S_PORT, &i2s_config, 0, NULL);
  i2s_set_pin(I2S_PORT, &pin_config);
  i2s_start(I2S_PORT);
}

void setup() {
  Serial.begin(115200);

  WiFi.mode(WIFI_AP);
  WiFi.softAP(ssid, password);

  Serial.println(WiFi.softAPIP());

  udp.begin(udp_port);
  setupI2S();
}

void loop() {

  // -------- HANDSHAKE MINIMAL --------
  if (!client_ok) {
    int packetSize = udp.parsePacket();

    if (packetSize) {
      char buf[16];
      int len = udp.read(buf, 15);
      buf[len] = 0;

      if (strcmp(buf, "HELLO") == 0) {
        target_ip = udp.remoteIP();

        udp.beginPacket(target_ip, udp.remotePort());
        udp.write((const uint8_t*)"OK", 2);
        udp.endPacket();

        client_ok = true;
      }
    }
    return;
  }

  // -------- AUDIO STREAM (IDENTIQUE) --------
  size_t bytes_read;
  i2s_read(I2S_PORT, audio_buffer, NUM_SAMPLES * 2, &bytes_read, portMAX_DELAY);

  if (bytes_read == NUM_SAMPLES * 2) {
    udp.beginPacket(target_ip, udp_port);
    udp.write((uint8_t*)audio_buffer, NUM_SAMPLES * 2);
    udp.endPacket();
  }
}