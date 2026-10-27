# Runner - glass edition

```
pip install -r requirements.txt
python game.py
```
Use `python3` / `py` instead of `python` if that is how Python starts on your computer.
Camera modes need `opencv-python` and `mediapipe` (Python 3.9 - 3.12 is the safe range for mediapipe).

## Folder layout
```
game.py  game_core.py  ui.py  glass.py  backdrop.py  themes.py  avatars.py  storage.py
controllers.py  vision_controller.py  camera_test.py
trex1.png ... obstacle1.png ...        (the original pictures: dino, ground, clouds, cacti, game over, restart)
avatars/<animal>/run1.png run2.png jump.png dead.png preview.png     (your 8 characters)
coin/coin_00.png ... coin_35.png                                     (your Sphinx logo coin)
```
| file | what it does |
|---|---|
| `game.py` | starts the app: menu, play screen, light/dark fade |
| `game_core.py` | game rules (obstacles, coins, speed, collisions) - no drawing |
| `ui.py` | menus: player, new player, character, controls |
| `glass.py`, `backdrop.py`, `themes.py` | glass cards, the rainy city backdrop, the colour palettes |
| `avatars.py` | the 8 characters, their themes, picture loading |
| `storage.py` | players, scores, Firebase sync (see `FIREBASE_SETUP.md`) |
| `controllers.py`, `vision_controller.py` | keyboard, body jump, hand gestures |
| `extract_avatars.py` | cuts the animals out of your two sprite sheets into `avatars/` |
| `make_coin.py` | turns your logo GIF into the coin pictures in `coin/` |
| `camera_test.py` | finds the webcam settings with the best frame rate |

## Controls
* **Keyboard:** Space / Up. **Body jump:** jump in front of the camera. **Hand gestures:** make a fist, then open your hand.
* `D` light/dark, `C` recalibrate the camera, `Esc` back to the menu.
* `python game.py --controller keyboard|body|hand` skips the menu's control choice.
* The theme fades to the other mode every 700 points (edit `NIGHT_EVERY` in `themes.py`).

## Changing the art
* **Characters:** each animal's four poses come from the sheets: two running poses, a jump pose, a game-over pose and the card picture.
  Which pose is used for what is the `POSES` table in `extract_avatars.py`; put your two sheets next to it and run
  `python extract_avatars.py`. Or just replace the PNGs in `avatars/<animal>/` yourself (transparent background, any size).
  Names and theme colours: the `AVATARS` list in `avatars.py`.
* **Coin:** put a new GIF next to `make_coin.py` and run `python make_coin.py my_logo.gif`.
* **Obstacles:** `obstacle1.png, obstacle2.png, ...` - any number of them. Pictures are drawn at half size; anything taller than
  about 130 px is shrunk to fit.
* **Backdrop:** drawn in code (`backdrop.py`) in the character's colours - towers, monolith with two glowing diamonds,
  rain. Tweak the layers list there.
