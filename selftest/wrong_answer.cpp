#include <iostream>

int main() {
    long long a, b;
    if (std::cin >> a >> b) {
        std::cout << a + b + 1 << "\n"; // Incorrect result!
    }
    return 0;
}
