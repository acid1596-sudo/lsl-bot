// =============================================================================
// Avatar Loader Script
// Place this script inside a prim in-world.
// The prim's inventory must contain:
//   - A notecard named "AvatarConfig" (see notecards/avatar_config.txt)
//   - One or more avatar objects (prim/linkset) named exactly as listed in
//     the notecard.
// Touch the prim to open the load/manage menu.
// =============================================================================

// ---------- tuneable constants -----------------------------------------------
string  NOTECARD_NAME  = "AvatarConfig";   // name of the config notecard
integer CMD_CHANNEL    = -88776655;        // channel avatars listen on
float   REZ_HEIGHT     = 0.5;             // height offset when rezzing avatars
integer MAX_AVATARS    = 12;              // hard cap (dialog fits 12 buttons)
// -----------------------------------------------------------------------------

// runtime state
list    g_names        = [];   // avatar names parsed from notecard
list    g_positions    = [];   // <x,y,z> offsets (strings) from notecard
list    g_rezzed_keys  = [];   // keys of currently rezzed avatar objects
integer g_nc_line      = 0;
key     g_nc_query     = NULL_KEY;
integer g_menu_channel = 0;   // randomised each time menu is shown
integer g_menu_handle  = 0;
key     g_menu_user    = NULL_KEY;
integer g_loading_cfg  = FALSE;

// ---------- helpers ----------------------------------------------------------

// Return the channel we sent the menu on
integer randomChannel()
{
    return (integer)("0x" + llGetSubString((string)llGenerateKey(), 0, 6));
}

// Build a flat list of button labels for llDialog
list buildMenuButtons()
{
    list btns = [];
    integer i;
    for (i = 0; i < llGetListLength(g_names) && i < MAX_AVATARS; i++)
    {
        btns += [llList2String(g_names, i)];
    }
    // management buttons
    btns += ["--- List ---", "--- DeRez All ---", "--- Reload Config ---"];
    return btns;
}

string trimWhitespace(string s)
{
    // Strip leading/trailing spaces and tabs
    while (llGetSubString(s, 0, 0) == " " || llGetSubString(s, 0, 0) == "\t")
        s = llDeleteSubString(s, 0, 0);
    while (llGetSubString(s, -1, -1) == " " || llGetSubString(s, -1, -1) == "\t")
        s = llDeleteSubString(s, -1, -1);
    return s;
}

// Rez a named avatar object at an offset from this prim
integer rezAvatar(string name, vector offset)
{
    if (llGetInventoryType(name) != INVENTORY_OBJECT)
    {
        llOwnerSay("[AvatarLoader] ERROR: object '" + name + "' not found in inventory.");
        return FALSE;
    }
    vector rezPos = llGetPos() + offset + <0.0, 0.0, REZ_HEIGHT>;
    rotation rezRot = llGetRot();
    llRezObject(name, rezPos, ZERO_VECTOR, rezRot, CMD_CHANNEL);
    return TRUE;
}

// De-rez (delete) all rezzed avatar objects we know about
derezAll()
{
    integer i;
    for (i = 0; i < llGetListLength(g_rezzed_keys); i++)
    {
        key k = llList2Key(g_rezzed_keys, i);
        if (k != NULL_KEY)
            llRegionSayTo(k, CMD_CHANNEL, "cmd:derez");
    }
    g_rezzed_keys = [];
    llOwnerSay("[AvatarLoader] All scripted avatars de-rezzed.");
}

// Show the main management dialog to the user
showMenu(key user)
{
    if (llGetListLength(g_names) == 0)
    {
        llRegionSayTo(user, 0,
            "[AvatarLoader] No avatars configured. "
            "Add an '" + NOTECARD_NAME + "' notecard and touch again.");
        return;
    }
    if (g_menu_handle) llListenRemove(g_menu_handle);
    g_menu_channel = -randomChannel();
    g_menu_handle = llListen(g_menu_channel, "", user, "");
    g_menu_user   = user;
    llDialog(user,
        "=== Avatar Loader ===\n"
        "Select an avatar to rez, or choose a management option:\n",
        buildMenuButtons(), g_menu_channel);
    llSetTimerEvent(30.0); // auto-close after 30 s
}

// Kick off notecard reading
loadConfig()
{
    if (llGetInventoryType(NOTECARD_NAME) != INVENTORY_NOTECARD)
    {
        llOwnerSay("[AvatarLoader] Notecard '" + NOTECARD_NAME + "' not found.");
        return;
    }
    g_names        = [];
    g_positions    = [];
    g_nc_line      = 0;
    g_loading_cfg  = TRUE;
    llSetText("Loading config...", <1,1,0>, 1.0);
    g_nc_query = llGetNotecardLine(NOTECARD_NAME, g_nc_line);
}

