import os
import random
import time
import re
from collections import Counter
from flask import Flask, render_template, request, jsonify

app = Flask(
    __name__,
    template_folder=os.path.abspath(
        os.path.join(os.path.dirname(__file__), "templates")
    )
)

app.config["SECRET_KEY"] = os.urandom(24).hex()

# ============================================================
# DICTIONARY
# ============================================================

DICTIONARY_FILE = os.path.join(
    os.path.dirname(__file__),
    "dictionary_filtered.txt"
)

GLOBAL_DICTIONARY = set()

if os.path.exists(DICTIONARY_FILE):
    with open(DICTIONARY_FILE, "r", encoding="utf-8") as f:
        GLOBAL_DICTIONARY = set(
            line.strip().lower()
            for line in f
            if line.strip()
        )

VALID_BASE_WORDS = [
    w for w in GLOBAL_DICTIONARY
    if len(w) == 6
]

if not VALID_BASE_WORDS:
    VALID_BASE_WORDS = [
        "action",
        "actors",
        "advice",
        "angels",
        "artist",
        "assets",
        "backed",
        "baking"
    ]


ROOMS = {}


# ============================================================
# CHAT MODERATION
# ============================================================

def moderate_text(text):
    banned_words = [
        r"crap",
        r"sh+it",
        r"f+u+c+k",
        r"b+i+t+c+h",
        r"a+s+s+h+o+l+e",
        r"d+i+c+k"
    ]

    moderated = text

    for pattern in banned_words:
        moderated = re.sub(
            pattern,
            lambda m: "*" * len(m.group()),
            moderated,
            flags=re.IGNORECASE
        )

    return moderated


# ============================================================
# BLACKJACK HELPERS
# ============================================================

BLACKJACK_SUITS = ["♠", "♥", "♦", "♣"]
BLACKJACK_RANKS = [
    "2", "3", "4", "5", "6", "7", "8", "9",
    "10", "J", "Q", "K", "A"
]


def create_blackjack_deck():
    deck = []

    for suit in BLACKJACK_SUITS:
        for rank in BLACKJACK_RANKS:
            deck.append({
                "rank": rank,
                "suit": suit
            })

    random.shuffle(deck)
    return deck


def blackjack_card_value(card):
    rank = card["rank"]

    if rank in ["J", "Q", "K"]:
        return 10

    if rank == "A":
        return 11

    return int(rank)


def blackjack_hand_value(hand):
    total = sum(
        blackjack_card_value(card)
        for card in hand
    )

    aces = sum(
        1 for card in hand
        if card["rank"] == "A"
    )

    while total > 21 and aces > 0:
        total -= 10
        aces -= 1

    return total


def blackjack_is_blackjack(hand):
    return (
        len(hand) == 2
        and blackjack_hand_value(hand) == 21
    )


def blackjack_card_text(card):
    return f"{card['rank']}{card['suit']}"


# ============================================================
# GAME ROOM
# ============================================================

