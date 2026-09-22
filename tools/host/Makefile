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

digi_render: digi_render.c ../../Wolf4SDL/sd_mixer.h
	$(CC) -O2 -g -Wall -Wextra -I../../Wolf4SDL $< -o $@

#
# The game built against the real PicoSDL, on the desktop.
#
# The SDL2 host build answers "is the game right".  This answers "is the game
# right against PicoSDL", which is a different question and the one a wrong
# pixel - or a wrong sound - on the board is an answer to.  Everything above
# the backend is the code the firmware runs: the blitters, the surface pool,
# the arena, the palette-as-CLUT, the mixer.
#
# Deliberately not using sdl2-config here: <SDL.h> must resolve to PicoSDL's
# header, not the system's.
#
ROOT       := ../..
PSDL_DIR   := $(ROOT)/picosdl
WOLF_DIR   := $(ROOT)/Wolf4SDL
GEN_DIR    ?= $(ROOT)/generated
PSDL_OBJDIR := .objs-psdl

# The PSDL_HAVE_* set has to match what picosdl/CMakeLists.txt gives the
# firmware, because the library compiles its subsystems out without them - a
# build missing PSDL_HAVE_AUDIO links but has no mixer in it, which is exactly
# the thing being investigated here.
PSDL_DEFS  := -DPICOWOLF=1 -DUSE_FLASH_ASSETS=1 -DUSE_GPL=1 \
              -DPSDL_HAVE_AUDIO=1 -DPSDL_HAVE_JOYSTICK=1 -DPSDL_HAVE_GAMEPAD=1 \
              -DPSDL_COLOR_DEPTH=8
PSDL_INCS  := -I$(WOLF_DIR) -I$(GEN_DIR) -I$(PSDL_DIR)/include/SDL2 \
              -I$(PSDL_DIR)/include -I$(PSDL_DIR)/src
# -std=gnu11 to match the firmware build.  Wolf4SDL declares its own
# `typedef enum {false,true} boolean;`, which a C23 compiler rejects because
# false and true are keywords there.
PSDL_CFLAGS := -O2 -g -Wall -std=gnu11 $(PSDL_DEFS) $(PSDL_INCS)

WOLF_SRCS := id_ca.c id_in.c id_pm.c id_sd.c id_us.c id_vw.c signon.c \
             wl_act1.c wl_act2.c wl_agent.c wl_atmos.c wl_cloudsky.c wl_debug.c \
             wl_draw.c wl_game.c wl_inter.c wl_main.c wl_menu.c wl_parallax.c \
             wl_plane.c wl_play.c wl_scale.c wl_shade.c wl_state.c wl_text.c \
             wl_utils.c

PSDL_C_SRCS := $(wildcard $(PSDL_DIR)/src/*.c) \
               psdl_host_backend.c psdl_host_main.c \
               $(addprefix $(WOLF_DIR)/,$(WOLF_SRCS)) \
               $(GEN_DIR)/wolf_assets.c
PSDL_CXX_SRCS := $(WOLF_DIR)/dosbox/dbopl.cpp $(WOLF_DIR)/dosbox/dbopl_adapter.cpp

PSDL_OBJS := $(patsubst %,$(PSDL_OBJDIR)/%.o,$(notdir $(PSDL_C_SRCS))) \
             $(patsubst %,$(PSDL_OBJDIR)/%.o,$(notdir $(PSDL_CXX_SRCS))) \
             $(PSDL_OBJDIR)/wolf_blobs.S.o

vpath %.c $(PSDL_DIR)/src:$(WOLF_DIR):$(GEN_DIR):.
vpath %.cpp $(WOLF_DIR)/dosbox
vpath %.S $(GEN_DIR)

$(PSDL_OBJDIR):
	mkdir -p $@

$(PSDL_OBJDIR)/%.c.o: %.c | $(PSDL_OBJDIR)
	$(CC) $(PSDL_CFLAGS) -c $< -o $@

$(PSDL_OBJDIR)/%.cpp.o: %.cpp | $(PSDL_OBJDIR)
	$(CXX) -O2 -g -std=gnu++17 $(PSDL_DEFS) $(PSDL_INCS) -fno-exceptions -fno-rtti -c $< -o $@

# .incbin paths inside wolf_blobs.S are relative to the generated directory.
$(PSDL_OBJDIR)/wolf_blobs.S.o: wolf_blobs.S | $(PSDL_OBJDIR)
	$(CC) $(PSDL_CFLAGS) -Wa,-I,$(GEN_DIR) -c $< -o $@

psdl_wolf: $(PSDL_OBJS)
	$(CXX) $^ -lm -o $@

clean:
	rm -f frame_dump.so resample_check psdl_wolf digi_render
	rm -rf $(PSDL_OBJDIR)

.PHONY: all check clean
