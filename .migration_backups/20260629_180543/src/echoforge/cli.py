import argparse

from echoforge.orchestrator import (
    init_project,
    show_status,
    doctor,
    show_workflow,
    run_all_placeholder,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="echoforge",
        description="Clean EchoForge workflow runner",
    )

    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("init", help="Create required runtime folders")
    subparsers.add_parser("status", help="Show project status and paths")
    subparsers.add_parser("doctor", help="Check clean project structure")
    subparsers.add_parser("workflow", help="Show official workflow")
    subparsers.add_parser("all", help="Run full workflow placeholder")

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "init":
        init_project()
    elif args.command == "status":
        show_status()
    elif args.command == "doctor":
        doctor()
    elif args.command == "workflow":
        show_workflow()
    elif args.command == "all":
        run_all_placeholder()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()