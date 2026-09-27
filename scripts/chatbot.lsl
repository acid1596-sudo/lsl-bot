// lsl-bot chat script for Second Life.
//
// start.cmd fills in BOT_URL and BOT_SECRET for you, saves a ready-to-paste
// copy as data\chatbot.lsl and copies it to your clipboard. Put it in any
// object, then say "bot <anything>" in local chat.
//
// Only the object's owner is listened to, so other people can't spend your
// API usage through it.

string BOT_URL    = "BOT_URL_HERE";
string BOT_SECRET = "BOT_SECRET_HERE";
string PREFIX     = "bot ";
string SYSTEM_PROMPT = "You are a chat bot inside Second Life. Keep replies to one or two short sentences.";

list pending;

ask(string text)
{
    string history = llList2Json(JSON_ARRAY, [
        llList2Json(JSON_OBJECT, ["role", "system", "content", SYSTEM_PROMPT])
    ]);
    pending += [llHTTPRequest(BOT_URL,
        [HTTP_METHOD, "POST",
         HTTP_MIMETYPE, "application/json",
         HTTP_CUSTOM_HEADER, "X-Bot-Secret", BOT_SECRET,
         HTTP_BODY_MAXLENGTH, 16384],
        llList2Json(JSON_OBJECT, ["message", text, "history", history]))];
}

say(string text)
{
    // llSay cuts a message off at 1024 bytes, so long replies go out in parts.
    while (text != "")
    {
        llSay(0, llGetSubString(text, 0, 499));
        text = llDeleteSubString(text, 0, 499);
    }
}

default
{
    state_entry()
    {
        llListen(0, "", llGetOwner(), "");
    }

    on_rez(integer start_param)
    {
        llResetScript();
    }

    changed(integer change)
    {
        if (change & CHANGED_OWNER)
            llResetScript();
    }

    listen(integer channel, string name, key id, string message)
    {
        if (llSubStringIndex(llToLower(message), PREFIX) == 0)
            ask(llGetSubString(message, llStringLength(PREFIX), -1));
    }

    http_response(key id, integer status, list meta, string body)
    {
        integer i = llListFindList(pending, [id]);
        if (i == -1)
            return;
        pending = llDeleteSubList(pending, i, i);

        if (status == 200)
            say(llJsonGetValue(body, ["reply"]));
        else
            llOwnerSay("lsl-bot error " + (string)status + ": " + body);
    }
}
