#include <stdio.h>

int main() {
    volatile int *ptr = NULL;
    *ptr = 42; // Null pointer dereference -> Segfault (SIGSEGV)
    return 0;
}
