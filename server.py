import os
import ssl
import random
import time
from collections import Counter
import requests
from flask import Flask, render_template, request, jsonify

try:
    _create_unverified_https_context = ssl._create_unverified_context
except AttributeError:
    pass
else:
    ssl._create_default_https_context = _create_unverified_https_context

app = Flask(__name__)
app.config['SECRET_KEY'] = os.urandom(24).hex()

VALID_BASE_WORDS = [
    "action", "actors", "advice", "angels", "artist", "assets", "backed", "baking", "beasts", "blames",
    "boards", "brains", "breaks", "brides", "buyers", "cabins", "cables", "candle", "cards", "castle",
    "chains", "chairs", "charms", "chased", "chiefs", "claims", "clans", "clears", "climbs", "coasts",
    "screws", "crimes", "dances", "dangers", "devils", "dreams", "drivers", "dusty", "earths", "engine"
]

FALLBACK_DICTIONARY = {"act", "ace", "aim", "air", "and", "ant", "any", "ape", "apt", "arc", "are"}
for w in VALID_BASE_WORDS:
    FALLBACK_DICTIONARY.add(w)

WORD_LIST_URL = "https://raw.githubusercontent.com/dwyl/english-words/master/words_alpha.txt"
LOCAL_CACHE_NAME = "dictionary_filtered.txt"

def load_comprehensive_dictionary():
    if os.path.exists(LOCAL_CACHE_NAME):
        try:
            with open(LOCAL_CACHE_NAME, "r", encoding="utf-8") as f:
                return {line.strip().lower() for line in f if len(line.strip()) > 2}
        except Exception: pass
    try:
        response = requests.get(WORD_LIST_URL, timeout=15)
        if response.status_code == 200:
            words = {line.strip().lower() for line in response.text.splitlines() if 3 <= len(line.strip()) <= 6}
            for w in VALID_BASE_WORDS: words.add(w)
            with open(LOCAL_CACHE_NAME, "w", encoding="utf-8") as f:
                for w in sorted(words): f.write(f"{w}\n")
            return words
    except Exception: pass
    return FALLBACK_DICTIONARY

GLOBAL_DICTIONARY = load_comprehensive_dictionary()
ROOMS = {}
class GameRoom:
    def __init__(self, room_id):
        self.room_id = room_id
        self.players = {}  # pid -> {name, score, current_round_words, is_host, last_seen, last_breakdown}
        self.base_word = ""
        self.scrambled_letters = []
        self.valid_anagrams = set()
        self.time_limit = 60
        self.time_left = 60
        self.end_timestamp = 0
        self.timer_active = False
        self.last_revealed_word = ""
        self.round_id = 0
        self.skipped_trigger = False
        self.generate_new_round()

    def generate_new_round(self):
        six_letter_words = [w for w in GLOBAL_DICTIONARY if len(w) == 6] or VALID_BASE_WORDS
        self.base_word = random.choice(six_letter_words)
        letters = list(self.base_word)
        while "".join(letters) == self.base_word: random.shuffle(letters)
        self.scrambled_letters = letters
        self.valid_anagrams = set()
        base_counter = Counter(self.base_word)
        for word in GLOBAL_DICTIONARY:
            if 3 <= len(word) <= 6 and all(Counter(word)[c] <= base_counter[c] for c in word):
                self.valid_anagrams.add(word)
        self.timer_active = False
        self.time_left = self.time_limit
        self.end_timestamp = 0
        self.round_id += 1
        for p_id in self.players:
            self.players[p_id]['current_round_words'] = []

    def evaluate_round_conclusion(self, skipped=False):
        score_chart = {3: 100, 4: 400, 5: 1200, 6: 2000}
        self.last_revealed_word = self.base_word
        self.skipped_trigger = skipped
        
        for pid, player in self.players.items():
            unique_guesses = list(dict.fromkeys(player['current_round_words']))
            breakdown = []
            round_score = 0
            
            for guess in unique_guesses:
                is_valid = guess in self.valid_anagrams
                pts = score_chart.get(len(guess), 0) if is_valid else 0
                round_score += pts
                breakdown.append({"word": guess, "valid": is_valid, "points": pts})
                
            player['score'] += round_score
            player['last_breakdown'] = {"breakdown": breakdown, "round_word": self.base_word, "skipped": skipped}
            
        self.generate_new_round()

    def check_timer(self):
        if self.timer_active:
            current_remaining = int(self.end_timestamp - time.time())
            if current_remaining <= 0:
                self.evaluate_round_conclusion(skipped=False)
                return True
            else:
                self.time_left = current_remaining
        return False

    def get_state(self):
        now = time.time()
        self.players = {sid: p for sid, p in self.players.items() if now - p['last_seen'] < 10}
        return {
            "letters": self.scrambled_letters, "target_count": len(self.valid_anagrams),
            "time_left": self.time_left, "timer_active": self.timer_active, "round_id": self.round_id,
            "leaderboard": sorted(
                [{"sid": sid, "name": p["name"], "score": p["score"], "is_host": p["is_host"]} 
                 for sid, p in self.players.items()], key=lambda x: x["score"], reverse=True
            )
        }

@app.route('/')
def index(): return render_template('index.html')

@app.route('/api/join', methods=['POST'])
def join_game():
    data = request.json
    room_id = data.get('room', 'lounge').strip() or 'lounge'
    name = data.get('name', 'User').strip() or 'User'
    pid = data.get('pid') or os.urandom(8).hex()
    if room_id not in ROOMS: ROOMS[room_id] = GameRoom(room_id)
    room = ROOMS[room_id]
    is_host = len(room.players) == 0 or not any(p['is_host'] for p in room.players.values())
    room.players[pid] = {"name": name, "score": 0, "current_round_words": [], "is_host": is_host, "last_seen": time.time(), "last_breakdown": None}
    return jsonify({"pid": pid, "is_host": is_host, "state": room.get_state()})

@app.route('/api/sync', methods=['POST'])
def sync_game():
    data = request.json
    room = ROOMS.get(data.get('room'))
    pid = data.get('pid')
    if not room or pid not in room.players: return jsonify({"error": "Expired"}), 404
    player = room.players[pid]
    player['last_seen'] = time.time()
    
    if room.timer_active:
        player['current_round_words'] = data.get('buffered_words', [])
        
    was_evaluated = room.check_timer()
    breakdown_payload = player['last_breakdown'] if (was_evaluated or player['last_breakdown'] is not None) else None
    if breakdown_payload:
        player['last_breakdown'] = None 
        
    return jsonify({"state": room.get_state(), "breakdown": breakdown_payload, "is_host": player['is_host']})

@app.route('/api/control', methods=['POST'])
def control_timer():
    data = request.json
    room = ROOMS.get(data.get('room'))
    pid = data.get('pid')
    action = data.get('action')
    if not room or pid not in room.players or not room.players[pid]['is_host']: return jsonify({"status": "denied"})
    
    if action == "start":
        room.timer_active = True
        room.end_timestamp = time.time() + room.time_left
    elif action == "pause":
        if room.timer_active:
            room.time_left = max(0, int(room.end_timestamp - time.time()))
            room.timer_active = False
    elif action == "limit":
        room.time_limit = max(10, int(data.get('limit', 60)))
        room.generate_new_round()
    elif action == "skip":
        room.evaluate_round_conclusion(skipped=True)
    return jsonify({"status": "ok"})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=False)
