#include <iostream>

int main() {
    volatile int *ptr = nullptr;
    *ptr = 1337; // Segfault
    return 0;
}
