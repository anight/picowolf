#
# Is PicoSDL the revision this firmware was last built and flashed against?
#
# picosdl is a dependency with its own history, and picowolf's copy of it is a
# symlink into a checkout shared with another project.  That is convenient
# while both are being worked on and it is also how the bring-up target came to
# be broken for five days: SDL_CreateWindow() was removed on the other side of
# the link, nothing here noticed, and the next build failed with errors that
# said nothing about why.
#
# So this runs on every build and says so.  It is a warning rather than an
# error because bumping PicoSDL deliberately is a normal thing to do - the
# answer is usually to fix the two lines and move the expected revision on.
#
if(NOT EXISTS "${PICOSDL_DIR}")
    return()
endif()

find_package(Git QUIET)

if(NOT GIT_FOUND)
    return()
endif()

execute_process(
    COMMAND ${GIT_EXECUTABLE} -C "${PICOSDL_DIR}" rev-parse HEAD
    OUTPUT_VARIABLE PICOSDL_ACTUAL
    OUTPUT_STRIP_TRAILING_WHITESPACE
    ERROR_QUIET
    RESULT_VARIABLE PICOSDL_RC)

if(NOT PICOSDL_RC EQUAL 0)
    return()
endif()

if(NOT PICOSDL_ACTUAL STREQUAL EXPECTED)
    string(SUBSTRING "${PICOSDL_ACTUAL}" 0 12 ACTUAL_SHORT)
    string(SUBSTRING "${EXPECTED}" 0 12 EXPECTED_SHORT)

    execute_process(
        COMMAND ${GIT_EXECUTABLE} -C "${PICOSDL_DIR}" log --oneline
                "${EXPECTED}..${PICOSDL_ACTUAL}"
        OUTPUT_VARIABLE PICOSDL_SINCE
        OUTPUT_STRIP_TRAILING_WHITESPACE
        ERROR_QUIET)

    message(WARNING
        "PicoSDL is at ${ACTUAL_SHORT}, not the ${EXPECTED_SHORT} this was "
        "built against.\n"
        "If the build fails below, that is where to look.  Once it builds "
        "again, move PICOSDL_EXPECTED_COMMIT in src/CMakeLists.txt on.\n"
        "${PICOSDL_SINCE}")
endif()