class GameRoom:

    def __init__(self, room_id):
        self.room_id = room_id

        # Game selection
        self.game_type = "unselected"
        self.game_locked = False

        # Players
        self.players = {}

        # Chat
        self.chat_history = []
        self.chat_counter = 0

        # ----------------------------------------------------
        # ANAGRAM
        # ----------------------------------------------------

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

        # ----------------------------------------------------
        # 20 QUESTIONS
        # ----------------------------------------------------

        self.tq_thinker_pid = None
        self.tq_secret_word = ""
        self.tq_questions = []
        self.tq_status = "waiting_thinker"
        self.tq_question_counter = 0

        # ----------------------------------------------------
        # BLACKJACK
        # ----------------------------------------------------

        self.bj_deck = []
        self.bj_dealer_hand = []
        self.bj_status = "waiting"
        self.bj_round_id = 0

        self.generate_new_round()


    # ========================================================
    # GENERAL ROUND RESET
    # ========================================================

    def generate_new_round(self):

        if self.game_type == "anagram":

            self.base_word = random.choice(
                VALID_BASE_WORDS
            ).lower()

            letters = list(self.base_word)

            while "".join(letters) == self.base_word:
                random.shuffle(letters)

            self.scrambled_letters = letters
            self.valid_anagrams = set()

            base_counter = Counter(self.base_word)

            for word in GLOBAL_DICTIONARY:

                w_low = word.strip().lower()

                if (
                    3 <= len(w_low) <= 6
                    and all(
                        Counter(w_low)[c]
                        <= base_counter[c]
                        for c in w_low
                    )
                ):
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

        elif self.game_type == "blackjack":

            self.start_blackjack_round()

        for player in self.players.values():
            player["current_round_words"] = []
            player["ready"] = False


    # ========================================================
    # BLACKJACK
    # ========================================================

    def start_blackjack_round(self):

        self.bj_deck = create_blackjack_deck()
        self.bj_dealer_hand = []

        self.bj_round_id += 1

        # Deal two cards to every player
        active_players = [
            p for p in self.players.values()
        ]

        for player in active_players:

            player["bj_hand"] = []
            player["bj_status"] = "playing"
            player["bj_result"] = None

        # Deal first player card
        for player in active_players:
            player["bj_hand"].append(
                self.bj_deck.pop()
            )

        # Dealer first card
        self.bj_dealer_hand.append(
            self.bj_deck.pop()
        )

        # Deal second player card
        for player in active_players:
            player["bj_hand"].append(
                self.bj_deck.pop()
            )

        # Dealer second card
        self.bj_dealer_hand.append(
            self.bj_deck.pop()
        )

        self.bj_status = "playing"

        # Immediately resolve natural blackjacks
        for player in active_players:

            if blackjack_is_blackjack(
                player["bj_hand"]
            ):
                player["bj_status"] = "blackjack"

        self.check_blackjack_completion()


    def active_blackjack_players(self):

        return [
            p for p in self.players.values()
            if p.get("bj_status") == "playing"
        ]


    def check_blackjack_completion(self):

        if self.bj_status != "playing":
            return

        active = self.active_blackjack_players()

        # Everyone has either blackjack or finished
        if not active:
            self.finish_blackjack_round()


    def blackjack_hit(self, pid):

        if self.bj_status != "playing":
            return False, "The round is not active."

        player = self.players.get(pid)

        if not player:
            return False, "Player not found."

        if player.get("bj_status") != "playing":
            return False, "You cannot hit right now."

        if not self.bj_deck:
            return False, "The deck is empty."

        player["bj_hand"].append(
            self.bj_deck.pop()
        )

        value = blackjack_hand_value(
            player["bj_hand"]
        )

        if value > 21:
            player["bj_status"] = "bust"

        elif value == 21:
            player["bj_status"] = "stand"

        self.check_blackjack_completion()

        return True, None


    def blackjack_stand(self, pid):

        if self.bj_status != "playing":
            return False, "The round is not active."

        player = self.players.get(pid)

        if not player:
            return False, "Player not found."

        if player.get("bj_status") != "playing":
            return False, "You cannot stand right now."

        player["bj_status"] = "stand"

        self.check_blackjack_completion()

        return True, None


    def finish_blackjack_round(self):

        if self.bj_status == "finished":
            return

        self.bj_status = "dealer"

        # Dealer plays using standard casino rule:
        # stand on 17 or higher.
        while blackjack_hand_value(
            self.bj_dealer_hand
        ) < 17:

            if not self.bj_deck:
                break

            self.bj_dealer_hand.append(
                self.bj_deck.pop()
            )

        dealer_value = blackjack_hand_value(
            self.bj_dealer_hand
        )

        dealer_blackjack = blackjack_is_blackjack(
            self.bj_dealer_hand
        )

        for player in self.players.values():

            status = player.get("bj_status")

            if status == "blackjack":

                if dealer_blackjack:
                    player["bj_result"] = "push"
                    player["score"] += 5
                else:
                    player["bj_result"] = "blackjack"
                    player["score"] += 15

                continue

            player_value = blackjack_hand_value(
                player.get("bj_hand", [])
            )

            if status == "bust":

                player["bj_result"] = "lose"

            elif dealer_value > 21:

                player["bj_result"] = "win"
                player["score"] += 10

            elif player_value > dealer_value:

                player["bj_result"] = "win"
                player["score"] += 10

            elif player_value == dealer_value:

                player["bj_result"] = "push"
                player["score"] += 5

            else:

                player["bj_result"] = "lose"

        self.bj_status = "finished"


    # ========================================================
    # ANAGRAM SCORING
    # ========================================================

    def evaluate_round_conclusion(self, skipped=False):

        if self.game_type != "anagram":
            return

        score_chart = {
            3: 100,
            4: 400,
            5: 1200,
            6: 2000
        }

        for pid, player in self.players.items():

            unique_guesses = list(
                dict.fromkeys(
                    player.get(
                        "current_round_words",
                        []
                    )
                )
            )

            breakdown = []

            round_score = player.get(
                "score",
                0
            )

            for guess in unique_guesses:

                g_low = guess.strip().lower()

                if g_low in self.valid_anagrams:

                    pts = score_chart.get(
                        len(g_low),
                        0
                    )

                    round_score += pts

                    breakdown.append({
                        "word": g_low,
                        "valid": True,
                        "points": pts
                    })

                else:

                    breakdown.append({
                        "word": g_low,
                        "valid": False,
                        "points": 0
                    })

            player["score"] = round_score

            player["last_breakdown"] = {
                "breakdown": breakdown,
                "round_word": self.base_word,
                "skipped": skipped
            }

        self.generate_new_round()


    # ========================================================
    # ANAGRAM TIMER
    # ========================================================

    def check_timer(self):

        if self.game_type != "anagram":
            return False

        if self.countdown_active:

            if time.time() >= self.countdown_end:

                self.countdown_active = False
                self.timer_active = True

                self.end_timestamp = (
                    time.time()
                    + self.time_left
                )

            return False

        if self.timer_active:

            self.time_left = int(
                self.end_timestamp
                - time.time()
            )

            if self.time_left <= 0:

                self.evaluate_round_conclusion(
                    skipped=False
                )

                return True

        return False


    def check_all_ready(self):

        if (
            not self.players
            or self.game_type != "anagram"
        ):
            return False

        if (
            all(
                p["ready"]
                for p in self.players.values()
            )
            and not self.timer_active
            and not self.countdown_active
        ):

            self.countdown_active = True

            self.countdown_end = (
                time.time() + 3
            )

            # Clear old submissions immediately
            for p in self.players.values():
                p["current_round_words"] = []

            return True

        return False


    # ========================================================
    # STATE
    # ========================================================

    def get_state(self, last_chat_id=0, pid=None):

        now = time.time()

        self.players = {
            sid: p
            for sid, p in self.players.items()
            if now - p["last_seen"] < 10
        }

        new_chats = [
            c
            for c in self.chat_history
            if c["id"] > last_chat_id
        ]

        # ----------------------------------------------------
        # ANAGRAM STATE
        # ----------------------------------------------------

        reveal_letters = self.timer_active

        letters_payload = (
            self.scrambled_letters
            if reveal_letters
            else ["?"] * 6
        )

        display_time = (
            max(
                0,
                int(
                    self.countdown_end
                    - time.time()
                )
            )
            if self.countdown_active
            else self.time_left
        )

        # ----------------------------------------------------
        # BLACKJACK STATE
        # ----------------------------------------------------

        blackjack_state = {
            "status": self.bj_status,
            "round_id": self.bj_round_id,
            "dealer_hand": [],
            "dealer_value": None,
            "your_hand": [],
            "your_value": 0,
            "your_status": None,
            "your_result": None,
            "players": [],
            "can_hit": False,
            "can_stand": False
        }

        if self.game_type == "blackjack":

            # Only expose dealer's first card while active
            if self.bj_status == "playing":

                if self.bj_dealer_hand:

                    blackjack_state[
                        "dealer_hand"
                    ] = [
                        self.bj_dealer_hand[0]
                    ]

                    blackjack_state[
                        "dealer_hand"
                    ].append({
                        "rank": "?",
                        "suit": "?"
                    })

            else:

                blackjack_state[
                    "dealer_hand"
                ] = list(
                    self.bj_dealer_hand
                )

                blackjack_state[
                    "dealer_value"
                ] = blackjack_hand_value(
                    self.bj_dealer_hand
                )

            if pid in self.players:

                player = self.players[pid]

                blackjack_state[
                    "your_hand"
                ] = player.get(
                    "bj_hand",
                    []
                )

                blackjack_state[
                    "your_value"
                ] = blackjack_hand_value(
                    player.get(
                        "bj_hand",
                        []
                    )
                )

                blackjack_state[
                    "your_status"
                ] = player.get(
                    "bj_status"
                )

                blackjack_state[
                    "your_result"
                ] = player.get(
                    "bj_result"
                )

                blackjack_state[
                    "can_hit"
                ] = (
                    self.bj_status == "playing"
                    and player.get(
                        "bj_status"
                    ) == "playing"
                )

                blackjack_state[
                    "can_stand"
                ] = (
                    self.bj_status == "playing"
                    and player.get(
                        "bj_status"
                    ) == "playing"
                )

            for sid, player in self.players.items():

                blackjack_state[
                    "players"
                ].append({
                    "sid": sid,
                    "name": player["name"],
                    "cards": len(
                        player.get(
                            "bj_hand",
                            []
                        )
                    ),
                    "status": player.get(
                        "bj_status"
                    ),
                    "result": player.get(
                        "bj_result"
                    )
                })

        # ----------------------------------------------------
        # LEADERBOARD
        # ----------------------------------------------------

        leaderboard = sorted(
            [
                {
                    "sid": sid,
                    "name": player["name"],
                    "score": player["score"],
                    "is_host": player["is_host"],
                    "ready": player["ready"]
                }
                for sid, player
                in self.players.items()
            ],
            key=lambda p: (
                -p["score"],
                p["name"].lower()
            )
        )

        return {
            "game_type": self.game_type,
            "game_locked": self.game_locked,

            "letters": letters_payload,
            "time_left": display_time,
            "timer_active": self.timer_active,
            "countdown_active": self.countdown_active,
            "round_id": self.round_id,

            "new_chats": new_chats,

            # 20 Questions
            "tq_thinker_pid": self.tq_thinker_pid,
            "tq_secret_word": (
                self.tq_secret_word
                if self.tq_status == "won"
                else (
                    "???"
                    if self.tq_secret_word
                    else ""
                )
            ),
            "tq_status": self.tq_status,
            "tq_questions": self.tq_questions,

            # Blackjack
            "blackjack": blackjack_state,

            # Sorted standings
            "leaderboard": leaderboard
        }