// ---------- states -----------------------------------------------------------

default
{
    state_entry()
    {
        llSetText("Avatar Loader\nTouch to open menu", <0,1,0>, 1.0);
        llOwnerSay("[AvatarLoader] Ready. Touch to manage scripted avatars.");
        // Auto-load config if notecard is present
        if (llGetInventoryType(NOTECARD_NAME) == INVENTORY_NOTECARD)
            loadConfig();
    }

    on_rez(integer start_param)
    {
        llResetScript();
    }

    touch_start(integer num)
    {
        key toucher = llDetectedKey(0);
        // Only the owner may use this tool
        if (toucher != llGetOwner()) return;
        if (g_loading_cfg)
        {
            llOwnerSay("[AvatarLoader] Still loading config, please wait...");
            return;
        }
        showMenu(toucher);
    }

    // ---- notecard reading ---------------------------------------------------
    dataserver(key query_id, string data)
    {
        if (query_id != g_nc_query) return;

        if (data == EOF)
        {
            g_loading_cfg = FALSE;
            integer count = llGetListLength(g_names);
            llSetText("Avatar Loader\n" + (string)count + " avatar(s) configured\nTouch to open menu",
                      <0,1,0>, 1.0);
            llOwnerSay("[AvatarLoader] Config loaded — " + (string)count + " avatar(s) available.");
            return;
        }

        string line = trimWhitespace(data);

        // Skip blank lines and comments
        if (line == "" || llGetSubString(line, 0, 0) == "#")
        {
            g_nc_line++;
            g_nc_query = llGetNotecardLine(NOTECARD_NAME, g_nc_line);
            return;
        }

        // Expected format:  AvatarName | x,y,z
        list parts = llParseString2List(line, ["|"], []);
        if (llGetListLength(parts) >= 1)
        {
            string name   = trimWhitespace(llList2String(parts, 0));
            string posStr = "0,0,0";
            if (llGetListLength(parts) >= 2)
                posStr = trimWhitespace(llList2String(parts, 1));

            if (name != "" && llGetListLength(g_names) < MAX_AVATARS)
            {
                g_names     += [name];
                g_positions += [posStr];
            }
        }

        g_nc_line++;
        g_nc_query = llGetNotecardLine(NOTECARD_NAME, g_nc_line);
    }

    // ---- dialog response ----------------------------------------------------
    listen(integer channel, string name, key id, string msg)
    {
        if (channel != g_menu_channel) return;
        llListenRemove(g_menu_handle);
        g_menu_handle = 0;
        llSetTimerEvent(0.0);

        if (msg == "--- List ---")
        {
            integer i;
            string out = "[AvatarLoader] Configured avatars:\n";
            for (i = 0; i < llGetListLength(g_names); i++)
                out += "  [" + (string)(i+1) + "] " + llList2String(g_names, i) + "\n";
            out += "Rezzed: " + (string)llGetListLength(g_rezzed_keys);
            llOwnerSay(out);
            return;
        }

        if (msg == "--- DeRez All ---")
        {
            derezAll();
            return;
        }

        if (msg == "--- Reload Config ---")
        {
            loadConfig();
            return;
        }

        // Otherwise the message is an avatar name to rez
        integer idx = llListFindList(g_names, [msg]);
        if (idx == -1)
        {
            llOwnerSay("[AvatarLoader] Unknown selection: " + msg);
            return;
        }

        string posStr = llList2String(g_positions, idx);
        list   coords = llParseString2List(posStr, [","], []);
        float  ox = 0.0, oy = 0.0, oz = 0.0;
        if (llGetListLength(coords) >= 3)
        {
            ox = (float)llList2String(coords, 0);
            oy = (float)llList2String(coords, 1);
            oz = (float)llList2String(coords, 2);
        }

        llOwnerSay("[AvatarLoader] Rezzing '" + msg + "'...");
        rezAvatar(msg, <ox, oy, oz>);
    }

    // ---- track rezzed objects -----------------------------------------------
    object_rez(key id)
    {
        g_rezzed_keys += [id];
        llOwnerSay("[AvatarLoader] Avatar rezzed. key=" + (string)id);
    }

    // ---- menu timeout -------------------------------------------------------
    timer()
    {
        llSetTimerEvent(0.0);
        if (g_menu_handle)
        {
            llListenRemove(g_menu_handle);
            g_menu_handle = 0;
        }
    }

    changed(integer change)
    {
        if (change & CHANGED_INVENTORY)
        {
            // Reload config if the notecard changes
            if (llGetInventoryType(NOTECARD_NAME) == INVENTORY_NOTECARD)
                loadConfig();
        }
    }
}
