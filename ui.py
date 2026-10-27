"""
Menus: who is playing, create a player, choose a character (a swipeable carousel), choose how to control the game.
Glass cards over the rainy city, GSAP-style entrances and hover pops, Lenis-style inertial scrolling, cartoon sounds.
"""
import math

import pygame

import avatars
from avatars import AVATARS
from glass import text, pill, disc, ring, fit_text
from motion import Tween, SmoothScroll, ease, clamp
from storage import valid_email

MODES = [
    ("keyboard", "Keyboard", "Space or the Up arrow makes your character jump."),
    ("body", "Body jump", "Jump in front of your webcam and your character jumps with you."),
    ("hand", "Hand gestures", "Make a fist, then open your hand to jump. Needs a webcam."),
]
CAR_W, CAR_H = 330, 430              # the focused carousel card
SPACING = 290                        # distance between the focused card and its neighbours
BAR_H = 64


def wrap(font, s, max_w):
    lines, cur = [], ""
    for word in s.split():
        trial = (cur + " " + word).strip()
        if font.size(trial)[0] <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


class MenuScene:
    def __init__(self, app, page=None, player_id=None, avatar_id=None, mode="keyboard", error=""):
        self.app = app
        self.store = app.store
        self.player_id = player_id
        self.avatar_id = avatar_id or AVATARS[0]["id"]
        self.mode = mode
        self.error = error
        self.name, self.email, self.consent, self.focus = "", "", True, "name"
        self.hits = []
        self.badges = {}
        self.frames = {}
        self.result = None
        self.hover = {}
        self.block = None
        self.bar_keys = {"Back", "Continue"}
        self.hover_key = None
        self.last_hover = None
        self.ripples = []
        self.car = SmoothScroll(lerp=0.12, wheel_px=1.0)     # carousel position, in card units
        self.last_input = -9.0
        self.last_focus = None
        self.press = None
        self.dragging = False
        self.drag_origin = 0.0
        self.rain_t = 0.0
        self.time = 0.0
        self.page = None
        self.goto(page or ("profile" if self.store.players() else "new"), quiet=True)

    # ---- helpers ---------------------------------------------------------
    @property
    def pal(self):
        return avatars.palette(self.avatar_id, self.app.dark)

    @property
    def dt(self):
        return self.app.dt

    def close(self):
        pass

    def hit(self, rect, fn):
        self.hits.append((pygame.Rect(rect), fn))

    def hv(self, key, rect):
        """0..1 hover amount for `key`, eased (and remembers which thing the mouse is over)."""
        mouse = pygame.mouse.get_pos()
        over = pygame.Rect(rect).collidepoint(mouse) and not self.dragging
        if over and self.block is not None and self.block.collidepoint(mouse) and key != "blocker":
            over = key in self.bar_keys
        tw = self.hover.get(key)
        if tw is None:
            tw = self.hover[key] = Tween(0.0, 0.0, 0.18, "power2.out")
        tw.to(1.0 if over else 0.0)
        tw.update(self.dt)
        if over:
            self.hover_key = key
        return tw.value

    def ent(self, i=0, delay=0.08, span=0.6):
        """GSAP-style staggered entrance 0 -> 1 (with a little overshoot) for the i-th element."""
        return ease("back.out", (self.page_time - delay - 0.05 * i) / span)

    def goto(self, page, quiet=False):
        self.page = page
        self.page_time = 0.0
        self.hits = []
        self.block = None
        if page == "avatar":
            self.car.set_limit(len(AVATARS) - 1)
            idx = [a["id"] for a in AVATARS].index(self.avatar_id)
            self.car.jump(idx)
            self.last_focus = idx
        if page == "new":
            pygame.key.start_text_input()
        else:
            pygame.key.stop_text_input()
        if not quiet:
            self.app.sounds.play("whoosh")

    def title(self, screen, s, y, size=36):
        """Page title whose letters rise in one after the other."""
        pal, fonts = self.pal, self.app.fonts
        font = fonts.get(size, True)
        total = font.size(s)[0]
        x0 = (screen.get_width() - total) // 2
        for i, ch in enumerate(s):
            t = clamp((self.page_time - 0.03 * i - 0.05) / 0.5)
            if t <= 0 or ch == " ":
                continue
            off = (1 - ease("power3.out", t)) * 28
            text(screen, fonts, ch, size, pal.ink, (x0 + font.size(s[:i])[0], y + off), "topleft", bold=True, alpha=255 * t)

    def badge(self, screen, aid, center, r):
        dark = self.app.dark
        disc(screen, avatars.palette(aid, dark).accent, center, r, 60)
        key = (aid, dark, r)
        if key not in self.badges:
            self.badges[key] = avatars.fit_surface(avatars.preview(aid, self.app.base, dark), r * 2.1, r * 1.5)
        img = self.badges[key]
        screen.blit(img, img.get_rect(center=center))

    def button(self, screen, rect, label, fn, primary=False, selected=False, size=16, key=None):
        h = self.hv(key or label, rect)
        pill(screen, self.app.fonts, self.pal, rect, label, primary=primary, hover=h, selected=selected, size=size)
        self.hit(rect, fn)

    def top_pills(self, screen, sw):
        a = self.app
        x = sw - 24
        for label, fn in (("Dark" if not a.dark else "Light", lambda: setattr(a, "dark", not a.dark)),
                          ("Windowed" if a.fullscreen else "Full screen", a.toggle_fullscreen),
                          ("Sound off" if a.sounds.muted else "Sound on", a.sounds.toggle)):
            w = 112 if label != "Full screen" and label != "Windowed" else 124
            x -= w
            self.button(screen, (x, 22, w, 36), label, fn, size=14, key="top-" + label.split()[0])
            x -= 10

    # ---- actions ---------------------------------------------------------
    def pick_player(self, pid):
        p = self.store.get(pid)
        self.player_id, self.avatar_id, self.mode = pid, p["avatar"], p.get("control", "keyboard")
        self.error = ""
        self.app.sounds.play("select")
        self.goto("control")

    def go_new(self):
        self.name, self.email, self.focus, self.error = "", "", "name", ""
        self.goto("new")

    def submit_new(self):
        name, email = self.name.strip(), self.email.strip()
        if not name:
            self.error = "Please enter a name."
        elif not valid_email(email):
            self.error = "Please enter a valid email address."
        else:
            p = self.store.add_player(name, email, self.consent, self.avatar_id)
            self.player_id, self.error = p["id"], ""
            self.app.sounds.play("restart")
            self.goto("avatar")

    def car_goto(self, i):
        self.car.drag_to(clamp(i, 0, len(AVATARS) - 1))
        self.last_input = self.time

    def car_step(self, d):
        self.car_goto(round(self.car.target) + d)

    def focus_id(self):
        return AVATARS[int(clamp(round(self.car.target), 0, len(AVATARS) - 1))]["id"]

    def confirm_avatar(self):
        self.avatar_id = self.focus_id()
        self.store.update(self.player_id, avatar=self.avatar_id)
        self.app.sounds.play("pop")
        self.goto("control")

    def start(self):
        self.store.update(self.player_id, control=self.mode, avatar=self.avatar_id)
        self.app.sounds.play("restart")
        self.result = ("play", {"player_id": self.player_id, "avatar_id": self.avatar_id, "mode": self.mode})

    def back(self):
        if self.page in ("new", "avatar", "control"):
            self.goto("profile" if self.store.players() else "new")
        self.error = ""

    def primary(self):
        {"new": self.submit_new, "avatar": self.confirm_avatar, "control": self.start}.get(self.page, lambda: None)()

    # ---- frame -------------------------------------------------------------
    def step(self, events):
        screen = pygame.display.get_surface()
        sw, sh = screen.get_size()
        self.page_time += self.dt
        self.time += self.dt
        self.car.update(self.dt)
        self.rain_t += self.dt
        if self.page == "avatar":
            if not self.dragging and self.time - self.last_input > 0.14:          # settle on the nearest card
                self.car.drag_to(round(self.car.target))
            if abs(self.car.current - self.car.target) < 0.004 and abs(self.car.target - round(self.car.target)) < 1e-3:
                fid = self.focus_id()
                if fid != self.avatar_id:                                        # the whole theme follows the card
                    self.avatar_id = fid
                    self.app.sounds.play("select")
        self.draw(screen)

        for e in events:
            if e.type == pygame.MOUSEWHEEL and self.page == "avatar":
                delta = -float(getattr(e, "precise_y", e.y)) + float(getattr(e, "precise_x", getattr(e, "x", 0)))
                self.car.wheel(clamp(delta * 0.8, -1.5, 1.5))
                self.last_input = self.time
            elif e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
                self.press, self.dragging, self.drag_origin = e.pos, False, self.car.target
            elif e.type == pygame.MOUSEMOTION and self.press is not None and self.page == "avatar":
                dx = e.pos[0] - self.press[0]
                if abs(dx) > 8:
                    self.dragging = True
                if self.dragging:
                    self.car.drag_to(self.drag_origin - dx / SPACING)
                    self.last_input = self.time
            elif e.type == pygame.MOUSEBUTTONUP and e.button == 1:
                if self.dragging:
                    self.car.drag_to(round(self.car.target))
                    self.last_input = self.time
                if self.press is not None and not self.dragging:
                    self.ripples.append([e.pos, 0.0])
                    fired = False
                    for rect, fn in reversed(self.hits):
                        if rect.collidepoint(e.pos):
                            fn()
                            fired = True
                            break
                    if not fired:
                        self.app.sounds.play("tick")
                self.press, self.dragging = None, False
            elif e.type == pygame.TEXTINPUT and self.page == "new":
                field = "name" if self.focus == "name" else "email"
                if len(getattr(self, field)) < (24 if field == "name" else 80):
                    setattr(self, field, getattr(self, field) + e.text)
                    self.app.sounds.play("tick")
            elif e.type == pygame.KEYDOWN:
                if e.key == pygame.K_ESCAPE:
                    self.back()
                elif e.key == pygame.K_RETURN:
                    if self.page == "new" and self.focus == "name":
                        self.focus = "email"
                    else:
                        self.primary()
                elif self.page == "new":
                    if e.key == pygame.K_BACKSPACE:
                        field = "name" if self.focus == "name" else "email"
                        setattr(self, field, getattr(self, field)[:-1])
                    elif e.key == pygame.K_TAB:
                        self.focus = "email" if self.focus == "name" else "name"
                elif e.key == pygame.K_d:
                    self.app.dark = not self.app.dark
                elif e.key == pygame.K_m:
                    self.app.sounds.toggle()
                elif self.page == "avatar":
                    if e.key in (pygame.K_RIGHT, pygame.K_DOWN):
                        self.car_step(1)
                    elif e.key in (pygame.K_LEFT, pygame.K_UP):
                        self.car_step(-1)
                    elif e.key == pygame.K_HOME:
                        self.car_goto(0)
                    elif e.key == pygame.K_END:
                        self.car_goto(len(AVATARS) - 1)
        result, self.result = self.result, None
        return result

    def draw(self, screen):
        app, pal, fonts = self.app, self.pal, self.app.fonts
        sw, sh = screen.get_size()
        self.hits = []
        self.hover_key = None
        app.glass.paint_background(screen, pal, t=self.rain_t)

        subs = {"profile": "Pick a player, or create a new one", "new": "Your best scores are saved to your profile",
                "avatar": "Swipe, scroll or use the arrow keys - every character has its own light and dark theme", "control": "You can change this any time"}
        titles = {"profile": "Who's playing?", "new": "Create your player", "avatar": "Choose your character",
                  "control": "How do you want to play?"}
        self.title(screen, titles[self.page], 62)
        text(screen, fonts, subs[self.page], 16, pal.ink_soft, (sw // 2, 112), "center",
             alpha=255 * clamp((self.page_time - 0.3) / 0.4))

        getattr(self, "draw_" + self.page)(screen, sw, sh)
        self.top_pills(screen, sw)
        text(screen, fonts, self.store.status(), 12, pal.ink_soft, (sw // 2, sh - 14), "center")

        # click ripples
        for r in self.ripples:
            r[1] += self.dt
        self.ripples = [r for r in self.ripples if r[1] < 0.6]
        for pos, t in self.ripples:
            k = t / 0.6
            ring(screen, pal.accent, pos, 8 + 70 * ease("power3.out", k), 2, 200 * (1 - k))

        # hover tick sound when the mouse moves onto something new
        if self.hover_key != self.last_hover:
            if self.hover_key is not None:
                app.sounds.play("tick")
            self.last_hover = self.hover_key

    # ---- pages -------------------------------------------------------------
    def draw_profile(self, screen, sw, sh):
        app, pal, fonts = self.app, self.pal, self.app.fonts
        cw, ch, gap = 230, 104, 18
        players = self.store.players()[:5]
        show_lb = sw >= 1100
        grid_w = 3 * cw + 2 * gap
        total = grid_w + (24 + 300 if show_lb else 0)
        x0, y0 = (sw - total) // 2, 150
        items = [("player", p) for p in players] + [("new", None)]
        for i, (kind, p) in enumerate(items):
            base = pygame.Rect(x0 + (i % 3) * (cw + gap), y0 + (i // 3) * (ch + gap), cw, ch)
            e = self.ent(i)
            if e <= 0.01:
                continue
            h = self.hv(("prof", i), base)
            r = base.inflate(round(h * 10), round(h * 8)).move(0, round((1 - e) * 60 - h * 4))
            app.glass.card(screen, pal, r, 20)
            if h > 0.02:
                pygame.draw.rect(screen, pal.accent, r, width=2, border_radius=20)
            if kind == "player":
                self.badge(screen, p["avatar"], (r.x + 44, r.centery), 26)
                text(screen, fonts, fit_text(fonts, p["name"], 18, cw - 100, True), 18, pal.ink,
                     (r.x + 84, r.y + 30), bold=True)
                text(screen, fonts, f"Best {p['best_score']}  ·  {p['coins_total']} coins", 13, pal.ink_soft,
                     (r.x + 84, r.y + 58))
                self.hit(r, lambda pid=p["id"]: self.pick_player(pid))
            else:
                text(screen, fonts, "+", 40 + round(h * 6), pal.accent, (r.centerx, r.y + 38), "center")
                text(screen, fonts, "New player", 16, pal.ink, (r.centerx, r.y + 74), "center", bold=True)
                self.hit(r, self.go_new)
        if show_lb:
            e = self.ent(6)
            r = pygame.Rect(x0 + grid_w + 24, y0 + round((1 - e) * 60), 300, 2 * ch + gap)
            app.glass.card(screen, pal, r, 20)
            entries, source = self.store.leaderboard(5)
            text(screen, fonts, "Top scores", 18, pal.ink, (r.x + 22, r.y + 18), bold=True)
            text(screen, fonts, source, 12, pal.ink_soft, (r.right - 22, r.y + 24), "topright")
            if not entries:
                text(screen, fonts, "No scores yet - be the first!", 14, pal.ink_soft, (r.x + 22, r.y + 64))
            for i, en in enumerate(entries):
                y = r.y + 58 + i * 32
                text(screen, fonts, str(i + 1), 14, pal.ink_soft, (r.x + 22, y))
                disc(screen, avatars.palette(en["avatar"], app.dark).accent, (r.x + 58, y + 9), 7)
                text(screen, fonts, fit_text(fonts, en["name"], 15, 130), 15, pal.ink, (r.x + 74, y))
                text(screen, fonts, str(en["score"]), 15, pal.ink, (r.right - 22, y), "topright", bold=True)

    def draw_new(self, screen, sw, sh):
        app, pal, fonts = self.app, self.pal, self.app.fonts
        w, h = min(560, sw - 80), 456
        e = self.ent(0)
        r = pygame.Rect((sw - w) // 2, max(130, (sh - h) // 2 + 30) + round((1 - e) * 70), w, h)
        app.glass.card(screen, pal, r, 26)
        x, iw = r.x + 40, r.width - 80
        blink = (pygame.time.get_ticks() // 500) % 2 == 0

        for label, field, y in (("Name", "name", r.y + 36), ("Email", "email", r.y + 126)):
            text(screen, fonts, label, 14, pal.ink_soft, (x, y))
            box = pygame.Rect(x, y + 24, iw, 46)
            focused = self.focus == field
            s = pygame.Surface(box.size, pygame.SRCALPHA)
            pygame.draw.rect(s, (*pal.ink, 26 if focused else 14), s.get_rect(), border_radius=14)
            pygame.draw.rect(s, (*(pal.accent if focused else pal.ink), 220 if focused else 60), s.get_rect(),
                             width=2 if focused else 1, border_radius=14)
            screen.blit(s, box)
            value = getattr(self, field)
            if value:
                rr = text(screen, fonts, fit_text(fonts, value, 18, iw - 32), 18, pal.ink, (box.x + 16, box.centery), "midleft")
                cx = rr.right + 2
            else:
                text(screen, fonts, "Your name" if field == "name" else "you@gmail.com", 18, pal.ink_soft,
                     (box.x + 16, box.centery), "midleft", alpha=150)
                cx = box.x + 16
            if focused and blink:
                pygame.draw.line(screen, pal.ink, (cx, box.y + 12), (cx, box.bottom - 12), 2)
            self.hit(box, lambda f=field: setattr(self, "focus", f))

        cb = pygame.Rect(x, r.y + 232, 24, 24)
        s = pygame.Surface(cb.size, pygame.SRCALPHA)
        pygame.draw.rect(s, (*(pal.accent if self.consent else pal.ink), 255 if self.consent else 70),
                         s.get_rect(), width=0 if self.consent else 2, border_radius=7)
        screen.blit(s, cb)
        if self.consent:
            pygame.draw.lines(screen, pal.on_accent, False,
                              [(cb.x + 6, cb.centery), (cb.x + 10, cb.bottom - 8), (cb.right - 6, cb.y + 7)], 3)
        label = ("Save my name and email online, so I can appear on the leaderboard. "
                 "Untick to keep everything on this computer.")
        for i, line in enumerate(wrap(fonts.get(14), label, iw - 40)):
            text(screen, fonts, line, 14, pal.ink_soft, (x + 38, cb.y + 2 + i * 20))
        self.hit(pygame.Rect(x, cb.y - 6, iw, 70), lambda: (setattr(self, "consent", not self.consent),
                                                              self.app.sounds.play("pop")))
        if self.error:
            text(screen, fonts, self.error, 14, (214, 76, 76), (x, r.y + 330))
        by = r.bottom - 76
        self.button(screen, (x, by, 130, 46), "Back", self.back)
        self.button(screen, (r.right - 40 - 160, by, 160, 46), "Continue", self.submit_new, primary=True)

    def avatar_surface(self, aid, idx):
        key = (aid, idx, self.app.dark)
        if key not in self.frames:
            art = avatars.load_avatar_art(aid, self.app.base)
            sprite = art["run"][idx % len(art["run"])]
            self.frames[key] = sprite.surf if art["custom"] else avatars.themed(
                sprite, avatars.palette(aid, self.app.dark), "accent").surf
        return self.frames[key]

    def chevron(self, screen, center, direction, key):
        pal = self.pal
        rect = pygame.Rect(0, 0, 52, 52)
        rect.center = center
        h = self.hv(key, rect)
        disc(screen, pal.ink, center, 26 + round(h * 3), 22 + 30 * h)
        x, y, d = center[0], center[1], direction
        pygame.draw.lines(screen, pal.ink, False, [(x - 5 * d, y - 11), (x + 5 * d, y), (x - 5 * d, y + 11)], 3)
        self.hit(rect, lambda: self.car_step(direction))

    def draw_avatar(self, screen, sw, sh):
        app, pal, fonts = self.app, self.pal, self.app.fonts
        n = len(AVATARS)
        bar = pygame.Rect(40, sh - BAR_H - 26, sw - 80, BAR_H)
        self.block = bar
        top, bottom = 140, bar.y - 66
        avail = max(250, bottom - top)
        base = min(1.0, avail / CAR_H, (sw - 140) / (CAR_W + 2 * SPACING * 0.6))
        cy = top + avail / 2
        cur = self.car.current
        focus = int(clamp(round(cur), 0, n - 1))
        if focus != self.last_focus:
            self.last_focus = focus
            app.sounds.play("tick")
        s1 = SPACING * base

        for i in sorted(range(n), key=lambda k: -abs(k - cur)):          # far cards first, focused card on top
            d = i - cur
            ad = abs(d)
            if ad > 2.7:
                continue
            sign = 1 if d >= 0 else -1
            x = sw / 2 + sign * (s1 * min(ad, 1.0) + s1 * 0.6 * max(0.0, ad - 1.0))
            c = clamp(1 - ad)                                              # how "focused" this card is (0..1)
            sc = base * (1 - 0.17 * min(ad, 2.0))
            e = self.ent(abs(i - focus), delay=0.1)
            if e <= 0.01:
                continue
            w, h = int(CAR_W * sc / 4) * 4, int(CAR_H * sc / 4) * 4
            r = pygame.Rect(0, 0, w, h)
            r.center = (round(x), round(cy + (1 - e) * 80))
            hv = self.hv(("car", i), r) if ad > 0.5 else 0.0
            r = r.inflate(round(hv * 10), round(hv * 10)).move(0, round(-hv * 4))
            apal = avatars.palette(AVATARS[i]["id"], app.dark)
            app.glass.card(screen, pal, r, int(30 * sc))
            disc(screen, apal.accent, (r.centerx, r.y + int(h * 0.31)), int(h * 0.27), 22 + 42 * c)
            if c > 0.05:
                pygame.draw.rect(screen, apal.accent, r, width=3 if c > 0.7 else 2, border_radius=int(30 * sc))

            art_n = len(avatars.load_avatar_art(AVATARS[i]["id"], app.base)["run"])
            frame = self.avatar_surface(AVATARS[i]["id"], int(self.time * (5 + 3 * c)) % art_n if c > 0.5 else 0)
            k = min((w - 56 * sc) / frame.get_width(), (h * 0.40) / frame.get_height())
            img = pygame.transform.smoothscale(frame, (max(2, round(frame.get_width() * k)), max(2, round(frame.get_height() * k))))
            img.set_alpha(int(120 + 135 * c))
            bob = math.sin(self.time * 6 + i) * 4 * c
            screen.blit(img, img.get_rect(center=(r.centerx, r.y + h * 0.31 + bob)))

            text(screen, fonts, AVATARS[i]["name"], max(12, int(30 * sc)), pal.ink, (r.centerx, r.y + h * 0.64),
                 "center", bold=True, alpha=130 + 125 * c)
            if c > 0.25:
                text(screen, fonts, AVATARS[i].get("tag", ""), max(11, int(15 * sc)), pal.ink_soft,
                     (r.centerx, r.y + h * 0.73), "center", alpha=255 * clamp((c - 0.25) / 0.5))
                light, dark = avatars.palettes(AVATARS[i]["id"])
                yy = r.y + h * 0.86
                alpha = 255 * clamp((c - 0.25) / 0.5)
                disc(screen, light.accent, (r.centerx - 44, yy), 8, alpha)
                text(screen, fonts, "Light", 12, pal.ink_soft, (r.centerx - 32, yy), "midleft", alpha=alpha)
                disc(screen, dark.accent, (r.centerx + 14, yy), 8, alpha)
                text(screen, fonts, "Dark", 12, pal.ink_soft, (r.centerx + 26, yy), "midleft", alpha=alpha)
            self.hit(r, lambda k=i: self.car_goto(k))

        if cur > 0.05:
            self.chevron(screen, (54, cy), -1, "chev-l")
        if cur < n - 1.05:
            self.chevron(screen, (sw - 54, cy), 1, "chev-r")

        # dots: a tiny map of the carousel (click one to jump)
        dy = bar.y - 30
        total = n * 26
        for i in range(n):
            c = clamp(1 - abs(i - cur))
            cx = sw / 2 - total / 2 + 13 + i * 26
            dw = int(8 + 16 * c)
            s = pygame.Surface((dw, 8), pygame.SRCALPHA)
            pygame.draw.rect(s, (*avatars.palette(AVATARS[i]["id"], app.dark).accent, int(120 + 135 * c)), s.get_rect(), border_radius=4)
            screen.blit(s, (int(cx - dw / 2), dy - 4))
            self.hit(pygame.Rect(int(cx - 13), dy - 12, 26, 24), lambda k=i: self.car_goto(k))

        # sticky glass bar
        app.glass.card(screen, pal, bar, 32)
        self.hit(bar, lambda: None)                         # registered first = checked last: the bar's own buttons win,
        self.button(screen, (bar.x + 16, bar.y + 10, 120, 44), "Back", self.back)   # but clicks never reach the cards below
        a = AVATARS[focus]
        text(screen, fonts, f"{a['name']}  ·  {a.get('tag', '')}", 16, pal.ink, bar.center, "center", bold=True)
        self.button(screen, (bar.right - 16 - 160, bar.y + 10, 160, 44), "Continue", self.confirm_avatar, primary=True)

    def draw_control(self, screen, sw, sh):
        app, pal, fonts = self.app, self.pal, self.app.fonts
        cw, ch, gap = 270, 190, 22
        x0, y0 = (sw - (3 * cw + 2 * gap)) // 2, 150
        for i, (mid, label, desc) in enumerate(MODES):
            base = pygame.Rect(x0 + i * (cw + gap), y0, cw, ch)
            e = self.ent(i)
            if e <= 0.01:
                continue
            h = self.hv(("mode", i), base)
            r = base.inflate(round(h * 12), round(h * 12)).move(0, round((1 - e) * 70 - h * 5))
            app.glass.card(screen, pal, r, 24)
            if mid == self.mode:
                disc(screen, pal.accent, (r.centerx, r.bottom - 10), 90, 26)
                pygame.draw.rect(screen, pal.accent, r, width=3, border_radius=24)
            elif h > 0.05:
                pygame.draw.rect(screen, pal.ink_soft, r, width=1, border_radius=24)
            text(screen, fonts, label, 22, pal.ink, (r.x + 26, r.y + 28), bold=True)
            for j, line in enumerate(wrap(fonts.get(15), desc, cw - 52)):
                text(screen, fonts, line, 15, pal.ink_soft, (r.x + 26, r.y + 76 + j * 22))
            self.hit(r, lambda m=mid: (setattr(self, "mode", m), self.app.sounds.play("pop")))
        p = self.store.get(self.player_id)
        by = y0 + ch + 36
        text(screen, fonts, f"Playing as {p['name']}", 15, pal.ink_soft, (sw // 2, by - 4), "center")
        by += 22
        self.button(screen, (sw // 2 - 330, by, 190, 46), "Change character", lambda: self.goto("avatar"))
        self.button(screen, (sw // 2 - 130, by, 170, 46), "Switch player", self.back)
        self.button(screen, (sw // 2 + 60, by, 190, 46), "Start", self.start, primary=True)
        if self.error:
            for j, line in enumerate(wrap(fonts.get(14), self.error, min(sw - 80, 760))[:3]):
                text(screen, fonts, line, 14, (214, 76, 76), (sw // 2, by + 74 + j * 20), "center")