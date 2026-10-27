"""
Input sources for the game.

Every controller answers one question per frame: "what does the player want to do?"
    Inputs(jump=True/False, restart=True/False)

game.py never cares where that came from.  KeyboardController is here;
the camera lives in vision_controller.py (VisionController).
"""
from dataclasses import dataclass


@dataclass
class Inputs:
    jump: bool = False
    restart: bool = False


class Controller:
    name = "base"
    hint = "Space / Up = jump     D = theme     Esc = menu"    # shown above the game
    panel_height = 0          # extra pixels the controller wants at the bottom of the window
    ready = True              # False = game waits (e.g. while the camera calibrates)

    def update(self, events) -> Inputs:
        """Called once per frame with the pygame events of that frame."""
        raise NotImplementedError

    def draw_overlay(self, screen, theme, rect):
        """Optional: draw extra things (e.g. the webcam preview) inside `rect`."""

    def close(self):
        """Release resources (e.g. the camera)."""


class KeyboardController(Controller):
    name = "keyboard"

    def update(self, events) -> Inputs:
        import pygame
        keys = pygame.key.get_pressed()
        jump = bool(keys[pygame.K_SPACE] or keys[pygame.K_UP])
        # restart only on a fresh key press, so holding jump when you die doesn't restart instantly
        restart = any(
            e.type == pygame.KEYDOWN and e.key in (pygame.K_SPACE, pygame.K_UP, pygame.K_RETURN)
            for e in events
        )
        return Inputs(jump=jump, restart=restart)


def make_controller(name: str, **options) -> Controller:
    if name == "keyboard":
        return KeyboardController()
    if name in ("body", "hand"):
        from vision_controller import VisionController      # imported lazily: needs opencv
        return VisionController(mode=name, **options)
    raise SystemExit(f"Unknown controller '{name}'. Use: keyboard, body or hand")