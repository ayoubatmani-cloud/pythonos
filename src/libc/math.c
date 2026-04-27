/*
 * math.c — Math functions via x87 FPU and SSE2 instructions.
 *
 * x86-64 has hardware support for most transcendental functions via x87.
 * We use inline asm rather than libm so we stay freestanding.
 *
 * Note: SSE2 is used for basic arithmetic (add/mul/sqrt) since it is
 * faster and mandatory on x86-64. x87 is used only for transcendentals
 * (sin, cos, log2, exp) where hardware instructions exist.
 * Interrupt stubs save/restore the FPU state so this is safe.
 */

#include "include/libc.h"
#include <stdint.h>

// ── Fundamental ops (SSE2) ────────────────────────────────────────────────────

double fabs(double x)  { return __builtin_fabs(x); }
double sqrt(double x)  { return __builtin_sqrt(x); }
double floor(double x) { return __builtin_floor(x); }
double ceil(double x)  { return __builtin_ceil(x); }
double round(double x) { return __builtin_round(x); }

double fmod(double x, double y) {
    double r;
    __asm__ volatile (
        "1: fprem\n\t"
        "fnstsw %%ax\n\t"
        "testb $4, %%ah\n\t"
        "jnz 1b\n\t"
        "fstp %%st(1)"
        : "=t"(r) : "0"(x), "u"(y) : "ax"
    );
    return r;
}

// ── Transcendentals (x87) ─────────────────────────────────────────────────────

double sin(double x) {
    double r;
    __asm__ ("fsin" : "=t"(r) : "0"(x));
    return r;
}

double cos(double x) {
    double r;
    __asm__ ("fcos" : "=t"(r) : "0"(x));
    return r;
}

double tan(double x) {
    double r, one;
    __asm__ ("fptan" : "=t"(one), "=u"(r) : "0"(x));
    (void)one;
    return r;
}

double atan(double x) {
    double r;
    __asm__ ("fld1; fpatan" : "=t"(r) : "0"(x));
    return r;
}

double atan2(double y, double x) {
    double r;
    __asm__ ("fpatan" : "=t"(r) : "0"(x), "u"(y));
    return r;
}

// log2(x) = fyl2x with y=1
double log2(double x) {
    double r;
    __asm__ ("fld1; fxch; fyl2x" : "=t"(r) : "0"(x));
    return r;
}

// log(x) = log2(x) * log(2) = log2(x) * fldln2
double log(double x) {
    double r;
    __asm__ ("fldln2; fxch; fyl2x" : "=t"(r) : "0"(x));
    return r;
}

// log10(x) = log2(x) * log10(2) = log2(x) * fldlg2
double log10(double x) {
    double r;
    __asm__ ("fldlg2; fxch; fyl2x" : "=t"(r) : "0"(x));
    return r;
}

// exp(x) = 2^(x / ln2) = 2^(x * log2(e))
double exp(double x) {
    // fldl2e loads log2(e); then fscale + f2xm1 compute 2^x
    double r, i, f;
    __asm__ ("fldl2e; fmulp" : "=t"(r) : "0"(x));  // r = x * log2(e)
    i = floor(r);
    f = r - i;
    // 2^f - 1 via f2xm1 (valid for -1 <= f <= 1), then add 1 and scale
    __asm__ ("f2xm1" : "=t"(f) : "0"(f));           // f = 2^f - 1
    f += 1.0;
    __asm__ ("fscale; fstp %%st(1)" : "=t"(r) : "0"(f), "u"(i));
    return r;
}

double pow(double x, double y) {
    if (y == 0.0)  return 1.0;
    if (x == 0.0)  return 0.0;
    if (x < 0.0 && y != (long long)y) return NAN;
    int neg = 0;
    if (x < 0.0) { x = -x; neg = (long long)y & 1; }
    double r = exp(y * log(x));
    return neg ? -r : r;
}

double hypot(double x, double y) {
    return sqrt(x * x + y * y);
}

// ── strtod ────────────────────────────────────────────────────────────────────

double strtod(const char *s, char **end) {
    while (isspace(*s)) s++;

    int neg = 0;
    if (*s == '-') { neg = 1; s++; }
    else if (*s == '+') s++;

    // Handle special values
    if (strncasecmp(s, "inf", 3) == 0) {
        if (end) *end = (char *)s + 3;
        if (strncasecmp(s + 3, "inity", 5) == 0 && end) *end = (char *)s + 8;
        return neg ? -INFINITY : INFINITY;
    }
    if (strncasecmp(s, "nan", 3) == 0) {
        if (end) *end = (char *)s + 3;
        return NAN;
    }

    // Hex float: 0x...p...
    int is_hex = 0;
    if (s[0] == '0' && (s[1] == 'x' || s[1] == 'X')) {
        is_hex = 1;
        s += 2;
    }

    double val = 0.0, frac = 0.0, scale = 1.0;
    int has_digits = 0;
    int base = is_hex ? 16 : 10;

    // Integer part
    while (*s) {
        int d;
        if (*s >= '0' && *s <= '9')      d = *s - '0';
        else if (is_hex && *s >= 'a' && *s <= 'f') d = *s - 'a' + 10;
        else if (is_hex && *s >= 'A' && *s <= 'F') d = *s - 'A' + 10;
        else break;
        val = val * base + d;
        has_digits = 1;
        s++;
    }

    // Fractional part
    if (*s == '.') {
        s++;
        while (*s) {
            int d;
            if (*s >= '0' && *s <= '9')      d = *s - '0';
            else if (is_hex && *s >= 'a' && *s <= 'f') d = *s - 'a' + 10;
            else if (is_hex && *s >= 'A' && *s <= 'F') d = *s - 'A' + 10;
            else break;
            scale /= base;
            frac += d * scale;
            has_digits = 1;
            s++;
        }
    }

    val += frac;
    if (!has_digits) { if (end) *end = (char *)s; return 0.0; }

    // Exponent
    if ((!is_hex && (*s == 'e' || *s == 'E')) ||
        ( is_hex && (*s == 'p' || *s == 'P'))) {
        s++;
        int eneg = 0;
        if (*s == '-') { eneg = 1; s++; }
        else if (*s == '+') s++;
        long exp_val = 0;
        while (*s >= '0' && *s <= '9') exp_val = exp_val * 10 + (*s++ - '0');
        double mult = is_hex ? exp(exp_val * 0.693147180559945) /* 2^n */
                             : pow(10.0, (double)exp_val);
        val = eneg ? val / mult : val * mult;
    }

    if (end) *end = (char *)s;
    return neg ? -val : val;
}

