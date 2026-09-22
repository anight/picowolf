/*
 * Render one digitised sound through the port's own mixer arithmetic.
 *
 * The point is that this is not a reimplementation: it includes sd_mixer.h and
 * calls SD_ResampleStep(), SD_ResampleSample() and SD_MixSample(), so what
 * comes out is what the board's mixer would produce for that sound, panned the
 * way the game would pan it.  A sound that is wrong here is wrong on the
 * board, and a sound that is right here is wrong somewhere else.
 *
 *   digi_render <raw-8bit-7042Hz-in> <wav-out> [outrate] [leftpos] [rightpos]
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>

#include "sd_mixer.h"

static void put32(FILE *f, unsigned v) { fputc(v,f); fputc(v>>8,f); fputc(v>>16,f); fputc(v>>24,f); }
static void put16(FILE *f, unsigned v) { fputc(v,f); fputc(v>>8,f); }

int main(int argc, char **argv)
{
    const char *inpath, *outpath;
    int outrate = 22050, leftpos = 0, rightpos = 0;
    long n;
    uint8_t *src;
    FILE *f;

    if (argc < 3) {
        fprintf(stderr,"usage: %s <raw in> <wav out> [rate] [leftpos] [rightpos]\n",argv[0]);
        return 2;
    }
    inpath = argv[1]; outpath = argv[2];
    if (argc > 3) outrate  = atoi(argv[3]);
    if (argc > 4) leftpos  = atoi(argv[4]);
    if (argc > 5) rightpos = atoi(argv[5]);

    f = fopen(inpath,"rb");
    if (!f) { perror(inpath); return 1; }
    fseek(f,0,SEEK_END); n = ftell(f); fseek(f,0,SEEK_SET);
    src = malloc(n);
    if (fread(src,1,n,f) != (size_t)n) { perror("read"); return 1; }
    fclose(f);

    /* The gains the game would set, including the clamp. */
    int left  = 255 - (leftpos  * 28);
    int right = 255 - (rightpos * 28);
    if (left  < 0) left  = 0;
    if (right < 0) right = 0;

    uint64_t step = SD_ResampleStep(SD_DIGIRATE,(unsigned)outrate);
    long frames = (long)((double)n * outrate / SD_DIGIRATE) + 2;

    int16_t *out = calloc(frames * 2, sizeof(int16_t));
    uint64_t pos = 0;
    long produced = 0;

    for (long i = 0; i < frames; i++) {
        if ((int64_t)(pos >> 32) >= (int)n)
            break;
        int s = SD_ResampleSample(src,(int)n,pos);
        pos += step;
        SD_MixSample(&out[i*2],     (s * left)  >> 8);
        SD_MixSample(&out[i*2 + 1], (s * right) >> 8);
        produced++;
    }

    f = fopen(outpath,"wb");
    if (!f) { perror(outpath); return 1; }
    unsigned bytes = (unsigned)produced * 4;
    fwrite("RIFF",1,4,f); put32(f, 36 + bytes); fwrite("WAVE",1,4,f);
    fwrite("fmt ",1,4,f); put32(f,16); put16(f,1); put16(f,2);
    put32(f,(unsigned)outrate); put32(f,(unsigned)outrate*4); put16(f,4); put16(f,16);
    fwrite("data",1,4,f); put32(f,bytes);
    fwrite(out,1,bytes,f);
    fclose(f);

    fprintf(stderr,"%ld source bytes (%.3f s at %d Hz) -> %ld frames at %d Hz, gains %d/%d\n",
            n, (double)n/SD_DIGIRATE, SD_DIGIRATE, produced, outrate, left, right);
    return 0;
}
