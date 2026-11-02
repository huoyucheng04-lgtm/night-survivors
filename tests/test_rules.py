"""unittest tests for the game rules in rules.py (no pygame needed)."""

import json
import math
import os
import random
import unittest

from rules import World, STEP, WEAPONS, PASSIVES

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_PATH = os.path.join(HERE, "..", "data", "game.json")


def make_world(seed=1, waves=True, boss=True):
    with open(DATA_PATH) as f:
        data = json.load(f)
    if not waves:  # silence the spawn table so a test can watch one enemy alone
        for wave in data["spawning"]["waves"]:
            wave["min_alive"] = 0
    if not boss:
        data["spawning"]["boss"]["from"] = 10 ** 9
    return World(data, rng=random.Random(seed))


def tick(world, seconds):
    for _ in range(round(seconds / STEP)):
        world.tick()


def add_enemy_at(world, type_name, x, y, hp=None):
    world._add_enemy(type_name)
    e = world.enemies[-1]
    e["x"], e["y"] = x, y
    if hp is not None:
        e["hp"] = hp
    return e


class Spawning(unittest.TestCase):
    def test_first_batch_spawns_on_the_spawn_circle(self):
        world = make_world()
        tick(world, 1.0)  # first spawn moment
        radius = world.data["spawning"]["spawn_radius"]
        self.assertEqual(len(world.enemies), 8)  # at most 8 per second
        for e in world.enemies:
            d = math.hypot(e["x"] - world.hero["x"], e["y"] - world.hero["y"])
            self.assertAlmostEqual(d, radius, places=6)
            self.assertEqual(e["type"], "bat")  # 0:00 wave is bats only

    def test_alive_grows_to_the_minimum(self):
        world = make_world()
        minimum = world.data["spawning"]["waves"][0]["min_alive"]
        tick(world, 3.0)
        self.assertGreaterEqual(len(world.enemies), minimum)

    def test_far_enemy_is_removed(self):
        world = make_world(waves=False)
        far = world.data["spawning"]["despawn_radius"] + 50
        add_enemy_at(world, "bat", far, 0.0)
        add_enemy_at(world, "bat", 100.0, 0.0)
        tick(world, STEP)
        self.assertEqual(len(world.enemies), 1)

    def test_wave_table_selects_the_right_types_and_minimum(self):
        world = make_world()  # no ticks: this only reads the table
        table = world.data["spawning"]["waves"]
        for at, types, minimum in ((0, ["bat"], 12), (46, ["slime", "ghost"], 36),
                                   (75, ["bat", "slime", "ghost"], 55),
                                   (105, ["bat"], 75)):
            world.time = at
            wave = world._wave()
            self.assertEqual(wave["types"], types)
            self.assertEqual(wave["min_alive"], minimum)
        self.assertEqual(len(table), 8)  # the whole table from GAME.md is loaded

    def test_ghost_is_faster_than_the_hero(self):
        world = make_world(waves=False)
        self.assertGreater(world.data["enemies"]["ghost"]["speed"],
                           world.data["hero"]["speed"])


class Boss(unittest.TestCase):
    def test_boss_spawns_once_at_130(self):
        world = make_world(waves=False)
        tick(world, 89.0)
        self.assertEqual([e for e in world.enemies if e["type"] == "demon"], [])
        tick(world, 2.0)
        demons = [e for e in world.enemies if e["type"] == "demon"]
        self.assertEqual(len(demons), 1)
        tick(world, 10.0)
        self.assertEqual(len([e for e in world.enemies if e["type"] == "demon"]), 1)

    def test_boss_is_never_removed_but_jumps_back(self):
        world = make_world(waves=False)
        demon = add_enemy_at(world, "demon", 5000.0, 0.0)
        tick(world, STEP)
        self.assertIn(demon, world.enemies)
        d = math.hypot(demon["x"] - world.hero["x"], demon["y"] - world.hero["y"])
        self.assertAlmostEqual(d, world.data["spawning"]["spawn_radius"], places=6)

    def test_boss_drops_no_gem(self):
        world = make_world(waves=False)
        demon = add_enemy_at(world, "demon", 100.0, 0.0)
        world._damage_enemy(demon, 800)
        self.assertEqual(world.kills, 1)
        self.assertEqual(world.gems, [])


