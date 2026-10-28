#!/usr/bin/env python3
"""
The Three Body Problem — a pretend startup run by AI agents.

Each round is one simulated week:
  CEO proposes -> board argues -> CEO answers -> board votes
  -> (if approved) engineer builds -> marketer promotes -> market reacts
  -> state updated, summary saved as memory for the next week.

Usage:
  export ANTHROPIC_API_KEY=sk-ant-...
  python3 three_body.py                     # full company, 8 weeks
  python3 three_body.py --agents core --weeks 1   # Step 3: CEO + board, one round
  python3 three_body.py --interactive       # pause each week so Luis can step in
  python3 three_body.py --mock              # no API calls, fake replies (for testing)

Stepping in without --interactive (handy on the Raspberry Pi):
  write text into inject.txt next to this script. At the start of the next week
  it is read as an event / board voice from Luis, then renamed so it fires once.
"""

import argparse
import json
import os
import random
import re
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DEFAULT_MODEL = "claude-sonnet-5-5"
MODELS = {  # per-role override; anything missing uses --model
    # "ceo": "claude-opus-5-5",
    # "market": "claude-haiku-5-5",
}
MAX_TOKENS = 700

START_CASH = 150_000       # pretend dollars (~10 weeks runway with full team)
BASE_BURN = 8_000          # weekly cost with the core team
ENGINEER_BURN = 4_000
MARKETER_BURN = 3_000
KILL_STREAK_LIMIT = 2      # two killed proposals in a row = CEO is fired

COMPANY_BRIEF = (
    "You are part of 'The Three Body Problem', a small pretend startup in a "
    "simulation. Each round is one week. Stay in character, be concrete, and "
    "keep replies under 200 words. Plain text, no markdown headers."
)

AGENTS = {
    "ceo": {
        "name": "CEO",
        "prompt": COMPANY_BRIEF + (
            " You are the CEO. You invent the product, set strategy and pitch "
            "a concrete plan to the board every week. You want the company to "
            "survive and grow, and you need the board's approval to act. "
            "When the board pushes back, defend or adapt your plan honestly."
        ),
    },
    "investor": {
        "name": "Board — Cautious Investor",
        "prompt": COMPANY_BRIEF + (
            " You are a board member: a cautious investor. You care about "
            "profit, runway and low risk. You poke holes in vague plans and ask "
            "about costs and evidence. You are not a pushover, but you approve "
            "plans that are sensible."
        ),
    },
    "visionary": {
        "name": "Board — Bold Visionary",
        "prompt": COMPANY_BRIEF + (
            " You are a board member: a bold visionary. You push for big swings "
            "and get bored by timid plans. You want the company to matter, and "
            "you'll back risky ideas if they could be huge. You often disagree "
            "with the cautious investor."
        ),
    },
    "engineer": {
        "name": "Engineer",
        "prompt": COMPANY_BRIEF + (
            " You are the engineer. Given the approved plan, describe what you "
            "actually built this week, what got cut, and any technical risk. "
            "Be realistic: one engineer, one week."
        ),
    },
    "marketer": {
        "name": "Marketer",
        "prompt": COMPANY_BRIEF + (
            " You are the marketer. Given what was built, write the positioning "
            "in one line, then the channels and the one campaign you ran this "
            "week. Small budget."
        ),
    },
    "market": {
        "name": "Market",
        "prompt": (
            "You simulate the customers of a small startup in a business "
            "simulation. Be a fair, somewhat skeptical market: most launches "
            "get little traction, good ideas grow slowly, hype without product "
            "fails. React to what the company actually built and marketed this "
            "week. Reply with ONLY a JSON object, no other text:\n"
            '{"new_users": int, "churned_users": int, "revenue": int, '
            '"sentiment": "one short sentence", "quote": "one customer quote"}'
        ),
    },
}

CORE = ["ceo", "investor", "visionary"]
FULL = CORE + ["engineer", "marketer", "market"]

# ---------------------------------------------------------------------------
# Model calls
# ---------------------------------------------------------------------------


class Brain:
    def __init__(self, model: str, mock: bool):
        self.model = model
        self.mock = mock
        self.client = None
        if not mock:
            if not os.environ.get("ANTHROPIC_API_KEY"):
                sys.exit("ANTHROPIC_API_KEY is not set. Export it, or run with --mock.")
            import anthropic
            self.client = anthropic.Anthropic()

    def ask(self, role: str, context: str) -> str:
        if self.mock:
            return mock_reply(role, context)
        msg = self.client.messages.create(
            model=MODELS.get(role, self.model),
            max_tokens=MAX_TOKENS,
            system=AGENTS[role]["prompt"],
            messages=[{"role": "user", "content": context}],
        )
        return "".join(b.text for b in msg.content if b.type == "text").strip()


