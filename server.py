import os
import ssl
import random
import time
import re
from collections import Counter
from flask import Flask, render_template, request, jsonify

app = Flask(__name__, template_folder=os.path.abspath(os.path.join(os.path.dirname(__file__), 'templates')))
app.config['SECRET_KEY'] = os.urandom(24).hex()

VALID_BASE_WORDS = [
    "action", "actors", "advice", "angels", "artist", "assets", "backed", "baking", "beasts", "blames",
    "boards", "brains", "breaks", "brides", "buyers", "cabins", "cables", "candle", "cards", "castle",
    "chains", "chairs", "charms", "chased", "chiefs", "claims", "clans", "clears", "climbs", "coasts",
    "crews", "crimes", "dances", "dangers", "devils", "dreams", "drivers", "dusty", "earths", "engine"
]

FALLBACK_DICTIONARY = {"act", "ace", "aim", "air", "and", "ant", "any", "ape", "apt", "arc", "are"}
for w in VALID_BASE_WORDS:
    FALLBACK_DICTIONARY.add(w)

LOCAL_CACHE_NAME = "dictionary_filtered.txt"

def load_comprehensive_dictionary():
    if os.path.exists(LOCAL_CACHE_NAME):
        try:
            with open(LOCAL_CACHE_NAME, "r", encoding="utf-8") as f:
                return {line.strip().lower() for line in f if len(line.strip()) > 2}
        except Exception: pass
    return FALLBACK_DICTIONARY

GLOBAL_DICTIONARY = load_comprehensive_dictionary()
ROOMS = {}

def moderate_text(text):
    banned_words = [r"crap", r"sh+it", r"f+u+c+k", r"b+i+t+c+h", r"a+s+s", r"d+i+c+k"]
    moderated = text
    for pattern in banned_words:
        moderated = re.sub(pattern, lambda m: "*" * len(m.group()), moderated, flags=re.IGNORECASE)
    return moderated
class GameRoom:
    def __init__(self, room_id):
        self.room_id = room_id
        self.players = {}  # pid -> {name, score, current_round_words, is_host, last_seen, last_breakdown, ready}
        self.chat_history = []
        self.chat_counter = 0
        self.base_word = ""
        self.scrambled_letters = []
        self.valid_anagrams = set()
        self.time_limit = 60
        self.time_left = 60
        self.end_timestamp = 0
        self.timer_active = False
        self.countdown_active = False
        self.countdown_end = 0
        self.last_revealed_word = ""
        self.round_id = 0
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
        self.countdown_active = False
        self.countdown_end = 0
        self.time_left = self.time_limit
        self.end_timestamp = 0
        self.round_id += 1
        for p_id in self.players:
            self.players[p_id]['current_round_words'] = []
            self.players[p_id]['ready'] = False

    def clear_all_scores(self):
        for p_id in self.players:
            self.players[p_id]['score'] = 0

    def evaluate_round_conclusion(self, skipped=False):
        score_chart = {3: 100, 4: 400, 5: 1200, 6: 2000}
        self.last_revealed_word = self.base_word
        for pid, player in self.players.items():
            unique_guesses = list(dict.fromkeys(player['current_round_words']))
            breakdown = []
            round_score = 0
            for guess in unique_guesses:
                if guess in self.valid_anagrams:
                    round_score += score_chart.get(len(guess), 0)
                    breakdown.append({"word": guess, "valid": True, "points": score_chart.get(len(guess), 0)})
                else:
                    breakdown.append({"word": guess, "valid": False, "points": 0})
            player['score'] = round_score  
            player['last_breakdown'] = {"breakdown": breakdown, "round_word": self.base_word, "skipped": skipped}
        self.generate_new_round()

    def check_timer(self):
        # Manage the 3-second lobby flash countdown transition states
        if self.countdown_active:
            rem_cd = int(self.countdown_end - time.time())
            if rem_cd <= 0:
                self.countdown_active = False
                self.timer_active = True
                self.end_timestamp = time.time() + self.time_left
            return False
            
        if self.timer_active:
            current_remaining = int(self.end_timestamp - time.time())
            if current_remaining <= 0:
                self.evaluate_round_conclusion(skipped=False)
                return True
            else:
                self.time_left = current_remaining
        return False

    def check_all_ready(self):
        if len(self.players) == 0: return False
        if all(p['ready'] for p in self.players.values()) and not self.timer_active and not self.countdown_active:
            self.clear_all_scores()
            # FIXED: Enter visual 3s pending block, deferring tile unmask until completion
            self.countdown_active = True
            self.countdown_end = time.time() + 3
            return True
        return False

    def get_state(self, last_chat_id=0):
        now = time.time()
        self.players = {sid: p for sid, p in self.players.items() if now - p['last_seen'] < 10}
        masked_letters = self.scrambled_letters if self.timer_active else ["?", "?", "?", "?", "?", "?"]
        new_chats = [c for c in self.chat_history if c["id"] > last_chat_id]
        
        display_time = self.time_left
        if self.countdown_active:
            display_time = max(0, int(self.countdown_end - time.time()))
            
        return {
            "letters": masked_letters, "target_count": len(self.valid_anagrams),
            "time_left": display_time, "timer_active": self.timer_active, 
            "countdown_active": self.countdown_active, "round_id": self.round_id,
            "new_chats": new_chats,
            "leaderboard": sorted(
                [{"sid": sid, "name": p["name"], "score": p["score"], "is_host": p["is_host"], "ready": p["ready"]} 
                 for sid, p in self.players.items()], key=lambda x: x["score"], reverse=True
            )
        }

