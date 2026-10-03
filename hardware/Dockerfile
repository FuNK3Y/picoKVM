# KiCad 10 toolchain.  Versions are pinned so a rebuild gives the same board;
# bump them deliberately.  The -full image includes KiCad's 3D models.
FROM kicad/kicad:10.0.6-full

USER root
RUN apt-get update \
 && apt-get install -y --no-install-recommends python3-pip make zip \
 && rm -rf /var/lib/apt/lists/*
RUN pip3 install --break-system-packages --no-cache-dir \
    skidl==2.3.0 easyeda2kicad==1.0.1 numpy==2.5.3 scipy==1.18.1

ENV KICAD10_SYMBOL_DIR=/usr/share/kicad/symbols \
    KICAD10_FOOTPRINT_DIR=/usr/share/kicad/footprints \
    KICAD_SYMBOL_DIR=/usr/share/kicad/symbols

USER kicad
WORKDIR /work
