import os,random,time,re
from collections import Counter
from flask import Flask,render_template,request,jsonify

app=Flask(__name__,template_folder=os.path.join(os.path.dirname(__file__),"templates"))
app.config["SECRET_KEY"]=os.urandom(24).hex()
DF=os.path.join(os.path.dirname(__file__),"dictionary_filtered.txt")
WORDS=set()
if os.path.exists(DF):
    with open(DF,encoding="utf-8") as f: WORDS={x.strip().lower() for x in f if x.strip()}
BASE=[x for x in WORDS if len(x)==6] or ["action","actors","advice","angels","artist","assets","backed","baking"]
PAIRS=[("apple","pear"),("dog","wolf"),("cat","tiger"),("beach","desert"),("school","university"),("coffee","tea"),("pizza","burger"),("football","rugby"),("basketball","netball"),("car","motorcycle"),("train","bus"),("ocean","river"),("mountain","hill"),("summer","winter"),("doctor","nurse"),("movie","tv"),("phone","computer"),("book","magazine"),("cake","cookie"),("lion","tiger"),("snake","lizard"),("airport","station"),("hotel","house"),("fire","smoke"),("rain","snow"),("sun","moon"),("king","queen"),("teacher","student"),("guitar","piano")]
SUITS=["♠","♥","♦","♣"];RANKS=["2","3","4","5","6","7","8","9","10","J","Q","K","A"];RV={r:i+2 for i,r in enumerate(RANKS)}

def card(r,s): return {"rank":r,"suit":s}
def deck(): return [card(r,s) for s in SUITS for r in RANKS]
def value(h):
    v=sum(min(RV[c["rank"]],10) for c in h);a=sum(c["rank"]=="A" for c in h)
    while a and v+10<=21:v+=10;a-=1
    return v

def poker_eval(cs):
    vals=sorted((RV[c["rank"]] for c in cs),reverse=True);cnt=Counter(vals);u=sorted(set(vals),reverse=True)
    if 14 in u:u.append(1)
    st=max((u[i] for i in range(len(u)-4) if u[i]-u[i+4]==4),default=0)
    flushes=[s for s in SUITS if sum(c["suit"]==s for c in cs)>=5]
    for s in flushes:
        fv=sorted((RV[c["rank"]] for c in cs if c["suit"]==s),reverse=True)
        if 14 in fv:fv.append(1)
        sf=max((fv[i] for i in range(len(fv)-4) if fv[i]-fv[i+4]==4),default=0)
        if sf:return (8,sf)
    q=sorted((v for v,n in cnt.items() if n==4),reverse=True)
    if q:return (7,q[0],max(v for v in vals if v!=q[0]))
    trips=sorted((v for v,n in cnt.items() if n>=3),reverse=True);pairs=sorted((v for v,n in cnt.items() if n>=2),reverse=True)
    if trips and len(pairs)>1:return (6,trips[0],max(v for v in pairs if v!=trips[0]))
    if flushes:
        s=flushes[0];return (5,*sorted((RV[c["rank"]] for c in cs if c["suit"]==s),reverse=True)[:5])
    if st:return (4,st)
    if trips:
        k=sorted((v for v in vals if v!=trips[0]),reverse=True)[:2];return (3,trips[0],*k)
    if len(pairs)>1:
        k1,k2=pairs[:2];return (2,k1,k2,max(v for v in vals if v not in (k1,k2)))
    if pairs:
        k=sorted((v for v in vals if v!=pairs[0]),reverse=True)[:3];return (1,pairs[0],*k)
    return (0,*vals[:5])

def mod(t):
    for p in [r"crap",r"sh+it",r"f+u+c+k",r"b+i+t+c+h",r"a+s+s+h+o+l+e",r"d+i+c+k"]:t=re.sub(p,lambda m:"*"*len(m.group()),str(t),flags=re.I)
    return t

