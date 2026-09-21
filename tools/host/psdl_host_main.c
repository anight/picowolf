/*
 * Entry point for the PicoSDL host build.
 *
 * The firmware's src/wolf_main.c does the clock and stdio; there is nothing to
 * do here but pass the arguments through, so a capture can be steered with the
 * same options the desktop build takes.
 */
int WolfMain(int argc, char *argv[]);

int main(int argc, char *argv[])
{
    return WolfMain(argc, argv);
}
