#
# picowolf - Wolfenstein 3D on a Raspberry Pi Pico 2 W.
#
# This is the top-level build. Configure it directly:
#
#     cmake -S . -B build
#     cmake --build build
#
# and it produces build/picowolf.uf2, which picosdl/picodev.sh will program.
#
# The layout it assumes:
#
#   src/        main.c for the bring-up, wolf_main.c for the game
#   picosdl/    the SDL2 subset, a submodule and an independent library
#   Wolf4SDL/   the game, a submodule on its picowolf branch
#   tools/      the asset pipeline and the desktop-side helpers
#
# picosdl knows nothing about this project: it is added as a subdirectory and
# linked, the same way any other game would use it. Everything below that is
# specific to Wolfenstein lives here rather than in the library.
#
# The revision of each dependency is the submodule gitlink, so a picosdl that
# has moved under this build shows up as a modified submodule in git status
# rather than as a link error.
#
cmake_minimum_required(VERSION 3.13)

set(CMAKE_C_STANDARD 11)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

if(NOT CMAKE_BUILD_TYPE AND NOT CMAKE_CONFIGURATION_TYPES)
    set(CMAKE_BUILD_TYPE Release CACHE STRING "Build type" FORCE)
    set_property(CACHE CMAKE_BUILD_TYPE PROPERTY STRINGS
        Debug Release MinSizeRel RelWithDebInfo)
endif()

set(PICOWOLF_ROOT ${CMAKE_CURRENT_LIST_DIR})
set(PICOSDL_DIR   ${PICOWOLF_ROOT}/picosdl)
set(WOLF_DIR      ${PICOWOLF_ROOT}/Wolf4SDL)

foreach(dir ${PICOSDL_DIR}/src ${WOLF_DIR})
    if(NOT EXISTS ${dir})
        message(FATAL_ERROR
            "${dir} is missing - run: git submodule update --init --recursive")
    endif()
endforeach()

# Pico 2 W has the RP2350 and 4 MiB of flash.  PICO_BOARD can be overridden
# when configuring a different supported board.
set(PICO_BOARD pico2_w CACHE STRING "Board type")

# PicoSDL owns the Pico SDK bootstrap so every game using it finds the same SDK.
include(${PICOSDL_DIR}/cmake/pico_sdk_bootstrap.cmake)

project(picowolf C CXX ASM)
pico_sdk_init()

# Keep the library's standalone demo available alongside our minimal target:
# it remains the fastest way to separate board/PicoSDL faults from game faults.
set(PICOSDL_BUILD_DEMO ON CACHE BOOL "Build picosdl-demo for board bring-up")
add_subdirectory(${PICOSDL_DIR} picosdl)

# ------------------------------------------------------------- the bring-up
#
# No game code at all: it verifies the hardware and the PicoSDL integration
# independently of assets, rendering, input mapping and audio synthesis.
#
add_executable(picowolf-bringup
    src/main.c
)

target_link_libraries(picowolf-bringup PRIVATE picosdl)
target_compile_definitions(picowolf-bringup PRIVATE PICO_HEAP_SIZE=4096)
set_source_files_properties(src/main.c PROPERTIES COMPILE_OPTIONS "-Wall;-Wextra")

pico_enable_stdio_uart(picowolf-bringup 1)
pico_enable_stdio_usb(picowolf-bringup 1)
pico_add_extra_outputs(picowolf-bringup)

# ---------------------------------------------------------------- the game
#
# Wolf4SDL itself, built against PicoSDL and the converted resources.  The
# game's own Makefile is still the desktop build; this is the same sources
# with USE_FLASH_ASSETS so nothing opens a file, and USE_GPL so the OPL is
# DOSBox's DBOPL - the MAME one allocates in three places and there is no
# allocator here.
#
set(PICOWOLF_GENERATED ${PICOWOLF_ROOT}/generated CACHE PATH
    "Where tools/assets/convert.py put the converted resources")

set(WOLF_SOURCES
    id_ca.c id_in.c id_pm.c id_sd.c id_us.c id_vw.c signon.c
    wl_act1.c wl_act2.c wl_agent.c wl_atmos.c wl_cloudsky.c wl_debug.c
    wl_draw.c wl_game.c wl_inter.c wl_main.c wl_menu.c wl_parallax.c
    wl_plane.c wl_play.c wl_scale.c wl_shade.c wl_state.c wl_text.c
    wl_utils.c
    dosbox/dbopl.cpp dosbox/dbopl_adapter.cpp)
list(TRANSFORM WOLF_SOURCES PREPEND ${WOLF_DIR}/)

if(EXISTS ${PICOWOLF_GENERATED}/wolf_assets.c)
    add_executable(picowolf
        src/wolf_main.c
        ${WOLF_SOURCES}
        ${PICOWOLF_GENERATED}/wolf_assets.c
        ${PICOWOLF_GENERATED}/wolf_blobs.S)

    target_include_directories(picowolf PRIVATE
        ${WOLF_DIR}
        ${PICOWOLF_GENERATED}
        # Wolf includes <SDL.h>; PicoSDL ships it as <SDL2/SDL.h>, and putting
        # that directory on the path is cheaper than patching every include.
        ${PICOSDL_DIR}/include/SDL2)

    target_compile_definitions(picowolf PRIVATE
        PICOWOLF=1 USE_FLASH_ASSETS=1 USE_GPL=1)

    # .incbin paths in wolf_blobs.S are relative to the generated directory.
    set_source_files_properties(${PICOWOLF_GENERATED}/wolf_blobs.S PROPERTIES
        COMPILE_OPTIONS "-Wa,-I,${PICOWOLF_GENERATED}")

    # Vendored C++ with no runtime needs.
    set_source_files_properties(
        ${WOLF_DIR}/dosbox/dbopl.cpp ${WOLF_DIR}/dosbox/dbopl_adapter.cpp
        PROPERTIES COMPILE_OPTIONS
        "-fno-exceptions;-fno-rtti;-fno-threadsafe-statics")

    target_link_libraries(picowolf PRIVATE picosdl)
    target_compile_definitions(picowolf PRIVATE PICO_HEAP_SIZE=4096)

    pico_enable_stdio_uart(picowolf 1)
    pico_enable_stdio_usb(picowolf 1)
    pico_add_extra_outputs(picowolf)
else()
    message(STATUS
        "picowolf: no converted resources in ${PICOWOLF_GENERATED}, "
        "building the bring-up only.  Run tools/assets/convert.py.")
endif()