class Room:
    def __init__(self,rid):
        self.id=rid;self.game="unselected";self.locked=False;self.players={};self.chat=[];self.chat_id=0
        self.time_limit=60;self.time_left=60;self.end=0;self.timer=False;self.countdown=False;self.countend=0;self.round=0
        self.tq={};self.imp={};self.bj={};self.poker={};self.new_round()

    def reset_scores(self):
        for p in self.players.values():p.update(score=0,words=[],ready=False,last_breakdown=None,breakdown_round=-1)

    def new_round(self):
        self.timer=False;self.countdown=False;self.end=0;self.time_left=self.time_limit
        if self.game=="anagram":
            self.base=random.choice(BASE);a=list(self.base)
            while "".join(a)==self.base:random.shuffle(a)
            self.letters=a;bc=Counter(self.base)
            self.valid={w for w in WORDS if 3<=len(w)<=6 and all(Counter(w)[c]<=bc[c] for c in Counter(w))}
        elif self.game=="twenty_questions":self.tq={"thinker":None,"word":"","questions":[],"status":"waiting_thinker","qid":0}
        elif self.game=="imposter":self.imp={"status":"waiting","main":"","fake":"","imp":None,"order":[],"turn":0,"clues":[],"votes":{},"result":None}
        elif self.game=="blackjack":self.start_bj()
        elif self.game=="poker":self.start_poker()
        for p in self.players.values():p["words"]=[];p["ready"]=False
        self.round+=1

    def start_bj(self):
        d=deck();random.shuffle(d);self.bj={"deck":d,"dealer":[d.pop(),d.pop()],"status":"playing"}
        for p in self.players.values():
            p["bj_hand"]=[d.pop(),d.pop()];p["bj_status"]="blackjack" if value(p["bj_hand"])==21 else "playing";p["bj_result"]=None
        self.resolve_bj()

    def resolve_bj(self):
        if any(p.get("bj_status")=="playing" for p in self.players.values()):return
        self.bj["status"]="dealer"
        while value(self.bj["dealer"])<17:self.bj["dealer"].append(self.bj["deck"].pop())
        dv=value(self.bj["dealer"])
        for p in self.players.values():
            pv=value(p["bj_hand"]);st=p["bj_status"]
            if st=="blackjack":r,pts="blackjack",15
            elif st=="bust":r,pts="lose",0
            elif dv>21 or pv>dv:r,pts="win",10
            elif pv==dv:r,pts="push",5
            else:r,pts="lose",0
            p["bj_result"]=r;p["score"]+=pts
        self.bj["status"]="finished"

    def bj_action(self,pid,a):
        if self.bj.get("status")!="playing":return "Round is finished."
        p=self.players[pid]
        if p.get("bj_status")!="playing":return "You cannot act."
        if a=="hit":
            p["bj_hand"].append(self.bj["deck"].pop());v=value(p["bj_hand"])
            p["bj_status"]="bust" if v>21 else ("stand" if v==21 else "playing")
        elif a=="stand":p["bj_status"]="stand"
        else:return "Invalid action."
        self.resolve_bj();return ""

    def start_poker(self):
        ids=list(self.players)
        if len(ids)<2:self.poker={"phase":"waiting","dealer":-1,"current":None,"deck":[]};return
        for p in self.players.values():p["chips"]=p.get("chips",1000) or 1000
        old=self.poker.get("dealer",-1) if self.poker else -1
        po={"phase":"preflop","dealer":(old+1)%len(ids),"current":None,"deck":deck(),"community":[],"pot":0,"bet":0,"minraise":20,"folded":set(),"allin":set(),"acted":set(),"results":{}}
        random.shuffle(po["deck"]);self.poker=po
        for p in self.players.values():p["pocket"]=[po["deck"].pop(),po["deck"].pop()];p["pbet"]=0;p["pstatus"]="playing"
        sb=(po["dealer"]+1)%len(ids);bb=(po["dealer"]+2)%len(ids) if len(ids)>2 else (po["dealer"]+1)%len(ids)
        self.take_bet(ids[sb],10);self.take_bet(ids[bb],20);po["bet"]=max(p["pbet"] for p in self.players.values())
        po["current"]=po["dealer"] if len(ids)==2 else self.next_active(ids,bb);self.check_poker()

    def take_bet(self,pid,n):
        p=self.players[pid];n=max(0,min(int(n),p["chips"]));p["chips"]-=n;p["pbet"]+=n;self.poker["pot"]+=n
        if p["chips"]==0:self.poker["allin"].add(pid)

    def next_active(self,ids,start):
        if not ids:return None
        base=ids.index(start) if start in ids else 0
        for i in range(1,len(ids)+1):
            x=ids[(base+i)%len(ids)]
            if x not in self.poker["folded"] and x not in self.poker["allin"]:return x
        return None

    def poker_action(self,pid,a,amt=0):
        po=self.poker
        if po.get("phase") not in ("preflop","flop","turn","river") or po.get("current")!=pid:return "Not your turn."
        p=self.players[pid];to=po["bet"]-p["pbet"];raised=False
        if a=="fold":po["folded"].add(pid);p["pstatus"]="folded"
        elif a=="check":
            if to:return "You must call or raise."
        elif a=="call":
            if not to:return "Nothing to call."
            self.take_bet(pid,to)
        elif a in ("raise","allin"):
            target=p["pbet"]+p["chips"] if a=="allin" else max(po["bet"]+po["minraise"],int(amt or 0))
            if target<=p["pbet"]:return "Raise amount is too small."
            add=target-p["pbet"];self.take_bet(pid,add)
            if target>po["bet"]:
                po["minraise"]=max(po["minraise"],target-po["bet"]);po["bet"]=target;raised=True
        else:return "Invalid action."
        po["acted"].add(pid)
        active=[x for x in self.players if x not in po["folded"]]
        if len(active)==1:
            w=active[0];self.players[w]["chips"]+=po["pot"];po["results"]={w:"win"};po["pot"]=0;po["phase"]="finished";po["current"]=None;return ""
        need=[x for x in active if x not in po["allin"]]
        complete=not need or all(x in po["acted"] and self.players[x]["pbet"]==po["bet"] for x in need)
        if complete:
            for q in self.players.values():q["pbet"]=0
            po["bet"]=0;po["acted"]=set();self.advance_poker()
        else:
            po["current"]=self.next_active(list(self.players),pid)
            if po["current"] is None:self.advance_poker()
        return ""

    def check_poker(self):
        po=self.poker;ids=list(self.players);active=[x for x in ids if x not in po.get("folded",set())]
        if len(active)==1:
            w=active[0];self.players[w]["chips"]+=po["pot"];po["results"]={w:"win"};po["pot"]=0;po["phase"]="finished";po["current"]=None;return
        need=[x for x in active if x not in po["allin"]]
        if po.get("current") is not None:
            if need and not all(x in po["acted"] and self.players[x]["pbet"]==po["bet"] for x in need):return
        for p in self.players.values():p["pbet"]=0
        po["bet"]=0;po["acted"]=set();self.advance_poker()

    def advance_poker(self):
        po=self.poker
        if po["phase"]=="preflop":po["community"] += [po["deck"].pop() for _ in range(3)];po["phase"]="flop"
        elif po["phase"]=="flop":po["community"].append(po["deck"].pop());po["phase"]="turn"
        elif po["phase"]=="turn":po["community"].append(po["deck"].pop());po["phase"]="river"
        elif po["phase"]=="river":self.showdown();return
        active=[x for x in self.players if x not in po["folded"] and x not in po["allin"]]
        po["current"]=self.next_active(list(self.players),po["dealer"]) if active else None
        if po["current"] is None:self.advance_poker()

    def showdown(self):
        po=self.poker;active=[x for x in self.players if x not in po["folded"]]
        scores={x:poker_eval(self.players[x]["pocket"]+po["community"]) for x in active};best=max(scores.values());wins=[x for x,v in scores.items() if v==best]
        share=po["pot"]//len(wins);rem=po["pot"]%len(wins)
        for i,w in enumerate(wins):self.players[w]["chips"]+=share+(i<rem);po["results"][w]="win"
        for x in active:
            if x not in wins:po["results"][x]="lose"
        po["pot"]=0;po["phase"]="finished";po["current"]=None

    def imp_start(self):
        if len(self.players)<3:return False
        a,b=random.choice(PAIRS);ids=list(self.players);random.shuffle(ids);self.imp={"status":"clues","main":a,"fake":b,"imp":ids[0],"order":ids,"turn":0,"clues":[],"votes":{},"result":None}
        for x in ids:self.players[x]["imp_word"]=b if x==ids[0] else a
        return True

    def imp_action(self,pid,a,d):
        x=self.imp
        if a=="start":
            if not self.players[pid]["is_host"]:return False,"Host only."
            return (self.imp_start(),"Need at least 3 players." if len(self.players)<3 else "")
        if a=="clue":
            if x["status"]!="clues" or x["order"][x["turn"]]!=pid:return False,"Not your turn."
            c=mod(str(d.get("clue","")).strip())[:30]
            if not c:return False,"Enter a clue."
            x["clues"].append({"pid":pid,"name":self.players[pid]["name"],"clue":c});x["turn"]+=1
            if x["turn"]>=len(x["order"]):x["status"]="voting"
            return True,""
        if a=="vote":
            t=d.get("target")
            if x["status"]!="voting" or t==pid or t not in self.players or pid in x["votes"]:return False,"Invalid vote."
            x["votes"][pid]=t
            if len(x["votes"])==len(self.players):self.imp_resolve()
            return True,""
        if a=="next_round" and self.players[pid]["is_host"] and x["status"]=="result":self.new_round();return True,""
        return False,"Invalid action."

    def imp_resolve(self):
        c=Counter(self.imp["votes"].values());m=max(c.values());leaders=[x for x,n in c.items() if n==m];caught=len(leaders)==1 and leaders[0]==self.imp["imp"]
        if caught:
            for pid,t in self.imp["votes"].items():
                if t==self.imp["imp"]:self.players[pid]["score"]+=2
        else:self.players[self.imp["imp"]]["score"]+=3
        self.imp["result"]={"imp":self.imp["imp"],"name":self.players[self.imp["imp"]]["name"],"caught":caught,"votes":dict(c),"main":self.imp["main"],"fake":self.imp["fake"]};self.imp["status"]="result"

    def tq_action(self,pid,a,d):
        t=self.tq
        if a=="become_thinker" and (not t["thinker"] or t["status"]=="won"):t.update(thinker=pid,word="",questions=[],status="waiting_word",qid=0)
        elif a=="set_word" and t["thinker"]==pid and d.get("word"):t["word"]=str(d["word"]).strip().lower();t["status"]="active"
        elif a=="ask_question" and t["status"]=="active" and len(t["questions"])<20 and pid!=t["thinker"]:
            t["qid"]+=1;t["questions"].append({"id":t["qid"],"pid":pid,"name":self.players[pid]["name"],"text":str(d.get("text",""))[:100],"answer":None})
        elif a=="answer_question" and t["thinker"]==pid:
            for q in t["questions"]:
                if q["id"]==d.get("qid"):q["answer"]=d.get("answer")
            if d.get("answer")=="Correct":t["status"]="won"

    def timer_check(self):
        if self.game!="anagram":return
        if self.countdown and time.time()>=self.countend:self.countdown=False;self.timer=True;self.end=time.time()+self.time_left
        if self.timer:
            self.time_left=max(0,int(self.end-time.time()))
            if self.time_left<=0:self.end_anagram()

    def end_anagram(self,skip=False):
        if not self.timer and not skip:return
        pts={3:100,4:400,5:1200,6:2000};rid=self.round
        for p in self.players.values():
            bd=[]
            for w in dict.fromkeys(p.get("words",[])):
                ok=w in self.valid;n=pts.get(len(w),0) if ok else 0;p["score"]+=n;bd.append({"word":w,"valid":ok,"points":n})
            p["last_breakdown"]={"breakdown":bd,"round_word":self.base,"skipped":skip};p["breakdown_round"]=rid;p["words"]=[]
        self.new_round()

    def ready(self):
        if self.game=="anagram" and self.players and all(p["ready"] for p in self.players.values()) and not self.timer and not self.countdown:
            for p in self.players.values():p["words"]=[]
            self.countdown=True;self.countend=time.time()+3

    def cleanup(self):
        now=time.time();dead=[pid for pid,p in self.players.items() if now-p.get("last_seen",now)>45]
        for pid in dead:self.players.pop(pid,None)
        if self.players and not any(p["is_host"] for p in self.players.values()):next(iter(self.players.values()))["is_host"]=True

    def state(self,pid,last_chat=0):
        self.cleanup();self.timer_check();pl=sorted(self.players.items(),key=lambda z:(-z[1]["score"],z[1]["name"].lower()));x=self.imp;b=self.bj;po=self.poker
        p=self.players.get(pid,{})
        s={"game_type":self.game,"game_locked":self.locked,"letters":self.letters if self.game=="anagram" and self.timer else ["?"]*6,"time_left":max(0,int(self.countend-time.time())) if self.countdown else self.time_left,"timer_active":self.timer,"countdown_active":self.countdown,"round_id":self.round,"new_chats":[c for c in self.chat if c["id"]>last_chat],"leaderboard":[{"sid":i,"name":q["name"],"score":q["score"],"is_host":q["is_host"],"ready":q["ready"]} for i,q in pl]}
        s.update(tq_thinker_pid=self.tq.get("thinker"),tq_secret_word=self.tq.get("word") if self.tq.get("status")=="won" else ("???" if self.tq.get("word") else ""),tq_status=self.tq.get("status"),tq_questions=self.tq.get("questions",[]))
        s.update(imp_status=x.get("status"),imp_round_ready=len(self.players)>=3,imp_your_word=p.get("imp_word"),imp_current_turn=x.get("order",[])[x.get("turn",0)] if x.get("status")=="clues" and x.get("turn",0)<len(x.get("order",[])) else None,imp_clues=x.get("clues",[]),imp_players=[{"pid":i,"name":q["name"]} for i,q in self.players.items()],imp_votes=x.get("votes",{}) if x.get("status")=="result" else {},imp_result=x.get("result"),imp_is_imposter=pid==x.get("imp") if pid else False)
        s["blackjack"]={"status":b.get("status"),"dealer_hand":[b["dealer"][0],{"rank":"?","suit":"?"}] if b.get("status")=="playing" else b.get("dealer",[]),"dealer_value":value(b["dealer"]) if b.get("status")!="playing" and b.get("dealer") else None,"your_hand":p.get("bj_hand",[]),"your_value":value(p.get("bj_hand",[])) if p.get("bj_hand") else None,"your_status":p.get("bj_status"),"your_result":p.get("bj_result"),"can_hit":b.get("status")=="playing" and p.get("bj_status")=="playing","can_stand":b.get("status")=="playing" and p.get("bj_status")=="playing","players":[{"sid":i,"name":q["name"],"cards":len(q.get("bj_hand",[])),"status":q.get("bj_status","waiting"),"result":q.get("bj_result")} for i,q in self.players.items()]}
        s["poker"]={"phase":po.get("phase"),"community":po.get("community",[]),"pot":po.get("pot",0),"current":po.get("current"),"bet":po.get("bet",0),"your_hand":p.get("pocket",[]),"your_chips":p.get("chips",1000),"your_bet":p.get("pbet",0),"can_act":po.get("current")==pid,"players":[{"pid":i,"name":q["name"],"chips":q.get("chips",1000),"bet":q.get("pbet",0),"status":"folded" if i in po.get("folded",set()) else ("all-in" if i in po.get("allin",set()) else ("turn" if i==po.get("current") else "playing"))} for i,q in self.players.items()],"results":po.get("results",{})}
        return s