@app.route('/')
def index(): return render_template('index.html')

@app.route('/api/join', methods=['POST'])
def join_game():
    data = request.json
    room_id = data.get('room', 'lounge').strip() or 'lounge'
    proposed_name = data.get('name', 'User').strip() or 'User'
    pid = data.get('pid') or os.urandom(8).hex()
    if room_id not in ROOMS: ROOMS[room_id] = GameRoom(room_id)
    room = ROOMS[room_id]
    existing_names = [p['name'].lower() for p in room.players.values()]
    final_name = proposed_name
    counter = 2
    while final_name.lower() in existing_names:
        final_name = f"{proposed_name} #{counter}"
        counter += 1
    is_host = len(room.players) == 0 or not any(p['is_host'] for p in room.players.values())
    room.players[pid] = {"name": final_name, "score": 0, "current_round_words": [], "is_host": is_host, "last_seen": time.time(), "last_breakdown": None, "ready": False}
    return jsonify({"pid": pid, "is_host": is_host, "final_name": final_name, "state": room.get_state()})

@app.route('/api/sync', methods=['POST'])
def sync_game():
    data = request.json
    room = ROOMS.get(data.get('room'))
    pid = data.get('pid')
    last_chat_id = int(data.get('last_chat_id', 0))
    if not room or pid not in room.players: return jsonify({"error": "Expired"}), 404
    player = room.players[pid]
    player['last_seen'] = time.time()
    if room.timer_active:
        player['current_round_words'] = data.get('buffered_words', [])
    was_evaluated = room.check_timer()
    room.check_all_ready()
    breakdown_payload = player['last_breakdown'] if (was_evaluated or player['last_breakdown'] is not None) else None
    if breakdown_payload: player['last_breakdown'] = None 
    return jsonify({"state": room.get_state(last_chat_id), "breakdown": breakdown_payload, "is_host": player['is_host']})

@app.route('/api/ready', methods=['POST'])
def toggle_ready():
    data = request.json
    room = ROOMS.get(data.get('room'))
    pid = data.get('pid')
    if not room or pid not in room.players: return jsonify({"error": "Missing"}), 404
    room.players[pid]['ready'] = not room.players[pid]['ready']
    room.check_all_ready()
    return jsonify({"status": "ok", "state": room.get_state()})

@app.route('/api/chat', methods=['POST'])
def post_chat():
    data = request.json
    room = ROOMS.get(data.get('room'))
    pid = data.get('pid')
    msg = data.get('msg', '').strip()
    last_chat_id = int(data.get('last_chat_id', 0))
    if not room or pid not in room.players or not msg: return jsonify({"status": "ignored"})
    room.chat_counter += 1
    room.chat_history.append({"id": room.chat_counter, "name": room.players[pid]['name'], "msg": moderate_text(msg[:100])})
    return jsonify({"status": "ok", "state": room.get_state(last_chat_id)})

@app.route('/api/control', methods=['POST'])
def control_timer():
    data = request.json
    room = ROOMS.get(data.get('room'))
    pid = data.get('pid')
    action = data.get('action')
    if not room or pid not in room.players or not room.players[pid]['is_host']: return jsonify({"status": "denied"})
    if action == "pause":
        if room.timer_active:
            room.time_left = max(0, int(room.end_timestamp - time.time()))
            room.timer_active = False
            for p_id in room.players: room.players[p_id]['ready'] = False
    elif action == "limit":
        room.time_limit = max(10, int(data.get('limit', 60)))
        room.generate_new_round()
    elif action == "skip":
        room.evaluate_round_conclusion(skipped=True)
    return jsonify({"status": "ok"})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=False)
