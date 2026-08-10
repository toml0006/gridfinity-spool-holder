// Gridfinity primitives.
//
// Every constant below was measured off a known-good bin
// (Documents/TomlinsonLTD/MakerWorld/Gridfinity/Calipers.3mf) rather than
// recalled, then cross-checked against kennetek/gridfinity-rebuilt-openscad.
// See README.md for the measurements and the one place the two disagree.

GF_PITCH      = 42;     // grid pitch
GF_GAP        = 0.5;    // outer footprint is PITCH*n - GAP
GF_TOP_INSET  = 0.25;   // = GAP/2, inset per side at top of base
GF_R_TOP      = 3.75;   // corner radius at top of base and up the wall

// Base profile, bottom to top. Insets are per side, measured in from the
// nominal 42mm cell edge. Bottom inset 3.20 = 0.25 + 0.8 + 2.15.
GF_BASE_C1    = 0.8;    // lower 45 deg chamfer
GF_BASE_STR   = 1.8;    // vertical section
GF_BASE_C2    = 2.15;   // upper 45 deg chamfer
GF_BASE_H     = GF_BASE_C1 + GF_BASE_STR + GF_BASE_C2;   // 4.75
GF_BOT_INSET  = GF_TOP_INSET + GF_BASE_C1 + GF_BASE_C2;  // 3.20

// Stacking lip. Insets are per side, in from the outer wall.
//
// The lip is a funnel that opens towards the rim: widest at the top so the
// feet of the bin above can drop in, narrowing to an inward ledge at the
// bottom of the lip which is what actually takes the load. Build it the
// other way up and the wall cavity just swallows it.
GF_LIP_C1     = 0.7;    // 45 deg at the rim, and the throat inset
GF_LIP_STR    = 1.8;    // vertical throat
GF_LIP_C2     = 1.9;    // 45 deg down to the ledge
GF_LIP_H      = GF_LIP_C1 + GF_LIP_STR + GF_LIP_C2;      // 4.40
GF_LIP_W      = GF_LIP_C1 + GF_LIP_C2;                   // 2.60, ledge inset
// Spec puts the rim at zero inset, i.e. a knife edge. Back it off so the rim
// prints as a real surface -- but the amount is derived, not chosen. The bin
// above sinks until its base flare jams on the rim, and that sink depth sets
// the stack pitch. Make it jam at exactly GF_LIP_H and the pitch comes out at
// exactly GF_UNIT_Z per height unit, so a tall stack stays on the grid.
//
// So the rim inset is however much wider the outer wall is than the base at
// GF_LIP_H above its underside: 0.60 - 0.25 = 0.35.
function gf_base_inset(t) =
      t <= GF_BASE_C1               ? GF_BOT_INSET - t
    : t <= GF_BASE_C1 + GF_BASE_STR ? GF_BOT_INSET - GF_BASE_C1
    : max(GF_TOP_INSET, GF_BOT_INSET - GF_BASE_C1 - (t - GF_BASE_C1 - GF_BASE_STR));

GF_LIP_TIP    = gf_base_inset(GF_LIP_H) - GF_TOP_INSET;   // 0.35

GF_UNIT_Z     = 7;      // height unit
GF_Z_LIPLESS  = 3.8;    // total = 7*u + this, for a lipless bin

// Corner radius shrinks 1:1 with inset, so the whole base is one rounded
// rect swept through a varying offset. Falls out of the measurements:
// at inset 3.20 this gives 0.80, and 0.80 is what the bottom face measures.
function gf_radius(inset) = GF_R_TOP - (inset - GF_TOP_INSET);

function gf_outer(n) = GF_PITCH * n - GF_GAP;

// Total outer height of a bin.
function gf_height(zu, lip = true) =
    GF_UNIT_Z * zu + (lip ? GF_LIP_H : GF_Z_LIPLESS);

// Rounded rectangular prism, centered in X/Y, sitting on z=0.
module gf_rrect(sx, sy, r, h) {
    linear_extrude(height = h)
        offset(r = r)
            square([sx - 2*r, sy - 2*r], center = true);
}