class ContactDamage(unittest.TestCase):
    def test_hero_is_hurt_once_per_rehit_interval(self):
        world = make_world(waves=False)
        add_enemy_at(world, "bat", world.hero["x"], world.hero["y"], hp=999)
        dmg = world.data["enemies"]["bat"]["damage"]
        interval = world.data["contact"]["rehit_interval"]
        tick(world, interval - STEP)
        self.assertEqual(world.hero["hp"], world.data["hero"]["max_hp"] - dmg)
        tick(world, interval)
        self.assertEqual(world.hero["hp"], world.data["hero"]["max_hp"] - 2 * dmg)

    def test_slime_hurts_harder_than_bat(self):
        world = make_world(waves=False)
        add_enemy_at(world, "slime", 0.0, 0.0, hp=999)
        tick(world, STEP)
        self.assertEqual(world.hero["hp"],
                         world.data["hero"]["max_hp"] - world.data["enemies"]["slime"]["damage"])


class SparkWand(unittest.TestCase):
    def test_sparks_kill_an_enemy(self):
        world = make_world(waves=False)
        add_enemy_at(world, "bat", 100.0, 0.0, hp=world.data["enemies"]["bat"]["hp"])
        tick(world, world.data["spark_wand"]["interval"] + 0.5)
        self.assertEqual(world.enemies, [])
        self.assertEqual(world.kills, 1)

    def test_wand_does_not_shoot_without_enemies(self):
        world = make_world(waves=False)
        tick(world, 2.0)
        self.assertEqual(world.sparks, [])

    def test_higher_level_wand_shoots_more_sparks(self):
        world = make_world(waves=False)
        world.weapons["spark_wand"] = 5  # +1 spark at levels 3 and 5 -> 3 sparks
        for x in (80.0, 160.0, 240.0):
            add_enemy_at(world, "bat", x, 0.0, hp=999)
        w = world.data["spark_wand"]
        world._wand_timer = w["interval"] - w["interval_minus_per_level"] * 4 - STEP
        tick(world, STEP)
        self.assertEqual(len(world.sparks), 3)


class SpinBladesAndRing(unittest.TestCase):
    def test_blades_hit_each_enemy_at_most_once_per_half_second(self):
        world = make_world(waves=False)
        world.weapons["spin_blades"] = 1
        e = add_enemy_at(world, "bat", 60.0, 0.0, hp=999)
        tick(world, 0.1)  # a blade sweeps through the enemy
        self.assertLess(e["hp"], 999)
        hp_after = e["hp"]
        tick(world, 0.4)  # less than the 0.5 s re-hit interval
        self.assertEqual(e["hp"], hp_after)

    def test_ring_hurts_every_enemy_inside_its_radius(self):
        world = make_world(waves=False)
        world.weapons["holy_ring"] = 1
        ring = world.data["holy_ring"]
        inside = add_enemy_at(world, "bat", ring["radius"] - 5, 0.0, hp=999)
        outside = add_enemy_at(world, "bat", ring["radius"] + 120, 0.0, hp=999)
        tick(world, ring["interval"] + STEP)
        self.assertEqual(inside["hp"], 999 - ring["damage"])
        self.assertEqual(outside["hp"], 999)


class GemsXpAndLevels(unittest.TestCase):
    def test_dead_enemy_drops_a_gem_that_gives_xp(self):
        world = make_world(waves=False)
        add_enemy_at(world, "bat", 30.0, 0.0)  # inside the magnet radius
        tick(world, world.data["spark_wand"]["interval"] + 0.5)
        self.assertEqual(world.kills, 1)
        self.assertGreaterEqual(world.xp, world.data["enemies"]["bat"]["xp"])
        self.assertEqual(world.gems, [])

    def test_level_up_at_the_xp_threshold(self):
        world = make_world(waves=False)
        need = world.xp_need()
        self.assertEqual(need, world.data["xp"]["first_level_need"])
        world._add_xp(need - 1)
        self.assertEqual(world.level, 1)
        world._add_xp(1)
        self.assertEqual(world.level, 2)
        self.assertEqual(world.pending_levelups, 1)
        self.assertEqual(world.xp_need(), need + world.data["xp"]["level_need_increment"])

    def test_tick_is_frozen_while_a_card_choice_is_pending(self):
        world = make_world(waves=False)
        world._add_xp(world.xp_need())
        before = world.time
        tick(world, 1.0)
        self.assertEqual(world.time, before)

    def test_offer_cards_respects_the_rules(self):
        world = make_world(waves=False)
        cards = world.offer_cards()
        self.assertEqual(len(cards), 3)
        self.assertEqual(len({c["key"] for c in cards}), 3)  # no duplicates
        for c in cards:
            self.assertLessEqual(c["level"], 5)
        world.weapons = {k: 5 for k in WEAPONS}
        world.passives = {k: 5 for k in PASSIVES}
        cards = world.offer_cards()
        self.assertEqual(cards, [{"key": "heal", "kind": "heal", "level": 1}])

    def test_no_third_weapon_offered_when_three_are_owned(self):
        world = make_world(waves=False)
        world.weapons = {"spark_wand": 1, "spin_blades": 1, "holy_ring": 1}
        for _ in range(20):  # random offers must never contain a new weapon
            for c in world.offer_cards():
                if c["kind"] == "weapon":
                    self.assertIn(c["key"], world.weapons)
                    self.assertGreater(c["level"], 1)

    def test_big_heart_and_boots_effects(self):
        world = make_world(waves=False)
        world.take_card({"key": "big_heart", "kind": "passive", "level": 1})
        self.assertEqual(world.hero["max_hp"], 120)
        self.assertEqual(world.hero["hp"], 120)  # heal 20 but capped at max
        world.take_card({"key": "swift_boots", "kind": "passive", "level": 2})
        self.assertAlmostEqual(world.hero_speed(),
                               world.data["hero"]["speed"] * 1.2, places=6)


