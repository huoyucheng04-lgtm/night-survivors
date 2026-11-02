"""Night Survivors — window, drawing, input, main loop.

Run with:  python main.py
The loop is async (one `await asyncio.sleep(0)` per frame) so pygbag can run
this file in a web browser. Only finished files from assets/ are loaded here.
"""

import asyncio
import json
import math
import os
import random

import pygame

from rules import World, STEP, WEAPONS, PASSIVES

HERE = os.path.dirname(os.path.abspath(__file__))

# ---- colours that are only about drawing (not game rules) ----
SPARK_COLOUR = (255, 170, 40)
HP_BAR_COLOUR = (220, 70, 70)
XP_BAR_COLOUR = (70, 130, 255)
BAR_BG = (60, 60, 60)
CARD_BG = (48, 52, 70)
CARD_BORDER = (255, 220, 120)


def load_data():
    with open(os.path.join(HERE, "data", "game.json")) as f:
        return json.load(f)


def load_image(name):
    path = os.path.join(HERE, "assets", name)
    if not os.path.exists(path):
        raise SystemExit("missing %s — run  python make_assets.py  first" % path)
    return pygame.image.load(path).convert_alpha()


def load_sound(name):
    """A finished file from sounds/ (.ogg preferred, .wav also fine). None = stay silent."""
    for ext in ("ogg", "wav"):
        path = os.path.join(HERE, "sounds", "%s.%s" % (name, ext))
        if os.path.exists(path):
            try:
                return pygame.mixer.Sound(path)
            except pygame.error:
                return None
    return None


def card_text(card, data):
    info = data["cards"][card["key"]]
    line2 = "New!" if card["level"] == 1 else "Lv %d" % card["level"]
    return info["name"], line2, info["text"]