ROOMS={}
def get_room(d):
    r=ROOMS.get((d or {}).get("room"));pid=(d or {}).get("pid")
    return r,pid

def response(r,pid,d=None,**extra):return jsonify(state=r.state(pid,int((d or {}).get("last_chat_id",0))),**extra)

@app.get("/")
def index():return render_template("index.html")

@app.post("/api/join")
def join():
    d=request.json or {};rid=(d.get("room") or "lounge").strip() or "lounge";incoming=str(d.get("pid") or "")
    if rid not in ROOMS:ROOMS[rid]=Room(rid)
    r=ROOMS[rid];r.cleanup();pid=incoming if incoming in r.players else os.urandom(8).hex()
    if pid not in r.players:
        is_host=not r.players
        r.players[pid]={"name":str(d.get("name") or "User").strip()[:15] or "User","score":0,"words":[],"ready":False,"is_host":is_host,"last_seen":time.time(),"last_breakdown":None,"breakdown_round":-1,"chips":1000}
    else:
        r.players[pid]["name"]=str(d.get("name") or r.players[pid]["name"]).strip()[:15] or r.players[pid]["name"];r.players[pid]["last_seen"]=time.time()
    return jsonify(pid=pid,is_host=r.players[pid]["is_host"],state=r.state(pid))

