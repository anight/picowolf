/*
 * Does the fixed-point resampler match the float one it replaced?
 *
 * SD_PrepareSound() used to expand every digitised sound to the device rate
 * once, in 16-bit, through a float Lagrange quadratic (GetSample), and cache
 * the result.  The mixer now steps a 32.32 cursor through the 8-bit source as
 * it plays and interpolates linearly, which is what makes the sounds free of
 * RAM - but it is a different interpolator, so "no regression" has to be
 * measured rather than assumed.
 *
 * This renders the same sources both ways and reports SNR.  The reference is
 * the old code, copied verbatim from before the change.
 *
 *   make -C tools/host resample_check && tools/host/resample_check
 */
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "../../Wolf4SDL/sd_mixer.h"

/* ------------------------------------------------- the reference ------ */
/*
 * id_sd.c before the mixer landed.  Unchanged apart from the types, which
 * came from SDL.
 */
static int16_t GetSample(float csample, unsigned char *samples, int size)
{
    float s0=0, s1=0, s2=0;
    int cursample = (int) csample;
    float sf = csample - (float) cursample;

    if(cursample-1 >= 0) s0 = (float) (samples[cursample-1] - 128);
    s1 = (float) (samples[cursample] - 128);
    if(cursample+1 < size) s2 = (float) (samples[cursample+1] - 128);

    float val = s0*sf*(sf-1)/2 - s1*(sf*sf-1) + s2*(sf+1)*sf/2;
    int32_t intval = (int32_t) (val * 256);
    if(intval < -32768) intval = -32768;
    else if(intval > 32767) intval = 32767;
    return (int16_t) intval;
}

/* ------------------------------------------------- the sources -------- */

static void fill_sine(unsigned char *p, int n, double hz)
{
    for (int i = 0; i < n; i++) {
        double v = 127.0 * sin(2.0 * M_PI * hz * i / SD_DIGIRATE);
        int    s = (int) lrint(128.0 + v);
        p[i] = (unsigned char) (s < 0 ? 0 : s > 255 ? 255 : s);
    }
}

static void fill_noise(unsigned char *p, int n)
{
    unsigned x = 12345;
    for (int i = 0; i < n; i++) { x = x * 1103515245u + 12345u; p[i] = (unsigned char)(x >> 16); }
}

/* A gunshot-ish shape: noise under a fast decay, which is most of VSWAP. */
static void fill_burst(unsigned char *p, int n)
{
    unsigned x = 999;
    for (int i = 0; i < n; i++) {
        x = x * 1103515245u + 12345u;
        double env = exp(-4.0 * i / (double) n);
        int    s   = (int) lrint(128.0 + ((int)((x >> 16) & 0xff) - 128) * env);
        p[i] = (unsigned char) (s < 0 ? 0 : s > 255 ? 255 : s);
    }
}

/* ------------------------------------------------- the comparison ----- */

/*
 * The last frame is reported apart.  Where the source runs out the reference
 * takes its third point as 0, so it interpolates the tail down towards
 * silence; this holds the final sample instead.  That is one frame of every
 * sound and it is the larger difference of the two, so averaging it in would
 * hide what the interior does.
 */
static double snr_db(const unsigned char *src, int n, int outrate, const char *what)
{
    int      frames = (int) ((int64_t) n * outrate / SD_DIGIRATE) - 2;
    double   sig = 0, err = 0, worst = 0, tail = 0;
    uint64_t step = SD_ResampleStep(SD_DIGIRATE, (unsigned) outrate);
    uint64_t pos  = 0;

    if (frames < 16) { printf("  %-22s too short\n", what); return 0; }

    for (int i = 0; i < frames; i++) {
        double ref = GetSample((float) i * (float) SD_DIGIRATE / (float) outrate,
                               (unsigned char *) src, n);
        double got = SD_ResampleSample(src, n, pos);
        double d   = got - ref;

        pos += step;

        if (i == frames - 1) { tail = fabs(d); continue; }

        sig += ref * ref;
        err += d * d;
        if (fabs(d) > worst) worst = fabs(d);
    }

    double snr = err > 0 ? 10.0 * log10(sig / err) : 1e9;
    printf("  %-22s %6d Hz  SNR %5.1f dB  worst interior %5.0f (%4.1f%% FS)  tail %5.0f\n",
           what, outrate, snr, worst, 100.0 * worst / 32768.0, tail);
    return snr;
}

int main(void)
{
    enum { N = 8192 };
    static unsigned char sine[N], noise[N], burst[N];
    int    fails = 0;
    double snr;

    fill_sine(sine, N, 440.0);
    fill_noise(noise, N);
    fill_burst(burst, N);

    printf("fixed-point linear resampler vs the float quadratic it replaced\n");
    printf("(they are different interpolators, so this characterises the gap\n");
    printf(" rather than demanding a match; noise disagrees most because at\n");
    printf(" 7042 Hz consecutive samples are unrelated)\n\n");

    for (int r = 0; r < 3; r++) {
        int rate = (int[]){ 44100, 22050, 11025 }[r];
        printf(" at %d Hz:\n", rate);
        snr = snr_db(sine,  N, rate, "440 Hz sine");        if (snr < 30) fails++;
        snr = snr_db(burst, N, rate, "decaying noise burst"); if (snr < 10) fails++;
        snr = snr_db(noise, N, rate, "white noise");         if (snr <  3) fails++;
        printf("\n");
    }

    /* Properties that must hold regardless of interpolator. */
    printf(" properties:\n");

    if (SD_ResampleSample(NULL, 100, 0) != 0) { printf("  FAIL null source is not silent\n"); fails++; }
    else printf("  null source is silent\n");

    if (SD_ResampleSample(sine, 10, (uint64_t)10 << 32) != 0) { printf("  FAIL past the end is not silent\n"); fails++; }
    else printf("  past the end is silent\n");

    {
        static unsigned char centre[64];
        memset(centre, 128, sizeof centre);
        int bad = 0;
        uint64_t p = 0, st = SD_ResampleStep(SD_DIGIRATE, 44100);
        for (int i = 0; i < 200; i++, p += st)
            if (SD_ResampleSample(centre, (int) sizeof centre, p) != 0) bad++;
        if (bad) { printf("  FAIL a constant 128 is not silence (%d samples off)\n", bad); fails++; }
        else printf("  a constant 128 is exactly silence, no DC\n");
    }

    {
        int16_t s = 30000;
        SD_MixSample(&s, 30000);
        if (s != 32767) { printf("  FAIL saturation: got %d\n", s); fails++; }
        else printf("  mixing saturates instead of wrapping\n");
        s = -30000;
        SD_MixSample(&s, -30000);
        if (s != -32768) { printf("  FAIL negative saturation: got %d\n", s); fails++; }
        else printf("  and saturates negative too\n");
    }

    printf(fails ? "\n%d FAILED\n" : "\nall checks passed\n", fails);
    return fails != 0;
}
