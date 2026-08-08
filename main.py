"""Windows-friendly terminal entry point; it never starts a browser or Streamlit."""

from personal_alpha_terminal.terminal.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
