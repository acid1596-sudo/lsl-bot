// bot_controller.lsl
// -----------------------------------------------------------------------
// Second Life Bot Controller
// Place this script inside the object named "Bot" that the loader rezzes.
//
// On rez the bot:
//   - Registers its key with the loader on CONTROL_CHANNEL
//   - Listens for commands from the loader
//
// Supported commands (sent by the loader as "CMD|<key>|<command>"):
//   WANDER   – roam randomly within a radius
//   STOP     – halt and stand still
//   FOLLOW   – follow the owner
//   RETURN   – return to rez position
//   DIE      – remove (delete) the bot
// -----------------------------------------------------------------------

// ---- must match bot_loader.lsl ----------------------------------------
integer CONTROL_CHANNEL = -987654;

// ---- configuration ----------------------------------------------------
float  WANDER_RADIUS   = 10.0;    // metres to wander from start position
float  WANDER_INTERVAL = 8.0;     // seconds between wander moves
float  MOVE_SPEED      = 2.0;     // walk speed (used with llMoveToTarget)
float  FOLLOW_DIST     = 2.5;     // metres behind owner to stand
string BOT_NAME        = "Bot";   // display name shown above the prim

// ---- internal state ---------------------------------------------------
key     ownerKey;
vector  startPos;
integer botSlot;        // slot number passed in on_rez param
integer mode;           // 0=idle, 1=wander, 2=follow, 3=return

integer MODE_IDLE   = 0;
integer MODE_WANDER = 1;
integer MODE_FOLLOW = 2;
integer MODE_RETURN = 3;

// ---- helpers ----------------------------------------------------------
vector randomNearby(vector centre, float radius)
{
    float angle = llFrand(TWO_PI);
    float dist  = llFrand(radius);
    return centre + <llCos(angle) * dist, llSin(angle) * dist, 0.0>;
}

applyMove(vector target)
{
    // llMoveToTarget works for physical objects; for non-physical use
    // llSetPos for simple teleport-style movement.
    if (llGetStatus(STATUS_PHYSICS))
        llMoveToTarget(target, 0.5);
    else
        llSetPos(target);
}

setMode(integer newMode)
{
    mode = newMode;
    if (mode == MODE_IDLE || mode == MODE_RETURN)
    {
        llSetTimerEvent(0.0);
        if (mode == MODE_RETURN)
            applyMove(startPos);
    }
    else if (mode == MODE_WANDER)
    {
        llSetTimerEvent(WANDER_INTERVAL);
    }
    else if (mode == MODE_FOLLOW)
    {
        llSetTimerEvent(1.5);
    }
}

// ---- event handlers ---------------------------------------------------
default
{
    state_entry()
    {
        ownerKey = llGetOwner();
        startPos = llGetPos();
        mode     = MODE_IDLE;
        botSlot  = 0;

        llSetObjectName(BOT_NAME);
        llSetText(BOT_NAME + "\n[idle]", <0.5, 1.0, 0.5>, 1.0);

        // Start listening for commands from the loader
        llListen(CONTROL_CHANNEL, "", NULL_KEY, "");
    }

    on_rez(integer param)
    {
        botSlot  = param;
        startPos = llGetPos();
        mode     = MODE_IDLE;

        llSetObjectName(BOT_NAME + " #" + (string)(param + 1));
        llSetText(BOT_NAME + " #" + (string)(param + 1) + "\n[idle]", <0.5, 1.0, 0.5>, 1.0);

        // Register with the loader
        llSay(CONTROL_CHANNEL, "REGISTER|" + (string)llGetKey());
    }

    listen(integer channel, string name, key id, string msg)
    {
        // Expected format: "CMD|<targetKey>|<command>"
        // Also handle REGISTER/GONE echoes (ignore them in the bot)
        list   parts  = llParseString2List(msg, ["|"], []);
        string prefix = llList2String(parts, 0);

        if (prefix != "CMD") return;

        // Commands are either broadcast (targetKey = "*") or directed
        key    target = (key)llList2String(parts, 1);
        string cmd    = llList2String(parts, 2);

        if (target != llGetKey() && (string)target != "*") return;

        if (cmd == "WANDER")
        {
            setMode(MODE_WANDER);
            llSetText(llGetObjectName() + "\n[wandering]", <0.2, 0.9, 0.2>, 1.0);
            return;
        }
        if (cmd == "STOP")
        {
            setMode(MODE_IDLE);
            llSetText(llGetObjectName() + "\n[stopped]", <1.0, 0.8, 0.0>, 1.0);
            return;
        }
        if (cmd == "FOLLOW")
        {
            setMode(MODE_FOLLOW);
            llSetText(llGetObjectName() + "\n[following]", <0.2, 0.5, 1.0>, 1.0);
            return;
        }
        if (cmd == "RETURN")
        {
            setMode(MODE_RETURN);
            llSetText(llGetObjectName() + "\n[returning]", <1.0, 0.5, 0.0>, 1.0);
            return;
        }
        if (cmd == "DIE")
        {
            llSay(CONTROL_CHANNEL, "GONE|" + (string)llGetKey());
            llDie();
            return;
        }
    }

    timer()
    {
        if (mode == MODE_WANDER)
        {
            vector target = randomNearby(startPos, WANDER_RADIUS);
            // Keep ground level (z unchanged from start)
            target.z = startPos.z;
            applyMove(target);
            return;
        }

        if (mode == MODE_FOLLOW)
        {
            vector ownerPos = llList2Vector(llGetObjectDetails(ownerKey,
                                            [OBJECT_POS]), 0);
            if (ownerPos == ZERO_VECTOR)
            {
                // Owner not found – fall back to idle
                setMode(MODE_IDLE);
                return;
            }
            // Stand slightly behind the owner
            vector dir    = llVecNorm(llGetPos() - ownerPos);
            vector target = ownerPos + dir * FOLLOW_DIST;
            target.z      = ownerPos.z;
            applyMove(target);
            return;
        }
    }

    changed(integer change)
    {
        if (change & CHANGED_OWNER)
            llResetScript();
    }
}
