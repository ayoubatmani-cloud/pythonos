#ifndef PYTHONOS_BOOT_TLS_H
#define PYTHONOS_BOOT_TLS_H

#include <stddef.h>
#include <stdint.h>

#define PYTHONOS_TLS_AREA_SIZE 512U

int tls_init_area(uint8_t *area, size_t area_size);

#endif