def mock_reply(role: str, context: str) -> str:
    """Fake replies so the plumbing can be tested without an API key."""
    if role == "market":
        return json.dumps({
            "new_users": random.randint(0, 120),
            "churned_users": random.randint(0, 15),
            "revenue": random.randint(0, 900),
            "sentiment": "Mildly curious, waiting to see more.",
            "quote": "Neat idea, but what does it do for me?",
        })
    if context.rstrip().endswith("VOTE: CHANGES"):
        vote = random.choice(["APPROVE", "APPROVE", "CHANGES", "KILL"])
        return f"(mock {role}) My reasoning in one line.\nVOTE: {vote}"
    if "summary" in context.lower() and role == "ceo":
        return "(mock) Week summary: pitched a plan, board debated, numbers moved a little."
    return f"(mock {role}) This is a placeholder reply for testing."


# ---------------------------------------------------------------------------
# Simulation
# ---------------------------------------------------------------------------


class Company:
    def __init__(self, roles, brain, log_dir, interactive):
        self.roles = roles
        self.brain = brain
        self.log_dir = log_dir
        self.interactive = interactive
        self.week = 0
        self.cash = START_CASH
        self.users = 0
        self.total_revenue = 0
        self.kill_streak = 0
        self.memory = []          # one summary per past week
        self.history = []         # numbers per week, for state.json
        self.status = "running"

    # -- helpers ----------------------------------------------------------
    def burn(self):
        b = BASE_BURN
        if "engineer" in self.roles:
            b += ENGINEER_BURN
        if "marketer" in self.roles:
            b += MARKETER_BURN
        return b

    def scoreboard(self):
        return (f"Week {self.week} | cash ${self.cash:,} | users {self.users} | "
                f"total revenue ${self.total_revenue:,} | weekly burn ${self.burn():,}")

    def background(self):
        past = "\n".join(f"- Week {i+1}: {m}" for i, m in enumerate(self.memory)) or "- (first week, nothing yet)"
        return f"Company scoreboard: {self.scoreboard()}\n\nWhat happened so far:\n{past}"

    # -- one week ---------------------------------------------------------
    def run_week(self):
        self.week += 1
        log = [f"# The Three Body Problem — Week {self.week}\n", f"_{self.scoreboard()}_\n"]
        transcript = []

        def say(role, text):
            name = AGENTS[role]["name"] if role in AGENTS else role
            transcript.append(f"{name}: {text}")
            log.append(f"## {name}\n\n{text}\n")
            print(f"\n[{name}]\n{text}")

        def room():
            return "\n\n".join(transcript)

        # Luis steps in
        event = self.luis_input()
        if event:
            say("Luis (owner)", event)

        # 1. CEO proposal
        ask = ("Pitch the product idea and your plan for week 1." if self.week == 1
               else "Pitch your plan for this week.")
        say("ceo", self.brain.ask("ceo", f"{self.background()}\n\nMeeting so far:\n{room() or '(empty)'}\n\n{ask}"))

        # 2. Board responds
        for member in ("investor", "visionary"):
            say(member, self.brain.ask(member, f"{self.background()}\n\nMeeting so far:\n{room()}\n\nRespond to the CEO's pitch."))

        # 3. CEO answers
        say("ceo", self.brain.ask("ceo", f"{self.background()}\n\nMeeting so far:\n{room()}\n\nAnswer the board. You may adjust the plan."))

        # 4. Vote
        votes = {}
        for member in ("investor", "visionary"):
            reply = self.brain.ask(member, (
                f"{self.background()}\n\nMeeting so far:\n{room()}\n\n"
                "Cast your vote on the CEO's final plan. One or two sentences of "
                "reasoning, then a last line exactly like: VOTE: APPROVE or "
                "VOTE: KILL or VOTE: CHANGES"))
            m = re.search(r"VOTE:\s*(APPROVE|KILL|CHANGES)", reply, re.I)
            votes[member] = m.group(1).upper() if m else "CHANGES"
            say(member, reply)
        decision = decide(votes)
        log.append(f"## Board decision: **{decision}**  ({votes['investor']} / {votes['visionary']})\n")
        print(f"\n>>> Board decision: {decision} {votes}")

        # 5-7. Build, market, market reaction (only if approved)
        market = {"new_users": 0, "churned_users": 0, "revenue": 0,
                  "sentiment": "No launch this week.", "quote": ""}
        if decision == "APPROVED":
            self.kill_streak = 0
            if "engineer" in self.roles:
                say("engineer", self.brain.ask("engineer", f"{self.background()}\n\nBoard meeting:\n{room()}\n\nThe plan was approved. What did you build this week?"))
            if "marketer" in self.roles:
                say("marketer", self.brain.ask("marketer", f"{self.background()}\n\nThis week:\n{room()}\n\nHow did you position and promote it this week?"))
            if "market" in self.roles:
                raw = self.brain.ask("market", f"Company status: {self.scoreboard()}\n\nWhat the company did this week:\n{room()}\n\nHow do customers react?")
                market = parse_market(raw)
                log.append("## Market reaction\n\n"
                           f"- New users: {market['new_users']}\n- Churned: {market['churned_users']}\n"
                           f"- Revenue: ${market['revenue']:,}\n- Sentiment: {market['sentiment']}\n"
                           f"- Customer: \"{market['quote']}\"\n")
                print(f"\n[Market] {market}")
        elif decision == "KILLED":
            self.kill_streak += 1
        else:
            self.kill_streak = 0  # changes requested is not a kill

        # 8. Update numbers
        self.users = max(0, self.users + market["new_users"] - market["churned_users"])
        self.cash += market["revenue"] - self.burn()
        self.total_revenue += market["revenue"]
        self.history.append({"week": self.week, "decision": decision, "votes": votes,
                             "cash": self.cash, "users": self.users,
                             "revenue": market["revenue"]})

        if self.cash <= 0:
            self.status = "bankrupt"
        elif self.kill_streak >= KILL_STREAK_LIMIT:
            self.status = "ceo_fired"

        # 9. Memory for next week
        summary = self.brain.ask("ceo", (
            f"Meeting transcript:\n{room()}\n\nBoard decision: {decision}. "
            f"Market: {market['sentiment']}\n\nWrite a 2-3 sentence factual summary "
            "of this week for the company record."))
        self.memory.append(summary)

        log.append(f"## End of week\n\n_{self.scoreboard()}_\n\n**Summary:** {summary}\n")
        if self.status != "running":
            log.append(f"\n**GAME OVER: {self.status}**\n")
        (self.log_dir / f"week_{self.week:02d}.md").write_text("\n".join(log))
        self.save_state()

    def luis_input(self):
        inject = HERE / "inject.txt"
        if inject.exists():
            text = inject.read_text().strip()
            inject.rename(HERE / f"inject_used_week{self.week:02d}.txt")
            if text:
                return text
        if self.interactive:
            try:
                text = input(f"\n--- Week {self.week}: type an event or board comment "
                             "(Enter to just watch): ").strip()
            except EOFError:
                text = ""
            return text or None
        return None

    def save_state(self):
        (self.log_dir / "state.json").write_text(json.dumps({
            "status": self.status, "week": self.week, "cash": self.cash,
            "users": self.users, "total_revenue": self.total_revenue,
            "roles": self.roles, "memory": self.memory, "history": self.history,
        }, indent=2))