async def main():
    data = load_data()
    pygame.init()
    screen = pygame.display.set_mode((data["window"]["width"], data["window"]["height"]))
    pygame.display.set_caption("Night Survivors")
    font = pygame.font.SysFont(None, 26)
    mid_font = pygame.font.SysFont(None, 34)
    big_font = pygame.font.SysFont(None, 64)
    clock = pygame.time.Clock()

    sounds = {}
    if pygame.mixer.get_init():
        for name in ("hit", "gem", "levelup", "hurt", "end"):
            sounds[name] = load_sound(name)
    else:  # no audio device (for example in tests): the game still runs silently
        sounds = {name: None for name in ("hit", "gem", "levelup", "hurt", "end")}

    world = World(data)
    center = (data["window"]["width"] / 2, data["window"]["height"] / 2)
    view = list(center)  # centre plus shake offset, used for all world drawing

    hero_img = load_image("hero.png")
    floor_img = load_image("floor.png")
    sword_img = load_image("sword.png")
    gem_blue = load_image("gem_blue.png")
    gem_pink = load_image("gem_pink.png")
    enemy_imgs = {}
    for name, stats in data["enemies"].items():
        img = load_image(name + ".png")
        scale = stats.get("draw_scale", 1)
        if scale != 1:  # the boss is drawn twice as big (scale() keeps pixels crisp)
            img = pygame.transform.scale(img, (img.get_width() * scale, img.get_height() * scale))
        enemy_imgs[name] = img

    def to_screen(x, y):
        return (x - world.hero["x"] + view[0], y - world.hero["y"] + view[1])

    def to_world(sx, sy):
        return (sx - center[0] + world.hero["x"], sy - center[1] + world.hero["y"])

    def blit_center(img, pos):
        screen.blit(img, (pos[0] - img.get_width() // 2, pos[1] - img.get_height() // 2))

    # level-up cards: rect for each offer, top to bottom
    card_rects = []
    w, h = 350, 150
    y = 170
    for _ in range(data["levelup"]["cards_shown"]):
        card_rects.append(pygame.Rect((data["window"]["width"] - w) // 2, y, w, h))
        y += h + 20

    input_mode = "idle"  # "mouse" follows the pointer, "touch" follows the finger, "idle" stands still
    touch_target_screen = None
    offers = None
    paused = False
    acc = 0.0
    running = True

    dmg_texts = []   # {"x", "y", "text", "age", "colour"} floating damage numbers
    flashes = []     # {"x", "y", "age"} white pop where an enemy died
    shake = 0.0      # seconds of screen shake left
    SHAKE_TIME = 0.18
    TEXT_TIME = 0.7
    FLASH_TIME = 0.25

    def restart():
        nonlocal paused, acc, offers, shake
        world.reset()
        paused = False
        acc = 0.0
        offers = None
        dmg_texts.clear()
        flashes.clear()
        shake = 0.0

    def play(name):
        sound = sounds.get(name)
        if sound:
            sound.play()

    def pick_card(pos):
        nonlocal offers
        for rect, card in zip(card_rects, offers):
            if rect.collidepoint(pos):
                world.take_card(card)
                offers = None
                return

    while running:
        dt = min(clock.tick(60) / 1000.0, 0.25)
        acc += dt  # don't let the catch-up grow unbounded

        for e in pygame.event.get():
            if e.type == pygame.QUIT:
                running = False
            elif e.type == pygame.MOUSEMOTION:
                input_mode = "mouse"
            elif e.type == pygame.KEYDOWN and e.key == pygame.K_p and not (world.game_over or world.victory):
                if offers is None:
                    paused = not paused
            elif e.type == pygame.MOUSEBUTTONDOWN:
                if offers is not None:
                    pick_card(e.pos)
                elif world.game_over or world.victory:
                    restart()
            elif e.type in (pygame.FINGERDOWN, pygame.FINGERMOTION):
                pos = (e.x * data["window"]["width"], e.y * data["window"]["height"])
                if e.type == pygame.FINGERDOWN:
                    if offers is not None:
                        pick_card(pos)
                        continue
                    if world.game_over or world.victory:
                        restart()
                        continue
                input_mode = "touch"
                touch_target_screen = pos
            elif e.type == pygame.FINGERUP:
                input_mode = "idle"
                touch_target_screen = None

        if offers is None and world.pending_levelups > 0:
            offers = world.offer_cards()

        # keep walking toward the pointer even when the mouse does not move
        if input_mode == "mouse":
            world.set_target(*to_world(*pygame.mouse.get_pos()))
        elif touch_target_screen is not None:
            world.set_target(*to_world(*touch_target_screen))
        else:
            world.stop()

        if not paused:
            while acc >= STEP:
                acc -= STEP
                world.tick()

        # ---- events: sounds and feel ----
        hits_played = 0
        for ev in world.drain_events():
            et = ev["type"]
            if et == "hit":
                dmg_texts.append({"x": ev["x"], "y": ev["y"], "text": str(ev["damage"]),
                                  "age": 0.0, "colour": (255, 255, 255)})
                if hits_played < 3:  # cap: many simultaneous hits must not become a wall of noise
                    play("hit")
                    hits_played += 1
            elif et == "kill":
                flashes.append({"x": ev["x"], "y": ev["y"], "age": 0.0})
            elif et == "gem":
                play("gem")
            elif et == "levelup":
                play("levelup")
            elif et == "hurt":
                play("hurt")
                shake = SHAKE_TIME
                dmg_texts.append({"x": world.hero["x"], "y": world.hero["y"] - 20,
                                  "text": "-%d" % ev["amount"], "age": 0.0,
                                  "colour": (255, 120, 120)})
            elif et == "end":
                play("end")

        for t in dmg_texts:
            t["age"] += dt
        dmg_texts[:] = [t for t in dmg_texts if t["age"] < TEXT_TIME]
        for f in flashes:
            f["age"] += dt
        flashes[:] = [f for f in flashes if f["age"] < FLASH_TIME]
        if shake > 0:
            shake = max(0.0, shake - dt)
            mag = 4.0 * shake / SHAKE_TIME
            view[0] = center[0] + random.uniform(-mag, mag)
            view[1] = center[1] + random.uniform(-mag, mag)
        else:
            view[0], view[1] = center

        # ---------------- drawing ----------------
        tile = floor_img.get_width()
        y0 = (-world.hero["y"]) % tile - tile
        y = y0
        while y < data["window"]["height"]:
            x = (-world.hero["x"]) % tile - tile
            while x < data["window"]["width"]:
                screen.blit(floor_img, (x, y))
                x += tile
            y += tile

        ring = world.ring_info()
        if ring:
            pygame.draw.circle(screen, (255, 240, 140), view, int(ring[1]), 3)
        for gem in world.gems:
            img = gem_pink if gem["xp"] >= data["gem"]["min_xp_for_pink"] else gem_blue
            blit_center(img, to_screen(gem["x"], gem["y"]))
        for e in world.enemies:
            blit_center(enemy_imgs[e["type"]], to_screen(e["x"], e["y"]))
        for sp in world.sparks:
            pygame.draw.circle(screen, SPARK_COLOUR, to_screen(sp["x"], sp["y"]), sp["radius"])
        for pos in world.blade_positions():
            ang = math.atan2(pos[1] - world.hero["y"], pos[0] - world.hero["x"])
            img = pygame.transform.rotate(sword_img, -math.degrees(ang))
            blit_center(img, to_screen(*pos))
        blit_center(hero_img, view)

        # death flashes and floating damage numbers
        for f in flashes:
            frac = f["age"] / FLASH_TIME
            r = int(16 + 22 * frac)
            pop = pygame.Surface((r * 2, r * 2), pygame.SRCALPHA)
            pygame.draw.circle(pop, (255, 255, 255, int(200 * (1.0 - frac))), (r, r), r)
            pos = to_screen(f["x"], f["y"])
            screen.blit(pop, (pos[0] - r, pos[1] - r))
        for t in dmg_texts:
            frac = t["age"] / TEXT_TIME
            colour = tuple(int(v * (1.0 - frac)) for v in t["colour"])
            pos = to_screen(t["x"], t["y"])
            img = font.render(t["text"], True, colour)
            screen.blit(img, (pos[0] - img.get_width() / 2, pos[1] - 30 - 25 * frac))

        # HUD: HP bar, XP bar, level, inventory
        bar_w = 140
        pygame.draw.rect(screen, BAR_BG, (10, 10, bar_w, 14), border_radius=4)
        frac = world.hero["hp"] / world.hero["max_hp"]
        if frac > 0:
            pygame.draw.rect(screen, HP_BAR_COLOUR, (10, 10, int(bar_w * frac), 14), border_radius=4)
        pygame.draw.rect(screen, BAR_BG, (10, 28, bar_w, 10), border_radius=4)
        xfrac = world.xp / world.xp_need()
        if xfrac > 0:
            pygame.draw.rect(screen, XP_BAR_COLOUR, (10, 28, int(bar_w * xfrac), 10), border_radius=4)
        screen.blit(mid_font.render("Lv %d" % world.level, True, (255, 255, 255)), (10, 42))
        goal = data["goal"]["time"]
        timer = "%d:%02d / %d:%02d" % (int(world.time) // 60, int(world.time) % 60,
                                       goal // 60, goal % 60)
        timg = font.render(timer, True, (255, 255, 255))
        screen.blit(timg, (data["window"]["width"] - timg.get_width() - 10, 10))
        have = ["%s %d" % (data["cards"][k]["short"], world.weapons[k])
                for k in WEAPONS if k in world.weapons]
        have += ["%s %d" % (data["cards"][k]["short"], world.passives[k])
                 for k in PASSIVES if k in world.passives]
        screen.blit(font.render("  ".join(have), True, (255, 255, 255)), (10, data["window"]["height"] - 30))

        if offers is not None:
            shade = pygame.Surface(screen.get_size())
            shade.set_alpha(170)
            shade.fill((0, 0, 0))
            screen.blit(shade, (0, 0))
            title = big_font.render("LEVEL UP", True, (255, 220, 120))
            screen.blit(title, (center[0] - title.get_width() / 2, 60))
            for rect, card in zip(card_rects, offers):
                pygame.draw.rect(screen, CARD_BG, rect, border_radius=12)
                pygame.draw.rect(screen, CARD_BORDER, rect, width=3, border_radius=12)
                name, lvl, text = card_text(card, data)
                line1 = mid_font.render("%s  —  %s" % (name, lvl), True, (255, 255, 255))
                line2 = font.render(text, True, (200, 205, 220))
                screen.blit(line1, (rect.x + 20, rect.y + 30))
                screen.blit(line2, (rect.x + 20, rect.y + 85))

        if paused and offers is None:
            shade = pygame.Surface(screen.get_size())
            shade.set_alpha(140)
            shade.fill((0, 0, 0))
            screen.blit(shade, (0, 0))
            text = big_font.render("PAUSED", True, (255, 255, 255))
            screen.blit(text, (center[0] - text.get_width() / 2, center[1] - 40))

        if world.game_over or world.victory:
            shade = pygame.Surface(screen.get_size())
            shade.set_alpha(170)
            shade.fill((0, 0, 0))
            screen.blit(shade, (0, 0))
            if world.victory:
                title, colour = "VICTORY", (110, 230, 110)
            else:
                title, colour = "GAME OVER", (230, 70, 70)
            text = big_font.render(title, True, colour)
            screen.blit(text, (center[0] - text.get_width() / 2, center[1] - 110))
            goal = data["goal"]["time"]
            stats = font.render("Time %d:%02d / %d:%02d   Kills %d   Lv %d"
                                % (int(world.time) // 60, int(world.time) % 60,
                                   goal // 60, goal % 60, world.kills, world.level),
                                True, (255, 255, 255))
            screen.blit(stats, (center[0] - stats.get_width() / 2, center[1] - 20))
            again = font.render("click or tap to play again", True, (200, 205, 220))
            screen.blit(again, (center[0] - again.get_width() / 2, center[1] + 20))

        pygame.display.flip()
        await asyncio.sleep(0)

    pygame.quit()


if __name__ == "__main__":
    asyncio.run(main())
