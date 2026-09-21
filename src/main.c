/*
 * PicoSDL-only board bring-up for picowolf.
 *
 * Keep this program free of Wolf4SDL headers and data.  A successful boot
 * establishes that the panel, palette path, input pump, USB console, and
 * PicoSDK integration work before game-specific code is introduced.
 */
#include <stdio.h>

#include "hardware/clocks.h"
#include "pico/stdlib.h"

#include "SDL2/SDL.h"
#include "psdl_pico.h"

enum {
    CANVAS_W = 320,
    CANVAS_H = 200,
    PAL_BLACK = 0,
    PAL_BLUE = 1,
    PAL_CYAN = 2,
    PAL_WHITE = 3,
};

/*
 * PicoSDL allocates no pixels, so the canvas is ours: 320x200 at one byte an
 * index, which is what the game will hand it too.  Static rather than on the
 * stack because the DMA chain reads from it after SDL_UpdateWindowSurface()
 * returns, and because a 62.5 KB frame is not a stack-sized object.
 */
static Uint8 canvas[CANVAS_W * CANVAS_H];

static void set_palette(void)
{
    SDL_Color palette[256] = {0};

    palette[PAL_BLUE] = (SDL_Color){ .r = 0x08, .g = 0x18, .b = 0x50, .a = SDL_ALPHA_OPAQUE };
    palette[PAL_CYAN] = (SDL_Color){ .r = 0x20, .g = 0xb0, .b = 0xd0, .a = SDL_ALPHA_OPAQUE };
    palette[PAL_WHITE] = (SDL_Color){ .r = 0xe0, .g = 0xe0, .b = 0xe0, .a = SDL_ALPHA_OPAQUE };

    SDL_SetPaletteColors(PSDL_GlobalPalette(), palette, 0, 256);
}

static void draw_frame(SDL_Surface *surface, unsigned frame)
{
    SDL_Rect band = { .x = 0, .w = CANVAS_W, .h = 20 };

    SDL_FillRect(surface, NULL, PAL_BLACK);
    for (int y = 0; y < CANVAS_H; y += band.h) {
        band.y = y;
        SDL_FillRect(surface, &band, ((unsigned)y / (unsigned)band.h + frame / 30u) & 1u
                                      ? PAL_BLUE : PAL_CYAN);
    }

    SDL_Rect marker = {
        .x = (int)(frame % (CANVAS_W - 24)), .y = 88, .w = 24, .h = 24,
    };
    SDL_FillRect(surface, &marker, PAL_WHITE);
}

int main(void)
{
    set_sys_clock_khz(PSDL_PICO_SYS_CLOCK_KHZ, true);
    stdio_init_all();
    sleep_ms(1500);

    printf("\n=== picowolf bring-up ===\n");
    printf("sys clock %u Hz\n", (unsigned)clock_get_hz(clk_sys));

    if (SDL_Init(SDL_INIT_VIDEO | SDL_INIT_EVENTS) != 0) {
        printf("SDL_Init failed: %s\n", SDL_GetError());
        for (;;) tight_loop_contents();
    }

    SDL_Window *window = PSDL_CreateWindow(canvas, CANVAS_W, CANVAS_H, CANVAS_W);
    if (window == NULL) {
        printf("PSDL_CreateWindow failed: %s\n", SDL_GetError());
        for (;;) tight_loop_contents();
    }

    SDL_Surface *surface = SDL_GetWindowSurface(window);
    if (surface == NULL) {
        printf("SDL_GetWindowSurface failed: %s\n", SDL_GetError());
        for (;;) tight_loop_contents();
    }

    set_palette();

    /*
     * The bands take RGB, not palette indices.  They are PicoSDL's overlay
     * rather than part of our indexed world, so they keep the colours asked
     * for whatever we do to the palette afterwards - which matters here,
     * because draw_frame() repaints the canvas every frame and a fade would
     * otherwise take the letterbox with it.
     */
    SDL_Color band_fg = { .r = 0xe0, .g = 0xe0, .b = 0xe0, .a = SDL_ALPHA_OPAQUE };
    SDL_Color band_bg = { .r = 0x00, .g = 0x00, .b = 0x00, .a = SDL_ALPHA_OPAQUE };

    PSDL_StatusBands(SDL_TRUE, band_fg, band_bg);
    PSDL_SetFooterText("picowolf: PicoSDL bring-up; Esc stops");

    for (unsigned frame = 0;; ++frame) {
        SDL_Event event;
        SDL_PumpEvents();
        while (SDL_PollEvent(&event)) {
            if (event.type == SDL_KEYDOWN &&
                event.key.keysym.scancode == SDL_SCANCODE_ESCAPE) {
                printf("bring-up stopped\n");
                SDL_Quit();
                for (;;) tight_loop_contents();
            }
        }

        draw_frame(surface, frame);
        SDL_UpdateWindowSurface(window);
        SDL_Delay(16);
    }
}

