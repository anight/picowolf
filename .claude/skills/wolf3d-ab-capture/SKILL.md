---
name: wolf3d-ab-capture
description: >-
  Capture video and audio from the picowolf/Wolf4SDL port and from the original
  DOS Wolfenstein 3D under DOSBox-X, drive either of them with synthetic
  keystrokes, and compare the two captures frame by frame and sample by sample.
  Use this whenever the task involves checking the port against the original,
  reproducing a rendering or sound difference, capturing what a PicoSDL or SDL2
  game actually put on screen or sent to the mixer, driving a game or emulator
  without a human at the keyboard, or comparing two captures of the same game -
  and also when someone asks why xdotool, screenshots or screen recording are
  not working on this machine, because the answer is in here.
---

# Capturing and comparing Wolfenstein 3D, port against original

Two programs play the same game from the same data: `Wolf4SDL` built for the
host, and the original 1992 DOS executable under DOSBox-X. This is how to make
both of them run unattended, record what they produced, and compare it.

The point of comparing is to find where the port diverges from the original.
That only works if the comparison is of the things the port is responsible for,
which is most of what this document is about.

## Before anything else: check for Wayland

```bash
echo "$XDG_SESSION_TYPE"
```

If that says `wayland`, **synthetic input and screen capture do not work on the
desktop**, and no amount of fixing the command line will change it:

- `xdotool key` reaches nothing. The game window lives under XWayland, the
  compositor owns the keyboard, and the window that X reports as focused is a
  1x1 unnamed window with no `WM_CLASS` and no `_NET_WM_PID` - XWayland's focus
  proxy. `xdotool getwindowfocus` will happily name your window while every
  keystroke goes somewhere else.
- `ffmpeg -f x11grab` returns solid black, because XWayland windows are not
  composited into the X root window that x11grab reads.

Both symptoms look like application bugs and are not. They are identical for
SDL1 and SDL2 programs, so switching emulators does not help.

There is a second reason to care beyond it not working: keystrokes aimed at a
window that is not receiving them land on whatever *is* focused, which is the
user's own editor or terminal. Do not type into a desktop you do not control.

**The fix is a private X server.** Inside Xvfb there is no compositor, so input
and capture behave the way the manuals say, and nothing can touch the user's
session.

```bash
Xvfb :99 -screen 0 1280x1024x24 -nolisten tcp -noreset &
DISPLAY=:99 xdpyinfo | head -3        # confirm it is up
```

Everything below runs with `DISPLAY=:99`.

## Driving a game with keystrokes

The mechanics are the same for the emulator and for the SDL2 host build,
because both are ordinary X clients once they are on the Xvfb display. What
differs is only how you start them.

### Find the window, and be sure which one

An SDL program usually maps more than one X window. Picking the wrong one is
the classic way to lose keystrokes, so take the last match and confirm its name:

```bash
WIN=$(DISPLAY=:99 xdotool search --name "DOSBox-X" | tail -1)
DISPLAY=:99 xdotool getwindowname "$WIN"
```

There is no window manager on a bare Xvfb, so `windowactivate` has nothing to
talk to. Set the input focus directly:

```bash
DISPLAY=:99 xdotool windowfocus "$WIN"
sleep 1
DISPLAY=:99 xdotool key --clearmodifiers Return
```

### Confirm the key arrived, do not assume it

Focus reporting correctly does not mean the program received anything. The
reliable check is whether the picture changed:

```bash
grab() { DISPLAY=:99 ffmpeg -loglevel error -f x11grab \
    -video_size "${W}x${H}" -i ":99.0+$X,$Y" -frames:v 1 -y "$1"; }

grab /tmp/before.png
DISPLAY=:99 xdotool key --clearmodifiers Return
sleep 3
grab /tmp/after.png
cmp -s /tmp/before.png /tmp/after.png && echo "key did NOT arrive"
```

Use that shape - press, look, press again only if nothing moved - whenever a
script has to drive a game through a screen. Note that the converse does not
hold: an unchanged picture does *not* prove the key was missed once the game is
running, because the attract sequence holds some screens still for twenty
seconds. It is only a reliable test on a screen you know is waiting for input.

### Getting past the opening screens

Both programs open on a run of screens that each wait for a key - the signon
summary, the "this game is NOT shareware" notice, the content rating card - and
only then reach the title and the attract loop: title, credits, high scores and
the recorded demos, all on the game's own timers.

The attract demos are what you want to compare. They are recorded input
replayed deterministically, so both programs do the same thing at the same time
by construction rather than by luck of timing.

`tools/dosbox/clear_intro.sh` gets a game there and stops. Call it with the
display, window and geometry; it works for the emulator and the host build
alike, because by then both are just X clients.

Four approaches that look right and are not. Each of these was tried and each
produced a capture that looked successful and contained nothing:

- **`NOWAIT` / `--nowait`.** Reads exactly like the switch for this, and it is
  the opposite: `while (!param_nowait)` in `wl_main.c` wraps the *whole attract
  loop*, not just the `IN_Ack()` waits. The game walks past the title to the
  main menu and sits there. A capture made with it contains a menu, and if you
  pass it to both sides you get two recordings of nothing that agree with each
  other 0.3% of the time.
