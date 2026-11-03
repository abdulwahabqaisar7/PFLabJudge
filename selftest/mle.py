import sys

def main():
    # Attempt to allocate 2 GB
    chunks = []
    for _ in range(2048):
        chunks.append(bytearray(1024 * 1024))
    print(f"Allocated {len(chunks)} MB")

if __name__ == "__main__":
    main()
