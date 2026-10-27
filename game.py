"""
Runner  -  glass edition.     Run:   python game.py

Menu: pick / create a player, choose a character (scroll the page), choose how to control the game
(keyboard, body jump or hand gestures).  The theme fades between light and dark as your score rises.

Keys in the game:  Space / Up = jump (and restart)     D = light / dark     F11 = full screen
                   M = sound on/off     C = recalibrate camera     Esc = back to the menu
Optional:  python game.py --controller keyboard|body|hand     (skips the menu choice)
Put this file next to the PNG pictures (trex1.png, ground2.png, obstacle1.png ...).
"""
import argparse
import math
import random

import pygame

import avatars
from avatars import AVATARS
from controllers import make_controller
from game_core import Game, WIDTH, HEIGHT, GROUND_Y, END, PLAY
from glass import Fonts, GlassKit, text, pill, disc, fit_text
from motion import Tween, ease, clamp
from sound import SoundBank
from storage import Store
from themes import lerp, night_target, ease_level
from ui import MenuScene


# ---------------------------------------------------------------- drawing the world
class SpriteCache:
    """Pictures are kept at full resolution and scaled once per window size - so they stay sharp."""

    def __init__(self):
        self._c = {}

    def scaled(self, surf, pw, ph):
        key = (id(surf), pw, ph)
        img = self._c.get(key)
        if img is None:
            if len(self._c) > 800:
                self._c.clear()
            img = surf if surf.get_size() == (pw, ph) else pygame.transform.smoothscale(surf, (pw, ph))
            self._c[key] = img
        return img

    def sprite(self, spr, scale):
        return self.scaled(spr.surf, max(1, round(spr.lw * scale)), max(1, round(spr.lh * scale)))


