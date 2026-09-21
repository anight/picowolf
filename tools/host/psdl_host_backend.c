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
    s_audio_freq = freq;
    s_audio_open = 1;
}

void psdl_backend_audio_close(void) { s_audio_open = 0; }
void psdl_backend_audio_pause(int pause_on) { s_audio_paused = pause_on; }
void psdl_backend_audio_lock(void) { }
void psdl_backend_audio_unlock(void) { }

static void pump_audio(Uint32 ms)
{
    int frames, blocks;

    if (!s_audio_open || s_audio_paused || !s_audio_freq)
        return;

    frames = (int)((Uint64)s_audio_freq * ms / 1000u);
    blocks = frames / PSDL_AUDIO_BLOCK_FRAMES;

    while (blocks-- > 0)
        psdl_audio_render(s_mix, PSDL_AUDIO_BLOCK_FRAMES);
}

/*
 * A virtual clock.  Wall time would make a run take as long as playing it
 * does; this advances only when the game asks to wait, so a capture finishes
 * as fast as the CPU allows and is the same every time.
 */
static Uint64 s_now_us;

Uint64 psdl_backend_ticks_us(void) { return s_now_us; }
Uint32 psdl_backend_ticks_ms(void) { return (Uint32)(s_now_us / 1000u); }

void psdl_backend_delay_ms(Uint32 ms)
{
    if (!ms)
        ms = 1;
    s_now_us += (Uint64)ms * 1000u;
    pump_audio(ms);
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
