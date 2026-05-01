## FFI surface for modulabot Python perception.
##
## Builds to a shared library loaded by
## :mod:`modulabot.nim_perception` on Python side. Pure stateless
## kernels only; every buffer is caller-allocated, owned by the
## NumPy array it came from.
##
## The kernels themselves live in ``among_them/common/perception_kernels/``
## so guided_bot can import them too without reaching into modulabot's
## tree (see ``among_them/common/README.md``). ``build.py`` resolves
## that directory via ``--path:``; the bare ``import sprite_match``
## etc. below pick the kernels up from there.
##
## ``lib.nim`` (this file) is modulabot-specific: it adds the
## ``mb_*`` ``{.exportc, dynlib.}`` ABI on top of the shared kernels
## and stamps the ABI version. Other agents that want their own FFI
## surface define their own equivalent of this file.
##
## Phase 0 (base): ABI version stamp.
## Phase 1: sprite-matching kernels.
## Later phases add camera scoring, patch hashing, ignore-mask
## computation, task-icon / radar scanners, and OCR primitives —
## each behind its own ``mb_*`` symbol and with a Python fallback
## in the matching ``modulabot/*.py`` module.
##
## Symbol prefix is ``mb_*`` (for "modulabot"). The Python wrapper
## checks :proc:`mb_abi_version` against
## :data:`modulabot.nim_perception.ABI_VERSION` and refuses to
## load a mismatched library. Bump it every time the FFI surface
## changes (new symbol, arg reorder, semantic change).

# Shared kernels — re-exported via their own ``{.exportc, dynlib.}``
# pragmas inside each module. Importing here is what makes the
# ``mb_*`` symbols appear in the built library.
import sprite_match
export sprite_match
import localize
export localize
import actors
export actors
import ocr
export ocr

const ModulabotPerceptionAbiVersion* = 6
  ## Bumped whenever the FFI surface changes. Keep in sync with
  ## ``modulabot/nim_perception/__init__.py::ABI_VERSION`` and with
  ## ``modulabot/nim_perception/build.py::ABI_VERSION``.

proc mb_abi_version*(): cint {.exportc, dynlib.} =
  ## Returns the ABI version number expected by the Python wrapper.
  cint(ModulabotPerceptionAbiVersion)