def decide(votes):
    v = list(votes.values())
    if v.count("APPROVE") == 2:
        return "APPROVED"
    if v.count("KILL") == 2:
        return "KILLED"
    if "KILL" in v and "APPROVE" not in v:
        return "KILLED"
    if "APPROVE" in v and "KILL" in v:
        return "SPLIT — CHANGES REQUESTED"
    return "CHANGES REQUESTED"


def parse_market(raw):
    default = {"new_users": 0, "churned_users": 0, "revenue": 0,
               "sentiment": "Market reaction unreadable.", "quote": ""}
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        return default
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return default
    out = dict(default)
    for k in ("new_users", "churned_users", "revenue"):
        try:
            out[k] = max(0, int(data.get(k, 0)))
        except (TypeError, ValueError):
            pass
    for k in ("sentiment", "quote"):
        if isinstance(data.get(k), str):
            out[k] = data[k]
    return out


# ---------------------------------------------------------------------------


def main():
    p = argparse.ArgumentParser(description="The Three Body Problem simulation")
    p.add_argument("--weeks", type=int, default=8)
    p.add_argument("--agents", choices=["core", "full"], default="full",
                   help="core = CEO + board only; full = whole company")
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--interactive", action="store_true", help="pause each week for Luis")
    p.add_argument("--mock", action="store_true", help="no API calls, fake replies")
    p.add_argument("--seed", type=int, default=None)
    args = p.parse_args()

    if args.seed is not None:
        random.seed(args.seed)

    roles = CORE if args.agents == "core" else FULL
    log_dir = HERE / "logs" / datetime.now().strftime("run_%Y%m%d_%H%M%S")
    log_dir.mkdir(parents=True, exist_ok=True)

    company = Company(roles, Brain(args.model, args.mock), log_dir, args.interactive)
    print(f"Starting run in {log_dir} with agents: {', '.join(roles)}")
    for _ in range(args.weeks):
        company.run_week()
        if company.status != "running":
            break
    if company.status == "running":
        company.status = "survived"
        company.save_state()
    print(f"\nRun finished: {company.status}. {company.scoreboard()}\nLogs: {log_dir}")


if __name__ == "__main__":
    main()
