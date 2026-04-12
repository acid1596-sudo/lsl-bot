// =============================================================================
// Avatar Behavior Script
// Drop this script into every avatar object that the Avatar Loader rezzes.
// The object will:
//   - Play an idle animation loop on rez
//   - Listen on CMD_CHANNEL for commands from the loader
//   - Optionally wander or follow a waypoint path
//   - Report its key back to the loader on startup
// =============================================================================

// Must match the CMD_CHANNEL in avatar_loader.lsl
integer CMD_CHANNEL = -88776655;

// ---- animations (change these to animation names in your inventory) --------
string ANIM_IDLE    = "stand";   // looped idle
string ANIM_WALK    = "walk";    // looped walk
string ANIM_WAVE    = "wave";    // one-shot greeting

// ---- wander settings -------------------------------------------------------
integer WANDER_ENABLED = FALSE;  // set TRUE to enable random wandering
float   WANDER_RANGE   = 5.0;   // metres from start position
float   WANDER_SPEED   = 2.0;   // m/s target move speed
float   WANDER_PAUSE   = 4.0;   // seconds to pause between moves

// Max entries kept in g_greeted to prevent unbounded memory growth
integer MAX_GREETED  = 50;
// ---- sensor settings -------------------------------------------------------
float SENSOR_RANGE   = 10.0;  // metres – greet nearby agents
float SENSOR_PERIOD  = 15.0;  // seconds between sensor sweeps

// ---- runtime state ---------------------------------------------------------
vector  g_start_pos     = ZERO_VECTOR;
vector  g_wander_target = ZERO_VECTOR; // current wander destination
integer g_moving        = FALSE;
list    g_waypoints     = [];   // optional fixed waypoints (set via cmd:waypoint)
integer g_wp_index      = 0;
list    g_greeted       = [];   // keys already greeted this session

// ---------- helpers ----------------------------------------------------------

playAnim(string anim)
{
    llStopAnimation(ANIM_IDLE);
    llStopAnimation(ANIM_WALK);
    llStartAnimation(anim);
}

stopMoving()
{
    llMoveToTarget(llGetPos(), 0.1);
    g_moving = FALSE;
    playAnim(ANIM_IDLE);
}

moveToTarget(vector target)
{
    g_moving        = TRUE;
    g_wander_target = target;
    llMoveToTarget(target, WANDER_SPEED);
    playAnim(ANIM_WALK);
}

// Pick a random position within WANDER_RANGE of start position
vector randomWanderTarget()
{
    float angle = llFrand(TWO_PI);
    float dist  = llFrand(WANDER_RANGE);
    return g_start_pos + <dist * llCos(angle), dist * llSin(angle), 0.0>;
}

handleCommand(string cmd)
{
    // Commands sent by avatar_loader.lsl or owner via CMD_CHANNEL chat
    if (cmd == "cmd:derez")
    {
        llDie();
        return;
    }
    if (cmd == "cmd:wave")
    {
        playAnim(ANIM_WAVE);
        return;
    }
    if (cmd == "cmd:stop")
    {
        WANDER_ENABLED = FALSE;
        stopMoving();
        llSetTimerEvent(0.0);
        return;
    }
    if (cmd == "cmd:wander")
    {
        WANDER_ENABLED = TRUE;
        llSetTimerEvent(WANDER_PAUSE);
        return;
    }
    if (llGetSubString(cmd, 0, 12) == "cmd:waypoint|")
    {
        // Format:  cmd:waypoint|x,y,z[|x,y,z|...]
        string payload = llGetSubString(cmd, 13, -1);
        list raw = llParseString2List(payload, ["|"], []);
        g_waypoints = [];
        integer i;
        for (i = 0; i < llGetListLength(raw); i++)
        {
            list coords = llParseString2List(llList2String(raw, i), [","], []);
            if (llGetListLength(coords) == 3)
            {
                vector wp = <(float)llList2String(coords, 0),
                              (float)llList2String(coords, 1),
                              (float)llList2String(coords, 2)>;
                g_waypoints += [wp];
            }
        }
        g_wp_index = 0;
        if (llGetListLength(g_waypoints) > 0)
        {
            WANDER_ENABLED = FALSE;
            llOwnerSay("[AvatarBehavior] " + (string)llGetListLength(g_waypoints) + " waypoint(s) set.");
            moveToTarget(llList2Vector(g_waypoints, 0));
            llSetTimerEvent(10.0);
        }
        return;
    }
    if (llGetSubString(cmd, 0, 10) == "cmd:moveto|")
    {
        // Format:  cmd:moveto|x,y,z
        list coords = llParseString2List(llGetSubString(cmd, 11, -1), [","], []);
        if (llGetListLength(coords) == 3)
        {
            vector target = <(float)llList2String(coords, 0),
                              (float)llList2String(coords, 1),
                              (float)llList2String(coords, 2)>;
            moveToTarget(target);
        }
        return;
    }
    if (llGetSubString(cmd, 0, 7) == "cmd:say|")
    {
        llSay(0, llGetSubString(cmd, 8, -1));
        return;
    }
}