@app.post("/api/sync")
def sync():
    d=request.json or {};r,pid=get_room(d)
    if not r or pid not in r.players:return jsonify(error="Expired"),404
    r.players[pid]["last_seen"]=time.time();r.timer_check()
    if r.game=="anagram" and r.timer and int(d.get("anagram_round",r.round))==r.round:
        r.players[pid]["words"]=[str(x).strip().lower() for x in d.get("buffered_words",[]) if str(x).strip()]
    r.ready();bd=None;p=r.players[pid]
    if p.get("last_breakdown") is not None:
        bd=p["last_breakdown"];p["last_breakdown"]=None
    return jsonify(state=r.state(pid,int(d.get("last_chat_id",0))),breakdown=bd,is_host=p["is_host"])

@app.post("/api/ready")
def ready():
    d=request.json or {};r,pid=get_room(d)
    if r and pid in r.players:r.players[pid]["ready"]=not r.players[pid]["ready"];r.ready()
    return response(r,pid,d) if r and pid in r.players else (jsonify(error="Expired"),404)

@app.post("/api/chat")
def chat():
    d=request.json or {};r,pid=get_room(d);m=str(d.get("msg","")).strip()
    if r and pid in r.players and m:
        r.players[pid]["last_seen"]=time.time();r.chat_id+=1;r.chat.append({"id":r.chat_id,"name":r.players[pid]["name"],"msg":mod(m[:100])});r.chat=r.chat[-200:]
        return response(r,pid,d)
    return jsonify(error="Invalid"),400