class Events(unittest.TestCase):
    def test_hit_and_kill_events(self):
        world = make_world(waves=False)
        add_enemy_at(world, "bat", 100.0, 0.0)
        tick(world, world.data["spark_wand"]["interval"] + 0.5)
        events = world.drain_events()
        kinds = [ev["type"] for ev in events]
        self.assertIn("hit", kinds)
        self.assertEqual(kinds.count("kill"), 1)
        self.assertEqual(world.events, [])  # drain clears the list

    def test_hurt_event_when_touching_an_enemy(self):
        world = make_world(waves=False)
        add_enemy_at(world, "bat", 0.0, 0.0, hp=999)
        tick(world, STEP)
        hurt = [ev for ev in world.drain_events() if ev["type"] == "hurt"]
        self.assertEqual(len(hurt), 1)
        self.assertEqual(hurt[0]["amount"], world.data["enemies"]["bat"]["damage"])

    def test_gem_levelup_and_end_events(self):
        world = make_world(waves=False)
        add_enemy_at(world, "bat", 30.0, 0.0)
        tick(world, world.data["spark_wand"]["interval"] + 0.5)
        kinds = [ev["type"] for ev in world.drain_events()]
        self.assertIn("gem", kinds)
        world._add_xp(world.xp_need())
        self.assertIn("levelup", [ev["type"] for ev in world.drain_events()])
        world.hero["hp"] = 1
        add_enemy_at(world, "bat", 0.0, 0.0, hp=999)
        world.pending_levelups = 0
        tick(world, STEP)
        end = [ev for ev in world.drain_events() if ev["type"] == "end"]
        self.assertEqual(end, [{"type": "end", "victory": False}])


class WinAndLose(unittest.TestCase):
    def test_hp_reaching_zero_ends_the_game(self):
        world = make_world(waves=False)
        world.hero["hp"] = world.data["enemies"]["bat"]["damage"]
        add_enemy_at(world, "bat", 0.0, 0.0, hp=999)
        tick(world, STEP)
        self.assertTrue(world.game_over)
        self.assertEqual(world.hero["hp"], 0)

    def test_surviving_to_200_wins(self):
        world = make_world(waves=False, boss=False)
        world.weapons = {}  # no fighting, just wait out the clock
        tick(world, 121.0)  # a little past the goal line
        self.assertTrue(world.victory)
        self.assertFalse(world.game_over)
        self.assertIn({"type": "end", "victory": True}, world.drain_events())
        frozen = world.time
        tick(world, 1.0)  # the world stays frozen after the win
        self.assertEqual(world.time, frozen)

    def test_reset_after_the_end(self):
        world = make_world(waves=False)
        world.hero["hp"] = 0
        world.game_over = True
        add_enemy_at(world, "demon", 1.0, 1.0)
        world.reset()
        self.assertFalse(world.game_over)
        self.assertFalse(world.victory)
        self.assertEqual(world.hero["hp"], world.data["hero"]["max_hp"])
        self.assertEqual(world.enemies, [])
        self.assertEqual(world.gems, [])
        self.assertEqual(world.level, 1)
        self.assertEqual(world.weapons, {"spark_wand": 1})
        self.assertEqual(world.time, 0.0)


if __name__ == "__main__":
    unittest.main()
