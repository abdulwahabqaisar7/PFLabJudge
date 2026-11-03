#include <iostream>
#include <vector>
#include <cstring>

int main() {
    // Attempt to allocate 2 GB (2048 MB) and touch each page to force physical commit
    std::vector<char*> blocks;
    try {
        for (int i = 0; i < 2048; ++i) {
            char* ptr = new char[1024 * 1024]; // 1 MB
            std::memset(ptr, 1, 1024 * 1024);
            blocks.push_back(ptr);
        }
        std::cout << "Allocated " << blocks.size() << " MB successfully\n";
    } catch (const std::bad_alloc& e) {
        std::cerr << "std::bad_alloc caught: " << e.what() << "\n";
        return 1;
    }
    return 0;
}
