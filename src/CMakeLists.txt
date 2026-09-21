#
# picowolf - Wolf4SDL on a Raspberry Pi Pico 2 W.
#
# Configure from the repository root with:
#
#   cmake -S src -B build
#   cmake --build build
#
# This initial target deliberately contains no game code.  It verifies the
# hardware and PicoSDL integration independently before the Wolf port adds
# assets, rendering, input mapping, and audio synthesis.
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

set(PICOWOLF_ROOT ${CMAKE_CURRENT_LIST_DIR}/..)
set(PICOSDL_DIR ${PICOWOLF_ROOT}/picosdl)

if(NOT EXISTS ${PICOSDL_DIR}/src)
    message(FATAL_ERROR
        "${PICOSDL_DIR} is missing - initialise the picosdl submodule/dependency")
endif()

# Pico 2 W has the RP2350 and 4 MiB of flash.  PICO_BOARD can be overridden
# when configuring a different supported board.
set(PICO_BOARD pico2_w CACHE STRING "Board type")

#
# The PicoSDL revision this was last built and flashed against.  picosdl_version.cmake
# checks it on every build and explains itself if it has moved; bump this once
# the build is happy with a newer one.
#
set(PICOSDL_EXPECTED_COMMIT "cc5894d5d2d92c44f3c8afb6dafa40427d3aa3f0")

# PicoSDL owns the Pico SDK bootstrap so every game using it finds the same SDK.
include(${PICOSDL_DIR}/cmake/pico_sdk_bootstrap.cmake)

project(picowolf C CXX ASM)
pico_sdk_init()

# Keep the library's standalone demo available alongside our minimal target:
# it remains the fastest way to separate board/PicoSDL faults from game faults.
set(PICOSDL_BUILD_DEMO ON CACHE BOOL "Build picosdl-demo for board bring-up")
add_subdirectory(${PICOSDL_DIR} picosdl)

add_executable(picowolf-bringup
    main.c
)

target_link_libraries(picowolf-bringup PRIVATE picosdl)
target_compile_definitions(picowolf-bringup PRIVATE PICO_HEAP_SIZE=4096)
set_source_files_properties(main.c PROPERTIES COMPILE_OPTIONS "-Wall;-Wextra")

add_custom_target(picosdl-version ALL
    COMMAND ${CMAKE_COMMAND}
        -DPICOSDL_DIR=${PICOSDL_DIR}
        -DEXPECTED=${PICOSDL_EXPECTED_COMMIT}
        -P ${CMAKE_CURRENT_LIST_DIR}/picosdl_version.cmake
    COMMENT "Checking the PicoSDL revision"
    VERBATIM)

pico_enable_stdio_uart(picowolf-bringup 1)
pico_enable_stdio_usb(picowolf-bringup 1)
pico_add_extra_outputs(picowolf-bringup)

