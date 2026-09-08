import argparse

from collector.youtube.client import YouTubeClient
from collector.channel_registry import add_channel


def verify_channel(channel_id: str) -> dict:
    """
    Verify that a YouTube channel ID exists and return its metadata.
    Does not modify the registry.
    """
    client = YouTubeClient()

    channel = client.get_channel(channel_id)

    if not channel:
        raise ValueError(f"Channel not found: {channel_id}")

    returned_id = channel.get("id")

    if returned_id != channel_id:
        raise ValueError(
            f"Channel ID mismatch. Requested {channel_id}, "
            f"received {returned_id}"
        )

    snippet = channel.get("snippet", {})
    content_details = channel.get("contentDetails", {})
    statistics = channel.get("statistics", {})

    uploads_playlist = (
        content_details
        .get("relatedPlaylists", {})
        .get("uploads")
    )

    return {
        "channel_id": returned_id,
        "title": snippet.get("title"),
        "description": snippet.get("description"),
        "uploads_playlist_id": uploads_playlist,
        "subscriber_count": statistics.get("subscriberCount"),
        "video_count": statistics.get("videoCount"),
        "view_count": statistics.get("viewCount"),
    }


def main():
    parser = argparse.ArgumentParser(
        description="Verify and optionally register a YouTube channel for Stataxis."
    )

    parser.add_argument(
        "--channel-id",
        required=True,
        help="YouTube channel ID to verify",
    )

    parser.add_argument(
        "--name",
        help="Stataxis channel name",
    )

    parser.add_argument(
        "--language",
        help="Channel language, e.g. Hindi, English, Bengali",
    )

    parser.add_argument(
        "--network",
        help="Parent network, e.g. TV Today Network",
    )

    parser.add_argument(
        "--add",
        action="store_true",
        help="Add the verified channel to config/channels.json",
    )

    args = parser.parse_args()

    try:
        result = verify_channel(args.channel_id)

        print()
        print("STAXIS CHANNEL VERIFICATION")
        print("=" * 60)
        print("Status:              VERIFIED")
        print(f"Channel:             {result['title']}")
        print(f"Channel ID:          {result['channel_id']}")
        print(f"Uploads Playlist:    {result['uploads_playlist_id']}")
        print(f"Subscribers:         {result['subscriber_count']}")
        print(f"Videos:              {result['video_count']}")
        print(f"Total Views:         {result['view_count']}")

        if args.add:
            if not args.name:
                raise ValueError(
                    "--name is required when using --add"
                )

            if not args.language:
                raise ValueError(
                    "--language is required when using --add"
                )

            if not args.network:
                raise ValueError(
                    "--network is required when using --add"
                )

            add_channel(
                channel_id=result["channel_id"],
                name=args.name,
                language=args.language,
                network=args.network,
            )

            print()
            print("Registry:            ADDED")
            print(f"Name:                {args.name}")
            print(f"Language:            {args.language}")
            print(f"Network:             {args.network}")

        else:
            print()
            print("Registry:            NOT CHANGED")

        print("=" * 60)
        print()

    except Exception as exc:
        print()
        print("STAXIS CHANNEL VERIFICATION")
        print("=" * 60)
        print("Status:              NOT VERIFIED / NOT ADDED")
        print(f"Reason:              {exc}")
        print("=" * 60)
        print()


if __name__ == "__main__":
    main()