// ---------- main state -------------------------------------------------------

default
{
    state_entry()
    {
        g_start_pos = llGetPos();
        llRequestPermissions(llGetOwner(),
            PERMISSION_TRIGGER_ANIMATIONS | PERMISSION_TAKE_CONTROLS);
        llListen(CMD_CHANNEL, "", NULL_KEY, "");
        if (WANDER_ENABLED) llSetTimerEvent(WANDER_PAUSE);
        if (SENSOR_PERIOD > 0.0) llSensorRepeat("", NULL_KEY, AGENT, SENSOR_RANGE, PI, SENSOR_PERIOD);
    }

    on_rez(integer start_param)
    {
        g_start_pos = llGetPos();
        llResetScript();
    }

    run_time_permissions(integer perm)
    {
        if (perm & PERMISSION_TRIGGER_ANIMATIONS)
            llStartAnimation(ANIM_IDLE);
    }

    listen(integer channel, string name, key id, string msg)
    {
        if (channel == CMD_CHANNEL)
            handleCommand(msg);
    }

    // ---- movement tick ------------------------------------------------------
    timer()
    {
        if (llGetListLength(g_waypoints) > 0)
        {
            // Waypoint following
            vector current_wp = llList2Vector(g_waypoints, g_wp_index);
            float dist = llVecDist(llGetPos(), current_wp);
            if (dist < 1.0)
            {
                // Reached waypoint – advance to next
                g_wp_index = (g_wp_index + 1) % llGetListLength(g_waypoints);
                moveToTarget(llList2Vector(g_waypoints, g_wp_index));
            }
            return;
        }

        if (WANDER_ENABLED)
        {
            if (!g_moving || llVecDist(llGetPos(), g_start_pos) > WANDER_RANGE * 1.5)
                stopMoving();
            else
                moveToTarget(randomWanderTarget());
        }
    }

    moving_end()
    {
        g_moving = FALSE;
        playAnim(ANIM_IDLE);
        if (WANDER_ENABLED) llSetTimerEvent(WANDER_PAUSE);
    }

    // ---- greet nearby agents ------------------------------------------------
    sensor(integer num)
    {
        integer i;
        for (i = 0; i < num; i++)
        {
            key agent = llDetectedKey(i);
            if (llListFindList(g_greeted, [agent]) == -1)
            {
                // Cap list size to avoid unbounded memory growth
                if (llGetListLength(g_greeted) >= MAX_GREETED)
                    g_greeted = llDeleteSubList(g_greeted, 0, 0);
                g_greeted += [agent];
                llSay(0, "Hello, " + llDetectedName(i) + "!");
                // Play wave then return to idle via moving_end / next timer tick
                playAnim(ANIM_WAVE);
            }
        }
    }

    no_sensor() { /* nobody nearby */ }
}
