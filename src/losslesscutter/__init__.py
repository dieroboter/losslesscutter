"""LosslessCutter: VRD-style cutting GUI over the smartcut engine (MIT fork).

Lossless here means smart cutting: everything between cut points is copied
bit-identical; only the small segments at cut points are re-encoded, at the
quality the user picks (default: matched to the source).
"""

__version__ = "1.4.1"
