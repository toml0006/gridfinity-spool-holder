/*
 * Gridfinity sewing thread spool holder -- parametric.
 *
 * A stackable gridfinity bin whose floor is a hex packed field of pegs, one
 * spool per peg. Set the footprint in gridfinity units and the spacing to
 * suit your spools; the peg field re-packs and re-centres itself.
 *
 * Single file on purpose: MakerWorld's Parametric Model Maker runs one
 * script, so there are no include<> statements to resolve.
 *
 * Every gridfinity constant here was measured off a bin known to fit rather
 * than recalled. Source and validator:
 * https://github.com/toml0006/gridfinity-spool-holder
 */

/* [Bin size] */

// Width, in gridfinity units of 42mm. 6 units is 251.5mm, about as much as a 256mm bed takes
grid_x = 3;         // [1:6]
// Depth, in gridfinity units of 42mm
grid_y = 4;         // [1:6]
// Height, in units of 7mm. Below 7 a 38mm peg stands proud of the rim and the bin stops stacking
grid_z = 7;         // [3:20]
// Stacking lip. Turn off to match a lipless library: still seats in a baseplate, but will not stack
stacking_lip = true;

/* [Spools] */

// Centre to centre spacing. This is the widest spool flange that will fit
spool_spacing = 24.68;  // [15:0.01:60]
// Peg diameter. Typical spool bore is about 6.3mm
peg_dia = 6;        // [3:0.1:12]
// How far the peg stands above the floor
peg_height = 38;    // [10:1:80]

/* [Shell] */

// Side wall thickness
wall = 1.6;         // [0.8:0.1:4]
// Floor above the top of the gridfinity base
floor_thickness = 1.25;  // [0.8:0.05:4]

/* [Quality] */

// Facets per full circle. Raise for a smoother finish, lower if generating times out
detail = 20;        // [12:4:48]

/* [Hidden] */

// --------------------------------------------------------------------------
// Gridfinity constants. Measured, not tuned.
//
//   pitch 42, outer footprint 42n - 0.5, corner radius 3.75 at the top of the
//   base falling to 0.80 at the bottom face, base profile 0.8 chamfer / 1.8
//   straight / 2.15 chamfer = 4.75 tall, both chamfers at 45 degrees.
// --------------------------------------------------------------------------

PITCH      = 42;
GAP        = 0.5;
TOP_INSET  = GAP / 2;                       // 0.25
R_TOP      = 3.75;

BASE_C1    = 0.8;                           // lower 45 deg chamfer
BASE_STR   = 1.8;                           // vertical section
BASE_C2    = 2.15;                          // upper 45 deg chamfer
BASE_H     = BASE_C1 + BASE_STR + BASE_C2;  // 4.75
BOT_INSET  = TOP_INSET + BASE_C1 + BASE_C2; // 3.20

UNIT_Z     = 7;
Z_LIPLESS  = 3.8;

// Stacking lip: a funnel that opens towards the rim. Widest at the top so the
// feet of the bin above drop in, narrowing to an inward ledge at the bottom
// which is what takes the load. Built the other way up, the wall cavity just
// swallows it and there is no lip at all.
LIP_C1     = 0.7;                           // throat inset, and the rim chamfer
LIP_STR    = 1.8;                           // vertical throat
LIP_C2     = 1.9;                           // 45 deg down to the ledge
LIP_H      = LIP_C1 + LIP_STR + LIP_C2;     // 4.40
LIP_W      = LIP_C1 + LIP_C2;               // 2.60, ledge inset

PEG_CHAMFER = 0.75;                         // lead-in at the peg tip
EPS         = 0.01;

// Sections of the base and the lip meet on exact planes. Solids that only
// touch on a coincident face are not reliably fused, and the result is a
// shell that measures correctly but is not watertight, so it will not slice.
// Straight sections are grown by this much into their neighbours to give the
// union real volume to work with. It is below one print layer.
OVER = 0.01;

// Inset per side of a base, t mm above its underside.
function base_inset(t) =
      t <= BASE_C1             ? BOT_INSET - t
    : t <= BASE_C1 + BASE_STR  ? BOT_INSET - BASE_C1
    : max(TOP_INSET, BOT_INSET - BASE_C1 - (t - BASE_C1 - BASE_STR));

// The bin above sinks until its base flare jams on the rim, and that depth is
// the stack pitch. Seating at exactly LIP_H makes the pitch exactly UNIT_Z per
// height unit, which is what keeps a tall stack on the grid.
LIP_TIP = base_inset(LIP_H) - TOP_INSET;    // 0.35

function outer(n)  = PITCH * n - GAP;
function radius_for(inset) = max(0.01, R_TOP - (inset - TOP_INSET));
function total_height() = UNIT_Z * grid_z + (stacking_lip ? LIP_H : Z_LIPLESS);

// --------------------------------------------------------------------------
// Primitives
//
// Rounded boxes are built as a hull of four cylinders rather than
// offset() on a square. Both are exact, but offset() is a 2D minkowski and
// costs far more; on a 3x4 bin the cylinder form renders many times faster,
// which matters when the generator has a wall-clock budget.
// --------------------------------------------------------------------------

module rbox(sx, sy, r, h) {
    rr = max(0.01, min(r, min(sx, sy) / 2 - 0.001));
    hull()
        for (dx = [-1, 1], dy = [-1, 1])
            translate([dx * (sx / 2 - rr), dy * (sy / 2 - rr), 0])
                cylinder(h = max(h, EPS), r = rr, $fn = detail);
}

