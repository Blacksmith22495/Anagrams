import os
import random
import time
import re
from collections import Counter
from flask import Flask, render_template, request, jsonify

app = Flask(__name__, template_folder=os.path.abspath(os.path.join(os.path.dirname(__file__), 'templates')))
app.config['SECRET_KEY'] = os.urandom(24).hex()

VALID_BASE_WORDS = [
    "action", "actors", "advice", "angels", "artist", "assets", "backed", "baking", "beasts", "blames",
    "boards", "brains", "breaks", "brides", "buyers", "cabins", "cables", "candle", "cards", "castle"
]
GLOBAL_DICTIONARY = {"act", "ace", "aim", "air", "and", "ant", "any", "ape", "apt", "arc", "are"}.union(set(VALID_BASE_WORDS))
ROOMS = {}

def moderate_text(text):
    banned_words = [r"crap", r"sh+it", r"f+u+c+k", r"b+i+t+c+h", r"a+s+s+h+o+l+e", r"d+i+c+k"]
    moderated = text
    for pattern in banned_words:
        moderated = re.sub(pattern, lambda m: "*" * len(m.group()), moderated, flags=re.IGNORECASE)
    return moderated

class GameRoom:
    def __init__(self, room_id):
        self.room_id = room_id
        self.game_type = "unselected"  # "unselected", "anagram", "twenty_questions"
        self.game_locked = False
        self.players = {}
        self.chat_history = []
        self.chat_counter = 0
        # Anagram states
        self.base_word = ""
        self.scrambled_letters = []
        self.valid_anagrams = set()
        self.time_limit = 60
        self.time_left = 60
        self.end_timestamp = 0
        self.timer_active = False
        self.countdown_active = False
        self.countdown_end = 0
        self.round_id = 0
        self.last_breakdown = None
        # 20 Questions states
        self.tq_thinker_pid = None
        self.tq_secret_word = ""
        self.tq_questions = []
        self.tq_status = "waiting_thinker"
        self.tq_question_counter = 0
        self.generate_new_round()
    def generate_new_round(self):
        if self.game_type == "anagram":
            self.base_word = random.choice(VALID_BASE_WORDS).lower()
            letters = list(self.base_word)
            while "".join(letters) == self.base_word: random.shuffle(letters)
            self.scrambled_letters = letters
            self.valid_anagrams = set()
            base_counter = Counter(self.base_word)
            for word in GLOBAL_DICTIONARY:
                w_low = word.strip().lower()
                if 3 <= len(w_low) <= 6 and all(Counter(w_low)[c] <= base_counter[c] for c in w_low):
                    self.valid_anagrams.add(w_low)
            self.timer_active = False
            self.countdown_active = False
            self.time_left = self.time_limit
            self.end_timestamp = 0
            self.round_id += 1
        elif self.game_type == "twenty_questions":
            self.tq_thinker_pid = None
            self.tq_secret_word = ""
            self.tq_questions = []
            self.tq_status = "waiting_thinker"
            self.tq_question_counter = 0
            self.round_id += 1
        for p in self.players.values():
            p['current_round_words'] = []
            p['ready'] = False

    def evaluate_round_conclusion(self, skipped=False):
        if self.game_type != "anagram": return
        score_chart = {3: 100, 4: 400, 5: 1200, 6: 2000}
        for pid, player in self.players.items():
            unique_guesses = list(dict.fromkeys(player.get('current_round_words', [])))
            breakdown = []
            round_score = player.get('score', 0)
            for guess in unique_guesses:
                g_low = guess.strip().lower()
                if g_low in self.valid_anagrams:
                    pts = score_chart.get(len(g_low), 0)
                    round_score += pts
                    breakdown.append({"word": g_low, "valid": True, "points": pts})
                else:
                    breakdown.append({"word": g_low, "valid": False, "points": 0})
            player['score'] = round_score
            player['last_breakdown'] = {"breakdown": breakdown, "round_word": self.base_word, "skipped": skipped}
        self.generate_new_round()

    def check_timer(self):
        if self.game_type != "anagram": return False
        if self.countdown_active:
            if time.time() >= self.countdown_end:
                self.countdown_active = False
                self.timer_active = True
                self.end_timestamp = time.time() + self.time_left
            return False
        if self.timer_active:
            self.time_left = int(self.end_timestamp - time.time())
            if self.time_left <= 0:
                self.evaluate_round_conclusion(skipped=False)
                return True
        return False

    def check_all_ready(self):
        if not self.players or self.game_type != "anagram": return False
        if all(p['ready'] for p in self.players.values()) and not self.timer_active and not self.countdown_active:
            self.countdown_active = True
            self.countdown_end = time.time() + 3
            return True
        return False

    def get_state(self, last_chat_id=0):
        now = time.time()
        self.players = {sid: p for sid, p in self.players.items() if now - p['last_seen'] < 10}
        new_chats = [c for c in self.chat_history if c["id"] > last_chat_id]
        reveal_letters = self.timer_active or self.countdown_active
        letters_payload = self.scrambled_letters if reveal_letters else ["?"] * 6
        display_time = max(0, int(self.countdown_end - time.time())) if self.countdown_active else self.time_left

        return {
            "game_type": self.game_type, "game_locked": self.game_locked,
            "letters": letters_payload, "time_left": display_time,
            "timer_active": self.timer_active, "countdown_active": self.countdown_active, "round_id": self.round_id,
            "new_chats": new_chats, "tq_thinker_pid": self.tq_thinker_pid, 
            "tq_secret_word": self.tq_secret_word if self.tq_status == "won" else ("???" if self.tq_secret_word else ""),
            "tq_status": self.tq_status, "tq_questions": self.tq_questions,
            "leaderboard": [{"sid": s, "name": p["name"], "score": p["score"], "is_host": p["is_host"], "ready": p["ready"]} for s, p in self.players.items()]
        }

