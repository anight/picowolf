/*
 * A desktop backend for PicoSDL: the panel and the DAC replaced by a
 * directory of frames.
 *
 * The point is that everything above this file - the blitters, the surface
 * pool, the arena, the palette-as-CLUT, the event ring - is the same code the
 * firmware runs.  The SDL2 host build proves the game is right; this proves
 * the game is right *against PicoSDL*, which is a different question and the
 * one that a wrong pixel on the board is an answer to.
 *
 * What it does not reproduce: timing, DMA concurrency, and the radio.
 *
 * Modelled on picosdl/test/host_backend.c, which is BSD-2-Clause and does the
 * capture half of this already.
 *
 *   WOLF_FRAMEDIR    where to write frameNNNNN.pgm (default: none)
 *   WOLF_FRAME_EVERY write every Nth present (default 1)
 *   WOLF_MAX_FRAMES  stop after this many (default 300)
 *   WOLF_EXIT_AFTER  exit(0) after this many presents (default: never)
 *   WOLF_FRAMEHASH   print one hash per present instead of writing frames, so
 *                    two builds can be compared densely without touching disk
 *   WOLF_AUDIOFILE   write every rendered block here as raw signed 16-bit
 *                    stereo at the rate the game opened, so what the mixer
 *                    produced can be listened to and measured
 *   WOLF_AUDIOSECS   stop writing after this many seconds of audio (default 60)
 *   WOLF_AUTOKEY     press Return whenever the game stalls waiting for one, at
 *                    most this many times (default 0, off)
 *
 * The audio cap is not a convenience.  The clock below is virtual and advances
 * as fast as the CPU allows, so the mixer is pumped at whatever multiple of
 * real time this machine manages - a couple of minutes of wall time wrote 16 GB
 * before this existed.
 */
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/time.h>

#include "psdl_internal.h"

Uint8     host_last_frame[PSDL_SCREEN_W * PSDL_SCREEN_H];
int       host_present_count;
SDL_Color host_clut[256];

static const char *s_framedir;
static int s_every = 1, s_max = 300, s_exit_after, s_hash, s_written, s_read_env;
static int s_audio_secs;
static int s_autokey_budget;
static Uint64 s_last_present_us;
static const char *s_audiofile;
static FILE *s_audiofp;
static long s_audio_frames_max, s_audio_frames_written;

static void read_env(void)
{
    const char *s;

    if (s_read_env)
        return;
    s_read_env = 1;

    s_framedir = getenv("WOLF_FRAMEDIR");
    if ((s = getenv("WOLF_FRAME_EVERY")) && atoi(s) > 0) s_every = atoi(s);
    if ((s = getenv("WOLF_MAX_FRAMES")))                 s_max = atoi(s);
    if ((s = getenv("WOLF_EXIT_AFTER")))                 s_exit_after = atoi(s);
    if ((s = getenv("WOLF_FRAMEHASH")))                  s_hash = 1;
    s_audiofile = getenv("WOLF_AUDIOFILE");
    s_audio_secs = 60;
    if ((s = getenv("WOLF_AUDIOSECS")) && atoi(s) > 0) s_audio_secs = atoi(s);
    if ((s = getenv("WOLF_AUTOKEY")) && atoi(s) > 0)   s_autokey_budget = atoi(s);
}

/*
 * The retained panel, hashed.  It is the panel rather than the frame just
 * pushed because a partial update leaves the rest of the previous one on
 * screen, and that is exactly the state a single-buffered client depends on.
 */
static unsigned long frame_hash(void)
{
    unsigned long h = 1469598103934665603UL;
    size_t i;

    for (i = 0; i < sizeof(host_last_frame); i++) {
        h ^= host_last_frame[i];
        h *= 1099511628211UL;
    }
    for (i = 0; i < 256; i++) {
        h ^= (unsigned long)host_clut[i].r << 16 ^ (unsigned long)host_clut[i].g << 8
           ^ (unsigned long)host_clut[i].b;
        h *= 1099511628211UL;
    }
    return h;
}

/* A P6 PPM: the indices through the CLUT, so what is written is what a viewer
 * would have seen rather than the indices alone. */
