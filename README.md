# lsl-bot

An **in-world Second Life / OpenSimulator tool** that lets the owner load, manage,
and de-rez scripted avatar objects from a single touch-menu.

---

## Files

| File | Purpose |
|------|---------|
| `scripts/avatar_loader.lsl` | Controller script — place inside the loader prim |
| `scripts/avatar_behavior.lsl` | Behavior script — place inside every avatar object |
| `notecards/avatar_config.txt` | Sample `AvatarConfig` notecard template |

---

## Quick-start setup

### 1 — Prepare the avatar objects

1. Create (or import) one prim / linkset for each scripted avatar you want to rez.
2. Drop `avatar_behavior.lsl` into each avatar object's contents and save it.
3. Give each object a unique, memorable name (e.g. `Greeter Bot`).

### 2 — Prepare the loader prim

1. Create a new prim in-world and name it `Avatar Loader` (or anything you like).
2. Drop `avatar_loader.lsl` into the prim's contents.
3. Drop the `AvatarConfig` **notecard** into the same prim's contents.
   * The notecard must be named exactly `AvatarConfig`.
   * Edit the notecard to list your avatar object names and spawn offsets
     (see the format in `notecards/avatar_config.txt`).
4. Drop each avatar **object** into the loader prim's contents.

### 3 — Use the loader

* **Touch** the loader prim to open the management dialog.
* Select an avatar name to rez it in-world at the configured offset.
* Use **--- List ---** to see all configured avatars and how many are currently rezzed.
* Use **--- DeRez All ---** to remove all rezzed avatars.
* Use **--- Reload Config ---** to re-read the notecard (e.g. after editing it).

---

## AvatarConfig notecard format

```
# Lines beginning with '#' are comments
# Format:  ObjectName | x_offset,y_offset,z_offset

Greeter Bot  | 0.5,2.0,0.0
Guard Bot    | 5.0,0.0,0.0
Tour Guide   | 0.0,3.0,0.0
```

* `ObjectName` — must match the object name in the loader prim's inventory exactly.
* `x,y,z` — spawn offset in metres relative to the loader prim
  (X = East, Y = North, Z = Up).
* Omitting the offset field defaults to `0,0,0`.
* Maximum 12 entries (dialog button limit).

---

## Controlling rezzed avatars

All rezzed avatars listen on **channel −88776655** for commands.
You can send commands via the loader (future extension) or directly in-world chat
using a script with `llSay(-88776655, "cmd:...")`.

| Command | Effect |
|---------|--------|
| `cmd:derez` | Remove (die) the avatar |
| `cmd:wave` | Play the wave animation |
| `cmd:stop` | Stop movement and disable wandering |
| `cmd:wander` | Enable random wandering |
| `cmd:moveto\|x,y,z` | Move to world position x,y,z |
| `cmd:waypoint\|x,y,z\|x,y,z\|...` | Follow a looping waypoint path |
| `cmd:say\|text` | Say `text` on public chat |

---

## Behavior script settings

Open `scripts/avatar_behavior.lsl` and adjust these constants at the top of the
file to customise each avatar type:

| Constant | Default | Description |
|----------|---------|-------------|
| `ANIM_IDLE` | `"stand"` | Looped idle animation name |
| `ANIM_WALK` | `"walk"` | Looped walk animation name |
| `ANIM_WAVE` | `"wave"` | One-shot greeting animation |
| `WANDER_ENABLED` | `FALSE` | Enable random wandering on rez |
| `WANDER_RANGE` | `5.0` | Wander radius in metres |
| `WANDER_SPEED` | `2.0` | Movement speed (m/s) |
| `WANDER_PAUSE` | `4.0` | Pause between wander moves (s) |
| `SENSOR_RANGE` | `10.0` | Range to detect nearby avatars |
| `SENSOR_PERIOD` | `15.0` | How often to scan for avatars (s) |

---

## License

MIT
