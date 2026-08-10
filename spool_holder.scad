// Gridfinity sewing thread spool holder.
//
// Derived from "2 large efficient Sewing Thread Spool Holder", whose peg
// geometry was measured directly off its STLs: 23 pegs, dia 6.0, 38mm proud
// of a 2mm plate, with a lead-in chamfer at the tip, on a lattice whose
// closest center-to-center distance is 24.68mm.
//
// That 24.68 is the real constraint -- it is the widest a spool flange can
// be. The original lattice also spaced in-row neighbours 37.5mm apart, which
// is pure slack, so this version re-packs the same spacing as a true hex
// grid. Same clearances, more spools.

include <gridfinity.scad>

/* [Grid] */
GRID_X       = 3;      // cells in X
GRID_Y       = 4;      // cells in Y
GRID_Z       = 7;      // height units (7mm each)
STACKING_LIP = true;   // false matches the rest of the library, but won't stack

/* [Shell] */
WALL         = 1.6;    // side wall thickness
FLOOR        = 1.25;   // floor above the top of the gridfinity base

/* [Spools] */
SPOOL_DIA    = 24.68;  // widest spool flange = min peg center distance
PEG_DIA      = 6.0;    // spool bore is ~6.3
PEG_H        = 38.0;   // proud of the floor
PEG_CHAMFER  = 0.75;   // lead-in at the tip

/* [Output] */
PART         = "bin";  // "bin" or "coupon"

$fa = 1;
$fs = 0.4;

// ---------------------------------------------------------------------------
// Peg lattice
//
// Columns run along Y so the long axis of the bin gets the tighter spacing.
// For a 3x4 that packs 30 pegs; running them the other way packs only 28.
// ---------------------------------------------------------------------------

function col_spacing() = SPOOL_DIA * sqrt(3) / 2;

// Usable span for peg *centers*: interior minus half a spool at each edge.
function span_x(gx) = gf_outer(gx) - 2*WALL - SPOOL_DIA;
function span_y(gy) = gf_outer(gy) - 2*WALL - SPOOL_DIA;

function n_cols(gx) = floor(span_x(gx) / col_spacing()) + 1;
function col_offset(j) = (j % 2 == 1) ? SPOOL_DIA/2 : 0;
function n_in_col(gy, j) = floor((span_y(gy) - col_offset(j)) / SPOOL_DIA) + 1;

function peg_grid(gx, gy) = [
    for (j = [0 : n_cols(gx) - 1], i = [0 : n_in_col(gy, j) - 1])
        [ j * col_spacing(), col_offset(j) + i * SPOOL_DIA ]
];

// Center the generated pattern in the interior rather than assuming it is
// symmetric -- offset columns end at a different Y than even ones.
function grid_extent(pts, axis) =
    max([for (p = pts) p[axis]]) - min([for (p = pts) p[axis]]);

module peg() {
    straight = PEG_H - PEG_CHAMFER;
    cylinder(h = straight, d = PEG_DIA);
    translate([0, 0, straight])
        cylinder(h = PEG_CHAMFER, d1 = PEG_DIA, d2 = PEG_DIA - 2*PEG_CHAMFER);
}

module peg_field(gx, gy) {
    pts = peg_grid(gx, gy);
    ox = -grid_extent(pts, 0) / 2;
    oy = -grid_extent(pts, 1) / 2;
    for (p = pts) translate([p[0] + ox, p[1] + oy, 0]) peg();
}

// ---------------------------------------------------------------------------
// Assembly
// ---------------------------------------------------------------------------

module spool_bin(gx, gy, zu) {
    union() {
        gf_bin(gx, gy, zu, WALL, FLOOR, STACKING_LIP);
        translate([0, 0, GF_BASE_H + FLOOR]) peg_field(gx, gy);
    }
}

// A 1x1 test print: checks baseplate fit, lip fit and spool fit for the cost
// of a few minutes, before committing to the full bin.
module coupon() {
    union() {
        gf_bin(1, 1, 6, WALL, FLOOR, STACKING_LIP);
        translate([0, 0, GF_BASE_H + FLOOR]) peg();
    }
}

if (PART == "coupon") coupon();
else spool_bin(GRID_X, GRID_Y, GRID_Z);

echo(str("pegs = ", len(peg_grid(GRID_X, GRID_Y))));
echo(str("outer = ", gf_outer(GRID_X), " x ", gf_outer(GRID_Y),
         " x ", gf_height(GRID_Z, STACKING_LIP)));