@app.post("/api/game_switch")
def switch():
    d=request.json or {};r,pid=get_room(d);g=d.get("game_type")
    if r and pid in r.players and r.players[pid]["is_host"] and not r.locked and g in ("anagram","twenty_questions","blackjack","imposter","poker"):
        r.reset_scores();r.game=g;r.locked=True
        if g=="poker":
            for p in r.players.values():p["chips"]=1000
        r.new_round()
    return response(r,pid,d) if r and pid in r.players else (jsonify(error="Denied"),403)

@app.post("/api/control")
def control():
    d=request.json or {};r,pid=get_room(d)
    if not r or pid not in r.players or not r.players[pid]["is_host"]:return jsonify(status="denied")
    a=d.get("action")
    if a=="pause" and r.game=="anagram" and r.timer:r.time_left=max(0,int(r.end-time.time()));r.timer=False
    elif a=="limit" and r.game=="anagram":r.time_limit=max(10,int(d.get("limit",60)));r.new_round()
    elif a=="skip" and r.game=="anagram":r.end_anagram(True)
    return response(r,pid,d)

@app.post("/api/tq_action")
def tq():
    d=request.json or {};r,pid=get_room(d)
    if not r or pid not in r.players or r.game!="twenty_questions":return jsonify(status="denied")
    r.tq_action(pid,d.get("action"),d);return response(r,pid,d)