# ============================================================
# INDEX
# ============================================================

@app.route("/")
def index():
    return render_template("index.html")


# ============================================================
# JOIN
# ============================================================

@app.route("/api/join", methods=["POST"])
def join_game():

    data = request.json or {}

    room_id = (
        data.get("room", "lounge")
        .strip()
        or "lounge"
    )

    pid = (
        data.get("pid")
        or os.urandom(8).hex()
    )

    if room_id not in ROOMS:
        ROOMS[room_id] = GameRoom(room_id)

    room = ROOMS[room_id]

    name = (
        data.get("name", "User")
        .strip()
        or "User"
    )

    is_existing_player = pid in room.players

    if is_existing_player:

        player = room.players[pid]
        player["name"] = name
        player["last_seen"] = time.time()

    else:

        is_host = len(room.players) == 0

        room.players[pid] = {
            "name": name,
            "score": 0,
            "current_round_words": [],
            "is_host": is_host,
            "last_seen": time.time(),
            "ready": False,
            "last_breakdown": None,

            # Blackjack
            "bj_hand": [],
            "bj_status": "waiting",
            "bj_result": None
        }

    return jsonify({
        "pid": pid,
        "is_host": room.players[pid]["is_host"],
        "state": room.get_state(
            pid=pid
        )
    })