- **Pressing a fixed number of times.** The count belongs to the build and the
  version. One short parks the capture on a notice for its whole length; one too
  many opens the main menu from the title screen, and the attract loop never
  starts.
- **Counting distinct colours** to tell a flat text notice from the title
  picture. Fires immediately with zero keys pressed, because the signon screen
  is itself a full 320x200 image - `signon[]`, 64,000 bytes of it.
- **Watching for the screen to change** as proof a key landed. True only on a
  screen you already know is waiting. Once the attract loop is running it holds
  the title, the credits and the high scores still for ten to twenty seconds at
  a time, so "unchanged" means nothing there.

What does separate them is time, not pixels: **a waiting screen waits forever,
and the title screen gives up after fifteen seconds and moves on by itself.**
So press a key, then watch for twenty seconds without touching anything. If the
picture moves on its own, the attract loop is running and you stop. If it sits
there, that was another notice and it needs one more key. That test does not
care how many notices a build shows.

**Check the capture afterwards, not the screen during it.** A run parked on a
notice produces a file of exactly the right size and duration and looks like a
success until something tries to compare it. Sample the recording: a parked
game is the one case where every frame is identical.

```bash
ffmpeg -loglevel error -i video.mkv -vf 'fps=1/5' -y /tmp/f%03d.png
md5sum /tmp/f*.png | awk '{print $1}' | sort -u | wc -l   # 1 means parked
```

Do this before computing any comparison, and look at one frame with your own
eyes before believing a table of numbers. Both capture scripts print the count.

### Sending keys to the host build

The port's host binary normally runs with `SDL_VIDEODRIVER=dummy`, which is
right for capturing frames (see below) but means there is no window and
therefore no way to send it anything. To drive it with keys, give it a real
window on the Xvfb display instead:

```bash
DISPLAY=:99 SDL_VIDEODRIVER=x11 ./wolf4sdl --windowed --nowait --joystick -1 &
```

Then find the window and send keys exactly as above - it maps one window
named `Wolfenstein 3D`, and the keys arrive (verified on this machine). Note
that its window is 1:1 at 320x200, where DOSBox-X's is the same picture doubled
to 640x400, so a grab of the port needs no halving and a grab of the emulator
does.

Pass `--joystick -1`. Wolf4SDL opens joystick 0 by default and SDL enumerates
some USB keyboards as joysticks; a stick resting off centre overwrites the
direction the keyboard just produced, and the menu becomes unusable. This is
upstream behaviour, not a port bug.

## Capturing video

### From the emulator: grab the X window

```bash
eval "$(DISPLAY=:99 xdotool getwindowgeometry --shell "$WIN")"
DISPLAY=:99 ffmpeg -loglevel error -f x11grab -framerate 70 \
    -video_size "${WIDTH}x${HEIGHT}" -i ":99.0+$X,$Y" \
    -t 120 -c:v ffv1 -level 3 -y video.mkv
```

Lossless (`ffv1`), so the comparison is against the emulator's pixels and not
an encoder's idea of them. 70 fps is the mode 13h refresh rate.

Configure the emulator so the window is the game's pixels doubled exactly -
`scaler=none`, `aspect=false` - and the capture halves back to 320x200 with
`scale=320:200:flags=neighbor` without guessing what was interpolated.
`tools/dosbox/reference-x.conf` is that configuration, plus `core=normal` and
`cycles=fixed` so two runs agree with each other.

DOSBox-X's own capture hotkeys (Ctrl+Alt+F5 and friends) are a dead end for
scripting: they are mapper actions, they need synthetic input to reach the
mapper, and there is no config option to start a capture. Grabbing the window
sidesteps the whole question.

### From the host build: intercept the presented surface

Better than grabbing, when it is available: `tools/host/frame_dump.so` is an
`LD_PRELOAD` shim over `SDL_UpdateWindowSurface()` that writes each presented
frame as a BMP. It captures exactly what reached the surface, needs no display
at all, and cannot miss or duplicate a frame the way a fixed-rate grab can.

```bash
SDL_VIDEODRIVER=dummy WOLF_DUMP_DIR=frames WOLF_DUMP_EVERY=3 \
WOLF_DUMP_MAX=400 LD_PRELOAD=tools/host/frame_dump.so \
./wolf4sdl --windowed --joystick -1
```

Use the dummy video driver here when nothing has to be typed: you do not need a
window to capture frames, and not having one keeps the run off any display.

The catch, and why `tools/host/capture.sh` grabs the window instead: the shim
starts dumping at the first present, so the opening notices spend the whole
frame budget before the attract sequence begins - and with dummy video there is
no window to send the keys that would get past them. The port's window is 1:1
at 320x200 with no compositor in the way, so grabbing it yields the surface
pixels anyway.

## Both sides must be the same release of the game

Before comparing anything, check that the two programs are reading the same
data. Wolfenstein 3D shipped in several releases whose files share names and
extensions and differ throughout, and nothing in either program complains.

