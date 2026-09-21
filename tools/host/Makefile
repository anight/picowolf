# Host-side helpers for verifying the port before it goes near the board.
CFLAGS  ?= -O2 -g -Wall -Wextra -fPIC
CFLAGS  += $(shell sdl2-config --cflags)
LDFLAGS += -shared
LDLIBS  += -ldl

all: frame_dump.so resample_check

frame_dump.so: frame_dump.c
	$(CC) $(CFLAGS) $(LDFLAGS) $< $(LDLIBS) -o $@

# A plain host program, so none of the shared-object flags above apply.
resample_check: resample_check.c ../../Wolf4SDL/sd_mixer.h
	$(CC) -O2 -g -Wall -Wextra $< -lm -o $@

check: resample_check
	./resample_check

clean:
	rm -f frame_dump.so resample_check

.PHONY: all check clean
