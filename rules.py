"""Game rules for Night Survivors. No pygame in this file.

Everything here is plain Python: positions, HP, XP, weapons, timers.
The rules advance one fixed step of STEP seconds at a time.
All numbers come from data/game.json, passed in by the caller as `data`.
"""

import math
import random

STEP = 1 / 60  # seconds per rules tick

WEAPONS = ("spark_wand", "spin_blades", "holy_ring")
PASSIVES = ("swift_boots", "big_heart", "magnet")


def _dist(ax, ay, bx, by):
    return math.hypot(ax - bx, ay - by)


class World:
    def __init__(self, data, rng=None):
        self.data = data
        self.rng = rng if rng is not None else random.Random()
        self.reset()

    def reset(self):
        hero = self.data["hero"]
        self.time = 0.0
        self.hero = {
            "x": 0.0,
            "y": 0.0,
            "hp": hero["max_hp"],
            "max_hp": hero["max_hp"],
            "radius": hero["radius"],
        }
        self.target = None  # world point the hero walks to (None = stand still)
        self.enemies = []
        self.sparks = []
        self.gems = []
        self.kills = 0
        self.game_over = False
        self.victory = False
        self.events = []  # short-lived happenings main.py turns into sounds and effects

        self.level = 1
        self.xp = 0
        self.pending_levelups = 0  # main.py shows cards this many more times
        self.weapons = {"spark_wand": 1}  # start with the Spark Wand
        self.passives = {}

        self._next_enemy_id = 0
        self._spawn_timer = 0.0
        self._boss_spawned = False
        self._wand_timer = 0.0
        self._blade_angle = 0.0
        self._ring_timer = 0.0

    def set_target(self, x, y):
        self.target = (x, y)

    def stop(self):
        self.target = None

    def drain_events(self):
        """Hand over the events collected since last time and clear the list."""
        events, self.events = self.events, []
        return events

    # --- derived stats (from weapon and passive levels) ---------------------

    def xp_need(self):
        x = self.data["xp"]
        return x["first_level_need"] + x["level_need_increment"] * (self.level - 1)

    def hero_speed(self):
        h = self.data["hero"]
        bonus = self.data["passives"]["swift_boots"]["speed_bonus_per_level"]
        return h["speed"] * (1 + bonus * self.passives.get("swift_boots", 0))

    def magnet_radius(self):
        h = self.data["hero"]
        plus = self.data["passives"]["magnet"]["magnet_radius_plus_per_level"]
        return h["magnet_radius"] + plus * self.passives.get("magnet", 0)

    def blade_info(self):
        """None if no Spin Blades, else (count, damage, orbit_radius, blade_hit_radius)."""
        lvl = self.weapons.get("spin_blades")
        if not lvl:
            return None
        s = self.data["spin_blades"]
        return (s["blades_by_level"][lvl - 1],
                s["damage"] + s["damage_plus_per_level"] * (lvl - 1),
                s["radius"], s["blade_hit_radius"])

    def ring_info(self):
        """None if no Holy Ring, else (damage, radius)."""
        lvl = self.weapons.get("holy_ring")
        if not lvl:
            return None
        s = self.data["holy_ring"]
        return (s["damage"] + s["damage_plus_per_level"] * (lvl - 1),
                s["radius"] + s["radius_plus_per_level"] * (lvl - 1))

    def blade_positions(self):
        """Where the spinning blades are right now, for drawing."""
        info = self.blade_info()
        if not info:
            return []
        count = info[0]
        radius = info[2]
        return [(self.hero["x"] + math.cos(self._blade_angle + k * 2 * math.pi / count) * radius,
                 self.hero["y"] + math.sin(self._blade_angle + k * 2 * math.pi / count) * radius)
                for k in range(count)]

    # --- main tick -----------------------------------------------------------

    def tick(self):
        """Advance the world by exactly STEP seconds."""
        if self.game_over or self.victory or self.pending_levelups > 0:
            return
        self._move_hero()
        self._update_enemies()
        self._apply_contact_damage()
        self._update_wand()
        self._update_sparks()
        self._update_blades()
        self._update_ring()
        self._update_gems()
        self._update_spawning()
        self.time += STEP
        if self.time >= self.data["goal"]["time"]:
            self.victory = True
            self.events.append({"type": "end", "victory": True})

    # --- hero ---------------------------------------------------------------

    def _move_hero(self):
        if self.target is None:
            return
        h = self.data["hero"]
        dx = self.target[0] - self.hero["x"]
        dy = self.target[1] - self.hero["y"]
        d = math.hypot(dx, dy)
        if d <= h["mouse_dead_zone"]:
            return
        step = self.hero_speed() * STEP
        if d <= step:
            self.hero["x"] = self.target[0]
            self.hero["y"] = self.target[1]
        else:
            self.hero["x"] += dx / d * step
            self.hero["y"] += dy / d * step

    # --- spawning ------------------------------------------------------------

    def _wave(self):
        """The wave row that is in force right now."""
        current = None
        for wave in self.data["spawning"]["waves"]:
            if wave["from"] <= self.time:
                current = wave
        return current

    def _update_spawning(self):
        s = self.data["spawning"]
        boss = s["boss"]
        if not self._boss_spawned and self.time >= boss["from"]:
            self._boss_spawned = True
            self._add_enemy(boss["type"])
        self._spawn_timer += STEP
        if self._spawn_timer < s["interval"]:
            return
        self._spawn_timer -= s["interval"]
        wave = self._wave()
        if wave is None:
            return
        need = wave["min_alive"] - len(self.enemies)
        room = min(s["max_alive"] - len(self.enemies), s["max_per_interval"])
        for _ in range(max(0, min(need, room))):
            self._add_enemy(self.rng.choice(wave["types"]))

    def _add_enemy(self, type_name):
        s = self.data["spawning"]
        enemy = dict(self.data["enemies"][type_name])  # copy of the stat line
        angle = self.rng.uniform(0, 2 * math.pi)
        enemy.update({
            "type": type_name,
            "id": self._next_enemy_id,
            "x": self.hero["x"] + math.cos(angle) * s["spawn_radius"],
            "y": self.hero["y"] + math.sin(angle) * s["spawn_radius"],
            "last_hit": -1e9,
            "blade_last": -1e9,
        })
        self.enemies.append(enemy)
        self._next_enemy_id += 1

    # --- enemies ---------------------------------------------------------------

    def _update_enemies(self):
        s = self.data["spawning"]
        gone = []
        for e in self.enemies:
            dx = self.hero["x"] - e["x"]
            dy = self.hero["y"] - e["y"]
            d = math.hypot(dx, dy)
            if e.get("boss"):
                # the boss is never removed; if it drifts too far it jumps back
                if d > s["boss_return_radius"]:
                    angle = self.rng.uniform(0, 2 * math.pi)
                    e["x"] = self.hero["x"] + math.cos(angle) * s["spawn_radius"]
                    e["y"] = self.hero["y"] + math.sin(angle) * s["spawn_radius"]
                    continue
            elif d > s["despawn_radius"]:
                gone.append(e)
                continue
            step = e["speed"] * STEP
            if d > step:
                e["x"] += dx / d * step
                e["y"] += dy / d * step
            else:
                e["x"] = self.hero["x"]
                e["y"] = self.hero["y"]
        for e in gone:
            self.enemies.remove(e)

    def _apply_contact_damage(self):
        contact = self.data["contact"]
        for e in self.enemies:
            if _dist(e["x"], e["y"], self.hero["x"], self.hero["y"]) <= e["radius"] + self.hero["radius"]:
                if self.time - e["last_hit"] >= contact["rehit_interval"]:
                    e["last_hit"] = self.time
                    self.hero["hp"] -= e["damage"]
                    self.events.append({"type": "hurt", "amount": e["damage"]})
                    if self.hero["hp"] <= 0:
                        self.hero["hp"] = 0
                        self.game_over = True
                        self.events.append({"type": "end", "victory": False})
                        return

    def _damage_enemy(self, e, damage):
        e["hp"] -= damage
        self.events.append({"type": "hit", "x": e["x"], "y": e["y"], "damage": damage})
        if e["hp"] <= 0:
            self.enemies.remove(e)
            self.kills += 1
            self.events.append({"type": "kill", "x": e["x"], "y": e["y"]})
            if e["xp"] > 0:
                self.gems.append({"x": e["x"], "y": e["y"], "xp": e["xp"]})

    # --- spark wand -------------------------------------------------------------

    def _update_wand(self):
        lvl = self.weapons.get("spark_wand")
        if not lvl:
            return
        w = self.data["spark_wand"]
        interval = w["interval"] - w["interval_minus_per_level"] * (lvl - 1)
        self._wand_timer += STEP
        # never bank more than one shot: with no enemies the timer must not pile up
        self._wand_timer = min(self._wand_timer, interval)
        if self._wand_timer < interval or not self.enemies:
            return
        self._wand_timer -= interval
        damage = w["damage"] + w["damage_plus_per_level"] * (lvl - 1)
        count = w["sparks_by_level"][lvl - 1]
        targets = sorted(self.enemies,
                         key=lambda e: _dist(e["x"], e["y"], self.hero["x"], self.hero["y"]))
        for i in range(count):
            t = targets[i % len(targets)]  # fire at the nearest enemies; repeat if there are fewer
            angle = math.atan2(t["y"] - self.hero["y"], t["x"] - self.hero["x"])
            self.sparks.append({
                "x": self.hero["x"],
                "y": self.hero["y"],
                "vx": math.cos(angle) * w["speed"],
                "vy": math.sin(angle) * w["speed"],
                "damage": damage,
                "life": w["life"],
                "radius": w["radius"],
            })

    def _update_sparks(self):
        w = self.data["spark_wand"]
        dead = []
        for sp in self.sparks:
            sp["x"] += sp["vx"] * STEP
            sp["y"] += sp["vy"] * STEP
            sp["life"] -= STEP
            hit = None
            for e in self.enemies:
                if _dist(sp["x"], sp["y"], e["x"], e["y"]) <= sp["radius"] + e["radius"]:
                    hit = e
                    break
            if hit is not None:
                self._damage_enemy(hit, sp["damage"])
                dead.append(sp)
            elif sp["life"] <= 0:
                dead.append(sp)
        for sp in dead:
            self.sparks.remove(sp)

    # --- spin blades --------------------------------------------------------------

    def _update_blades(self):
        info = self.blade_info()
        if not info:
            return
        count, damage, _, blade_hit = info
        s = self.data["spin_blades"]
        self._blade_angle += (2 * math.pi / s["turn_period"]) * STEP
        for k in range(count):
            a = self._blade_angle + k * 2 * math.pi / count
            bx = self.hero["x"] + math.cos(a) * s["radius"]
            by = self.hero["y"] + math.sin(a) * s["radius"]
            for e in list(self.enemies):
                if _dist(bx, by, e["x"], e["y"]) <= blade_hit + e["radius"]:
                    if self.time - e["blade_last"] >= s["hit_interval"]:
                        e["blade_last"] = self.time
                        self._damage_enemy(e, damage)

    # --- holy ring ---------------------------------------------------------------

    def _update_ring(self):
        info = self.ring_info()
        if not info:
            return
        damage, radius = info
        s = self.data["holy_ring"]
        self._ring_timer += STEP
        if self._ring_timer < s["interval"]:
            return
        self._ring_timer -= s["interval"]
        for e in list(self.enemies):
            if _dist(e["x"], e["y"], self.hero["x"], self.hero["y"]) <= radius + e["radius"]:
                self._damage_enemy(e, damage)

    # --- gems, XP and level-up -----------------------------------------------------

    def _update_gems(self):
        g = self.data["gem"]
        magnet = self.magnet_radius()
        taken = []
        for gem in self.gems:
            dx = self.hero["x"] - gem["x"]
            dy = self.hero["y"] - gem["y"]
            d = math.hypot(dx, dy)
            if d <= self.hero["radius"]:
                taken.append(gem)
                continue
            if d <= magnet:
                step = g["speed"] * STEP
                if d <= step:
                    gem["x"], gem["y"] = self.hero["x"], self.hero["y"]
                else:
                    gem["x"] += dx / d * step
                    gem["y"] += dy / d * step
        for gem in taken:
            self.gems.remove(gem)
            self.events.append({"type": "gem", "xp": gem["xp"]})
            self._add_xp(gem["xp"])

    def _add_xp(self, amount):
        self.xp += amount
        while self.xp >= self.xp_need():
            self.xp -= self.xp_need()
            self.level += 1
            self.pending_levelups += 1
            self.events.append({"type": "levelup"})

    def offer_cards(self):
        """Three random choices for a level-up (fewer if not enough exist)."""
        options = []
        for key in WEAPONS:
            lvl = self.weapons.get(key, 0)
            if lvl == 0 and len(self.weapons) < 3:
                options.append({"key": key, "kind": "weapon", "level": 1})
            elif 0 < lvl < 5:
                options.append({"key": key, "kind": "weapon", "level": lvl + 1})
        for key in PASSIVES:
            lvl = self.passives.get(key, 0)
            if lvl < 5:
                options.append({"key": key, "kind": "passive", "level": lvl + 1})
        self.rng.shuffle(options)
        cards = options[: self.data["levelup"]["cards_shown"]]
        if not cards:
            cards = [{"key": "heal", "kind": "heal", "level": 1}]
        return cards

    def take_card(self, card):
        if card["kind"] == "heal":
            heal = self.data["levelup"]["heal_fallback"]
            self.hero["hp"] = min(self.hero["max_hp"], self.hero["hp"] + heal)
        elif card["kind"] == "weapon":
            self.weapons[card["key"]] = card["level"]
        else:
            self.passives[card["key"]] = card["level"]
            if card["key"] == "big_heart":
                p = self.data["passives"]["big_heart"]
                self.hero["max_hp"] += p["max_hp_plus_per_level"]
                self.hero["hp"] = min(self.hero["max_hp"], self.hero["hp"] + p["heal_per_level"])
        self.pending_levelups -= 1
