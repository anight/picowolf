/*
 * Firmware entry point for the game.
 *
 * Wolf4SDL's own main() is WolfMain() here, because a program on this board
 * starts before there is a clock to run at or a console to print to, and ends
 * without anywhere to return to.  This is the part that differs; everything
 * after WolfMain() is the game exactly as the desktop build runs it.
 */
#include <stdio.h>

#include "hardware/clocks.h"
#include "pico/stdlib.h"

#include "SDL2/SDL.h"
#include "psdl_pico.h"

int WolfMain(int argc, char *argv[]);

/*
 * The command line the desktop build would have been given.
 *
 * --joystick 0 is the board's controller, and there is only ever one: PicoSDL
 * reports a single joystick whether the analog stick, the I2C pad or both are
 * fitted, because both feed the same axes and a client that finds a controller
 * stops looking for joysticks.
 *
 * tools/host/play.sh passes -1 instead, which is a desktop workaround: there,
 * joystick 0 can be whatever SDL enumerated - on this machine a keyboard's
 * "System Control" collection, parked off-centre.  Carrying that over to the
 * board disabled the stick and the pad together.
 */
static char  arg0[] = "picowolf";
static char  arg1[] = "--joystick";
static char  arg2[] = "0";
static char *args[] = { arg0, arg1, arg2, NULL };

int main(void)
{
    /* Before stdio_init_all(): changing the clock re-parents clk_peri, and a
     * UART set up at the old rate would then have the wrong baud. */
    set_sys_clock_khz(PSDL_PICO_SYS_CLOCK_KHZ, true);
    stdio_init_all();
    sleep_ms(1500);

    printf("\n=== picowolf ===\n");
    printf("sys clock %u Hz\n", (unsigned)clock_get_hz(clk_sys));

    /*
     * The letterbox.  The panel is 320x240 and the game is 320x200, so there
     * are twenty rows above and below that would otherwise be black.  PicoSDL
     * puts the frame rate and the per-core load in the top one and whatever
     * text it is given in the bottom one.
     *
     * The colours are RGB rather than palette indices, and that is the point:
     * the bands are PicoSDL's overlay, not part of the game's indexed world.
     * Wolf fades the palette to black between every screen and flashes entry
     * 0 red when the player is hit - bands drawn in indices would follow both.
     *
     * Set before WolfMain() rather than inside it: PSDL_StatusBands only
     * records what to paint, the painting happens at present time, and this
     * is a choice the firmware makes rather than anything the game knows.
     */
    static const SDL_Color band_fg = { 255, 255, 255, SDL_ALPHA_OPAQUE };
    static const SDL_Color band_bg = {   0,   0,   0, SDL_ALPHA_OPAQUE };

    PSDL_StatusBands(SDL_TRUE, band_fg, band_bg);
    PSDL_SetFooterText("github.com/anight/picowolf");

    WolfMain((int)(sizeof(args) / sizeof(args[0])) - 1, args);

    /*
     * WolfMain() does not return: Quit() is what ends the game, and on this
     * board that means saying so on the console and stopping, because there is
     * no shell waiting for an exit status and a reboot would only hide it.
     */
    printf("picowolf: the game returned, which it should not\n");

    for (;;)
        tight_loop_contents();
}