@app.post("/api/blackjack_action")
def bj():
    d=request.json or {};r,pid=get_room(d)
    if not r or pid not in r.players or r.game!="blackjack":return jsonify(status="denied")
    a=d.get("action")
    if a=="new_round":
        if r.players[pid]["is_host"] and r.bj.get("status")=="finished":r.new_round()
        else:return jsonify(message="Only the host can start the next round.",state=r.state(pid,int(d.get("last_chat_id",0))))
    else:
        m=r.bj_action(pid,a)
        if m:return jsonify(message=m,state=r.state(pid,int(d.get("last_chat_id",0))))
    return response(r,pid,d)

@app.post("/api/imposter_action")
def imp():
    d=request.json or {};r,pid=get_room(d)
    if not r or pid not in r.players or r.game!="imposter":return jsonify(status="denied")
    ok,msg=r.imp_action(pid,d.get("action"),d);return jsonify(status="ok" if ok else "error",message=msg,state=r.state(pid,int(d.get("last_chat_id",0))))

@app.post("/api/poker_action")
def poker():
    d=request.json or {};r,pid=get_room(d)
    if not r or pid not in r.players or r.game!="poker":return jsonify(status="denied")
    a=d.get("action")
    if a=="new_round":
        if r.players[pid]["is_host"] and r.poker.get("phase")=="finished":r.new_round()
        else:return jsonify(message="Only the host can start the next hand.",state=r.state(pid,int(d.get("last_chat_id",0))))
    elif a=="start":
        if r.players[pid]["is_host"] and r.poker.get("phase")=="waiting":r.new_round()
    else:
        m=r.poker_action(pid,a,d.get("amount",0))
        if m:return jsonify(message=m,state=r.state(pid,int(d.get("last_chat_id",0))))
    return response(r,pid,d)

if __name__=="__main__":app.run(host="0.0.0.0",port=int(os.environ.get("PORT",5001)),debug=False)