# ============================================================
# SYNC
# ============================================================

@app.route("/api/sync", methods=["POST"])
def sync_game():

    data = request.json or {}

    room = ROOMS.get(
        data.get("room")
    )

    pid = data.get("pid")

    if (
        not room
        or pid not in room.players
    ):
        return jsonify({
            "error": "Expired"
        }), 404

    player = room.players[pid]

    player["last_seen"] = time.time()

    # Anagram buffered words
    if (
        room.timer_active
        and room.game_type == "anagram"
    ):

        raw_words = data.get(
            "buffered_words",
            []
        )

        player["current_round_words"] = [
            str(w).strip().lower()
            for w in raw_words
        ]

    room.check_timer()
    room.check_all_ready()

    breakdown_payload = player.get(
        "last_breakdown"
    )

    if breakdown_payload:
        player["last_breakdown"] = None

    return jsonify({
        "state": room.get_state(
            int(
                data.get(
                    "last_chat_id",
                    0
                )
            ),
            pid=pid
        ),
        "breakdown": breakdown_payload,
        "is_host": player["is_host"]
    })


# ============================================================
# READY
# ============================================================

@app.route("/api/ready", methods=["POST"])
def toggle_ready():

    data = request.json or {}

    room = ROOMS.get(
        data.get("room")
    )

    pid = data.get("pid")

    if (
        room
        and pid in room.players
        and room.game_type == "anagram"
    ):

        room.players[pid]["ready"] = not (
            room.players[pid]["ready"]
        )

        room.check_all_ready()

    return jsonify({
        "state": room.get_state(
            pid=pid
        ) if room else {}
    })