static void write_frame(void)
{
    char  path[512];
    FILE *f;
    int   i;

    snprintf(path, sizeof(path), "%s/frame%05d.ppm", s_framedir, s_written);

    f = fopen(path, "wb");
    if (!f)
        return;

    fprintf(f, "P6\n%d %d\n255\n", PSDL_SCREEN_W, PSDL_SCREEN_H);
    for (i = 0; i < PSDL_SCREEN_W * PSDL_SCREEN_H; i++) {
        SDL_Color c = host_clut[host_last_frame[i]];
        fputc(c.r, f); fputc(c.g, f); fputc(c.b, f);
    }
    fclose(f);
    s_written++;
}

static void presented(void)
{
    read_env();
    host_present_count++;

    if (s_hash)
        printf("present %6d hash %016lx\n", host_present_count, frame_hash());
    else if (s_framedir && s_written < s_max && (host_present_count - 1) % s_every == 0)
        write_frame();

    if (s_exit_after && host_present_count >= s_exit_after) {
        fflush(stdout);
        exit(0);
    }
}

void psdl_backend_video_init(int w, int h)
{
    (void)w; (void)h;
    memset(host_last_frame, 0, sizeof(host_last_frame));
    host_present_count = 0;
}

/* Partial pushes accumulate and are never cleared: the real panel keeps what
 * it was last sent. */
void psdl_backend_video_present_rect(const Uint8 *pixels, int pitch,
                                     int x, int y, int w, int h)
{
    for (int row = 0; row < h; ++row) {
        int dy = y + row, cx = x, cw = w;
        if (dy < 0 || dy >= PSDL_SCREEN_H) continue;
        if (cx < 0) { cw += cx; cx = 0; }
        if (cx + cw > PSDL_SCREEN_W) cw = PSDL_SCREEN_W - cx;
        if (cw <= 0) continue;
        memcpy(host_last_frame + (size_t)dy * PSDL_SCREEN_W + cx,
               pixels + (size_t)dy * pitch + cx, (size_t)cw);
    }
    presented();
}

void psdl_backend_video_present(const Uint8 *pixels, int w, int h, int pitch)
{
    for (int y = 0; y < h && y < PSDL_SCREEN_H; ++y)
        memcpy(host_last_frame + (size_t)y * PSDL_SCREEN_W,
               pixels + (size_t)y * pitch,
               (size_t)(w < PSDL_SCREEN_W ? w : PSDL_SCREEN_W));
    presented();
}

void psdl_backend_video_sync(void) { }

int psdl_backend_video_buffer_busy(const void *pixels)
{
    (void)pixels;
    return 0;          /* the copy above is synchronous */
}

void psdl_backend_palette_set(int first, int ncolors, const SDL_Color *colors)
{
    for (int i = 0; i < ncolors; ++i)
        host_clut[first + i] = colors[i];
}

void psdl_backend_input_init(void) { }
void psdl_backend_input_poll(void) { }

/*
 * The mixer is pumped from the frame loop rather than by a device.
 *
 * Not for the sound - nothing here can play it - but because the game waits on
 * it.  SD_WaitSoundDone() spins until the AdLib channel goes quiet, and what
 * clears it is the mixer callback.  A backend that never calls it hangs the
 * game at the first sound that anything waits for.
 */
static int s_audio_open, s_audio_paused = 1, s_audio_freq;
static Sint16 s_mix[PSDL_AUDIO_BLOCK_FRAMES * 2];

void psdl_backend_audio_open(int freq, int channels, int block_frames)
{
    (void)channels; (void)block_frames;
    read_env();
    s_audio_freq = freq;
    s_audio_open = 1;
}

void psdl_backend_audio_close(void) { s_audio_open = 0; }
void psdl_backend_audio_pause(int pause_on) { s_audio_paused = pause_on; }
void psdl_backend_audio_lock(void) { }
void psdl_backend_audio_unlock(void) { }

/*
 * Blocks are accumulated rather than rounded down per call: at 22050 Hz a
 * one-millisecond wait is 22 frames and a 256-frame block is 11.6 ms, so
 * dividing each wait by the block size on its own would discard nearly every
 * one of them and the mixer would barely run.
 */