def draw_world(target, game, w, g, scale, cache, squash=0.0):
    """The game inside rectangle g (game units * scale = pixels), drawn straight onto the window."""

    def centre(spr, x, y):
        img = cache.sprite(spr, scale)
        target.blit(img, (round(g.x + x * scale - img.get_width() / 2), round(g.y + y * scale - img.get_height() / 2)))

    def feet(spr, x, bottom):
        img = cache.sprite(spr, scale)
        if abs(squash) > 0.02:                           # squash and stretch, anchored at the feet
            img = pygame.transform.smoothscale(
                img, (max(2, round(img.get_width() * (1 - 0.6 * squash))), max(2, round(img.get_height() * (1 + squash)))))
        target.blit(img, (round(g.x + x * scale - img.get_width() / 2), round(g.y + bottom * scale - img.get_height())))

    target.set_clip(g)
    centre(w["ground"], game.ground_x, GROUND_Y)
    for c in game.clouds:
        centre(w["cloud"], c.x, c.y)
    coin = w["coin"][(game.frame // 3) % len(w["coin"])]
    for c in game.coins:
        centre(coin, c.x, c.y)
    for o in game.obstacles:
        centre(w["obstacles"][o.image], o.x, o.y)
    t = game.trex
    if game.state == END:
        pose = w["dead"]
    elif not game.on_ground:
        pose = w["jump"]
    else:
        pose = w["run"][(game.frame // 5) % len(w["run"])]
    feet(pose, t.x, t.y + t.h / 2)                       # feet always rest on the ground, whatever the pose
    if game.state == END:
        centre(w["game_over"], 300, 100)
        centre(w["restart"], 300, 140)
    target.set_clip(None)


# ---------------------------------------------------------------- play screen
class PlayScene:
    def __init__(self, app, player_id, avatar_id, mode):
        self.app = app
        self.player = app.store.get(player_id)
        self.player_id, self.avatar_id, self.mode = player_id, avatar_id, mode
        self.world = app.world(avatar_id)
        self.controller = make_controller(mode, **app.cam_options) if mode != "keyboard" else make_controller("keyboard")
        self.game = Game(self.world["sizes"], high_score=self.player["best_score"])
        self.level = 1.0 if app.dark else 0.0          # 0 = light ... 1 = dark (fades)
        self.cycle = False                              # the automatic day/night flip
        self.result = None                              # set when a run ends: {'new_best': ..}
        self.pulse = 0                                  # little bounce of the coin counter
        self.buf = None
        self.controller_restart = False
        self.hover = {}
        self.time = 0.0
        self.stretch = 0.0                              # squash (-) / stretch (+) of the character
        self.in_air = False
        self.shake = 0.0
        self.floats = []                                # [text, x, y, age]
        self.streak, self.last_coin = 0, -9.0
        self.milestone = 0
        self.dead_time = None
        self.pending = []                               # (time, sound)
        self.rects = {}
        pygame.key.stop_text_input()

    # ---- life cycle ----------------------------------------------------
    def close(self):
        if self.game.state == PLAY and self.game.score > 0:
            self.finish()
        self.controller.close()

    def finish(self):
        """Save the run once (when it ends or when you leave in the middle of it)."""
        self.result = self.app.store.record_run(self.player_id, self.game.score, self.game.coins_collected)

    def menu_state(self):
        return ("menu", {"page": "control", "player_id": self.player_id,
                         "avatar_id": self.avatar_id, "mode": self.mode})

    def hv(self, key, rect):
        tw = self.hover.get(key)
        if tw is None:
            tw = self.hover[key] = Tween(0.0, 0.0, 0.18, "power2.out")
        tw.to(1.0 if pygame.Rect(rect).collidepoint(pygame.mouse.get_pos()) else 0.0)
        tw.update(self.app.dt)
        return tw.value

    # ---- layout ----------------------------------------------------------
    def layout(self, sw, sh):
        panel_h = self.controller.panel_height
        top = 96
        avail = sh - top - panel_h - 24
        scale = max(0.4, min((sw - 100) / WIDTH, (avail - 40) / HEIGHT))
        gw, gh = int(WIDTH * scale), int(HEIGHT * scale)
        gx, gy = (sw - gw) // 2, top + (avail - gh) // 2
        L = {"scale": scale, "game": pygame.Rect(gx, gy, gw, gh),
             "card": pygame.Rect(gx - 20, gy - 20, gw + 40, gh + 40),
             "bar": pygame.Rect(20, 14, sw - 40, 60), "panel": None}
        x = sw - 36
        for key, w in (("menu", 92), ("theme", 92), ("full", 124), ("sound", 108)):
            x -= w
            L[key] = pygame.Rect(x, 26, w, 36)
            x -= 8
        if panel_h:
            L["panel"] = pygame.Rect(40, sh - 174 - 18, sw - 80, 174)
        return L

    # ---- frame -----------------------------------------------------------
    def step(self, events):
        app, game, snd = self.app, self.game, self.app.sounds
        screen = pygame.display.get_surface()
        sw, sh = screen.get_size()
        L = self.layout(sw, sh)
        dt = app.dt
        self.time += dt

        for e in events:
            if e.type == pygame.KEYDOWN:
                if e.key == pygame.K_ESCAPE:
                    return self.menu_state()
                if e.key == pygame.K_d:
                    app.dark = not app.dark
                if e.key == pygame.K_m:
                    snd.toggle()
            elif e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
                if L["menu"].collidepoint(e.pos):
                    return self.menu_state()
                if L["theme"].collidepoint(e.pos):
                    app.dark = not app.dark
                    snd.play("pop")
                elif L["full"].collidepoint(e.pos):
                    app.toggle_fullscreen()
                elif L["sound"].collidepoint(e.pos):
                    snd.toggle()
                elif game.state == END:
                    g, s = L["game"], L["scale"]
                    lx, ly = (e.pos[0] - g.x) / s, (e.pos[1] - g.y) / s
                    rs = self.world["light"]["restart"]
                    if abs(lx - 300) < rs.lw / 2 and abs(ly - 140) < rs.lh / 2:
                        self.controller_restart = True

        inputs = self.controller.update(events)
        restart = inputs.restart or self.controller_restart
        self.controller_restart = False
        out = game.step(jump=inputs.jump, restart=restart) if self.controller.ready else []
        self.react(out, L)

        if game.state == PLAY:
            flip = night_target(game.score)
            if flip != self.cycle:
                snd.play("whoosh")
            self.cycle = flip
        self.level = ease_level(self.level, app.dark != self.cycle)
        self.pulse = max(0, self.pulse - 1)
        self.stretch *= 0.80 ** (dt * 60)
        self.shake *= 0.88 ** (dt * 60)
        for item in list(self.pending):
            if self.time >= item[0]:
                snd.play(item[1])
                self.pending.remove(item)
        self.draw(screen, L)
        return None

    def react(self, out, L):
        """Everything that happens *because* something happened in the game: sounds and shakes."""
        app, game, snd = self.app, self.game, self.app.sounds
        g, s = L["game"], L["scale"]
        t = game.trex
        char_px = (g.x + t.x * s, g.y + (t.y - t.h * 0.2) * s)

        if "jump" in out:
            self.stretch = 0.30
            snd.play("boing")
        air = not game.on_ground and game.state == PLAY
        if self.in_air and not air and game.state == PLAY:
            self.stretch = -0.26
            snd.play("land")
        self.in_air = air

        for _ in game.picked:
            self.streak = self.streak + 1 if self.time - self.last_coin < 0.9 else 0
            self.last_coin = self.time
            snd.play("coin", self.streak)
            self.pulse = 10                                # the coin counter bounces

        ms = game.score // 100
        if game.state == PLAY and ms > self.milestone:
            self.milestone = ms
            snd.play("ding")
            self.floats.append([f"{ms * 100}", char_px[0], char_px[1] - 30 * s, 0.0])

        if "died" in out:
            self.finish()
            self.shake = 14.0
            snd.play("death")
            if self.result and self.result.get("new_best") and game.score > 0:
                self.pending.append((self.time + 0.85, "fanfare"))
            self.dead_time = 0.0
        if "restart" in out:
            self.result, self.dead_time, self.milestone = None, None, 0
            snd.play("restart")

    # ---- drawing -----------------------------------------------------------
    def draw(self, screen, L):
        lvl = self.level
        off = (random.uniform(-1, 1) * self.shake, random.uniform(-1, 1) * self.shake) if self.shake > 0.4 else (0, 0)
        if off != (0, 0):
            L = dict(L)
            L["game"] = L["game"].move(off)
            L["card"] = L["card"].move(off)
        if lvl <= 0.0 or lvl >= 1.0:
            self.render(screen, L, lvl >= 1.0)
        else:                                            # cross-fade two complete renderings
            size = screen.get_size()
            if self.buf is None or self.buf.get_size() != size:
                self.buf = pygame.Surface(size).convert()
            self.render(screen, L, True)
            self.render(self.buf, L, False)
            self.buf.set_alpha(int(255 * (1 - lvl)))
            screen.blit(self.buf, (0, 0))
        light, dark = avatars.palettes(self.avatar_id)
        accent, ink = lerp(light.accent, dark.accent, lvl), lerp(light.ink, dark.ink, lvl)
        if L["panel"] is not None:
            theme = {"fg": ink, "soft": lerp(light.ink_soft, dark.ink_soft, lvl), "accent": accent,
                     "track": lerp((205, 205, 215), (70, 70, 85), lvl)}
            self.controller.draw_overlay(screen, theme, L["panel"])

        # floating score texts
        for f in list(self.floats):
            f[3] += self.app.dt
            if f[3] > 1.0:
                self.floats.remove(f)
                continue
            k = f[3]
            text(screen, self.app.fonts, f[0], int(22 + 10 * ease("back.out", k * 3)), accent,
                 (f[1], f[2] - 70 * ease("power3.out", k)), "center", bold=True, alpha=255 * (1 - k ** 2))

    def render(self, target, L, dark):
        app, game, fonts = self.app, self.game, self.app.fonts
        pal = avatars.palette(self.avatar_id, dark)
        w = self.world["dark" if dark else "light"]
        sw, sh = target.get_size()
        app.glass.paint_background(target, pal, t=self.time)

        # glass top bar
        bar = L["bar"]
        app.glass.card(target, pal, bar, 30)
        center = (bar.x + 38, bar.centery)
        disc(target, pal.accent, center, 22, 60)
        prev = avatars.preview(self.avatar_id, app.base, dark)
        k = min(40 / prev.get_width(), 30 / prev.get_height())
        img = app.sprites.scaled(prev, max(2, round(prev.get_width() * k)), max(2, round(prev.get_height() * k)))
        target.blit(img, img.get_rect(center=center))
        text(target, fonts, fit_text(fonts, self.player["name"], 19, 230, True), 19, pal.ink, (bar.x + 74, bar.y + 10), bold=True)
        text(target, fonts, f"{avatars.avatar(self.avatar_id)['name']}  ·  {self.controller.name}", 13,
             pal.ink_soft, (bar.x + 74, bar.y + 34))
        for key, label in (("menu", "Menu"), ("theme", "Light" if dark else "Dark"),
                           ("full", "Windowed" if app.fullscreen else "Full screen"),
                           ("sound", "Sound off" if app.sounds.muted else "Sound on")):
            pill(target, fonts, pal, L[key], label, hover=self.hv(key, L[key]), size=14)

        # game card
        g = L["game"]
        app.glass.card(target, pal, L["card"], 28)
        draw_world(target, game, w, g, L["scale"], app.sprites, self.stretch)

        # glass HUD chips: coins (left) and score (right)
        s = L["scale"]
        size = max(13, int(6 * s + 5))
        coin = w["coin"][(game.frame // 3) % len(w["coin"])]
        ch = max(18, int(coin.lh * s * 0.7))
        chip = pygame.Rect(g.x + 8, g.y + 8, ch + 28 + size * 3 + round(self.pulse * 1.5), ch + 10)
        app.glass.card(target, pal, chip, chip.height // 2)
        target.blit(app.sprites.scaled(coin.surf, ch, ch), (chip.x + 10, chip.y + 5))
        text(target, fonts, str(game.coins_collected), size + int(self.pulse * 0.6), pal.ink,
             (chip.x + 10 + ch + 8, chip.centery), "midleft", bold=True)
        hi = f"HI {game.high_score:05d}   {game.score:05d}"
        sw_chip = fonts.get(size, True).size(hi)[0] + 34
        chip2 = pygame.Rect(g.right - 8 - sw_chip, g.y + 8, sw_chip, ch + 10)
        app.glass.card(target, pal, chip2, chip2.height // 2)
        text(target, fonts, hi, size, pal.ink_soft, chip2.center, "center", bold=True)
        if self.result and self.result.get("new_best") and game.state == END:
            text(target, fonts, "New best!", size, pal.accent, (chip2.centerx, chip2.bottom + 10), "midtop", bold=True)
        if L["panel"] is not None:
            app.glass.card(target, pal, L["panel"], 26)


# ---------------------------------------------------------------- application
class App:
    def __init__(self, args):
        pygame.init()
        try:                                              # fit the window to this screen
            info = pygame.display.Info()
            size = (max(900, min(1180, info.current_w - 80)), max(700, min(780, info.current_h - 140)))
        except Exception:
            size = (1180, 780)
        self.fullscreen = False
        self.windowed_size = size
        pygame.display.set_mode(size, pygame.RESIZABLE)
        pygame.display.set_caption("Runner")
        self.fonts, self.glass, self.sprites = Fonts(), GlassKit(), SpriteCache()
        self.store = Store()
        self.base = avatars.load_base_assets()
        self.sounds = SoundBank()
        self.dark = False
        self.dt = 1 / 60
        self.forced_mode = getattr(args, "controller", None)    # None = use whatever is picked in the menu
        self.cam_options = dict(camera=args.camera, backend=args.backend, sensitivity=args.sensitivity,
                                camera_api=args.camera_api, exposure=args.exposure)
        self._worlds = {}

    def toggle_fullscreen(self):
        self.fullscreen = not self.fullscreen
        if self.fullscreen:
            self.windowed_size = pygame.display.get_surface().get_size()
            pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
        else:
            pygame.display.set_mode(self.windowed_size, pygame.RESIZABLE)

    def world(self, avatar_id):
        if avatar_id not in self._worlds:
            self._worlds[avatar_id] = avatars.build_world(avatar_id, self.base)
        return self._worlds[avatar_id]

    def loading(self, message):
        screen = pygame.display.get_surface()
        pal = avatars.palette(AVATARS[0]["id"], self.dark)
        self.glass.paint_background(screen, pal)
        text(screen, self.fonts, message, 22, pal.ink, (screen.get_width() // 2, screen.get_height() // 2), "center")
        pygame.display.flip()

    def run(self):
        scene = MenuScene(self)
        clock = pygame.time.Clock()
        while True:
            events = pygame.event.get()
            if any(e.type == pygame.QUIT for e in events):
                break
            for e in events:
                if e.type == pygame.KEYDOWN and (e.key == pygame.K_F11 or (
                        e.key == pygame.K_RETURN and pygame.key.get_mods() & pygame.KMOD_ALT)):
                    self.toggle_fullscreen()
            result = scene.step(events)
            pygame.display.flip()
            self.dt = min(clock.tick(60) / 1000.0, 0.05)
            if not result:
                continue
            if result[0] == "quit":
                break
            if result[0] == "menu":
                scene.close()
                scene = MenuScene(self, **result[1])
            elif result[0] == "play":
                cfg = dict(result[1])
                if self.forced_mode:                      # --controller overrides the menu choice
                    cfg["mode"] = self.forced_mode
                self.loading("Starting camera..." if cfg["mode"] != "keyboard" else "Loading...")
                try:
                    scene = PlayScene(self, **cfg)
                except (SystemExit, Exception) as e:
                    scene = MenuScene(self, page="control", player_id=cfg["player_id"],
                                      avatar_id=cfg["avatar_id"], mode=cfg["mode"], error=str(e) or type(e).__name__)
        scene.close()
        self.store.close()
        pygame.quit()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--controller", default=None, choices=["keyboard", "body", "hand", "vision"],
                    help="control mode to use when a game starts (default: the one chosen in the menu; "
                         "'vision' = body)")
    ap.add_argument("--camera", type=int, default=0, help="webcam number (camera modes)")
    ap.add_argument("--backend", default="auto", choices=["auto", "pose", "face"],
                    help="body jump: how the camera finds you")
    ap.add_argument("--camera-api", default="auto", choices=["auto", "dshow", "msmf", "any"],
                    help="camera modes: how Windows talks to the webcam (try msmf if fps is stuck at 15)")
    ap.add_argument("--exposure", type=float, default=None,
                    help="camera modes: fixed webcam exposure, e.g. -6 (shorter = more fps, darker picture)")
    ap.add_argument("--sensitivity", type=float, default=1.0,
                    help="body jump: above 1 = smaller jumps count, below 1 = bigger jumps needed")
    args = ap.parse_args()
    if args.controller == "vision":
        args.controller = "body"
    App(args).run()


if __name__ == "__main__":
    main()