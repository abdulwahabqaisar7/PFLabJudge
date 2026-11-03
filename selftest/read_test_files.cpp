#include <iostream>
#include <fstream>
#include <filesystem>

int main() {
    // Malicious attempt to inspect parent directory and read other test cases
    try {
        for (const auto& entry : std::filesystem::directory_iterator("..")) {
            std::cout << "FOUND_FILE: " << entry.path() << "\n";
        }
    } catch (...) {
        std::cout << "ACCESS_DENIED\n";
    }
    return 0;
}
