SCAD ?= /Applications/OpenSCAD.app/Contents/MacOS/OpenSCAD
OUT  := out
BIN  := $(OUT)/spool_holder_3x4x7.stl
CPN  := $(OUT)/coupon_1x1.stl
SRC  := spool_holder.scad gridfinity.scad

.PHONY: all bin coupon validate clean

all: validate coupon

bin: $(BIN)
coupon: $(CPN)

$(OUT):
	mkdir -p $(OUT)

$(BIN): $(SRC) | $(OUT)
	$(SCAD) -o $@ -D 'PART="bin"' spool_holder.scad

$(CPN): $(SRC) | $(OUT)
	$(SCAD) -o $@ -D 'PART="coupon"' spool_holder.scad

validate: $(BIN)
	python3 validate.py $(BIN)

clean:
	rm -rf $(OUT)
