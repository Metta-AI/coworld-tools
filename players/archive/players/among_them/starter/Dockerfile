# Among Them ivotewell starter player image.
#
# Built via this leaf's ``build.sh`` from a BitWorld monorepo checkout (the
# Nim source imports ``../../sim``, ``../../texts``, ``../../votereader`` and
# ``../../../common/server`` which live in BitWorld, not here). The script
# resolves a BITWORLD_ROOT and uses ``docker buildx --build-context`` to
# overlay this repo's ``ivotewell.nim`` so the image always contains the
# freshest in-repo player source.

FROM alpine AS build

RUN apk add --no-cache build-base curl gcompat git

RUN if [ "$(apk --print-arch)" = "x86_64" ]; then \
      curl -fsSL \
        -o /usr/local/bin/nimby \
        https://github.com/treeform/nimby/releases/download/0.1.26/nimby-Linux-X64; \
    elif [ "$(apk --print-arch)" = "aarch64" ]; then \
      curl -fsSL \
        -o /usr/local/bin/nimby \
        https://github.com/treeform/nimby/releases/download/0.1.26/nimby-Linux-ARM64; \
    else \
      echo "unsupported arch: $(apk --print-arch)" && exit 1; \
    fi && \
    chmod +x /usr/local/bin/nimby && \
    nimby use 2.2.4

ENV PATH="/root/.nimby/nim/bin:$PATH"

WORKDIR /workspace/bitworld
COPY nimby.lock .
RUN nimby --global sync nimby.lock && \
    cat nim.cfg >> /root/.nimby/nim/config/nim.cfg

# 1. Copy the full BitWorld framework from the primary build context.
COPY . .
# 2. Overlay the in-repo ivotewell.nim so the image carries the freshest
#    player source from this players repo, not whatever BitWorld currently
#    has on disk.
COPY --from=player ivotewell.nim among_them/players/ivotewell/ivotewell.nim

WORKDIR /workspace/bitworld/among_them/players/ivotewell
RUN nim c \
      -d:release \
      -d:botHeadless \
      --nimcache:/tmp/bitworld-nimcache \
      --out:ivotewell \
      ivotewell.nim

FROM alpine

WORKDIR /workspace/bitworld
COPY --from=build \
  /workspace/bitworld/among_them/players/ivotewell/ivotewell \
  /bin/ivotewell
COPY --from=build /workspace/bitworld/among_them/*.json ./among_them/
COPY --from=build /workspace/bitworld/among_them/*.aseprite ./among_them/
COPY --from=build /workspace/bitworld/among_them/*.png ./among_them/
COPY --from=build /workspace/bitworld/clients/data ./clients/data

WORKDIR /workspace/bitworld/among_them/players

# The ivotewell binary reads COWORLD_PLAYER_WS_URL from the environment when
# set (see ``ivotewell.nim``'s ``main``). The Coworld runner injects that
# variable into the container at episode start. No CLI flags are needed.
CMD ["/bin/ivotewell"]
