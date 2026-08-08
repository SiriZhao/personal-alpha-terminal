import sys

from personal_alpha_terminal.cli import main

if __name__ == "__main__":
    sys.argv.insert(1, "daily-pipeline")
    main()
