"""Entry point for the Python sample project."""

from calculator import Calculator


def main():
    calc = Calculator()
    print(f"Sum: {calc.add(2, 3)}")
    print(f"Diff: {calc.subtract(5, 3)}")


if __name__ == "__main__":
    main()