The cheap discriminator is the graphics chunk count, which is `VGAHEAD` divided
by three (it holds 3-byte offsets, plus a terminator):

```bash
python3 -c "import os; s=os.path.getsize('vgahead.wl6'); print(s//3 - 1)"
```

Compare that against the `NUMCHUNKS` of the shipped `gfxv_*.h` headers: 149 is
v1.4 GT/ID/Activision (`gfxv_wl6.h`), 158 is Apogee v1.1 or v1.2, 161 is Apogee
v1.4. `VSWAP`'s first six bytes (chunk count, first sprite, first sound) and
`MAPHEAD`'s RLEW tag confirm the family but not the release - two different
releases agree on all of those.

Mixing releases invalidates everything downstream: different graphics chunk
numbering, different audio, different maps, and the attract demos are recorded
input replayed against map and actor data that no longer matches, so the two
runs diverge by construction rather than because of any port defect.

## Capturing audio

Both programs are SDL2, so both can be captured the same way, with **SDL's disk
audio driver**: it writes what the mixer produced to a file instead of to a
sound card. No sound hardware, no capture hotkey, no mixing with anything else
on the machine.

```bash
SDL_AUDIODRIVER=disk SDL_DISKAUDIOFILE=audio.raw ./program
```

The output is raw samples in whatever format the program asked for - for these
two, 44100 Hz stereo signed 16-bit little-endian, if you ask the port for
`--samplerate 44100` and set the emulator's mixer to 44100. Because both sides
come out of the same driver in the same format, nothing resamples between them.

Two things to know:

- **Do not set `SDL_DISKAUDIODELAY=0`.** The default delays by the buffer
  duration, which paces the capture at real time and keeps it lined up with the
  video. With zero delay the callback runs flat out: 168 MB of audio in thirty
  seconds, uncorrelated with anything on screen.
- **Check the pacing early.** File size divided by `rate * channels * 2` should
  equal the wall-clock seconds elapsed. If it is running ahead, the delay is
  wrong and the capture is worthless for comparison.

## Comparing video

**Compare palette indices, not RGB.** A VGA DAC takes 6 bits per channel, and
the two paths widen them to 8 bits differently - Wolf4SDL computes `r*255/63`,
DOSBox-X has its own scaling. Comparing RGB reports every pixel of an identical
picture as a difference. Which palette entry each pixel got is what the port is
responsible for, and it is exact.

`tools/dosbox/compare_video.py` does this: it loads `gamepal` from
`Wolf4SDL/wolfpal.inc`, maps both sides to nearest palette entries, and reports
how much of each frame agrees.

```bash
tools/dosbox/compare_video.py --dos captures/dos/video.mkv --pw captures/pw/frames
```

It also reports how far each frame sat from the palette ("palette fit"). Near
zero means the frame really is drawn from `gamepal` and the index comparison is
meaningful. A large value means the game had faded the palette, and comparing
indices against the unfaded table says nothing - expect this during fades and
do not read the percentages then.

Three mistakes that produce confident nonsense:

- **Integer overflow in the distance.** A squared channel difference reaches
  `255*255 = 65025`, which does not fit in `int16`. In numpy, `.astype(np.int16)`
  on the pixels turns every distance into noise; the symptom is `nan` distances
  and every frame matching every other frame identically. Use `int32`.
- **Comparing per pixel instead of per colour.** An indexed frame holds at most
  256 distinct colours however many pixels it has. Mapping the unique colours
  and scattering the result back is hundreds of distance computations instead of
  tens of thousands, and turns minutes into seconds.
- **Believing a uniform result.** If every sampled frame reports the same match
  against the same frame, nothing is being compared - either the extraction
  produced identical frames (the game never advanced past a screen waiting for a
  key) or the mapping is broken. Look at one extracted frame before trusting any
  table of numbers.

## Comparing audio

The two runs are not synchronised: each started its attract sequence when it
felt like it, and the emulator's capture begins when the emulator starts rather
than when the game does. Align first, compare second.

Align on **energy envelopes**, not samples. Correlating samples requires two OPL
renderings to agree phase for phase over minutes, which they never will;
correlating energy per 10 ms only requires the same notes at the same times,
which is the thing being checked.

```bash
tools/dosbox/compare_audio.py --dos captures/dos/audio.raw --pw captures/pw/audio.raw
```

Expect a high correlation but not 1.0, and say so rather than treating the gap
as a defect. The music is the same IMF data driving the same DBOPL in both, but
DOSBox-X renders the OPL at its own rate and resamples to the mixer rate
differently than the port does, and the digitised sounds are resampled
differently again. The comparison characterises the gap; it does not demand a
match.

## Checklist for a new comparison run

1. `echo $XDG_SESSION_TYPE` - if `wayland`, use Xvfb, and never the desktop.
2. Start Xvfb, confirm with `xdpyinfo`.
3. Start the program; find its window by name, take the last match.
4. Press keys one at a time, checking the picture changed after each.
5. Start the video and audio captures; check the audio file grows at real time.
6. Let the attract demos play - they are the deterministic part.
7. Compare indices for video, envelopes for audio.
8. Before reporting numbers, look at one frame from each side.
