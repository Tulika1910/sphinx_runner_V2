"""
Pure game logic for the T-Rex runner (no pygame, no camera, no drawing).

One call per frame drives everything, so any input source (keyboard, camera, a test
script) can play the game:

    events = game.step(jump=True/False, restart=True/False)

All the difficulty knobs are the constants just below - tweak them there.
"""
import random
from dataclasses import dataclass

PLAY, END = 1, 0

# ---- world -----------------------------------------------------------------
WIDTH, HEIGHT = 600, 200      # logical game size
GROUND_TOP = 185              # top of the invisible ground (y=190, height 10)
GROUND_Y = 180                # y of the scrolling ground picture
OBSTACLE_Y = 165              # centre y of cacti
TREX_X = 50
GRAVITY = 0.8
JUMP_VELOCITY = -12.0
HITBOX_INSET = 3              # shrink hit boxes so transparent corners don't kill you

# ---- difficulty (speeds are pixels per frame at 60 fps) ----------------------
START_SPEED = 4.0             # was 6 and rose 15x faster
MAX_SPEED = 10.0
ACCEL = 0.0022                # speed gained per score point (max speed at about score 2700)
SCORE_RATE = 0.025            # score gained per pixel travelled
FIRST_OBSTACLE_FRAME = 90     # breathing room at the start of each run

# ---- obstacle patterns -------------------------------------------------------
GROUP_WEIGHTS = {1: 88, 2: 12}          # chance of a single / double cluster (no triples)
SPAWN_MARGIN = 20             # obstacles appear this far off-screen to the right
AIR_FRAMES_OVER_CACTUS = 20   # frames the trex stays above cactus height in a jump
GAP_SECONDS_MIN = 1.25        # least time between one pattern passing and the next arriving
GAP_SPREAD = 2.2              # most gap = least gap * this + 60 px (random in between)

# ---- coins -------------------------------------------------------------------
COIN_PATTERNS = {"arc": 50, "trail": 30, "none": 20}   # chance of a coin arc over the cacti,
                                                       # a trail on the ground between them, or nothing
COIN_ARC_HEIGHT = 62          # how high the middle of an arc floats above the running height
COIN_SPACING = 28

# ---- clouds ------------------------------------------------------------------
CLOUD_SPEED_FACTOR = 0.3      # clouds drift slower than the ground
CLOUD_EVERY = (70, 160)       # frames between clouds (random in this range)
CLOUD_Y = (40, 110)


@dataclass
class Entity:
    x: float                  # centre x
    y: float                  # centre y
    w: float
    h: float
    vy: float = 0.0
    image: int = 0            # which obstacle picture
    hit_w: float = None       # collision box, if smaller than the picture (it sits on the feet)
    hit_h: float = None

    def hitbox(self):
        hw, hh = self.hit_w or self.w, self.hit_h or self.h
        w = max(1.0, hw - 2 * HITBOX_INSET)
        h = max(1.0, hh - 2 * HITBOX_INSET)
        cy = self.y + (self.h - hh) / 2
        return (self.x - w / 2, cy - h / 2, w, h)

    @property
    def right(self) -> float:
        return self.x + self.w / 2


def _overlap(a: Entity, b: Entity) -> bool:
    ax, ay, aw, ah = a.hitbox()
    bx, by, bw, bh = b.hitbox()
    return ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah


class Game:
    """
    sizes = {
        "trex": (w, h),               # nominal size of the character (its feet rest on the ground)
        "trex_hit": (w, h),           # optional: smaller collision box
        "cloud": (w, h),
        "obstacles": [(w, h), ...],   # any number of pictures
        "coin": (w, h),
        "ground_w": width of the ground picture,
    }
    """

    def __init__(self, sizes, high_score=0, seed=None):
        self.sizes = sizes
        self.rng = random.Random(seed)
        self.high_score = high_score
        self.frame = 0                       # frames since the program started
        self.ground_x = sizes["ground_w"] / 2
        tw, th = sizes["trex"]
        hit = sizes.get("trex_hit") or (None, None)
        self.trex = Entity(TREX_X, GROUND_Y, tw, th, hit_w=hit[0], hit_h=hit[1])
        self.reset()

    # ----------------------------------------------------------------
    def reset(self):
        self.state = PLAY
        self.score_f = 0.0
        self.run_frames = 0                  # frames since this run started
        self.obstacles = []                  # ordered left -> right
        self.coins = []
        self.picked = []
        self.coins_collected = 0
        self.clouds = []
        self.next_gap = 0.0
        self.next_cloud = 20
        self.trex.vy = 0.0

    @property
    def score(self) -> int:
        return int(self.score_f)

    def speed(self) -> float:
        return min(MAX_SPEED, START_SPEED + ACCEL * self.score_f)

    @property
    def floor(self) -> float:
        return GROUND_TOP - self.trex.h / 2

    @property
    def on_ground(self) -> bool:
        return self.trex.y >= self.floor - 0.01

    # ----------------------------------------------------------------
    def step(self, jump=False, restart=False):
        """Advance one frame. Returns a list of events: 'jump', 'coin', 'died', 'high_score', 'restart'."""
        events = []
        self.picked = []                                 # (x, y) of coins collected this frame
        self.frame += 1

        if self.state == PLAY:
            self.run_frames += 1
            sp = self.speed()
            self.score_f += sp * SCORE_RATE

            # world scrolls
            self.ground_x -= sp
            if self.ground_x < 0:
                self.ground_x = self.sizes["ground_w"] / 2
            for o in self.obstacles:
                o.x -= sp
            for c in self.coins:
                c.x -= sp
            for c in self.clouds:
                c.x -= sp * CLOUD_SPEED_FACTOR
            self.obstacles = [o for o in self.obstacles if o.right > -50]
            self.clouds = [c for c in self.clouds if c.right > -50]
            self.coins = [c for c in self.coins if c.right > -50]

            # trex
            t = self.trex
            if jump and self.on_ground:
                t.vy = JUMP_VELOCITY
                events.append("jump")
            t.vy += GRAVITY
            t.y += t.vy
            if t.y >= self.floor:
                t.y = self.floor
                t.vy = 0.0

            self._maybe_spawn_obstacles(sp)
            self._maybe_spawn_cloud()

            hx, hy, hw, hh = t.hitbox()
            for c in list(self.coins):                      # pick up coins (a little generous)
                if abs(c.x - (hx + hw / 2)) < (hw + c.w) / 2 + 6 and abs(c.y - (hy + hh / 2)) < (hh + c.h) / 2 + 6:
                    self.coins.remove(c)
                    self.picked.append((c.x, c.y))
                    self.coins_collected += 1
                    events.append("coin")

            if any(_overlap(t, o) for o in self.obstacles):
                self.state = END
                t.vy = 0.0
                events.append("died")
                if self.score > self.high_score:
                    self.high_score = self.score
                    events.append("high_score")

        elif restart:
            self.reset()
            events.append("restart")

        return events

    # ----------------------------------------------------------------
    def _maybe_spawn_obstacles(self, sp):
        x_left = WIDTH + SPAWN_MARGIN
        prev_right = None
        if self.obstacles:
            last = self.obstacles[-1]
            prev_right = last.right
            if last.right > x_left:
                return                                   # the previous pattern hasn't come into view yet
            # keep the full gap even when it is wider than the screen (matters at high speed)
            x_left = max(x_left, last.right + self.next_gap)
        elif self.run_frames < FIRST_OBSTACLE_FRAME:
            return
        self._spawn_group(sp, x_left, prev_right)

    def _pick_group_size(self):
        sizes, weights = zip(*GROUP_WEIGHTS.items())
        return self.rng.choices(sizes, weights)[0]

    def _spawn_group(self, sp, x_left=WIDTH + SPAWN_MARGIN, prev_right=None):
        """Spawn 1-3 cacti side by side.  A cluster is only as wide as the trex can still jump
        over at the current speed, so bigger clusters naturally appear as the game speeds up."""
        trex_hit_w = (self.trex.hit_w or self.trex.w) - 2 * HITBOX_INSET
        budget = 0.65 * AIR_FRAMES_OVER_CACTUS * sp - trex_hit_w   # max hit-box width of a cluster
        count = self._pick_group_size()

        # pictures too wide to jump over at this speed are left out (wide ones appear once it is faster)
        pics = self.sizes["obstacles"]
        fits = [i for i, (pw, ph) in enumerate(pics)
                if (pw - 2 * HITBOX_INSET) + trex_hit_w <= 0.9 * AIR_FRAMES_OVER_CACTUS * sp]
        allowed = fits or [min(range(len(pics)), key=lambda i: pics[i][0])]

        first = len(self.obstacles)
        group_left = x_left
        span = 0.0
        for n in range(count):
            idx = self.rng.choice(allowed)
            w, h = self.sizes["obstacles"][idx]
            gap = 0.0 if n == 0 else self.rng.uniform(4, 14)
            add = (w - 2 * HITBOX_INSET) + gap
            if n > 0 and span + add > budget:
                break                                   # would be unjumpable at this speed
            x_left += gap
            self.obstacles.append(Entity(x_left + w / 2, OBSTACLE_Y, w, h, image=idx))
            x_left += w
            span += add

        lo = sp * 60 * GAP_SECONDS_MIN + 20
        self.next_gap = self.rng.uniform(lo, lo * GAP_SPREAD + 60)
        self._spawn_coins(self.obstacles[first:], group_left, prev_right, sp)

    def _spawn_coins(self, group, group_left, prev_right, sp):
        """Coins float in an arc over a cactus group (jump to get them) or in a trail on the ground
        in the gap before it (just run through)."""
        if not self.sizes.get("coin"):
            return
        cw, ch = self.sizes["coin"]
        kinds, weights = zip(*COIN_PATTERNS.items())
        kind = self.rng.choices(kinds, weights)[0]
        occupied = max((c.x for c in self.coins), default=-1e9)       # keep clear of earlier coins
        run_y = self.floor
        group_right = group[-1].right

        if kind == "arc":
            span = group_right - group_left
            arc_w = max(span + 60, min(300.0, 22 * sp))
            cx = (group_left + group_right) / 2
            if cx - arc_w / 2 < occupied + 40:
                return
            top = min(o.y - o.h / 2 for o in group)                   # top of the tallest cactus
            n = 5
            for i in range(n):
                u = i / (n - 1)
                x = cx - arc_w / 2 + u * arc_w
                y = run_y - COIN_ARC_HEIGHT * 4 * u * (1 - u)
                if group_left - 10 <= x <= group_right + 10:
                    y = min(y, top - ch / 2 - 8)                      # float above the cactus, not inside it
                self.coins.append(Entity(x, y, cw, ch))
        elif kind == "trail" and prev_right is not None:
            n = 4
            width = (n - 1) * COIN_SPACING
            start = (prev_right + group_left) / 2 - width / 2
            if start < occupied + 40 or start < prev_right + 60 or start + width > group_left - 60:
                return
            for i in range(n):
                self.coins.append(Entity(start + i * COIN_SPACING, run_y, cw, ch))

    def _maybe_spawn_cloud(self):
        self.next_cloud -= 1
        if self.next_cloud <= 0:
            w, h = self.sizes["cloud"]
            self.clouds.append(Entity(WIDTH + w, round(self.rng.uniform(*CLOUD_Y)), w, h))
            self.next_cloud = self.rng.randint(*CLOUD_EVERY)