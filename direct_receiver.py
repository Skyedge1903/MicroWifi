import sounddevice as sd
import sys

# Réglages de base
SAMPLERATE = 48000   # 44100 ou 48000 selon ta carte son
CHANNELS = 1         # 1 = mono, 2 = stéréo
DTYPE = 'float32'

# Conseils latence :
# - latency='low' demande au driver d'utiliser un mode faible latence
# - blocksize=0 laisse PortAudio choisir la taille optimale
# - évite tout traitement Python dans le callback

def audio_callback(indata, outdata, frames, time, status):
    if status:
        print(status, file=sys.stderr)
    outdata[:] = indata  # copie directe micro -> sortie

try:
    print("Liste des périphériques audio :")
    print(sd.query_devices())
    print("\nDémarrage du retour micro en faible latence...")
    print("Appuie sur Ctrl+C pour arrêter.\n")

    with sd.Stream(
        samplerate=SAMPLERATE,
        blocksize=0,
        dtype=DTYPE,
        channels=CHANNELS,
        latency='low',
        callback=audio_callback
    ):
        while True:
            sd.sleep(1000)

except KeyboardInterrupt:
    print("\nArrêt.")
except Exception as e:
    print(f"Erreur: {e}")