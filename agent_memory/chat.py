"""
CLI entry point — thin loop over agent.process_turn().
Run: python chat.py
"""

import sys

import agent
import knowledge


def main() -> None:
    knowledge.init_memory_dirs()

    print("Agent Memory — Company Knowledge Assistant")
    print("Type 'exit' or 'quit' to end the session.\n")

    while True:
        try:
            query = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye.")
            sys.exit(0)

        if not query:
            continue

        if query.lower() in {"exit", "quit"}:
            print("Goodbye.")
            sys.exit(0)

        try:
            answer = agent.process_turn(query)
        except Exception as e:
            print(f"[error] {e}\n")
            continue

        print(f"\nAssistant: {answer}\n")


if __name__ == "__main__":
    main()
