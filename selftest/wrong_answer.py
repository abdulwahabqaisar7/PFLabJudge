import sys

def main():
    data = sys.stdin.read().split()
    if len(data) >= 2:
        a = int(data[0])
        b = int(data[1])
        print(a + b + 99) # Incorrect result!

if __name__ == "__main__":
    main()