# ============================================================
# CHAT
# ============================================================

@app.route("/api/chat", methods=["POST"])
def post_chat():

    data = request.json or {}

    room = ROOMS.get(
        data.get("room")
    )

    pid = data.get("pid")

    msg = (
        data.get("msg", "")
        .strip()
    )

    if (
        room
        and pid in room.players
        and msg
    ):

        room.chat_counter += 1

        room.chat_history.append({
            "id": room.chat_counter,
            "name": room.players[pid]["name"],
            "msg": moderate_text(
                msg[:100]
            )
        })

    return jsonify({
        "state": room.get_state(
            int(
                data.get(
                    "last_chat_id",
                    0
                )
            ),
            pid=pid
        ) if room else {}
    })


# ============================================================
# GAME SWITCH
# ============================================================

@app.route("/api/game_switch", methods=["POST"])
def game_switch():

    data = request.json or {}

    room = ROOMS.get(
        data.get("room")
    )

    pid = data.get("pid")

    gt = data.get(
        "game_type"
    )

    valid_games = {
        "anagram",
        "twenty_questions",
        "blackjack"
    }

    if (
        room
        and pid in room.players
        and room.players[pid]["is_host"]
        and not room.game_locked
        and gt in valid_games
    ):

        room.game_type = gt
        room.game_locked = True

        # Reset scores when a new game is selected
        for player in room.players.values():
            player["score"] = 0
            player["current_round_words"] = []
            player["ready"] = False
            player["last_breakdown"] = None

        room.generate_new_round()

    return jsonify({
        "state": room.get_state(
            pid=pid
        ) if room else {}
    })


# ============================================================
# ANAGRAM HOST CONTROL
# ============================================================

@app.route("/api/control", methods=["POST"])
def control_timer():

    data = request.json or {}

    room = ROOMS.get(
        data.get("room")
    )

    pid = data.get("pid")
    action = data.get("action")

    if (
        not room
        or pid not in room.players
        or not room.players[pid]["is_host"]
    ):
        return jsonify({
            "status": "denied"
        })

    if (
        action == "pause"
        and room.game_type == "anagram"
    ):

        if room.timer_active:

            room.time_left = max(
                0,
                int(
                    room.end_timestamp
                    - time.time()
                )
            )

            room.timer_active = False

            for p in room.players.values():
                p["ready"] = False

    elif (
        action == "limit"
        and room.game_type == "anagram"
    ):

        room.time_limit = max(
            10,
            int(
                data.get(
                    "limit",
                    60
                )
            )
        )

        room.generate_new_round()

    elif (
        action == "skip"
        and room.game_type == "anagram"
    ):

        room.evaluate_round_conclusion(
            skipped=True
        )

    return jsonify({
        "state": room.get_state(
            pid=pid
        )
    })


