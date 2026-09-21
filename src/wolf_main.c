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
 * The command line the desktop build would have been given.  --joystick -1
 * because Wolf4SDL opens joystick 0 by default and that is not how the board's
 * controller should be found; when the input rework names its devices this
 * goes with it.
 */
static char  arg0[] = "picowolf";
static char  arg1[] = "--joystick";
static char  arg2[] = "-1";
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
