import sys

def main():
    chunk = "A" * (64 * 1024)
    while True:
        sys.stdout.write(chunk)
        sys.stdout.flush()

if __name__ == "__main__":
    main()