// A rounded rect described by its inset from a footprint, so radius stays
// consistent with the profile.
module gf_rrect_inset(fx, fy, inset, h) {
    gf_rrect(fx - 2*inset, fy - 2*inset, gf_radius(inset), h);
}

// One base foot, occupying a single 42mm cell, sitting on z=0.
module gf_foot(eps = 0.002) {
    P = GF_PITCH;
    // 45 deg run-out from the bottom inset to the straight section
    hull() {
        gf_rrect_inset(P, P, GF_BOT_INSET, eps);
        translate([0, 0, GF_BASE_C1 - eps])
            gf_rrect_inset(P, P, GF_BOT_INSET - GF_BASE_C1, eps);
    }
    // straight section
    translate([0, 0, GF_BASE_C1])
        gf_rrect_inset(P, P, GF_BOT_INSET - GF_BASE_C1, GF_BASE_STR);
    // 45 deg flare out to full width at the top of the base
    hull() {
        translate([0, 0, GF_BASE_C1 + GF_BASE_STR])
            gf_rrect_inset(P, P, GF_BOT_INSET - GF_BASE_C1, eps);
        translate([0, 0, GF_BASE_H - eps])
            gf_rrect_inset(P, P, GF_TOP_INSET, eps);
    }
}

// Full base: one foot per cell, arrayed on the grid. The 0.5mm grooves
// between adjacent feet are intentional and are what the grid looks like.
module gf_base(gx, gy) {
    for (i = [0:gx-1], j = [0:gy-1])
        translate([(i - (gx-1)/2) * GF_PITCH,
                   (j - (gy-1)/2) * GF_PITCH, 0])
            gf_foot();
}

// Solid outer body from the top of the base up to `h`.
module gf_body(gx, gy, h) {
    translate([0, 0, GF_BASE_H])
        gf_rrect(gf_outer(gx), gf_outer(gy), GF_R_TOP, h - GF_BASE_H);
}

// Negative for the stacking lip: the socket cut into the rim that receives
// the feet of the bin above. Cut from the ledge upward, widening as it goes.
module gf_lip_negative(gx, gy, h, eps = 0.002) {
    fx = gf_outer(gx);
    fy = gf_outer(gy);
    throat_z = h - GF_LIP_C1 - GF_LIP_STR;
    // ledge at the bottom of the lip, opening out to the throat
    hull() {
        translate([0, 0, h - GF_LIP_H])
            gf_rrect_inset(fx, fy, GF_LIP_W, eps);
        translate([0, 0, throat_z])
            gf_rrect_inset(fx, fy, GF_LIP_C1, eps);
    }
    // vertical throat
    translate([0, 0, throat_z])
        gf_rrect_inset(fx, fy, GF_LIP_C1, GF_LIP_STR);
    // final flare out to the rim
    hull() {
        translate([0, 0, h - GF_LIP_C1])
            gf_rrect_inset(fx, fy, GF_LIP_C1, eps);
        translate([0, 0, h - eps])
            gf_rrect_inset(fx, fy, GF_LIP_TIP, eps);
    }
    // everything above the rim is open
    translate([0, 0, h - eps])
        gf_rrect_inset(fx, fy, GF_LIP_TIP, GF_LIP_H);
}

// An open bin: base, walls, cavity, optional stacking lip.
// The cavity floor sits at z = GF_BASE_H + floor_h.
module gf_bin(gx, gy, zu, wall = 1.6, floor_h = 1.25, lip = true) {
    h = gf_height(zu, lip);
    difference() {
        union() {
            gf_base(gx, gy);
            gf_body(gx, gy, h);
        }
        // Interior cavity. It has to stop at the bottom of the lip, otherwise
        // it cuts straight through and erases the ledge -- the wall is
        // thinner than the ledge inset, so whichever cut runs deeper wins.
        cavity_top = lip ? h - GF_LIP_H : h;
        floor_z = GF_BASE_H + floor_h;
        translate([0, 0, floor_z])
            gf_rrect(gf_outer(gx) - 2*wall, gf_outer(gy) - 2*wall,
                     max(0.1, GF_R_TOP - wall), cavity_top - floor_z);
        if (lip) gf_lip_negative(gx, gy, h);
    }
}
