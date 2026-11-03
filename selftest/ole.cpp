#include <iostream>
#include <string>

int main() {
    // Generate massive output exceeding output limit (10MB / 1GB)
    std::string chunk(1024 * 64, 'X');
    while (true) {
        std::cout << chunk << "\n";
    }
    return 0;
}