// Rounded box described by its inset from a footprint, so the corner radius
// stays consistent with the base profile.
module rbox_inset(fx, fy, inset, h) {
    rbox(fx - 2 * inset, fy - 2 * inset, radius_for(inset), h);
}

// A 45 degree run between two insets, as a single hull of eight cylinders.
module taper(fx, fy, z0, inset0, z1, inset1) {
    hull() {
        translate([0, 0, z0]) rbox_inset(fx, fy, inset0, EPS);
        translate([0, 0, z1 - EPS]) rbox_inset(fx, fy, inset1, EPS);
    }
}

// --------------------------------------------------------------------------
// Base
// --------------------------------------------------------------------------

// One foot, occupying a single 42mm cell.
module foot() {
    taper(PITCH, PITCH, 0, BOT_INSET, BASE_C1, BOT_INSET - BASE_C1);
    translate([0, 0, BASE_C1 - OVER])
        rbox_inset(PITCH, PITCH, BOT_INSET - BASE_C1, BASE_STR + 2 * OVER);
    taper(PITCH, PITCH, BASE_C1 + BASE_STR, BOT_INSET - BASE_C1,
          BASE_H, TOP_INSET);
}

// The 0.5mm grooves between adjacent feet are intentional; that is what the
// underside of a gridfinity bin looks like.
module base() {
    for (i = [0 : grid_x - 1], j = [0 : grid_y - 1])
        translate([(i - (grid_x - 1) / 2) * PITCH,
                   (j - (grid_y - 1) / 2) * PITCH, 0])
            foot();
}

// --------------------------------------------------------------------------
// Peg lattice
// --------------------------------------------------------------------------

// Hex packed with columns running along Y. The spacing is the only real
// constraint: it is the widest a spool flange can be. Columns along Y pack 30
// pegs into a 3x4; running them the other way packs only 28.
function col_spacing() = spool_spacing * sqrt(3) / 2;
function span_x() = outer(grid_x) - 2 * wall - spool_spacing;
function span_y() = outer(grid_y) - 2 * wall - spool_spacing;
function n_cols()  = span_x() < 0 ? 0 : floor(span_x() / col_spacing()) + 1;
function col_off(j) = (j % 2 == 1) ? spool_spacing / 2 : 0;
function n_in_col(j) = span_y() < col_off(j) ? 0
                     : floor((span_y() - col_off(j)) / spool_spacing) + 1;

function peg_grid() = [
    for (j = [0 : max(0, n_cols() - 1)], i = [0 : max(0, n_in_col(j) - 1)])
        if (n_cols() > 0 && n_in_col(j) > 0)
            [j * col_spacing(), col_off(j) + i * spool_spacing]
];

// Offset columns end at a different Y than even ones, so the generated block
// is not symmetric about its own origin and has to be centred explicitly.
function grid_mid(pts, axis) =
    (min([for (p = pts) p[axis]]) + max([for (p = pts) p[axis]])) / 2;

// Revolved as one solid rather than a shaft plus a cone. Two primitives per
// peg means twice the solids for the final union to chew through, and with
// thirty pegs that is the single biggest cost in the script.
module peg() {
    r = peg_dia / 2;
    r_tip = max(0.05, r - PEG_CHAMFER);
    straight = peg_height - PEG_CHAMFER;
    // Sunk OVER into the floor for the same reason the base sections overlap.
    rotate_extrude($fn = detail)
        polygon([[0, -OVER], [r, -OVER], [r, straight],
                 [r_tip, peg_height], [0, peg_height]]);
}

module peg_field() {
    pts = peg_grid();
    if (len(pts) > 0) {
        ox = grid_mid(pts, 0);
        oy = grid_mid(pts, 1);
        for (p = pts) translate([p[0] - ox, p[1] - oy, 0]) peg();
    }
}

// --------------------------------------------------------------------------
// Assembly
// --------------------------------------------------------------------------

module lip_negative(fx, fy, h) {
    throat_z = h - LIP_C1 - LIP_STR;
    taper(fx, fy, h - LIP_H, LIP_W, throat_z, LIP_C1);
    translate([0, 0, throat_z - OVER])
        rbox_inset(fx, fy, LIP_C1, LIP_STR + 2 * OVER);
    taper(fx, fy, h - LIP_C1, LIP_C1, h, LIP_TIP);
    translate([0, 0, h - EPS]) rbox_inset(fx, fy, LIP_TIP, LIP_H);
}

module bin() {
    h = total_height();
    fx = outer(grid_x);
    fy = outer(grid_y);
    floor_z = BASE_H + floor_thickness;
    // The cavity has to stop at the bottom of the lip. The wall is thinner
    // than the ledge inset, so a full height cavity cuts through and quietly
    // erases the lip.
    cavity_top = stacking_lip ? h - LIP_H : h;

    difference() {
        union() {
            base();
            translate([0, 0, BASE_H - OVER])
                rbox(fx, fy, R_TOP, h - BASE_H + OVER);
        }
        translate([0, 0, floor_z])
            rbox(fx - 2 * wall, fy - 2 * wall, R_TOP - wall,
                 cavity_top - floor_z);
        if (stacking_lip) lip_negative(fx, fy, h);
    }
}

module spool_holder() {
    union() {
        bin();
        translate([0, 0, BASE_H + floor_thickness]) peg_field();
    }
}

spool_holder();

echo(str("pegs = ", len(peg_grid())));
echo(str("size = ", outer(grid_x), " x ", outer(grid_y),
         " x ", total_height(), " mm"));
echo(str("stack pitch = ", UNIT_Z * grid_z, " mm"));
