// bot_loader.lsl
// -----------------------------------------------------------------------
// Second Life Bot Loader HUD
// Wear this script as a HUD attachment (or place it in a prim in-world).
// It lets you rez, list, command, and clean up bot objects.
//
// Usage:
//   1. Place a bot object (with bot_controller.lsl inside) in the same
//      prim's inventory, named "Bot".
//   2. Wear or rez this object.
//   3. Touch it to open the control menu.
// -----------------------------------------------------------------------

// ---- configuration ----------------------------------------------------
integer MAX_BOTS        = 10;       // maximum bots allowed at once
float   BOT_ALTITUDE    = 0.0;      // extra altitude offset when rezzing
float   BOT_SPREAD      = 2.0;      // metres between each rezzed bot
string  BOT_INVENTORY   = "Bot";    // name of the bot object in inventory

// ---- communication channel (same in bot_loader.lsl, bot_controller.lsl,
//      and bot_npc.lsl – update ALL files if you change this value) ------
integer CONTROL_CHANNEL = -987654;

// ---- internal state ---------------------------------------------------
list    botKeys   = [];   // keys of rezzed bots
integer listening = FALSE;
integer listenHandle;

// ---- helpers ----------------------------------------------------------
showMenu(key id)
{
    integer count = llGetListLength(botKeys);
    string  status = "Active bots: " + (string)count + " / " + (string)MAX_BOTS;

    list buttons = ["Load Bot", "Remove All", "List Bots",
                    "Move Bots", "Stop Bots",  "Close"];

    llDialog(id, "=== Bot Loader ===\n" + status, buttons, CONTROL_CHANNEL);

    if (!listening)
    {
        listenHandle = llListen(CONTROL_CHANNEL, "", id, "");
        listening    = TRUE;
        llSetTimerEvent(30.0);   // auto-close listen after 30 s
    }
}

rezBot()
{
    if (llGetListLength(botKeys) >= MAX_BOTS)
    {
        llOwnerSay("Bot limit reached (" + (string)MAX_BOTS + ").");
        return;
    }

    if (llGetInventoryType(BOT_INVENTORY) == INVENTORY_NONE)
    {
        llOwnerSay("ERROR: No inventory object named \"" + BOT_INVENTORY + "\" found.");
        return;
    }

    // Spread bots out in a line from the owner
    integer idx    = llGetListLength(botKeys);
    vector  offset = <(float)idx * BOT_SPREAD, 0.0, BOT_ALTITUDE + 1.0>;
    vector  pos    = llGetPos() + offset;

    // param = index so the bot knows its slot number
    llRezObject(BOT_INVENTORY, pos, ZERO_VECTOR, ZERO_ROTATION, idx);
    llOwnerSay("Rezzing bot #" + (string)(idx + 1) + " ...");
}

removeAllBots()
{
    integer i;
    for (i = 0; i < llGetListLength(botKeys); i++)
    {
        key k = llList2Key(botKeys, i);
        if (k != NULL_KEY)
            llSay(CONTROL_CHANNEL, "CMD|" + (string)k + "|DIE");
    }
    botKeys = [];
    llOwnerSay("All bots removed.");
}

listBots()
{
    integer count = llGetListLength(botKeys);
    if (count == 0)
    {
        llOwnerSay("No active bots.");
        return;
    }
    llOwnerSay("Active bots (" + (string)count + "):");
    integer i;
    for (i = 0; i < count; i++)
        llOwnerSay("  #" + (string)(i + 1) + " key=" + (string)llList2Key(botKeys, i));
}

sendAll(string cmd)
{
    integer i;
    for (i = 0; i < llGetListLength(botKeys); i++)
    {
        key k = llList2Key(botKeys, i);
        if (k != NULL_KEY)
            llSay(CONTROL_CHANNEL, "CMD|" + (string)k + "|" + cmd);
    }
}

// ---- event handlers ---------------------------------------------------
default
{
    state_entry()
    {
        llOwnerSay("Bot Loader ready. Touch to open the menu.");
        llSetText("Bot Loader\nTouch to start", <0.2, 0.8, 1.0>, 1.0);
    }

    touch_start(integer num)
    {
        showMenu(llDetectedKey(0));
    }

    // Receive bot key when a newly rezzed bot calls llMessageLinked / llSay
    listen(integer channel, string name, key id, string msg)
    {
        // ---- menu responses ----
        if (msg == "Load Bot")
        {
            rezBot();
            showMenu(id);
            return;
        }
        if (msg == "Remove All")
        {
            removeAllBots();
            showMenu(id);
            return;
        }
        if (msg == "List Bots")
        {
            listBots();
            showMenu(id);
            return;
        }
        if (msg == "Move Bots")
        {
            sendAll("WANDER");
            llOwnerSay("Bots set to wander.");
            showMenu(id);
            return;
        }
        if (msg == "Stop Bots")
        {
            sendAll("STOP");
            llOwnerSay("Bots stopped.");
            showMenu(id);
            return;
        }
        if (msg == "Close")
        {
            llListenRemove(listenHandle);
            listening = FALSE;
            llSetTimerEvent(0.0);
            return;
        }

        // ---- registration: bot reports its key on rez ----
        // format: "REGISTER|<key>"
        if (llGetSubString(msg, 0, 8) == "REGISTER|")
        {
            key botKey = (key)llGetSubString(msg, 9, -1);
            if (llListFindList(botKeys, [botKey]) == -1)
            {
                botKeys += [botKey];
                llOwnerSay("Bot registered. Total: " + (string)llGetListLength(botKeys));
            }
            return;
        }

        // ---- deregistration: bot reports death ----
        // format: "GONE|<key>"
        if (llGetSubString(msg, 0, 4) == "GONE|")
        {
            key botKey = (key)llGetSubString(msg, 5, -1);
            integer idx = llListFindList(botKeys, [botKey]);
            if (idx != -1)
            {
                botKeys = llDeleteSubList(botKeys, idx, idx);
                llOwnerSay("Bot removed. Remaining: " + (string)llGetListLength(botKeys));
            }
            return;
        }
    }

    object_rez(key id)
    {
        // Auto-register the bot we just rezzed
        if (llListFindList(botKeys, [id]) == -1)
        {
            botKeys += [id];
            llOwnerSay("Bot #" + (string)llGetListLength(botKeys) + " rezzed (key=" + (string)id + ").");
        }
        llSetText("Bot Loader\nBots: " + (string)llGetListLength(botKeys), <0.2, 0.8, 1.0>, 1.0);
    }

    timer()
    {
        // Auto-remove listen handle if idle
        if (listening)
        {
            llListenRemove(listenHandle);
            listening = FALSE;
        }
        llSetTimerEvent(0.0);
    }

    on_rez(integer param)
    {
        llResetScript();
    }
}
