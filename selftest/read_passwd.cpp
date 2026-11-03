#include <iostream>
#include <fstream>
#include <string>

int main() {
    // Malicious attempt to read host system /etc/passwd
    std::ifstream file("/etc/passwd");
    if (file.is_open()) {
        std::string line;
        while (std::getline(file, line)) {
            std::cout << "LEAK_PASSWD: " << line << "\n";
        }
    } else {
        std::cout << "ACCESS_DENIED\n";
    }
    return 0;
}
