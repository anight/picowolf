/*
 * frame_dump - capture what a program presents through the SDL2 window surface.
 *
 * Wolf4SDL's video path was moved off the renderer/texture API onto
 * SDL_GetWindowSurface() + SDL_UpdateWindowSurface(), which is the only path
 * PicoSDL offers.  This shim interposes on the present call so the frames that
 * reach the window can be inspected without a display and without adding a
 * debug hook to the game.
 *
 *   make -C tools/host
 *   cd Wolf4SDL
 *   SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy \
 *   WOLF_DUMP_DIR=/tmp/frames WOLF_DUMP_EVERY=20 WOLF_DUMP_MAX=12 \
 *   LD_PRELOAD=../tools/host/frame_dump.so ./wolf4sdl --windowed
 *
 * WOLF_DUMP_DIR     where to write frameNNNNN.bmp (default: cwd)
 * WOLF_DUMP_EVERY   save every Nth present (default 1)
 * WOLF_DUMP_MAX     stop after this many saved frames, 0 for no limit (default 0)
 * WOLF_DUMP_VERBOSE name every saved frame on stderr, so a debugger breakpoint
 *                   in the same log says which frames a given call produced
 *
 * The BMP is written from the window surface itself, so a wrong palette, a
 * missing blit or a frame that was never presented all show up in the output.
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <SDL2/SDL.h>

static int (*real_UpdateWindowSurface)(SDL_Window *);
static int (*real_UpdateWindowSurfaceRects)(SDL_Window *, const SDL_Rect *, int);

static const char *dump_dir = ".";
static unsigned    dump_every = 1;
static unsigned    dump_max;
static int         dump_verbose;
static unsigned    presents;
static unsigned    saved;

static void dump_init(void)
{
    static int done;
    const char *s;

    if (done)
        return;
    done = 1;

    real_UpdateWindowSurface = dlsym(RTLD_NEXT, "SDL_UpdateWindowSurface");
    real_UpdateWindowSurfaceRects = dlsym(RTLD_NEXT, "SDL_UpdateWindowSurfaceRects");

    if ((s = getenv("WOLF_DUMP_DIR")) != NULL && *s)
        dump_dir = s;
    if ((s = getenv("WOLF_DUMP_EVERY")) != NULL && atoi(s) > 0)
        dump_every = (unsigned)atoi(s);
    if ((s = getenv("WOLF_DUMP_MAX")) != NULL)
        dump_max = (unsigned)atoi(s);
    if ((s = getenv("WOLF_DUMP_VERBOSE")) != NULL && *s && *s != '0')
        dump_verbose = 1;
}

static void dump_frame(SDL_Window *window)
{
    SDL_Surface *surface;
    char path[1024];

    if (dump_max != 0 && saved >= dump_max)
        return;
    if (presents++ % dump_every != 0)
        return;

    surface = SDL_GetWindowSurface(window);
    if (surface == NULL) {
        fprintf(stderr, "frame_dump: no window surface: %s\n", SDL_GetError());
        return;
    }

    snprintf(path, sizeof(path), "%s/frame%05u.bmp", dump_dir, saved);
    if (SDL_SaveBMP(surface, path) != 0) {
        fprintf(stderr, "frame_dump: %s: %s\n", path, SDL_GetError());
        return;
    }

    if (saved == 0)
        fprintf(stderr, "frame_dump: %dx%d %s, pitch %d\n", surface->w, surface->h,
                SDL_GetPixelFormatName(surface->format->format), surface->pitch);
    if (dump_verbose)
        fprintf(stderr, "frame_dump: saved frame%05u\n", saved);
    saved++;
}

int SDL_UpdateWindowSurface(SDL_Window *window)
{
    dump_init();
    dump_frame(window);
    return real_UpdateWindowSurface(window);
}

int SDL_UpdateWindowSurfaceRects(SDL_Window *window, const SDL_Rect *rects, int numrects)
{
    dump_init();
    dump_frame(window);
    return real_UpdateWindowSurfaceRects(window, rects, numrects);
}