@app.route('/')
def index(): return render_template('index.html')

@app.route('/api/join', methods=['POST'])
def join_game():
    data = request.json
    room_id = data.get('room', 'lounge').strip() or 'lounge'
    pid = data.get('pid') or os.urandom(8).hex()
    if room_id not in ROOMS: ROOMS[room_id] = GameRoom(room_id)
    room = ROOMS[room_id]
    name = data.get('name', 'User').strip() or 'User'
    is_host = len(room.players) == 0
    room.players[pid] = {"name": name, "score": 0, "current_round_words": [], "is_host": is_host, "last_seen": time.time(), "ready": False, "last_breakdown": None}
    return jsonify({"pid": pid, "is_host": is_host, "state": room.get_state()})

@app.route('/api/sync', methods=['POST'])
def sync_game():
    data = request.json
    room = ROOMS.get(data.get('room'))
    pid = data.get('pid')
    if not room or pid not in room.players: return jsonify({"error": "Expired"}), 404
    player = room.players[pid]
    player['last_seen'] = time.time()
    
    if room.timer_active and room.game_type == "anagram":
        # FIXED: Lower-case all text elements inside the list compilation mapping layer
        raw_words = data.get('buffered_words', [])
        player['current_round_words'] = [str(w).strip().lower() for w in raw_words]
        
    room.check_timer()
    room.check_all_ready()
    breakdown_payload = player.get('last_breakdown')
    if breakdown_payload: player['last_breakdown'] = None
    return jsonify({"state": room.get_state(int(data.get('last_chat_id', 0))), "breakdown": breakdown_payload, "is_host": player['is_host']})

@app.route('/api/ready', methods=['POST'])
def toggle_ready():
    room = ROOMS.get(request.json.get('room'))
    pid = request.json.get('pid')
    if room and pid in room.players and room.game_type == "anagram":
        room.players[pid]['ready'] = not room.players[pid]['ready']
        room.check_all_ready()
    return jsonify({"state": room.get_state()})

@app.route('/api/chat', methods=['POST'])
def post_chat():
    room = ROOMS.get(request.json.get('room'))
    pid = request.json.get('pid')
    msg = request.json.get('msg', '').strip()
    if room and pid in room.players and msg:
        room.chat_counter += 1
        room.chat_history.append({"id": room.chat_counter, "name": room.players[pid]['name'], "msg": moderate_text(msg[:100])})
    return jsonify({"state": room.get_state(int(request.json.get('last_chat_id', 0)))})

@app.route('/api/game_switch', methods=['POST'])
def game_switch():
    room = ROOMS.get(request.json.get('room'))
    pid = request.json.get('pid')
    gt = request.json.get('game_type')
    if room and pid in room.players and room.players[pid]['is_host'] and not room.game_locked:
        room.game_type = gt
        room.game_locked = True
        room.generate_new_round()
    return jsonify({"state": room.get_state()})

@app.route('/api/control', methods=['POST'])
def control_timer():
    room = ROOMS.get(request.json.get('room'))
    pid = request.json.get('pid')
    action = request.json.get('action')
    if not room or pid not in room.players or not room.players[pid]['is_host']: return jsonify({"status": "denied"})
    
    if action == "pause" and room.game_type == "anagram":
        if room.timer_active:
            room.time_left = max(0, int(room.end_timestamp - time.time()))
            room.timer_active = False
            for p in room.players.values(): p['ready'] = False
    elif action == "limit" and room.game_type == "anagram":
        room.time_limit = max(10, int(request.json.get('limit', 60)))
        room.generate_new_round()
    elif action == "skip" and room.game_type == "anagram":
        room.evaluate_round_conclusion(skipped=True)
    return jsonify({"state": room.get_state()})

@app.route('/api/tq_action', methods=['POST'])
def tq_action():
    room = ROOMS.get(request.json.get('room'))
    pid = request.json.get('pid')
    action = request.json.get('action')
    if not room or pid not in room.players or room.game_type != "twenty_questions": return jsonify({"status": "denied"})
    if action == "become_thinker" and not room.tq_thinker_pid:
        room.tq_thinker_pid = pid
        room.tq_status = "waiting_word"
    elif action == "set_word" and room.tq_thinker_pid == pid:
        room.tq_secret_word = request.json.get('word', '').strip().lower()
        room.tq_status = "active"
    elif action == "ask_question":
        if room.tq_status == "active" and len(room.tq_questions) < 20:
            room.tq_question_counter += 1
            room.tq_questions.append({"id": room.tq_question_counter, "pid": pid, "name": room.players[pid]['name'], "text": request.json.get('text'), "answer": None})
    elif action == "answer_question" and room.tq_thinker_pid == pid:
        qid = request.json.get('qid')
        ans = request.json.get('answer')
        for q in room.tq_questions:
            if q['id'] == qid: q['answer'] = ans
        if ans == "Correct": room.tq_status = "won"
    return jsonify({"state": room.get_state()})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=False)
