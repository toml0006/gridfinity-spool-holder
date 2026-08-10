# Gridfinity sewing thread spool holder

A stackable gridfinity bin with a hex-packed field of spool pegs.
3x4 cells, 7 height units, 30 spools.

```
make            # build the bin, validate it, build the test coupon
make bin        # out/spool_holder_3x4x7.stl
make coupon     # out/coupon_1x1.stl -- print this first
make validate   # measure the export against the spec
```

| | |
|---|---|
| Footprint | 125.5 x 167.5 mm (3 x 4 cells) |
| Height | 53.4 mm (7 units + 4.4 lip) |
| Stack pitch | 49.00 mm, exactly 7 per unit |
| Spools | 30 |
| Peg | dia 6.0, 38 mm proud of the floor, 0.75 chamfer |
| Modelled volume | 183 cm3 |

## Print the coupon first

`out/coupon_1x1.stl` is a 1x1 bin with a single peg, about ten minutes of
printing. It checks the three things that would otherwise waste a six hour
print: that the base seats in your baseplate, that the lip accepts another
bin, and that your spools actually fit the peg and the 24.68 mm spacing.

The lip is the one dimension not measured from a known-good local part --
see below -- so it is the thing most worth checking on a coupon.

## Where the numbers came from

Nothing here is recalled from memory. The base profile was measured off
`~/Documents/TomlinsonLTD/MakerWorld/Gridfinity/Calipers.3mf`, a bin known to
fit, by slicing it and fitting the geometry:

| Constant | Measured | How |
|---|---|---|
| Grid pitch | 42.0 | footprint / cell count |
| Outer footprint | 42n - 0.5 | 83.5 at 2 cells, 125.5 at 3 |
| Bottom inset | 3.20 / side | bottom span 77.60 at 2 cells |
| Chamfer angle | 45 deg | width grew 1.996 mm per mm |
| Base height | 4.75 | 0.8 + 1.8 + 2.15 |
| Corner radius | 3.75 top, 0.80 bottom | circle fit, error 0.0000 |
| Height convention | 7u + 3.8 lipless | 24.8 / 31.8 / 38.8 across 10 bins |

Cross-checked against `kennetek/gridfinity-rebuilt-openscad`, which agrees on
every one. Its `BASE_PROFILE_HEIGHT` reads 4.95, but its own segment lengths
(0.8 + 1.8 + 2.15) sum to 4.75 and the measured part is 4.75, so 4.75 is used.

### The lip is the unverified part

All ten local bins are lipless -- their outer wall runs dead straight from
the top of the base to the rim, so they seat in a baseplate but do not stack.
That left no local part to measure a stacking lip from, so the lip profile
(0.7 / 1.8 / 1.9, 4.4 tall) comes from the reference implementation only.

The rim inset is *derived* rather than taken: the bin above sinks until its
base flare jams against the rim, and that sink depth is the stack pitch.
Solving for a sink of exactly 4.4 gives a rim inset of 0.35, which puts the
pitch at exactly 49.00 mm for a 7 unit bin. `validate.py` recomputes this
from the exported mesh rather than trusting the constant.

## Peg layout

Derived from "2 large efficient Sewing Thread Spool Holder", measured off its
STLs: 23 pegs, dia 6.0, 38 mm proud of a 2 mm plate, chamfered tips, on a
lattice whose closest centre distance is 24.68 mm.

That 24.68 is the real constraint -- it is the widest a spool flange can be.
The original also spaced in-row neighbours 37.5 mm apart, which nothing
requires, so it spends 642 mm2 per spool where a true hex pack at the same
24.68 spacing spends 528. This model re-packs it properly: same clearances,
same spool compatibility, 30 spools instead of the 27 the original lattice
would tile into this footprint.

Columns run along Y. Running them the other way packs only 28.

## Known tradeoffs

- The base feet are modelled solid. Real gridfinity libraries hollow them to
  save material; here the slicer's infill does that job. If you want the
  filament back, hollowing the feet is the place to look.
- Wall is 1.6 mm, thicker than the 0.95 the reference uses, because the peg
  field puts spool loads on the walls.
- No label tab, no scoop. The pegs need the floor area more.

## Files

- `gridfinity.scad` -- base profile, stacking lip, bin shell. No spool logic,
  reusable for the next bin.
- `spool_holder.scad` -- peg lattice and assembly. Parameters at the top.
- `validate.py` -- measures an exported STL against the spec. 33 checks.
