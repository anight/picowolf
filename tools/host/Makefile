# Host-side helpers for verifying the port before it goes near the board.
CFLAGS  ?= -O2 -g -Wall -Wextra -fPIC
CFLAGS  += $(shell sdl2-config --cflags)
LDFLAGS += -shared
LDLIBS  += -ldl

all: frame_dump.so

frame_dump.so: frame_dump.c
	$(CC) $(CFLAGS) $(LDFLAGS) $< $(LDLIBS) -o $@

clean:
	rm -f frame_dump.so

.PHONY: all clean