static int s_pending_frames;

static void pump_audio(Uint32 ms)
{
    if (!s_audio_open || s_audio_paused || !s_audio_freq)
        return;

    s_pending_frames += (int)((Uint64)s_audio_freq * ms / 1000u);

    while (s_pending_frames >= PSDL_AUDIO_BLOCK_FRAMES) {
        s_pending_frames -= PSDL_AUDIO_BLOCK_FRAMES;

        psdl_audio_render(s_mix, PSDL_AUDIO_BLOCK_FRAMES);

        if (s_audiofile) {
            if (!s_audiofp) {
                s_audiofp = fopen(s_audiofile, "wb");
                if (!s_audiofp) {
                    fprintf(stderr, "psdl_host: cannot write %s\n", s_audiofile);
                    s_audiofile = NULL;
                    continue;
                }
                s_audio_frames_max = (long)s_audio_secs * s_audio_freq;
                fprintf(stderr, "psdl_host: audio -> %s, %d Hz stereo s16, "
                        "stopping after %ds\n",
                        s_audiofile, s_audio_freq, s_audio_secs);
            }
            fwrite(s_mix, sizeof(Sint16), PSDL_AUDIO_BLOCK_FRAMES * 2, s_audiofp);
            s_audio_frames_written += PSDL_AUDIO_BLOCK_FRAMES;

            if (s_audio_frames_written >= s_audio_frames_max) {
                fprintf(stderr, "psdl_host: audio capture complete (%lds)\n",
                        s_audio_frames_written / s_audio_freq);
                fclose(s_audiofp);
                s_audiofp = NULL;
                s_audiofile = NULL;
            }
        }
    }
}

/*
 * A virtual clock.  Wall time would make a run take as long as playing it
 * does; this advances only when the game asks to wait, so a capture finishes
 * as fast as the CPU allows and is the same every time.
 */
static Uint64 s_now_us;

Uint64 psdl_backend_ticks_us(void) { return s_now_us; }
Uint32 psdl_backend_ticks_ms(void) { return (Uint32)(s_now_us / 1000u); }

/*
 * Press a key when, and only when, the game is stuck waiting for one.
 *
 * The opening screens - the signon summary, the notices - each sit in
 * IN_Ack() until something arrives, and this backend has no keyboard, so a run
 * that needs to get past them stops there for ever.  What must not happen is
 * pressing a key at any other time: one extra keystroke at the title screen
 * opens the main menu, and the attract demos - the only part of an unattended
 * run where the game plays sounds - never start.
 *
 * The distinction the backend can make is that a game doing anything at all
 * presents frames.  A stretch of virtual time with delays but no present is a
 * game waiting for input, and nothing else looks like that: the attract loop
 * draws continuously, and the brief waits inside a frame are far shorter than
 * this.
 */
#define AUTOKEY_STALL_US (2u * 1000u * 1000u)

static void autokey_check(void)
{
    if (s_autokey_budget <= 0)
        return;
    if (s_now_us - s_last_present_us < AUTOKEY_STALL_US)
        return;

    s_autokey_budget--;
    s_last_present_us = s_now_us;

    psdl_push_key(SDL_SCANCODE_RETURN, 1, 0);
    psdl_push_key(SDL_SCANCODE_RETURN, 0, 0);
}

void psdl_backend_delay_ms(Uint32 ms)
{
    if (!ms)
        ms = 1;
    s_now_us += (Uint64)ms * 1000u;
    pump_audio(ms);
    autokey_check();
}

static int s_volume = PSDL_DEFAULT_VOLUME;

void PSDL_SetMasterVolume(int volume)
{
    if (volume < 0) volume = 0;
    if (volume > PSDL_VOLUME_UNITY) volume = PSDL_VOLUME_UNITY;
    s_volume = volume;
}

int PSDL_GetMasterVolume(void) { return s_volume; }

void psdl_backend_log(const char *fmt, ...)
{
    va_list ap;
    va_start(ap, fmt);
    vfprintf(stderr, fmt, ap);
    va_end(ap);
    fflush(stderr);
}
