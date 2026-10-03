# Runs INSIDE the kvm-board-tools container — use ./build.sh from the host
# (it also runs the autorouter, which needs a separate Java container).
#   make pcb        netlist + ERC + placed, unrouted PCB
#   make outputs    DRC, renders, JLCPCB files and impedance check for the current PCB
#   make parts      re-import LCSC symbols/footprints/3D models

LCSC := C544517 C7501849 C7501850 C138388 C138714 C165948 C318884 C7429571 C55266 C273616 C125115 C571338 C5378721 C128396
GERBER_LAYERS := F.Cu,In1.Cu,In2.Cu,B.Cu,F.Paste,B.Paste,F.Silkscreen,B.Silkscreen,F.Mask,B.Mask,Edge.Cuts
PCB := out/kvm_board.kicad_pcb

.PHONY: pcb outputs silk drc render fab impedance review parts jlcref clean

pcb:
	mkdir -p out/img out/jlcpcb/gerbers
	cd hw && python3 kvm_board.py 2>&1 | grep -E "^ERC|errors found|parts written"; \
	  rm -f kvm_board.log kvm_board_sklib.py; mv -f kvm_board.erc ../out/
	cd out && python3 ../hw/make_pcb.py 2>&1 | grep -v -i warning

# the targets below work on whatever $(PCB) currently holds (routed or not)
outputs: silk fab render drc impedance review

review:
	python3 hw/review.py

silk:
	python3 hw/make_pcb.py silk || echo "silk refresh skipped (board keeps its labels)"

impedance:
	cd hw && python3 impedance.py | tee ../out/impedance.txt

drc:
	timeout -k 10 300 kicad-cli pcb drc --format report --severity-all -o out/drc.rpt $(PCB) | tail -2
	timeout -k 10 300 kicad-cli pcb drc --format report --severity-all -o out/drc_panel.rpt $(PANEL) | tail -1

render:
	python3 hw/make_pcb.py models || echo "model refresh skipped (board keeps its models)"
	timeout -k 10 300 kicad-cli pcb render --width 1600 --height 1100 --side top --quality basic -o out/img/top.png $(PCB) >/dev/null
	timeout -k 10 300 kicad-cli pcb render --width 1600 --height 1100 --side bottom --quality basic -o out/img/bottom.png $(PCB) >/dev/null
	timeout -k 10 300 kicad-cli pcb render --width 1600 --height 1100 --rotate 315,0,30 --perspective --floor --quality basic -o out/img/iso.png $(PCB) >/dev/null

# Gerbers/drill come from the panel (board + JLC edge rails, hw/panel.py);
# BOM/CPL from the board, whose coordinates the panel keeps.
PANEL := out/kvm_board_panel.kicad_pcb

fab:
	mkdir -p out/jlcpcb/gerbers
	rm -f out/jlcpcb/gerbers/*
	python3 hw/panel.py
	cp out/kvm_board.kicad_pro out/kvm_board_panel.kicad_pro
	cp out/kvm_board.kicad_dru out/kvm_board_panel.kicad_dru
	kicad-cli pcb export gerbers --layers $(GERBER_LAYERS) -o out/jlcpcb/gerbers/ $(PANEL) >/dev/null
	kicad-cli pcb export drill --format excellon --excellon-units mm --excellon-separate-th -o out/jlcpcb/gerbers/ $(PANEL) >/dev/null
	python3 hw/make_fab.py
	cd out/jlcpcb && rm -f gerbers.zip && cd gerbers && zip -q ../gerbers.zip *

parts:
	cd hw/lib && easyeda2kicad --full --lcsc_id $(LCSC) --output /work/hw/lib/lcsc --project-relative --overwrite

# JLC's own footprints for every BOM part (for CPL alignment in make_fab.py)
jlcref:
	python3 hw/jlcref.py

clean:
	rm -rf out
