"""Small console-formatting helpers shared by client commands."""


def heading(title: str) -> None:
    print("\n" + "=" * 68)
    print(title)
    print("=" * 68)
