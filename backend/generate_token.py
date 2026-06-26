from services.auth import STATIC_TOKEN_MINUTES, create_access_token


def main() -> None:
    token = create_access_token(subject="frontend", expires_minutes=STATIC_TOKEN_MINUTES)
    print(token)


if __name__ == "__main__":
    main()
