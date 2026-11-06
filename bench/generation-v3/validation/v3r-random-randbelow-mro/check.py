"""Behavioural check for v3r-random-randbelow-mro.

Pre-fix behaviour: the choice between the getrandbits-based and
the random()-based integer generator was made by comparing the
subclass's attributes by identity against the base implementation,
which misjudged overrides that were inherited from an intermediate
class or supplied by a mixin: a subclass that overrode random()
but inherited a getrandbits() override (or the mirror image,
depending on mixin order) was wired to the wrong primitive.
"""

import importlib.util
import pathlib

spec = importlib.util.spec_from_file_location(
    "randcore", pathlib.Path("app/randcore.py"))
randcore = importlib.util.module_from_spec(spec)
spec.loader.exec_module(randcore)

WITH = randcore.RandomCore.__dict__["_randbelow_with_getrandbits"]
WITHOUT = randcore.RandomCore.__dict__["_randbelow_without_getrandbits"]


class RandomOnly(randcore.RandomCore):
    """Supplies only random(); getrandbits stays unimplemented."""

    def __init__(self):
        self.calls = 0

    def random(self):
        self.calls += 1
        return 0.5


class BitsOnly(randcore.RandomCore):
    """Supplies only getrandbits()."""

    def __init__(self):
        self.calls = 0

    def getrandbits(self, k):
        self.calls += 1
        return 0


# Direct overrides select the matching primitive.
assert RandomOnly.__dict__["_randbelow"] is WITHOUT
assert BitsOnly.__dict__["_randbelow"] is WITH
r = RandomOnly()
assert r.randrange(10) == 6 and r.calls >= 1  # int(0.5 * 2**53) % 10
b = BitsOnly()
assert b.randrange(10) == 0 and b.calls >= 1


class BitsBase(randcore.RandomCore):
    def getrandbits(self, k):
        return 0


class OverridesRandom(BitsBase):
    """random() defined here is nearer in the MRO than the
    getrandbits() inherited from BitsBase, so it must win."""

    def random(self):
        return 0.5


assert OverridesRandom.__dict__["_randbelow"] is WITHOUT
assert OverridesRandom().randrange(10) == 6


class MixinRandom:
    def random(self):
        return 0.5


class MixinBits:
    def getrandbits(self, k):
        return 0


class SubRandomFirst(MixinRandom, MixinBits, randcore.RandomCore):
    pass


class SubBitsFirst(MixinBits, MixinRandom, randcore.RandomCore):
    pass


# Mixin order decides: the first primitive in the MRO wins.
assert SubRandomFirst.__dict__["_randbelow"] is WITHOUT
assert SubBitsFirst.__dict__["_randbelow"] is WITH


class Custom(randcore.RandomCore):
    """A subclass defining _randbelow keeps its own version."""

    def _randbelow(self, n):
        return 42


assert Custom().randrange(10) == 42

# A subclass overriding nothing inherits the default implementation.
class Plain(randcore.RandomCore):
    pass


assert "_randbelow" not in Plain.__dict__
assert Plain.__dict__.get("_randbelow", WITH) is WITH

print("v3r-random-randbelow-mro: OK")