# ============================================================
# 20 QUESTIONS
# ============================================================

@app.route("/api/tq_action", methods=["POST"])
def tq_action():

    data = request.json or {}

    room = ROOMS.get(
        data.get("room")
    )

    pid = data.get("pid")
    action = data.get("action")

    if (
        not room
        or pid not in room.players
        or room.game_type != "twenty_questions"
    ):
        return jsonify({
            "status": "denied"
        })

    # --------------------------------------------------------
    # Start a new round
    # --------------------------------------------------------

    if (
        action == "become_thinker"
        and room.tq_status in [
            "waiting_thinker",
            "won"
        ]
    ):

        room.tq_thinker_pid = pid
        room.tq_secret_word = ""
        room.tq_questions = []
        room.tq_question_counter = 0
        room.tq_status = "waiting_word"
        room.round_id += 1

    # --------------------------------------------------------
    # Set secret word
    # --------------------------------------------------------

    elif (
        action == "set_word"
        and room.tq_thinker_pid == pid
        and room.tq_status == "waiting_word"
    ):

        word = (
            data.get("word", "")
            .strip()
            .lower()
        )

        if word:

            room.tq_secret_word = word
            room.tq_status = "active"

    # --------------------------------------------------------
    # Ask question
    # --------------------------------------------------------

    elif action == "ask_question":

        if (
            room.tq_status == "active"
            and len(room.tq_questions) < 20
            and pid != room.tq_thinker_pid
        ):

            room.tq_question_counter += 1

            room.tq_questions.append({
                "id": room.tq_question_counter,
                "pid": pid,
                "name": room.players[pid]["name"],
                "text": str(
                    data.get(
                        "text",
                        ""
                    )
                )[:200],
                "answer": None
            })

    # --------------------------------------------------------
    # Answer question
    # --------------------------------------------------------

    elif (
        action == "answer_question"
        and room.tq_thinker_pid == pid
    ):

        qid = data.get("qid")
        ans = data.get("answer")

        allowed_answers = {
            "Yes",
            "No",
            "Maybe",
            "Correct"
        }

        if ans not in allowed_answers:
            return jsonify({
                "state": room.get_state(
                    pid=pid
                )
            })

        for q in room.tq_questions:

            if q["id"] == qid:
                q["answer"] = ans

        if ans == "Correct":
            room.tq_status = "won"

    return jsonify({
        "state": room.get_state(
            pid=pid
        )
    })


# ============================================================
# BLACKJACK ACTION
# ============================================================

@app.route("/api/blackjack_action", methods=["POST"])
def blackjack_action():

    data = request.json or {}

    room = ROOMS.get(
        data.get("room")
    )

    pid = data.get("pid")
    action = data.get("action")

    if (
        not room
        or pid not in room.players
        or room.game_type != "blackjack"
    ):
        return jsonify({
            "status": "denied"
        })

    # --------------------------------------------------------
    # HIT
    # --------------------------------------------------------

    if action == "hit":

        success, error = room.blackjack_hit(
            pid
        )

        if not success:

            return jsonify({
                "status": "error",
                "message": error,
                "state": room.get_state(
                    pid=pid
                )
            })

    # --------------------------------------------------------
    # STAND
    # --------------------------------------------------------

    elif action == "stand":

        success, error = room.blackjack_stand(
            pid
        )

        if not success:

            return jsonify({
                "status": "error",
                "message": error,
                "state": room.get_state(
                    pid=pid
                )
            })

    # --------------------------------------------------------
    # NEW ROUND
    # --------------------------------------------------------

    elif action == "new_round":

        if (
            room.bj_status != "finished"
            or not room.players[pid]["is_host"]
        ):

            return jsonify({
                "status": "denied",
                "state": room.get_state(
                    pid=pid
                )
            })

        room.start_blackjack_round()

    else:

        return jsonify({
            "status": "error",
            "message": "Unknown Blackjack action.",
            "state": room.get_state(
                pid=pid
            )
        })

    return jsonify({
        "status": "ok",
        "state": room.get_state(
            pid=pid
        )
    })


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=5001,
        debug=False
    )
