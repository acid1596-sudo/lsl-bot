// bot_npc.lsl
// -----------------------------------------------------------------------
// Second Life NPC Pathfinding Bot (Experience-based)
// Uses llCreateCharacter / llExecCharacterCmd (requires an Experience key).
//
// How to use:
//   1. Enable an Experience in the parcel/region.
//   2. Place this script in a prim that is part of the Experience.
//   3. Set EXPERIENCE_KEY to your Experience UUID.
//   4. Touch the prim to spawn a character and start wandering.
// -----------------------------------------------------------------------

// ---- configuration ----------------------------------------------------
string  EXPERIENCE_KEY  = "00000000-0000-0000-0000-000000000000"; // replace!
float   WANDER_RADIUS   = 15.0;
float   WANDER_INTERVAL = 6.0;
float   CHAR_SPEED      = 2.0;   // m/s
float   CHAR_RADIUS     = 0.3;   // collision radius (metres)
float   CHAR_HEIGHT     = 1.8;   // character height (metres)

// ---- internal state ---------------------------------------------------
vector  origin;
integer active = FALSE;

// ---- helpers ----------------------------------------------------------
vector randomNearby(vector centre, float radius)
{
    float angle = llFrand(TWO_PI);
    float dist  = llFrand(radius);
    return centre + <llCos(angle) * dist, llSin(angle) * dist, 0.0>;
}

spawnCharacter()
{
    // Guard: warn the user if the Experience key has not been configured
    if (EXPERIENCE_KEY == "00000000-0000-0000-0000-000000000000")
    {
        llOwnerSay("ERROR: EXPERIENCE_KEY is still the default placeholder. "
                 + "Set it to your Experience UUID before using NPC bots.");
        return;
    }

    // Create a pathfinding character on this prim
    llCreateCharacter([
        CHARACTER_RADIUS,        CHAR_RADIUS,
        CHARACTER_LENGTH,        CHAR_HEIGHT,
        CHARACTER_ORIENTATION,   CHAR_ORIENTATION_UPRIGHT
    ]);

    active = TRUE;
    llSetText("NPC Bot\n[wandering]", <0.5, 1.0, 0.0>, 1.0);
    llSetTimerEvent(WANDER_INTERVAL);
    llOwnerSay("NPC character created. Wandering started.");
}

deleteCharacter()
{
    llDeleteCharacter();
    active = FALSE;
    llSetTimerEvent(0.0);
    llSetText("NPC Bot\n[inactive]", <1.0, 0.4, 0.4>, 1.0);
    llOwnerSay("NPC character removed.");
}

// ---- event handlers ---------------------------------------------------
default
{
    state_entry()
    {
        origin = llGetPos();
        llSetText("NPC Bot\n[inactive]", <1.0, 0.4, 0.4>, 1.0);
        llOwnerSay("NPC Bot ready. Touch to toggle.");
    }

    touch_start(integer num)
    {
        if (active)
            deleteCharacter();
        else
            spawnCharacter();
    }

    timer()
    {
        if (!active) return;

        vector target = randomNearby(origin, WANDER_RADIUS);

        // Navigate to target using the pathfinding system
        llExecCharacterCmd(CHARACTER_CMD_SMOOTH_STOP, []);
        llNavigateTo(target, [NAVIGATE_ACCEPT_PARTIAL_PATHS, TRUE]);
    }

    path_update(integer type, list reserved)
    {
        // PATH_UPDATE_FULL_STOP means we arrived – pick a new target on next timer
        if (type == PU_GOAL_REACHED || type == PU_FAILURE_NO_NAVMESH)
            llSetTimerEvent(WANDER_INTERVAL);
    }

    on_rez(integer param)
    {
        llResetScript();
    }
}
