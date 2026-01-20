from .config import settings


def main():
    print("workshop1: ok")
    print("openrouter base:", settings.openrouter_base_url)
    # Don't print tokens; just confirm present/absent:
    print("openrouter key set:", bool(settings.openrouter_api_key))


if __name__ == "__main__":
    main()
