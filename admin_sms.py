import serial
import time
import subprocess
import os
from datetime import datetime
import binascii
import re

class SIM800L:
    def __init__(self, port='/dev/serial0', baudrate=9600):
        self.ser = serial.Serial(
            port=port,
            baudrate=baudrate,
            timeout=1
        )
        self.authorized_numbers = [
            "+221777350027",
            "+221764489909"
        ]

    def clean_text(self, text):
        """Nettoie le texte des caractères non désirés"""
        try:
            text = str(text)
            # Ne garde que les caractères imprimables et les espaces
            cleaned = ''.join(char for char in text if char.isprintable() or char.isspace())
            # Supprime les espaces multiples
            cleaned = ' '.join(cleaned.split())
            # Supprime les caractères de contrôle
            cleaned = ''.join(char for char in cleaned if ord(char) >= 32)
            return cleaned.strip()
        except Exception as e:
            print(f"Erreur nettoyage texte: {e}")
            return str(text).strip()

    def decode_hex_message(self, text):
        """Décode un message qui pourrait être en hexadécimal"""
        try:
            # Si le texte est déjà lisible, le retourner tel quel
            if any(c.isalpha() for c in text):
                return self.clean_text(text)

            # Essai de décodage hex
            # Supprime tout ce qui n'est pas hexadécimal
            hex_str = ''.join(c for c in text if c in '0123456789ABCDEFabcdef')
            if len(hex_str) % 2 == 0:  # Vérifie que la longueur est paire
                bytes_str = binascii.unhexlify(hex_str)
                decoded = bytes_str.decode('utf-16-be', errors='ignore')
                return self.clean_text(decoded)

            return self.clean_text(text)
        except Exception as e:
            print(f"Erreur décodage (retour texte original): {e}")
            return self.clean_text(text)

    def send_command(self, command, wait_time=1):
        """Envoie une commande AT au module SIM800L"""
        try:
            self.ser.write(f"{command}\r\n".encode())
            time.sleep(wait_time)
            response = ""
            while self.ser.in_waiting:
                response += self.ser.read().decode('ascii', errors='ignore')
            return response.strip()
        except Exception as e:
            print(f"Erreur commande: {e}")
            return None

    def send_sms(self, number, message):
        """Envoie un SMS"""
        try:
            self.send_command('AT+CMGF=1')  # Mode texte
            self.send_command('AT+CSCS="GSM"')  # Set GSM character set
            number = number.replace('"', '')  # Nettoie le numéro
            if not number.startswith('+'):
                number = '+' + number
            self.send_command(f'AT+CMGS="{number}"')
            response = self.send_command(message + chr(26))  # chr(26) = Ctrl+Z
            return "OK" in response
        except Exception as e:
            print(f"Erreur envoi SMS: {e}")
            return False

    def execute_command(self, command):
        """Exécute une commande système et retourne le résultat"""
        try:
            print(f"Exécution de: {command}")
            result = subprocess.check_output(command, shell=True, text=True, stderr=subprocess.STDOUT)
            print(f"Sortie brute: {result}")
            # Nettoie et limite la sortie
            cleaned_result = result.strip()[:150]
            return cleaned_result
        except subprocess.CalledProcessError as e:
            return f"Erreur: {e.output}"
        except Exception as e:
            return f"Erreur système: {str(e)}"

    def process_sms_command(self, sender, message):
        """Traite les commandes reçues par SMS"""
        if sender not in self.authorized_numbers:
            print(f"Numéro non autorisé: {sender}")
            return "Numéro non autorisé"

        commands = {
            'temp': "vcgencmd measure_temp",
            'cpu': "top -bn1 | grep 'Cpu(s)' | awk '{print $2}'",
            'mem': "free -m | grep 'Mem:' | awk '{print \"Total: \"$2\"MB, Used: \"$3\"MB\"}'",
            'disk': "df -h / | tail -1 | awk '{print \"Used: \"$5 \" of \"$2}'",
            'uptime': "uptime -p",
            'reboot': "sudo reboot",
            'shutdown': "sudo shutdown -h now",
            'services': "systemctl list-units --type=service --state=running | head -5",
            'help': "Liste des commandes: temp, cpu, mem, disk, uptime, reboot, shutdown, services"
        }

        cmd = message.strip().lower()
        if cmd in commands:
            if cmd == 'help':
                return commands[cmd]
            elif cmd in ['reboot', 'shutdown']:
                message_action = "Arrêt" if cmd == 'shutdown' else "Redémarrage"
                self.send_sms(sender, f"{message_action} du système en cours...")
                time.sleep(1)
                self.execute_command(commands[cmd])
                return None
            else:
                print(f"Exécution de la commande système: {commands[cmd]}")
                result = self.execute_command(commands[cmd])
                print(f"Résultat obtenu: {result}")
                return f"Résultat de {cmd}:\n{result}"
        else:
            return "Commande inconnue. Envoyez 'help' pour la liste des commandes."

    def check_sms(self):
        """Vérifie et traite uniquement les nouveaux SMS non lus"""
        self.send_command("AT+CMGF=1")  # Mode texte
        response = self.send_command('AT+CMGL="REC UNREAD"', wait_time=3)  # Lire que les messages non lus

        if "CMGL:" in response:
            messages = response.split('+CMGL:')
            for msg in messages[1:]:
                try:
                    # Parse le message
                    lines = msg.split('\n')
                    if len(lines) < 2:
                        continue

                    header = lines[0]
                    parts = header.split(',')
                    if len(parts) >= 3:
                        msg_index = parts[0].strip()
                        sender = parts[2].strip('"')
                        text = lines[1].strip()

                        # Décode et nettoie le message
                        decoded_text = self.decode_hex_message(text)
                        print(f"Message reçu de {sender}: {decoded_text}")

                        # Traite la commande
                        reply = self.process_sms_command(sender, decoded_text)
                        if reply:
                            self.send_sms(sender, reply)

                        # Supprime le message traité
                        self.send_command(f"AT+CMGD={msg_index}")
                except Exception as e:
                    print(f"Erreur traitement message: {e}")

    def start_monitoring(self):
        """Démarre la surveillance des SMS"""
        print("Démarrage du système d'administration par SMS...")
        self.send_command("AT")  # Test communication
        self.send_command("AT+CMGF=1")  # Mode texte

        self.send_command('AT+CNMI=2,1,0,0,0')  # Config notifications

        while True:
            try:
                self.check_sms()
                time.sleep(1)  # Vérifie toutes les 1 seconde
            except KeyboardInterrupt:
                print("\nArrêt du programme...")
                break
            except Exception as e:
                print(f"Erreur: {e}")
                time.sleep(10)

def main():
    sim = SIM800L()
    try:
        sim.start_monitoring()
    finally:
        sim.ser.close()

if __name__ == "__main__":
    main()