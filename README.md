# ESP32 WiFi Microphone

Stream audio en temps réel depuis un microphone I2S connecté à un ESP32 vers un PC via UDP sur un réseau WiFi local.

## Overview

L'ESP32 crée un point d'accès WiFi (Access Point) et capture l'audio via un microphone MEMS I2S. Les données audio sont envoyées en continu par paquets UDP à un client Python qui les joue en temps réel via `sounddevice`.

## Hardware requis

- ESP32 (testé sur ESP32-WROOM)
- Microphone MEMS I2S (ex: INMP441, SPH0645)
- Câblage I2S :

| Microphone | ESP32 |
|-----------|-------|
| BCK (BCLK) | GPIO 14 |
| WS (LRCLK) | GPIO 15 |
| SD (DATA) | GPIO 16 |
| VDD | 3.3V |
| GND | GND |

## Fonctionnement

### Protocole

1. L'ESP32 démarre en mode **Access Point** (`ESP_MIC` / `12345678`)
2. Le client Python se connecte au réseau et envoie `HELLO` en UDP
3. L'ESP32 répond `OK` et enregistre l'IP du client
4. L'ESP32 streame des frames audio de **220 samples (440 octets)** à 44100 Hz en continu

### Paramètres audio

| Paramètre | Valeur |
|-----------|--------|
| Sample rate | 44 100 Hz |
| Bit depth | 16-bit |
| Canaux | Mono (LEFT) |
| Frame size | 5 ms / 220 samples |
| Paquet UDP | 440 bytes |

## Installation client Python

```bash
pip install sounddevice numpy
```

## Utilisation

### 1. Flasher l'ESP32

Ouvre le firmware dans l'IDE Arduino ou PlatformIO et flash l'ESP32.

### 2. Connecter le PC au réseau WiFi

```
SSID     : ESP_MIC
Password : 12345678
```

### 3. Lancer le client Python

```bash
python client.py
```

L'audio du microphone sera joué en temps réel sur la sortie audio du PC.

## Structure du projet

```
├── firmware/
│   └── esp32_mic.ino   # Firmware ESP32 (WiFi AP + I2S + UDP)
└── client.py           # Client Python (réception UDP + lecture audio)
```

## Limitations connues

- Un seul client à la fois (pas de multicast)
- Pas de buffer de jitter : latence minimale mais sensible aux pertes réseau
- Le handshake n'est pas sécurisé (réseau local uniquement)
