"""Local media pipeline — FFmpeg-based assembly, captions, and command construction.

ARCHITECTURE §3, §12. This package is the "Media Pipeline" layer, distinct
from the Provider Interfaces layer: FFmpeg is fixed, chosen tooling (not a
swappable provider), so nothing here uses the Protocol-based provider
pattern used in ``providers/``.
"""