float strtof(const char *s, char **end) {
    return (float)strtod(s, end);
}

// ── Misc ──────────────────────────────────────────────────────────────────────

double ldexp(double x, int exp) {
    double r;
    double e = (double)exp;
    __asm__ ("fscale; fstp %%st(1)" : "=t"(r) : "0"(x), "u"(e));
    return r;
}

double frexp(double x, int *exp) {
    if (x == 0.0) { *exp = 0; return 0.0; }
    int e = (int)floor(log2(fabs(x))) + 1;
    *exp = e;
    return x / ldexp(1.0, e);
}

double modf(double x, double *ipart) {
    *ipart = x >= 0 ? floor(x) : ceil(x);
    return x - *ipart;
}

double copysign(double x, double y) {
    return (y < 0) ? -fabs(x) : fabs(x);
}

double nextafter(double x, double y) {
    if (x == y) return y;
    union { double d; uint64_t u; } u = {x};
    if (x == 0.0) { u.u = 1; return (y > 0) ? u.d : -u.d; }
    if ((x < y) == (x > 0)) u.u++; else u.u--;
    return u.d;
}

double tgamma(double x) {
    // Lanczos approximation (g=7, n=9)
    static const double c[] = {
        0.99999999999980993, 676.5203681218851, -1259.1392167224028,
        771.32342877765313, -176.61502916214059, 12.507343278686905,
        -0.13857109526572012, 9.9843695780195716e-6, 1.5056327351493116e-7
    };
    if (x < 0.5) return 3.14159265358979323846 / (sin(3.14159265358979323846 * x) * tgamma(1 - x));
    x -= 1;
    double a = c[0];
    double t = x + 7.5;
    for (int i = 1; i < 9; i++) a += c[i] / (x + i);
    return sqrt(2 * 3.14159265358979323846) * pow(t, x + 0.5) * exp(-t) * a;
}

double lgamma(double x) { return log(fabs(tgamma(x))); }

double erf(double x) {
    // Abramowitz & Stegun 7.1.26 approximation
    double t = 1.0 / (1.0 + 0.3275911 * fabs(x));
    double y = 1.0 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t
                        - 0.284496736) * t + 0.254829592) * t * exp(-x * x);
    return (x >= 0) ? y : -y;
}

double erfc(double x) { return 1.0 - erf(x); }

double asin(double x) { return atan2(x, sqrt(1 - x * x)); }
double acos(double x) { return atan2(sqrt(1 - x * x), x); }
double sinh(double x) { return (exp(x) - exp(-x)) / 2; }
double cosh(double x) { return (exp(x) + exp(-x)) / 2; }
double tanh(double x) { double e = exp(2 * x); return (e - 1) / (e + 1); }

// ── Additional transcendentals required by CPython ────────────────────────────

// expm1(x) = e^x - 1; use Taylor series near 0 to preserve precision
double expm1(double x) {
    if (fabs(x) < 1e-5)
        return x + x*x/2.0 + x*x*x/6.0 + x*x*x*x/24.0;
    return exp(x) - 1.0;
}

// log1p(x) = log(1+x); use series near 0
double log1p(double x) {
    if (fabs(x) < 1e-5)
        return x - x*x/2.0 + x*x*x/3.0 - x*x*x*x/4.0;
    return log(1.0 + x);
}

// cbrt(x) = x^(1/3), sign-aware
double cbrt(double x) {
    if (x == 0.0) return 0.0;
    double r = pow(fabs(x), 1.0 / 3.0);
    return x < 0.0 ? -r : r;
}

double acosh(double x) { return log(x + sqrt(x*x - 1.0)); }
double asinh(double x) { return log(x + sqrt(x*x + 1.0)); }
double atanh(double x) { return 0.5 * log((1.0 + x) / (1.0 - x)); }

// exp2(x) = 2^x using x87 f2xm1 + fscale
double exp2(double x) {
    double i = floor(x), f = x - i;
    double r;
    __asm__ ("f2xm1" : "=t"(f) : "0"(f));
    f += 1.0;
    __asm__ ("fscale; fstp %%st(1)" : "=t"(r) : "0"(f), "u"(i));
    return r;
}

double fma(double x, double y, double z) { return __builtin_fma(x, y, z); }

// trunc: toward-zero rounding
double trunc(double x) { return x >= 0 ? floor(x) : ceil(x); }
