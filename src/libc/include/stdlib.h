/* stdlib.h — bare-metal wrapper for PythonOS.
 *
 * Wraps system stdlib.h and adds POSIX extensions that glibc hides
 * behind _POSIX_C_SOURCE (setenv, unsetenv, mkstemp, etc.).
 */
#pragma once

#include_next <stdlib.h>

#ifndef setenv
int setenv(const char *name, const char *val, int overwrite);
#endif
#ifndef unsetenv
int unsetenv(const char *name);
#endif
#ifndef mkstemp
int mkstemp(char *tmpl);
#endif
