# lsl-bot

A Second Life bot-loading system written in **LSL (Linden Scripting Language)**.

## Files

| File | Purpose |
|---|---|
| `bot_loader.lsl` | HUD/controller script – rez, list, command, and remove bots via a touch menu |
| `bot_controller.lsl` | Goes inside each rezzed bot object; handles movement and commands |
| `bot_npc.lsl` | Optional Experience-based NPC using `llCreateCharacter` / pathfinding |

---

## Quick Start (object-based bots)

### 1 – Create the bot object

1. In-world, create a new prim (any shape) and name it **`Bot`**.
2. Open its **Contents** tab and paste `bot_controller.lsl` in as a new script.
3. Take the object into your inventory.

### 2 – Create the loader

1. Create another prim (your HUD or in-world rezzor).
2. Paste `bot_loader.lsl` into it as a script.
3. Drag the **`Bot`** object from your inventory into the loader prim's **Contents** tab.

### 3 – Use the menu

Touch the loader prim to open the control menu:

| Button | Action |
|---|---|
| **Load Bot** | Rez a new bot near you (up to 10) |
| **Remove All** | Delete all active bots |
| **List Bots** | Print active bot keys to local chat |
| **Move Bots** | Set all bots to wander randomly |
| **Stop Bots** | Stop all bot movement |
| **Close** | Close the menu |

---

## NPC pathfinding bots (`bot_npc.lsl`)

These use Second Life's built-in pathfinding / character system and require an **Experience**.

1. Create or join a Second Life Experience (via the Dashboard → Experiences).
2. Enable the Experience on your parcel (About Land → Experiences).
3. Create a prim, paste `bot_npc.lsl` into it, and set `EXPERIENCE_KEY` to your Experience UUID.
4. Touch the prim to spawn / despawn the NPC character.

---

## Configuration

### `bot_loader.lsl`

| Variable | Default | Description |
|---|---|---|
| `MAX_BOTS` | `10` | Maximum number of bots that can be active at once |
| `BOT_SPREAD` | `2.0` | Metres between each rezzed bot |
| `BOT_ALTITUDE` | `0.0` | Extra altitude offset when rezzing |
| `BOT_INVENTORY` | `"Bot"` | Name of the bot object in the loader's inventory |

### `bot_controller.lsl`

| Variable | Default | Description |
|---|---|---|
| `WANDER_RADIUS` | `10.0` | Max metres to wander from start position |
| `WANDER_INTERVAL` | `8.0` | Seconds between wander moves |
| `FOLLOW_DIST` | `2.5` | Metres behind owner when following |

### `bot_npc.lsl`

| Variable | Default | Description |
|---|---|---|
| `EXPERIENCE_KEY` | *(set this)* | UUID of your Second Life Experience |
| `WANDER_RADIUS` | `15.0` | NPC wander radius in metres |
| `CHAR_SPEED` | `2.0` | Character movement speed (m/s) |

---

## Communication protocol

All scripts share channel **`-987654`** (can be changed in all files simultaneously).

| Message | Direction | Meaning |
|---|---|---|
| `REGISTER|<key>` | bot → loader | Bot announces itself after being rezzed |
| `GONE|<key>` | bot → loader | Bot announces it is about to be deleted |
| `CMD|<key>\|<cmd>` | loader → bot | Command directed at one bot (`<key>`) |
| `CMD|*|<cmd>` | loader → bot | Broadcast command to all bots |

Supported `<cmd>` values: `WANDER`, `STOP`, `FOLLOW`, `RETURN`, `DIE`.
